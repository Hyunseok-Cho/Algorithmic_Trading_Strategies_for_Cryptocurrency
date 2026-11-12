# 체결·회계·펀딩 가정

이 엔진은 연구용 OHLCV 근사다. 실제 Binance의 체결·청산·계정 규칙과 일치한다고 주장하지 않는다.

1. 전략은 완료된 봉의 prefix만 받는다. 음수 인덱스와 slicing도 prefix 내부다. 종가를 보고 낸 주문은
   다음 봉 시가에 체결한다. 마지막 봉의 새 신호는 체결하지 않는다. warmup 동안 관측은 하되 주문은 무시한다.
   History는 신뢰할 수 있는 사용자 코드용 인터페이스이며 악성 Python을 격리하는 보안 sandbox는 아니다.
2. 진입 budget은 현재 가용 현금의 allocation 비율이다. 단일 포지션만 허용하므로 flat에서 equity와 cash가 같다.
   `notional = budget / (1/leverage + open_fee_rate)`로 진입 수수료를 포함해 배정한다.
   기존 포지션에서 OPEN 신호는 무시한다. TARGET_LONG/SHORT는 반대 포지션을 다음 봉 시가에서 청산한 뒤
   같은 시가 기준으로 새 방향에 진입한다. 두 leg의 비용은 각각 반영한다. 같은 방향 목표는 추가 진입하지 않는다.
3. 현물은 Long만, 레버리지 1이다. 진입 시 원금+수수료를 cash에서 빼고 청산 시 매도대금-수수료를 더한다.
   선물은 포지션별 isolated margin을 잠그고 `side * quantity * (price-entry)`를 평가손익으로 사용한다.
   계좌 화폐 `base_currency`는 기존 계획서 명칭을 따르지만 의미는 USDT account/quote currency다.
4. 매수 가격은 기준가 × (1+slippage_bps/10000), 매도는 × (1-slippage_bps/10000)다.
   maker 주문·스프레드·호가잔량·부분 체결·최소주문·tick/lot 단위는 모형화하지 않는다.
5. CLOSE의 fraction은 **남은 수량**에 적용한다. 부분 청산 주문 수와 realized PnL은 즉시 반영하되
   완결 거래는 전량 종료 시 하나만 생성한다. 최종 exit price는 부분 청산의 수량 가중평균이다.
6. 계좌 결제 금액은 Decimal 12자리 half-even이다. 초기자본도 12자리 이하로 제한한다.
   수량과 기준가격은 더 높은 Decimal 정밀도를 유지한다. Excel만 float로 표시한다.
7. 펀딩이 봉 시가와 같으면 기존 포지션에 먼저 반영한 뒤 예약된 주문을 체결한다.
   그러므로 같은 시각에 새 진입한 포지션은 그 이벤트를 내지 않고 기존 포지션의 청산은 낸다.
   봉 내부 이벤트는 해당 봉의 위험 판단 전에 반영한다. OHLC만으로 이벤트와 극값의 실제 순서를 알 수 없어 근사다.
8. 펀딩 cash flow는 `-side * quantity * historical_mark_price * rate`이며 isolated collateral에 반영한다.
   strict는 검증한 이벤트 목록·출처와 event mark price를 모두 요구한다. 빈 목록도 명시적인 검증 주장이다.
   그 출처의 정확성까지 프로그램이 인증하지 않는다. assume_zero는 관측한 이벤트를 적용하되 누락은 0으로 보고,
   mark price 결측은 마지막 완료 종가(첫 봉은 시가)로 근사하고 경고한다.
9. 청산 기준은 `margin + unrealized <= notional_at_price * (maintenance_rate + liquidation_fee_rate)`다.
   계약별·과거 tier, mark OHLC, 보험기금, ADL, 교차증거금, 헤지 모드는 없다. 청산은 거래가격 OHLC로 판단한다.
   liquidation fee와 일반 close fee를 함께 차감하는 보수적 가정이다. `hedge`는 타입만 예약하고 실행을 거부한다.
10. 한 봉에 여러 위험 이벤트가 보이면 청산 → stop loss → take profit 순이다. 청산보다 stop이 실제로 먼저였을
    가능성도 있으므로 매우 보수적일 수 있다. stop은 gap 시 더 불리한 시가, target은 목표가로 체결한다.
    intrabar 위험 청산은 봉 종료 시각으로 기록한다. 이로 인해 보유시간 역시 봉 단위 근사다.
11. 선물의 gap 손실이 isolated collateral을 넘으면 wallet으로 추가 전가하지 않는다.
    `price_pnl`은 제한 전 손익, `limited_loss_adjustment`는 초과손실 제한 조정이며,
    `gross_pnl = price_pnl + limited_loss_adjustment`다. 조정이 발생하면 경고하고 별도로 표시한다.
    이는 실제 Binance 보험·파산가격 계산을 재현한 것이 아니다.
12. 마지막 포지션은 옵션에 따라 마지막 종가에서 비용을 내고 강제 종료한다. 종료하지 않으면 unrealized PnL을
    equity에 포함하고 완결 거래 수에는 포함하지 않는다.

수수료율 예시와 maintenance/liquidation 기본값은 연구용 입력이다. 현재 VIP·BNB 할인이나 현재 계정 수수료를
과거 전체에 실제로 적용됐다고 주장하지 않는다. 같은 기간·가정의 민감도 분석을 권한다.
