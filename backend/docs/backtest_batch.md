# BTC·ETH·SOL RSI 일괄 실험

## 생성한 YAML

기간은 **2024-01-01 00:00 ~ 2026-11-01 00:00 UTC(종료 제외)**다.
2026-10-31 전체를 포함하며, 기존 단건 실험의 2024-01-01 14:00 ~ 2026-10-31 18:00과 다르다.
1h RSI 준비용 14개 봉을 위해 수집 시작은 2023-12-31 10:00 UTC다.

| 버전 | 자산 | 시장·방향 | 레버리지 | SL | TP | 개수 |
|---|---|---|---|---|---|---:|
| v1 | BTC·ETH·SOL | 현물 Long only | 1배 | 없음 | 없음 | 3 |
| v1 | 동일 | 선물 Long only·Short only·Long/Short | 1~5배 | 없음 | 없음 | 45 |
| v2 | 동일 | 선물 세 방향 | 1~5배 | 2~10%, 1% 간격 | 없음 | 405 |
| v3 | 동일 | 선물 세 방향 | 1~5배 | 2~10%, 1% 간격 | SL×2: 4~20% | 405 |
| **합계** | | | | | | **858** |

v3는 (SL2, TP4), (SL3, TP6), …, (SL10, TP20)의 **9쌍**이다.
SL과 TP의 모든 교차 조합을 생성한 것이 아니다.

공통 조건은 초기 1000 USDT, 배분 100%, RSI 14/38/70, 1h, 슬리피지 5bps,
편도 수수료 현물 0.1%·선물 0.05%다. 비용은 실험 가정이다.
선물은 one_way/isolated, assume_zero 펀딩을 사용한다. 저장된 펀딩은 반영하고 누락 이벤트는 0으로 가정한다.
펀딩 이력 수집·완전성 검증을 새로 수행하는 배치는 아니며, 모형의 역사적 펀딩·청산 한계는 유지한다.

```text
config/batches/20240101_20261031/rsi/
├── v1/
│   ├── spot/<symbol>/1h/1x/rsi_v1.yaml
│   └── future/<direction>/<symbol>/1h/<leverage>x/rsi_v1.yaml
├── v2/future/<direction>/<symbol>/1h/<leverage>x/rsi_v2_SL2_TPnone.yaml
└── v3/future/<direction>/<symbol>/1h/<leverage>x/rsi_v3_SL2_TP4.yaml
```

각 폴더에는 해당 SL·TP 설정들이 들어 있다. 기존 config/rsi 단건 설정과 examples는 변경하지 않았다.
실제 거래 규칙과 출력 경로는 YAML 내부 값이 결정한다.

## 1. 데이터 수집

모든 명령은 가상환경이 활성화된 backend에서 실행한다. Docker DB와 migration 준비를 마친 상태가 전제다.
BTC·ETH·SOL마다 현물과 선물 가격을 별도로 저장한다. 수집은 누락만 요청하므로 반복 실행할 수 있다.
진행 중인 봉은 sync가 제외하므로 종료 시각까지 모든 봉이 완료된 뒤 전체 범위가 채워진다.

```powershell
docker compose up -d --wait db

$dataFrom = "2023-12-31T10:00:00Z"
$dataTo = "2026-11-01T00:00:00Z"

foreach ($coin in @("BTC", "ETH", "SOL")) {
    trading-lab data sync --market spot --symbol "${coin}/USDT" --timeframe 1h --from "$dataFrom" --to "$dataTo" --limit 1000
    if ($LASTEXITCODE -ne 0) { throw "Spot sync failed or partial: $coin" }

    trading-lab data sync --market perpetual --symbol "${coin}/USDT:USDT" --timeframe 1h --from "$dataFrom" --to "$dataTo" --limit 1000
    if ($LASTEXITCODE -ne 0) { throw "Perpetual sync failed or partial: $coin" }
}
```

자산별 누락은 data status로 확인할 수 있다. 자동화도 실행 전에 6개 데이터셋의 준비 기간 포함 완전성을 검사한다.
누락·미수집 시장이 있으면 백테스트를 시작하지 않는다. 누락을 임의로 보간하거나 건너뛰지 않는다.
거래소에서 제공하지 않는 구간이 있으면 해당 문제를 해결하거나 실험 기간을 명시적으로 조정해야 한다.

