---
title: 시스템 지식 Teams 봇 온보딩
translation_of: system-knowledge-teams-onboarding.md
translation_source_sha: 943260ffe87fc1976df277909cef0c67da8b1dd1
translation_revised: 2026-09-10
---
# 시스템 지식 Teams 봇 온보딩

이 runbook을 사용해 승인된 표준 Teams channel 하나에 독립 FDAI 시스템 지식 서비스를 준비하고
배포합니다. Bot Framework application 또는 `FDAI-bot`이라는 Team 범위 Teams Outgoing
Webhook을 사용할 수 있습니다. Outgoing Webhook 경로에는 Entra application 등록, app package
또는 Microsoft Graph 설치 권한이 필요하지 않습니다.

> **범위:** 이 runbook은 개발 환경을 다룹니다. 운영 A3 봇을 변경하거나 모든 channel 메시지를
> 읽는 RSC(resource-specific consent)를 요청하거나 관리 리소스 실행 권한을 부여하지 않습니다.
>
> **비공개 tenant:** Key Vault, Blob, Terraform state 및 Container Apps 작업은 VNet에 연결된
> self-hosted runner에서 실행합니다. Secret 또는 비공개 state file을 laptop으로 복사하지
> 않습니다.

## 필수 조건

다음 항목이 필요합니다.

- 승인된 표준 Team과 channel
- 전용 Team을 만들어야 할 때 유지관리자에게 활성화된 Teams service plan
- 안정적인 FDAI 지식 principal 이름에 매핑할 Entra 사용자 한 명 이상
- 필수 CI를 통과하고 attestation을 받은 `fdai-system-knowledge-service` 이미지가 있는 clean
  protected-main 개정
- Bot Framework를 선택할 때 배포 전용 installer 신원을 초기화할 tenant 관리 권한
- Outgoing Webhook을 선택할 때 webhook을 만들 Team 소유자 권한
- 문서 Blob storage를 활성화한 기존 비공개 FDAI platform

첫 release에서는 private 및 shared channel을 지원하지 않습니다.

## Teams profile 구성

값을 source control에 기록하지 않고 다음 repository secret을 만듭니다.

| Secret | 내용 |
|--------|------|
| `SYSTEM_KNOWLEDGE_TEAMS_PROFILE_JSON` | 선택한 transport, 서비스 이름, tenant, 승인된 team과 channel 목록 및 transport별 trust root |
| `SYSTEM_KNOWLEDGE_PRINCIPAL_MAP_JSON` | Teams sender `aadObjectId`와 배포 로컬 지식 principal의 매핑 |
| `SYSTEM_KNOWLEDGE_TEAMS_OUTGOING_HMAC_SECRET` | Teams가 발급한 Base64 HMAC key. Outgoing Webhook bootstrap 후에만 설정 |

Outgoing Webhook에는 다음 profile을 사용합니다.

```json
{
  "transport": "outgoing_webhook",
  "service_name": "<container-app-name>",
  "tenant_id": "<tenant-guid>",
  "team_ids": ["<team-guid>"],
  "channel_ids": ["<channel-id>"]
}
```

Bot Framework에는 기존 profile을 사용합니다.

```json
{
  "transport": "bot_framework",
  "service_name": "<container-app-name>",
  "bot_name": "<azure-bot-name>",
  "tenant_id": "<tenant-guid>",
  "team_ids": ["<team-guid>"],
  "channel_ids": ["<channel-id>"],
  "allowed_service_urls": ["https://<bot-service-origin>"],
  "jwks_url": "https://<bot-service-jwks-url>"
}
```

Principal map은 다음 형태를 사용합니다.

```json
{
  "<entra-user-object-id>": "<knowledge-principal>"
}
```

보호된 workflow는 principal map만 고정 Key Vault secret 하나에 씁니다. 다른 값은 보호된 배포
입력에 유지되며 접근이 제한된 Terraform state에 나타납니다. Outgoing Webhook enable
transition에서는 HMAC key도 두 번째 고정 Key Vault secret에 쓰고 다시 읽어 검증합니다. HMAC
값은 Terraform state에 들어가지 않습니다.

## Bot Framework 배포 전용 installer 초기화

Installer는 정확히 두 Microsoft Graph application permission을 사용합니다.

- `AppCatalog.ReadWrite.All`
- `TeamsAppInstallation.ReadWriteForTeam.All`

런타임 UAMI에는 어느 권한도 주지 않습니다. Tenant 관리자로 로그인한 상태에서 installer를 한
번 초기화합니다.

```bash
result="$(
  uv run --frozen --package fdai-system-knowledge-service python \
    scripts/deployment/system_knowledge/bootstrap_installer_identity.py \
    --repository dotnetpower/fdai \
    --environment dev
)"
client_id="$(jq -er '.client_id' <<<"$result")"
gh variable set SYSTEM_KNOWLEDGE_INSTALLER_CLIENT_ID --body "$client_id"
result=""
client_id=""
```

Helper는 Entra application, service principal, GitHub
`repo:dotnetpower/fdai:environment:dev` federated credential 및 정확한 Graph role 두 개를
만들거나 검증합니다. Apply job은 GitHub OIDC를 수명이 짧은 Graph token으로 교환합니다. Client
secret은 만들지 않습니다.

## Outgoing Webhook bootstrap

먼저 `transition=bootstrap`으로 보호된 workflow를 실행합니다. 아래에서 설명하는 plan-only 및
정확한 apply 근거 흐름을 그대로 사용합니다. Bootstrap은 Azure Bot, Teams channel resource,
app package 또는 HMAC 결속 없이 Container App, 비공개 claim container 및 전용 UAMI를 만듭니다.

