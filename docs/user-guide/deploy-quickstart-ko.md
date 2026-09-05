---
title: 배포 빠른 시작
description: 보호된 fdaictl 작업 흐름으로 FDAI의 최소 Azure 인벤토리를 프로비저닝하거나 azd로 인프라 전용 개발 경로를 미리 봅니다.
translation_of: deploy-quickstart.md
translation_source_sha: 4b35a6e9d20b0761091c7795a5d5507f05ebb2ed
translation_revised: 2026-09-05
---

# 배포 빠른 시작

FDAI는 `infra/` 아래의 코드형 인프라(IaC)로 프로비저닝하며, Terraform이 실행 엔진이자 단일
기준입니다. 비공개 `dev` 및 `staging` 환경에는 보호된 `fdaictl` 작업 흐름을 사용하는 것이
좋습니다. `azd` 래퍼는 상용 네트워크 개발을 위한 인프라 전용 경로이며 Terraform 직접
실행은 전문가용 경로입니다.

## 시작하기 전에

- 리소스를 만들 수 있는 **Azure 구독**과 **Azure CLI**(`az`)가 필요합니다. 보호된
  경로에는 GitHub CLI(`gh`)가 필요하며 직접 개발 경로에는 **Azure Developer CLI**(`azd`)가
  필요합니다.
- [배포 사전 점검](../roadmap/deployment/deployment-preflight-ko.md)을 완료해야 합니다.
  이 점검은 컨트롤 루프가 시작되기 전에 쿼터, 권한, 연결, 롤백 차단 요소를 수집합니다.
- 환경별 값을 `*.tfvars` 파일에 입력합니다. 이 파일은 커밋하지 마세요.
- 승인된 대상을 `AZURE_SUBSCRIPTION_ID`와 `AZURE_TENANT_ID`로 내보내기합니다. 현재 자격
  증명이나 선택된 `azd` 환경이 이 조합과 다르면, 부트스트랩과 턴키 헬퍼가 아무것도 바꾸기
  전에 중단합니다.
- `infra/bootstrap`을 적용해 안정적인 배포 UAMI를 만든 뒤 client ID와 principal ID를
  `DEPLOY_RUNNER_CLIENT_ID`와 `DEPLOY_RUNNER_PRINCIPAL_ID`로 게시합니다. 보호된 workflow는
  이 client ID를 선택하고 ARM token `oid`, 테넌트 및 구독이 모두 일치하지 않으면 중단합니다.
- `container-supply-chain.yml`이 증명한 FDAI 서비스 이미지가 필요합니다. 보호된 서비스
  계획은 선택한 source revision에 대한 Core, Operator, Document Ingestion API,
  Document Processing Worker, Isolated Executor 이미지 증명을 각각 검증합니다. Exact 적용은
  해당 digest를 연결하며 이미지를 promote하거나 재구축하지 않습니다.
- 배포 호스트에서 모든 비공개 엔드포인트로 연결할 수 있어야 합니다. 프라이빗 전용 환경에서는
  운영자 워크스테이션 대신 VNet에 연결된 배포 러너에서 Terraform을 실행하세요. 그 환경의
  Premium 레지스트리도 프라이빗이므로 이미지 빌드와 푸시도 같은 러너에서 하세요.
- 보호된 원격 계획을 쓰려면 비밀이 아닌 `DEPLOY_PREFLIGHT_INPUT_JSON` 저장소 변수에 필요한
  라이브 카테고리를 모두 설정하세요. 프로필이 없으면 Azure 로그인 전에 중단하고, 프로브가
  차단되면 정제된 점검 결과와 발견된 문제만 로그에 남습니다. Terraform 계획 이후 runner-owned
  `run_live_preflight.py`가 Azure Policy, Compute quota, executor RBAC 및 value-blind Key Vault
  secret metadata를 검사합니다. 점검이 불완전하면 계획 산출물을 저장하기 전에 중단합니다.
- VNet에 연결된 runner에서 5개 서비스 root를 독립적으로 배포합니다. 각 서비스는 자체
  이미지, Terraform state, migration branch, 상태 probe, workload identity를 소유합니다.
  Isolated Executor만 작업별 효과 역할을 받을 수 있습니다.
- 보호된 Console 게시자를 통해 Console 및 Manual Studio 정적 콘텐츠를 게시합니다. 이
  게시자는 정확한 적용에서 동기화한 Static Web App 결속을 사용하고 Azure 리소스와 호스트
  이름의 일치를 검증한 뒤 결합된 정적 아티팩트를 독립적으로 업로드합니다. 별도 catalog
  갱신을 사용해 schema migration을 실행하고 정확히 검증된 Core 이미지에서 구체화한 뒤,
  리포지토리의 모든 예상 Rule 및 Ontology 프로젝션을 PostgreSQL과 비교합니다. 사전
  바인딩하거나 사전 실행한 catalog Job은 이미지와 실행 성공을 readback한 뒤에만 허용합니다.
