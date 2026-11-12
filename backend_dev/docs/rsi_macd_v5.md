# RSI+MACD V5 BTC 선물

V4의 보호 청산 후 RSI 재설정 규칙을 방향별로 적용한다. 설정의 `strategy_parameters.reentry_lock`은 `none`, `short_only`, `long_only`, `both`를 지원한다. 기본값은 `short_only`다. 이 값은 잠금 대상 방향을 뜻한다. 실험의 `direction_mode`는 모든 조합에서 `long_short`다.

## 실험 범위

- Binance BTC/USDT:USDT 무기한 선물 1시간봉, 2024-01-02~2026-11-01 UTC.
- SL 2~10% (1%p 간격), TP 없음 또는 4~20% (2%p 간격). 모든 SL과 TP를 교차한다.
- 격리 레버리지 1~5배와 재진입 제한 4종을 적용해 총 1,800개다.
- 초기 1,000 USDT, 자금 배분 100%, 편도 수수료 0.05%, 슬리피지 5bps, 기존 `assume_zero` 펀딩 정책을 사용한다.

전체 비교는 PostgreSQL에서 동일 캔들과 펀딩을 한 번 읽고, 기존 보호 청산 엔진으로 각 조합을 독립 실행한다. CSV는 진행 중에도 기록되며 1,800행이 완료 조건이다. 개별 실행은 기존 CLI에서 거래 원장과 자산 곡선을 포함한 보고서를 생성한다.

`backend` 디렉터리에서 다음 명령을 실행한다.

```powershell
& ./.venv/Scripts/python.exe ../backend_dev/run_v5_sweep.py --config ../backend_dev/config/rsi_macd/v5/btc_1h_long_short.yaml --output ../Reports/RSI_MACD_V5_BTC_Futures/comparison.csv
& ./.venv/Scripts/python.exe ../backend_dev/run_backtest.py --config config/rsi_macd/v5/btc_1h_long_short.yaml
```

전체 비교를 다시 실행할 때는 새 출력 파일 경로를 지정한다.

## 방향별 SL·TP

`config/rsi_macd/v5/directional`의 5개 설정은 같은 롱숏 전략에서 롱 SL 4%·TP 12%, 숏 SL 2%·TP 4%를 적용한다. 재진입 제한은 양방향에 적용한다. `strategy_parameters.directional_protection`에 롱과 숏의 SL·TP를 모두 지정하고 공통 SL·TP는 비워 둔다. 모든 보호 가격은 포지션의 실제 진입 체결가를 기준으로 계산한다.

`backend` 디렉터리에서 1~5배를 실행한다.

```powershell
Get-ChildItem ../backend_dev/config/rsi_macd/v5/directional -Filter *.yaml | ForEach-Object {
    & ./.venv/Scripts/python.exe ../backend_dev/run_backtest.py --config $_.FullName
    if ($LASTEXITCODE -ne 0) { throw "Backtest failed: $($_.Name)" }
}
```
