---
title: 배포 리소스 규약
translation_of: deployment-resource-conventions.md
translation_source_sha: 277d42b675cf4b481faf689a3673b8e01b4cb08c
translation_revised: 2026-08-01
---
# 배포 리소스 규약

이 문서는 FDAI가 프로비저닝하는 인프라의 리소스 명명 및 태깅 규약을 정의합니다.
Terraform 플랜을 결정론적으로 유지하고, 리소스 소유권을 질의 가능하게 만들며, 배포별 값을
upstream distribution 외부에 두는 데 사용하세요.

> 이 계약은 프로비저닝된 인프라에 적용됩니다. 런타임 코드는 설정을 통해 리소스 식별자를
> 사용하며 이름이나 소유권 태그를 계산하지 않습니다.

## 리소스 명명 규약(Resource Naming Convention)

이 리포지토리가 프로비저닝하는 모든 Azure 리소스는 **Microsoft Cloud Adoption Framework
(CAF)** 축약 규약을 따릅니다. 이름은 결정론적이고 배포에 종속되지 않으며 grep할 수 있습니다.
이름 변경은 Terraform diff로 처리하고 손으로 편집하지 않습니다.

패턴:

```
<caf-prefix>-<workload>[-<component>][-<env>][-<region>][-<instance>]
```

- **workload**: 고정 리터럴 `fdai`입니다. 제품 이름이며 고객 식별자가 아니므로
  [generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)에
  따라 허용됩니다.
- **component**: 같은 리소스 종류를 두 개 이상 프로비저닝할 때만 추가합니다. 예를 들어
  `ca-fdai-core`와 향후 `ca-fdai-worker`를 구분합니다.
- **env** (`dev`/`staging`/`prod`)와 **region** (`krc`/`weu`/`eus`): 리소스를 나란히
  배포할 때만 접미사로 추가합니다. Day-zero 배포는 접미사를 사용하지 않습니다.
- **instance** (`01`, `02`, ...): 한 환경에 여러 복사본이 있을 때만 추가합니다.

기본 **리소스 그룹**은 `rg-fdai`입니다. 구독 범위 배치가 필요한 리소스 종류를 제외하면
시스템이 프로비저닝하는 모든 리소스가 이 리소스 그룹에 속합니다. 현재 해당 예외는 없습니다.

### Day-zero 인벤토리용 CAF 접두사

| 리소스 | CAF 접두사 | 문자 규칙 | 예시 이름 |
|--------|------------|-----------|-----------|
| Resource Group | `rg-` | 1-90; 영숫자 + 하이픈/밑줄 | `rg-fdai` |
| User-assigned Managed Identity | `id-` | 3-128 | `id-fdai-executor` |
| Container Apps environment | `cae-` | 2-32; 영숫자 + 하이픈 | `cae-fdai` |
| Container App (core) | `ca-` | 2-32 | `ca-fdai-core` |
| Container Apps Job (out-of-band) | `caj-` | 2-32 | `caj-fdai-oob` |
| Event Hubs namespace | `evhns-` | 6-50 | `evhns-fdai` |
| PostgreSQL Flexible Server | `psql-` | 3-63; 소문자 | `psql-fdai` |
| Key Vault | `kv-` | 3-24; 영숫자 + 하이픈 | `kv-fdai` |
| **Container Registry (ACR)** | `cr` | 5-50; **영숫자만 허용, 하이픈 불가** | `crfdai` |
| Log Analytics workspace | `log-` | 4-63 | `log-fdai` |
| Foundry account (`AIServices`) | `aif-` | 2-64; 영숫자 + 하이픈 | `aif-fdai-search` |
| Foundry account project | `proj-` | 2-64; 영숫자 + 하이픈 | `proj-fdai-search` |
| Azure Bot (HIL Adaptive Cards) | `bot-` | 2-64 | `bot-fdai` |
| Static Web App (read-only console) | `stapp-` | 2-40 | `stapp-fdai` |

### 길이 안전 규칙

- **ACR 이름에는 하이픈을 넣지 않습니다**. 접두사 `cr`를 workload 토큰과 결합해
  `crfdai`로 사용합니다. env/region 접미사를 추가할 때도 하이픈을 다시 넣지 않고
  `crfdaidevkrc01`처럼 연속된 소문자 영숫자 문자열을 사용합니다.
- **Storage account**는 최대 24자의 소문자 영숫자를 사용합니다. Document storage는
  전역 고유성을 위해 subscription + environment에서 파생한 안정적인 6자 해시를 추가합니다.
- env/region/instance를 추가한 합법적 이름이 문자 제한을 넘으면 해당 리소스 종류에만
  문서화된 짧은 이름 `aip`를 `fdai` 대신 사용합니다. 전체 이름이 제한 안에 있으면
  `aip`를 사용하지 않습니다.

### 이 규칙이 방지하는 항목

- **무작위 접미사**: Storage처럼 전역 고유 이름이 필요한 경우 짧고 결정론적인 해시는
  허용됩니다. 플랜마다 바뀌는 접미사는 리뷰를 차단합니다.
- **식별자 안의 고객 이름 또는 환경 값**: 이 값은 리소스 이름이 아니라 `*.tfvars`와
  태그 맵에 둡니다.
- **Python의 인라인 명명 로직**: 앱은 환경 변수에서 식별자를 읽고, `infra/`가 플랜 시점에
  이름을 결정합니다.

## 리소스 태깅 규약(Resource Tagging Convention)

