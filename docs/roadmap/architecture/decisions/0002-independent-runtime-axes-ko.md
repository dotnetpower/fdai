---
title: ADR-0002 Independent Runtime and Customization Axes
translation_of: 0002-independent-runtime-axes.md
translation_source_sha: ef947df1e66033eb1a293306de43b7f8d03f07da
translation_revised: 2026-07-21
---
# ADR-0002: 독립적인 Runtime 및 Customization 축

이 record는 FDAI가 어디서 실행되는지, 어떤 evidence를 읽는지, 누가 동작할 수 있는지,
action을 실행할 수 있는지, downstream distribution을 어떻게 customize하는지를 결정하는
configuration 축을 분리합니다. `local`, `dev`, `shadow`, `fork`가 서로의 별칭이 되는 것을
방지합니다.

## 상태

**Accepted:** 2026-07-20.

## Context

이전 design text는 여러 독립 concern을 결합했습니다. Local development가 test fake 또는
shadow-only behavior를 의미하는 경우가 있었습니다. Downstream fork도 production 또는 customer
environment처럼 설명되는 경우가 많았습니다. Authentication flag는 browser operator, Azure data
access, privileged executor도 혼합했습니다.

이러한 shortcut은 production-parity debugging을 불가능하게 만들고 authorization defect를
숨깁니다. 또한 fork가 실제 의미인 capability 제한 또는 확장 distribution이 아니라 실행 위치나
운영 상태처럼 보이게 합니다.

## Decision

FDAI는 다음 축을 독립 configuration으로 취급합니다.

| 축 | 대표 값 | Authority |
|----|---------|-----------|
| 실행 위치 | `local`, `deployed` | process launcher |
| 배포 환경 | `dev`, `staging`, `production` | deployment configuration |
| Evidence profile | `authoritative`, `fixture` | composition root |
| Action lifecycle | `shadow`, `enforce` | ActionType 및 Workflow별 promotion registry |
| 사용자 identity | Entra principal 및 App Role | browser token 및 RBAC policy |
| Executor identity | managed workload identity | deployed executor boundary |
| Distribution | `upstream`, `fork` | source 및 customization boundary |
| Operational safety profile | `mscp-operational-v1` | Versioned core policy, 실행 authority 아님 |

어떤 축의 값도 다른 축의 값을 선택하지 않습니다. 특히 다음 계약을 적용합니다.

- Local 실행은 shadow mode, test fixture, anonymous authorization 또는 local-only business logic을
  강제하지 않습니다.
- Development deployment는 production과 같은 risk, approval, blast-radius, rollback, audit gate를
  통과할 때 promoted action을 enforce mode로 실행할 수 있습니다.
- Production deployment도 어떤 action이든 shadow mode로 유지할 수 있습니다.
- Fork는 모든 environment에 deployment가 없거나 여러 개 있을 수 있습니다. Upstream도 직접
  deploy할 수 있습니다.
- Fork detection은 upstream framework surface를 보호합니다. Runtime behavior, autonomy, identity,
  environment를 변경하지 않습니다.
- Operational safety profile은 실행 위치, environment, evidence, lifecycle, identity 및
  distribution과 독립적입니다. Profile check는 기존 autonomy decision을 유지하거나 낮출 수만
  있습니다.

### Interactive local profile

기본 interactive local profile은 production-parity control-plane client 및 runtime입니다.

- Browser는 deployment와 같은 Entra JWT 및 App Role 검사를 사용합니다.
- Azure CLI credential은 development data plane을 읽는 local Azure provider adapter로 제한합니다.
  Browser principal 또는 executor identity를 대체하지 않습니다.
- 동일한 agent pantheon, catalog, promotion registry, risk gate, Process journal, stage event를
  local에서도 실행합니다.
