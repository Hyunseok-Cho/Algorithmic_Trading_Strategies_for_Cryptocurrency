# MACD 개발용 백엔드

현재 RSI 배치를 유지하면서 MACD를 개발하기 위한 별도 디렉토리다.
기존 backend/src, 레지스트리, YAML, 가상환경 패키지를 수정하지 않는다.
EMA·MACD 지표·전략·YAML·실행 파일·테스트만 이 폴더에서 관리한다.

## 구조와 재사용

```text
backend_dev/
├── indicators/ema.py
├── indicators/macd.py
├── strategies/macd/v1.py
├── strategies/macd/v2.py
├── strategies/macd/v3.py
├── backtesting/             # v2 SL 전용 개발 실행 연결
├── reporting/               # 배치에 영향을 주지 않는 개발용 보고서·Excel 출력
├── config/macd/v1/
│   ├── spot/BTC_USDT/1h/1x/
│   └── future/long_short/BTC_USDT_USDT/1h/<2x|3x|4x|5x>/
├── run_backtest.py
├── tests/
└── reports/
```

거래 컨텍스트, 방향 정책, DB 조회, 포트폴리오·비용·성과 계산은 기존 trading_lab 모듈을 import한다.
보호 SL/TP의 실행 연결과 빠른 Excel 보고서는 개발 폴더에 분리하며 JSON/CSV 도우미는 재사용한다.
실행 파일은 개발 전략 객체를 BacktestService에 직접 전달하므로 기존 레지스트리를 변경하지 않는다.
DB에서는 가격·펀딩을 읽기만 하며 run_store를 전달하지 않아 기존 run/trade 테이블에도 쓰지 않는다.
보고서와 코드 지문은 backend_dev/reports에 저장한다. 데이터가 부족해도 자동 수집하지 않는다.

## MACD v1 정의

- EMA는 첫 N개 입력의 단순평균으로 시작한 뒤 alpha=2/(N+1)로 갱신한다.
- MACD=EMA12(close)-EMA26(close), Signal=EMA9(MACD), Histogram=MACD-Signal이다.
- Histogram의 이전 값 <= 0, 현재 값 > 0이면 상승 신호다.
- 이전 값 >= 0, 현재 값 < 0이면 하락 신호다. 정확히 0인 현재 값에는 신호가 없다.
- 현물은 상승 교차에서 매수, 하락 교차에서 청산한다.
- 선물은 상승 교차에서 Long, 하락 교차에서 Short 목표로 전환한다(one_way).
- TP·SL·재진입 잠금은 없다. 첫 계산값은 이전 값으로 저장만 한다.
- warmup 중에도 지표와 이전 Histogram은 갱신하지만 주문은 만들지 않는다.
- 이미 처리한 봉의 반복 호출에는 다시 신호를 만들지 않는다.

기본값은 12/26/9이며 첫 완성 Histogram에는 종가 34개가 필요하다.
첫 분석 봉에서도 이전 Histogram과 비교할 수 있도록 **이전 준비 봉 34개**를 요구한다.
이는 계산에 필요한 최소 초기화 길이이며 초기 EMA의 영향이 완전히 사라졌다는 뜻은 아니다.
다른 플랫폼의 EMA 초기화 방식·준비 데이터에 따라 초기 수치가 달라질 수 있다.

## YAML의 공통 조건

BTC, 1h, 초기 자금 1000 USDT, 배분 100%, 슬리피지 5bps다.
현물 편도 수수료 0.1%, 선물 0.05%는 비교용 가정이다.
현물은 1배 Long only, 선물은 Long/Short 2·3·4·5배 설정을 각각 제공한다.
선물은 isolated와 assume_zero 펀딩을 사용하며 기존 청산·과거 mark price 근사 한계가 적용된다.

분석 기간은 **2024-01-02 00:00 ~ 2026-11-01 00:00 UTC(종료 제외)**다.
준비 데이터는 2023-12-31 14:00부터 필요하다. RSI 배치를 위해 이미 수집한
2023-12-31 10:00 이후 데이터만 사용하도록 시작 날짜를 정했다.
RSI 배치와 분석 시작일이 하루 다르므로 최종 비교에서는 기간을 맞춰야 한다.
배치 중 추가 sync/refresh나 migration을 실행하지 않는다.

## 실행

기존 backend/.venv를 그대로 사용할 수 있으며 추가 패키지 설치는 필요 없다.
명령은 가상환경이 활성화된 **backend** 디렉토리 기준이다.
--config 상대 경로는 작업 디렉토리가 아니라 backend_dev 기준으로 해석한다.
개발용 출력 루트는 backend_dev/reports로 고정된다.

```powershell
# 설정만 확인: DB 접근 없음
python ../backend_dev/run_backtest.py --config config/macd/v1/spot/BTC_USDT/1h/1x/macd_v1_btc_spot_1h.yaml --check

# 현물
python ../backend_dev/run_backtest.py --config config/macd/v1/spot/BTC_USDT/1h/1x/macd_v1_btc_spot_1h.yaml

# 선물 2~5배, 하나씩 순차 실행
foreach ($leverage in 2..5) {
    $configPath = "config/macd/v1/future/long_short/BTC_USDT_USDT/1h/${leverage}x/macd_v1_btc_future_1h_${leverage}x.yaml"
    python ../backend_dev/run_backtest.py --config "$configPath"
    if ($LASTEXITCODE -ne 0) { throw "MACD development run failed: ${leverage}x" }
}
```

기존 trading-lab CLI의 macd는 여전히 미구현 상태다. 위 개발 실행 파일을 사용해야 한다.
MACD v2(SL 추가)의 45개 YAML과 실행 방법은 [v2 안내](docs/macd_v2.md)를 참고한다.
MACD v3(SL·TP)의 45개 1:2 조합과 일괄 실행은 [v3 안내](docs/macd_v3.md)를 참고한다.
MACD 방향 필터와 기존 RSI를 결합한 v1은 [RSI+MACD 안내](docs/rsi_macd_v1.md)를 참고한다.
결합 전략의 SL·TP 버전과 90개 설정은 [RSI+MACD v2·v3 안내](docs/rsi_macd_v2_v3.md)를 참고한다.
BTC 선물 재진입 제한과 방향별 12개 설정은 [RSI+MACD v4 안내](docs/rsi_macd_v4.md)를 참고한다.
방향별 재진입 제한과 SL·TP·레버리지 전수 비교는 [RSI+MACD v5 안내](docs/rsi_macd_v5.md)를 참고한다.
수수료를 보정해 배율별 진입 명목액을 맞춘 실험은 [RSI+MACD v6 안내](docs/rsi_macd_v6.md)를 참고한다.
개발용 Excel 출력은 행 개수 검사 비용을 줄인 별도 출력기를 사용하며 기존 레이아웃을 유지한다.
읽기 전용 DB 재사용으로 RSI 배치의 데이터·코드를 바꾸지는 않지만 동시 실행은 CPU·디스크 자원을 공유한다.

## 테스트

```powershell
$devTestTemp = Join-Path $PWD ("../backend_dev/reports/pytest-" + [guid]::NewGuid().ToString("N"))
python -m pytest ../backend_dev/tests -q --basetemp "$devTestTemp"
```

테스트는 합성 가격으로 실행하며 DB·네트워크를 사용하지 않는다.
RSI 배치가 끝난 뒤에는 지표·전략·테스트·등록 변경을 검토해 기존 backend로 반영한다.
