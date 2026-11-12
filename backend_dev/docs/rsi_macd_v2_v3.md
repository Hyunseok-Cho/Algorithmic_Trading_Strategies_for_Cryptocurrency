# RSI+MACD v2·v3 — SL / SL·TP 비교

## 버전 정의

두 버전은 v1을 상속하며 MACD > Signal + RSI < 38 Long,
MACD < Signal + RSI > 70 Short 조건을 유지한다.
Long은 반대 RSI > 70, Short는 RSI < 38에서 청산하며 반대 MACD 필터도 맞으면 전환한다.
MACD 방향 변경만으로 청산하지 않는다.

| 버전 | 추가한 종료 조건 | YAML 수 |
|---|---|---:|
| v2 | 고정 SL 2~10%, 1% 간격 | 45 |
| v3 | 같은 SL과 TP=SL×2, TP 4~20% | 45 |

각 버전에는 현물 1배 9개, 선물 Long/Short 2·3·4·5배 각각 9개가 있다.
v3는 (SL2,TP4)부터 (SL10,TP20)까지 9쌍이며 모든 교차 조합이 아니다.
보호 종료 외의 입력은 각 배율의 v1 YAML과 동일하게 보존했다.

BTC 1h, RSI 14/38/70, MACD 12/26/9, 준비 34봉, 초기 자금 1000 USDT, 배분 100%,
분석 2024-01-02 00:00 ~ 2026-11-01 00:00 UTC(종료 제외),
현물 편도 수수료 0.1%, 선물 0.05%, 슬리피지 5bps다.
선물은 one_way/isolated·assume_zero 펀딩이며 기존 유지증거금·청산 근사 한계가 남는다.

## SL·TP 동작

SL·TP는 실제 진입 체결 가격 대비 비율이며 증거금 ROI나 계좌 손실률이 아니다.
RSI 종료와 보호 가격 종료 중 먼저 발생한 조건을 사용한다.
SL 또는 TP 종료 후 진입 조건이 유지되면 다시 진입할 수 있다.
이 재진입은 MACD 교차 순간만 사용하는 단독 전략과 달리, 상태 필터와 RSI 밴드 조건에서 발생할 수 있다.
재진입 제한·추적 손절·시간 제한 종료는 추가하지 않았다.

시가 갭은 예약 신호보다 먼저 검사한다. 청산 경계를 넘으면 청산, SL만 넘으면 시가 손절,
TP를 넘어선 유리한 갭이면 시가 익절한다. 같은 봉에서 유리·불리 양쪽을 통과하면 순서를 알 수 없어
불리한 SL/청산을 우선한다. 두 불리한 경계는 연속 가격 이동을 가정해 더 가까운 경계가 우선이다.
종료에는 수수료·불리한 슬리피지가 적용되며 지정된 손실률이나 체결 가격을 보장하는 모형은 아니다.

v2는 SL 필수·TP 금지, v3는 SL·TP 모두 필수다.
기존 개발용 엔진을 두 전략 계열에 연결했으며 backend/src와 원래 레지스트리는 변경하지 않았다.
DB에서는 가격/펀딩을 읽기만 하고 결과는 개발 폴더에 저장한다.

## 실행 (backend_dev에서)

먼저 설정만 확인할 수 있다. --check는 DB에 접근하지 않는다.

```powershell
python run_backtest.py --config config/rsi_macd/v2/spot/BTC_USDT/1h/1x/rsi_macd_v2_btc_spot_1h_sl5.yaml --check
```

단건으로 v2·v3를 비교하려면:

```powershell
# 현물 1배, v2 SL5%
python run_backtest.py --config config/rsi_macd/v2/spot/BTC_USDT/1h/1x/rsi_macd_v2_btc_spot_1h_sl5.yaml

# 현물 1배, v3 SL5%·TP10%
python run_backtest.py --config config/rsi_macd/v3/spot/BTC_USDT/1h/1x/rsi_macd_v3_btc_spot_1h_sl5_tp10.yaml
```

전체 조합 실행·재개:

```powershell
python run_all.py --strategy rsi_macd --version v2
python run_all.py --strategy rsi_macd --version v3
```

v2는 reports/rsi_macd/v2, v3는 reports/rsi_macd/v3 아래에 저장한다.
마지막 폴더명에는 기간-SL-TP-RSI-MACD 파라미터가 표시되고 Windows 출력 권한을 상속한다.
전체 비교 CSV와 체크포인트는 각각 reports/batches/rsi_macd_v2, rsi_macd_v3에 생성한다.
실행 중에는 개발 코드·YAML·DB 데이터를 수정하지 말고 summary.csv를 Excel에서 닫아둔다.

같은 입력·코드·데이터와 온전한 산출물인 성공 건은 재개 시 건너뛴다.
개발 코드가 바뀐 이전 실험은 다시 실행될 수 있으며 기존 결과를 덮어쓰지 않는다.
같은 시장·배율·SL의 v2와 v3를 비교하고, v1과는 SL 추가 효과를 구분한다.
수익률·낙폭·평균 손실·수수료·거래 수와 SL/TP/청산 종료 건수를 함께 확인한다.