## 2. 확인 및 실행

자동화 파일은 scripts/run_backtest_batch.py 하나다. 기본값은 위 배치 폴더 전체다.
Python subprocess로 현재 가상환경의 기존 CLI를 한 건씩 실행하며, 데이터 다운로드는 하지 않는다.

```powershell
# YAML만 읽고 개수·버전 확인: DB와 백테스트를 실행하지 않음
python scripts/run_backtest_batch.py --plan

# 실제 한 건 실행: 성공 건은 나중에 전체 실행 시 건너뜀
python scripts/run_backtest_batch.py --limit 1

# 전체 순차 실행 또는 중단 후 재개
python scripts/run_backtest_batch.py
```

858개는 각각 Excel·CSV·JSON 보고서를 생성하므로 시간과 저장 공간이 필요하다.
첫 한 건의 실행 시간과 보고서 크기를 확인한 뒤 전체 실행한다.
배치 중에는 YAML·전략 코드·DB 데이터를 수정하거나 data sync/refresh를 병행하지 않는다.
입력 변경이 감지된 실행은 성공으로 기록하지 않으며, 새 명령으로 다시 계획해야 한다.

## 3. 기록·재개

```text
reports/batches/rsi_20240101_20261031/
├── state.json           # 설정별 최신 상태, 재개 기준
├── summary.csv          # 전체 실험 비교표, UTF-8 BOM
└── logs/                # 각 CLI 실행의 stdout·stderr
```

개별 상세 보고서는 기존 reports/rsi/<version>/... 경로에 계속 생성한다.
비교 CSV에는 자산·방향·배율·SL·TP, 수익률·낙폭·거래 수·수수료·펀딩,
SL/TP/강제 청산 종료 건수, run_id와 보고서 경로를 포함한다. 종료 사유는 거래별 실제 기록에서 집계한다.

성공한 실험은 설정·모형·코드·가격/펀딩 데이터가 같고, 결과 파일 해시까지 온전할 때만 건너뛴다.
실패·중단 건은 다음 실행에서 재시도한다. 일반 실패는 로그에 남기고 다음 YAML을 진행한다.
Ctrl+C로 중단하면 현재 건은 재시도 대상이다. 보고서 생성 직후 기록 전 강제 종료된 건은 재실행될 수 있으나
기존 보고서를 덮어쓰지는 않는다. 같은 상태 폴더의 동시 실행은 OS 잠금으로 차단한다.
CSV를 Excel에서 열어 둔 상태로 실행하면 파일 갱신이 막힐 수 있으므로 실행 중에는 닫아 둔다.

## 추가 옵션

```powershell
python scripts/run_backtest_batch.py --version v3 --symbol BTC --plan
python scripts/run_backtest_batch.py --version v1 --symbol BTC --market spot --limit 1
python scripts/run_backtest_batch.py --rerun
```

--limit은 완료 건을 건너뛴 뒤 **새로 실행할 최대 건수**다.
--rerun은 같은 성공 설정도 다시 실행하며 기존 보고서는 보존한다.
--config-root로 다른 YAML 트리를 지정할 수 있다. --state-dir로 별도 실행 기록 폴더를 선택할 수 있다.
기본 폴더의 YAML을 모두 재생성하려면 --generate-only를 사용한다. 동일 설정은 보존하며 내용이 다른 파일은
덮어쓰지 않고 중단한다. 생성기는 현재 v1~v3 조합만 만든다.
실행기는 레지스트리에서 구현 상태를 확인하므로 이후 새 버전의 YAML이 트리에 추가되고 구현 등록되면 실행한다.
현재 미구현 v4 및 다른 미구현 전략은 건너뛰며, 알 수 없는 전략이나 잘못된 YAML은 계획 단계에서 오류를 낸다.

이번 기간에서 가장 수익률이 높은 행을 찾는 것만으로 전략 검증이 끝나는 것은 아니다.
조절에 사용하지 않은 별도 기간의 검증과 비용·펀딩 가정 검토를 후속 실험으로 남긴다.
