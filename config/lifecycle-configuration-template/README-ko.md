---
translation_of: README.md
translation_source_sha: 0def06d63c13b695be9f1b1373929a19cea80aaa
translation_revised: 2026-10-18
---
# 고객 수명 주기 구성 템플릿

버전 관리되는 이 디렉터리에서 계획된 고객 소유 구성 저장소를 자리 표시자로 확인할 수 있습니다.
기존 순수 검증기로 주석, 계층과 비밀 참조를 오프라인에서 검사할 수 있습니다.
이 디렉터리는 서명된 패키지나 배포 가능한 설치 구성이 아닙니다.

> **경계:** 실제 값을 추가하기 전에 이 디렉터리를 고객의 비공개 저장소로 복사하세요.
> 실제 값을 upstream FDAI에 커밋하지 마세요. 서명, 이전 개정 검증, 봉인과 Hub 패키지
> 가져오기는 아직 구현되지 않았으므로 원본 디렉터리를 Hub에 업로드하지 마세요.

## 파일

| 파일 | 용도 |
|------|------|
| `release-schema.yaml` | 오프라인 검사를 위한 합성 Release 스키마이며 신뢰된 Release가 아님 |
| `installations/example-installation/installation.yaml` | 채널, 버전 범위, 시간 구간과 Entity 목록 예제 |
| `installations/example-installation/environment.yaml` | 권한과 무관한 값과 Key Vault 참조 |
| `installations/example-installation/sealed.yaml` | 향후 패키지 생성기가 봉인해야 할 평문 자리 표시자 식별자 |
| `installations/example-installation/entities/core.yaml` | 넓은 Release 범위와 더 구체적인 재정의 범위 |

식별자, 엔드포인트, 자격 증명 모음 이름과 리전은 자리 표시자입니다. `DEV`, 버전 범위,
복제본 수와 UTC 시간 구간은 일반 예제 설정이며 선택된 배포 대상이 아닙니다.
`sealed.yaml`은 향후 패키지 생성기의 입력 이름일 뿐, 현재 내용이 암호화되어 있다는 뜻은 아닙니다.

## 예제 검증

FDAI checkout에서 기존 잠금 개발 환경으로 실행하세요.

```bash
uv run --no-sync pytest -q --no-cov \
  tests/integration/test_lifecycle_configuration_template.py
```

검사는 기존 배포 CLI 검증기를 호출합니다. Release `1.5.2`에는 복제본 3개를 선택하고,
범위 밖의 `2.0.0`, 권한 키와 비밀 리터럴을 차단합니다. 통과 결과는 해당 오프라인 계약만
검증합니다. 키 등록, 패키지 서명이나 가져오기, Plan 인가, 실제 리전 검증 또는 워크로드
관측을 수행하지 않습니다.

## 값의 소유 경계 유지

- 일반 구성은 `environment.yaml`이나 Entity 재정의에 둡니다.
- 식별자는 비공개 `sealed.yaml` 입력에만 둡니다. 검토된 봉인 및 가져오기 경로가 생기기
  전에는 Hub에 보내지 마세요.
- 자격 증명은 Key Vault에 저장하고 값 대신 참조만 포함하세요.
- 승인 정책, 승격, 상시 권한과 실행기 신원은 구성에서 제외하세요.

## 다음 단계

| 알아볼 내용 | 참고 문서 |
|-------------|-----------|
| 키 보관과 등록 선행 조건 | [구성 키 등록](../../docs/runbooks/lifecycle-configuration-key-onboarding-ko.md) |
| 구성 계약과 남은 구현 | [수명 주기 구성](../../docs/roadmap/deployment/lifecycle-configuration-ko.md) |