명명은 리소스를 읽기 쉽게 만들고, 태깅은 플릿을 질의 가능하게 만듭니다. 이 리포지토리가
프로비저닝하는 모든 리소스는 작고 기계 파싱 가능한 태그 세트를 가집니다. FDAI 소유 키는
모두 `fdai:` 접두사 아래에 네임스페이스되므로 전체 세트를 grep할 수 있고, 다른 팀의 리소스가
함께 있는 **공유 구독**에서도 FDAI가 프로비저닝한 리소스를 구분할 수 있습니다. 태그 맵은
Terraform의 `infra/main.tf` `base_tags`에서 결정하며 Python에서 계산하지 않습니다.

### 기본 태그 세트

| 태그 키 | 값 | 소스 | 목적 |
|---------|----|------|------|
| `fdai:managed` | `true` | 상수 | **소유권 마커.** "FDAI가 이 리소스를 프로비저닝했다"는 것을 나타내는 단일 권위 플래그입니다. `az resource list --tag fdai:managed=true`는 FDAI 소유 리소스를 정확히 열거하며 영향 범위 제한, 정리/감사 교차 확인, 비용 귀속의 기반이 됩니다. |
| `fdai:workload` | `fdai` | `var.workload` | 제품/workload 토큰이며 CAF 이름 토큰과 일치합니다. |
| `fdai:env` | `day-zero` / `dev` / `staging` / `prod` | `var.env` | 환경입니다. `day-zero`는 한정되지 않은 배포입니다. |
| `fdai:layer` | `control-plane` / `ops-bootstrap` | 설정별 | 앱 spoke인 `infra/main.tf`와 ops/hub bootstrap인 `infra/bootstrap`을 구분하는 아키텍처 계층입니다. |
| `fdai:managed-by` | `terraform` | 상수 | 프로비저닝 도구입니다. |
| `fdai:vertical` | `shared` / `resilience` / `change-safety` / `cost-governance` | `var.cost_vertical` (기본값 `shared`) | 리소스 비용을 귀속할 AIOps vertical입니다. 여러 vertical이 공유하는 control-plane 인프라는 `shared`를 유지하고, 세 executor MI 같은 vertical별 리소스가 이 키를 재정의합니다. |

### `fdai:managed`가 중요한 이유

executor는 FDAI가 소유하지 않는 리소스도 호스팅하는 구독 안에서 실행될 수 있습니다.
소유권 마커를 사용하면 control plane이 이 경계를 그을 수 있습니다. 이 마커는 한 스크립트에
하드코딩한 동작이 아니라 다음 기능이 사용하는 질의 키입니다.

- **영향 범위 제한**: 자율 액션이 대상 집합을 제한해야 한다는 안전 불변식을
  `fdai:managed=true`에 대해 표현합니다. 따라서 수정 작업은 FDAI가 만든 리소스로 제한되고
  FDAI가 만들지 않은 리소스에는 도달하지 않습니다.
- **정리와 감사**: `terraform destroy`는 상태를 기준으로 프로비저닝된 플릿을 제거합니다.
  마커는 sweep 또는 감사에서 리소스를 삭제 대상으로 고려하기 전에 FDAI 소유인지 확인하는
  out-of-band 교차 확인 수단입니다.
- **비용 귀속**: Cost Management와 Resource Graph는 `fdai:vertical`로 지출을 그룹화하고
  전체 FDAI 사용량을 `fdai:managed=true` 슬라이스로 분리할 수 있습니다.

### 배포 공급 태그(`additional_tags`)

고객별 및 환경별 키는 `base_tags`에 하드코딩하지 않습니다. 배포는 커밋하지 않은
`*.tfvars`의 `additional_tags` 맵을 통해 값을 공급하며 `fdai:` 네임스페이스를 유지합니다.

```hcl
additional_tags = {
  "fdai:cost-center"         = "cc-1234"
  "fdai:owner"               = "team-platform"
  "fdai:criticality"         = "high"
  "fdai:data-classification" = "internal"
}
```

`additional_tags`는 `base_tags` 위에 병합되므로 배포에서 core를 편집하지 않고
`fdai:vertical` 고정과 같은 기본값 재정의도 할 수 있습니다.

### 리소스별 재정의

모듈 호출은 로컬 `merge`로 단일 키를 좁힐 수 있습니다. 예를 들어 vertical별 executor MI는
`merge(local.tags, { "fdai:vertical" = "resilience" })`를 설정합니다. 한 리소스가 한 개념에
대해 경쟁하는 키 두 개를 가지지 않도록 같은 `fdai:` 네임스페이스를 사용하세요. 같은 리소스
종류를 여러 번 프로비저닝할 때는 `core`와 `worker` 같은 CAF component 토큰을 위해
`fdai:component`를 예약합니다.

### 규칙

- **모든 FDAI 키에 `fdai:` 네임스페이스를 사용합니다**: `env` 또는 `vertical` 같은 bare
  key는 다른 팀과 충돌하고 grep 가능성 보장을 깨뜨립니다.
- **고객 및 secret 값을 `base_tags`에 넣지 않습니다**: 배포별 이름과 마찬가지로 커밋하지
  않은 `*.tfvars`의 `additional_tags`에 둡니다.
- **질의 값을 안정적인 소문자로 유지합니다**: Cost Management와 Resource Graph는 `true`,
  `dev`, `resilience` 같은 리터럴 값으로 그룹화하므로 drift가 발생하면 집계가 깨집니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 구체적인 리소스 인벤토리 및 bootstrap 순서 | [배포 및 온보딩](deploy-and-onboard-ko.md) |
| 배포 lifecycle 및 environment 모델 | [배포](deployment-ko.md) |
| 고객 비종속 배포 설정 | [Customer-Agnostic Scope](../../../.github/instructions/generic-scope.instructions.md) |
