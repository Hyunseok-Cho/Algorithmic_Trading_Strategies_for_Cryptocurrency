# Trading Lab — CLI 백테스트 백엔드

현재 단계는 데이터 수집·저장과 백테스트 기반 구축입니다. 기존 frontend는 연결하지 않습니다.
API 디렉토리는 빈 placeholder입니다. **RSI는 사용자 정의 38/70 규칙으로 구현**했고,
MACD/RSI+MACD는 아직 placeholder로 `StrategyNotImplemented`를 반환합니다. 실거래 주문 기능은 없습니다.
RSI의 현물/선물 방향 정책과 계산·검증은 [RSI 명세](docs/rsi_strategy.md)를 참조하세요.
버전 정의와 파일 구조는 [RSI 버전 안내](src/trading_lab/strategies/RSI_MACD/RSI/README.md)를 참조하세요.
`strategy_version`은 기본 `v1`이며, `v2`는 기존 RSI 신호에 SL을 추가합니다.
실험 YAML은 `config/<strategy>/<version>/<market>/<direction>/<symbol>/<timeframe>/<leverage>x/`로 정리합니다.
현물 경로에는 direction을 생략합니다. [설정 디렉토리 안내](config/README.md)에 실행 예시가 있습니다.
v3는 RSI 종료·전환과 SL·TP를 함께 사용합니다. v4만 실행을 차단하는 placeholder입니다.
[v2 실행 안내](docs/rsi_v2.md), [v3 실행 안내](docs/rsi_v3.md)를 참조하세요.
BTC·ETH·SOL의 전체 조합 858개는 [일괄 실험 안내](docs/backtest_batch.md)를 참조하세요.

## 먼저 실행하기: DB 없이 설치와 테스트

