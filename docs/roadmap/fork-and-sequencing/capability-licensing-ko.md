---
title: Capability 라이선싱
translation_of: capability-licensing.md
translation_source_sha: 510e0aae56fd26855cd2ad81969c82b7e594204c
translation_revised: 2026-09-14
---
# 기능 라이선싱

다운스트림 분포는 소스가 아니라 이미지로 고객에게 전달되는 경우가 많습니다. 포크를
빌드하고, 이미지를 넘기고, 그 이미지는 게시자가 도달할 수 없는 네트워크 안에서 돕니다. 이 문서는
그런 분포가 비밀을 배포하지 않고, 네트워크 호출 없이, 그리고 결코 자율성을 높이는 경로가
되지 않으면서 권한을 활성화하는 방법을 정의합니다.

> **범위:** 메커니즘은 업스트림 소유이며 모든 분포에서 동일합니다. 공개 키는 배포판
> 아티팩트이고 토큰은 배포 설정입니다. 이 문서는 상업 조건, 가격, 철회 서비스를 정의하지
> 않습니다.

## 한눈에 보는 설계

순진한 형태 - 빌드 시 시리얼 번호를 이미지에 심기 - 는 곧바로 실패합니다. 이미지는 tar 파일이므로
계층에 심은 것은 전달받은 사람이 그대로 읽습니다. 또한
[security-and-identity-ko.md](../architecture/security-and-identity-ko.md)의 시크릿 계약와도
충돌합니다. 비밀은 환경변수 또는 마운트된 시크릿으로만 들어와야 합니다.

그래서 라이선싱은 비대칭을 뒤집습니다. 리포지토리가 framework-surface 매니페스트와 offline 키트에
이미 적용 중인 패턴을 그대로 재사용합니다.

| 위치 | 무엇 | 왜 안전한가 |
|------|------|-------------|
| 이미지 안 (읽기 전용) | **공개** 검증 키 | 공개 키는 비밀이 아니며 공개해도 비용이 없습니다 |
| 이미지 밖 (배포 설정) | **서명된 license 토큰** | 환경변수나 마운트 시크릿에 들어가는 ASCII 문자열 하나이며, 비공개 키 없이는 위조 불가입니다 |

읽기 전용 루트 파일시스템은 장애물이 아닙니다. 활성화 상태를 이미지에 쓰지 않기 때문입니다.
토큰은 통상의 시크릿 경로로 들어오고, 지속 기록이 필요하면 상태 저장소에 둡니다.

## 영속적인 무키 Trial 목표

연결된 소스 배포는 인증된 배포 기록 작성자를 통해 첫 활성화 때 30일 Trial 하나를 초기화합니다.
설치 및 배포 바인딩은 소스 버전과 이미지 digest에 종속되지 않으므로 일반 업그레이드나 재시작으로
Trial을 갱신하지 않습니다. 활성화 시각은 변경되지 않습니다. 영속 관측마다 리비전과 마지막 UTC
관측 시각을 갱신합니다. 시간이 역행하면 새 Trial이 아니라 영속적인 차단 상태를 기록합니다.
만료 시각 이후의 첫 관측부터 새로운 변경 요청을 차단하되 관찰, 진단, 감사, 내보내기, 안전을 위해
필요한 진행 중 작업의 완료와 복구는 중단하지 않습니다.

초기 구현에는 권한을 부여하지 않는 기록과 결정적인 상태 전이 계약만 추가합니다. 원자적인 영속
저장, 인증된 초기화, 프로세스 간 재조회, 모든 실행 경로의 검증을 연결하고 테스트할 때까지
런타임은 기존 서명 토큰 경로로 사용 가능 여부를 결정합니다. 기존 기록의 누락이나 불일치는
재초기화를 허용하지 않습니다. 잘못되거나 만료된 서명 자격 증명이 새 Trial로 전환돼서는 안 됩니다.

향후 버전이 있는 사용권으로 Trial 제한을 해제할 수 있습니다. 해당 계약이 구현될 때까지 현재
서명 토큰의 30일 상한은 유지합니다. 서명된 배포 키트는 산출물을 인증할 뿐 사용 권한을 뜻하지
않으며, 별도로 유효한 사용권을 포함할 때만 Trial을 해제합니다. 발급자 개인 키는 배포 환경에
전달하지 않습니다. 소스와 모든 영속 상태를 통제하는 소유자는 이 검사를 제거할 수 있으므로,
오프라인 방식이 변조를 완전히 막거나 모든 재설치를 탐지한다고 주장하지 않습니다.