- Pantheon startup은 기본 활성 상태입니다. `FDAI_START_PANTHEON`이 없으면 모든 agent를
  활성화하고 명시적인 false 값만 비활성화합니다. Event Hubs configuration은 Azure transport를
  선택하며 runtime 존재 여부를 결정하지 않습니다. Event Hubs가 없으면 local in-process
  EventBus가 agent message와 status를 전달하고 Azure evidence는 unavailable 상태를 유지합니다.
- Privileged execution은 Thor의 deployed managed identity 뒤에 유지합니다. Local process는
  governed command를 development event bus로 publish하며 developer token으로 실행하지 않습니다.
- Authoritative provider가 없으면 unavailable로 표시하거나 fail closed합니다. Fixture를 선택하지
  않습니다.

Automated test와 명시적인 mock application은 `fixture` evidence profile을 선택할 수 있습니다.
Offline interactive 작업은 repository catalog 및 reference screen으로 제한하며 runtime claim을
만들지 않습니다.

### Shadow 및 promotion

Shadow-first는 development-environment policy가 아니라 capability lifecycle invariant입니다. 새
ActionType과 Workflow는 모든 위치에서 shadow로 시작합니다. Promotion evidence를 통과한 후 모든
실행 위치는 같은 authoritative lifecycle state를 관찰합니다. Local flag는 action을 promote할 수
없으며 local 실행은 risk 또는 approval decision을 낮출 수 없습니다.

### Fork boundary

Fork는 downstream distribution customization boundary입니다. 다음 작업을 할 수 있습니다.

- upstream provider Protocol에 다른 implementation을 binding합니다.
- 지원되는 seam을 통해 capability, catalog, policy, presentation overlay를 추가하거나 제거합니다.
- upstream safety invariant를 유지하면서 더 좁거나 넓은 product profile을 package합니다.

Deployment value, environment name, tenant identifier, secret, runtime promotion state는 deployment
configuration입니다. Fork가 소유한 deployment repository에서 제공할 수 있지만 이러한 값이
fork를 정의하지 않으며 fork도 production을 의미하지 않습니다.

## 검토한 대안

| 대안 | 선택하지 않은 이유 |
|------|---------------------|
| Local을 shadow-only로 유지 | promoted behavior 및 RBAC의 end-to-end debugging을 막습니다. |
| Local process에 executor privilege 부여 | operator와 executor identity를 합칩니다. |
| 모든 customer deployment를 fork로 취급 | source distribution을 tenancy 및 environment와 결합합니다. |
| Instruction만으로 축 보존 | Prose는 충돌하는 edit를 결정적으로 차단할 수 없습니다. |

## Consequence

- Local startup은 기본적으로 실제 Entra, Azure data-plane binding, 전용 development consumer
  identity가 필요합니다.
- 동일한 input과 promotion state에 대해 local 및 deployed decision snapshot을 비교할 수 있습니다.
- Test fixture에는 명시적인 pytest 또는 mock profile이 필요합니다.
- Documentation 및 configuration key는 자신이 제어하는 축을 이름에 나타내야 합니다.
- Instruction 및 design-document routing에는 machine-readable manifest와 edit-time gate가
  필요합니다.
- 기존 `production fork`, `dev-mode fake`, local shadow-only 표현을 migration해야 합니다.

## Evidence

- [Application Shape](../../../../.github/instructions/app-shape.instructions.md)
- [Dev/Deploy Parity](../../deployment/dev-and-deploy-parity-ko.md)
- [User RBAC 및 Identity](../../interfaces/user-rbac-and-identity-ko.md)
- [Operator-Initiated SRE 및 ARB](../../operations/operator-initiated-sre-and-arb-ko.md)
- [Downstream Fork Guide](../../fork-and-sequencing/downstream-fork-guide-ko.md)
- [`design-routes.json`](../../../../scripts/lib/design-routes.json)

## 다음 단계

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| Azure platform baseline | [ADR-0001](0001-azure-day-zero-platform-ko.md) |
| Runtime composition boundary | [Project Structure](../project-structure-ko.md) |
| ADR process | [Architecture Decision Record](README-ko.md) |
