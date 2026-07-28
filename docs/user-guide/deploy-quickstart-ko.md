---
title: 배포 빠른 시작
description: FDAI 최소 Azure 인벤토리를 프로비저닝하는 방법. azd 턴키와 Terraform 직접 실행 두 경로 모두 먼저 미리보고, 계획이 맞을 때만 적용합니다.
translation_of: deploy-quickstart.md
translation_source_sha: b223b26faf52511c7a5b99d4b1a86ca87614954e
translation_revised: 2026-07-28
---

# 배포 빠른 시작

FDAI는 `infra/` 아래의 코드형 인프라(IaC)로 프로비저닝하며, Terraform이 실행 엔진이자 단일
기준입니다. 턴키 `azd` 래퍼를 쓰거나 Terraform을 직접 실행하는 두 경로로 동일한 최소 Azure
인벤토리를 구성할 수 있습니다. 두 경로 모두 먼저 미리보기를 제공하므로, 별도의 apply 단계를
실행하기 전에 plan을 검토할 수 있습니다.

## 시작하기 전에

- 리소스를 만들 수 있는 **Azure 구독**과 **Azure CLI**(`az`)가 필요합니다. 턴키
  경로에는 **Azure Developer CLI**(`azd`)도 필요합니다.
- [배포 사전 점검](../roadmap/deployment/deployment-preflight-ko.md)을 완료해야 합니다.
  이 점검은 컨트롤 루프가 시작되기 전에 쿼터, 권한, 연결, 롤백 차단 요소를 수집합니다.
- 환경별 값을 `*.tfvars` 파일에 입력합니다. 이 파일은 커밋하지 마세요.
- 승인된 대상을 `AZURE_SUBSCRIPTION_ID`와 `AZURE_TENANT_ID`로 export합니다. 현재 자격
  증명이나 선택된 `azd` 환경이 이 조합과 다르면, 부트스트랩과 턴키 헬퍼가 아무것도 바꾸기
  전에 중단합니다.
- 저장소 `Dockerfile`로 빌드한 FDAI 런타임 이미지가 필요합니다.
  `container-supply-chain.yml`이 생성한 커밋 태그를 `core_image`에 설정하세요. 프로덕션은
  증명된 다이제스트를 사용하며, Terraform은 예전 Azure CLI 자리표시자를 거부합니다.
- 배포 호스트에서 모든 private endpoint로 연결할 수 있어야 합니다. 프라이빗 전용 환경에서는
  운영자 워크스테이션 대신 VNet에 연결된 배포 러너에서 Terraform을 실행하세요. 그 환경의
  Premium 레지스트리도 프라이빗이므로 이미지 빌드와 푸시도 같은 러너에서 하세요.
- 보호된 원격 plan을 쓰려면 비밀이 아닌 `DEPLOY_PREFLIGHT_INPUT_JSON` 저장소 변수에 필요한
  라이브 카테고리를 모두 설정하세요. 프로필이 없으면 Azure 로그인 전에 중단하고, 프로브가
  차단되면 정제된 점검 결과와 발견된 문제만 로그에 남습니다.

## 최소 인벤토리 프로비저닝

먼저 미리보기하고, 계획이 예상과 일치할 때만 적용하세요. 두 경로 모두 동일한 `infra/`
Terraform 구성을 사용하므로 워크플로에 맞는 쪽을 고르면 됩니다.

프라이빗 네트워킹으로 전환하는 보호된 작업에서 허용되는 delete는 광범위한 PostgreSQL
Azure-services 방화벽 규칙을 없애는 것 하나뿐입니다. plan에 같은 주소의 교체나 다른 delete가
보이면 apply를 중단하세요.

<!-- fdai:tabs -->

#### azd (턴키)

```bash
azd auth login
azd env new fdai-dev
export AZURE_SUBSCRIPTION_ID="<expected-subscription-id>"
export AZURE_TENANT_ID="<expected-tenant-id>"
# 안전한 미리보기 - `azd provision --preview` 실행, 아무것도 적용하지 않음
scripts/deployment/azure/azd-up.sh
# 실제 프로비저닝 - 두 번째 게이트가 실수로 적용하는 일을 막음
FDAI_AZD_CONFIRM=1 scripts/deployment/azure/azd-up.sh
```

#### terraform (직접)

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
     `aw.inventory.raw`에 도달합니다.
   - 기본 샤드가 Standard 엔터티 10개 제한 안에 있고, Huginn이 테스트 리소스 변경을
     투영합니다.
   - Inventory Job이 10분마다 깨어나고, PostgreSQL이 정상 전체 스캔을 6시간으로 유지하며,
     실패하거나 중단된 시도가 다음 tick에 재시도됩니다. 이때 코어에는 job-start 역할을
     주지 않습니다.
   - 프라이빗 네트워킹을 켰다면 PostgreSQL과 두 Event Hubs 샤드가 런타임 서브넷이나 피어링된
     러너에서 프라이빗 주소로 확인되고, TLS 점검을 통과하며, Event Hubs 공개 접근이 꺼져
     있습니다.
2. **런타임 상태와 자격 증명 검증.** 내부 코어 프로브가 정상인지, 15개 에이전트가 모두 상태
   스냅샷에 보고되는지, 첫 canary publisher Job이 완료됐는지 확인합니다. 이어서 켜 둔 기능만
   확인합니다.
   - **읽기 API**: 브라우저 Entra 앱 역할이 동작하고, 읽기와 명령 자격 증명이 Thor의 실행기
     관리 자격 증명과 분리돼 있습니다.
   - **문서 OCR**: 수집 자격 증명이 지정된 Document Intelligence 리소스에만
     `Cognitive Services User` 역할을 갖습니다.
   - **케이스 히스토리**: 전용 관리 자격 증명만 Blob 데이터에 접근하고, 실행기에는
     케이스 히스토리 Blob 역할이 없으며, `FDAI_CASE_HISTORY_RETENTION_TICK_SECONDS`가 승인된
     삭제 주기와 일치합니다.
   - **예측 학습**: 옵트인 Job이 원시 tick만 발행하고, 코어에 검토된
     `FDAI_FORECAST_TARGETS_JSON` 문서가 있습니다.
3. **개발 운영 게이트웨이 검증.** 이것은 개발 도구입니다. Easy Auth 뒤에서 public
   inbound endpoint를 종단하며, Terraform은 `env=dev`가 아니면 plan 자체를 거부합니다.
   폐쇄망에서는 꺼둔 채로 두십시오. 이 게이트웨이를 켰다면 아래를 확인합니다.
   - 보호된 소스 아카이브가 Terraform apply 뒤에 배포됐고, 현재 원격 빌드 배포가
     성공했습니다.
   - 두 Function 트리거가 등록됐고, 호스트와 idempotency 저장소가 reader 관리 자격 증명을
     사용하며, 등록된 네트워크 읽기가 성공합니다.
   - 실행기 주체로 제한된 변경 하나를 plan하고, 반환된 일회용 receipt로 제출한 뒤, 재실행이
     두 번째 ARM 호출을 만들지 않는지 확인하고, ARM이 `submitted`를 반환하는 동안 idempotency
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
