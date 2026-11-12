# 향후 웹 연결 경계

이번 단계에 HTTP 앱·라우트·인증·서버는 없다. `interfaces/api/.gitkeep`는 빈 placeholder다.

- API를 나중에 추가하더라도 `application.dto.BacktestRequest`의 검증 규칙과
  `BacktestService`, `MarketDataService`, `ReportService`를 재사용한다.
- CLI의 Typer 타입·stdout·종료 코드를 application에 전달하지 않는다. HTTP request도 application에 전달하지 않는다.
- 데이터 수집은 명시적 별도 작업이며 백테스트 안에서 자동 네트워크 수집하지 않는다.
- 긴 실행은 향후 job worker로 옮길 수 있지만 DB transaction을 네트워크/계산 전체에 걸쳐 유지하지 않는다.
- BacktestResult JSON은 Decimal 문자열과 UTC 시각, run UUID, 입력·가정·경고·버전 정보를 보존한다.
- hedge·미구현 전략·strict funding 결측을 HTTP에서도 동일하게 오류 처리해야 한다.

구체적 endpoint 경로·응답 status·인증·배포 설계는 이번 구현 범위에 포함하지 않는다.
