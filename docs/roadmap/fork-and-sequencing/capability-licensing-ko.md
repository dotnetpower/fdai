---
title: Capability 라이선싱
translation_of: capability-licensing.md
translation_source_sha: 7816b2b77659285b5b66dce4ee1f3556cd63c2f8
translation_revised: 2026-08-11
---
# 기능 라이선싱

다운스트림 분포는 소스가 아니라 이미지로 고객에게 전달되는 경우가 많습니다. 포크를
빌드하고, 이미지를 넘기고, 그 이미지는 게시자가 도달할 수 없는 네트워크 안에서 돕니다. 이 문서는
그런 분포가 비밀을 배포하지 않고, 네트워크 호출 없이, 그리고 결코 자율성을 높이는 경로가
되지 않으면서 권한을 활성화하는 방법을 정의합니다.

> **범위:** 메커니즘은 업스트림 소유이며 모든 분포에서 동일합니다. 공개 키와 토큰은
> 배포 설정입니다. 이 문서는 상업 조건, 가격, 철회 서비스를 정의하지 않습니다.

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

`tenant_binding`은 결코 테넌트 식별자가 아닙니다. 다이제스트로 연결하면 리포지토리, 이미지, 모든
로그 줄에 고객 값이 남지 않습니다
([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).

## 이 설계를 안전하게 만드는 규칙

**License는 `available` 축만 움직입니다.** 기능을 shadow에서 승격하거나, 역할을 넓히거나,
risk 결정을 완화하거나, 승인 권한을 부여할 수 없습니다. 그것들은 승격 레지스트리, RBAC,
risk 게이트가 계속 소유합니다
([coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)).

결과를 분명히 말할 가치가 있습니다. 위조되거나 탈취된 토큰의 최악 결과는 운영자에게 기능이
목록에 보이는 것입니다. 고위험 조치가 실행되는 것이 결코 아닙니다. 자율성을 올릴 수 있는 라이선스
검사는 그 자체가 backdoor입니다.

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
이동할 것을 전제하는 분포는 연결을 걸어야 합니다.

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
| `active` | 서명 검증 통과, 기간 내, 연결 일치 | 카탈로그에 존재하는 나열된 기능과 모든 읽기 전용 기능 |
| `absent` | 토큰 미설정 | 업스트림은 전체 카탈로그, 분포가 `require_license`를 켜면 읽기 전용 |
| `untrusted` | 형식 오류 토큰, 비정규 토큰, packaged 키가 거부한 서명, 또는 실행되지 못한 검증기 | 읽기 전용 |
| `not-yet-valid` / `expired` | 유효 기간 밖 | 읽기 전용 |
| `misbound` | 이미지 다이제스트 또는 배포 연결 불일치 | 읽기 전용 |

이 리포지토리는 license 없이 배포되므로 `absent`가 전체 카탈로그를 유지하며 개발이 막히지 않습니다.
실패 시 차단을 원하는 분포는 조립 루트에서 `require_license`를 설정합니다.

## 코드 위치

| 관심사 | 위치 |
|--------|------|
| 토큰 계약, 검증, 정본 바이트 | `services/core-control-plane/src/fdai/core/licensing/token.py` (crypto-free) |
| 상태, 연결, 권한 해석 | `services/core-control-plane/src/fdai/core/licensing/entitlement.py` |
| 서명 검증 | `services/core-control-plane/src/fdai/delivery/trust/ed25519.py`의 `Ed25519LicenseVerifier` |
| 발급 (release 전용) | `scripts/deployment/release/issue-license.py` |
| 모든 운영자를 위한 오프라인 검증 | `fdaictl license inspect` |

이 분리는 확장 및 스킬 trust 경계와 같습니다. `core/`는 `LicenseVerifier` 프로토콜만 선언하고
crypto 백엔드, 전송 계층, `fdai.delivery`를 가져오기하지 않습니다
([project-structure-ko.md](../architecture/project-structure-ko.md#module-boundaries)).

## 이 리포지토리에서 검증하기

업스트림은 license 없이 배포되지만 라이선싱은 업스트림에서도 테스트 가능합니다. Key를 만들고,
토큰을 발급하고, inspect합니다.

```bash
openssl genpkey -algorithm ed25519 -out /tmp/license-key.pem
openssl pkey -in /tmp/license-key.pem -pubout -out /tmp/license-key.pub
PYTHONPATH=src python3 scripts/deployment/release/issue-license.py \
 --private-key /tmp/license-key.pem --public-key /tmp/license-key.pub \
 --license-id lic-0001 --distribution-id example-distribution \
 --capability cost.metering --capability incident.restart \
 --output /tmp/license.token
PYTHONPATH=src python3 -m fdai.deployment_cli license inspect \
 --token /tmp/license.token --public-key /tmp/license-key.pub --output json
```

`issue-license.py`는 출력 전에 자신의 결과를 supplied 공개 키로 재검증하므로, 교대된 signing
키는 고객 현장이 아니라 발급 시점에 실패합니다. `license inspect`는 상태와 비밀이 아닌 메타데이터만
보고하며 토큰, 문서, 서명을 절대 출력하지 않습니다.

자동화된 커버리지는 계약과 저하 표에 대해 `services/core-control-plane/tests/core/licensing/`, 변조·잘못된 서명자·잘못된
연결을 포함한 실제 발급-검증 경로에 대해 `tests/integration/scripts/test_issue_license.py`에 있습니다.

## 정직한 한계

서명 검증은 framework-surface 매니페스트에 기록된 것과 똑같이 **tamper-evident이지
tamper-proof가 아닙니다**. 이미지를 받은 고객은 그 런타임을 통제하므로 검사를 제거할 수 있습니다.
난독화는 걸리는 시간만 바꿉니다.

따라서 강제력 있는 부분은 binary가 아니라 배포 채널입니다.

- `license_id`를 감사 trail에 기록해 권한을 사후에 귀속 가능하게 합니다.
- 업데이트, 지원, 새로 서명된 offline 키트를 현재 license에 묶어, 다음 릴리스를 잃는 것이 실제
 결과가 되게 합니다.
- 폐쇄망에는 철회 경로가 없고 호스트 시계가 게시자 통제 밖이므로, 짧은 유효 기간과 갱신을
 선호합니다.

## 관련 문서

| 알아보려는 것 | 읽을 문서 |
|---------------|-----------|
| 포크가 편집할 수 있는 것과 주입해야 하는 것 | [downstream-fork-guide-ko.md](downstream-fork-guide-ko.md) |
| 기능 번들, 확장, 신뢰 검사 | [project-structure-ko.md](../architecture/project-structure-ko.md#capability-bundles) |
| 시크릿 처리와 네트워크 경계 | [security-and-identity-ko.md](../architecture/security-and-identity-ko.md) |
| 폐쇄망으로 이미지와 키트 전달 | [disconnected-deployment-ko.md](../deployment/disconnected-deployment-ko.md) |