## 발급자 워크스테이션 예외

**초기 설계.** `secrets/` 아래에 비공개 키 파일이 있으면 발급자 워크스테이션이라고 간주하고
라이선스 검사를 건너뜁니다.

**비판.** 파일 이름은 암호학적 신원이 아닙니다. 빈 파일, 관계없는 키, 심볼릭 링크 또는 마운트된
키 경로도 단순 존재 검사를 통과합니다. `secrets/integrity-signing-key.pem`을 재사용하면 프레임워크
무결성과 라이선스의 침해 범위가 합쳐지고, 런타임이 필요하지 않은 키를 읽게 됩니다.

**수정된 설계.** 소스 checkout은 다음 검사를 모두 통과해야만 `issuer-workstation` 상태가 될 수
있습니다.

- 실행 장소가 `local`이고 아티팩트 루트에 Git checkout 표시가 있습니다.
- 고정 경로 `secrets/license-signing-key.pem`이 현재 UID 소유의 mode-`0600` 일반 파일이며,
  크기를 제한하고 차단하지 않으며 링크를 따르지 않는 파일 서술자로 읽힙니다.
- 파일에 든 Ed25519 비공개 키에서 유도한 공개 바이트가 Core 배포판에 포함된 추적 대상 라이선스
  공개 키와 정확히 일치합니다.
- 전용 라이선스 키는 `secrets/integrity-signing-key.pem`과 분리됩니다.

배포된 실행 장소에서는 런타임이 비공개 키 경로를 열지 않습니다. Docker 빌드 맥락은 전체
`secrets/` 트리를 제외합니다. 검증된 발급자 워크스테이션은 설정된 라이선스 토큰을 무시하고 전체
카탈로그를 사용 가능하게 유지합니다. 승격, RBAC, 위험, 승인, 롤백, 감사 및 효과 검증 게이트는
그대로 적용됩니다. 비공개 키가 없거나 형식, 권한 또는 키 쌍이 잘못되어도 예외를 부여하지 않으며
관찰 기능은 중단하지 않습니다.

이는 변경할 수 없는 물리 하드웨어가 아니라 전용 키의 소유를 증명합니다. 키를 복사하면 발급자
상태도 복사됩니다. 향후 하드웨어 보호 키 설계로 서명 토큰 계약을 바꾸지 않고 보관 경계를 강화할
수 있습니다.

## 토큰

토큰은 `base64url(canonical-document) "." base64url(signature)`입니다. 환경변수, Container Apps
시크릿, Kubernetes 시크릿 마운트에 들어가는 단일 ASCII 문자열입니다. 서명은 정본
문서의 정확한 바이트를 덮으므로 필드 순서를 다르게 해석할 수 없고, 문서 안의
`schema_version`이 다른 모든 FDAI 서명과 페이로드를 분리합니다.

| 점유 | 목적 |
|-------|------|
| `license_id`, `distribution_id` | 권한과 발급 분포 식별 |
| `capability_ids` | 이 license가 available로 만드는 카탈로그 기능 |
| `not_before`, `not_after` | 유효 기간 |
| `image_digest` | 특정 런타임 이미지에 대한 선택적 연결 |
| `tenant_binding` | 특정 배포에 대한 선택적 연결, **다이제스트 전용** |

발급기는 1일부터 30일까지의 유효 기간을 허용하고 기본값으로 30일을 사용합니다. Core 토큰 계약과
오프라인 검사기도 경과 UTC 시간 기준으로 30일을 넘는 서명된 유효 기간을 거부하므로 대체 발급기로
상한을 우회할 수 없습니다. 갱신할 때는 기존 서명 문서를 연장하거나 다시 쓰지 않고 새 토큰을
발급합니다.

배포되는 Core 런타임은 `distribution_id`를 `fdai-upstream`에 연결합니다. 같은 발급자가 다른
배포판용으로 서명했더라도 여기서는 `misbound`입니다. 다운스트림 배포판은 조립 단계에서 자체 예상
신원을 제공하며, 환경 값으로 발급 후 토큰의 배포판 이름을 바꿀 수 없습니다.