- 독립 Slack 또는 Teams channel edge를 활성화하려면 프로바이더 credential과 principal mapping을
  local-only input 및 Key Vault에 보관하세요. Repository variable에는 versionless secret-id 목록만
  설정하고, 별도 Operator service `enable` plan보다 platform identity plan을 먼저 검토하고
  적용하세요. Edge identity에는 executor role을 부여하지 않습니다.
- A1 승인을 사용하려면 그룹 연결 Teams 팀, 채널 및 HTTPS Bot 액티비티 endpoint를 함께
  구성하거나 Slack 워크스페이스와 사용자-Entra 매핑을 함께 구성하세요. 매핑 값과 서명 입력은
  Key Vault 또는 로컬 전용 배포 입력에 보관합니다. 채널 권한 구성이 없거나 일부뿐이면 승인을
  사용할 수 없으며 Incoming Webhook으로 대체하지 않습니다.
- 교차 테넌트 SharePoint 인제스트를 사용하려면 SharePoint 및 Power Platform 연결을 Microsoft
  365 테넌트에 유지하고, 기본적으로 비활성화된 `power_platform_*` 정책 값을 로컬 `tfvars`
  파일에 설정하세요. 정확한 원본 테넌트, 승인된 OAuth 클라이언트, FDAI API 대상, 컬렉션,
  접근 서술자, 대상 그룹, 보존 정책 및 용도를 연결합니다. 배포 값이나 공급자 자격 증명을
  커밋하지 마세요.
- 범위가 제한된 OHL scale-out 근거 대상을 프로비저닝하려면 private networking과 개발 운영
  게이트웨이를 사용하는 `dev` 환경에서만 `enable_ohl_scale_out_evidence_target`을 사용하도록
  설정하세요. Exact 이미지 버전, 보호된 작업 흐름의 SSH 공개 키 입력, 재시도해도 유지되는
  캠페인 ID 및 사람 개시자의 주체 ID를 제공해야 합니다. 대상은 용량 `1`로 시작합니다. 수동
  proposal Job은 정상 수신 경로를 통해 shadow 제안 하나를 게시하며 provider-effect 권한은
  갖지 않습니다. 보호된 provider staging은 검증된 롤백 전에 용량을 `2`까지만 늘릴 수 있습니다.
- AKS runtime topology를 포함하려면 `inventory_kubernetes_api_server`,
  `inventory_kubernetes_cluster_ref`, `inventory_kubernetes_ca_pem`,
  `inventory_kubernetes_audience`를 함께 제공합니다. Inventory managed identity에는 AKS RBAC
  Reader만 부여하며 request 시점에 수명이 짧은 token을 취득합니다. Kubernetes bearer token을
  Terraform 또는 environment 구성에 넣지 마세요.
- rule-watcher 스냅샷을 보존하고 초안 전용 수집 검토를 열려면
  `enable_rule_catalog_snapshot_storage`와 기존 운영 책임(`stewardship`) GitOps 연결을 함께
  활성화하세요.
  GitHub 자격 증명은 Key Vault 시크릿 참조만 제공합니다. Watcher identity에는 Blob 데이터
  접근과 초안 검토 권한만 있으며 카탈로그 병합 또는 작업 권한은 없습니다.
- 운영 이력 lifecycle을 활성화하려면 비밀이 아닌 `ENABLE_OPERATIONAL_HISTORY` repository
  변수를 `true`로 설정한 뒤 정확히 증명된 Core 이미지 revision을 대상으로 보호된 `history-`
  계획과 적용을 실행합니다. 예약 Job은 inventory identity를 사용하는 shadow-only 상태를
  유지합니다. Enforce와 certify는 외부 증적을 요구하며 certify만 database purge gate에
  도달할 수 있습니다.
- 단계 4 측정을 예약하려면 필요한 기준선, 패턴 성장 또는 운영 승격 작업만 명시적으로
  활성화하세요. 세 작업은 모두 기본적으로 비활성화되며 이미지 가져오기, 상태 저장소 비밀,
  선택적 모델 추론 접근 권한만 있는 전용 측정 신원을 공유합니다. 실행기 신원이나 클라우드
  변경 역할은 받지 않습니다.
