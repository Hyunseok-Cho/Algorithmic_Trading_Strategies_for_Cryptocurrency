# 데이터 계약

- DB는 PostgreSQL이며 시장 식별자는 `(exchange, market_type, unified symbol)`이다.
  현물 `BTC/USDT`와 선물 `BTC/USDT:USDT`를 합치지 않는다. 선물 범위는 USDT linear perpetual이다.
- 모든 시각은 timezone-aware UTC, 조회 구간은 `[start, end)`이다. 고정 UTC 분·시간·1일 봉만
  지원하며 사용자 경계를 조용히 반올림하지 않는다. 월·주·다일 봉은 앵커 규칙이 달라 거부한다.
  엔진의 간격 지원과 실제 거래소 지원 여부는 별도로 검사한다.
- Candle은 거래가격 OHLCV다. 가격은 quote/base, volume은 base 수량이다. mark-price 봉이 아니다.
  CCXT Binance spot/linear kline의 volume 필드를 사용한다. 가격 문자열은 `number=str` → Decimal로 변환한다.
- DB NUMERIC은 소수를 보존하며 NaN/Infinity·음수 거래량·잘못된 OHLC 관계를 거부한다.
  단일 입력 페이지에서 같은 시각의 같은 값은 병합하고 충돌하는 값은 오류다.
- 저장키는 캔들 `(market_id, timeframe, open_time)`, 펀딩 `(market_id, funding_time)`이다.
  캔들 키의 B-tree 인덱스가 해당 시장/시간봉의 기간 조회에도 사용된다.
- 저장소는 `ON CONFLICT DO NOTHING`으로 신규를 추가하고 NULL-safe 비교로 변경 행만 갱신한다.
  신규·정정 건수는 RETURNING 결과로 계산하며 같은 입력 재실행은 원칙적으로 0/0이다.
  서버 실행에 대한 검증은 PostgreSQL 통합 테스트가 담당한다. mock 검사만으로 이를 입증하지 않는다.
- sync 서비스는 기존 timestamp를 훑어 leading/internal/trailing gap을 찾고 해당 구간만 요청한다.
  정상 페이지를 저장하고 cursor/counter를 갱신하는 작업은 같은 transaction에 묶는다.
  네트워크 요청과 backoff는 transaction 밖이다. job 상태는 이전 snapshot을 비교하여 갱신한다.
- 빈 페이지와 상장 전/보관 정책에 의한 미제공 이력은 합성하지 않는다. 누락은 partial과 gap으로 남는다.
  마지막 저장 봉은 실제 최초 제공 봉이나 상장일을 입증하지 않는다. `first_available_at`은 확인 전 NULL이다.
- sync 시계를 한 번 캡처하고 해당 시점까지 완성된 봉만 저장한다. 실패 후 재실행은 DB gap을 기준으로
  이어받는다. 최신 완료 job만 믿고 중간 공백이 없다고 가정하지 않는다.
- `data_coverage`는 마지막으로 확인한 특정 요청 구간의 snapshot이며 모든 과거 구간의 합집합이 아니다.
  다른 구간의 status는 DB timestamp를 다시 검사한다. 오래된 check가 최신 snapshot을 덮어쓰지 않는다.
- 펀딩은 부호가 있는 실제 이벤트다. 양수 rate는 long 지급/short 수취다. 결측을 관측된 0과 구분한다.
  incremental funding sync는 마지막 이벤트 이후만 요청하며 `--refresh`로 과거 구간을 다시 확인한다.
  이벤트 간격은 고정하지 않으며 completeness는 자동 인증하지 않는다. strict 백테스트는 별도 검증 목록을 요구한다.
- 실제 2021년 펀딩 응답에서 `markPrice=""`가 관측됐다. 빈 문자열은 결측 `None`으로 보존한다.
  0으로 만들지 않으며 strict 백테스트에서는 역사적 mark price를 보완하지 않으면 거부한다.
  이벤트 시각도 정각에서 수 ms 어긋날 수 있으므로 실제 timestamp를 그대로 사용한다.
- OHLCV만으로 과거 스프레드·호가 깊이·주문 크기별 슬리피지를 복원하지 않는다. 비용 가정은 각 run에 저장한다.
- 원시 데이터·보고서·환경 비밀값은 Git에서 제외한다. 작은 합성 fixture만 테스트 코드로 보존한다.

공식 근거: [CCXT Manual](https://github.com/ccxt/ccxt/wiki/Manual),
[PostgreSQL ON CONFLICT](https://www.postgresql.org/docs/16/sql-insert.html),
[Binance Futures market data](https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data).
