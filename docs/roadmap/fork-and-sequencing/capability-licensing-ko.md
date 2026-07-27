---
title: Capability 라이선싱
translation_of: capability-licensing.md
translation_source_sha: 8dc4c70159a21aa49c0d323d7c80097768955cc5
translation_revised: 2026-07-27
---
# Capability 라이선싱

다운스트림 distribution은 소스가 아니라 이미지로 고객에게 전달되는 경우가 많습니다. Fork를
빌드하고, 이미지를 넘기고, 그 이미지는 게시자가 도달할 수 없는 네트워크 안에서 돕니다. 이 문서는
그런 distribution이 비밀을 배포하지 않고, 네트워크 호출 없이, 그리고 결코 자율성을 높이는 경로가
되지 않으면서 entitlement를 활성화하는 방법을 정의합니다.

> **범위:** 메커니즘은 upstream 소유이며 모든 distribution에서 동일합니다. Public key와 token은
> 배포 설정입니다. 이 문서는 상업 조건, 가격, revocation 서비스를 정의하지 않습니다.

## 한눈에 보는 설계

순진한 형태 - 빌드 시 시리얼 번호를 이미지에 심기 - 는 곧바로 실패합니다. 이미지는 tar 파일이므로
layer에 심은 것은 전달받은 사람이 그대로 읽습니다. 또한
[security-and-identity-ko.md](../architecture/security-and-identity-ko.md)의 secret contract와도
충돌합니다. 비밀은 환경변수 또는 마운트된 secret으로만 들어와야 합니다.

그래서 라이선싱은 비대칭을 뒤집습니다. 리포지토리가 framework-surface manifest와 offline kit에
이미 적용 중인 패턴을 그대로 재사용합니다.

| 위치 | 무엇 | 왜 안전한가 |
|------|------|-------------|
| 이미지 안 (읽기 전용) | **public** 검증 key | Public key는 비밀이 아니며 공개해도 비용이 없습니다 |
| 이미지 밖 (배포 설정) | **서명된 license token** | 환경변수나 마운트 secret에 들어가는 ASCII 문자열 하나이며, private key 없이는 위조 불가입니다 |

읽기 전용 root 파일시스템은 장애물이 아닙니다. 활성화 상태를 이미지에 쓰지 않기 때문입니다.
Token은 통상의 secret 경로로 들어오고, 지속 기록이 필요하면 state store에 둡니다.

## Token

Token은 `base64url(canonical-document) "." base64url(signature)`입니다. 환경변수, Container Apps
secret, Kubernetes Secret 마운트에 들어가는 단일 ASCII 문자열입니다. Signature는 canonical
document의 정확한 byte를 덮으므로 field 순서를 다르게 해석할 수 없고, document 안의
`schema_version`이 다른 모든 FDAI signature와 payload를 분리합니다.

| Claim | 목적 |
|-------|------|
| `license_id`, `distribution_id` | Entitlement와 발급 distribution 식별 |
| `capability_ids` | 이 license가 available로 만드는 catalog capability |
| `not_before`, `not_after` | 유효 기간 |
| `image_digest` | 특정 runtime image에 대한 선택적 binding |
| `tenant_binding` | 특정 배포에 대한 선택적 binding, **digest 전용** |

