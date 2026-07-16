---
title: 배포 Quickstart
description: FDAI 최소 세트 인벤토리를 Azure에 프로비저닝 - 두 가지 동등한 경로(azd 턴키 또는 Terraform 직접), 먼저 미리보기, 계획이 맞을 때만 적용.
translation_of: deploy-quickstart.md
translation_source_sha: 4ed39d29aafab144c9e4cfc307ff741abf889846
translation_revised: 2026-07-17
---

# 배포 Quickstart

FDAI는 `infra/` 아래의 코드형 인프라(IaC)에서 프로비저닝되며, Terraform이 실행
엔진이자 진실의 원천입니다. 두 가지 동등한 경로가 동일한 최소 세트 Azure 인벤토리를
세웁니다: 턴키 `azd` 래퍼, 또는 Terraform 직접. 둘 다 적용 전에 미리보기하므로,
실수로 프로비저닝하는 일은 불가능합니다.

## 시작하기 전에

- 리소스를 만들 수 있는 **Azure 구독**과 **Azure CLI**(`az`) - 그리고 턴키
  경로를 위한 **Azure Developer CLI**(`azd`).
- 완료된 [배포 사전 점검](../roadmap/deployment/deployment-preflight-ko.md) -
  컨트롤 루프가 시작되기 전에 쿼터, 권한, 연결, 롤백 차단 요소를 수집합니다.
- `*.tfvars` 파일에 담긴 환경별 값 - 이 파일은 **결코 커밋되지 않습니다**.

## 최소 세트 인벤토리 프로비저닝

먼저 미리보기하세요. 계획이 예상과 일치할 때만 적용하세요. 워크플로에 맞는 경로를
고르면 됩니다 - 둘 다 동일한 `infra/` Terraform을 프로비저닝합니다.

<!-- fdai:tabs -->

#### azd (턴키)

```bash
azd auth login
azd env new fdai-dev
# 안전한 미리보기 - `azd provision --preview` 실행, 아무것도 적용하지 않음
scripts/azd-up.sh
# 실제 프로비저닝 - 두 번째 게이트가 실수 적용을 막음
FDAI_AZD_CONFIRM=1 scripts/azd-up.sh
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

1. **인벤토리 검증.** 리소스가 프로비저닝되었고 실행자(executor) 아이덴티티가
   범위가 제한된 최소 권한만 가지는지 확인합니다.
2. **하나의 제한된 스코프 온보딩.** 리소스 그룹과 동등한 스코프 하나로 시작하고
   소유자를 지정합니다.
3. **shadow 모드로 관찰.** FDAI가 변경 없이 판단과 감사만 하도록 두고, 실행 예정
   액션을 검토합니다.
4. **하나의 액션 승격.** 승격 게이트를 통과한 액션만 enforce로 켜고, 나머지는
   shadow로 둡니다.

[시작하기](../get-started/) 가이드가 이 첫 번째 안전한 롤아웃을 자세히 다루고,
[배포와 온보딩](../roadmap/deployment/deploy-and-onboard-ko.md)이 전체 배포
참고 자료입니다.

## 관련 문서

<!-- fdai:cards -->

- [사전 점검](../roadmap/deployment/deployment-preflight-ko.md) - 프로비저닝 전에 차단 요소를 해소합니다.
- [배포와 온보딩](../roadmap/deployment/deploy-and-onboard-ko.md) - 전체 배포 참고 자료와 Azure 인벤토리.
- [시작하기](../get-started/) - 오리엔테이션과 첫 번째 안전한 롤아웃.
- [운영자 콘솔](../roadmap/interfaces/operator-console-ko.md) - FDAI가 라이브가 되면 실행하고 질의합니다.
