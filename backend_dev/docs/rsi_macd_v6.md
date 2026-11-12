# RSI+MACD V6 명목액 일치 실험

BTC/USDT:USDT 무기한 선물 1시간봉 롱숏에서 V5 방향별 SL·TP와 양방향 RSI 재진입 제한을 사용한다. 롱 SL 4%·TP 12%, 숏 SL 2%·TP 4%다. 기간, 비용, 펀딩 정책은 V5 방향별 실험과 같다.

CLI가 적용하는 자금 배정률은 `100 × (1 / leverage + fee_rate_open) / (1 + fee_rate_open)`이다. 배정 예산은 진입 직전 가용 현금에 배정률을 곱한 값이며 증거금과 진입 수수료를 포함한다. 공식은 가용 현금이 같을 때 1배의 진입 명목액을 재현하며 체결 계산에는 기존 엔진의 반올림 규칙을 적용한다. 실제 배정률은 `--check` 출력과 개별 보고서 요청 항목에 기록한다.

`backend` 디렉터리에서 실행한다.

```powershell
Get-ChildItem ../backend_dev/config/rsi_macd/v6 -Filter *.yaml | ForEach-Object {
    & ./.venv/Scripts/python.exe ../backend_dev/run_backtest.py --config $_.FullName
    if ($LASTEXITCODE -ne 0) { throw "Backtest failed: $($_.Name)" }
}
```