Python 3.12 이상이 필요합니다. 아래는 저장소 루트에서 시작하는 PowerShell 명령입니다.
시스템 Python을 먼저 설치하거나 사용 가능한 Python 3.12+ 실행 파일을 지정하세요.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
.\.venv\Scripts\trading-lab.exe --help
.\.venv\Scripts\trading-lab.exe strategy list
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m tests.fixtures.run_demo
```

마지막 명령은 테스트에만 있는 합성 데이터와 예약된 주문을 사용합니다. 초기 1000 → 최종 1200의
fixture 결과와 보고서를 생성하며 실제 전략 성능을 나타내지 않습니다. DB/API 키/인터넷은 필요 없습니다.
현물 보고서는 `backend/reports/<strategy>/<version>/spot/<symbol>/<timeframe>/<leverage>x/<UTC start> - <UTC end>/`에 생성됩니다.
선물 보고서는 `backend/reports/<strategy>/<version>/future/<direction>/<symbol>/<timeframe>/<leverage>x/<UTC start> - <UTC end>/`에 생성됩니다.
심볼의 `/`, `:`는 `_`로 표시합니다. 같은 구간을 다시 실행하면 짧은 식별자를 붙여 기존 결과를 보존합니다.
데이터 수집부터 결과 확인까지의 순서는 [RSI 백테스트 가이드](docs/rsi_backtest_guide.md)를 참고하세요.

검증 당시 Windows/Python 3.12의 정확한 패키지 버전은 `requirements.lock`에 기록합니다.
같은 플랫폼에서 재현하려면 먼저 `pip install -r requirements.lock`, 이어서 `pip install -e . --no-deps`를
실행합니다. 다른 OS에서는 `pyproject.toml`로 설치하고 다시 검증하세요.

## PostgreSQL 설정

Docker Desktop/Compose를 설치하고 실행한 상태에서:

```powershell
Copy-Item .env.example .env
# .env를 열고 POSTGRES_PASSWORD의 예시 값을 실제 로컬 개발 비밀번호로 변경합니다.
docker compose config --quiet
docker compose up -d --wait db
.\.venv\Scripts\alembic.exe upgrade head
```

`.env`의 DB 이름·사용자·호스트·포트는 CLI와 Compose에서 공유합니다. 포트 충돌 시
`POSTGRES_PORT`를 바꾸세요. DB는 로컬 loopback에만 노출되고 Docker named volume에 저장됩니다.
CLI는 호스트에서 실행합니다. 일반 `docker compose down`은 named volume을 유지합니다.
이미 초기화한 volume의 비밀번호는 `.env` 수정만으로 바뀌지 않으므로 실제 DB 계정과 맞춰야 합니다.
Python 설정은 실행 위치와 관계없이 `backend/.env`를 읽습니다. Compose/Alembic 명령은 `backend`에서 실행하세요.

DB 없이 migration SQL만 확인할 수도 있습니다. 이것은 실제 적용 성공을 입증하지 않습니다.

```powershell
.\.venv\Scripts\alembic.exe upgrade head --sql
```

## 작은 범위부터 수집

먼저 BTC 현물 1시간봉 하루만 확인하세요. `--to`는 종료 제외입니다.

```powershell
.\.venv\Scripts\trading-lab.exe data sync --symbol BTC/USDT --timeframe 1h --from 2021-01-01 --to 2021-01-02
.\.venv\Scripts\trading-lab.exe data status --symbol BTC/USDT --timeframe 1h --from 2021-01-01 --to 2021-01-02
.\.venv\Scripts\trading-lab.exe data preview --symbol BTC/USDT --timeframe 1h --from 2021-01-01 --to 2021-01-02 --rows 10
```

`sync`를 반복하면 저장된 구간의 누락만 요청합니다. `--refresh`는 같은 기간을 재조회해 정정값도 갱신합니다.
시작 기본값은 2021-01-01 UTC이고 `--to` 생략 시 마지막 완성 봉까지 요청하므로 최초 점검에서는
반드시 짧은 종료 기간을 지정하는 것이 좋습니다. 미완성 봉과 가짜 보간 데이터는 저장하지 않습니다.
누락이 남으면 JSON의 `missing_ranges`에 표시하고 종료 코드 2를 반환합니다. 거래소가 제공하지 않는
기간을 합성하거나, 첫 저장 봉을 실제 상장일로 단정하지 않습니다.

선물 데이터는 완전히 별개입니다.

```powershell
.\.venv\Scripts\trading-lab.exe data sync --market perpetual --symbol BTC/USDT:USDT --timeframe 1h --from 2021-01-01 --to 2021-01-02
.\.venv\Scripts\trading-lab.exe data funding-sync --symbol BTC/USDT:USDT --from 2021-01-01 --to 2021-01-02
```

공개 수집에 API 키는 요구하지 않습니다. CCXT가 Binance 공개 API를 호출하고 rate limit 및
제한된 재시도를 적용합니다. 장기 차단·지원하지 않는 요청·데이터 검증 오류는 반복 재시도하지 않습니다.
`data status/preview`와 백테스트는 DB만 읽습니다. 백테스트의 암묵적 자동 동기화는 없습니다.

## 백테스트 설정과 실행

`config/examples/btc_spot_1h.yaml`, `btc_perpetual_1h.yaml`을 복사해 사용하세요. JSON도 지원합니다.
수수료·슬리피지 예시 값은 연구용 가정이며 실제 Binance의 과거 수수료를 보증하지 않습니다.
가격/비용 소수는 문자열로 적으면 도구 간 변환에서도 정밀도를 보존하기 쉽습니다.

```powershell
.\.venv\Scripts\trading-lab.exe backtest run --strategy rsi --config config/examples/btc_spot_1h.yaml
```

RSI 실행에는 먼저 `data sync ... --from 2021-01-01 --to 2021-01-03`으로 48개 봉을 저장하세요.
현재 예시는 앞선 14개를 warmup으로 사용하고 2021-01-01 14:00 UTC부터 01-03 00:00 UTC까지 분석합니다.
RSI<38은 Long, RSI>70은 현물 청산/선물 Short, 중간과 경계값에서는 유지합니다.
이번 현물 점검 구간에는 RSI<38이 없어 거래가 0건인 것이 정상입니다. MACD/결합은 미구현 오류를 유지합니다.
작성 위치와 계약은 [전략 작성 안내](docs/strategy_authoring.md)를 참고하세요.

선물 strict 모드는 `expected_funding_times`에 실제 검증한 UTC 이벤트 목록과
`funding_schedule_source`를 요구하며, DB 이벤트 및 mark price를 대조합니다. 8시간 고정 주기를
추측하지 않습니다. `assume_zero`를 명시하면 누락 펀딩을 0으로 단순화하되 실제 저장된 이벤트는 적용하고
강한 경고를 결과에 남깁니다. 이 모드에서도 청산 모형이 Binance와 정확히 일치하는 것은 아닙니다.

레버리지는 범용 모형 상한 125와 설정한 유지증거금 안전조건을 검증합니다. 실제 심볼의 과거 허용
레버리지·증거금 구간·호가단위·최소주문 규칙은 구현하지 않았습니다. `hedge` 값은 예약돼 있지만 실행은 거부합니다.

## 보고서와 pandas

보고서 묶음은 `report.xlsx`, `summary.json`, `trades.csv`, `equity_curve.csv`,
`daily_statistics.csv`, `result.json`, `manifest.json`입니다. Excel에는 Summary, Parameters, Trades,
EquityCurve, DailyStatistics, DataQuality, Assumptions가 있습니다. Excel 숫자의 유효 자릿수는 약 15자리이며
정확한 Decimal 문자열과 전체 결과는 JSON/CSV에도 보존됩니다. manifest는 입력·가정·데이터/소스 해시와 파일 해시를 담습니다.

완료한 DB run을 다시 출력하려면:

```powershell
.\.venv\Scripts\trading-lab.exe report export --run-id '<실제 run UUID>'
```

`data preview`는 pandas DataFrame으로 표시합니다. Python에서는
`trading_lab.infrastructure.database.dataframe.candles_frame(candles)`를 사용할 수 있으며 숫자 열은
Decimal, 인덱스는 UTC입니다. 직접 `pd.read_sql_query()`를 쓸 때는 SQLAlchemy 연결과
`coerce_float=False`를 사용하세요. Decimal을 float로 바꾸는 통계 계산은 계좌 회계와 분리했습니다.

## 검증 명령

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check src tests migrations
.\.venv\Scripts\python.exe -m ruff format --check src tests migrations
.\.venv\Scripts\python.exe -m pip check
```

