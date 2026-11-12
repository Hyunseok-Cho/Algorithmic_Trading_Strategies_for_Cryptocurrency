# 사용자 전략 작성 순서

RSI는 사용자 정의 38/70 규칙으로 `implemented=true`다. MACD와 결합 전략은 아직 `implemented=false`다.
현재 구현·시장별 정책·warmup은 [RSI 명세](rsi_strategy.md)를 참조한다.

1. 다음 파일 중 하나에 사용자 로직을 작성한다.
   - `src/trading_lab/strategies/RSI_MACD/RSI/strategy.py`
   - `src/trading_lab/strategies/RSI_MACD/MACD/strategy.py`
   - `src/trading_lab/strategies/RSI_MACD/RSI_MACD/strategy.py`
2. 클래스명 `UserStrategy`를 유지하고 `__init__(**parameters)`에서 본인이 정한 파라미터를 검증한다.
   매 실행마다 새 객체를 사용한다. 전역 상태·현재시각·임의 난수·외부 요청으로 결과를 바꾸지 않는다.
3. `on_bar(context)`는 `OrderIntent` 또는 `None`을 반환한다. `None`은 아무 주문도 요청하지 않는다.
   action은 `SignalAction.OPEN_LONG`, `OPEN_SHORT`, `CLOSE`, `TARGET_LONG`, `TARGET_SHORT`다.
   CLOSE의 Decimal fraction은 남은 수량의 (0,1] 비율이며 기본값 1이다.
   OPEN은 기존 포지션이 있으면 무시하고, TARGET은 반대 포지션을 다음 시가에서 청산한 뒤 전환한다.
   부분 진입과 피라미딩은 지원하지 않는다. 두 전환 leg의 비용은 각각 부과한다.
4. `context.history`는 지금까지 완료된 봉만 노출한다. `[-1]`은 방금 완료된 봉이며 미래 인덱스는 오류다.
   `time`은 해당 봉 종료 시각이다. `equity`, `cash`, immutable `position` snapshot을 읽을 수 있다.
   `direction_mode`로 허용 방향을 확인할 수 있다. 현물은 long_only로 검증된다.
   DB·CCXT·계좌 내부 상태를 직접 변경하지 않는다.
5. `warmup_bars`만큼 앞선 데이터도 DB에 있어야 한다. warmup 중 `trading_enabled=False`이며
   on_bar는 호출되지만 반환 주문은 무시된다. warmup에서 낸 주문을 첫 분석 봉에 몰래 체결하지 않는다.
6. 논문 규칙과 본인 수정 사항을 기록하고, 신호 시점·필요한 최소 history·롱/숏·청산·경계값 테스트를 만든다.
   `tests/fixtures/scenarios.py`는 엔진 검증용 예약 주문일 뿐 실제 전략의 기준 성능이 아니다.
7. 테스트가 준비되면 `strategies/registry.py`의 해당 `StrategyInfo`에 `implemented=True`를 명시한다.
   ID는 `rsi`, `macd`, `rsi_macd`, 표시명은 `RSI`, `MACD`, `RSI+MACD`를 유지한다.
8. 설정 파일에 `strategy_parameters`를 기록하고 같은 비용·데이터 구간으로 비교한다. 실행 명령:
   `trading-lab backtest run --config config/examples/btc_spot_1h.yaml --strategy rsi`.

MACD/결합이 완성되기 전에는 `StrategyNotImplemented`가 기대되는 동작이다. 엔진 자체는
`python -m tests.fixtures.run_demo`와 pytest로 독립 확인할 수 있다. hedge mode는 예약 값이며 실행은 거부한다.
