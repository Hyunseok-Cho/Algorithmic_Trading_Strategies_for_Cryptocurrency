# RSI+MACD V4 선물 백테스트

BTC/USDT:USDT 무기한 선물 1시간봉에서 기존 RSI·MACD 진입 조건과 보호 청산을 사용한다. 손절 또는 익절 후에는 청산한 방향에 한해 재진입을 제한한다.

- 롱 청산 후 종가 RSI가 38 이상으로 올라오면 롱 진입을 다시 허용한다. 실제 진입은 RSI 38 미만과 상승 MACD 조건을 다시 충족해야 한다.
- 숏 청산 후 종가 RSI가 70 이하로 내려오면 숏 진입을 다시 허용한다. 실제 진입은 RSI 70 초과와 하락 MACD 조건을 다시 충족해야 한다.
- 보호 청산이 발생한 봉의 종가부터 RSI 리셋을 평가한다. 반대 방향 신호는 별도로 평가하며, 잠금에 걸린 반전은 기존 포지션의 청산만 실행한다.
- SL·TP는 진입 체결가 대비 가격 비율이다. 일반 RSI 청산과 강제 청산은 재진입 잠금을 걸지 않는다.

롱 전용·숏 전용·롱숏에 각각 SL 2%, SL 4%, SL 2% + TP 4%, SL 4% + TP 8%를 적용해 총 12개 설정을 제공한다. 기존 결과에서 살펴본 2%·4%를 공통으로 사용해 같은 손절 폭에서 익절 추가와 재진입 제한의 효과를 따로 비교할 수 있다.

기간은 2024-01-02 00:00부터 2026-11-01 00:00 UTC 직전까지다. 준비 34봉, 초기 1,000 USDT, 배분 100%, 1배 격리 증거금, 편도 수수료 0.05%, 슬리피지 5bps다. 기존과 같은 `assume_zero` 펀딩 모드를 사용한다. 저장된 이벤트를 반영하고 누락 이벤트를 0으로 처리한다.

아래 명령은 `backend` 디렉터리에서 실행한다. DB 없이 설정만 확인하려면 실행 명령에 `--check`를 추가한다.

```powershell
Get-ChildItem ../backend_dev/config/rsi_macd/v4 -Recurse -Filter *.yaml | ForEach-Object {
    & ./.venv/Scripts/python.exe ../backend_dev/run_backtest.py --config $_.FullName
    if ($LASTEXITCODE -ne 0) { throw "V4 backtest failed: $($_.FullName)" }
}
```

결과는 `backend_dev/reports/rsi_macd/v4/future` 아래에 방향과 SL·TP별로 저장한다. 비교용으로 동일한 YAML의 전략 버전만 SL 전용에서는 `v2`, SL·TP에서는 `v3`로 바꾸면 재진입 잠금이 없는 대조군을 재현할 수 있다.