Apply 후 workflow summary에서 callback URL을 복사합니다. Teams에서 **팀 관리** > **앱** >
**앱 업로드** > **발신 웹후크 만들기**를 열고 다음 순서로 진행합니다.

1. 이름을 `FDAI-bot`으로 설정합니다.
2. 정확한 callback URL을 붙여 넣습니다.
3. 범위가 제한된 설명과 선택적 이미지를 추가합니다.
4. Webhook을 만듭니다.
5. `gh secret set SYSTEM_KNOWLEDGE_TEAMS_OUTGOING_HMAC_SECRET`을 실행하고 terminal prompt에만
   표시된 HMAC key를 입력해 보호된 repository secret에 직접 저장합니다.

Key를 chat, 명령 인자, file 또는 workflow input에 붙여 넣지 않습니다. Secret을 설정한 뒤 새로운
`transition=enable` plan을 만들고 정확한 근거로 적용합니다. Enable은 VNet 내부에서 HMAC key를
쓰고 versionless Key Vault reference를 추가한 뒤 새 Container App 개정을 만듭니다. 이 단계가
끝날 때까지 bootstrap endpoint는 `503 outgoing_webhook_unconfigured`을 반환합니다.

## 배포 plan

정확한 필수 CI 개정의 attested image digest를 확인한 뒤 plan-only를 실행합니다.

```bash
gh workflow run system-knowledge-deploy.yml \
  -f commit_sha=<exact-sha> \
  -f image_ref=ghcr.io/dotnetpower/fdai/fdai-system-knowledge-service@sha256:<digest> \
  -f previous_image_ref=ghcr.io/dotnetpower/fdai/fdai-system-knowledge-service@sha256:<digest> \
  -f transition=<bootstrap-or-enable>
```

모든 plan에는 전용 UAMI, 비공개 claim container, 최소 role assignment 세 개, replica 하나의
Container App 및 `execution_authority=false` 계약이 있어야 합니다. Bot Framework plan에는 F0
Azure Bot과 Teams channel도 있습니다. Outgoing Webhook plan에는 두 resource가 없어야 합니다.

Workflow summary에서 plan run id, attempt, plan digest 및 context digest를 기록합니다.

## 적용 및 설치

정확한 plan 근거를 사용해 apply를 실행합니다.

```bash
gh workflow run system-knowledge-deploy.yml \
  -f commit_sha=<exact-sha> \
  -f image_ref=ghcr.io/dotnetpower/fdai/fdai-system-knowledge-service@sha256:<digest> \
  -f previous_image_ref=ghcr.io/dotnetpower/fdai/fdai-system-knowledge-service@sha256:<digest> \
  -f transition=<bootstrap-or-enable> \
  -f apply=true \
  -f plan_run_id=<plan-run-id> \
  -f plan_run_attempt=<attempt> \
  -f plan_digest=<plan-sha256> \
  -f context_digest=sha256:<context-sha256>
```

Workflow는 다음 단계를 실행합니다.

1. 정확한 binary plan을 재생하고 guard합니다.
2. 비공개 VNet 내부에서 principal map을 materialize하고 다시 읽어 검증합니다.
3. Plan을 적용합니다.
4. 활성 healthy 개정과 비공개 Blob claim container를 검증합니다.
5. Bot Framework는 결정적 Teams package를 build하고 배포 전용 OIDC 신원으로 업로드 및
   설치합니다.
6. Outgoing Webhook은 Azure Bot이 없음을 검증하고 workflow summary에 callback URL을 표시합니다.

## Channel 검증

승인된 표준 channel에서 다음을 확인합니다.

1. Bot Framework에서는 `FDAI Knowledge`, Outgoing Webhook에서는 `FDAI-bot`을 멘션하고 FDAI가
   작업을 안전하게 유지하는 방법을 묻습니다.
2. 동일 대화의 응답 하나에 설계된 동작, 구현 근거, 제한, source path 및
   `execution_authority=false`가 있는지 확인합니다.
3. 정확한 Container App 개정을 다시 시작합니다.
4. 이전 메시지에 다시 답하지 않는지 확인합니다.
5. 멘션을 하나 더 보내고 새 응답 하나만 오는지 확인합니다.
6. 내용이 없는 claim, 개정, 전달 및 시간 근거만 보존합니다.

대화 본문, 사용자 식별자, Team id 또는 channel id를 저장소에 복사하지 않습니다.

## 비활성화 및 롤백 예행 연습

`transition=disable`로 새 plan을 만든 뒤 같은 workflow에서 정확한 근거를 사용해 적용합니다.
Apply는 15분 안에 끝나야 하며 전용 서비스 Terraform state를 비워야 합니다. Core, Operator
Service, 문서 서비스, Isolated Executor 및 운영 A3 edge는 바뀌지 않아야 합니다.

롤백 근거를 기록한 뒤 승인된 목표 상태가 봇 실행 유지라면 새로운 `enable` plan을 만들고
적용합니다.

## 관련 문서

| 알아볼 내용 | 문서 |
|-------------|------|
| 서비스 설계와 실패 동작 | [시스템 지식 서비스](../roadmap/interfaces/system-knowledge-service-ko.md) |
| 비공개 배포 runner | [배포 및 온보딩](../roadmap/deployment/deploy-and-onboard-ko.md) |
| 서비스 승격 gate | [서비스 승격 및 데이터 소유권](../roadmap/architecture/service-graduation-and-ownership-ko.md) |
| 운영 Teams 대화 | [운영 A3 채널 런타임](../roadmap/interfaces/production-a3-channel-runtime-ko.md) |
