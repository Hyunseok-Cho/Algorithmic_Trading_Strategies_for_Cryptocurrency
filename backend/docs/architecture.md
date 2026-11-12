# CLI 백테스팅 백엔드 설계

상태: CLI 구현 범위의 설계 기준. 실제 검증 상태는 implementation_report.md를 참조한다.

## 범위와 진행 방식

- 기존 frontend는 수정하지 않는다.
- 현재 실행 인터페이스는 Python CLI로 한정한다.
- 웹/API 연결부는 빈 디렉토리 또는 빈 파일 placeholder만 둔다.
- 초기 기반 구축에서는 전략을 비워 뒀다. 이후 사용자 요청으로 RSI 38/70 규칙과 명시적 포지션 전환을
  구현했다. MACD/결합은 상세 규칙 확정 후 구현할 슬롯으로 남아 있다. [RSI 명세](rsi_strategy.md) 참조.
- 초기에는 파일별 승인으로 진행했으며, 이후 사용자가 남은 파일 전체 구현을 승인했다.
  커밋은 별도 요청 시 수행한다. 실제 전략 로직은 계속 사용자 작성 범위다.
- 첨부 계획서는 설계 참고 자료이며, 사용자 요청과 충돌하면 사용자 요청을 따른다.

## 계층과 의존성

- domain: Candle, 주문 의도, 체결, 포지션 등 공통 타입과 저장소/provider 계약.
- application: 데이터 동기화, 백테스트, 보고서 서비스 및 Pydantic 입출력 모델.
- infrastructure: PostgreSQL 저장소, CCXT/Binance 데이터 접근, 결과 파일 출력.
- backtesting: 체결, 회계, 포지션, 위험 모형 및 성과 계산.
- strategies: 사용자 작성용 인터페이스, registry, 미구현 전략 슬롯.
- interfaces: Typer CLI 및 빈 API placeholder.

CLI는 application을 호출한다. domain과 엔진은 CLI, HTTP, CCXT, DB에 의존하지 않는다.
이를 통해 외부 네트워크 없이 엔진을 검증하고 이후 같은 서비스를 웹에서 호출한다.

## Binance 데이터 기준

초기 수집은 CCXT의 Binance 어댑터를 사용한다. CCXT 역시 거래소 API를 호출하므로
직접 REST 호출이라는 이유만으로 더 정확하거나 안정적이라고 가정하지 않는다.
공통 provider 계약 뒤에서 수집 방식을 교체할 수 있게 한다.
Binance 고유 정보가 공통 메서드로 충분히 제공되지 않으면 전용 어댑터를 추가한다.

- Spot과 USDT 결제 선형 무기한 선물을 분리한다. 초기 선물 범위에 COIN-M은 포함하지 않는다.
- 거래가격 OHLCV, mark price, 펀딩은 서로 다른 데이터로 취급한다.
- 실제 펀딩 시각과 비율을 저장하며 고정 8시간 주기를 전제로 결측을 판단하지 않는다.
- OHLCV만으로 과거 호가 스프레드나 주문 크기별 슬리피지를 복원할 수 없다.
  slippage_bps는 실험 가정으로 명시하고 민감도 분석이 가능하게 한다.
- 진입/청산 수수료율은 명시적 설정으로 보존한다. 현재 계정 수수료율을 과거 전체에
  적용 가능한 역사적 사실로 간주하지 않는다. 공개 데이터 수집에 API 키는 요구하지 않는다.
- mark price 및 유지증거금 구간 등 근거 데이터가 부족한 청산 모델은 근사로 표시한다.
- 데이터 출처, 조회 범위, 수집 시각 및 사용한 비용 가정을 결과에 남긴다.

## 재현성과 검증

- 시간은 UTC, 요청 범위는 [start, end)로 통일한다.
- 데이터 저장소는 PostgreSQL이며 백테스트 중 자동 외부 데이터 수집을 하지 않는다.
- 완성된 봉만 저장하고 중복, 누락, OHLC 유효성 및 페이지 중단 복구를 검증한다.
- 전략은 완료된 봉까지만 보고 주문은 다음 봉 시가에서 체결한다.
- 기본 펀딩 모드는 strict이며 결측을 자동으로 0으로 바꾸지 않는다.
- 테스트용 결정론적 전략은 tests/fixtures에만 두고 실제 전략으로 등록하지 않는다.
- 단위 테스트는 오프라인, PostgreSQL 통합 테스트와 실제 거래소 smoke 검사는 별도로 구분한다.

## 구현 순서

1. 패키지 설정, 환경 예시, ignore, Compose, DB 모델과 migration.
2. provider와 저장소, 데이터 sync/status CLI 및 오프라인 검증.
3. 전략 계약과 placeholder, 요청 검증, Spot/선물 엔진 및 회계 검증.
4. 통계, DB 실행 기록, Excel/CSV/JSON 출력 및 결과 일치 검증.
5. CLI 명령 연결, 설정 예시, 설치·실행·테스트 및 전략 작성 가이드.

## 공식 참고 자료

- CCXT Manual: https://github.com/ccxt/ccxt/wiki/Manual
- Binance Futures Market Data: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/market-data
- Binance Futures Account: https://developers.binance.com/en/docs/catalog/core-trading-derivatives-trading-usd-s-m-futures/api/rest-api/account
