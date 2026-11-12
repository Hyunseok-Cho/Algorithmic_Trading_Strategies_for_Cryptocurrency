# 사용자 정의 RSI 단독 전략

이 전략은 논문의 결합 전략을 그대로 복제하지 않는다. 사용자가 정한 RSI 밴드 규칙을 구현한다.
현재 RSI만 활성화돼 있으며 MACD와 결합 전략의 상세 규칙은 별도 확정 후 구현한다.

## 시장과 주문을 나누는 방식

지표 계산에는 spot/futures 조건문을 넣지 않는다. 동일한 WilderRSI를 재사용한다.
전략은 방향을 판단하고 `direction_mode` 정책이 허용된 포지션 목표로 변환한다.
엔진은 시장에 따라 현물 inventory 또는 선물 margin/PnL을 계산한다.

| RSI | 현물 / long_only | 선물 / long_short | 선물 / short_only |
|---|---|---|---|
| `< lower` (기본 38) | Long 진입/유지 | Long 목표, 기존 Short면 전환 | Short 청산 후 flat |
| `> upper` (기본 70) | Long 청산 후 flat | Short 목표, 기존 Long이면 전환 | Short 진입/유지 |
| 그 외, 정확히 38/70 포함 | 기존 상태 유지 | 기존 상태 유지 | 기존 상태 유지 |

이것은 **상태 조건**이며 임계값 교차 순간만 진입하는 전략이 아니다. 포지션이 없는 상태에서도
이미 RSI가 임계값 밖이면 신호를 낸다. 같은 방향 목표가 반복돼도 피라미딩·추가 주문은 없다.
선택적 stop/target이 포지션을 종료했다면 밴드 조건이 지속되는 동안 다음 봉에 다시 진입할 수 있다.
cooldown이나 재교차 조건을 원하면 별도 연구 변경으로 명시해야 한다.

Long은 buy로 진입하고 sell로 청산한다. Short는 sell로 진입하고 buy로 청산한다.
one_way는 한 방향 포지션만 보유한다는 뜻이며 방향 전환은 가능하다. hedge의 동시 롱/숏 보유와 다르다.
`TARGET_LONG/SHORT`가 반대 포지션을 발견하면 **다음 봉 시가**에서 기존 포지션을 먼저 전량 종료하고
같은 시가를 기준으로 반대 포지션에 진입한다. 두 leg는 각각 수수료·불리한 슬리피지를 적용하며
청산 후 자본으로 allocation을 다시 계산한다. 자본이 부족하면 반대 진입은 성립하지 않을 수 있다.
기존 `OPEN_LONG/SHORT`의 '보유 중 추가 진입 무시' 의미는 유지한다.

## RSI 계산

- 기본 period=14이며 **14개 봉의 가격 변화**를 뜻한다. 1h에서 14일을 의미하지 않는다.
- 최초 N개 종가 변화의 상승분·하락분을 각각 SMA로 초기화한다.
- 그다음에는 `avg = (previous_avg * (N-1) + current_gain_or_loss) / N`으로 Wilder smoothing을 한다.
- `RSI = 100 * avg_gain / (avg_gain + avg_loss)`를 사용한다. 일반 RSI 식과 동치다.
- N+1개 종가가 첫 유효 RSI를 만든다. 상승만 있으면 100, 하락만 있으면 0이다.
  상승/하락이 모두 0인 완전한 flat 구간은 **프로젝트의 명시적 중립 규칙으로 50**을 사용한다.
- Decimal과 50자리 계산 context를 사용하고 결정을 내리기 전에 지표를 표시용으로 반올림하지 않는다.
- period는 2~10000의 정수, `0 < lower < upper < 100`이며 알 수 없는 파라미터는 거부한다.
- `warmup_bars >= period`가 필요하다. 앞선 warmup 봉을 읽되 해당 기간에는 주문하지 않는다.
  첫 분석 봉의 종가를 본 후 낸 신호도 다음 봉 시가에만 체결한다.
- smoothing seed의 시작점은 결과에 영향을 줄 수 있다. 비교 실험은 데이터 시작과 warmup을 고정해야 한다.
  기본 14 warmup은 최소 준비값이며 어떤 시장에서도 충분한 수렴을 보증하는 수치는 아니다.

계산/관례 참고: [Fidelity RSI](https://www.fidelity.com/learning-center/trading-investing/technical-analysis/technical-indicator-guide/RSI),
[TA-Lib RSI 구현](https://github.com/TA-Lib/ta-lib/blob/main/src/ta_func/ta_RSI.c).
TA-Lib과 모든 seed·flat·호환 모드가 동일하다고 주장하지 않는다.

## 실행

현물 설정 `config/examples/btc_spot_1h.yaml`:

```yaml
strategy_id: rsi
strategy_parameters:
  period: 14
  lower: "38"
  upper: "70"
warmup_bars: 14
```

```powershell
trading-lab backtest run --config config/examples/btc_spot_1h.yaml
```

예시는 이미 수집한 2021-01-01~03의 48개 봉 중 첫 14개를 warmup으로 쓰고,
`[2021-01-01T14:00Z, 2021-01-03T00:00Z)`의 34개 봉을 분석한다.
수수료와 슬리피지는 기존 예시의 연구 가정이며 Binance의 실제 역사적 요율로 검증한 값은 아니다.

선물의 방향 전환에는 `market_type=perpetual`, `symbol=BTC/USDT:USDT`,
`direction_mode=long_short`, `position_mode=one_way`를 사용한다. 선물 가격·펀딩을 별도로 저장해야 하며
strict funding의 검증된 이벤트 목록·출처·mark price 요구는 그대로 적용된다. hedge 실행은 아직 지원하지 않는다.

## 이번 검증

- Wilder seed의 손계산 기준값과 후속 재귀값, 상승/하락/flat, 파라미터·임계 경계 검증.
- spot / long_only / short_only / long_short의 방향 정책, 미래 접근 금지, warmup 검증.
- Long→Short와 Short→Long을 다음 시가에서 전환하고 두 leg의 비용·펀딩 소속을 검증.
- 같은 방향 목표의 반복은 추가 매매하지 않음을 검증.
- 기본 전체 테스트 **337 passed, 3 deselected**. PostgreSQL 통합 테스트 3개는 이번에 실행하지 않았다.
- 실제 DB에 저장된 현물 48개 봉으로 RSI 실행·run 저장·Excel/CSV/JSON 생성·DB 결과 재출력 성공.
  run ID: `1126d2e4-f41c-4e28-84c0-612e32e59119`.
- 분석 RSI: 최솟값 약 49.2465, 최댓값 약 86.4692, `<38` 0회, `>70` 8회.
  현물은 최초 flat이고 진입 조건이 없어 **완결 거래 0건·최종 자본 1000**이다.
  이 결과는 짧은 구간의 기능 확인이며 전략의 우열이나 미래 수익성을 뜻하지 않는다.

## 다음 비교 단계

RSI 테스트 → MACD 규칙 확정/구현/테스트 → 결합 규칙 확정/구현/테스트 → 동일 실험 조건에서 비교한다.
시장·심볼·분석 start/end·데이터 snapshot·초기자본·allocation·레버리지·비용·청산 정책을 고정한다.
지표별 최소 history는 달라도 **분석 구간은 같아야 하며**, 충분한 공통 warmup을 정하는 편이 비교하기 쉽다.
개발 점검의 이틀치 결과와 교수님께 전달할 성과 실험은 구분한다. 성과 실험의 기간·비용과 파라미터는
결과를 본 뒤 유리하게 바꾸지 않고 먼저 명세로 확정한다. 변경하면 별도 실험으로 기록한다.
