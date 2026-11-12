# 지표 정의와 단위

금액은 USDT, funding은 수취 양수/지급 음수, 수수료는 비용 양수다. `%` 필드는 0~1 비율이 아닌
퍼센트 포인트다. JSON의 Decimal은 정확한 문자열이고 N/A는 null이며 `na_reasons`에 이유가 있다.

- `net_pnl = ending_equity - initial_equity`; `total_return_pct = net_pnl / initial_equity * 100`.
- `realized_pnl = settled_gross_realized - all_fees + all_funding`이며 열린 포지션의 진입 비용도 포함한다.
  `unrealized_pnl`은 남은 수량의 거래가격 평가손익이다. 부분 청산 realized도 total에 포함한다.
- `gross_pnl = settled_gross_realized + unrealized_pnl`; `uncapped_price_pnl`은 제한 전 가격 손익이다.
  isolated 초과손실은 `limited_loss_adjustment`로 분리한다. 실행 가정을 함께 읽어야 한다.
- 여러 부분 청산에서 12자리 결제 반올림의 합산 순서가 달라지는 미세한 차이는
  `settlement_rounding_residual`로 공개한다. `net_pnl = realized_pnl + unrealized_pnl + residual`이다.
- 거래 수는 **완결 round trip 수**다. partial close와 주문 수는 별개이며 미청산 포지션은 별도 표시한다.
- 승/패/본전은 수수료·펀딩 포함 net trade PnL의 부호로 구분한다. 승률은 승 / 전체 완결 거래 수 ×100이다.
  본전도 분모에 포함한다. 평균 승리/손실과 최고 이익/최악 손실은 해당 부호의 거래만 집계한다.
- 거래 수익률은 `net_trade_pnl / initial_committed_margin * 100`이다. 현물 margin은 매수 원금이며
  진입 수수료는 분모에 더하지 않는다. 선물은 최초 isolated margin을 분모로 한다.
- expectancy는 전체 net trade PnL의 평균이다. 본전을 포함한 `win_prob*avg_win + loss_prob*avg_loss`와 같다.
- profit factor는 양수 net trade 합 / 음수 net trade 합 절댓값이다. 손실이 없으면 무한대 대신 null이다.
- 평균 보유시간은 entry→최종 exit의 초 단위 평균이다. 연속 승/패는 본전에서 끊긴다.
- calendar_days는 `[start,end)`가 걸치는 UTC 날짜 수다. 평균 일 거래 수는 전체 완결 거래 / 날짜 수,
  active-day 평균은 완결 거래가 발생한 날짜만 분모로 한다. end 정각의 최종 종료는 마지막 분석 날짜에 귀속한다.
- equity curve는 분석 시작 초기자본과 매 완료 봉의 평가액을 포함한다. 미래 봉 참조 없이 계산한다.
  일별 통계는 완료 시각에서 1 microsecond를 빼 해당 봉이 끝난 UTC 날짜에 귀속하고 마지막 equity를 쓴다.
  첫 날의 opening equity는 초기자본, 다음 날은 전날 마지막 equity다. 부분 날짜도 한 calendar day다.
- 일 수익률은 `day_end/day_open - 1`. 전일 equity가 0이면 정의하지 않는다.
- drawdown 금액은 관측한 running peak − equity의 최댓값이고, drawdown%는 각 시점 decline/peak의 최댓값이다.
  초기자본도 peak 후보다. 시작/끝은 최대 퍼센트 낙폭의 peak/trough, underwater 시간은 마지막 peak 이후
  하락 상태로 관측한 최장 시간이다. **봉 사이 intrabar equity drawdown은 포함하지 않는다.**
- Sharpe: 유효 일 수익률 평균 / sample 표준편차(ddof=1) × sqrt(365), risk-free=0.
- Sortino: 일 수익률 평균 / sqrt(mean(min(r,0)^2)) × sqrt(365). downside 분모는 모든 관측일을 사용한다.
- 연율 변동성: sample 일 표준편차 × sqrt(365) ×100. 무거래 또는 유효 일 수익률이 2개 미만이면 N/A다.
  Sharpe/Sortino의 분모가 0이면 N/A다. 0 equity 이후 정의되지 않는 날이 있으면 risk ratio를 산출하지 않는다.
- Calmar는 365일 이상, ending equity>0, drawdown>0인 경우 CAGR%/max_drawdown%다. 짧은 기간은 N/A다.
- Buy & Hold는 동일 거래가격 dataset·allocation·수수료·슬리피지로 첫 분석 봉 시가에 매수하고 마지막 종가에
  매도하는 **가상의 무레버리지 보유**다. 선물 dataset에서도 펀딩·청산을 제외한 기준선이며 실제 선물 보유 수익이 아니다.
  초과수익은 전략 수익률% − 해당 기준선%다.

N/A를 0이나 무한대로 바꾸지 않는다. Excel의 퍼센트 필드는 표시 형식으로 `%`를 붙이고 값을 다시 100배 하지 않는다.
