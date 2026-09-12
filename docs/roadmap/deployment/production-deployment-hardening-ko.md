---
title: 운영 배포 강화
translation_of: production-deployment-hardening.md
translation_source_sha: 92063a84a017b05dcc04c93b5d2468f628703b13
translation_revised: 2026-09-12
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
| 자격 증명 없는 인프라 및 drift gate | implemented | `.github/workflows/ci.yml`, `.github/workflows/infra-drift.yml`, 안정적인 배포 신원 도우미, 실행기 상태 스크립트, CI 계약 테스트 | 필수 CI는 자격 증명 없이 모든 Terraform 루트를 검증합니다. 보호된 workflow는 bootstrap이 소유한 UAMI 하나를 선택하고 token `oid`를 검증합니다. 구독 역할 위임은 서비스 주체용 읽기 역할 3개로 제한됩니다. Drift 검사는 모든 상태 root를 다루며 상태 누락, 예상하지 않은 실행기 저장소 또는 로컬이 아닌 배치를 거부합니다. |
| 기준선 없는 Terraform 보안 검사 | implemented | `.github/workflows/ci.yml`, 인라인 Checkov 및 Trivy 예외, 집중 인프라 테스트 | 경로 범위가 지정된 `terraform-validate` 작업은 Terraform 검증 후 고정 버전 Checkov 및 Trivy를 실행하고 하나의 필수 CI 결과로 집계합니다. 의도적 예외는 하나의 리소스에 연결되고 보완 제어 또는 관리형 서비스 제약을 인용합니다. 새로 발견된 문제는 소스에서 수정하거나 범위가 좁고 검토된 예외를 기록할 때까지 CI를 차단합니다. |
| 범위가 제한된 split-service 선행 조건 bootstrap | implemented | `deploy-dev.yml`, `enforce_plan_scope.py`, deployment CLI 및 workflow 계약 테스트 | 요청에 결속된 `plan-rca-*` 또는 `apply-rca-*` 모드는 split Core 서비스가 platform 출력을 사용하기 전에 전용 Activity Log RCA reader identity와 Monitoring Reader 역할만 생성할 수 있습니다. |
| 범위가 제한된 analyzer Job 수렴 | implemented | `deploy-dev.yml`, `observability-analyzer-image.tf`, `update_analyzer_job_image.sh`, 집중 updater, rollback, 범위 및 workflow 테스트 | 보호된 계획은 state 전용 Terraform updater 하나만 대상으로 합니다. Apply는 기존 analyzer container image만 검증된 ACR digest로 변경하고 독립적으로 다시 읽으며, effect 검증이 실패하면 이전 digest로 rollback합니다. 원래 Container Apps Job 리소스가 모든 Job 구성의 선언적 소유자로 유지됩니다. |
| 범위가 제한된 Cost Governance 패키지 배포 | implemented | `deploy-dev.yml`, `enforce_plan_scope.py`, `verify_deploy_convergence.sh`, 집중 범위, 수렴 및 workflow 테스트 | 요청에 결속된 `plan-cost-*` 또는 `apply-cost-*` 모드는 Cost Management Reader 역할 배정과 collector 및 analyzer Job만 대상으로 합니다. 독립 변경 주소 검증기는 destructive plan 검토 또는 아티팩트 보존 전에 그 밖의 모든 리소스를 거부합니다. 적용 후 검증은 같은 대상 집합으로 다시 계획하고 두 Job 이미지를 모두 독립적으로 다시 읽습니다. Cost 전용 적용은 Core 리비전 상태와 canary 검사를 유지하지만 관련 없는 기존 inventory Job은 시작하지 않습니다. |
| Bot 소유 보호 Core service apply | implemented | `request-protected-operation.yml`, `service-deploy.yml`, Core apply 요청 검증기 및 집중 workflow 검사 | 제출기는 개발 또는 스테이징의 Core에 대해 유효 기간이 남은 model-binding plan만 받습니다. Service workflow는 필수 사람 Environment 승인을 유지하고 변경 전에 정책을 다시 검사합니다. |
| Scenario-lab 실행기 도구 준비 | implemented | `sre-demo-lab.yml`, `test_scenario_lab.py`, CI 계약 검사, actionlint, 다운로드한 checksum 검증 | 보호된 workflow는 요청 선행 조건을 확인하기 전에 checksum으로 고정된 Helm과 kubelogin을 실행기 임시 저장소에 설치합니다. 후보 실행기에 Helm이 미리 설치됐다고 가정하지 않으며 설치는 Azure 리소스나 실행기 이미지를 변경하지 않습니다. |
| exact-revision 보호 운영 적용 근거 | in-progress | [배포와 온보딩](deploy-and-onboard-ko.md#구현-상태) | 코드와 계획 gate는 있지만 이 소유 문서는 모든 제어를 함께 입증하는 현재 운영 적용을 하나로 보존하지 않습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-09-12 | implemented | Cost Governance 적용 후 검증을 동일한 범위 제한 패키지 표면으로 한정했습니다. 적용 수렴 단계는 정확한 reader, collector 및 analyzer 대상을 다시 계획하고 두 Job 이미지를 독립적으로 검증합니다. 공용 상태 검증은 Core 리비전과 canary 검사를 유지하되 관련 없는 기존 inventory Job은 시작하지 않습니다. | 실패한 적용 `34691578702` 및 `34692383517`, PR #848, PR #849, `current change`, 집중 수렴 및 workflow 계약 테스트 | 성공한 정확 적용 증적을 보존한 뒤 독립 Core 계획을 적용하고 수명 주기 설치 전에 세 런타임이 한 다이제스트를 사용하는지 검증합니다. |
| 2026-09-12 | implemented | 공유 compute module의 module-level dependency graph가 관련 없는 scheduler, VNet 및 PostgreSQL 변경을 포함한 뒤 두 Cost Governance Job을 해당 module 밖으로 이동했습니다. Root 소유 Job은 이전 state 주소를 보존하고 기존 environment 및 inventory identity 입력만 해석합니다. | `current change`, `infra/cost_governance_jobs.tf`, 집중 Terraform, Job, workflow 및 범위 검사, 실패한 보호 계획 `34687002689`는 아티팩트 보존 또는 apply 전에 중단됨 | Reader 역할 배정과 두 패키지 Job만 포함하는 삭제 없는 Cost Governance 계획을 보존한 뒤 정확한 해당 아티팩트를 적용합니다. |
| 2026-09-12 | implemented | 보호된 계획에서 관련 없는 root module drift가 드러난 뒤 Cost Governance platform 계획을 격리했습니다. Workflow는 이제 reader 역할 배정과 두 패키지 Job만 정확히 대상으로 하며 별도 허용 목록은 그 밖의 모든 변경 주소를 거부합니다. | `current change`, `.github/workflows/deploy-dev.yml`, `scripts/deployment/azure/enforce_plan_scope.py`, 집중 deployment, request 및 dispatch 테스트 146개, 실패한 보호 계획 `34683751394`는 apply 또는 보존된 plan 아티팩트를 생성하지 않음 | 삭제가 없는 보호 Cost Governance 계획과 exact apply를 하나 보존한 뒤 별도의 W7 수명 주기 및 캠페인 근거를 수집합니다. |
| 2026-09-12 | implemented | GitHub와 독립적인 관리 호스트가 애플리케이션 활성화 전에 서명된 런타임 이미지를 가져올 수 있도록 구성된 안정적 배포 실행기에 정확한 ACR 범위의 `AcrPush` 배정을 추가했습니다. 이 배정은 생성된 registry로 범위가 제한되며 구독 전체 이미지 또는 역할 관리 권한을 부여하지 않습니다. | `current change`, `infra/main.tf`, standalone 관리 호스트 이미지 가져오기 및 다이제스트 재확인, root Terraform 검증, 라우팅된 deployment 및 Genesis 테스트 | 관리 ID가 모든 서명 이미지 다이제스트를 가져오고 독립적으로 재확인했음을 입증하는 활성 로그인 배포 증적을 하나 보존합니다. |
| 2026-09-11 | implemented | 보호된 배포 인벤토리에서 상태를 재정의하는 모든 실행 단계로 검증기 성공 직접 결속을 확장했습니다. 여기에는 코호트 정리, 채널 비밀 정리, 프레임워크 컨텍스트 정리, 드리프트 근거 강제, 시스템 지식 요약 및 정리, 서비스 롤백 보고, 시나리오 근거와 권한 정리가 포함됩니다. | `current change`, 보호된 워크플로 인벤토리, 집중 CI 보안 계약 테스트, `check-ci-contracts.py` | 검증기 이후 실패 처리 경로를 실행하고 검증기 실패 시 이후 실행 단계가 실행되지 않음을 입증하는 보호 실행을 보존합니다. |
| 2026-09-11 | implemented | 플랫폼, 서비스 및 시나리오 워크플로에서 상태를 재정의하는 아티팩트 및 권한 정리 작업을 보호된 원본 검증기의 성공 결과에 직접 결속했습니다. 검증기가 실패하거나 건너뛰어지면 작업 권한을 가진 `always()` 작업으로 더 이상 진행할 수 없습니다. | `current change`, `.github/workflows/{deploy-dev,service-deploy,sre-demo-lab}.yml`, 집중 CI 보안 계약 테스트, `check-ci-contracts.py` | 검증기 성공 후 아티팩트 게시와 권한 정리가 실행되고 검증기 실패 시 아무것도 게시하거나 변경하지 않음을 입증하는 보호 실행을 보존합니다. |
| 2026-09-11 | implemented | 기준선 없는 Checkov와 Trivy 검사를 경로 범위가 지정된 `terraform-validate` 작업에 통합하면서 필수 CI 그래프를 20개 작업에서 13개 작업으로 줄였습니다. 스캐너 버전, 검토된 예외, 기준선을 사용하지 않는 정책 및 집계 `required` 결과는 그대로 유지합니다. | `current change`, `.github/workflows/ci.yml`, 집중 CI workflow 계약 테스트, `check-ci-contracts.py`, `actionlint` | 최소화된 필수 그래프의 보호된 main 실행이 한 번 통과한 뒤 새 배치를 런타임 검증 근거로 취급합니다. |
| 2026-09-11 | implemented | Depth 2도 경계 parent를 root commit처럼 처리한 뒤, 수동 shallow-history secret scan을 checksum으로 고정한 gitleaks 8.24.3 exact-commit scan으로 교체했습니다. Push와 pull request는 고정 action과 이력 기반 범위를 유지합니다. 수동 exact-main 검증은 전체 이력을 `HEAD^..HEAD` 평가에만 사용하며 redaction과 같은 실패 코드를 적용합니다. | 수동 CI 실행 `34521958778`, `current change`, 집중 CI workflow 계약 검사, 로컬 exact-diff scan에서 누출 없음 | 정확한 보호 main SHA에서 수동으로 실행한 필수 검사 하나를 green으로 만듭니다. |
| 2026-09-11 | implemented | 수동 CI secret scan의 depth 1이 merge snapshot을 root commit처럼 보이게 하여 현재 트리의 테스트 고정본을 새 추가분으로 보고한 뒤, 보호된 merge parent를 checkout에 포함했습니다. Depth 2는 저장소 전체 이력을 다시 열지 않고 정확한 merge diff를 보존합니다. | 수동 CI 실행 `34519737666`, `current change`, 집중 CI workflow 계약 검사 | 정확한 보호 main SHA에서 수동으로 실행한 필수 검사 하나를 green으로 만듭니다. |
| 2026-09-11 | implemented | 첫 수동 실행에서 이벤트 비교 범위가 없어 과거 커밋 8,205개 전체를 검사한 뒤, 수동 CI secret 검사를 checkout된 보호 리비전으로 제한했습니다. Push와 pull request 실행은 전체 이력 checkout과 기존 커밋 범위 검사를 유지합니다. | 수동 CI 실행 `34517495951`, `current change`, 집중 CI workflow 계약 검사 | 정확한 보호 main SHA에서 수동으로 실행한 필수 검사 하나를 green으로 만듭니다. |
| 2026-09-11 | implemented | 보호된 main push 이벤트를 사용할 수 없을 때도 전체 필수 검사 그래프를 보존하는 수동 CI trigger를 추가했습니다. 이 trigger는 checkout된 보호 main 리비전을 검증하며 호출자가 커밋을 선택하도록 허용하거나 push 및 pull request CI를 약화하지 않습니다. | `current change`, 집중 CI workflow 계약 검사 | 실패한 검사를 우회하는 용도가 아니라 정확한 보호 main 필수 검사를 복구할 때만 수동 trigger를 사용합니다. |
| 2026-09-10 | implemented | 900초 trace 근거 lookback을 60초 detection bucket과 분리해 반복 멱등성 또는 Incident 상관관계 범위를 약화하지 않고 예약된 연속성 검사가 Log Analytics ingestion 하한을 포괄하도록 했습니다. | `current change`, 집중 trace source, runner, CLI 및 Terraform binding 테스트, 세 개의 수집된 scenario를 관측하는 데 900초가 필요했던 실시간 one-shot 근거 | 수정된 analyzer image를 배포하고 execution override 없이 수집된 scenario를 관측하는 예약 실행 하나를 보존합니다. |
| 2026-09-10 | implemented | 관측성 요청의 적용 후 수렴 검사를 같은 state 전용 updater로 제한하고 독립 analyzer Job image readback을 추가했습니다. 다른 apply는 전체 root 수렴과 inventory image 검사를 유지합니다. | `current change`, 집중 수렴 routing 테스트, 보호 apply `34438595436`에서 updater와 image effect는 완료됐지만 이전 전체 root 수렴 불일치를 확인 | 성공한 재개 검증 또는 새로운 정확한 apply receipt를 하나 보존합니다. |
| 2026-09-10 | implemented | Root compute module의 선행 조건 그래프가 관련 없는 구성 drift를 포함했으므로 analyzer 리소스 직접 지정을 state 전용 Terraform updater로 교체했습니다. Updater는 두 image를 digest로 고정된 ACR 참조로 검증하고, 이름이 지정된 container 하나를 갱신하며, 권위 있는 readback을 검증하고, 실패 시 이전 digest를 복원합니다. | `current change`, 성공, no-op, 거부, effect 실패 및 rollback 집중 테스트, state 조정 후에도 직접 대상 지정이 관련 없는 dependency를 포함했고 올바르게 차단되었음을 보호 실행 `34435938544`에서 확인 | 생성 전용 보호 updater 계획, 정확한 적용 및 성공한 analyzer tick receipt를 하나 보존합니다. |
| 2026-09-10 | implemented | 안전하지 않은 legacy 대상 확장을 analyzer 계획 전 state 전용 주소 조정으로 교체했습니다. 이 마이그레이션은 이전 주소와 현재 주소가 공존하면 실패하고 state digest를 기록하며, Terraform 대상과 허용된 변경 집합을 analyzer Job으로 제한합니다. | `current change`, 집중 조정, 정확한 대상 및 부정 범위 테스트, 보호 실행 `34432091729`에서 대상 확장이 관련 없는 dependency를 허용했고 guard가 이를 올바르게 차단함 | 삭제가 없는 보호 analyzer 계획과 정확한 적용을 하나 보존합니다. |
| 2026-09-10 | implemented | 함수 수준 guard가 있었지만 parser가 workflow 호출을 거부한 문제를 수정하기 위해 실행 가능한 계획 범위 CLI 경계에 범위가 제한된 analyzer 모드를 등록했습니다. | `current change`, CLI 허용 및 부정 범위 계약 테스트, 실패한 보호 실행 `34430430009` | 삭제가 없는 보호 analyzer 계획과 정확한 적용을 하나 보존합니다. |
| 2026-09-10 | implemented | Analyzer 전용 계획 중 기록된 state 이동을 마무리하도록 Terraform이 요구하는 두 legacy Container Apps Job 주소를 허용된 변경 집합에는 추가하지 않고 대상 closure에 포함했습니다. | `current change`, workflow 대상 및 부정 범위 계약 테스트, 실패한 보호 계획 `34428877985`에서 필요한 closure 확인 | 삭제가 없는 보호 analyzer 계획과 정확한 적용을 하나 보존합니다. |
| 2026-09-10 | implemented | 증명된 런타임 이미지를 결속하면서 관련 없는 플랫폼 리소스를 계획에 노출하지 않는 analyzer 전용 보호 계획 경로를 추가했습니다. | `current change`, 범위가 제한된 계획 범위 및 workflow 계약 테스트 | 삭제가 없는 보호 계획, 정확한 적용 및 성공한 실시간 analyzer receipt를 하나 보존합니다. |
| 2026-09-09 | implemented | 일반 역할 관리 권한을 부여하지 않고 플랫폼 인벤토리 및 RCA 서비스 주체에 필요한 구독 읽기와 조건부 역할 위임을 추가했습니다. | `current change`; bootstrap Terraform 검증 및 집중 신원 계약 테스트. | 승인된 기반 계층 적용에서 유효 역할과 privileged 역할 거부 관측을 보존합니다. |
| 2026-09-08 | implemented | 후보 self-hosted 실행기에 Helm이 없어 SRE demo plan 선행 검사가 실패한 문제를 수정했습니다. Workflow는 공식 배포 위치에서 Helm v3.18.6을 내려받고 고정된 SHA-256을 확인한 뒤 실행기 임시 저장소에만 설치하며 요청 선행 조건 전에 바이너리를 검증합니다. | `current change`, scenario-lab 검사 7개, CI/workflow 계약 검사 54개, actionlint 통과, 공개 고정 archive checksum 일치, 전체 Operator surface CI 명령에서 Console 테스트 2,827개와 타입 검사 및 빌드 통과 | 공유 branch를 조정하고 작업 소유 변경을 커밋한 뒤에만 push합니다. 이후 apply를 제출하지 않고 새 plan-only 실행을 관찰합니다. |
| 2026-09-05 | implemented | Core 전용 bot 소유 service apply 요청을 추가했습니다. 요청은 제출 전에 정확한 실행 및 시도 provenance, 유효 기간이 남은 plan 아티팩트 하나, 커밋 및 context digest, digest로 고정된 Core image, model-binding 모드를 검사합니다. Service apply는 선택한 Environment에 결속하고 변경 전에 승인 정책을 다시 검사합니다. | `current change`, 보호 요청 및 service workflow, `verify_core_apply_request.py`, 집중 검증기 및 workflow 검사 | 병합 revision의 필수 CI와 supply-chain 검사를 통과한 뒤 bot이 요청하고 별도 사람이 승인한 exact apply 증적 하나를 보존합니다. |
| 2026-09-05 | implemented | 보호된 `main`의 Environment validator blob을 runner 임시 저장소에 복사해 exact revision checkout 이후에도 보존하고, apply 측 정책 검사를 요청 검증과 통합해 배포 workflow의 56-step 검토 예산을 유지했습니다. | `current change`, deploy workflow diet, 보호된 workflow 및 CI 계약 검사 | 독립 승인 exact apply 증적을 하나 보존합니다. |
| 2026-09-05 | implemented | 독립된 인프라 PR workflow를 하나의 필수 CI 그래프에 통합했습니다. Terraform 보안 검사는 경로 범위를 유지하며 공유 유효성 검사 작업은 이제 scenario-lab 루트도 다룹니다. | `current change`, `.github/workflows/ci.yml`, `resolve_test_scope.py`, 집중 CI 범위, 보안 검사 및 scenario-lab 계약 테스트 | 아래에 나열된 정확한 보호 운영 및 drift 근거를 보존합니다. |
| 2026-09-05 | implemented | Service 적용 후 스키마를 변경하는 카탈로그 수명 주기 회귀를 직렬화하고 forward Core 마이그레이션으로 root 소유 T2 lookup index를 복원했습니다. 조정되지 않은 만료가 진행 중인 receipt 또는 보존 근거를 무효화하므로 만료되지 않는 서명 secret 두 개에는 resource-local Checkov 예외를 적용합니다. | `current change`, 집중 마이그레이션 계약, 일회용 PostgreSQL 수명 주기 검사 및 finding 0건의 Checkov | 배포 전에 exact green required CI 및 supply-chain 증적을 보존합니다. |
| 2026-09-05 | implemented | 1인 유지관리자가 자체 검토 없이 bot이 요청한 배포를 검토할 수 있도록 exact RCA reader apply와 검증 재개를 위한 bot 소유 요청 경로를 추가했습니다. `fdaictl`은 exclusive RCA 작업을 이 경계로 라우팅합니다. Environment가 관리자 우회를 비활성화하고 자체 검토를 차단하며 필수 reviewer를 선언하지 않으면 요청은 제출 전에 실패합니다. apply job은 선택한 Environment에 binding하고 변경 전에 같은 정책을 다시 검사합니다. 두 검사는 보호된 `main` checkout의 validator를 실행하므로 이전 plan이 정책을 downgrade할 수 없습니다. | `current change`, 집중 deployment CLI, Environment validator 및 보호된 workflow 계약 검사 | 독립 승인 exact apply 및 효과 증적을 보존합니다. |
| 2026-09-05 | implemented | 이미 검증된 model, notification-receipt 및 RCA reader 환경 전환을 Core plan 하나에서 조합했습니다. 검증기는 여전히 정확한 model digest, 정본 notification topic, 전용 RCA identity를 요구하고 추가 runtime drift를 허용하지 않습니다. | `current change`, 집중 service plan guard 검사, Ruff 및 strict mypy | 세 전환을 모두 포함하는 보호된 Core plan을 생성하고 적용한 뒤 배포된 환경을 독립적으로 검증합니다. |
| 2026-09-05 | implemented | RCA binding transition의 rollback recovery 형태를 추가했습니다. Terraform state에 전용 `-rca-reader` identity가 정확히 하나 이미 있지만 복원된 active revision에 client-ID environment value가 없으면 명시적 model-binding plan이 해당 값 하나만 완성할 수 있습니다. Model guard는 관련 없는 모든 environment 변경을 계속 거부합니다. | `current change`, 집중 service plan recovery 및 negative identity 검사 | 보호된 Core plan을 적용하고 배포된 identity와 environment value를 독립적으로 검증합니다. |
| 2026-09-05 | implemented | 현재 revision이 healthy 상태가 아니고 정확한 last-ready revision이 provisioned 및 healthy 상태를 유지할 때만 보호된 service apply가 Azure의 별도 `latestReadyRevisionName`을 rollback baseline으로 사용할 수 있게 했습니다. workflow는 해당 revision을 활성화하지 않고 snapshot으로 보존하며, 별도의 apply 이후 freshness sentinel은 실제 apply 이전 current revision을 계속 사용합니다. Service Terraform은 inactive revision 2개를 보존하고 plan guard는 범위가 제한된 `1 -> 2` retention 증가만 허용하므로 새 revision을 만드는 동안 stuck current revision과 last-ready rollback source가 유지됩니다. | `current change`, 집중 recovery, workflow, rollback 거부, Terraform, Ruff 및 strict mypy 검사 | 보호된 Core plan을 적용하고 health 및 rollback 근거를 모두 보존합니다. |
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
- [ ] Reader 역할 배정과 두 패키지 Job만 변경하는 삭제 없는 Cost Governance 계획과 exact apply를
  보존한 뒤 배포된 image digest를 독립적으로 검증합니다.

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

공개 레지스트리 egress가 없는 테넌트는
`--build-arg BASE_IMAGE_REGISTRY=<internal-mirror>`로 런타임 이미지를 빌드합니다. 움직이는 것은
레지스트리 호스트뿐이고 base 이미지 다이제스트는 `Dockerfile`에 pin된 채로 남습니다. 따라서
미러는 바이트의 출처를 바꿀 수 있어도 어떤 바이트가 수락되는지는 바꿀 수 없습니다. Base
이미지가 둘 중 하나라도 잃으면 `scripts/quality/ci/check-ci-contracts.py`가 빌드를 실패시킵니다.
같은 계약은 허용된 base 이미지에 남은 취약 버전보다 최신인 보안 갱신 런타임 라이브러리도 고정합니다.

서명된 배포 번들은 추출 후에도 일반 소스 파일을 실행 불가능 상태로 유지합니다. 초기화,
정책, 마이그레이션 및 공개 경로 호출자는 인증된 소스를 고정된 신뢰할 수 있는 인터프리터로만
시작합니다. 실행 비트를 광범위하게 복원하거나 신뢰할 수 없는 주변 경로에서 인터프리터를
선택하지 않습니다.

Genesis 이미지 빌더는 두 Firewall 공개 IP의 테넌트 정책 추가 `ip_tags`만 외부 소유로
처리합니다. 두 IP 모두에서 태그가 없거나 `FirstPartyUsage=/Unprivileged`인 동일 상태만
허용하고, 독립 ARM 재확인으로 그 밖의 모든 값을 거부하며, 이미지 증적을 게시하기 전에
새로 실행한 변경 없음 Terraform 계획을 요구합니다.

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
| Day-zero 전제조건 및 보호 러너 | [배포와 온보딩](deploy-and-onboard-ko.md#전제조건prerequisites) |
| 정책 및 연결 preflight | [배포 Preflight](deployment-preflight-ko.md) |
| 비공개 네트워크 토폴로지 | [네트워크 연결 매트릭스](network-connectivity-matrix-ko.md) |
