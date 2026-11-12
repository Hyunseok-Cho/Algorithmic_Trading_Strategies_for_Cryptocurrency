# CLI 백엔드 구현 보고서

> 이 문서는 초기 CLI 기반 구축 시점의 기록이다. 후속 사용자 요청으로 RSI와 명시적 포지션 전환을
> 구현했다. 현재 전략 상태·추가 테스트·실제 DB 실행 결과는 [RSI 명세](rsi_strategy.md)를 참조한다.

기준일: 2026-10-31. 사용자가 남은 파일 전체 구현을 승인한 뒤 CLI 범위를 연결했다.
기존 frontend 코드는 변경하지 않았고 Git commit은 만들지 않았다.

## 실제 검증 결과

| 검사 | 수행 결과 |
|---|---|
| editable package 설치 | `pip install -e '.[dev]'` 성공, Windows/Python 3.12 |
| 기본 pytest | **300 passed, 3 deselected**, DeprecationWarning을 오류로 설정해 통과 |
| PostgreSQL 통합 테스트 선택 실행 | **3 skipped** — 전용 테스트 DB URL과 실행 서버가 없음 |
| Ruff check / format | src, tests, migrations, scripts 검사 통과 |
| pip check | 의존성 충돌 없음 |
| Alembic heads | `0001_initial_schema (head)` |
| Alembic offline SQL | upgrade/downgrade 생성과 ORM snapshot 대조 통과 |
| 실제 PostgreSQL migration / UPSERT / run 저장 | **미검증** — Docker/PostgreSQL 실행 파일을 찾지 못함 |
| Binance Spot 실제 공개 API | 2021-01-01 1h 캔들 2개 조회 성공 |
| Binance USDT perpetual 실제 공개 API | 같은 기간 캔들 2개, 펀딩 이벤트 2개 조회 성공 |
| fixture demo | 합성 초기 1000 → 최종 1200, 1 round trip, 2 orders |
| Excel/JSON/CSV | 실제 파일 생성 및 시트·핵심 집계값·manifest 해시 검사 통과 |
| JSON round trip / report 재출력 | Decimal 복원 및 Excel 숫자 셀 유지 검사 통과 |
| 실제 전략 CLI | RSI/MACD/RSI+MACD 미구현 표시, 실행 거부 확인 |
| frontend diff | 변경 없음 |

실제 API 검증은 소규모 읽기만 수행했고 실데이터를 DB/파일로 수집하거나 주문하지 않았다.
2021년 펀딩 API의 `markPrice=""` 응답을 발견하여 None으로 보존하도록 수정하고 회귀 테스트를 추가했다.
이 데이터의 strict 백테스트는 역사적 mark price를 보완하지 않으면 거부한다.
테스트 수가 많다는 사실을 실제 DB의 성능·동시성·복구 검증으로 해석해서는 안 된다.
mypy는 실행하지 않았으며 Protocol 타입 힌트 자체가 런타임 구현 검사를 강제하지 않는다.

## 생성·변경 파일과 로직

아래 경로는 backend 기준이다. 빈 `__init__.py`는 Python 패키지 경계이며 별도 매매 로직이 없다.

