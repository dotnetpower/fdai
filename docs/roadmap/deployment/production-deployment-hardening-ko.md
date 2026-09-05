---
title: 운영 배포 강화
translation_of: production-deployment-hardening.md
translation_source_sha: ba63cddc79294fbb78431d7784ba57eece236356
translation_revised: 2026-09-05
---
# 운영 배포 강화

이 문서는 런타임 계약을 바꾸지 않고 FDAI 개발 자세를 강화하는 운영 전용 배포 제어를
정의합니다. 해체 동작, 내구성, 비공개 네트워킹, 신뢰할 수 있는 이미지, 알림 대상,
모니터링 및 비용 상한을 다룹니다.

> **범위:** 이 값은 범용 환경 매개변수입니다. 배포는 테넌트 데이터를 커밋하지 않고 보호된
> 구성을 통해 자체 대상과 값을 제공합니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 운영 계획 gate 및 환경 knob | implemented | `infra/production-gates.tf`, `infra/envs/{staging,prod}.tfvars.example`, Terraform 구성 테스트 | 서명된 이미지, 비공개 네트워크, 내구성, 모니터링 또는 비용 입력이 없으면 운영 계획을 차단합니다. 표준 프로파일은 전역 이름을 사용하는 리소스를 영구 삭제하고 관리 잠금을 비활성화합니다. |
| 자격 증명 없는 인프라 및 drift gate | implemented | `.github/workflows/infra-lint.yml`, `.github/workflows/infra-drift.yml`, 안정적인 배포 신원 도우미, 실행기 상태 스크립트, CI 계약 테스트 | 보호된 workflow는 bootstrap이 소유한 UAMI 하나를 선택하고 token `oid`를 검증하며 각 적용 작업을 해당 GitHub Environment에 연결한 뒤 Terraform 실행 전에 승인 정책을 다시 확인합니다. Drift 검사는 모든 상태 root를 다루며 상태 누락, 예상하지 않은 실행기 저장소 또는 로컬이 아닌 배치를 거부합니다. |
| Baseline 없는 Terraform 보안 검사 | implemented | `.github/workflows/infra-lint.yml`, 인라인 Checkov 및 Trivy 예외, 집중 인프라 테스트 | Checkov와 Trivy에 Low를 초과하는 활성 점검 결과가 없습니다. 의도적 예외는 하나의 리소스에 연결되고 보완 제어 또는 관리형 서비스 제약을 인용합니다. 새로 발견된 문제는 소스에서 수정하거나 범위가 좁고 검토된 예외를 기록할 때까지 CI를 차단합니다. |
| 범위가 제한된 split-service 선행 조건 bootstrap | implemented | `deploy-dev.yml`, `enforce_plan_scope.py`, deployment CLI 및 workflow 계약 테스트 | 요청에 결속된 `plan-rca-*` 또는 `apply-rca-*` 모드는 split Core 서비스가 platform 출력을 사용하기 전에 전용 Activity Log RCA reader identity와 Monitoring Reader 역할만 생성할 수 있습니다. |
| exact-revision 보호 운영 적용 근거 | in-progress | [배포와 온보딩](deploy-and-onboard-ko.md#구현-상태) | 코드와 계획 gate는 있지만 이 소유 문서는 모든 제어를 함께 입증하는 현재 운영 적용을 하나로 보존하지 않습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-09-05 | implemented | 배포 단계 통합 후 workflow 내부 GitHub Environment 정책 검사를 복원하여 직접 workflow dispatch가 CLI 승인 경계를 우회하지 못하게 했습니다. | `current change`, 집중 배포 workflow, Environment 정책, 마이그레이션 및 배포 CLI 검사 153개 통과 | 관리자 우회와 자기 검토를 비활성화한 독립 승인 exact apply 증적 하나를 보존합니다. |
| 2026-09-05 | implemented | 앞선 전환을 정정하여 적용 작업의 GitHub Environment 연결을 복원하고 정책 재검사를 통합된 요청 검증 단계에 포함했습니다. 원래의 별도 검사는 작업을 Environment에 연결하지 않았고 현재 단계 예산도 초과했습니다. | `current change`, 집중 배포 workflow, Environment 정책 및 배포 CLI 검사 86개 통과 | 관리자 우회와 자기 검토를 비활성화한 독립 승인 exact apply 증적 하나를 보존합니다. |
| 2026-09-04 | implemented | 실제 계획에서 split Core 서비스가 누락된 platform 출력을 올바르게 차단하고 일반 platform 계획에 관련 없는 destructive drift가 있음을 확인한 뒤, RCA reader identity만 위한 exact-context bounded bootstrap을 추가했습니다. 기존 요청 필드를 사용하므로 workflow는 GitHub의 25개 입력 한도를 유지합니다. | `current change`, deployment CLI, 요청 검증, 계획 범위 및 workflow 집중 검사 105개 통과, Ruff 및 strict mypy 통과 | 보호된 계획과 exact apply를 실행한 뒤 split Core 서비스 계획에서 결과 출력을 사용합니다. |
| 2026-08-26 | implemented | 해석되지 않는 Functions 배포 액션을 인증된 Azure CLI `config-zip` 경로로 교체했습니다. 개발 operations gateway는 원격 빌드를 유지하고 관리 ID 실행기의 게시 작업을 900초로 제한합니다. | `current change`, 집중 배포 workflow 검사 93개 통과, CI 계약 통과 | 정확히 커밋된 workflow에서 보호된 gateway 게시 증적 하나를 보존합니다. |
| 2026-08-26 | implemented | 예약된 인프라 drift에 읽기 전용 실행기 저장소 상태 검사를 추가하고 임시 실행기 프로파일의 구성된 할당 해제와 수동 할당 해제를 모두 차단했습니다. | `current change`; 실행기 상태 스크립트, drift workflow, 수명 주기 도우미 및 집중 계약 검사 14개. | 실제 실행기의 blue/green 교체를 완료하고 성공한 예약 상태 검사 증적 하나를 보존합니다. |
| 2026-08-21 | in-progress | 인프라 동작을 변경하지 않고 기존 운영 강화 제어를 집중 소유 문서로 옮겼습니다. | `current change`; 문서 크기, 번역, 경로 및 링크 검사입니다. | 모든 필수 제어를 다루는 exact-revision 보호 운영 계획 및 적용 증적 하나를 보존합니다. |
| 2026-08-24 | implemented | 모든 표준 환경에서 제어 가능한 해체 및 동일 이름 재생성 제약을 제거했습니다. Terraform은 삭제된 Key Vault와 Cognitive Services 계정을 purge하고, Log Analytics 작업 영역을 영구 삭제하며, 리소스가 남은 리소스 그룹 삭제를 허용하고, 애플리케이션 및 상태 계정 관리 잠금을 비활성화합니다. | `current change`; `infra/` 아래 프로바이더 기능과 환경 값; `tests/integration/infra/test_key_vault_lifecycle.py` (`2 passed`); 공유, scenario-lab, bootstrap 및 dev-access 루트의 Terraform 형식과 유효성 검사. | 보호된 비운영 destroy 및 동일 이름 재생성 증적을 보존합니다. Azure 소유 서비스 지연은 Terraform 제어 밖에 남습니다. |
| 2026-08-24 | implemented | 비공개 runner에 구독 전체 생성 권한을 부여하는 대신 일회용 scenario lab을 기존의 보호된 holding 리소스 그룹에 연결했습니다. Apply와 destroy는 보호된 실행 동안 해당 그룹에만 Contributor를 부여한 뒤 회수하며, Terraform은 태그가 지정된 하위 리소스만 소유하고 제거합니다. 겹치지 않는 `10.73.0.0/20` VNet과 runner 전용 민감한 암호 구체화는 영속 secret store 없이 lab을 비공개 상태로 완전히 폐기할 수 있게 합니다. | `current change`; scenario-lab Terraform 유효성 검사와 finding 0건의 Trivy 및 Checkov 검사; 집중 scenario 및 workflow 계약. | 정확한 보호 plan, apply, VPN, 승인된 sweep 및 하위 리소스 destroy 증적을 보존합니다. |
| 2026-08-24 | implemented | 비공개 runner에 구독 전체 생성 권한을 부여하는 대신 일회용 scenario lab을 기존의 보호된 holding 리소스 그룹에 연결했습니다. Apply와 destroy는 보호된 실행 동안 해당 그룹에만 Contributor를 부여한 뒤 회수하며, Terraform은 태그가 지정된 하위 리소스만 소유하고 제거합니다. Workflow는 명시적인 runner principal을 요구하며 권한을 부여하기 전에 활성 Azure Resource Manager token의 `oid`와 일치하는지 확인합니다. 겹치지 않는 `10.73.0.0/20` VNet과 runner 전용 민감한 암호 구체화는 영속 secret store 없이 lab을 비공개 상태로 완전히 폐기할 수 있게 합니다. | `current change`; scenario-lab Terraform 유효성 검사와 finding 0건의 Trivy 및 Checkov 검사; 집중 scenario 및 workflow 계약. | 정확한 보호 plan, apply, VPN, 승인된 sweep 및 하위 리소스 destroy 증적을 보존합니다. |
| 2026-08-24 | implemented | 앞선 이력의 인플레이스 확장을 교정하기 위해 원래 scenario-lab 전환을 복원하고 runner 신원 결합을 별도로 기록했습니다. Workflow는 모호한 Azure CLI 계정 메타데이터를 명시적인 scenario runner principal로 교체하고, 임시 Contributor 권한을 부여하기 전에 활성 Azure Resource Manager token의 `oid`와 일치하도록 요구합니다. | `current change`; `.github/workflows/sre-demo-lab.yml`; `tests/integration/infra/test_scenario_lab.py` (`6 passed`); CI 계약과 일치 및 불일치 합성 token 검사. | 정확한 보호 plan, apply, VPN, 승인된 sweep 및 하위 리소스 destroy 증적을 보존합니다. |
| 2026-08-25 | implemented | 오래된 리포지토리 전체 Checkov baseline을 리소스 로컬 예외로 교체하고 Storage 액세스 진단, PostgreSQL 감사 로깅, 로컬 사용자 비활성화, managed identity 및 범위가 제한된 NSG를 추가했으며 재사용 모듈마다 Terraform 호환성을 선언했습니다. | `current change`; 모든 루트의 Terraform 유효성 검사, Checkov `88 passed / 0 failed`, Trivy Medium 이상 0건, TFLint 0건. | 아래 열린 항목이 요구하는 exact protected 운영 계획 및 적용 근거를 보존합니다. |

### 남은 작업

- [ ] 잠금이 해제된 해체 프로파일, 비공개 네트워킹, PostgreSQL 내구성, 신뢰할 수 있는 이미지
  다이제스트, 알림, 모니터링 및 비용 예산을 함께 입증하고 차단된 부정 계획 하나를 포함하는
  exact-revision 보호 운영 계획 및 적용 증적을 보존합니다.
- [ ] Key Vault, Cognitive Services, Log Analytics 및 리소스 그룹에 대해 보호된 비운영 destroy와
  동일 이름 재생성 증적을 보존합니다.
- [ ] 필수 CI가 green이면 관련 없는 destroy가 0인 UAMI 역할 이행 계획과 검토된 VM 크기,
  로컬 임시 배치, 관리형 OS 디스크 부재 및 정확한 배포 principal을 보고하는 예약 실행기 상태
  증적 하나를 보존합니다.
- [ ] 관련 없는 delete 또는 replacement를 허용하지 않고 범위가 제한된 RCA reader identity 계획,
  exact apply, platform 출력 및 split Core 소비 증적을 보존합니다.

## 범위가 제한된 split-service 선행 조건 bootstrap

Split Core 서비스는 platform Terraform 출력에서만 RCA reader identity를 읽습니다. Azure 리소스
이름을 추론하거나 표시 이름으로 조회하지 않습니다. 출력이 아직 없으면 서비스 계획은 입력을
구체화하기 전에 중단합니다.

일반 application 선택을 모두 비활성화하고 deployment CLI의 `--deploy-rca-reader-identity` 선택을
사용합니다. CLI는 이를 `plan-rca-*` 또는 `apply-rca-*` 요청으로 결속합니다. Workflow는
`reconcile_rca_bootstrap_state.sh`로 Azure 리소스를 변경하지 않고 모든 legacy count 형태의
measurement Job state 주소 두 개를 조정합니다. 그런 다음
`module.rca_reader_identity`와 `azurerm_role_assignment.rca_monitoring_reader`만 대상으로 하며,
계획 범위 검증기는 다른 변경 주소를 모두 차단합니다. Workflow는 state digest를 기록하고 주소가
모호하거나 현재 주소와 함께 있으면 실패하며 두 plan guard를 계속 적용합니다.

## 배포자 신원

- 대상 리소스 그룹에 subscription-scoped **Owner** 또는 **Contributor + User Access
  Administrator**를 사용하여 실행기 Managed Identity와 그 범위 역할 배정을 생성합니다.
- 실행기의 **작업 허용 목록**에 맞는 subscription-scoped 역할만 부여합니다. [보안 및
  신원](../architecture/security-and-identity-ko.md)을 참조하세요.
- 배포자 권한을 패키징하는 목적별 custom 역할은 열린 설계 선택으로 남습니다.

## 강화 제어

모든 제어는 개발 자세를 기본값으로 사용하므로 실제 환경은 바뀌지 않습니다. 환경별 tfvars로
강화합니다. [`staging.tfvars.example`](../../../infra/envs/staging.tfvars.example)과
[`prod.tfvars.example`](../../../infra/envs/prod.tfvars.example)을 참조하세요.

정확한 서비스 적용은 정상인 활성 Container Apps revision에서만 시작하고 복구를 위해 비활성
revision 1개를 보존합니다. 계획은 이전 보존값을 `0`에서 `1`로 강화할 수 있지만 별도로 검토된 설계
변경 없이는 해당 rollback 경계를 줄이거나 넓힐 수 없습니다.

| 관심사 | Knob | Prod 값 |
|--------|------|---------|
| 관리 잠금 | `enable_resource_locks`, bootstrap `enable_state_lock` | `false` |
| Key Vault | `kv_purge_protection_enabled`, `kv_soft_delete_retention_days` | `false`, `7` |
| Postgres 네트워크 | `enable_private_postgres` | `true` |
| Postgres 내구성 | `postgres_backup_retention_days`, `postgres_geo_redundant_backup` | `35`, `true` |
| Postgres 가용성 | `postgres_high_availability_mode` | `ZoneRedundant` |
| HIL 전달 | `enable_chatops_hil`, `chatops_webhook_url`, `chatops_webhook_secret` | 활성화 + CI secrets |
| 이메일 알림 | `enable_email_notifications`, `notification_email_recipients`, `email_data_location` | 활성화 + 수신자 그룹 |
| 레지스트리 | `acr_sku` | `Premium` |
| 모니터링 | `enable_monitoring`, `alert_email`, `alert_webhook_url` | on + 대상 |
| 비용 | `monthly_budget_amount`, `budget_alert_emails` | 설정 |
| 실행기 저장소 | bootstrap `runner_vm_size`, 임시 `ResourceDisk`, `runner_auto_shutdown_time` | 검토된 지속형 크기, 로컬 OS, 빈 종료 시간 |

리소스 그룹을 소유하는 모든 Terraform 루트는 프로바이더의 잔여 리소스 검사 기능을
비활성화합니다. Log Analytics를 소유하는 루트는 작업 영역을 영구 삭제하고 공유 루트는 destroy
시 Cognitive Services 계정과 Key Vault를 purge합니다. 표준 운영, staging, bootstrap 및 개발 프로파일은
`CanNotDelete` 관리 잠금을 사용하지 않습니다. 이러한 설정은 Terraform destroy가 성공하면
되돌릴 수 없게 만들며 서비스 측 복구보다 즉시 재생성을 우선합니다.

Azure가 소유하는 제약은 계속 적용됩니다. Purge protection이 이미 활성화된 Key Vault는 기존
위치에서 변경할 수 없고 보존 기간이 끝날 때까지 보호됩니다. 다른 구독에서 Event Hubs 이름
공간 이름을 재사용하려면 4시간 대기가 필요할 수 있습니다. PostgreSQL은 삭제된 서버 백업을
5일 동안 보존하지만 이 백업이 새 서버 이름을 예약하지는 않습니다. 이 프로파일 이전에 생성된
soft-delete 상태의 리소스는 이름이 해제되기 전에 명시적인 서비스 purge 또는 영구 삭제 작업이
필요할 수 있습니다.

## 신뢰할 수 있는 이미지 출처

공개 레지스트리 egress가 없는 테넌트는
`--build-arg BASE_IMAGE_REGISTRY=<internal-mirror>`로 런타임 이미지를 빌드합니다. 움직이는 것은
레지스트리 호스트뿐이고 base 이미지 다이제스트는 `Dockerfile`에 pin된 채로 남습니다. 따라서
미러는 바이트의 출처를 바꿀 수 있어도 어떤 바이트가 수락되는지는 바꿀 수 없습니다. Base
이미지가 둘 중 하나라도 잃으면 `scripts/quality/ci/check-ci-contracts.py`가 빌드를 실패시킵니다.

## 비공개 데이터 서비스

`enable_private_postgres`는 PostgreSQL Flexible Server 전용 delegated 서브넷을 추가하고 앱 및
ops VNet에 비공개 DNS 영역을 연결하며 공개 접근과 `AllowAllAzureServices` firewall 규칙을
비활성화합니다. 기존 공개 서버에서 활성화하면 서버가 교체될 수 있으므로 승격 전에 계획을
검토하고 백업 및 복원을 예행 연습하는 것이 좋습니다. `infra/production-gates.tf`의 assertion은
서명된 이미지 다이제스트, 비공개 networking, 내구성, 경보 대상 및 비용 예산 최소값이 제공될
때까지 운영 계획을 차단합니다.

`enable_private_networking = true`이고 delegated-subnet PostgreSQL이 꺼져 있으면 Terraform은
`postgresqlServer` 비공개 엔드포인트를 추가하고 `privatelink.postgres.database.azure.com`을 앱
및 ops VNet에 연결합니다. 두 Event Hubs 샤드는 `privatelink.servicebus.windows.net`을 공유하며
각 이름 공간은 자체 비공개 엔드포인트를 갖고 공개 네트워크 접근은 비활성화됩니다. 따라서 시작
탐색은 개발 데이터베이스를 교체하지 않고 Container Apps 서브넷 또는 peered 실행기에서 실행할
수 있습니다.

## 기존 이메일 채택

승인된 out-of-band ACS Email bootstrap은 첫 개발 수렴 계획에서
`import_existing_email_notifications=true`를 설정할 수 있습니다. 가져오기 블록은
Communication Service, Email Service, Azure-managed domain, association, notification identity,
결정론적 역할 배정을 상태로 가져옵니다. 계획을 적용한 뒤 플래그를 끄는 것이 좋으며 새 환경은
Terraform이 stack을 직접 생성하도록 합니다.

## 지속적인 인프라 검사

CI는 자격 증명 없는 gate 두 개를 추가합니다. [`infra-lint.yml`](../../../.github/workflows/infra-lint.yml)은
모든 인프라 PR에서 format, validation, Trivy 및 Checkov를 실행합니다. Scanner는 리포지토리 전체
finding baseline을 사용하지 않습니다. 의도적 예외는 정확한 리소스 옆에서 운영 gate, 구현된 제어,
provider 제한 또는 관리형 서비스 제약을 설명합니다.
[`infra-drift.yml`](../../../.github/workflows/infra-drift.yml)은 실행기에서 이전 방식, 독립 서비스
다섯 개 및 bootstrap 상태 루트에 대해 scheduled `plan -detailed-exitcode`를 실행합니다. 루트가
없거나 읽을 수 없거나 변경되면 실패 시 차단하므로 green은 일곱 루트를 모두 다룹니다.
Bootstrap 계획 전에 실행기 VM을 독립적으로 읽고 검토된 크기, `Local` `ResourceDisk` 배치 및
관리형 OS 디스크 부재를 요구합니다. 불일치하면 blue/green 교체 작업을 보고하고 Azure 상태를
변경하지 않은 채 실패합니다. 임시 프로파일은 할당된 상태로 유지됩니다. 구성된 자동 종료와
수명 주기 도우미는 OS와 GitHub 등록을 초기화하는 할당 해제를 모두 거부합니다.
모니터링을 활성화하면 PostgreSQL, Key Vault, Event Hubs 및 Container Apps용 action group과
metric alert, Log Analytics diagnostic setting을 프로비저닝합니다. 경보는 사람 신호일 뿐 자율
작업이 아닙니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| Day-zero 전제조건 및 보호 러너 | [배포와 온보딩](deploy-and-onboard-ko.md#전제조건prerequisites) |
| 정책 및 연결 preflight | [배포 Preflight](deployment-preflight-ko.md) |
| 비공개 네트워크 토폴로지 | [네트워크 연결 매트릭스](network-connectivity-matrix-ko.md) |