기본 테스트는 네트워크와 PostgreSQL을 요구하지 않습니다. 별도 **개발 테스트 DB**에서 실제 저장을
확인하려면 `TRADING_LAB_TEST_DATABASE_URL`을 `postgresql+psycopg://...` 형식으로 지정하고
`pytest -q -m integration`을 실행하세요. 테스트는 임의의 고유 schema를 만들고 해당 schema만 정리합니다.
URL에 비밀번호 특수문자가 있으면 URL 인코딩이 필요합니다. 실제 운영 DB는 사용하지 마세요.

Windows에서 기존 pytest 임시 폴더/캐시에 `PermissionError`가 발생하면 권한을 일괄 변경하지 않고
새 전용 경로로 실행할 수 있습니다.

```powershell
$testTemp = Join-Path $PWD ("reports\pytest-user-" + [guid]::NewGuid().ToString("N"))
python -m pytest -q -p no:cacheprovider --basetemp "$testTemp"
```

기본 unit tests 통과와 실제 DB/API 검증은 구분합니다. 이 환경에서 실행한 검사의 최신 결과와 파일별 설명은
[구현 보고서](docs/implementation_report.md)에 기록합니다.

계산식은 [지표 정의](docs/metrics_definitions.md), 체결·펀딩·청산 한계는
[실행 가정](docs/execution_assumptions.md), 데이터 정책은 [데이터 계약](docs/data_contract.md)에 있습니다.
