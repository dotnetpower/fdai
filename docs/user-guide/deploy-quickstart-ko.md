---
title: 배포 빠른 시작
description: FDAI 최소 세트 인벤토리를 Azure에 프로비저닝하는 방법. 동등한 두 경로(azd 턴키 또는 Terraform 직접 실행) 모두 먼저 미리보고, 계획이 맞을 때만 적용합니다.
translation_of: deploy-quickstart.md
translation_source_sha: e212a5baabf1928c65dd74593338bd920fd15d6a
translation_revised: 2026-07-22
---

# 배포 빠른 시작

FDAI는 `infra/` 아래의 코드형 인프라(IaC)를 사용해 프로비저닝하며, Terraform을 실행
엔진이자 단일 기준으로 사용합니다. 턴키 `azd` 래퍼를 사용하거나 Terraform을 직접 실행하는 두
가지 동등한 경로로 동일한 최소 세트 Azure 인벤토리를 구성할 수 있습니다. 두 경로 모두
미리보기 우선 워크플로를 지원합니다. 별도의 apply 단계를 실행하기 전에 plan을 검토하세요.

## 시작하기 전에

- 리소스를 만들 수 있는 **Azure 구독**과 **Azure CLI**(`az`)가 필요합니다. 턴키
   경로에는 **Azure Developer CLI**(`azd`)도 필요합니다.
- [배포 사전 점검](../roadmap/deployment/deployment-preflight-ko.md)을 완료해야 합니다.
   이 점검은 컨트롤 루프가 시작되기 전에 쿼터, 권한, 연결, 롤백 차단 요소를 수집합니다.
- 환경별 값을 `*.tfvars` 파일에 입력합니다. 이 파일은 **커밋하지 마세요**.
- 저장소 `Dockerfile`로 빌드한 FDAI runtime image가 필요합니다.
   `container-supply-chain.yml`이 생성한 commit tag를 `core_image`에 설정하고 production에서는
   attested digest를 사용하세요. Terraform은 이전 Azure CLI placeholder를 차단합니다.
- 배포 호스트에서 모든 private endpoint로 연결할 수 있어야 합니다. Private-only 환경에서는
   운영자 워크스테이션 대신 VNet에 연결된 배포 runner에서 Terraform을 실행하세요.
- Protected remote plan은 non-secret `DEPLOY_PREFLIGHT_INPUT_JSON` repository variable에
   required live category를 모두 설정해야 합니다. Profile이 없으면 Azure login 전에 중단하며,
   probe가 차단되면 정제된 점검 결과만 로그에 출력합니다.

## 최소 세트 인벤토리 프로비저닝

먼저 미리보기하세요. 계획이 예상과 일치할 때만 적용하세요. 워크플로에 맞는 경로를
선택하면 됩니다. 두 경로 모두 동일한 `infra/` Terraform 구성을 사용합니다.

<!-- fdai:tabs -->

#### azd (턴키)

```bash
azd auth login
azd env new fdai-dev
# 안전한 미리보기 - `azd provision --preview` 실행, 아무것도 적용하지 않음
scripts/deployment/azure/azd-up.sh
# 실제 프로비저닝 - 두 번째 게이트가 실수로 적용하는 일을 막음
FDAI_AZD_CONFIRM=1 scripts/deployment/azure/azd-up.sh
```

#### terraform (직접)

```bash
az login
terraform -chdir=infra init
# 템플릿을 복사해 값을 채웁니다 (tfvars는 커밋하지 않음)
cp infra/envs/dev.tfvars.example infra/envs/dev.tfvars
terraform -chdir=infra plan  -var-file=envs/dev.tfvars
terraform -chdir=infra apply -var-file=envs/dev.tfvars
```

<!-- /fdai:tabs -->

## 프로비저닝 후

<!-- fdai:steps -->

1. **인벤토리 검증.** 리소스가 프로비저닝됐는지, 실행자(executor) 아이덴티티가 지정된
   범위에서 최소 권한만 갖는지 확인합니다. Subscription Event Grid delivery가 inventory
   managed identity로 `aw.inventory.raw`에 도달하는지, Huginn이 test resource change를
   project하는지, 6시간 ARG/ARM reconciliation Job이 예약되어 있는지 확인합니다.
2. **Runtime health 및 identity 검증.** 내부 core probe가 정상인지, 15개 agent가 모두 Pantheon
   health snapshot에 보고되는지, 즉시 실행한 canary publisher Job이 완료됐는지 확인합니다.
   Read API를 사용하면 browser Entra App Role을 검증하고 read/command credential이 Thor의
   executor Managed Identity와 분리됐는지 확인합니다.
3. **Development operations gateway 검증.** 이 gateway를 사용하면 보호된 source archive가
   Terraform apply 후에 배포됐는지, 현재 remote-build deployment가 성공했는지, 두 Function
   trigger가 등록됐는지, host 및 idempotency storage가 reader managed identity를 사용하는지,
   registered network read가 성공하는지 확인합니다. Executor principal로 bounded mutation 하나를
   plan하고 반환된 일회용 receipt로 제출한 다음 replay가 두 번째 ARM 호출을 만들지 않는지 확인합니다.
   ARM이 `submitted`를 반환하면 idempotency key로 상태를 조회합니다.
4. **제한된 범위 하나 온보딩.** 리소스 그룹 수준과 동등한 범위 하나로 시작하고
   소유자를 지정합니다.
5. **shadow 모드로 관찰.** FDAI가 변경을 적용하지 않고 판단과 감사만 수행하도록 두고,
   실행됐을 액션을 검토합니다.
6. **하나의 액션 승격.** 승격 게이트를 통과한 액션만 적용 모드로 전환하고, 나머지는
   shadow로 둡니다.

[시작하기](get-started-ko.md) 가이드에서는 이 첫 번째 안전한 롤아웃을 자세히 다룹니다.
[배포와 온보딩](../roadmap/deployment/deploy-and-onboard-ko.md)은 전체 배포 참고 자료입니다.

## 관련 문서

<!-- fdai:cards -->

- [사전 점검](../roadmap/deployment/deployment-preflight-ko.md) - 프로비저닝 전에 차단 요소를 해소합니다.
- [배포와 온보딩](../roadmap/deployment/deploy-and-onboard-ko.md) - 전체 배포 참고 자료와 Azure 인벤토리.
- [시작하기](get-started-ko.md) - 오리엔테이션과 첫 번째 안전한 롤아웃.
- [운영자 콘솔](../roadmap/interfaces/operator-console-ko.md) - FDAI가 실행된 후 상태를 조회하는 방법.
