# RSI v2 — 기존 RSI 신호에 SL 추가

## 변경 범위

v1의 RSI 계산·진입·종료·반대 방향 전환을 그대로 재사용한다.
v2 전략 클래스는 v1을 상속하며 매매 신호를 복사하거나 별도로 변경하지 않는다.
고정 SL의 감시·체결·수수료·슬리피지는 공통 엔진이 v2 전용 정책으로 처리한다.
v2에는 TP와 손절 후 재진입 제한을 추가하지 않았다. TP는 별도 v3에 구현했으며 v4는 placeholder다.

## 설정과 실행

```yaml
strategy_id: rsi
strategy_version: v2
stop_loss_pct: "2"
take_profit_pct: null
```

SL은 **실제 진입 체결 가격 대비 2%**이며 계좌 손실률이나 증거금 ROI 기준이 아니다.
Long은 진입가 × 0.98, Short는 진입가 × 1.02다. 고정 가격이므로 추적 손절이 아니다.
v2에서 SL 누락, 0 이하/100 이상/비유한 값, TP 설정은 실행 전에 거부한다.
SL 체결에는 불리한 슬리피지와 청산 수수료가 추가되므로 실제 손실은 설정 비율과 다를 수 있다.
여기서 청산 수수료는 일반 포지션 종료 수수료이며, 강제 청산 때만 별도 liquidation fee가 더해진다.

파일명에 v2를 넣은 완전한 YAML 세 개를 준비했다. SL 2%는 비교용 시작값이며 최적화한 값이 아니다.
모두 BTC USDT 무기한 선물, 1h, 1배, 자금 배분 100%, 초기 자금 1000 USDT,
RSI 14/38/70, 편도 수수료 0.05%, 슬리피지 5bps, assume_zero 펀딩을 사용한다.
분석 구간은 2024-01-01 14:00 ~ 2026-10-31 18:00 UTC(종료 제외), 이전 14개 봉은 준비용이다.

```powershell
trading-lab backtest run --config config/rsi/v2/future/long_only/BTC_USDT_USDT/1h/1x/rsi_v2_btc_perpetual_1h_1x_long_only_sl2.yaml
trading-lab backtest run --config config/rsi/v2/future/short_only/BTC_USDT_USDT/1h/1x/rsi_v2_btc_perpetual_1h_1x_short_only_sl2.yaml
trading-lab backtest run --config config/rsi/v2/future/long_short/BTC_USDT_USDT/1h/1x/rsi_v2_btc_perpetual_1h_1x_long_short_sl2.yaml
```

현물도 v2를 사용할 수 있으나 별도 현물 설정을 준비해야 한다.
새 보고서는 reports/rsi/v2/future/<direction>/BTC_USDT_USDT/1h/1x/<UTC interval>/에 저장한다.
v2부터 마지막 결과 폴더명은 기간과 실험 조건을 함께 표시한다.

```text
2024-01-01T1400Z-2026-10-31T1800Z-SL2-TPnone-P14-L38-U70/
```

시각은 UTC이며 종료 제외다. SL2는 가격 기준 손절 2%, TPnone은 TP 미설정,
P14/L38/U70은 RSI period/lower/upper다. 소수 값도 보존하며 2.00은 2로 표시한다.
동일 조건 재출력은 짧은 식별자를 붙여 보존한다. 기존 폴더는 이동하거나 이름을 바꾸지 않는다.
v3/v4도 같은 명명 규칙을 사용하고 v1은 기존 기간만의 이름을 유지한다.
실제 적용한 파라미터 기록이 있으면 이를 우선 사용하고, 과거 기록에 없는 값은 unknown으로 표시한다.
버전과 SL 값은 result.json, manifest, Excel Parameters에 남는다.
파일명만 바꾸어도 실제 버전은 바뀌지 않으며 YAML의 strategy_version이 선택 기준이다.

## SL·강제 청산 체결 순서

- 기존 v1의 위험 처리 순서는 유지한다.
- v2에서 이전 봉부터 보유한 포지션은 시가 갭을 먼저 검사하고, 그다음 이전 봉의 RSI 주문을 실행한다.
  시가가 강제 청산 경계를 넘으면 강제 청산, SL만 넘으면 시가로 손절한다. 건너뛴 SL 가격에 체결시키지 않는다.
- 시가가 두 경계 안쪽이면 연속적인 불리한 가격 이동을 가정해 더 가까운 SL/강제 청산 경계를 먼저 처리한다.
  같은 경계이면 강제 청산으로 보수적으로 처리한다. SL을 강제 청산가보다 멀리 두면 청산이 먼저 가능하다.
- 시가 갭 종료 시각은 봉 시작이며, 봉 내부 종료 시각은 봉 종료로 근사한다.
- 1h OHLC만으로 봉 내부 점프를 알 수 없으므로 SL 체결 가격을 보장하는 모형은 아니다.
  펀딩의 봉 내부 처리와 과거 mark price/증거금 구간별 청산 근사도 기존 한계로 남는다.

SL로 종료해도 같은 봉 종가의 RSI가 진입 조건이면 다음 봉 시가에 재진입할 수 있다.
시가 갭 손절 후 기존 예약 주문이 진입을 지시한 경우에는 같은 시가에 새 포지션을 열 수도 있다.
이는 재진입 제한을 넣기 전 v2의 의도된 동작이며, v4에서 별도로 비교할 예정이다.

## 비교 방법

먼저 같은 조건의 v1 1배 Long/Short와 v2 1배 Long/Short를 비교한다.
수익률·최대 낙폭·평균 손실·거래 수·수수료와 Trades의 exit_reason=stop_loss/liquidation/reversal/signal을 확인한다.
SL로 인해 거래 수와 비용이 증가할 수 있다. 이 구현 자체가 수익 개선을 뜻하지 않는다.
공통 엔진 식별자는 ohlcv-isolated-v3-protective-sl로 갱신했으며 기존 결과를 덮어쓰지 않는다.

## 첫 전체 기간 실행 결과

1배 Long/Short, SL 2% 설정을 기존 v1과 같은 데이터·비용으로 실행했다.
v1 재실행의 최종 자산 717.512267714889 USDT는 이전 사용자 결과와 일치했다.

| 항목 | v1 | v2 (SL 2%) |
|---|---:|---:|
| 최종 자산 (USDT) | 717.51 | 236.95 |
| 총수익률 | −28.25% | −76.31% |
| 최대 낙폭 | 54.84% | 82.39% |
| 완료 거래 | 278 | 723 |
| 총수수료 (USDT) | 243.72 | 354.44 |
| Profit Factor | 0.926 | 0.847 |

v2 종료 사유는 SL 461건, RSI 반대 방향 전환 261건, 기간 종료 1건이다.
이 설정에서 SL 추가는 성과를 개선하지 못했다. 재진입을 허용한 상태에서 거래 수와 비용도 증가했다.
재진입 제한이 개선을 보장한다는 뜻은 아니며, v3/v4를 별도로 검증하기 위한 기준 결과로 보존한다.
v2 run_id: `8bbc143e-b49f-42de-947f-4e60a5f134d0`.
