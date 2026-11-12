# RSI v3 — RSI 종료·전환 + SL + TP

## 변경 내용

v1의 RSI 계산과 신호를 상속해 그대로 사용하고 v2의 SL 정책에 TP를 추가한다.
RSI 반대 신호에 따른 종료·전환도 계속 동작한다. TP·SL만으로 종료하는 전략은 아니다.
가격 감시와 체결은 엔진이 담당하며, 재진입 제한은 아직 없다(v4 예정).
v1·v2의 위험 처리 정책은 유지한다.

## 첫 비교 설정

직전 v2 SL 10% 결과와 비교할 수 있도록 나머지 입력은 유지하고 TP 20%만 추가했다.
SL 10%와 TP 20%는 진입 체결 가격 대비 비율이며 최적화하거나 성과를 확인해 선택한 값이 아니다.

```yaml
strategy_id: rsi
strategy_version: v3
stop_loss_pct: "10"
take_profit_pct: "20"
```

Long 진입가가 100이면 SL 90, TP 120이고 Short는 SL 110, TP 80이다.
TP가 SL의 두 배라도 RSI 조기 종료·비용·갭 때문에 실제 평균 손익비가 2가 되는 것은 아니다.
v3에서 SL 또는 TP 누락, 0 이하/100 이상/비유한 값은 실행 전에 거부한다.

공통 입력은 Binance BTC USDT 무기한 선물, 1h, 1배, 자금 배분 100%, 초기 자금 1000 USDT,
RSI 14/38/70, 편도 수수료 0.05%, 슬리피지 5bps, assume_zero 펀딩이다.
기간은 2024-01-01 14:00 ~ 2026-10-31 18:00 UTC(종료 제외), 이전 14개 봉은 준비용이다.

## 실행

backend에서 실행한다. 우선 Long/Short를 v2 SL 10%와 비교한다.

```powershell
$configPath = "config/rsi/v3/future/long_short/BTC_USDT_USDT/1h/1x/rsi_v3_btc_perpetual_1h_1x_long_short_sl10_tp20.yaml"
trading-lab backtest run --config "$configPath"
```

Long only와 Short only도 같은 계층의 방향별 폴더에 각각 설정했다.
결과는 reports/rsi/v3/future/<direction>/BTC_USDT_USDT/1h/1x/ 아래에 생성한다.

```text
2024-01-01T1400Z-2026-10-31T1800Z-SL10-TP20-P14-L38-U70/
```

## 체결 가정

1. 이전 봉부터 보유한 포지션은 시가 갭의 강제 청산·SL·TP를 예약된 RSI 주문보다 먼저 처리한다.
2. 불리한 갭에서는 청산 경계를 넘으면 강제 청산, SL만 넘으면 시가 손절이다.
3. 유리한 갭에서 이미 TP를 넘었다면 시가에 TP 종료한다. 나중에 같은 봉의 저가/고가가 SL을
   건드렸더라도 이미 알고 있는 시가 TP를 무시하지 않는다.
4. 시가가 모든 경계 안에 있고 같은 봉에서 유리·불리 양쪽을 모두 건드리면, 순서를 알 수 없으므로
   불리한 SL/강제 청산을 우선한다. 두 불리한 경계 중에는 v2처럼 더 가까운 경계를 먼저 처리한다.
5. TP만 도달한 봉에서는 목표 가격으로 종료한다. 모든 종료에는 일반 수수료와 불리한 슬리피지가 적용된다.

TP는 지정가 주문의 대기열·maker 체결 모형이 아니라 가격 트리거 후 시장가 종료의 근사다.
시가 갭 종료 시각은 봉 시작, 봉 내부 종료 시각은 봉 종료로 기록한다.
OHLC만으로 봉 내부 점프·실제 체결 순서를 알 수 없으며, 펀딩·청산의 기존 근사도 남아 있다.
TP/SL 종료 뒤 RSI 조건이 유지되면 다음 봉에 재진입할 수 있고, 시가 종료 뒤 예약 주문으로
같은 시가에 새 포지션을 열 수도 있다. 이 재진입 규칙은 v2와 동일하다.

## 비교 기준

같은 방향·기간·배율의 v2 SL 10%를 기준으로 수익률, 최대 낙폭, 평균 손익, 거래 수, 수수료,
profit factor와 Trades의 take_profit/stop_loss/reversal/signal/end_of_test 건수를 확인한다.
TP가 드물게 발생하면 기존 RSI 종료가 먼저 발생했을 수 있으므로 이를 오류로 단정하지 않는다.
v3의 성과 개선 여부는 실제 실행 결과로 판단한다. 공통 엔진 식별자는
ohlcv-isolated-v4-protective-tpsl이며 전략 버전 v4(미구현)와는 별개의 식별자다.