`tenant_binding`은 결코 테넌트 식별자가 아닙니다. 다이제스트로 연결하면 리포지토리, 이미지, 모든
로그 줄에 고객 값이 남지 않습니다
([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).

## 이 설계를 안전하게 만드는 규칙

**License는 `available` 축만 움직입니다.** 기능을 shadow에서 승격하거나, 역할을 넓히거나,
risk 결정을 완화하거나, 승인 권한을 부여할 수 없습니다. 그것들은 승격 레지스트리, RBAC,
risk 게이트가 계속 소유합니다
([coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)).

결과를 분명히 설명하면, 신뢰할 수 있는 토큰은 가용성 보류 하나를 해제할 수 있지만 그 자체로
효과를 승인할 수 없습니다. 작업은 독립적인 승격, 역할, 위험, 승인, 신원, 안전장치 및 효과 검증을
모두 통과해야 합니다. 라이선스 검사가 이러한 결정을 대체하거나 높일 수 있다면 그 자체가
backdoor입니다.

권한은 배포된 카탈로그와의 교집합이기도 하므로, 토큰이 분포에 없는 기능을
만들어낼 수 없습니다.

**읽기 전용 기능은 license 대상이 아닙니다.** 모든 저하 상태가 이미 무조건 부여하므로,
`active` license도 나열 여부와 무관하게 부여합니다. 그렇지 않으면 조치 기능만 나열한
license를 쓰는 운영자가 만료된 license보다 더 적게 보게 되고, 권한을 갱신했더니 대시보드가
사라지는 일이 생깁니다. 따라서 `active`의 가용 집합은 항상 저하 집합의 상위 집합입니다.

## 토큰 취급

토큰은 비공개 키 같은 의미의 비밀은 아닙니다. 위조할 수 없기 때문입니다. 하지만 **bearer
자격 증명**입니다. `image_digest`나 `tenant_binding` 없이 발급된 license는 그것을 읽을 수 있는
누구에게나 동작합니다. 그래서 발급기는 소유자 전용으로, symlink를 따르지 않고 기록하며, 토큰이
이동할 것을 전제하는 분포는 연결을 걸어야 합니다. 앞뒤 공백은 유효한 토큰 표기가 아니므로
파일 출력에는 끝 줄 바꿈 없이 정본 토큰 바이트만 기록합니다.

Azure 전달 경로는 각 토큰을 다이제스트에서 파생한 Key Vault 시크릿 이름에 기록하고 새 Terraform
개정 번호에서만 Core 참조를 바꿉니다. 교체 계획이 성공하기 전에 활성 개정 번호가 사용하는 버전
없는 시크릿 이름을 덮어쓰지 않습니다. 따라서 갱신 실패로 사용되지 않는 시크릿이 남을 수는 있지만,
실행 중인 Core 프로세스를 잘못 연결하거나 Trial로 낮출 수는 없습니다.

## 토큰 정규성

License의 유효한 표기는 정확히 하나입니다. 대부분의 표준 라이브러리에서 base64 디코딩은 알파벳
밖 문자를 조용히 버립니다. 그래서 어느 세그먼트에든 공백을 끼워 넣어도 같은 서명 바이트로
디코딩되어 서명이 그대로 유효합니다. License 하나에 서로 다른 토큰 문자열이 무한히 생기는
셈입니다. 세그먼트는 패딩 없는 base64url 알파벳과 일치해야 하고, 디코딩된 바이트는 도착한
세그먼트로 다시 인코딩되어야 합니다. 디코딩된 문서도 도착한 정본 JSON 바이트와 정확히
같게 다시 serialize되어야 합니다. 공백, 키 순서, 목록 순서, 시각 표기가 다른 동등한 JSON은
거부합니다.

이는 지금 있는 것보다 앞으로 만들 것에 관한 문제입니다. 철회, 재사용 탐지, 감사 상관관계는
모두 토큰을 키로 삼습니다. 각각이 고유하지 않은 식별자 위에 세워지게 됩니다. 앞뒤 공백도 다른
표기로 취급하며, 파싱 전에 잘라내는 대신 거부합니다.

## 해석과 저하

해석은 안전 쪽으로 실패합니다. 모든 비정상 경로는 예외를 던지는 대신 카탈로그의 읽기 전용
부분집합으로 저하됩니다. 그래서 license가 만료된 운영자도 관찰은 계속하고 조치만 못 합니다.
검증기 자체가 실행되지 못하는 경우도 포함합니다. 손상된 packaged 공개 키는 비정상 종료가 아니라
`untrusted`로 해석됩니다. 바로 그때가 런타임이 살아 있어야 진단이 가능한 시점이기 때문입니다.
운영자에게 보이는 사유는 일반 문구를 유지하고 검증기 exception 세부 내용을 되풀이하지 않습니다.

| 상태 | 원인 | 가용성 |
|------|------|--------|
| `issuer-workstation` | 로컬 소스 checkout이 일치하는 전용 비공개 키의 소유를 증명 | 전체 카탈로그, 설정된 토큰은 무시 |
| `active` | 서명 검증 통과, 기간 내, 연결 일치 | 카탈로그에 존재하는 나열된 기능과 모든 읽기 전용 기능 |
| `absent` | 토큰 미설정 및 발급자 워크스테이션 증명 없음 | 배포된 런타임에서 읽기 전용 |
| `untrusted` | 형식 오류 토큰, 비정규 토큰, packaged 키가 거부한 서명, 또는 실행되지 못한 검증기 | 읽기 전용 |
| `not-yet-valid` / `expired` | 유효 기간 밖 | 읽기 전용 |
| `misbound` | 배포판 신원, 이미지 다이제스트 또는 배포 연결 불일치 | 읽기 전용 |

암호화 구현과 분리된 해석기는 격리된 라이브러리 및 포크 조립을 위해 명시적인
`require_license` 입력을 유지합니다. 배포되는 Core 런타임은 항상 이 입력을 설정합니다. 개발은
검증된 발급자 워크스테이션에서만 제한 없이 동작합니다. 다른 checkout은 토큰이 없는 배포와 같은
읽기 전용 Trial 상태가 됩니다.

## 런타임 실행 상한

일반 컨트롤 루프 발송과 사람 승인 후 재개가 공유하는 Thor 실행 포트에서 가용성을 검사합니다.
PR 기반, 직접 API 및 도구 호출 작업 경로는 모두 카탈로그 기능 `operations.typed-mutation`을
요구합니다. 런타임은 각 포트 호출 직전에 권한을 다시 해석합니다. 따라서 시작할 때 토큰이
유효했더라도 프로세스가 `not_after`를 지나면 다시 시작하지 않고 다음 작업 요청을 차단합니다.

차단 시 상태, 가능한 경우 라이선스 ID, 만료 시각, 필요한 기능 및 실행 경로를 담은 비밀 없는
종료 감사 레코드를 기록합니다. 토큰, 문서, 서명, 공개 키 바이트, 비공개 키 경로 또는 검증기 예외는
기록하지 않습니다. 차단 결과는 사람 승인이나 다른 실행기 경로로 전환할 수 없습니다. 감사 저장에
실패해도 delegate는 계속 차단되고 호출자는 `audit_persisted=false`가 표시된 종료 거부를 받습니다.
비밀 없는 구조화 오류가 보조 운영 신호를 제공하며, 차단을 처리되지 않은 실행 경로 예외로 바꾸지
않습니다.

이 상한은 가용성만 낮출 수 있습니다. 토큰에 `operations.typed-mutation`이 있어도 효과를
적용하려면 기존 승격, RBAC, 위험, 승인, 안전장치, 신원 및 효과 검증을 모두 통과해야 합니다. 토큰을
교체할 때는 새 시크릿을 시작 시 연결할 수 있도록 Core를 다시 시작해야 하지만, 만료 자체에는 다시
시작할 필요가 없습니다.

## 코드 위치

| 관심사 | 위치 |
|--------|------|
| 토큰 계약, 검증, 정본 바이트 | `services/core-control-plane/src/fdai/core/licensing/token.py` (crypto-free) |
| 상태, 연결, 현재 시각 기준 권한 해석 | `services/core-control-plane/src/fdai/core/licensing/entitlement.py` |
| 런타임 서명 및 로컬 발급자 키 검증 | `services/core-control-plane/src/fdai/delivery/trust/ed25519.py` |
| 런타임 Trial 연결 | `services/core-control-plane/src/fdai/runtime/licensing.py` |
| 최종 공유 실행 상한 | `services/core-control-plane/src/fdai/core/executor/licensing_gate.py` |
| 발급 및 자체 검증 (release 전용) | 고정된 cryptography 의존성의 Ed25519와 배타적 mode-`0600` 출력 생성을 사용하는 `scripts/deployment/release/issue-license.py` |
| 모든 운영자를 위한 오프라인 검증 | 배포 CLI의 독립 Ed25519 검증기를 사용하는 `fdaictl license inspect` |

이 분리는 확장 및 스킬 trust 경계와 같습니다. `core/`는 `LicenseVerifier` 프로토콜만 선언하고
crypto 백엔드, 전송 계층, `fdai.delivery`를 가져오기하지 않습니다
([project-structure-ko.md](../architecture/project-structure-ko.md#module-boundaries)).

## 이 리포지토리에서 검증하기

발급자 비공개 키를 노출하지 않고 라이선싱을 테스트할 수 있습니다. 발급자 워크스테이션에서 30일
전체 카탈로그 토큰을 발급하고 검사합니다.

```bash
uv run python scripts/deployment/release/issue-license.py \
  --license-id lic-0001 --distribution-id example-distribution \
  --all-capabilities \
  --output /tmp/license.token
uv run python -m fdai.deployment_cli license inspect \
  --token /tmp/license.token \
  --public-key services/core-control-plane/src/fdai/delivery/trust/license-signing-key.pub \
  --output json
```

`issue-license.py`는 출력 전에 자신의 결과를 supplied 공개 키로 재검증하므로, 교대된 서명
키는 고객 현장이 아니라 발급 시점에 실패합니다. 비공개 키는 현재 UID가 소유한 mode-`0600`
일반 파일일 때만 허용되며, 두 키 모두 비차단, 심볼릭 링크 차단, 65536바이트 경계를 통해
읽습니다. 기본값은 고정 발급자 키, 패키지 공개 키 및 30일 유효 기간이며, 키 교대 확인을 위해
공개 키를 명시할 수도 있습니다. `license inspect`는 상태와 비밀이 아닌 메타데이터만 보고하며
토큰, 문서, 서명을 출력하지 않습니다.

자동화된 커버리지는 계약과 저하 표에 대해 `services/core-control-plane/tests/core/licensing/`, 변조·잘못된 서명자·잘못된
연결을 포함한 실제 발급-검증 경로에 대해 `tests/integration/scripts/test_issue_license.py`에 있습니다.

## 정직한 한계

서명 검증은 framework-surface 매니페스트에 기록된 것과 똑같이 **tamper-evident이지
tamper-proof가 아닙니다**. 이미지를 받은 고객은 그 런타임을 통제하므로 검사를 제거할 수 있습니다.
난독화는 걸리는 시간만 바꿉니다.

따라서 강제력 있는 부분은 binary가 아니라 배포 채널입니다.

- `license_id`를 감사 이력에 기록해 권한을 사후에 귀속 가능하게 합니다.
- 업데이트, 지원, 새로 서명된 offline 키트를 현재 license에 묶어, 다음 릴리스를 잃는 것이 실제
  결과가 되게 합니다.
- 폐쇄망에는 철회 경로가 없고 호스트 시계가 게시자 통제 밖이므로, 짧은 유효 기간과 갱신을
  선호합니다.

## 관련 문서

| 알아보려는 것 | 읽을 문서 |
|---------------|-----------|
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/fork-and-sequencing/capability-licensing.md) |
| 포크가 편집할 수 있는 것과 주입해야 하는 것 | [downstream-fork-guide-ko.md](downstream-fork-guide-ko.md) |
| 기능 번들, 확장, 신뢰 검사 | [project-structure-ko.md](../architecture/project-structure-ko.md#capability-bundles) |
| 시크릿 처리와 네트워크 경계 | [security-and-identity-ko.md](../architecture/security-and-identity-ko.md) |
| 폐쇄망으로 이미지와 키트 전달 | [disconnected-deployment-ko.md](../deployment/disconnected-deployment-ko.md) |