| 파일 | 역할과 선택 이유 |
|---|---|
| `pyproject.toml` | src 패키지, `trading-lab` 진입점, 의존성·pytest·Ruff 설정 |
| `requirements.lock` | 검증한 Windows/Python 3.12 의존성을 정확한 버전으로 기록 |
| `.env.example` | 로컬 DB·경로·수집 재시도 설정 예시. 비밀값 자체는 `.env`로 분리 |
| `.gitignore` | 데이터·보고서·백업·캐시 제외, 예시와 작은 fixture는 추적 허용 |
| `compose.yaml` | PostgreSQL 16, loopback 포트, named volume, health check, UTC |
| `alembic.ini` | 파일 기준 migration/src 경로와 로그. DB 비밀번호 없음 |
| `migrations/env.py` | 온라인 적용/오프라인 SQL, 기존 Settings 재사용, 외부 transaction 연결 지원 |
| `migrations/versions/0001_initial_schema.py` | 7개 테이블·키·제약·인덱스의 고정 snapshot과 역순 downgrade |
| `migrations/script.py.mako` | 이후 revision 생성 템플릿 |
| `src/trading_lab/config.py` | Pydantic Settings, 비밀번호 마스킹·입력 검증·안정적인 경로·SQLAlchemy URL 구성 |
| `src/trading_lab/domain/enums.py` | 시장·주문·포지션·방향·증거금·펀딩 모드 공통 값. hedge는 예약 값 |
| `src/trading_lab/domain/models.py` | immutable Market/Candle/FundingRate, Decimal·UTC·OHLC 검증 |
| `src/trading_lab/domain/interfaces.py` | provider / DB 읽기 / DB 쓰기 Protocol과 실제 write count 계약 |
| `src/trading_lab/domain/exceptions.py` | 일시 오류·영구 오류·미지원·결측·저장 실패를 외부 SDK와 독립적으로 구분 |
| `src/trading_lab/domain/timeframes.py` | 고정 UTC 봉 경계, 완성 봉 cutoff, leading/internal/trailing gap 탐지 |
| `src/trading_lab/domain/sync.py` | job 상태·기간·건수·cursor와 coverage의 일관성 검증 |
| `src/trading_lab/application/dto.py` | 공통 BacktestRequest/Result·거래·equity·SyncResult. JSON Decimal 복원 |
| `src/trading_lab/application/ports.py` | DataUnit와 sync storage 계약. 서비스 테스트의 fake 교체 지점 |
| `src/trading_lab/application/market_data_service.py` | 증분/갭/refresh 동기화, 페이지별 atomic 저장, 실패 상태, DB-only status |
| `src/trading_lab/application/backtest_service.py` | DB 데이터 로딩, 전략 연결, 입력/소스/데이터 해시, 엔진·지표·run 기록 orchestration |
| `src/trading_lab/application/report_service.py` | staging 후 완성된 보고서 디렉토리 공개, manifest, report 실패 상태 분리 |
| `src/trading_lab/backtesting/accounting.py` | 12자리 Decimal 결제·부호별 가격 손익 |
| `src/trading_lab/backtesting/execution.py` | 매수/매도에 불리한 bps 슬리피지 |
| `src/trading_lab/backtesting/portfolio.py` | 현물 cash/inventory, 선물 margin/PnL/funding, 부분 청산과 round-trip 집계 |
| `src/trading_lab/backtesting/risk.py` | 문서화된 보수적 청산·stop·target 근사 |
| `src/trading_lab/backtesting/validation.py` | warmup 포함 gap-free 입력, strict funding 목록·mark price 검증 |
| `src/trading_lab/backtesting/engine.py` | 다음 봉 시가 체결, prefix history, 펀딩/위험 순서, 종료 평가·강제 종료 |
| `src/trading_lab/backtesting/metrics.py` | UTC daily equity, 거래 통계·위험 지표·drawdown·N/A·Buy & Hold |
| `src/trading_lab/infrastructure/database/models.py` | SQLAlchemy PostgreSQL 테이블. NUMERIC·TIMESTAMPTZ·JSONB·키·검사 제약 |
| `src/trading_lab/infrastructure/database/engine.py` | lazy engine, 세션 factory, commit/rollback/close 경계 |
| `src/trading_lab/infrastructure/database/repositories.py` | 시장·캔들·펀딩 저장/stream 조회. 중복·정정·NULL-safe 차이와 실제 write count |
| `src/trading_lab/infrastructure/database/sync_repository.py` | job snapshot 비교 갱신, 진행 역행 방지, 최신 coverage 저장 |
| `src/trading_lab/infrastructure/database/unit_of_work.py` | 데이터와 cursor를 같은 transaction/session에 연결 |
| `src/trading_lab/infrastructure/database/run_repository.py` | run 시작/완료/실패, 결과 JSON·거래 행, 재출력용 결과 복원 |
| `src/trading_lab/infrastructure/database/dataframe.py` | Decimal을 유지하는 UTC-index pandas OHLCV view |
| `src/trading_lab/infrastructure/exchanges/ccxt_provider.py` | Binance spot/usdm 구분, exact symbol, Decimal 문자열, API bounds·rate limit·retry·검증 |
| `src/trading_lab/infrastructure/reporting/excel_exporter.py` | 7개 시트, 숫자/퍼센트 서식·필터·고정 행·equity chart |
| `src/trading_lab/infrastructure/reporting/csv_exporter.py` | UTF-8 BOM·무거래 헤더·문자열 formula 방지 |
| `src/trading_lab/infrastructure/reporting/json_exporter.py` | Decimal 문자열·UTC 시각·UUID 직렬화, 비유한 JSON 숫자 금지 |
| `src/trading_lab/interfaces/cli.py` | Typer data sync/status/preview/funding-sync, strategy list, backtest run, report export |
| `src/trading_lab/interfaces/api/.gitkeep` | 빈 API placeholder. HTTP 코드 없음 |
| `src/trading_lab/strategies/base.py` | History prefix, immutable context/position view, OrderIntent와 Strategy Protocol |
| `src/trading_lab/strategies/registry.py` | 3개 ID/표시명/상태, 미구현 시 명확한 오류 |
| `src/trading_lab/strategies/RSI_MACD/RSI/strategy.py` | 사용자 작성 슬롯. 계산/규칙 없음 |
| `src/trading_lab/strategies/RSI_MACD/MACD/strategy.py` | 사용자 작성 슬롯. 계산/규칙 없음 |
| `src/trading_lab/strategies/RSI_MACD/RSI_MACD/strategy.py` | 사용자 작성 슬롯. 계산/규칙 없음 |
| `config/examples/btc_spot_1h.yaml` | 명시적인 현물 실험 입력 예시 |
| `config/examples/btc_perpetual_1h.yaml` | 선물 예시. strict schedule은 확인 전 null로 두어 잘못된 실행 방지 |
| `scripts/smoke_exchange.py` | 명시적 소규모 실제 API 연결 검사. 기본 pytest에 포함하지 않음 |
| `tests/fixtures/fakes.py` | rollback 가능한 메모리 저장소·fake provider·fake run store |
| `tests/fixtures/scenarios.py` | 합성 OHLCV와 지정 index의 주문. 실전 전략으로 등록되지 않음 |
| `tests/fixtures/run_demo.py` | DB·API 없이 엔진과 보고서의 end-to-end 데모 |
| `data/.gitkeep`, `reports/.gitkeep` | 생성물 경로만 보존 |

