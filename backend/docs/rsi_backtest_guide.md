# RSI 백테스트 실행 및 분석

명령은 가상환경이 활성화된 backend 디렉토리에서 실행한다.
PostgreSQL 컨테이너가 실행 중이고 migration 적용이 완료되어 있어야 한다.

## 1. 저장할 타임프레임 선택

현재 CLI는 Binance에서 타임프레임별 OHLCV를 받아 PostgreSQL에 별도로 저장한다.
1h 데이터만 저장한 상태에서 5m 또는 4h를 지정한다고 자동 변환되지 않는다.
필요한 타임프레임을 각각 sync한 뒤 설정 파일의 timeframe을 선택한다.
이미 저장한 데이터는 전략마다 다시 수집할 필요가 없다.
현물과 무기한 선물 가격 데이터는 별도다.

원본 1m 데이터에서 임의의 큰 타임프레임을 만드는 리샘플링 기능은 아직 없다.
그 기능을 추가한다면 UTC 경계, 누락 봉, 미완료 구간을 검증하면서
open=first, high=max, low=min, close=last, volume=sum으로 집계해야 한다.
1h로부터 1m 가격 경로는 복원할 수 없다.
2021년부터 2026-10-31까지는 대략 1h 5.1만 개, 1m 307만 개의 봉이므로
첫 실험은 1h 데이터로 진행하고 다른 주기를 추가하는 편이 간단하다.

## 2. 2021년부터 실행 시점까지 1h 수집

종료 시각을 한 번 고정하여 sync, status, 백테스트 설정에 동일하게 사용한다.
현재 진행 중인 1h 봉은 제외한다. 날짜만 지정하면 UTC 00:00이며 종료는 제외다.

```powershell
$endUtc = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:00:00Z")
$endUtc
trading-lab data sync --symbol BTC/USDT --timeframe 1h --from 2021-01-01 --to "$endUtc" --limit 1000
if ($LASTEXITCODE -ne 0) { throw "Data sync failed or has missing ranges; inspect the output." }
trading-lab data status --symbol BTC/USDT --timeframe 1h --from 2021-01-01 --to "$endUtc"
```

complete=true, missing_bar_count=0인지 확인한다.
중간에 실패하면 동일한 종료 시각으로 sync를 다시 실행하여 저장된 구간을 재사용한다.
API에서 과거 데이터를 제공하지 않는 구간은 임의로 보간하거나 누락을 무시하지 않는다.

분석 시작을 2021-01-01 00:00 UTC로 하려면 그 이전 준비 데이터도 필요하다.
RSI 14의 1h 실험에는 이전 14개 봉이 필요하므로 하루를 추가 수집한다.

```powershell
trading-lab data sync --symbol BTC/USDT --timeframe 1h --from 2020-12-31 --to 2021-01-01
```

4h와 1d를 실험하려면 해당 주기도 따로 수집한다. 아래 시작 날짜는 RSI 14의 준비 기간을 포함한다.
각 주기의 마지막 완료 봉 경계는 --to를 생략하면 CLI가 계산한다.
재현 실험에서는 출력된 데이터 범위의 end를 해당 설정에 기록한다.

```powershell
trading-lab data sync --symbol BTC/USDT --timeframe 4h --from 2020-12-01 --limit 1000
trading-lab data sync --symbol BTC/USDT --timeframe 1d --from 2020-12-01 --limit 1000
```

## 3. 설정 복사와 실행

```powershell
Copy-Item config/examples/btc_spot_1h.yaml config/rsi/v1/spot/BTC_USDT/1h/1x/rsi_btc_spot_1h.yaml
```

복사한 YAML에서 다음을 설정한다. end_time에는 위에서 출력한 $endUtc 값을 직접 입력한다.

```yaml
start_time: "2021-01-01T00:00:00Z"
end_time: "여기에 수집에 사용한 UTC 종료 시각"
timeframe: 1h
strategy_id: rsi
strategy_version: v1
strategy_parameters:
  period: 14
  lower: "38"
  upper: "70"
warmup_bars: 14
```

예제의 fee_rate_open/close=0.001, slippage_bps=5는 실험 가정이며 역사적 실제 비용의 보장이 아니다.
준비 봉은 지표 계산에만 사용하고 분석 기간의 주문과 성과에는 포함하지 않는다.

```powershell
trading-lab backtest run --config config/rsi/v1/spot/BTC_USDT/1h/1x/rsi_btc_spot_1h.yaml
```

출력의 report_directory를 연다. 예시 경로:

