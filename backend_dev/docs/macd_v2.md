# MACD v2 — 교차 신호 + 가격 기준 SL

기존 MACD v1의 Histogram 교차 진입·종료·전환을 상속해 유지하고 고정 SL을 추가했다.
TP와 손절 후 재진입 잠금은 없다. 상태 조건 RSI와 달리 MACD는 새로운 교차에서만 주문을 요청하므로
손절 후 Histogram이 같은 부호라는 이유만으로 즉시 같은 방향 재진입하지는 않는다.
새 교차가 발생하면 다시 진입하며, 시가 갭 종료와 기존 예약 교차 주문이 겹치면 같은 시가에 진입할 수도 있다.

## YAML 45개

| 시장·방향 | 배율 | SL | 개수 |
|---|---|---|---:|
| 현물 Long only | 1배 | 2~10%, 1% 간격 | 9 |
| 선물 Long/Short | 2·3·4·5배 | 각각 2~10%, 1% 간격 | 36 |
| 합계 | | | 45 |

SL만 제외하면 해당 배율의 v1 YAML과 동일하다. BTC 1h, MACD 12/26/9, 준비 34봉,
초기 자금 1000 USDT, 배분 100%, 분석 2024-01-02 00:00 ~ 2026-11-01 00:00 UTC(종료 제외)다.
SL은 증거금 ROI나 계좌 손실률이 아니라 **실제 진입 가격 대비 비율**이다.
예를 들어 SL5에서 Long 진입가 100이면 95, Short이면 105가 손절 기준이다.
이는 고정 손절이며 추적 손절이 아니다. 갭과 종료 비용 때문에 정확히 해당 손실률을 보장하지 않는다.

```text
config/macd/v2/
├── spot/BTC_USDT/1h/1x/macd_v2_btc_spot_1h_sl2.yaml ... sl10.yaml
└── future/long_short/BTC_USDT_USDT/1h/<2x|3x|4x|5x>/
    └── macd_v2_btc_future_1h_<leverage>x_sl2.yaml ... sl10.yaml
```

## 실행 (backend_dev에서)

```powershell
# 현물 SL 5% 단건
python run_backtest.py --config config/macd/v2/spot/BTC_USDT/1h/1x/macd_v2_btc_spot_1h_sl5.yaml

# 선물 2배 SL 5% 단건
python run_backtest.py --config config/macd/v2/future/long_short/BTC_USDT_USDT/1h/2x/macd_v2_btc_future_1h_2x_sl5.yaml

# 45개 전체 순차 실행. 기존 보고서는 보존되지만 이 루프에는 재개/건너뛰기 기능이 없다.
$configs = Get-ChildItem -LiteralPath config/macd/v2 -Recurse -Filter *.yaml | Sort-Object FullName
foreach ($config in $configs) {
    python run_backtest.py --config "$($config.FullName)"
    if ($LASTEXITCODE -ne 0) { throw "MACD v2 failed: $($config.FullName)" }
}
```

--check를 붙이면 설정만 검증하고 DB에 접근하지 않는다.
결과는 reports/macd/v2/<market>/<direction>/<symbol>/1h/<leverage>x/ 아래에 저장된다.
현물은 direction 폴더를 생략한다. 마지막 폴더명에는 기간과 SL·TPnone·MACD 파라미터를 넣는다.
일반 실행과 결과 저장 모두 DB의 시장 데이터·run/trade 테이블에 쓰지 않는다.

## 실행 연결과 체결 가정

원래 backend/src와 레지스트리는 변경하지 않았다. v1은 기존 BacktestService/엔진을 계속 사용한다.
v2는 backend_dev/backtesting의 읽기 전용 서비스와 개발용 실행 루프를 사용한다.
공통 엔진은 위험 정책을 RSI 버전에 연결해 두었기 때문에, 실행 루프만 개발 폴더에 분리했다.
이 임시 복사본은 기존 체결 순서를 기반으로 MACD v2의 보호 SL 선택만 연결한 것이다.
포트폴리오, 명목금액·수수료 계산, SL/청산 경계 계산, 검증과 지표 계산은 기존 모듈을 import한다.
기존 모듈의 전역 함수 교체나 RSI용 요청으로 위장하는 처리는 하지 않는다.
배치가 끝난 뒤에는 실행 정책 주입 구조로 통합하는 것이 후속 작업이다.

- 보유 포지션의 시가 갭을 예약된 교차 주문보다 먼저 검사한다.
- 시가가 강제 청산 경계를 넘으면 청산하고, SL만 넘으면 시가로 손절한다.
- 연속적인 불리한 가격 이동을 가정해 SL과 청산 중 더 가까운 경계를 먼저 처리한다.
- 모든 종료에 일반 수수료·불리한 슬리피지를 반영한다. 강제 청산에는 별도 가정 수수료도 반영한다.
- 봉 내부 점프·실제 순서는 OHLC만으로 알 수 없으며, 펀딩과 청산의 기존 근사는 유지한다.

개발 엔진 식별자와 개발 Python 소스 해시를 결과에 기록한다. RSI 배치가 검사하는 backend/src는 그대로다.

## 수수료 확인

2026-11-01 확인: 현물 편도 0.1%는 [Binance 공식 일반 사용자 기본표](https://www.binance.com/en/fee/trading)와 일치한다.
선물 편도 0.05%는 [Binance 공식 USDⓈ-M 계산 예시](https://www.binance.com/en/support/faq/detail/360033544231)의
일반 사용자 taker 요율과 같다. 공식 선물 실시간 표는 이번 조회에서 값이 표시되지 않아,
최신 계정별 요율을 확인한 것으로 간주하지 않는다. VIP·BNB·프로모션·과거 요율 변동은 미반영한 고정 가정이다.

일반 수수료는 명목 체결금액 × 요율로 계산한다. 레버리지는 포지션 크기에 반영되며 수수료에 다시 곱하지 않는다.
현물 v1의 947회 왕복·1894회 체결에서 수수료 778.44 USDT는 누적 체결금액 약 778,442 USDT에 해당한다.
초기 자금 대비 커 보일 수 있지만 수수료 기준은 누적 거래금액이다. 슬리피지는 체결 가격에 이미 반영되어 있다.
펀딩 assume_zero와 고정 유지증거금·청산 수수료는 별도 모형 가정이며 실제 Binance 비용 전체의 재현을 뜻하지 않는다.
