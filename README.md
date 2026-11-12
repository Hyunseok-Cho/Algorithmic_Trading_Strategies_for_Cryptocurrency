# Algorithmic Trading Strategies for Cryptocurrency

Final project by Hyunseok Cho, supervised by Anna Gorawska.

`backend/` provides market-data storage, the Trading Lab CLI and RSI backtests. `backend_dev/` provides experimental MACD, RSI+MACD and Bollinger mean-reversion runners. Both use the same PostgreSQL database.

## Set up on Windows

If you already have a clone, open PowerShell in its root and run:

```powershell
git fetch origin
git switch feat/cho/backend
git pull --ff-only
```

Install Git and Python 3.12 or later. For a fresh clone, run `git clone --branch feat/cho/backend https://github.com/Hyunseok-Cho/Algorithmic_Trading_Strategies_for_Cryptocurrency.git` and enter the repository directory.

Install Docker Desktop with the WSL 2 backend and launch it from the Start menu. Follow Docker's WSL setup instructions if WSL is missing or needs an update. [Docker Desktop installation guide](https://docs.docker.com/desktop/setup/install/windows-install/)

Run the following in PowerShell from the repository root. Run subsequent commands from `backend/`.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e '.[dev]'
$py = '.\.venv\Scripts\python.exe'
$cli = '.\.venv\Scripts\trading-lab.exe'
docker compose version
```

On first setup, copy `.env.example` to `.env` and replace `POSTGRES_PASSWORD` with a local password. Keep `POSTGRES_HOST=127.0.0.1` for the Compose database. Change `POSTGRES_PORT` if port 5432 is occupied.

```powershell
Copy-Item .env.example .env
notepad .env
docker compose config --quiet
docker compose up -d --wait db
.\.venv\Scripts\alembic.exe upgrade head
docker compose ps
```

`docker compose down` stops PostgreSQL and keeps its data volume. The laptop gets a fresh database. Sync candles and funding again, or restore a PostgreSQL backup if you need the existing runs. The local `.env` and generated reports also live outside Git.

## Trading Lab CLI

Use `& $cli --help` to list groups and add `--help` to any command to see its options. The following examples sync a small UTC range and run the RSI sample. `--to` is exclusive. Public data sync uses Binance and requires no API key.

```powershell
& $cli strategy list
& $cli data sync --symbol BTC/USDT --timeframe 1h --from 2021-01-01 --to 2021-01-03
& $cli data status --symbol BTC/USDT --timeframe 1h --from 2021-01-01 --to 2021-01-03
& $cli data preview --symbol BTC/USDT --timeframe 1h --from 2021-01-01 --to 2021-01-03 --rows 10
& $cli data sync --market perpetual --symbol BTC/USDT:USDT --timeframe 1h --from 2021-01-01 --to 2021-01-03
& $cli data funding-sync --symbol BTC/USDT:USDT --from 2021-01-01 --to 2021-01-03
& $cli backtest run --strategy rsi --config config/examples/btc_spot_1h.yaml
& $cli report export --run-id '<run UUID from backtest output>'
```

Copy an example YAML to change the market, time range, costs or strategy parameters. Sync the full range required by the config, including indicator warmup candles and any required perpetual funding. Backtests read stored data and write report bundles under `backend/reports/` by default. [Configuration reference](backend/config/README.md)

## Experimental strategy runners

From `backend/`, use `--check` to validate a YAML without connecting to PostgreSQL. Remove it to run the backtest. Choose YAMLs from the MACD, RSI+MACD or Bollinger config directories.

```powershell
& $py ../backend_dev/run_backtest.py --config config/macd/v1/spot/BTC_USDT/1h/1x/macd_v1_btc_spot_1h.yaml --check
& $py ../backend_dev/run_all.py --help
& $py ../backend_dev/run_all.py --strategy bollinger_mr --version v1
& $py ../backend_dev/run_v5_sweep.py --config ../backend_dev/config/rsi_macd/v5/btc_1h_long_short.yaml --output ../backend_dev/reports/v5_sweep.csv --workers 4
```

`run_all.py` also accepts `macd` and `rsi_macd`. Use `--rerun` to repeat completed runs. For Bollinger v1, both runners accept `--exit-middle dynamic` or `--exit-middle fixed`. [Development runner details](backend_dev/README.md)

## Offline demo and tests

```powershell
& $py -m tests.fixtures.run_demo
& $py -m pytest -q
& $py -m pytest ../backend_dev/tests -q
```

The demo uses synthetic data. PostgreSQL integration tests require `TRADING_LAB_TEST_DATABASE_URL` pointing to a dedicated test database. [Backend details](backend/README.md)