`tenant_binding`은 결코 tenant 식별자가 아닙니다. Digest로 binding하면 리포지토리, 이미지, 모든
log 줄에 고객 값이 남지 않습니다
([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).

## 이 설계를 안전하게 만드는 규칙

**License는 `available` 축만 움직입니다.** Capability를 shadow에서 승격하거나, role을 넓히거나,
risk 결정을 완화하거나, approval 권한을 부여할 수 없습니다. 그것들은 promotion registry, RBAC,
risk gate가 계속 소유합니다
([coding-conventions.instructions.md](../../../.github/instructions/coding-conventions.instructions.md)).

결과를 분명히 말할 가치가 있습니다. 위조되거나 탈취된 token의 최악 결과는 운영자에게 capability가
목록에 보이는 것입니다. 고위험 조치가 실행되는 것이 결코 아닙니다. 자율성을 올릴 수 있는 라이선스
검사는 그 자체가 backdoor입니다.

Entitlement는 배포된 catalog와의 교집합이기도 하므로, token이 distribution에 없는 capability를
만들어낼 수 없습니다.

**읽기 전용 capability는 license 대상이 아닙니다.** 모든 저하 상태가 이미 무조건 부여하므로,
`active` license도 나열 여부와 무관하게 부여합니다. 그렇지 않으면 조치 capability만 나열한
license를 쓰는 운영자가 만료된 license보다 더 적게 보게 되고, entitlement를 갱신했더니 대시보드가
사라지는 일이 생깁니다. 따라서 `active`의 가용 집합은 항상 저하 집합의 상위 집합입니다.

## Token 취급

Token은 private key 같은 의미의 비밀은 아닙니다. 위조할 수 없기 때문입니다. 하지만 **bearer
credential**입니다. `image_digest`나 `tenant_binding` 없이 발급된 license는 그것을 읽을 수 있는
누구에게나 동작합니다. 그래서 발급기는 소유자 전용으로, symlink를 따르지 않고 기록하며, token이
이동할 것을 전제하는 distribution은 binding을 걸어야 합니다.

## Token 정규성

License의 유효한 표기는 정확히 하나입니다. 대부분의 표준 라이브러리에서 base64 디코딩은 알파벳
밖 문자를 조용히 버립니다. 그래서 어느 세그먼트에든 공백을 끼워 넣어도 같은 서명 바이트로
디코딩되어 signature가 그대로 유효합니다. License 하나에 서로 다른 token 문자열이 무한히 생기는
셈입니다. 세그먼트는 패딩 없는 base64url 알파벳과 일치해야 하고, 디코딩된 바이트는 도착한
세그먼트로 다시 인코딩되어야 합니다.

이는 지금 있는 것보다 앞으로 만들 것에 관한 문제입니다. Revocation, 재사용 탐지, 감사 상관관계는
모두 token을 키로 삼습니다. 각각이 고유하지 않은 식별자 위에 세워지게 됩니다.

## 해석과 저하

해석은 안전 쪽으로 실패합니다. 모든 비정상 경로는 예외를 던지는 대신 catalog의 읽기 전용
부분집합으로 저하됩니다. 그래서 license가 만료된 운영자도 관찰은 계속하고 조치만 못 합니다.
검증기 자체가 실행되지 못하는 경우도 포함합니다. 손상된 packaged public key는 crash가 아니라
`untrusted`로 해석됩니다. 바로 그때가 런타임이 살아 있어야 진단이 가능한 시점이기 때문입니다.

| 상태 | 원인 | 가용성 |
|------|------|--------|
| `active` | Signature 검증 통과, 기간 내, binding 일치 | Catalog에 존재하는 나열된 capability와 모든 읽기 전용 capability |
| `absent` | Token 미설정 | Upstream은 전체 catalog, distribution이 `require_license`를 켜면 읽기 전용 |
| `untrusted` | 형식 오류 token, 비정규 token, packaged key가 거부한 signature, 또는 실행되지 못한 검증기 | 읽기 전용 |
| `not-yet-valid` / `expired` | 유효 기간 밖 | 읽기 전용 |
| `misbound` | Image digest 또는 배포 binding 불일치 | 읽기 전용 |

이 리포지토리는 license 없이 배포되므로 `absent`가 전체 catalog를 유지하며 개발이 막히지 않습니다.
Fail-closed를 원하는 distribution은 composition root에서 `require_license`를 설정합니다.

## 코드 위치

| 관심사 | 위치 |
|--------|------|
| Token contract, 검증, canonical byte | `src/fdai/core/licensing/token.py` (crypto-free) |
| 상태, binding, entitlement 해석 | `src/fdai/core/licensing/entitlement.py` |
| Signature 검증 | `src/fdai/delivery/trust/ed25519.py`의 `Ed25519LicenseVerifier` |
| 발급 (release 전용) | `scripts/deployment/release/issue-license.py` |
| 모든 운영자를 위한 오프라인 검증 | `fdaictl license inspect` |

이 분리는 extension 및 skill trust seam과 같습니다. `core/`는 `LicenseVerifier` Protocol만 선언하고
crypto backend, transport, `fdai.delivery`를 import하지 않습니다
([project-structure-ko.md](../architecture/project-structure-ko.md#module-boundaries)).

## 이 리포지토리에서 검증하기

Upstream은 license 없이 배포되지만 라이선싱은 upstream에서도 테스트 가능합니다. Key를 만들고,
token을 발급하고, inspect합니다.

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

`issue-license.py`는 출력 전에 자신의 결과를 supplied public key로 재검증하므로, rotation된 signing
key는 고객 현장이 아니라 발급 시점에 실패합니다. `license inspect`는 상태와 비밀이 아닌 metadata만
보고하며 token, document, signature를 절대 출력하지 않습니다.

자동화된 커버리지는 contract와 저하 표에 대해 `tests/core/licensing/`, 변조·잘못된 서명자·잘못된
binding을 포함한 실제 발급-검증 경로에 대해 `tests/scripts/test_issue_license.py`에 있습니다.

## 정직한 한계

Signature 검증은 framework-surface manifest에 기록된 것과 똑같이 **tamper-evident이지
tamper-proof가 아닙니다**. 이미지를 받은 고객은 그 runtime을 통제하므로 검사를 제거할 수 있습니다.
난독화는 걸리는 시간만 바꿉니다.

따라서 강제력 있는 부분은 binary가 아니라 배포 채널입니다.

- `license_id`를 audit trail에 기록해 entitlement를 사후에 귀속 가능하게 합니다.
- 업데이트, 지원, 새로 서명된 offline kit을 현재 license에 묶어, 다음 릴리스를 잃는 것이 실제
  결과가 되게 합니다.
- 폐쇄망에는 revocation 경로가 없고 host 시계가 게시자 통제 밖이므로, 짧은 유효 기간과 갱신을
  선호합니다.

## 관련 문서

| 알아보려는 것 | 읽을 문서 |
|---------------|-----------|
| Fork가 편집할 수 있는 것과 주입해야 하는 것 | [downstream-fork-guide-ko.md](downstream-fork-guide-ko.md) |
| Capability bundle, extension, 신뢰 검사 | [project-structure-ko.md](../architecture/project-structure-ko.md#capability-bundles) |
| Secret 처리와 네트워크 경계 | [security-and-identity-ko.md](../architecture/security-and-identity-ko.md) |
| 폐쇄망으로 이미지와 kit 전달 | [disconnected-deployment-ko.md](../deployment/disconnected-deployment-ko.md) |
