# 백테스트 YAML 구성

실험 설정은 결과 보고서와 동일한 분류를 사용한다.
2024-01-01~2026-10-31 전체 기간의 BTC·ETH·SOL 일괄 실험은
`batches/20240101_20261031/rsi/`에 별도로 생성했다([자동화 안내](../docs/backtest_batch.md)).
기존 `rsi/` 아래 단건 실험은 보존한다.

```text
config/
├── examples/                       # 일반 시작 템플릿, 기존 위치 유지
└── rsi/
    ├── v1/
    │   ├── spot/BTC_USDT/1h/1x/
    │   └── future/
    │       ├── long_only/BTC_USDT_USDT/1h/5x/
    │       ├── short_only/BTC_USDT_USDT/1h/5x/
    │       └── long_short/BTC_USDT_USDT/1h/
    │           ├── 1x/
    │           └── 5x/
    ├── v2/
        └── future/
            ├── long_only/BTC_USDT_USDT/1h/1x/
            ├── short_only/BTC_USDT_USDT/1h/1x/
            └── long_short/BTC_USDT_USDT/1h/1x/
    └── v3/
        └── future/
            ├── long_only/BTC_USDT_USDT/1h/1x/
            ├── short_only/BTC_USDT_USDT/1h/1x/
            └── long_short/BTC_USDT_USDT/1h/1x/
```

v2의 각 방향 폴더에는 SL 2%(`_sl2.yaml`)와 SL 10%(`_sl10.yaml`) 설정이 있다.
v3의 각 방향 폴더에는 SL 10%·TP 20%(`_sl10_tp20.yaml`) 비교 설정이 있다.
SL 2% 파일에만 구분 접미사를 추가했으며 모든 YAML의 설정 내용은 이동 전과 동일하다.
파일명과 디렉토리는 사람이 구분하기 위한 분류이고, 실제 실행은 YAML 내부 값이 결정한다.
새 설정을 추가할 때 분석 기간과 비용 등 전체 입력값도 확인한다.

## 실행 예시

backend 디렉토리에서 실행한다. SL 10%, 1배, RSI v2 Long/Short:

```powershell
$configPath = "config/rsi/v2/future/long_short/BTC_USDT_USDT/1h/1x/rsi_v2_btc_perpetual_1h_1x_long_short_sl10.yaml"
trading-lab backtest run --config "$configPath"
```

SL 2%를 실행하려면 같은 폴더의 `_sl2.yaml` 파일을 선택한다.
기존 루트 파일은 이동했으므로 예전 `--config config/rsi_....yaml` 대신 새 경로를 사용한다.
보고서 경로는 기존 보고서 생성 규칙을 따르며 YAML을 옮겨도 이미 생성된 보고서는 이동하지 않는다.

일반 예제 `examples/btc_spot_1h.yaml`, `examples/btc_perpetual_1h.yaml`은 그대로다.
후자는 미구현 결합 전략과 미검증 strict 펀딩 설정을 포함한 템플릿이므로 바로 실행하는 실험 설정이 아니다.
