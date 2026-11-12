# 선물 1배 비교용 보충 설정

기존 MACD와 RSI+MACD 실험은 현물 1배 및 선물 2~5배였다.
선물 1배의 누락은 오류가 아니라 해당 설정과 결과가 없었다는 의미다.

기존 2배 YAML에서 **leverage만 1로 변경**한 38개 설정을 별도로 보존한다.
각 전략에 v1 1개, v2 SL2~10% 9개, v3 SL2~10%·TP4~20%(1:2) 9개가 있다.
모두 BTC USDT 무기한 선물 Long/Short, 1h, 2024-01-02~2026-10-31 UTC 분석이다.
기존 단건/45개 배치 설정은 변경하지 않았다.

backend_dev에서 실행:

```powershell
# 기본 v1 비교
python run_backtest.py --config config/comparison_1x/macd/v1/future/long_short/BTC_USDT_USDT/1h/1x/macd_v1_btc_future_1h_1x.yaml
python run_backtest.py --config config/comparison_1x/rsi_macd/v1/future/long_short/BTC_USDT_USDT/1h/1x/rsi_macd_v1_btc_future_1h_1x.yaml

# v1~v3 38개 전부: 이 루프는 기존 완료 건도 다시 실행한다.
$configs = Get-ChildItem -LiteralPath config/comparison_1x -Recurse -Filter *.yaml | Sort-Object FullName
foreach ($config in $configs) {
    python run_backtest.py --config "$($config.FullName)"
    if ($LASTEXITCODE -ne 0) { throw "Failed: $($config.FullName)" }
}
```

상대 경로는 backend_dev 기준이며 --check를 붙이면 DB 조회 없이 검증한다.
결과는 기존 reports/<strategy>/<version>/future/long_short/BTC_USDT_USDT/1h/1x/ 아래에 생성한다.
이 폴더는 보충 실험이며 기존 run_all 기본 설정 트리에 포함하지 않았다.