```text
reports/rsi/v1/spot/BTC_USDT/1h/1x/2021-01-01T00-00-00Z - 2026-10-31T12-00-00Z/
  report.xlsx
  summary.json
  trades.csv
  equity_curve.csv
  daily_statistics.csv
  result.json
  manifest.json
```

예시 종료 12:00은 실제 수집 시각으로 바꾼다. 모든 이름의 시각은 UTC이고 end는 제외다.
같은 구간을 재실행/재출력하면 폴더명에 __와 짧은 식별자가 붙는다.
run_id와 전체 설정은 result.json/manifest.json에 남는다.
기존 날짜별 보고서는 이동하거나 삭제하지 않는다.

## 선물 5배 방향별 비교

2024-01-01 14:00 UTC부터 2026-10-31 18:00 UTC 직전까지 현물 실험과 같은 분석 기간을 사용한다.
세 설정은 방향 외 모든 조건이 같으며 RSI 14/38/70, 초기 자금 1000 USDT,
allocation_pct=100, leverage=5, one_way/isolated, 수수료 편도 0.0005, 슬리피지 5bps다.
allocation_pct=100은 가용 자금 전체를 증거금 배분 대상으로 삼는 설정이며,
레버리지 5는 해당 증거금에 대한 명목 노출 배율이다. 진입 비용도 엔진이 반영한다.
손절/익절은 별도로 설정하지 않았다. 비용은 예시 가정이며 역사적 실제 Binance 비용의 보장이 아니다.

```powershell
trading-lab backtest run --config config/rsi/v1/future/long_only/BTC_USDT_USDT/1h/5x/rsi_btc_perpetual_1h_5x_long_only.yaml
trading-lab backtest run --config config/rsi/v1/future/short_only/BTC_USDT_USDT/1h/5x/rsi_btc_perpetual_1h_5x_short_only.yaml
trading-lab backtest run --config config/rsi/v1/future/long_short/BTC_USDT_USDT/1h/5x/rsi_btc_perpetual_1h_5x_long_short.yaml
```

보고서는 reports/rsi/v1/future/<long_only|short_only|long_short>/BTC_USDT_USDT/1h/5x/<UTC start> - <UTC end>/에 저장한다.
현물은 reports/rsi/v1/spot/BTC_USDT/1h/1x 아래에 저장한다. 기존 보고서는 자동 이동하지 않는다.
v2는 RSI 신호와 SL을 함께 사용하며 [v2 실행 안내](rsi_v2.md)를 참조한다.
v3는 RSI와 SL·TP를 함께 사용한다([v3 실행 안내](rsi_v3.md)). v4는 placeholder이며 실행을 중단한다.
기존의 rsi_btc_perpetual_1h.yaml 대신 위의 완전한 세 설정을 사용한다.

funding_mode=assume_zero이므로 저장된 펀딩 이벤트는 적용하되 누락된 이벤트는 0으로 가정한다.
과거 mark price가 없으면 완료된 거래 가격 봉으로 대체한다. 청산은 거래 OHLC와 고정 유지증거금률의 근사다.
따라서 이 결과는 방향과 5배 레버리지의 개발용 비교이며 엄밀한 역사적 펀딩/청산 재현 결과는 아니다.
Long/Short는 반대 신호에서 포지션을 전환하는 one_way로, 동시 양방향 보유인 hedge와 다르다.

## 4. 결과를 읽는 순서

1. DataQuality와 Assumptions에서 데이터 범위, 누락, 비용 및 체결 가정을 확인한다.
2. Trades의 첫 거래 몇 건을 가격/RSI와 대조한다. 신호는 완료된 봉에서 판단하고 다음 봉 시가에 체결한다.
3. Summary의 total_return_pct와 buy_and_hold_return_pct를 비교한다.
4. max_drawdown_pct로 손실 구간의 크기를 확인하고 EquityCurve와 DailyStatistics로 시기를 살펴본다.
5. completed_trades, win_rate_pct, average_profit/loss, profit_factor, expectancy를 함께 확인한다.
6. total_fees와 거래 빈도를 확인한다. 승률만으로 전략 성과를 판단하지 않는다.

거래 0건이면 매수 조건 발생 여부와 데이터/준비 기간부터 확인한다.
NA/null인 지표는 summary의 na_reasons를 확인하며 임의로 0으로 바꾸지 않는다.
Excel은 약 15자리 유효숫자 표시 제한이 있어 정확한 값은 JSON/CSV로 확인한다.
RSI/MACD/결합 전략은 같은 시장, 분석 기간, 타임프레임, 초기 자금, 비용 및 체결 규칙으로 비교한다.
전체 결과 외에 연도별 결과와 별도의 검증 기간을 확인하고 파라미터 변경은 새 실험으로 기록한다.
