---
title: 운영 배포 강화
translation_of: production-deployment-hardening.md
translation_source_sha: 02189732a925d52cfe7dd4a05eb14f04bb36fa74
translation_revised: 2026-10-08
---
# 운영 배포 강화

> **배포 방식:** [헌법](../architecture/fdai-constitution.md#article-1-purpose-and-scope)은 단일 명령 소스 배포, 서명된 오프라인 패키지, [Hub 관리형 수명 주기](hub-managed-lifecycle-ko.md)라는 세 가지 설치 방식을 정의합니다. Hub 관리형 수명 주기는 설계만 되어 있고 아직 구현되지 않았습니다. 이 문서의 설치 관문 중 헌법에 없는 것은 대체되었으며 더 이상 적용되지 않습니다.

이 문서는 런타임 계약을 바꾸지 않고 FDAI 개발 자세를 강화하는 운영 전용 배포 제어를
정의합니다. 해체 동작, 내구성, 비공개 네트워킹, 신뢰할 수 있는 이미지, 알림 대상,
모니터링 및 비용 상한을 다룹니다.

> **범위:** 이 값은 범용 환경 매개변수입니다. 배포는 테넌트 데이터를 커밋하지 않고 보호된
> 구성을 통해 자체 대상과 값을 제공합니다.
>
> **실행 전송 계층:** 운영 대상 환경 계획과 적용은 `fdaictl provision azure`와 수동 Managed
> Host를 사용합니다. GitHub Actions는 소스를 검증하고 release를 게시할 수 있지만 운영 배포
> 실행기로 사용하지 않습니다.
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
- Bootstrap runner는 추가로 구독 `Reader`와 서비스 주체의 `Reader`, `Monitoring Reader`,
  `Cost Management Reader` 배정만 허용하는 조건부 `Role Based Access Control Administrator`를
  사용합니다. 별도의 `Cognitive Services Contributor` 배정은 model 해석기를 충족하며 역할을
  위임할 수 없습니다.
- 애플리케이션 root는 생성하는 정확한 registry에서만 안정적 배포 실행기에 `AcrPush`를
  부여합니다. 관리 호스트는 이 역할로 서명되고 다이제스트에 연결된 이미지를 가져오며
  애플리케이션 활성화 전에 각 registry 다이제스트를 확인합니다.
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

공개 레지스트리 송신 경로가 없는 테넌트는 사전 빌드 release 이미지를 승인된 내부 레지스트리로
미러링합니다. release 매니페스트는 전체 이미지 digest, 출처, SBOM 및 소스 버전을 고정합니다.
미러는 바이트의 위치를 바꿀 수 있지만 수락할 바이트를 바꿀 수 없습니다. 테넌트 프로비저닝은
Docker, Buildx, ACR Tasks, 원격 builder 또는 VM 이미지 캡처를 실행하지 않습니다. 계획 전에
미러 digest를 검증하고 rollout 뒤 실행 중인 Pod digest를 다시 확인합니다.

서명된 배포 번들은 추출 후에도 일반 소스 파일을 실행 불가능 상태로 유지합니다. 초기화,
정책, 마이그레이션 및 공개 경로 호출자는 인증된 소스를 고정된 신뢰할 수 있는 인터프리터로만
시작합니다. 실행 비트를 광범위하게 복원하거나 신뢰할 수 없는 주변 경로에서 인터프리터를
선택하지 않습니다.

기존 Genesis 이미지 builder와 잔여 복구 경로는 제거 대상입니다. 연결된 배포는 정확한
Marketplace 호스트와 checksum 고정 bootstrap을 사용하고, 아티팩트 오프라인 배포는 별도로
게시한 사전 빌드 호스트 이미지를 사용할 수 있습니다. 두 경로 모두 테넌트 배포 실행에서 호스트
이미지를 만들거나 캡처하지 않습니다.

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

필수 [`CI` workflow](../../../.github/workflows/ci.yml)는 platform, bootstrap 및 scenario-lab
루트에서 Terraform 형식과 검증을 실행합니다. 경로 범위가 지정된 `terraform-validate`
작업은 인프라 또는 해당 CI 제어가 변경될 때만 이어서 Trivy와 Checkov를 실행합니다. 스캐너는 리포지토리
전체 finding baseline을 사용하지 않습니다. 의도적 예외는 정확한 리소스 옆에서 운영 gate,
구현된 제어, provider 제한 또는 관리형 서비스 제약을 설명합니다.
[`infra-drift.yml`](../../../.github/workflows/infra-drift.yml)은 실행기에서 이전 방식, 독립 서비스
다섯 개 및 bootstrap 상태 루트에 대해 scheduled `plan -detailed-exitcode`를 실행합니다. 루트가
없거나 읽을 수 없거나 변경되면 실패 시 차단하므로 green은 일곱 루트를 모두 다룹니다.
Operator Service 계획은 배포와 마찬가지로 저장된 플랫폼 상태에서 읽은 플랫폼 소유 Cost 가명 키를
연결합니다. 플랫폼에 해당 키가 없으면 설정되지 않은 Terraform 변수 오류 대신 명시적인 이유와 함께
그 루트의 근거가 실패합니다.
구독 거버넌스는 업무 시간 외에 개발 PostgreSQL 서버를 중지하며, 중지된 서버에서는 이전 방식 루트를
새로 고칠 수 없습니다. 이전 방식 계획 전에 실행은 저장된 플랫폼 상태에서 서버 식별자를 읽고 제한된
전원 창을 엽니다. Ready 서버는 그대로 두고, Stopped 서버는 먼저 클레임을 기록한 뒤 시작해 Ready가
될 때까지 기다립니다. 서비스 루트 이후에는 자체 클레임에 이 실행이 시작했다고 기록된 경우에만
서버를 다시 중지합니다. 이 창은 서버 구성을 바꾸지 않으며, Ready에 도달하지 못한 서버는 명시적인
이유와 함께 근거를 실패로 처리합니다. Cost Governance 관측 내보내기도 같은 창을 열고, 두 작업은 하나의
동시성 그룹을 공유하므로 어느 쪽도 다른 쪽이 사용하는 중에 서버를 중지하지 않습니다.
검토된 외부 변경을 수용할 때는 별도의
[`infra-drift-reconcile.yml`](../../../.github/workflows/infra-drift-reconcile.yml) workflow를
사용합니다. 미리 보기 실행은 모든 루트의 refresh-only 계획을 다시 계산하고, 변경된 주소, 속성 경로,
이동, 출력을 값 해시로 묶는 digest 하나를 게시합니다. 값은 로그에 나타나지 않습니다. 보호된
`drift-reconcile` 환경의 적용 실행은 같은 계획을 다시 계산해 검토된 digest를 재현할 때만 저장된
refresh-only 계획을 적용하고, 이후 모든 루트에 drift가 없어야 합니다. Refresh-only 계획은 원격 객체와
출력을 상태에 기록할 뿐 인프라를 바꾸지 않으므로, 원하는 상태를 바꿔야 하는지는 검토자가 따로
결정합니다. 플랫폼에 Cost 가명 키 바인딩이 없으면 실행은 Operator Service 루트만 건너뛰고 요약에
그 이름을 기록합니다. 키 선행 조건이 이 조정이 기록하는 플랫폼 출력을 읽기 때문입니다.
Refresh-only 적용은 계획의 입력으로 루트 출력도 다시 평가합니다. 배포된 출력을 빈 값, null,
알 수 없는 값 또는 삭제된 값으로 바꾸는 계획이 있으면 실행은 그 루트를 제외하고 요약에 해당 출력
이름을 기록합니다. 레거시 플랫폼 루트의 경우 두 drift workflow는 추적된 상태에서 출력에 영향을 주는
기능 입력만 재구성합니다. 모델 기능은 정확히 추적된 배포에서 가져오며 더 새로운 리포지토리 바인딩에
의존하지 않고 저장된 해석 모델 digest를 보존합니다. 리소스가 없거나, 통제된 신원 집합이 일부만
있거나, 모델 배포가 잘못됐으면 계획 전에 실행을 중단합니다. 따라서 저장된 refresh-only 계획은 배포
소유 출력을 보존하면서 검토된 프로바이더 drift를 기록합니다. 원하는 구성을 바꾸려면 계속 별도로
검토된 배포 계획이 필요합니다.
범위가 제한된 Cost 가명 키 선행 조건은 새로운 토글 기반 루트 출력이 없을 때 추적된 레거시
Operator 신원을 직접 읽습니다. 따라서 키를 만들기 위해 광범위한 플랫폼 적용을 실행할 필요가
없습니다.
서비스 입력 구체화는 패키지의 선택적 런타임 가져오기를 실행하지 않고, 정확히 체크아웃한 소스에서
표준 라이브러리만 사용하는 승인 계약을 직접 불러옵니다. 따라서 특정 자체 호스팅 실행기 환경에
우연히 설치된 패키지에 의존하지 않습니다.
Bootstrap 계획 전에 실행기 VM을 독립적으로 읽고 검토된 크기, `Local` `ResourceDisk` 배치 및
관리형 OS 디스크 부재를 요구합니다. 불일치하면 blue/green 교체 작업을 보고하고 Azure 상태를
변경하지 않은 채 실패합니다. 임시 프로파일은 할당된 상태로 유지됩니다. 구성된 자동 종료와
수명 주기 도우미는 OS와 GitHub 등록을 초기화하는 할당 해제를 모두 거부합니다. 전체 범위 drift는
안정 deploy principal의 직접 Azure 역할을 Bootstrap 및 플랫폼 Terraform 상태의 정확한 합집합과
비교합니다. 누락된 역할과 상태 밖 권한을 모두 실패로 처리하고 정제된 매니페스트 증적을 보존합니다.
같은 실행은 일회용 시나리오 상태가 없거나 관리 리소스 인스턴스를 소유하지 않도록 요구하고 별도
종료 증적을 보존합니다.
모니터링을 활성화하면 PostgreSQL, Key Vault, Event Hubs 및 Container Apps용 action group과
metric alert, Log Analytics diagnostic setting을 프로비저닝합니다. 경보는 사람 신호일 뿐 자율
작업이 아닙니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| 구현 상태 및 남은 작업 | [구현 원장](../../roadmap-implementation/deployment/production-deployment-hardening.md) |
| Day-zero 전제조건 및 보호 러너 | [배포와 온보딩](deploy-and-onboard-ko.md#전제조건prerequisites) |
| 정책 및 연결 preflight | [배포 Preflight](deployment-preflight-ko.md) |
| 비공개 네트워크 토폴로지 | [네트워크 연결 매트릭스](network-connectivity-matrix-ko.md) |
