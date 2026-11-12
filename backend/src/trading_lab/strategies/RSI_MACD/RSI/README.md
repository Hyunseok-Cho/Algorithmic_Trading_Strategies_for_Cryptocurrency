# RSI 전략 버전 안내

현재 구현된 버전은 **v1·v2·v3**다. v4는 파일 구조와 등록 정보만 준비한 placeholder이며,
선택하면 DB 조회·백테스트·보고서 생성 전에 `StrategyNotImplemented`로 중단한다.
파일을 직접 import해 생성해도 `NotImplementedError`로 중단하며 v1으로 대체 실행하지 않는다.

| 버전 | 규칙 | 상태 / 파일 |
|---|---|---|
| v1 | 기존 RSI 진입·종료·반대 방향 전환 | 구현 완료: `strategy.py` |
| v2 | v1 + 가격 기준 SL | 구현 완료: `versions/v2/strategy.py` |
| v3 | v2 + 가격 기준 TP | 구현 완료: `versions/v3/strategy.py` |
| v4 | v3 + SL 종료 후 같은 방향 재진입 제한 | placeholder: `versions/v4/strategy.py` |

v2·v3는 기존 RSI 종료·전환을 유지한다. v4에서는 SL 종료 후 Long은 RSI가
lower 이상, Short는 upper 이하로 돌아와야 같은 방향의 새 신호를 허용할 예정이다.
v4의 미래 규칙은 아직 구현된 동작을 뜻하지 않는다.
v2의 체결 순서·설정·검증은 [v2 구현 안내](../../../../../docs/rsi_v2.md)에 정리했다.
v3의 TP 설정과 봉 내부 우선순위는 [v3 구현 안내](../../../../../docs/rsi_v3.md)에 정리했다.

## 구성

```text
RSI/
├── README.md
├── strategy.py              # 기존 v1, 매매 로직 유지
├── common.py                # 새 버전의 공통 처리용 자리, 현재 문서만 존재
└── versions/
    ├── v2/strategy.py       # 기존 RSI 전략 상속, SL은 엔진에서 처리
    ├── v3/strategy.py       # 기존 RSI 전략 상속, SL·TP는 엔진에서 처리
    └── v4/strategy.py       # placeholder
```

RSI 수학은 상위 `indicators.py`, 방향 변환은 `position_policy.py`, 체결·SL/TP 감시·비용·증거금은
기존 백테스트 엔진과 포트폴리오 모듈이 담당한다. v1 코드를 공통 파일로 옮기거나 복사하지 않았다.
`common.py`는 실제 중복이 생기는 시점에 채운다.

## 선택과 결과 저장

```yaml
strategy_id: rsi
strategy_version: v1
strategy_parameters:
  period: 14
  lower: "38"
  upper: "70"
```

`strategy_version`을 생략한 기존 YAML/저장 결과는 v1으로 읽는다.
`trading-lab strategy list`에서 버전별 설명과 구현 상태를 확인할 수 있다.
v2는 stop_loss_pct가 필수이며 take_profit_pct는 설정할 수 없다.
v3는 stop_loss_pct와 take_profit_pct가 모두 필수다. v4는 현재 실행할 수 없다.

새 보고서는 다음과 같이 자동 분류한다.

```text
reports/rsi/v1/spot/BTC_USDT/1h/1x/<UTC start> - <UTC end>/
reports/rsi/v1/future/long_short/BTC_USDT_USDT/1h/5x/<UTC start> - <UTC end>/
```

동일 기간 재실행 시 짧은 식별자를 붙여 기존 결과를 보존한다. 이전 위치의 보고서는 자동 이동하지 않는다.
과거 결과를 `report export`로 다시 출력하면 새 v1 경로에 별도로 생성한다.
버전은 결과 JSON, manifest, Excel Parameters 및 DB의 기존 parameters JSON에 기록하므로 DB migration은 필요 없다.
코드 식별 정보도 계속 기록한다. 전략 버전은 공통 엔진까지 고정된 실행 환경을 의미하지 않는다.
숫자만 바꾼 실험은 같은 버전으로 두고 파라미터와 run_id로 구분한다.
v2부터 결과 폴더명에도 기간-SL-TP-P(period)-L(lower)-U(upper)를 표시한다.
예: `2024-01-01T1400Z-2026-10-31T1800Z-SL2-TPnone-P14-L38-U70`.
SL/TP 숫자는 진입 가격 대비 퍼센트이며 none은 미설정을 뜻한다. v1 이름은 기존 형식을 유지한다.
