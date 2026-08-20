---
title: 운영 배포 강화
translation_of: production-deployment-hardening.md
translation_source_sha: 250468bd4f71ac3c8822240d1d06adf15a404218
translation_revised: 2026-08-21
---
# 운영 배포 강화

이 문서는 런타임 계약을 바꾸지 않고 FDAI 개발 자세를 강화하는 운영 전용 배포 제어를
정의합니다. 리소스 잠금, 내구성, 비공개 네트워킹, 신뢰할 수 있는 이미지, 알림 대상,
모니터링 및 비용 상한을 다룹니다.

> **범위:** 이 값은 범용 환경 매개변수입니다. 배포는 테넌트 데이터를 커밋하지 않고 보호된
> 구성을 통해 자체 대상과 값을 제공합니다.

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 운영 계획 gate 및 환경 knob | implemented | `infra/production-gates.tf`, `infra/envs/{staging,prod}.tfvars.example`, Terraform 구성 테스트 | 서명된 이미지, 비공개 네트워크, 내구성, 모니터링 또는 비용 입력이 없으면 운영 계획을 차단합니다. |
| 자격 증명 없는 인프라 및 drift gate | implemented | `.github/workflows/infra-lint.yml`, `.github/workflows/infra-drift.yml`, CI 계약 테스트 | 선언된 모든 상태 루트를 다루고 루트가 없거나 읽을 수 없거나 변경되면 실패 시 차단합니다. |
| exact-revision 보호 운영 적용 근거 | in-progress | [배포와 온보딩](deploy-and-onboard-ko.md#구현-상태) | 코드와 계획 gate는 있지만 이 소유 문서는 모든 제어를 함께 입증하는 현재 운영 적용을 하나로 보존하지 않습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-08-21 | in-progress | 인프라 동작을 변경하지 않고 기존 운영 강화 제어를 집중 소유 문서로 옮겼습니다. | `current change`; 문서 크기, 번역, 경로 및 링크 검사입니다. | 모든 필수 제어를 다루는 exact-revision 보호 운영 계획 및 적용 증적 하나를 보존합니다. |

### 남은 작업

- [ ] 리소스 잠금, 비공개 네트워킹, PostgreSQL 내구성, 신뢰할 수 있는 이미지 다이제스트,
  알림, 모니터링 및 비용 예산을 함께 입증하고 차단된 부정 계획 하나를 포함하는 exact-revision
  보호 운영 계획 및 적용 증적을 보존합니다.

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

| 관심사 | Knob | Prod 값 |
|--------|------|---------|
| 삭제 보호 | `enable_resource_locks`, bootstrap `enable_state_lock` | `true` |
| Key Vault | `kv_purge_protection_enabled`, `kv_soft_delete_retention_days` | `true`, `90` |
| Postgres 네트워크 | `enable_private_postgres` | `true` |
| Postgres 내구성 | `postgres_backup_retention_days`, `postgres_geo_redundant_backup` | `35`, `true` |
| Postgres 가용성 | `postgres_high_availability_mode` | `ZoneRedundant` |
| HIL 전달 | `enable_chatops_hil`, `chatops_webhook_url`, `chatops_webhook_secret` | 활성화 + CI secrets |
| 이메일 알림 | `enable_email_notifications`, `notification_email_recipients`, `email_data_location` | 활성화 + 수신자 그룹 |
| 레지스트리 | `acr_sku` | `Premium` |
| 모니터링 | `enable_monitoring`, `alert_email`, `alert_webhook_url` | on + 대상 |
| 비용 | `monthly_budget_amount`, `budget_alert_emails`, bootstrap `runner_auto_shutdown_time` | 설정 |

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
모든 인프라 PR에서 format, validation, tfsec 및 Checkov를 실행합니다.
[`infra-drift.yml`](../../../.github/workflows/infra-drift.yml)은 실행기에서 이전 방식, 독립 서비스
다섯 개 및 bootstrap 상태 루트에 대해 scheduled `plan -detailed-exitcode`를 실행합니다. 루트가
없거나 읽을 수 없거나 변경되면 실패 시 차단하므로 green은 일곱 루트를 모두 다룹니다.
모니터링을 활성화하면 PostgreSQL, Key Vault, Event Hubs 및 Container Apps용 action group과
metric alert, Log Analytics diagnostic setting을 프로비저닝합니다. 경보는 사람 신호일 뿐 자율
작업이 아닙니다.

## 관련 문서

| 알아볼 내용 | 읽을 문서 |
|-------------|-----------|
| Day-zero 전제조건 및 보호 러너 | [배포와 온보딩](deploy-and-onboard-ko.md#전제조건prerequisites) |
| 정책 및 연결 preflight | [배포 Preflight](deployment-preflight-ko.md) |
| 비공개 네트워크 토폴로지 | [네트워크 연결 매트릭스](network-connectivity-matrix-ko.md) |