## 테스트 파일의 검증 범위

| 파일 | 주요 검증 |
|---|---|
| `test_config.py` | 환경 우선순위, SecretStr, URL 특수문자, 시간/경로/입력 검증 |
| `test_domain_models.py` | OHLC·Decimal·UTC·상품 구분·펀딩·불변성 |
| `test_timeframes.py` | 경계 직전/정각, 미완성 봉, 잘못된 timestamp, 128가지 gap 조합 |
| `test_sync_models.py` | 상태/기간/건수/cursor와 coverage 일관성 |
| `test_database_engine.py` | SQLite transaction commit/rollback/중단/commit 실패와 자원 정리 |
| `test_migrations.py` | PostgreSQL용 offline SQL·키·인덱스·ORM 일치, migration engine 정리 |
| `test_postgres_migrations.py` | 실제 DB에서 upgrade/downgrade. 현재 환경에서는 skip |
| `test_repositories.py` | SQL·범위·중복·타입·오류, opt-in 실제 DB 저장/반복/정정/rollback |
| `test_sync_repository.py` | 상태 비교 갱신·진행 역행 거부·JSON round trip·최신 snapshot |
| `test_run_repository.py` | run 상태·입력/출처·결과/거래·재출력 snapshot |
| `test_ccxt_provider.py` | 실제 파서+fake endpoint, 정밀도·펀딩·오류·retry·빈 mark price |
| `test_data_sync.py` | 첫/반복/증분/gap/refresh, 미완성 봉, 실패 재개, 데이터+cursor atomic rollback |
| `test_backtesting.py` | next-open·미래 접근 금지·spot/perp long/short·비용·leverage·부분 청산·손익·청산·warmup |
| `test_metrics.py` | initial peak drawdown·일 수익률·Sharpe/Sortino 공식·무거래/전액손실/N/A |
| `test_services_reporting_cli.py` | 전체 fixture run·Excel/JSON 일치·manifest·실패 상태·pandas·CLI·설정 |

## 문서와 시작 순서

- `README.md`: 설치 → 오프라인 테스트/데모 → DB → 짧은 기간 sync → preview → 전략 작성 → backtest/report 명령.
- `docs/architecture.md`: 계층과 이번 승인 범위.
- `docs/data_contract.md`: UTC/키/단위/갭/미완성 봉/펀딩 결측 정책.
- `docs/execution_assumptions.md`: 체결 순서·cash/margin·funding·청산/슬리피지 근사.
- `docs/metrics_definitions.md`: 지표의 공식·단위·분모·연율화·N/A·결제 rounding 차이.
- `docs/strategy_authoring.md`: 사용자가 직접 세 전략을 채우는 순서.
- `docs/future_api_contract.md`: 향후 서비스 재사용 경계만 문서화. API 코드는 없음.
- 저장소 루트 `README.md`에는 backend 안내 링크만 추가했다.

## 의도적으로 남긴 범위와 한계

RSI/MACD/결합 전략, hedge 실행, HTTP/API/웹 연결, 실거래·paper trading은 구현하지 않았다.
실제 거래소의 과거 수수료 tier·정밀 liquidation·mark OHLC·tick/lot/minimum notional·스프레드·주문 크기별
시장 충격을 재현하지 않는다. 지정한 비용과 flat-rate isolated 근사로 실험하며 결과의 Assumptions에 보존한다.
actual DB migration·동시 수집 충돌·DB 중단 복구·대용량 성능은 PostgreSQL 환경에서 추가 확인해야 한다.
백테스트는 현재 요청한 캔들 범위를 메모리에 올리므로 초대형 1분봉 실험은 별도 용량/성능 검토가 필요하다.
명령 설치와 fake end-to-end는 확인했지만 실제 DB 기반 sync→run→export 전체 경로의 성공을 주장하지 않는다.