- 단계 3 스케줄러 또는 DB-DR 훈련을 활성화하기 전에 서로 분리된 작업 신원을 검토하세요.
  스케줄러는 Event Bus 전송, 이미지 가져오기 및 상태 저장소 비밀 접근 권한만 받습니다.
  DB-DR은 원본 읽기와 격리 대상 그룹 안의 PostgreSQL 복원 및 삭제 권한만 받습니다. 완전한
  구성 계획을 검토할 때까지 `dr_drill_dry_run=true`를 유지하세요.
- WARA를 예약하려면 umbrella Workload ID 하나, 해당 ID를 키로 사용하는 검토된 태그 및 서로
  일치하는 매시간 또는 UTC 자정 일별 실행 slot을 구성하세요. Job은 인벤토리 읽기 신원을
  사용하며 기존 Pantheon 물리 토픽에만 전송할 수 있습니다. Core T1 RCA는 platform에서 내보내
  split 서비스 계획에 hydrate하는 별도 Monitoring Reader 신원을 사용합니다. 관리되는 T2 문서
  grounding에는 별도 읽기 전용 문서 DSN secret과 정확한 컬렉션, 접근 참조, 읽기 그룹 입력도
  필요합니다.

## 최소 인벤토리 프로비저닝

먼저 미리보기하고, 계획이 예상과 일치할 때만 적용하세요. 보호된 경로는 비공개 계획 데이터를
VNet에 연결된 실행기에 유지하며 정확한 적용 전에 구성된 GitHub 환경 승인을 요구합니다.

프라이빗 네트워킹으로 전환하는 보호된 작업에서는 보호된 워크플로가 이미 허용한 검토된
삭제나 마이그레이션만 받아들입니다. 광범위한 PostgreSQL Azure-services 방화벽 규칙 제거가
그 예입니다. 계획에 같은 주소의 교체, 검토된 마이그레이션에서 벗어난 내용, 또는 다른 삭제가
보이면 적용을 중단하세요.

개발 운영 게이트웨이가 보호된 targeted 계획을 사용한다면 AI 계정과 역할 수집이 모두
포함됐는지 확인하세요. 그래야 네트워크 및 권한 확인 변경이 같은 적용에서 수렴하고
post-apply 계획이 남지 않습니다. 각 서비스 계획이 소유한 state만 변경하고 다른 네 서비스
state를 그대로 유지하는지 확인하세요.

<!-- fdai:tabs -->

#### fdaictl (보호된 dev 및 staging)

```bash
fdaictl deploy plan \
  --profile .fdai/environments/dev.json \
  --repository <owner>/<repository> \
  --commit-sha <git-sha> \
  --run-id <run-id> \
  --output json

fdaictl deploy status \
  --profile .fdai/environments/dev.json \
  --repository <owner>/<repository> \
  --request-id <request-id> \
  --commit-sha <git-sha> \
  --output json

fdaictl deploy apply \
  --profile .fdai/environments/dev.json \
  --repository <owner>/<repository> \
  --plan-id <plan-id> \
  --plan-digest <plan-digest> \
  --plan-expires-at <expires-at> \
  --commit-sha <git-sha> \
  --run-id <run-id> \
  --output json
```

`--plan-expires-at` 값은 정제된 `deploy status` 계획 메타데이터에서 가져옵니다. 계획이
만료되지 않았고, 저장소 대상과 지역이 프로필과 일치하며, GitHub 환경이 독립적인 검토자
한 명을 요구하고 자체 검토와 관리자 우회를 차단해야 적용 명령을 진행할 수 있습니다.
두 명 이상의 승인이 필요한 프로필과 모든 `prod` 요청은 차단됩니다.

#### azd (직접 개발 인프라)

```bash
azd auth login
azd env new fdai-dev
export AZURE_SUBSCRIPTION_ID="<expected-subscription-id>"
export AZURE_TENANT_ID="<expected-tenant-id>"
# 안전한 미리보기 - `azd provision --preview` 실행, 아무것도 적용하지 않음
scripts/deployment/azure/azd-up.sh
# 실제 인프라 프로비저닝 - 런타임 이미지는 보호된 서비스 작업 흐름 사용
FDAI_AZD_CONFIRM=1 scripts/deployment/azure/azd-up.sh
```

#### terraform (전문가용 직접 경로)

```bash
az login
export AZURE_SUBSCRIPTION_ID="<expected-subscription-id>"
export AZURE_TENANT_ID="<expected-tenant-id>"
scripts/deployment/azure/verify-azure-context.sh \
   "$AZURE_SUBSCRIPTION_ID" "$AZURE_TENANT_ID"
terraform -chdir=infra init
# 템플릿을 복사해 값을 채웁니다 (tfvars는 커밋하지 않음)
cp infra/envs/dev.tfvars.example infra/envs/dev.tfvars
terraform -chdir=infra plan  -var-file=envs/dev.tfvars
terraform -chdir=infra apply -var-file=envs/dev.tfvars
```

