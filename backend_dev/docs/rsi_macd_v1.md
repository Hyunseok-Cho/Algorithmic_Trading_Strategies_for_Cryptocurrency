# RSI+MACD v1 — MACD 방향 필터와 RSI 진입·종료

## 확정한 규칙

MACD는 개발 폴더의 MACD 계산기를 사용한다.
RSI는 trading_lab.strategies.RSI_MACD.indicators.WilderRSI를 import하며 중복 구현하지 않았다.
기존 backend/src, 원래 레지스트리 및 실행 중인 RSI 배치의 소스는 수정하지 않는다.

```text
MACD > Signal AND RSI < 38 → Long 진입 허용
MACD < Signal AND RSI > 70 → Short 진입 허용
```

MACD는 교차 순간이 아닌 **현재의 MACD–Signal 관계**를 확인한다.
이는 Histogram 부호와 같지만 MACD line 자체의 부호와는 다르다.
두 조건은 같은 완료 봉에서 충족되어야 하며, 신호는 다음 봉 시가에 체결한다.
정확히 MACD=Signal이면 신규 방향을 허용하지 않고 RSI=38 또는 70에서는 진입·청산하지 않는다.

| 상태 | 조건 | 처리 |
|---|---|---|
| Flat | 상승 MACD 필터 + RSI < lower | Long 진입 (허용 방향일 때만) |
| Flat | 하락 MACD 필터 + RSI > upper | Short 진입 (현물에서는 진입 안 함) |
| Long | RSI > upper | MACD와 무관하게 청산 |
| Long | RSI > upper + 하락 MACD 필터 | Long/Short 설정이면 Short로 전환 |
| Short | RSI < lower | MACD와 무관하게 청산 |
| Short | RSI < lower + 상승 MACD 필터 | Long/Short 설정이면 Long으로 전환 |
| 보유 중 | MACD 방향만 변경 | 보유 유지 |

현물 하락 방향 신호는 보유분 청산이며 Short를 열지 않는다.
TP·SL·시간 제한 종료·재진입 잠금·동시 양방향 보유는 넣지 않았다.
반대 RSI 기준까지 기다리는 동안 손실 제한은 없으며, 선물의 모형상 강제 청산은 적용된다.

## 논문과의 관계

사용자가 제공한 논문 3쪽 IV.B는 RSI > 30, MACD > Signal,
현재 RSI > 이전 RSI를 매수 조건으로 설명하고 종료에 ATR20과 이전 종가를 사용한다고 적는다.
따라서 MACD 방향과 RSI를 함께 사용한다는 관점은 유사하지만,
이번 구현의 RSI < 38 Long / RSI > 70 Short, 반대 RSI 종료 및 선물 대칭 확장은 별도의 사용자 정의 규칙이다.
RSI 상승 조건과 ATR 종료를 추가하지 않았으며 논문 재현 전략이라고 표기하지 않는다.

## 설정·실행

BTC 1h, MACD 12/26/9, Wilder RSI 14/38/70, 준비 34봉, 초기 자금 1000 USDT, 배분 100%다.
분석은 2024-01-02 00:00 ~ 2026-11-01 00:00 UTC(종료 제외)로 MACD 단독 실험과 같다.
현물 1배 1개, 선물 Long/Short 2~5배 4개 YAML이 있다.
수수료·슬리피지·펀딩과 청산 근사는 해당 배율의 기존 MACD v1과 동일하다.
RSI 단독 결과와 비교할 때도 분석 기간과 비용을 맞춰야 한다.

backend_dev에서 실행한다.

```powershell
# 현물 단건
python run_backtest.py --config config/rsi_macd/v1/spot/BTC_USDT/1h/1x/rsi_macd_v1_btc_spot_1h.yaml

# 선물 2배 단건
python run_backtest.py --config config/rsi_macd/v1/future/long_short/BTC_USDT_USDT/1h/2x/rsi_macd_v1_btc_future_1h_2x.yaml

# 5개 전체 실행 또는 재개
python run_all.py --strategy rsi_macd --version v1
```

기존 개발 실행 파일과 원래 엔진에 전략 객체를 직접 전달한다. DB에서는 가격/펀딩을 읽기만 한다.
보고서는 reports/rsi_macd/v1/ 아래에 시장·방향·심볼·타임프레임·배율별로 저장한다.
결과 폴더명에는 기간·RSI·MACD 파라미터가 표시된다. 전체 비교표는
reports/batches/rsi_macd_v1/summary.csv, 재개 기록은 같은 폴더의 state.json에 저장한다.
출력 권한은 Windows 상위 폴더에서 상속하도록 처리한다.

## 첫 실행 결과

5개 모두 성공했으며 각 보고서의 manifest 파일 해시를 검증했다.

| 시장·배율 | 총수익률 | 최대 낙폭 | 완료 거래 | 강제 청산 |
|---|---:|---:|---:|---:|
| 현물 1배 | +30.27% | 39.85% | 70 | 0 |
| 선물 2배 | −52.83% | 76.67% | 93 | 0 |
| 선물 3배 | −99.39% | 99.73% | 94 | 1 |
| 선물 4배 | 약 −100% | 약 100% | 94 | 3 |
| 선물 5배 | 약 −100% | 약 100% | 97 | 7 |

같은 기간 MACD 단독 현물 v1의 947건·수수료 778.44 USDT에 비해 결합 v1은 70건·182.10 USDT였다.
현물 최종 자산은 1302.75 USDT, Profit Factor는 약 1.205였으나 단순 보유 수익률 +75.08%에는 못 미쳤다.
필터가 거래 흐름을 크게 바꾼 것은 확인됐지만 단일 기간·자산에서의 결과이며 안정적 우위는 입증하지 않았다.
선물 2배는 Long 69건·Short 24건이었고 누적 손실이 남았다.
RSI 단독과 비교할 때에는 시작일이 다른 기존 결과를 그대로 비교하지 않고 동일한 분석 범위로 맞춘다.