<!-- /fdai:tabs -->

## 프로비저닝 후

<!-- fdai:steps -->

1. **인벤토리 검증.** 리소스가 만들어졌는지, 실행기 자격 증명이 지정된 범위에서 최소
   권한만 갖는지 확인합니다. 그런 다음 아래 항목을 확인합니다.
   - 구독 Event Grid 전달이 인벤토리 관리 자격 증명으로 운영 Event Hubs 샤드의
     `fdai.inventory.raw`에 도달합니다.
   - 기본 샤드가 Standard 엔터티 10개 제한 안에 있고, Huginn이 테스트 리소스 변경을
     투영합니다.
   - 인벤토리 작업이 매분 깨어나고, PostgreSQL이 정상 전체 스캔을 6시간으로 유지하며,
     관측된 리소스 변경은 앞당겨 조정됩니다. 실패하거나 마감을 넘긴 시도는 범위가 제한된
     백오프 뒤에 재시도됩니다. 이때 코어에는 job-start 역할을 주지 않습니다.
   - Provider Schema Job이 daily run을 완료하고 PostgreSQL에 durable generation digest를
     보존하며 material change를 Heimdall의 shadow Drift로 전달합니다. Ontology, rule 또는
     policy를 자동으로 업데이트하지 않습니다.
   - Rule 수집 전달을 활성화한 경우 Rule Watcher Job은 내용 기반 주소가 지정된 스냅샷을
     비공개 Blob 컨테이너에 미러링하고, 변경되지 않은 내용에는 초안 검토를 최대 하나만
     엽니다. 재검증 시간은 패키지 ID를 바꾸지 않으며 Job은 카탈로그 내용을 병합하거나
     활성화하지 않습니다.
   - AKS topology를 구성한 경우 inventory identity에 AKS RBAC Reader만 있고 API endpoint가
     CA verification을 통과하며, static token secret 없이 완전 세대에 UID 기반 Kubernetes
     resource가 포함되는지 확인합니다.
   - 프라이빗 네트워킹을 켰다면 PostgreSQL과 두 Event Hubs 샤드가 런타임 서브넷이나 피어링된
     러너에서 프라이빗 주소로 확인되고, TLS 점검을 통과하며, Event Hubs 공개 접근이 꺼져
     있습니다.
2. **런타임 상태와 자격 증명 검증.** 5개 서비스 revision이 모두 정상인지, 15개 에이전트가
  Core 상태 스냅샷에 보고되는지, 첫 canary 발행기 작업이 완료됐는지 확인합니다. 이어서
  아래 경계를 확인합니다.
   - **Operator API**: 브라우저 Entra 앱 역할이 동작하고, 읽기와 명령 자격 증명이 Thor의 실행기
     관리 자격 증명과 분리돼 있습니다.
   - **Operator channel edge**: 활성화한 경우 최신 edge revision이 attested Operator image와 정확히
     하나의 non-executor identity를 사용하고, HTTPS의 `/health/ready`가 성공하며, primary Operator
     revision이 정상인지 확인합니다. Disable 또는 첫 enable 실패 시 복구가 완료되기 전에 공개
     edge resource가 없음을 증명해야 합니다.
   - **문서 서비스**: Document Ingestion API는 인증된 upload lifecycle 요청을 받고,
     Document Processing Worker만 영속 inspection, extraction, indexing, claim 및 reconciliation을
     소유합니다.
   - **Isolated Executor**: 내부 `/live`와 `/ready` 프로브가 통과하고 최신 revision이 활성 상태인지
     확인합니다. 전용 identity에는 image pull, 명령 수신, receipt 또는 DLQ 전송, state-secret
     읽기와 명시적으로 승인된 작업별 효과 역할만 있습니다. Core와 Operator에는 관리 대상
     리소스 효과 역할이 없습니다.
   - **이메일 알림**: incident-open 메시지가 multipart HTML과 plain 텍스트로 도착합니다. Console을
     활성화한 경우 상세 링크는 Static Web App 출처를 사용하고 Settings > Integrations는 합성
     자리 표시자로 동일한 렌더러를 표시합니다.
   - **문서 OCR**: Azure를 삭제하지 않고 로컬 한국어 및 영어 OCR을 사용하려면
     `use_local_retain`, 비공개 Document Intelligence 계정을 계획하려면
     `use_azure_provision`, 제거 전에 로컬 OCR을 선택하려면 `deprovision_use_local`을
     사용합니다. 수집 자격 증명은 구성된 Document Intelligence 리소스에만
     `Cognitive Services User` 역할을 갖습니다. 기본 동작은 계획이며 적용에는 별도 승인이
     필요합니다.
   - **케이스 히스토리**: 전용 관리 자격 증명만 Blob 데이터에 접근하고, 실행기에는
     케이스 히스토리 Blob 역할이 없으며, 비공개 네트워크 룰은 Defender scanner
     private-link 접근을 유지하고, `FDAI_CASE_HISTORY_RETENTION_TICK_SECONDS`가 승인된 삭제
     주기와 일치합니다.
   - **예측 학습**: 옵트인 작업이 원시 틱만 발행하고, 코어에 검토된
     `FDAI_FORECAST_TARGETS_JSON` 문서가 있습니다.
   - **Analyzer tick**: `FDAI_INVENTORY_DSN`이 설정되면 Job이 명시적 대상과 영속 인벤토리
     projection에서 지원되는 리소스만 병합하고 구성된 발견 상한을 보고합니다. 지원하지 않는
     리소스 타입은 제외하며, 완전히 해석된 대상 집합이 비어 있으면 정상 no-op으로 종료합니다.
    보호된 배포에서는 `TRACE_TOPOLOGIES_JSON` repository variable을 설정합니다. Workflow가 이를
    Job의 `FDAI_TRACE_TOPOLOGIES_JSON`으로 전달합니다. 같은 Job과 읽기 신원이 범위가 제한된 작업 영역
    기반 Application Insights 근거를 조회합니다. 완전한 추적은 발견된 문제를 보고하지 않고, 누락되거나
     분리된 hop은 관찰 모드로 하나를 보고합니다. 빈 값은 연속성 검사만 비활성화합니다.
   - **OHL scale-out 근거**: 활성화한 경우 수동 proposal Job을 시작하고, 설정된 캠페인과
     개시자가 포함된 shadow 제안 하나만 정상 수신 경로에 도달하는지 확인합니다. 이 자격
     증명에는 이미지 pull과 기본 Event Hubs send 권한만 있고 provider-effect 권한은 없습니다.
3. **개발 운영 게이트웨이 검증.** 이것은 개발 도구입니다. Easy Auth 뒤에서 공개
   인바운드 엔드포인트를 종단하며, Terraform은 `env=dev`가 아니면 계획 자체를 거부합니다.
   폐쇄망에서는 꺼둔 채로 두십시오. 이 게이트웨이를 켰다면 아래를 확인합니다.
   - 보호된 소스 아카이브가 Terraform 적용 뒤에 배포됐고, 현재 원격 빌드 배포가
     성공했습니다.
   - 두 함수 트리거가 등록됐고, 호스트와 멱등성 저장소가 읽기 담당 관리 자격 증명을
     사용하며, 등록된 네트워크 읽기가 성공합니다.
   - 실행기 주체로 제한된 변경 하나를 계획하고, 반환된 일회용 증적으로 제출한 뒤, 재실행이
     두 번째 ARM 호출을 만들지 않는지 확인하고, ARM이 `submitted`를 반환하는 동안 멱등성
     키로 상태를 조회합니다.
4. **제한된 범위 하나 온보딩.** 리소스 그룹 크기의 범위 하나로 시작하고 소유자를
   지정합니다.
5. **관찰 모드로 지켜보기.** FDAI가 아무것도 바꾸지 않고 판단과 감사만 하도록 두고, 실행했을
   법한 작업을 검토합니다.
6. **하나의 작업 승격.** 승격 기준을 통과한 작업만 적용 모드로 바꾸고, 나머지는 관찰 모드로
   둡니다.

[시작하기](get-started-ko.md) 가이드에서는 이 첫 번째 안전한 롤아웃을 자세히 다룹니다.
[배포와 온보딩](../roadmap/deployment/deploy-and-onboard-ko.md)은 전체 배포 참고 자료입니다.

## 관련 문서

<!-- fdai:cards -->

- [사전 점검](../roadmap/deployment/deployment-preflight-ko.md) - 프로비저닝 전에 차단 요소를 해소합니다.
- [배포와 온보딩](../roadmap/deployment/deploy-and-onboard-ko.md) - 전체 배포 참고 자료와 Azure 인벤토리.
- [시작하기](get-started-ko.md) - 오리엔테이션과 첫 번째 안전한 롤아웃.
- [운영자 콘솔](../roadmap/interfaces/operator-console-ko.md) - FDAI가 실행된 후 상태를 조회하는 방법.
