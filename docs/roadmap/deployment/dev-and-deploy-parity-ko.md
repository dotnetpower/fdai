---
title: Runtime Parity - Authoritative Local Development 및 Test Fixture
translation_of: dev-and-deploy-parity.md
translation_source_sha: 43f8ec55eba2a886c8628fd03930d89fbbdd10df
translation_revised: 2026-08-26
---
# 런타임 동등성 - 권위 있는 로컬 개발 및 테스트 고정본

**목표**: 자동화 테스트는 결정론적이고 secret-free 상태를 유지하며, interactive 로컬 Console은 운영자의 실제 Azure 개발 환경만 표시합니다. Azure 배포에서는 계속 **배포자의 Azure 권한과 리전 카탈로그가 어떤 LLM과 기타 리소스를 프로비저닝할지 결정**합니다. 세 명제가 동시에 참입니다:

- **자동화 테스트 truth**: pytest와 committed mock은 결정론적 가짜를 사용할 수 있습니다. 명시적 test-fixture 빌더를 사용하며 Azure 관측 상태로 표현하지 않습니다.
- **Full-stack 로컬 truth**: `Console Web: Full Stack`은 배포와 같은 App 역할 검사를 적용하는 브라우저 Entra sign-in을 사용합니다. 서버의 Azure CLI 세션은 Azure 개발 데이터 평면 프로바이더 자격 증명만 제공합니다. 인벤토리, 모델 가용성, 에이전트 활동, 프로세스 상태, 승격 근거, 감사 데이터는 권위 있는 프로바이더에서만 표시합니다. 출처가 없으면 사용 불가 또는 명시적 빈으로 표시하며 생성 예제로 대체하지 않습니다.
- **Deploy truth**: `terraform apply` 가 CSP-neutral 컨트랙트의 Azure 측 실현체를 생성. **LLM 부분은 배포자-스코프**: 초기화 해석기가 배포자 아이덴티티를 대상 리전 카탈로그와 대조해 **배포자가 만들 권한이 있는 것만** 프로비저닝하고, resolved `{capability → deployment}` 매핑과 해석기 입력 출처 이력을 산출물에 기록합니다.
모든 프로파일은 **하나의 컨트롤 경로**를 공유하며 composition-root 어댑터와 자격 증명만 다릅니다.
([project-structure.md § Customization via 의존성 주입](../architecture/project-structure-ko.md#customization-via-dependency-injection)). 검토된 docstring은 기존 경계를 기록하며 별도 런타임을 만들거나 상태 소유권을 변경하거나 고정본을 허용하지 않습니다. 실제 Azure 클라이언트 추가는 fork-side 주입이며 `core/`를 편집하지 않습니다.
## 구현 상태
### 구현 범위
| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 자동화 테스트 고정본 격리 | implemented | `tests/`, `console/tests/` 및 리포지토리 테스트 모음이 실행하는 고정본 전용 composition 경로 | 결정론적 고정본은 권위 있는 interactive 프로파일 밖에 유지됩니다. |
| 인증된 라이브 Console 경로 보증 | in-progress | `console/playwright.live.config.ts`, `console/tests/live-e2e/operator_service.py`, `console/tests/live-e2e/console-routes.spec.ts`, `console/tests/live-e2e/ontology-query-assurance*.ts`, focused 경로 검사 및 출처 이력 테스트 통과 | 통제된 아티팩트는 정확한 source revision, 정규 run-configuration digest, workspace patch digest, authentication attestation 및 턴별 request와 projection id를 연결합니다. 전체 경로, 온톨로지 cohort 및 비평 라운드는 열려 있습니다. |
| Live 관찰 소비자 격리 | implemented | `services/operator-service/src/fdai_operator_service/environment.py`, `services/operator-service/src/fdai_operator_service/composition.py`, `console/tests/live-e2e/operator_service.py` 및 focused 회귀 검사, 테스트 41개 통과 | `FDAI_LIVE_STAGE_CONSUMER_GROUP_ID`는 독립적으로 실행되는 각 Operator 프로세스 또는 복제본을 고유한 그룹에 연결합니다. E2E launcher는 상속된 값을 항상 UUID 범위 그룹으로 교체합니다. |
| Agent 새로 고침 최신 상태 초기화 | validated | focused 스트림 테스트 9개 통과, 인증된 `/agents` 새로 고침이 각각 224ms, 232ms, 228ms 안에 `Watching 2 / Idle 13 / Unobserved 0` 도달 | Agent hub는 agent별로 검증된 최신 `agent.state` 이벤트 하나를 새 구독자에게 초기값으로 제공합니다. 일반 Live는 이후 이벤트만 전달하며 어느 hub도 영속 이력 재생을 제공하지 않습니다. |
| 인증된 로컬 Live 이벤트 경로 | validated | 통제된 Browser Entra 근거와 현재 `fdai.change.events` 및 `fdai.pipeline.stages` 연결 | 이 경로는 권위 있는 온톨로지를 보존하고 이벤트와 허용된 네 단계를 모두 렌더링합니다. 브라우저 Notifications API 또는 브라우저 종료 상태의 push 전달은 검증하지 않았습니다. |
| 로컬 컨트롤 루프 변경 이벤트 유입 | validated | `.vscode/tasks.json`, `infra/modules/compute/container-apps/inventory_job.tf`, `tests/integration/infra/test_inventory_repair_wiring.py`, 로컬 실행 1회가 권위 있는 `inventory.resource_changed` 이벤트 5건을 발행했고 인증된 Live 화면이 `Runtime observed`와 `5 routed events`를 보고 | 로컬 inventory reconciliation 태스크가 VNet 통합 배포 job과 똑같이 `FDAI_INVENTORY_RECOVERY_DELTA=1`을 바인딩하므로 Activity Log delta가 두 장소 모두에서 `fdai.change.events`에 도달합니다. 배포 job은 infrastructure subnet이 없으면 여전히 delta를 비활성화합니다. |
| 로컬 및 배포 composition 동등성 | implemented | `.vscode/tasks.json`, `.vscode/launch.json`, `scripts/deployment/local/`, `infra/`, `fdai_operator_service/composition.py`, `postgres_read_investigation_replay.py`, `incident_intervention_runtime.py`, 서비스 통합 테스트 및 focused Operator 검사 | Composition root는 근거 권한을 바꾸지 않고 자격 증명과 어댑터를 선택합니다. 로컬 및 배포 Operator composition은 같은 Reader 범위 `GET /browser-evidence` 경로, 영속 read-investigation completion bridge 및 인증된 Incident intervention 경로를 versioned topic, PostgreSQL store 및 replay-safe outbox로 등록합니다. Incident intervention은 권한 없는 제안을 기록하기 전에 권위 있는 대상과 수명 주기를 다시 확인하며 실행기를 직접 호출하지 않습니다. 전용 로컬 재시작 태스크는 supervision만 바꿉니다. PostgreSQL이 없으면 합성 데이터 대신 사용 불가를 반환합니다. |
| 독립 A3 channel-edge 동등성 | 구현됨 | `channel_edge/`, `prepare-channel-edge-env.sh`, `.vscode/tasks.json`, `infra/services/operator-service`, 플랫폼 edge identity/RBAC, 집중 edge 및 로컬 실행 검사 | 두 venue는 port 8014에서 동일한 Operator distribution ASGI factory, PostgreSQL store, 의미 EventBus bridge, 프로바이더 경로 및 readiness 논리를 실행합니다. Local은 private 0600 provider input과 Redpanda를 사용하고 deployed는 Key Vault reference, Event Hubs Kafka 및 전용 non-executor Managed Identity를 사용합니다. Provider 구성이 없으면 선택적 기능은 synthetic 대신 unavailable 상태를 유지합니다. |
| 재사용 가능한 서비스 Terraform 모듈 호환성 | implemented | `infra/**/versions.tf`, `infra/**/.terraform.lock.hcl`, Terraform 검증 및 TFLint | 모든 재사용 가능한 모듈이 Terraform `>= 1.9`를 선언하고 독립 모듈 검증은 committed provider checksum으로 해석됩니다. 프로바이더 구성과 배포 소유권은 서비스 루트에 유지됩니다. |
| Primary worktree 명시적 전체 스택 시작 | validated | `.vscode/tasks.json`, `run-bounded-command.py`, `prepare-console-full-stack.sh`, `start-console-services.sh`, `run-console-service.sh`, `developer-workflow.py`, 집중 시작 계약 테스트 및 표준 로컬 준비 상태 6/6 결과 | 폴더를 열 때 더 이상 이행, 권위 데이터 새로 고침 또는 애플리케이션 서비스를 실행하지 않습니다. 준비 작업은 migration 소유권을 검증하고 lockfile 기반 Console 의존성을 복구하며 독립적으로 fingerprint된 8개 단계를 재사용합니다. 시작 태스크는 terminal `ready` 또는 `failed`에서만 닫히며 모든 외부 준비 및 readiness 명령에는 전체 및 무진행 기한이 있습니다. |
| 선택적 10분 로컬 복구 감시 | implemented | `.vscode/tasks.json`, `watch-console-services.sh`, `developer-workflow.py`, 집중 workspace 태스크 계약 | 단일 인스턴스 태스크가 600초마다 구성 요소 6개의 준비 상태 계약을 확인합니다. 정상 스택은 건너뛰고 실패한 경우에는 표준 준비 및 supervisor 경로를 사용하여 고정 로컬 포트와 서비스 소유권 규칙을 유지합니다. |
| 로컬 진단 로그 복원력 | implemented | `capture-local-service-log.py`, `fdai.shared.telemetry.logging`, 집중 telemetry 및 launcher 검사 | 경고 보존은 레코드별 압축 없이 추가하고, 로컬 파일 캡처는 터미널 역압력과 격리하며, 과대 레코드는 범위를 제한하고, 반복 의존성 실패는 최초·주기·서로 다른 실패 근거를 보존합니다. |
| 폴더 열기 dev-access 경로 안정화 | implemented | `tools/dev-access/scripts/vscode-startup.sh`, `tests/integration/infra/test_dev_access.py`, 집중 dev-access 테스트 | 태스크는 Azure VPN Client를 최대 한 번 열고 범위가 제한된 7초 유예 시간 동안 mirrored WSL 경로를 8번 확인합니다. Direct 경로가 나타나면 DNS를 적용하고 실제 연결 끊김에는 exit `20`을 유지합니다. 로컬 상태가 없는 workstation과 direct-VNet 머신은 계속 조용히 종료합니다. |
| 리포지토리 범위 roadmap campaign 용량 | implemented | `roadmap_verification_watchdog.py`, `test_roadmap_verification_watchdog.py`, `scripts/README.md`의 무작위 campaign 운영 계약 | FDAI session lease와 최근 Copilot 활동을 모두 이 리포지토리 범위에서만 계산합니다. Linked worktree는 VS Code workspace ID를 도출하기 전에 primary checkout을 해석합니다. 다른 workspace는 FDAI 작업을 보류할 수 없으며, 900초 활동 창과 campaign 세션 2개 상한은 FDAI 동시 편집을 계속 보호합니다. |
| 의미 계획 tier 동등성 | implemented | `composition/semantic_query_model_targets.py`, `composition/wire_semantic_query.py`, 해석된 모델 산출물, 집중 tier 라우팅 및 조립 테스트 | 로컬 및 배포 Core는 같은 기능 산출물을 로드하고 해석된 narrator 또는 `t1.judge` pool을 T1으로 연결하며 T2는 선택 사항으로 유지합니다. T1 제안을 사용할 수 없거나 결정론적 검증을 통과하지 못한 경우에만 해당 단계를 T2로 다시 시도할 수 있습니다. |
| 배포 모델 산출물 바인딩 | implemented | Core service Terraform root, 보호 service workflow, active Core revision 및 image-attestation 검증기, 집중 service 및 model 검사 | 배포 Core는 Core 전용 보호 transition을 통해서만 `LLM_MODE=azure`, 고정 이미지 산출물 경로 및 정확한 attested digest를 받습니다. 모델 정책 CAS는 해당 healthy active runtime 근거를 요구하며 로컬은 같은 조립 계약으로 준비된 산출물을 계속 로드합니다. |
| 권한 인식 관측 캠페인 동등성 | implemented | `config/observation-sources.yaml`, `fdai.delivery.observation_campaign*`, `.vscode/tasks.json`, `infra/modules/compute/container-apps/observation_campaign_job.tf`, 집중 Core, Operator, Console, workspace 및 인프라 검사 | 로컬과 배포 프로필은 같은 출처 카탈로그, 실행 조건 상태, 실행기, 정규화 활동 계약 및 1분 기동을 사용합니다. 검증 전에는 런타임 산출물이 더 필요합니다. |
| 로컬 검증 데이터베이스 격리 | implemented | `infra/local/docker-compose.yml`, `scripts/automation/validation_queue_context.py`, 로컬 준비 스크립트 및 focused 검증과 migration 통합 테스트 | 런타임 상태는 로컬 PostgreSQL port `5432`에 유지하고 파괴적인 migration 검증은 port `5433`의 별도 로컬 PostgreSQL cluster를 사용합니다. |
| 보호 배포 workflow 및 서비스 migration bootstrap | implemented | `.github/workflows/deploy-dev.yml`, `.github/workflows/service-deploy.yml`, `scripts/deployment/azure/`, `service-migrations/`, 집중 테스트 568개, 대상 workflow의 `actionlint 1.7.12` 통과 | Plan 및 apply는 sealed evidence, authority, resume 조건을 유지하며 공유 검사는 검토된 helper를 통해 실행합니다. Fresh 및 existing 데이터베이스는 같은 manifest 순서의 재시도 안전 서비스 bootstrap을 사용합니다. |
| FDAI workspace 및 프로파일 부하 제어 | implemented | `.vscode/settings.json`, `.vscode/fdai.code-profile`, `scripts/automation/configure-vscode-profile.py`, `tests/integration/scripts/test_vscode_workspace_performance.py`, 집중 프로파일 및 workspace 검사 | 리소스 범위 분석 제어는 workspace에 두고, 공유 구성에는 선택한 확장이 소유한 설정만 유지합니다. Copilot은 선택한 모델의 맥락 창 80%에서 에이전트 이력을 압축하고, 이식 가능한 프로파일은 격리할 수 없는 Remote WSL Pylance 머신 설정을 거부하며, 0이 아닌 터미널 종료는 중복 VS Code 알림 없이 계속 확인할 수 있습니다. |
| 격리된 Console E2E 개발 루프 | implemented | `console/playwright.config.ts`, `console/playwright.live.config.ts`, `console/scripts/playwright-port-pool.ts`, focused 테스트 및 `.github/skills/vscode-profile-onboarding/SKILL.md`의 Playwright 지침, Console 타입 검사와 동시 focused desktop E2E 통과 | 각 세션은 frontend/API 포트 쌍 10개 중 하나를 원자적으로 임대하고 worker와 공유합니다. slot별로 산출물을 격리하고 종료된 PID의 잠금을 회수하며 전체 desktop 및 mobile 행렬은 바꾸지 않습니다. |
| 같은 체크아웃의 백엔드 시작 재사용 | implemented | `local-service-input-digest.py`, `run-local-service.sh`, `run-local-service-child.py`, `developer-workflow.py`, `.vscode/tasks.json`, 집중 런처 및 workspace 태스크 테스트 | 재사용하려면 서비스 소스, private 환경, 의존성, 감독 코드 및 실행 명령 fingerprint가 정확히 일치해야 합니다. 오래된 managed 태스크는 자동으로 교체합니다. 시작 후에는 최신 Core heartbeat를 포함한 표준 로컬 구성 요소 6개가 범위가 제한된 준비 상태 검사를 모두 통과해야 합니다. 종료는 범위가 제한된 유예 시간 뒤 강제로 전환합니다. 체크아웃 외부에서 소유한 포트 또는 런타임 잠금은 계속 시작 실패로 처리합니다. |
| FDAI Pylance launch ceiling 런타임 증명 | deferred | FDAI Remote WSL을 clean restart해도 Pylance는 bundled VS Code Node 실행 파일로 시작했고 `--max-old-space-size=2048`이 없었습니다. VS Code Server 1.133은 활성 프로파일 서비스와 별개로 Remote Machine 설정 리소스 하나를 생성합니다. | 격리된 런타임을 마련할 때까지 blocked 상태입니다. Shared Remote Machine 재정의는 제외 대상 workspace에도 영향을 주므로 ceiling을 활성화하려면 별도 VS Code Server data root 또는 WSL 배포판으로 런타임을 격리해야 합니다. |
### 구현 이력
| 날짜 | 상태 | 변경 | 근거 | 잔여 작업 |
|------|------|------|------|-----------|
| 2026-08-26 | implemented | 검토된 AKS topology mapping 변경 뒤 content-addressed provider 관계 검토를 다시 생성했습니다. 후보 개수, `automatic_promotion=false`, `grants_authority=false`는 유지되며 산출물은 런타임 연결이나 권한을 바꾸지 않습니다. | `current change`, provider review `sha256:f6df73948d31bc1cce212918e776f515d6dad1713b61e10a9fa18eeb60a6c976`, 집중 provider-schema 검사 65개 통과 | semantic mapping을 바꾸기 전에 선택한 후보를 독립적으로 검토합니다. |
| 2026-08-26 | validated | 프로세스 시작 시점의 잘못된 준비 완료를 terminal `ready` 또는 `failed`로 교체하고, 중복 시작 요청을 조용히 무시하던 동작을 제거했으며, 전체 및 무진행 process-group 기한을 추가했습니다. Console 의존성은 lockfile에서 자동 복구하고 서비스 migration 소유권 검증은 Docker 및 권위 데이터 새로 고침보다 먼저 실행합니다. | `current change`, `.vscode/tasks.json`, `scripts/automation/run-bounded-command.py`, `scripts/deployment/local/{prepare-console-full-stack,start-console-services,run-console-service}.sh`, 집중 시작 계약 테스트 19개 통과, 셸 구문 및 편집기 진단 통과, 표준 태스크에서 서비스 branch 5개와 table 127개를 검증하고 Console 의존성을 복구한 뒤 첫 번째 bounded 진단 시도에서 준비 상태 6/6 도달 | 범위가 제한되고 실패 시 닫히는 로컬 시작에 남은 구현 작업은 없습니다. |
| 2026-08-26 | implemented | selector가 반복될 때마다 종료 시각을 갱신하여 `SIGTERM`을 무시하는 자식 프로세스가 유예 시간 완료를 막을 수 있던 기한 승격 결함을 수정했습니다. 이제 만료 시각을 한 번만 고정하고 선언된 유예 시간이 지나면 전체 process group에 `SIGKILL`을 보내며 JSON 출력은 바꾸지 않고 텍스트 모드 준비 상태 표식을 즉시 내보냅니다. | `current change`, `scripts/automation/{run-bounded-command,developer-workflow}.py`, `tests/integration/scripts/test_{run_bounded_command,developer_workflow,vscode_workspace_performance}.py`, 집중 시작 진단 모음 34개 통과, Ruff와 문서 게이트 통과, exact 로컬 진단에서 시작 표식을 내보내고 첫 시도에 준비 상태 6/6 도달 | 기한 승격 또는 준비 상태 진행 표시에 남은 구현 작업은 없습니다. |
| 2026-08-26 | implemented | 10회 비평에서 직접 자식이 종료된 뒤 같은 process group의 하위 프로세스가 출력 pipe를 계속 보유하면 기한 적용이 중단되는 결함을 찾았습니다. 이제 전체 group이 상속된 출력을 닫을 때까지 process-group signal과 강제 종료 단계를 계속 적용합니다. | `current change`, `scripts/automation/run-bounded-command.py`, `tests/integration/scripts/test_run_bounded_command.py`, 수정 전 회귀 검사는 3.05초에서 실패했고 수정 후 1.05초에 통과 | 남은 비평 라운드와 집중 게이트 모음을 완료합니다. |
| 2026-08-26 | validated | 비평에서 보고된 Operator 재시작 정지를 재현했습니다. VS Code background matcher는 `event=ready`를 요구했지만 launcher가 준비 상태 확인 없이 실행되어 `starting`, `reused`, `stopped`만 내보낼 수 있었습니다. 이제 Core와 Operator 재시작은 새 `starting` 또는 입력이 정확히 같은 `reused` 세대를 기다린 뒤 서비스 범위의 bounded readiness를 수행하고 원래 실패 상태와 함께 terminal `ready` 또는 `failed` 표식을 정확히 하나 내보냅니다. | `current change`, `.vscode/tasks.json`, `scripts/automation/run-local-service.sh`, `scripts/deployment/local/run-console-service.sh`, `tests/integration/scripts/test_{start_console_services,vscode_workspace_performance}.py`, 실행 marker 경로 3개와 workspace task 계약 통과, 실제 VS Code task는 새 Operator 프로세스가 application startup complete와 `event=ready`를 보고한 뒤에만 `Task completed`로 반환 | 범위가 제한된 Operator 재시작 task 완료에 남은 구현 작업은 없습니다. |
| 2026-08-26 | implemented | 5차 비평에서 하위 프로세스가 새 session을 시작해 원래 process group을 벗어나고 강제 종료 뒤에도 출력 pipe를 유지할 수 있음을 찾았습니다. 이제 실행기는 사용할 수 있는 출력을 한 번 배출하고 직접 자식을 회수한 뒤 상속된 출력을 닫아, 탈출한 보유자를 기다리지 않고 범위가 제한된 실패를 반환합니다. | `current change`, `scripts/automation/run-bounded-command.py`, `tests/integration/scripts/test_run_bounded_command.py`, 수정 전 회귀 검사는 3.04초에서 실패했고 수정 후 2.14초에 통과 | 10회 비평의 최종 집중 게이트 모음을 완료합니다. |
| 2026-08-26 | implemented | 9차 비평에서 입력이 정확히 같은 `reused` wrapper 종료와 새로 `starting`한 장기 실행 서비스를 구분했습니다. 시작된 서비스가 준비 상태 전에 0으로 종료하면 이제 ready를 보고하지 않고 exit 1과 함께 terminal `failed`를 내보냅니다. 외부 signal, 조용한 busy loop, 지속 출력 및 즉시 Operator probe를 대상으로 한 적대적 검사는 프로세스 누수 없이 선언된 범위를 유지했습니다. | `current change`, `scripts/deployment/local/run-console-service.sh`, `tests/integration/scripts/test_start_console_services.py`, Operator 수명주기 경로 4개 통과, 외부 `SIGTERM`은 1.225초에 143 반환, 조용한 busy loop는 1.024초에 124 반환, 지속 출력은 전체 deadline 도달, 즉시 Operator probe는 0.092초에 완료, 통합 집중 모음 76개와 Ruff, shell, 번역 및 구현 ledger gate 통과 | 10회 bounded readiness 비평에서 남은 구현 작업은 없습니다. |
| 2026-08-25 | implemented | 보호 배포 workflow를 검토된 helper로 통합하고 명시적 Terraform remote-state 초기화와 active-model compare-and-swap 근거를 복원했으며 fresh 및 existing 서비스 migration이 manifest 순서의 bootstrap 하나를 사용하도록 했습니다. | `current change`, 보호 workflow, Azure 배포 helper, 서비스 migration branch, Operator PostgreSQL query/index 변경, 집중 테스트 568개 통과, Ruff, mypy, ShellCheck, YAML parsing 및 대상 `actionlint 1.7.12` 통과 | 이 상태를 `validated`로 올리기 전에 보호 Azure plan, apply, migration 및 effect-verification receipt를 보존합니다. |
| 2026-08-25 | implemented | 서비스 소유권이나 프로바이더 선택을 바꾸지 않고 모든 재사용 가능한 서비스 모듈에 Terraform `>= 1.9` 호환성을 선언했습니다. | `current change`, `infra/services/**/modules/**/versions.tf`, Terraform 검증 및 TFLint | 프로바이더 주 버전 변경을 명시적으로 유지하고 지원 범위를 넓히기 전에 각 서비스 루트를 검증합니다. |
| 2026-08-25 | implemented | LLM 측정 행을 추가하는 데 필요한 정확한 identity sequence 권한을 부여하되 sequence 변경 권한은 주지 않는 정방향 Core service migration을 추가했습니다. | `current change`, `core_metering_sequence_20260825`, service migration inventory 55건 통과, Core branch 검증에서 table 126개, transition 12개 및 새 head 확인 | 성공한 exact Core apply, 측정 기록 쓰기 및 post-apply 상태 증적을 보존합니다. |
| 2026-08-25 | implemented | 선택적 `console: keep full stack ready (10m)` 태스크를 추가했습니다. 기존의 범위가 제한된 6개 구성 요소 준비 상태 검사를 600초마다 실행하고, 정상 구성은 건너뛰며 준비 상태 검사에 실패한 경우에만 표준 준비 및 supervisor 경로로 진입합니다. | `current change`, `.vscode/tasks.json`, `scripts/deployment/local/watch-console-services.sh`, `tests/integration/scripts/test_vscode_workspace_performance.py`, 집중 workspace 계약 테스트 4개 통과, 셸 구문 및 VS Code 진단 통과 | 선택적 로컬 복구 감시에 남은 구현 작업은 없습니다. |
| 2026-08-25 | implemented | 배포 Core 모델 조립을 exact image가 증명한 resolved artifact에 결속하고 모델 정책 CAS가 변경 가능한 Terraform 입력 대신 healthy active revision을 관측하도록 했습니다. Apply는 같은 revision, image 및 model digest를 다시 검증합니다. | [이슈 #270](https://github.com/dotnetpower/fdai/issues/270); 보호 service/model workflow, guard, plan bundle, active-runtime 검증기 및 통합 집중 검사. | 검증 전에 live Core transition 및 정방향/역방향 PTU 증적을 보존합니다. |
| 2026-08-24 | implemented | HashiCorp 전용 workspace와 이식 가능한 프로파일에서 Microsoft Terraform 언어 서버 설정을 제거하고, workspace에서 사용하지 않는 Live Server 설정을 제거했습니다. 맥락 사용량 표시기는 설계대로 계속 활성화합니다. | `current change`, `.vscode/settings.json`, `.vscode/fdai.code-profile`, 집중 프로파일 및 workspace 계약 테스트 13개 통과 | 확장이 소유하는 공유 설정에 남은 구현 작업은 없습니다. |
| 2026-08-23 | implemented | 준비 캐시 유효성을 런타임 상태와 분리하고 준비 작업을 순서가 있는 단계 fingerprint 7개로 나눴으며, Docker volume identity가 데이터베이스 기반 단계를 무효화하도록 했습니다. 전체 스택 시작은 감독 대상 프로세스를 시작한 뒤 반환하고 supervisor는 60초 게이트를 계속 실행합니다. `console: wait full stack ready`가 명시적 차단 검사를 제공하며 Core 전용 복구는 최신 Pantheon heartbeat를 기다립니다. | `current change`, `.vscode/tasks.json`, `scripts/automation/{developer-workflow.py,local-service-input-digest.py}`, `scripts/deployment/local/{prepare-console-full-stack,prepare-console-state,start-console-services,run-console-service}.sh`, 집중 시작 계약 모음 테스트 38개 통과, 셸 구문 및 VS Code 진단 통과 | 범위가 제한된 로컬 시작 응답 경로에 남은 구현 작업은 없습니다. |
| 2026-08-22 | validated | Core Runtime이 범위가 제한된 프로바이더 초기화를 완료하고 첫 Pantheon heartbeat를 내보낼 수 있도록 clean Console 시작 준비 상태 게이트를 15초에서 60초로 늘렸습니다. 제한 없는 Bash `/dev/tcp` 소유권 확인을 연결 전에 상속된 서비스 잠금을 닫는 250ms IPv4 및 IPv6 소켓 검사로 교체하여, 필터링된 loopback 포트가 준비 상태 기한을 넘겨 소유자 정보만 있는 잠금을 유지하지 않도록 했습니다. | [이슈 #254](https://github.com/dotnetpower/fdai/issues/254), `current change`, `scripts/automation/run-local-service.sh`, `scripts/deployment/local/start-console-services.sh`, 집중 실행기 및 workspace 작업 계약 테스트 28개 통과, clean 표준 시작에서 6/6 준비 상태 도달, port 5273 및 8010-8013의 HTTP 200 응답, 관리 잠금 6개 유지 확인 | #254의 잔여 작업이 없습니다. |
| 2026-08-22 | implemented | 폴더를 열 때 실행하던 전체 스택 시작을 명시적 `console: start full stack` 작업으로 바꾸고, 호출자가 하나뿐인 준비 작업 9개를 통합했으며, 서비스 작업 블록 8개와 별도 준비 상태 확인 작업을 supervisor 하나로 교체했습니다. Supervisor는 서비스마다 허용 목록 기반 실행기, 잠금, fingerprint, 로그 및 프로세스 수명주기를 각각 유지합니다. 작업 수를 29개에서 11개로 줄였습니다. | `current change`, `.vscode/tasks.json`, `scripts/deployment/local/{prepare-console-full-stack,start-console-services,run-console-service}.sh`, 집중 workspace 작업 계약 테스트 4개 통과, 세 스크립트의 `bash -n` 통과 | Console 구성이 필요할 때 명시적 전체 스택 작업을 실행합니다. |
| 2026-08-21 | implemented | Cognitive deployment를 변경할 수 있는 계획에만 중요한 모델 완결성 검사를 적용했습니다. 개발 게이트웨이 대상 계획은 기존 모델 계정과 호출자 RBAC를 계속 수렴하지만 대상 집합에 cognitive deployment가 없으므로 관련 없는 모델 해석을 건너뜁니다. | `current change`, `.github/workflows/deploy-dev.yml`, 집중 모델 수명 주기 및 보호 workflow 테스트, Terraform 전 불일치를 드러낸 보호 실행 `32435485872`와 `32435748272`. | 동일한 Event Bus 이행 계획을 다시 실행합니다. 모델 레지스트리를 바꾸기 전에 별도의 Foundry 다중 발행기 endpoint 이행을 설계합니다. |
| 2026-08-21 | implemented | 빈 기능 맵이 기존 embedding deployment 삭제를 암시한 사실을 확인한 뒤 개발 게이트웨이 예외를 정정했습니다. 이제 게이트웨이 대상 계획은 모델 해석을 유지하면서 완결성 결과만 차단하지 않습니다. | 보호된 계획 실행 `32456242726`, `current change`, 집중 모델 수명 주기 및 보호 workflow 스위트의 테스트 44개 통과. | 동일한 Event Bus 이행 계획을 다시 실행하고 적용 전에 모델 deployment 변경이 없음을 확인합니다. |
| 2026-08-21 | implemented | `hil-only` 해석기 레코드를 Terraform 기능 입력에서 제외하면서 봉인된 근거 산출물에는 유지했습니다. | 보호된 계획 실행 `32460379091`에서 경계 불일치를 확인했습니다. `current change`의 집중 모델 수명 주기 검사에서 테스트 9개가 통과했습니다. | 동일한 Event Bus 이행 계획을 다시 실행하고 적용 전에 모델 deployment 변경이 없음을 확인합니다. |
| 2026-08-19 | implemented | 서비스 hot path에서 경고 로그 쓰기 증폭과 로컬 터미널 역압력을 제거했습니다. 경고 레코드는 범위가 제한된 프로세스 간 잠금 아래 추가하고, 압축은 공유 5분 주기로 실행하며, 구조화 레코드와 터미널 버퍼에 byte 상한을 적용합니다. 반복 aiokafka 또는 Pantheon 관찰자 실패는 서로 다른 최초·주기 근거와 복구 횟수를 보존합니다. | `current change`, 집중 telemetry·launcher·provider integration·framework layout 검사, 16회 비평 라운드 결과 Low를 넘는 발견 사항 없음 | 실제 프로세스가 이 개정 번호를 사용하려면 다시 시작해야 합니다. 런타임 종료 게이트와 배포 근거는 변경되지 않았습니다. |
| 2026-08-19 | implemented | 로컬 및 배포 job에 완전한 창 4개라는 동일한 catch-up 상한을 적용했습니다. 첫 로컬 실제 실행에서 개별 창이 각각 범위 내에 있어도 창의 연속 개수가 제한되지 않으면 terminal cursor 기록 전에 source 수준 timeout을 소진할 수 있음을 확인했습니다. | [이슈 #217](https://github.com/dotnetpower/fdai/issues/217). Bound 전 로컬 실행은 `source_timeout`을 보고했고, 이후 focused 공유 provider 및 runner 검사 31개가 통과했습니다. | 완료된 로컬 및 배포 revision campaign 근거를 보존합니다. |
| 2026-08-19 | implemented | 로컬 및 배포 observation job에서 Activity Log backlog 복구 동작을 동일하게 유지했습니다. 두 실행 위치 모두 timestamp 전용 adaptive 창, 완전한 창 단위 cursor checkpoint, result 10,000개 및 2,000,000 byte 상한, 즉시 `source_catchup` 연속 실행을 사용하며 관련 없는 실패는 정상 간격을 유지합니다. | [이슈 #217](https://github.com/dotnetpower/fdai/issues/217). Focused provider 및 runner 검사 30개가 통과했습니다. 동작은 공유 출처 catalog와 campaign package에 유지됩니다. | 완료된 로컬 campaign을 보존한 뒤 기존의 열린 배포 revision campaign 근거를 확보합니다. |
| 2026-08-19 | implemented | venue 게이트 자체의 범위가 조용히 줄어들 수 없게 했습니다. `main([])`은 넘겨받은 트리만 보고하고 테스트는 종료 코드만 단언했으므로, `SCANNED_TREES`에서 행을 지워도 게이트는 통과했을 것입니다. 이제 테스트가 저장소 구조에서 기대 집합을 도출하며, core 서비스가 패키지 2개를 배포하기 때문에 `services/core-control-plane/src/fdai_core_service`가 스캔되지 않고 있었다는 사실을 바로 찾았습니다. 게이트는 트리 7개를 훑습니다. 그 패키지에는 위반이 없었으므로 이는 결함이 아니라 커버리지 구멍을 메운 것입니다. | `current change`, `tests/integration/scripts/test_venue_capability_contract.py`가 5건 통과했고 신규 테스트는 표를 고치기 전에 `core-control-plane has 2 source packages`로 실패했습니다. 게이트는 소스 트리 7개에서 OK를 보고하고 pre-push 구조 게이트 10개가 모두 통과했습니다. | 게이트 탐지는 여전히 텍스트 기반이므로 계산된 키를 통한 우회적 재도입은 잡지 못합니다. |
| 2026-08-19 | implemented | WSL 재시작 뒤 transient 경로가 VPN 연결 끊김 경고로 나타난 문제를 막기 위해 폴더 열기 dev-access 태스크에 범위가 제한된 유예 시간을 추가했습니다. Azure VPN Client는 한 번만 열고 direct 경로가 나타나면 즉시 재시도를 끝내 WSL DNS를 적용하며, 8번 확인 뒤에도 indirect인 경로는 기존 actionable 오류를 계속 보고합니다. | `current change`, 즉시 준비됨, 세 번째 probe에서 회복, 영구 연결 끊김을 다루는 실제 startup harness가 client 1회 실행, 재시도 8회, 대기 7회, DNS 미적용 및 exit `20`을 검증합니다. | Transient 폴더 열기 경로 전파에 남은 구현 작업은 없습니다. Private endpoint 진단은 계속 명시적 `doctor.sh` 대상을 사용합니다. |
| 2026-08-17 | validated | 검토된 ActionType 팔레트와 워크플로 카탈로그를 `operator-projection:workflow:workflow.action-type-list`와 `workflow.catalog`로 구체화해, Workflow builder가 unavailable 대신 선언된 구성 요소를 렌더합니다. | 현재 변경; `test_materialize_authoritative_catalogs.py` 5개 통과; 인증된 `/workflow-builder` 로드가 ActionType 48개와 워크플로 12개를 트리거·스텝 수·모드와 함께 렌더했습니다. | 검토된 선언이 아니라 런타임 근거에 기반한 화면은 여전히 `503`을 반환합니다. |
| 2026-08-17 | validated | 검토된 `config/agent-stewardship.yaml`을 기존 Core coverage 보고서를 통해 `operator-projection:operations:stewardship.coverage`로 구체화해, Agent oversight가 unavailable 대신 측정된 소유 현황을 렌더합니다. | 현재 변경; `test_materialize_authoritative_catalogs.py` 3개 통과(콘솔 계약 불변조건 테스트 포함); 인증된 `/agent-oversight` 로드가 `AGENTS 15`, `MAINTAINERS 2`, `AUTONOMOUS 1`과 Core 계산 finding 표를 unavailable 블록 없이 표시했습니다. | 리포 선언이 아닌 런타임에 생성되는 근거 화면은 여전히 `503`을 반환합니다. |
| 2026-08-17 | implemented | 이 리포 어디에도 없는 심볼인 `OperatorApiConfig.<field>`를 안내하던 운영자 대상 문구를 담당 체계·워크플로 작성·승격 게이트·규칙 카탈로그·온톨로지·팬테온 패널에서 제거했습니다. | 현재 변경; 집중 콘솔 검사 9개 파일 71개 테스트 통과, Console typecheck 통과, 영향받는 5개 카탈로그 쌍 모두 키 패리티 유지, 6개 패널 인증 통과에서 제거된 심볼 참조가 없었습니다. | 해당 route 배선은 별도 작업이며, 패널은 이제 관측 가능한 상태만 진술합니다. |
| 2026-08-17 | validated | 남은 미제공 읽기 화면(`/capabilities`, `/skills`, `/forecast-learning`, `/operator-memory`)을 선언하고, 대화 보증 패널이 날것 전송 코드를 표시하지 않도록 했습니다. | 현재 변경; Operator composition 집중 테스트 `50 passed`, Console typecheck 통과, 보증 카탈로그 키 패리티 확인; Agents·Governance·Evidence·Settings 하위 메뉴 인증 통과에서 `404`와 날것 `HTTP nnn`이 모두 없었습니다. | 이 화면 집합에 남은 작업은 없습니다. projection이 연결되지 않은 등록된 route는 계속 서버 소유 사유와 함께 `503`을 반환합니다. |
| 2026-08-17 | validated | 제공하지 않는 `/onboarding`, `/configuration-baselines`, `/conversation-delivery` 화면을 각각 자신의 소스로 선언해 패널이 자기 자신에 대한 사유를 표시하도록 했습니다. | 현재 변경; Operator composition 집중 테스트 `50 passed`; Operations 13개 화면 인증 통과에서 오류 알림·`404`·날것 전송 코드 노출이 모두 없었습니다. | 소실된 onboarding·baseline·delivery 기능을 서비스 경계 안에서 재구축할지 결정합니다. 이전 구현은 Core provider를 직접 import했습니다. |
| 2026-08-17 | validated | 이 배포판이 제공하지 않는 `/finops`와 `/kpi/autonomy` 측정 화면을 읽기 데이터 소스 레지스트리에 선언하고, 선택적 Overview projection이 레지스트리의 `503` 신호를 허용하도록 했습니다. | 현재 변경; Operator composition 집중 테스트 `49 passed`와 Console dashboard-loading 테스트 `3 passed`를 모두 변이 검증했고, Overview 6개 화면 인증 통과에서 오류 알림이 없었으며 모든 `404`가 사라졌습니다. | 이 배포판에 reader만 있고 writer가 없는 `promotion-gate.list` projection을 구현하거나 폐기합니다. |
| 2026-08-13 | in-progress | 이전 출처 이력을 재구성하지 않고 구현 ledger를 도입했으며 machine 범위 Pylance launch 제어를 FDAI 프로파일로 이동했습니다. | 현재 변경의 `.vscode/fdai.code-profile`, `.vscode/settings.json`, `scripts/automation/configure-vscode-profile.py` 및 focused 프로파일/workspace 테스트 9개 통과. | FDAI Pylance process argument와 중앙 검증 receipt를 기록합니다. |
| 2026-08-13 | deferred | 실효성 없는 Pylance machine 설정을 제거하고 중복 프로파일 JSON 키를 거부했으며 재도입 방지 contract를 추가했습니다. | Clean Remote WSL process command에 구성한 heap argument가 없었으며 focused 프로파일 및 workspace 테스트 11개가 통과했습니다. | 별도 root의 VS Code Server 또는 WSL 배포판을 사용한 뒤 재시작한 process command에서 heap argument를 증명합니다. |
| 2026-08-13 | implemented | 파괴적인 검증을 위한 전용 로컬 PostgreSQL cluster를 추가하고 detached 검증 queue가 생성된 전용 DSN만 읽도록 했습니다. | 현재 변경, Compose config 통과, focused queue 및 local-env 테스트 68개 통과, 격리된 migration upgrade/downgrade 검사 2개 통과. | 로컬 검증 데이터베이스 격리에 남은 구현 작업은 없습니다. |
| 2026-08-13 | in-progress | 라이브 Console 테스트의 폐기된 backend 경로를 운영 어댑터와 테스트 전용 bearer 검증을 사용하는 독립 Operator Service로 교체하고, readiness 실패를 제한하도록 격리된 stack을 IPv6 loopback으로 옮겼습니다. | 현재 변경의 `console/playwright.live.config.ts`, `console/tests/live-e2e/operator_service.py`, `console/tests/live-e2e/console-routes.spec.ts`, focused Overview 검사 1개가 5.1초에 통과했습니다. | 등록된 경로 50개를 모두 실행한 뒤 최소 10회 보증 라운드와 10회 비평/하드닝 라운드를 완료하여 Low보다 높은 심각도 finding이 남지 않게 합니다. |
| 2026-08-13 | in-progress | Capability catalog가 선택적 projection 누락과 예기치 않은 실패를 구분하도록 하고 라이브 예외를 `404 /capabilities`로 제한했습니다. | 현재 변경의 `console/src/routes/capabilities.tsx`, `console/src/routes/capabilities.test.ts`, `console/tests/live-e2e/console-routes.spec.ts`, focused unit 테스트 7개 및 인증된 focused 라이브 검사 1개가 통과했습니다. | 남은 실패 경로를 수리한 뒤 열려 있는 보증 및 비평/하드닝 라운드를 완료합니다. |
| 2026-08-13 | validated | Live 관찰 소비자 그룹을 Operator 환경과 composition에 연결하고 E2E launcher를 UUID 범위 그룹으로 격리했으며 정본 유입부터 기존 Live DOM까지 인증된 로컬 이벤트 경로를 증명했습니다. | 현재 변경의 Operator 환경, composition, launcher 및 focused 회귀 검사에서 테스트 41개가 통과했습니다. 통제된 Browser Entra 근거는 이벤트와 허용된 네 단계를 모두 렌더링했습니다. | 배포된 개정 번호에서 동등한 근거를 기록합니다. 브라우저 Notifications API와 브라우저 종료 상태의 push 전달은 이 근거 범위 밖에 남습니다. |
| 2026-08-13 | in-progress | 온톨로지 보증 아티팩트가 통제된 근거가 되기 전에 정확한 source, configuration, workspace, 인증, request 및 projection 출처 이력에 연결했습니다. | 현재 변경의 `console/tests/live-e2e/ontology-query-assurance*.ts`, focused Vitest 25개 통과 및 Console 타입 검사 통과. | 정확한 중앙 검증 receipt를 얻은 뒤 seeded 영/한 100-case cohort 전에 인증된 probe 하나를 실행합니다. |
| 2026-08-13 | implemented | 로컬 상태를 한 번 준비하고 서비스별 확인 클릭 없이 백엔드 서비스 5개와 Console SPA를 모두 시작하는 신뢰된 workspace 집계 작업을 추가했습니다. | 현재 변경의 `.vscode/tasks.json` 및 `tests/integration/scripts/test_vscode_workspace_performance.py`, 집중 workspace 작업 테스트 3개 통과. | 로컬 full-stack 자동 시작에 남은 구현 작업은 없습니다. |
| 2026-08-13 | implemented | 로컬 시작 및 배포된 Operator 상태에 검토된 Rule 및 Ontology 카탈로그를 준비 시점에 구체화하도록 추가했습니다. | 현재 변경의 `.vscode/tasks.json`, `scripts/deployment/local/materialize-authoritative-catalogs.py`, `infra/modules/operator-api/container-app/`, `.github/workflows/deploy-dev.yml`, 집중 materializer, Operator 및 배포 테스트 통과. | 카탈로그 구체화 전에 migration이 완료됨을 보여 주는 보호된 배포 근거를 기록합니다. |
| 2026-08-13 | implemented | 일반 Live가 이후 이벤트만 전달하는 성질을 유지하면서 새 Agent SSE 구독자에게 경쟁 조건 없이 프로세스 내부 최신 상태를 제공하도록 했습니다. | 현재 변경의 Operator 스트림 hub, composition 및 focused 회귀 검사, 스트림 테스트 9개와 변경한 모든 Python 파일의 Ruff 검사 통과. | 인증된 브라우저 세션에서 Agent fleet이 즉시 초기화되는지 검증합니다. |
| 2026-08-13 | validated | 변경한 코드로 Operator를 다시 시작한 후 기존의 인증된 Browser Entra 세션을 통해 Agent fleet이 즉시 초기화되는지 검증했습니다. | `/agents` 새로 고침 3회가 각각 224ms, 232ms, 228ms 안에 `Watching 2 / Idle 13 / Unobserved 0`에 도달해 15초 런타임 heartbeat 간격보다 충분히 짧았습니다. | Agent 새로 고침 최신 상태 초기화에 남은 구현 작업은 없습니다. |
| 2026-08-13 | implemented | 고정된 160000토큰 Copilot 에이전트 이력 압축 임계값을 선택한 모델의 맥락 창 80%로 바꿨습니다. | 현재 변경의 `.vscode/settings.json`과 `tests/integration/scripts/test_vscode_workspace_performance.py`, VS Code JSON 진단 통과 및 집중 압축 계약 테스트 1개 통과. | 비율 기반 Copilot 대화 압축에 남은 구현 작업은 없습니다. |
| 2026-08-14 | implemented | 자동 full-stack 작업을 반복 요청해도 VS Code 작업 인스턴스 선택창을 열지 않고 실행 중인 각 단일 인스턴스를 유지하도록 했습니다. | 현재 변경의 `.vscode/tasks.json`과 `tests/integration/scripts/test_vscode_workspace_performance.py`, 집중 자동 시작 계약 테스트 1개 통과. | 클릭 없는 중복 시작 요청에 남은 구현 작업은 없습니다. |
| 2026-08-14 | implemented | 등록된 모든 출처를 위한 하나의 권한 인식 관측 캠페인을 추가하고 실행 조건을 확인하는 같은 CLI를 full-stack 로컬과 배포된 Container Apps Job에 연결했습니다. | `current change`, 버전 관리 활동 계약, 출처 카탈로그, 프로바이더 probe, 영속 실행기, Operator 변환 결과, Console lane 및 집중 검사 | 검증을 주장하기 전에 같은 카탈로그 digest를 사용하는 통제된 로컬 실행 하나와 배포 개정 실행 하나를 보존합니다. |
| 2026-08-14 | implemented | 제거된 인제스트 co-host 경로와 독립 Document Ingestion API 및 Document Processing Worker 서비스 루트에 맞게 mock Terraform 검사를 정렬했습니다. | `current change`, Terraform 검증 통과 및 집중 인제스트 테스트 5개 통과 | 배포 가이드와 mock 테스트를 독립 서비스 루트에 맞게 유지합니다. |
| 2026-08-14 | implemented | 격리된 Playwright 시작 probe 지연을 제거하고 repository root와 VS Code에 직접 desktop E2E 항목 지점을 추가했습니다. | `current change`, Console 타입 검사 통과, 라이브 수집이 `*.spec.ts` 파일 4개에서 테스트 58개를 나열했으며 focused desktop E2E 테스트 1개가 2.8초에 통과했습니다. | 격리된 Console E2E 개발 루프에 남은 구현 작업은 없습니다. |
| 2026-08-14 | implemented | 동시에 실행되는 고정본 및 live Playwright 세션을 위해 frontend와 Operator API 포트를 짝지은 원자적 10-slot 포트 풀과 slot별 산출물 격리를 추가했습니다. | `current change`, allocator 테스트 6개와 Console 타입 검사가 통과했으며 focused Playwright 프로세스 2개가 frontend port `5274`와 `5275`에서 동시에 통과한 뒤 listener와 lock이 남지 않았습니다. | 동시에 실행되는 격리 Playwright 포트 할당에 남은 구현 작업은 없습니다. |
| 2026-08-14 | implemented | T2를 최초 플래너로 연결하는 대신 로컬 및 배포 의미 계획을 하나의 T1 우선 모델 cascade로 정렬했습니다. | `current change`, 집중 플래너 및 조립 검사는 두 실행 장소가 사용하는 동일한 해석된 산출물 계약에서 통과합니다. | T1 선택과 범위가 제한된 T2 escalation의 통제된 로컬 및 배포 기록을 보존합니다. |
| 2026-08-15 | implemented | 로컬 및 배포 Operator composition에 같은 payload-free 브라우저 근거 메타데이터 경로와 데이터 출처 소유권을 추가했습니다. | `current change`, focused Operator 검사 `51 passed`, Operator 경계 및 independent-service gate 통과 | 인증된 배포 읽기 증적 하나를 보존하고 Console 메타데이터 패널을 추가합니다. |
| 2026-08-15 | implemented | 연결된 두 작업 영역이 표준 Console, Operator 및 Core 프로세스를 두고 경합한 뒤 폴더 열기 full-stack 자동 시작을 primary checkout으로 제한했습니다. | 현재 변경의 `.vscode/tasks.json`과 `tests/integration/scripts/test_vscode_workspace_performance.py`, 집중 자동 시작 계약 통과. | 연결된 worktree 자동 시작 격리에 남은 구현 작업은 없습니다. |
| 2026-08-15 | implemented | 로컬 서비스 실행기가 서비스가 실제로 소유하는 싱글턴을 확인하도록 해서, 런타임 lock 또는 포트가 이미 다른 인스턴스 소유일 때 실패가 예정된 자식 프로세스를 띄우지 않고 중단하도록 했습니다. | `current change`, `scripts/automation/run-local-service.sh`와 `tests/integration/scripts/test_run_local_service.py`, 실행기 테스트 11건 통과, 두 백엔드 작업 모두 provider 스택 추적 대신 `service already running`을 보고. | Console dev 서버는 자체 작업이 직접 실행하므로 포트 충돌은 아직 Vite 오류로 드러납니다. |
| 2026-08-15 | implemented | 배포 준비 상태 polling의 job별, app별 시도 횟수 곱을 누적 migration deadline 하나와 누적 revision deadline 하나로 대체했습니다. | `current change`, `.github/workflows/deploy-dev.yml`, focused workflow 계약 테스트 통과. | 남은 준비 대기는 provider에 종속되며 선언된 deadline으로 보고됩니다. |
| 2026-08-15 | implemented | 공유 deadline에 관측할 예산이 남지 않으면 migration job 시작을 거부하도록 해서, 시작된 job이 관측되지 않은 채 방치되지 않게 했습니다. | `current change`, `.github/workflows/deploy-dev.yml`, focused workflow 계약 테스트 통과. | Migration 관측 범위에 남은 작업이 없습니다. |
| 2026-08-15 | implemented | Poll 주기 1회와 ARM start 왕복이 공유 deadline 안에 들어갈 때만 migration job을 시작하도록 했습니다. | `current change`, `.github/workflows/deploy-dev.yml`, focused workflow 계약 테스트 통과. | 여유값은 고정 45초 추정치이므로 그보다 느린 start는 job이 실행 중인데도 미완료로 보고될 수 있습니다. 해당 단계는 조용히 넘어가지 않고 명시적으로 실패합니다. |
| 2026-08-15 | implemented | 위 deadline 및 여유값 행의 근거를 정정합니다. 해당 값을 단언하는 focused 테스트는 없으므로 workflow는 YAML 파싱과 배포 계약 suite로 검증했고 제한은 단계 자체가 강제합니다. | `current change`, `deploy-dev.yml`이 유효한 YAML로 파싱되고 script 통합 suite 1151개 통과입니다. | 선언된 deadline 값에 대한 focused 단언은 남아 있습니다. |
| 2026-08-17 | implemented | Roadmap 자동화 session 용량을 리포지토리 범위로 제한했습니다. 기본 WSL workspace-storage id는 정본 remote URI에서 도출하고, 다른 VS Code remote는 정확한 storage 경로를 지정할 수 있으며, 다른 리포지토리의 최근 활동은 FDAI를 보류하지 않습니다. | `current change`, `roadmap_verification_watchdog.py`, focused watchdog 테스트, `scripts/README.md`의 운영 계약 | Campaign session 범위에 남은 작업은 없습니다. |
| 2026-08-17 | implemented | Linked worktree session 계산을 바로잡았습니다. 기존 리포지토리 범위 구현은 campaign worktree 경로를 hash해 VS Code storage를 찾지 못했으므로 linked campaign이 FDAI session을 0개로 셀 수 있었습니다. 이제 workspace URI를 hash하기 전에 Git common directory에서 primary checkout을 도출합니다. | `current change`, `roadmap_verification_watchdog.py`, `test_roadmap_verification_watchdog.py`의 실제 linked-worktree 회귀, focused watchdog suite 9건 통과 | Linked-worktree workspace identity에 남은 작업은 없습니다. |
| 2026-08-17 | implemented | 배포 README의 추적 연속성 문장을 필수 표시 용어로 다시 썼습니다. 운영자용 문장에 그대로 쓰인 `finding`이 중앙 검증의 `display-terminology`를 통과하지 못해 main이 거부되었고 모든 lane과 모든 착륙이 멈췄습니다. | `current change`, `infra/README.md`와 user-guide 쌍, `display-terminology`가 문서 524개에서 OK를 보고하고 번역 185/185 검증 통과 | 이 변경에 남은 작업은 없습니다. |
| 2026-08-17 | implemented | 표준 로컬 또는 배포 네임스페이스를 바꾸지 않고 대체 로컬 Operator 프로세스의 영속 semantic outbox claim을 격리했습니다. 테스트 전용 Operator는 `FDAI_SEMANTIC_TURN_OUTBOX_NAMESPACE`를 실행 id에 연결할 수 있으며 운영 기본값은 복제본에 안전한 하나의 공유 queue를 계속 사용합니다. | `current change`, focused 환경, composition, 저장소 lease 및 runner 검사 114개 통과, strict mypy 통과 | 네임스페이스가 적용된 보증 runner에서 exact-source Browser 근거를 보존합니다. |
| 2026-08-17 | validated | 로컬 장소를 배포와 동일한 권위 있는 컨트롤 루프 유입 경로에 바인딩했습니다. Activity Log recovery delta가 배포 inventory job에서는 켜져 있었지만 로컬에서는 `False` 기본값으로 남아 있어서 `aw.change.events`에 아무것도 들어오지 않았고, 모든 전송 구성 요소가 정상인데도 인증된 Live 화면이 `Source unavailable`을 표시했습니다. | `current change`, `.vscode/tasks.json`와 `tests/integration/infra/test_inventory_repair_wiring.py`, focused 인프라 및 헌법 검사 14건 통과, 로컬 실행 1회가 권위 있는 `inventory.resource_changed` 이벤트 5건을 발행해 `source: runtime-observed`인 `ingest`, `route`, `verify`, `audit` 프레임을 만들었고 Live 화면이 `Runtime observed`로 바뀜 | 남은 장소 선택 기능 플래그를 개별 바인딩 대신 하나의 계약으로 열거합니다. |
| 2026-08-18 | implemented | Core 컨트롤 플레인의 장소 선택 기능 플래그를 하나의 계약으로 열거했습니다. `runtime/venue.py`가 `FDAI_EXECUTION_VENUE`를 한 번만 해석하고 전송 보안, 워크로드 신원, 인벤토리 소스, 이벤트 버스, 관측 전송 바인딩을 소유하며, `bootstrap.py`와 인벤토리·관측·분석기 CLI는 각자 기본값을 둔 원시 문자열 비교 대신 이 표에서 읽습니다. 인식할 수 없는 값은 이제 더 약한 로컬 전송으로 떨어지지 않고 거부됩니다. `check-venue-capability-contract.py`는 임의의 직접 읽기나 리터럴 비교가 다시 들어오면 실패하며 pre-push 구조 게이트, `verify.sh`, CI에서 실행됩니다. | `current change`, `tests/runtime` focused 테스트 209건 통과, 음성 픽스처 2건을 포함한 게이트 통합 테스트 4건 통과, `tests/delivery` 1489건 통과, 작업 범위 Ruff·format·strict mypy 통과 | operator, document-ingestion, document-worker 서비스도 같은 계약 아래로 옮겨야 합니다. 각자 아직 장소를 따로 해석합니다. |
| 2026-08-18 | implemented | 검토 결과 capability 표 5개 항목 중 3개에 운영 소비자가 없어 계약이 동작을 선택하지 않고 의도만 기록하고 있었으므로 표를 실제로 동작하게 만들었습니다. `inventory_source`, `event_bus_implementation`, `observation_transport`을 제거하고, 남은 둘을 실제 선택 대상을 가리키는 `bus_identity_binding`과 `workload_identity_source`로 나눴으며, 인벤토리·관측·분석기의 신원 분기가 venue enum 비교 대신 capability를 읽도록 했습니다. focused 테스트가 소스 트리를 훑어 선언된 capability에 운영 접근자가 없으면 실패하므로 표가 다시 문서로 되돌아갈 수 없습니다. | `current change`, `tests/runtime`·`tests/delivery`·게이트 통합 테스트 focused 1703건 통과(스킵 3건), 작업 범위 Ruff·format·strict mypy 통과, venue 계약 게이트 통과 | operator, document-ingestion, document-worker 서비스도 같은 계약 아래로 옮겨야 합니다. 각자 아직 장소를 따로 해석합니다. |
| 2026-08-18 | implemented | 모든 FDAI 서비스를 같은 장소 계약 아래로 옮겼습니다. 독립 서비스는 core 컨트롤 플레인을 import할 수 없으므로 표를 `packages/service-contracts/src/fdai_service_contracts/venue.py`로 옮기고 `fdai/runtime/venue.py`는 이를 다시 내보내도록 했습니다. Operator, Document Ingestion API, Document Processing Worker, 격리 Executor의 composition은 서로 다른 오류 타입을 가진 개별 파서 4개 대신 `resolve_execution_venue()`와 capability 접근자를 읽습니다. `document_provider_binding`은 두 문서 서비스에 소비자가 있는 신규 capability이며, `bus_security_protocol`은 이제 literal 타입을 반환하므로 선언되지 않은 프로토콜로 표를 고치면 전송이 낮아지는 대신 타입 검사가 실패합니다. 게이트는 소스 트리 6개를 모두 훑습니다. | `current change`, `packages/service-contracts/tests`·`services/core-control-plane/tests/runtime`·`tests/integration/scripts/test_venue_capability_contract.py`와 독립 서비스 4개 suite에서 focused 874건 통과(스킵 1건), `tests/delivery` 1689건 통과(스킵 3건), 작업 범위 Ruff·format·mypy 통과, venue 게이트가 소스 트리 6개에서 OK 보고, `check-independent-services.py` 통과 | 게이트 탐지는 여전히 텍스트 기반이므로 계산된 키를 통한 우회적 재도입은 잡지 못합니다. |
| 2026-08-20 | 구현됨 | 다섯 distribution topology를 바꾸지 않고 독립 A3 channel edge의 local 및 deployed composition을 추가했습니다. 두 venue는 동일한 Operator 소유 runtime을 사용하며 프로바이더 credential, Kafka security, secret source 및 scale만 다릅니다. | `current change`, 집중 edge 검사 74개, 로컬 실행 검사 3개, 플랫폼 및 Operator-service Terraform root 검증 통과, independent-service 검사가 distribution 5개를 유지 | 통제된 local provider 증적 하나와 보호된 deployed plan/apply/rollback 증적 하나를 보존합니다. |
| 2026-08-20 | 구현됨 | Frozen legacy lineage와 service-owned branch 5개의 local 및 protected deployed migration 실패 경계를 정렬했습니다. 모든 연결에는 10초 deadline이 있고 모든 database 잠금 대기에는 5분 deadline이 있으며 하나의 protected migration 단계는 Terraform 적용 전에 누적 20분 deadline을 갖습니다. | `current change`; 집중 migration, A3 route 및 protected 배포 검사 282개 통과, 환경 제한 skip 1개; migration entry point 3개 strict mypy 통과. | 성공한 exact Core 적용 및 post-apply 상태 증적을 보존합니다. |
| 2026-08-20 | implemented | Local legacy migration, local service-branch migration 및 protected service 조정에 같은 15분 PostgreSQL statement deadline을 추가했습니다. Server가 20분 workflow deadline 전에 장기 실행 DDL을 취소하므로 연결이 끊긴 runner가 service 간 advisory lock을 보유하는 방치된 transaction을 남길 수 없습니다. | `current change`; 집중 migration deadline 검사; entry point 3개 strict mypy 통과; 일회용 PostgreSQL에서 예산을 초과한 statement를 취소하고 연결 해제 뒤 advisory lock 0개를 확인함. | 성공한 exact Core 적용 및 post-apply 상태 증적을 보존합니다. |
| 2026-08-20 | implemented | Question-campaign table 생성을 legacy compatibility head에서 Core service branch로 옮겼습니다. Local 준비와 protected 배포는 legacy `0086` 또는 Core branch 중 어느 쪽이 먼저 실행돼도 같은 single writer를 통해 수렴합니다. | `current change`; service migration inventory 검사; 일회용 PostgreSQL에서 두 migration 순서 통과; service 5개의 fresh adoption 통과. | 성공한 exact Core 적용 및 post-apply 상태 증적을 보존합니다. |
| 2026-08-20 | implemented | PTY host와 셸 시작은 정상인데 VS Code 기본 설정이 사용자가 입력한 통합 터미널의 0이 아닌 종료를 알림으로 표시한다는 진단에 따라 FDAI workspace에서 터미널 종료 알림을 비활성화했습니다. 중복 토스트만 억제하며 터미널 출력, 작업 상태 및 프로세스 종료 코드는 계속 확인할 수 있습니다. | `current change`, `.vscode/settings.json`, `tests/integration/scripts/test_vscode_workspace_performance.py`, 집중 workspace 계약 및 VS Code JSON 진단 | 터미널 종료 토스트에 남은 구현 작업은 없습니다. |
| 2026-08-20 | implemented | VS Code가 태스크 인스턴스 메타데이터를 잃은 뒤에도 이 체크아웃의 서비스 로그 잠금을 계속 소유한 프로세스를 자동 백엔드 시작에서 재사용하도록 했습니다. 재사용 경로는 터미널 표식을 내보내고 다른 자식 프로세스를 시작하지 않습니다. 마지막 15초 게이트는 Core 소유권과 Console, Operator API, Document Ingestion API, Document Processing Worker 및 격리 Executor 검사를 요구합니다. 다른 체크아웃이 소유한 포트와 런타임 잠금은 계속 시작 실패로 처리합니다. | `current change`, `scripts/automation/run-local-service.sh`, `developer-workflow.py`, `.vscode/tasks.json`, 집중 런처, 준비 상태 및 workspace 태스크 검사 | 같은 체크아웃의 백엔드 태스크 재연결과 시작 후 준비 상태 검사에 남은 구현 작업은 없습니다. |
| 2026-08-20 | implemented | 검토 후 재사용 판정을 강화했습니다. 각 runner는 서비스 소유 source, 생성된 환경, 의존성 선언, 감독 코드 및 정확한 실행 명령의 SHA-256 fingerprint와 owner 및 child PID를 private 0600 metadata에 기록합니다. 오래된 같은 체크아웃 runner는 cwd, 서비스 ID, owner PID 및 child process group을 검증한 뒤 자동 교체하며 다른 체크아웃 또는 unmanaged 프로세스는 받아들이지 않습니다. Child shim은 기록된 PID를 실제 session leader로 만들고 wrapper가 사라지면 `SIGTERM`을 받습니다. Core는 2초 간격 Pantheon heartbeat를 내보내고 준비 상태 검사는 10초보다 오래되지 않은 heartbeat를 요구합니다. 정상 종료가 10초를 넘으면 서비스를 강제로 종료해 singleton 잠금을 무기한 보유하지 못하게 합니다. | `current change`, 집중 launcher, digest, heartbeat, orphan 복구 및 workspace 검사. 통제된 로컬 재시작은 한 번의 검사에서 6/6 ready에 도달했고 metadata 7개가 모두 live owner와 정확한 child process group에 일치했으며 측정된 Core heartbeat는 5.4초 이내를 유지했습니다. Port `8010`-`8013` 및 `5273`은 모두 `200`을 반환했습니다. | 오래된 입력 재사용, Core liveness, parent 소실 정리 및 범위가 제한된 로컬 종료에 남은 구현 작업은 없습니다. |

### 잔여 작업
- [ ] FDAI 전용 Remote WSL server data root 또는 WSL 배포판을 마련한 뒤 제외 대상 workspace를 변경하지 않고 재시작한 Pylance process command에 `--max-old-space-size=2048`이 포함됨을 기록합니다.
- [ ] 등록된 Console 경로 50개 전체의 통과 근거를 기록한 뒤 최소 10회 보증 라운드와 10회 비평/하드닝 라운드를 완료하여 해결되지 않은 finding의 심각도가 모두 Low 이하임을 입증합니다.
- [ ] 복제본별 `FDAI_LIVE_STAGE_CONSUMER_GROUP_ID`를 통해 인증된 Live DOM에 도달하는 배포 개정 이벤트를 기록합니다. 브라우저 Notifications API 및 브라우저 종료 상태의 push 전달이 범위에 들어오면 별도로 추적합니다.
- [ ] Operator schema migration이 성공한 뒤 catalog Job이 검토된 Rule 및 Ontology 참조 변환 결과를 기록함을 보여 주는 보호된 배포 증적을 기록합니다.
- [ ] 같은 카탈로그 digest를 사용하는 통제된 로컬 및 배포 관측 캠페인 쌍을 보존합니다. 권한 있음, 사용 불가, 부분, 건너뜀 및 완료 출처 결과와 snapshot-first/실제 Agent Activity
  중복 제거를 포함합니다.
- [ ] 동일한 webhook 경로, 의미 terminal digest, 프로바이더 확인 응답 분류 및 rollback 결과를
  증명하는 통제된 local 및 보호된 deployed A3 channel-edge 증적을 보존합니다.
- [ ] venue 게이트의 텍스트 기반 탐지를 import 그래프 또는 AST 검사로 바꿔서 계산된 키나
  우회 별칭으로 도달한 장소 읽기도 리터럴과 동일하게 실패하도록 합니다
  ([#152](https://github.com/dotnetpower/fdai/issues/152)).
## 전수조사 - 로컬 동작 vs Azure 필요
2026-07-21 기준. "자동화 테스트"는 테스트 실행기가 실행하는 pytest 또는 committed mock을
뜻합니다. "Full-stack 로컬"은 운영자에 브라우저 Entra를 사용하고 서버 측 Azure 어댑터에
현재 Azure CLI 맥락을 사용하는 VS 코드 compound launch입니다. 테스트 고정본은 이 launch
프로파일에서 활성화되지 않습니다.
### 자동화 테스트에서 완전 동작 (Azure 불필요)
| 서브시스템 | 로컬 백엔드 | 비고 |
|-----------|-------------|------|
| T0 결정론 엔진 | `opa` 바이너리 + Rego 정책 + 룰 카탈로그 | 100% 오프라인; CI 동등성 게이트가 증명 |
| Rule 카탈로그 로더 + shadow eval 파이프라인 | 파일시스템 YAML | 클라우드 콜 없음 |
| Risk 게이트 + 승격 레지스트리 | 인-메모리 `ActionPromotionRegistry` | 경계 스왑 가능 |
| 실행기 + 리소스 잠금 | 인-프로세스 | 고정본 전용이며 interactive 실행기가 아님 |
| 감사 + T2 복구 상태 | `InMemoryStateStore` (hash-chain 검증) | prod 백엔드 = Postgres이며 같은 증적/경로 키가 결정론적 채팅 읽기를 제공합니다 |
| Event ingest + trust 라우터 | 인-프로세스 | 버스 미배선 |
| Verticals (복원력 / FinOps / 변경 안전성) | 순수 결정 모듈 | 클라우드 없음 |
| Quality 게이트 | `StaticVerifier` + `MatchTypeCrossCheckModel` + `InMemoryGroundingSource` | [llm-strategy-ko.md § T2](../architecture/llm-strategy-ko.md#t2--reasoning-tier-quality-gate-required) 참조 |
| T1 유사도 | `DeterministicEmbeddingModel` + `InMemoryPatternLibrary` | 해시 기반, 실제 임베딩 없음 |
Operator 브라우저 E2E 테스트는 명시적인 dev-test 프로파일에서 실제 Vite SPA를 Playwright로
실행합니다. 경로 interception은 선언된 synthetic read-source 매니페스트, 인시던트, 에이전트 프레임 및
채팅 SSE 응답을 제공합니다. 이 고정본은 테스트 실행기 안에서만 존재하며 `Console Web: Full
Stack`에서는 활성화되지 않습니다. 백엔드 통합 테스트는 같은 요청과 범위가 제한된 최종
turn-timing 계약을 실제 Starlette 경로와 근거 해석기로 별도 검증합니다.

두 격리 Playwright 구성은 `*.spec.ts` 파일만 찾아 같은 위치의 단위 테스트가 호환되지 않는
테스트 런타임을 불러오지 않게 합니다. 고정본 실행기는 Vite를 즉시 시작하고 사용하지 않는
loopback URL 또는 dual-stack port를 probe하는 대신 stdout의 `ready in` 표시를 기다립니다. 각
프로세스는 slot 10개 중 하나를 원자적으로 임대합니다. frontend port `5274-5283`은 live
Operator API port `8020-8029`와 짝을 이룹니다. Playwright worker는 부모의 slot을 상속하고,
종료된 PID의 lock은 회수하며, trace, screenshot 및 video는 slot별 output directory를
사용합니다. repository root에서 `npm --prefix console run test:e2e:quick`은 desktop 범위를
실행하며 VS Code의 `console: Playwright quick (desktop)` 테스트 작업도 같은 경로를 제공합니다.
기존 `npm --prefix console run test:e2e` 명령은 전체 desktop 및 mobile 행렬을 계속 실행합니다.

이를 보완하는 `npm --prefix console run test:e2e:live` 모음은 경로 interception 없이 운영 데이터
어댑터와 테스트 전용 신원 검증을 사용하는 격리된 Operator Service를 시작합니다. 등록된 모든
Console 패널을 방문하고, 패널 경계가 안정될 때까지 기다리며, 브라우저 exception, 공유 error
상태 및 예상하지 않은 Operator API `4xx`/`5xx` 응답을 차단하고, 테스트 경로 인벤토리가 운영
레지스트리와 계속 일치하는지 검증합니다. 정확히 선언된 unavailable contract는 런타임 결함으로
취급하지 않으면서 화면에 그대로 표시합니다. 또한 실제 운영 Command Deck을 통해 결정론적 현재
시각 턴과 허용 목록에 포함된 Microsoft Learn 웹 검색을 제출하고, 검증된 또는 근거에 기반한 최종
근거를 요구합니다. 통제된 온톨로지 보증 아티팩트는 정확한 source revision, 정규 run configuration과 digest, workspace patch digest, authentication attestation 및 정확한 request와 projection id를 기록하며, runner는 malformed source 또는 workspace 출처 이력을 첫 요청 전에 거부합니다.

### dev-up.sh 필요 (여전히 로컬)

| 서브시스템 | 로컬 백엔드 | Prod 백엔드 |
|-----------|-------------|--------------|
| 런타임 상태 저장소 및 서비스 통합 | `pgvector/pgvector:pg16` on `:5432` | Azure PostgreSQL Flexible + pgvector |
| 파괴적 migration 검증 | 별도 `pgvector/pgvector:pg16` cluster on `:5433` | 격리된 CI 검증 데이터베이스 |
| Event 버스 (통합 테스트) | Redpanda on `:19092` (Kafka wire) | Event Hubs Kafka on `:9093` |

### 고정 workspace 포트

커밋된 VS 코드 설정은 각 로컬 web 표면이 항상 같은 포트를 사용하게 합니다. 정적 design mock
site는 인증된 Console full stack과 분리되어 있습니다.

| 표면 | 기본 주소 | Workspace 항목 지점 |
|---------|-------------|-----------------------|
| Design mock | `http://127.0.0.1:5373` | `Design Mocks: Static Site` launch 또는 `design mocks: serve (5373)` 작업 |
| Console SPA | `http://127.0.0.1:5273` | `Console Web: Full Stack` (권장) 또는 `Console Web: Frontend` (SPA 전용) |
| Operator API | `http://127.0.0.1:8010` | `Console Web: Operator API` |
| 문서 인제스트 API | `http://127.0.0.1:8011` | `Console Web: Document Ingestion API` |
| 문서 처리 워커 상태 | `http://127.0.0.1:8012` | `Console Web: Document Processing Worker` |
| 격리 실행기 상태 | `http://127.0.0.1:8013` | `Console Web: Isolated Executor` |

`Console Web: Full Stack` compound는 독립 패키지로 구성된 백엔드 서비스 5개와 Console
SPA를 시작합니다. 각 launch는 담당 서비스 분포만 가져오며 제거된 top-level 패키지, 문서 처리
co-host 또는 프로세스 내 Operator API 호환성 경로를 복원하지 않습니다. 로컬 격리 실행기는
managed-resource identity가 없는 영속 shadow consumer입니다. 이 venue에서 authority cutover를
설정하면 시작이 실패합니다. Compound는 정적 design mock이나 fixture 애플리케이션을 시작하지
않습니다.

프로세스 launcher는 `RUNTIME_ENV`와 독립적으로 `FDAI_EXECUTION_VENUE=local`을 설정합니다. 로컬
서비스 상태는 `127.0.0.1:5432`의 Docker PostgreSQL을 사용하며 Core, Operator, 문서 인제스트 API,
문서 처리 워커 및 격리 실행기는 각각 담당 역할로 연결하고, 로컬 이벤트 전송은 `127.0.0.1:19092`의
Docker Redpanda를 사용합니다. Azure에 배포된 프로세스는 `FDAI_EXECUTION_VENUE=deployed`를 설정하고
서비스 소유 Azure Database for PostgreSQL DSN과 Event Hubs Kafka endpoint를 사용합니다. Venue 선택은 근거 권한, 승격 상태, 사람 신원 또는 executor 권한을 변경하지 않습니다. Schema parity는 legacy 및 서비스 소유 migration 5개로 이동한 뒤 대상 Settings, catalog, ontology 및 inventory projection을 권위 있는 입력에서 다시 생성합니다. 로컬 `audit_log`, `state_kv`, 승인, idempotency record, lease 또는 executor receipt를 배포 환경에 복제하지 않습니다. 이러한 record는 출처 venue의 인과 관계와 권한을 유지합니다.

`database_host_binding` 배포 mode는 배포 service의 비밀이 아닌 `POSTGRES_HOST` 연결만 변경합니다. 모든 service root는 비어 있지 않은 host를 요구하고, Core는 검증된 `llm` object를 child module로 전달하며, 봉인된 guard는 다른 명령이나 환경 표류를 차단하고 exact apply는 plan의 mode와 digest를 그대로 반복해야 합니다. Core 모델 전환은 비밀 service tfvars 대신 저장소의 resolved-model 매니페스트와 웹 검색 정책에서 해당 `llm` object를 도출합니다. 구체화 도구는 매니페스트의 정규 digest가 이미지 attestation과 일치하도록 요구하고 HTTPS endpoint 출처를 정확히 하나만 허용하며, 산출물에 일치하는 후보가 있고 저장소 정책이 허용 목록을 제공할 때만 웹 검색을 활성화합니다. Legacy Core revision에 검토된 Event Bus topic, database host 및 model binding이 모두 없으면 Core 전용 전환 하나가 세 mode를 함께 봉인하고 모든 전용 guard를 같은 plan에 적용합니다. 네 번째 환경 변경은 계속 차단됩니다. 독립 배포된 Operator는 typed incident request와 read-investigation completion topic 및 consumer group을 렌더링하고 필수로 요구하므로 topic guard가 정확한 값을 검증합니다. 격리 Executor migration도 command, receipt 및 DLQ transport 값을 `FDAI_EXECUTION_VENUE=deployed`와 함께 고정하며 관련 없는 환경 변경은 계속 차단됩니다. Local composition은 loopback host를 계속 사용하므로 이 전환은 실행 venue를 바꾸거나 배포 DSN을 local에서 재사용하지 않습니다. Database venue도 측정 권한을 변경하지 않습니다. Core는 table `SELECT, INSERT`와 `llm_invocation_invocation_id_seq`의 `USAGE, SELECT` 권한으로 `llm_invocation`에 행을 추가하고 Operator는 table을 `SELECT`로 읽습니다. 권한 migration은 `PUBLIC` 접근을 revoke하고 어느 role에도 table update 또는 delete 권한을 주지 않으며 Core에는 sequence `UPDATE` 권한을 주지 않습니다. 두 venue 모두 JSON payload를 scan하지 않고 concurrently 생성한 동일한 partial `audit_log.action_kind` index를 통해 incident lifecycle history를 복구합니다.

작업 영역을 열어도 Console 구성을 시작하지 않습니다. 신뢰된 primary checkout에서 `console: start full stack`을 명시적으로 실행하면 준비 작업이 편집기 초기화와 경쟁하지 않습니다. 이 작업은 공유 Git 디렉터리 소유를 확인하고 `prepare-console-full-stack.sh`을 실행한 뒤 `start-console-services.sh`을 실행합니다. 준비 작업은 먼저 모든 서비스 migration branch와 쓰기 소유권을 검증합니다. 그다음 port `5432`의 런타임 PostgreSQL, port `5433`의 격리된 검증 PostgreSQL cluster, Redpanda 및 ClamAV를 복구한 뒤 순서가 있는 8개 단계 fingerprint를 평가합니다. 8개 단계는 Console 의존성, 로컬 migration, 런타임 환경, 권위 있는 인벤토리, Settings 변환 결과, 카탈로그 변환 결과, 서비스 환경 및 Entra redirect입니다. 각 단계는 이미 실행 중인 애플리케이션 스택을 요구하지 않고 정확한 입력과 필수 출력으로 재사용됩니다. 데이터베이스 기반 단계에는 로컬 PostgreSQL volume identity도 포함하므로 재생성된 volume이 오래된 파일 marker를 상속할 수 없습니다. Console 의존성 단계가 없거나 변경되면 운영자에게 `node_modules`를 수동 복구하도록 요청하지 않고 lockfile 기반 `npm ci`를 실행합니다. 각 외부 명령은 출력을 전달하는 `run-bounded-command.py`를 통해 실행하며 전체 또는 무진행 기한을 한 번만 고정합니다. 실행기는 직접 자식이 먼저 종료되어도 전체 자식 process group에 계속 signal을 보내며 만료 시 `SIGTERM`을 보낸 뒤 선언된 유예 시간이 지나면 `SIGKILL`로 전환합니다. `--force`는 모든 단계를 무효화합니다.

Supervisor는 허용된 각 `run-console-service.sh`을 자체 잠금, fingerprint, 로그 및 수명주기와 함께 병렬 시작합니다. 모든 launcher를 시작한 뒤 `started`를 내보내지만 VS Code 태스크는 supervisor가 terminal `ready` 또는 `failed` 중 하나를 정확히 한 번 내보낼 때까지 활성 상태를 유지합니다. 전체 readiness gate의 기본값은 60초이며 외부 process-group deadline은 65초입니다. Readiness 전의 모든 child exit, readiness 실패, signal 또는 managed-lock 실패는 `failed`를 내보내고 0이 아닌 값으로 종료합니다. 중복된 명시적 시작은 조용히 무시되지 않고 managed lock과 fingerprint 재사용 경로를 통해 동시에 실행됩니다. `console: wait full stack ready`는 성공한 시작 뒤 사용하는 별도 10초 진단이며 두 번째 시작 단계가 아닙니다. 텍스트 모드는 반복 확인 전에 대기 예산을 내보내고 JSON 모드는 하나의 기계 판독 문서를 유지합니다. Core와 Operator 복구 작업은 이름이 지정된 동일한 서비스 준비 상태 검사를 적용하고 프로세스 시작을 준비 상태로 취급하지 않도록 terminal 표식을 내보냅니다. 변경되거나 다른 소유권은 관리 대상만 교체하거나 실패합니다.

순서가 있는 준비 작업은 해당 단계 입력이 바뀐 경우에만 읽기 전용 Azure Resource Graph 인벤토리를 새로 읽고 정제된 모델, 런타임 Settings, Rule 및 Ontology 변환 결과를 구체화합니다. 이러한 선언은 발견된 문제, 관측된 인벤토리, 준비 상태 또는 실행 권한을 만들지 않습니다. 프로바이더를 사용할 수 없거나 권한이 없으면 고정본 데이터로 대체하지 않고 인벤토리를 명시적으로 사용할 수 없는 상태로 유지합니다. 전체 스택 시작에는 신뢰된 workspace와 커밋된 정책이 필요하며 권한을 약화하지 않습니다.
Loopback 소유권 확인에는 범위가 250ms로 제한된 IPv4 및 IPv6 소켓 검사를 사용하며 연결 중에는
서비스 잠금을 유지하지 않습니다. 종료는 10초 뒤 자식 process group을 중지하고 wrapper가 사라지면
그 leader에 signal을 보냅니다. 개별 서비스 또는 debug launch 전에는
`console: prepare full stack`을 실행합니다.
Git에서 제외된 로컬 런타임 환경은 검증 cluster를 `FDAI_VALIDATION_DATABASE_URL`로 기록하고,
분리된 검증 queue는 선택된 통합 테스트에 이 값만 `FDAI_DATABASE_URL`로 매핑합니다. 활성 런타임
DSN은 전달하지 않습니다. Alembic role 변경은 cluster-global이므로 별도 cluster가 필요합니다.
같은 이행이 로컬 및 deployed PostgreSQL에 principal 범위 `conversation_image` 저장소를
만듭니다. 따라서 두 프로파일의 Command Deck 이력은 동일한 인증 Operator API 경로를 통해 전송된
이미지를 복원하며, 어느 프로파일도 inline base64를 턴 메타데이터 또는 브라우저 대화 기록 캐시에
저장하지 않습니다.
Compound는 하위 구성을 시작하기 전에 `console: prepare full stack`을 완료하므로 오래된 이행,
백엔드 환경, 변환 결과, 인벤토리 또는 Entra 단계만 실행됩니다. Operator 환경은 브라우저
API 범위에서 JWT 대상을 파생하고 브라우저와 Azure 테넌트 일치를 요구하며, 일치할 수 없는 로컬
자리로 raw-group 대체 경로를 비활성화하고 `SET ROLE fdai_operator`로 연결합니다. Standalone Core
런타임 또는 Operator API debug launch에서는 이 준비 작업을 먼저 실행합니다.
준비 순서에서는 구성된 Entra SPA 등록에 `http://localhost:5273`과
`http://127.0.0.1:5273`을 안전하게 재시도할 수 있는 방식으로 동기화합니다. 보조 로직은 기존
redirect를 보존하고 해당 loopback 호스트에만 HTTP를 허용하며, 활성 테넌트가 다르거나 운영자가
등록을 읽거나 업데이트할 수 없으면 서비스 시작 전에 중단합니다. 로컬 Event Hubs 토큰 새로 고침은
준비된 `AZURE_TENANT_ID`와 `AZURE_SUBSCRIPTION_ID`에 고정되므로 이후 기본값 계정이 바뀌어도
실행 중인 서비스의 Event Hubs 발급자를 바꿀 수 없습니다.
Resolved-model 산출물이 있으면 같은 준비 단계에서 서술기 엔드포인트가 HTTPS 출처인지 검증하고
`FDAI_LLM_ENDPOINT`와 `LLM_RESOLVED_MODELS_PATH`를 비공개 로컬 런타임 환경에 기록합니다.
Narrator 엔드포인트가 없거나 올바르지 않으면 코어 런타임을 시작한 뒤 실패하게 두지 않고 Terraform
또는 Azure 프로바이더에 접근하기 전에 준비 단계를 중단합니다.
선택적인 로컬 configuration-baseline 대화는 ignored 산출물 세 개를 `FDAI_CONFIGURATION_BASELINE_JSON`, `FDAI_CONFIGURATION_BASELINE_DOCX`, `FDAI_CONFIGURATION_OBSERVATION_JSON`으로 연결합니다. Full-stack preparation 이후 Operator API launch에 세 값을 모두 제공합니다. Preparation이 생성된 `.fdai/local-runtime.env`를 교체하므로 해당 파일을 직접 수정하지 않는 것이 좋습니다.
일부 값만 구성하거나 기준선 무결성 또는 DOCX 다이제스트가 일치하지 않으면 Operator API 시작이 중단되며 호출자는 고정된 범위, 버전, 다이제스트 또는 문서를 바꿀 수 없습니다. 연결이 성공하면 로컬 조립은 같은 맥락을 결정론적 채팅과 GET-only 구성 기준선 패널에 등록합니다.
패널은 요청마다 관측 출처를 실행하고 연결 부재를 사용 불가로 보고하며 고정본나 cached Azure 상태를 대체 근거로 사용하지 않습니다. 가능한 경우 캠페인 상태를 PostgreSQL에 연결합니다.
캠페인 개정 번호와 감사 증적은 재시작 후에도 유지됩니다. 영속성이 없으면 검토는 not 구성된이고 in-memory 대체 경로를 사용하지 않으며, pinned 산출물만 활성 변경할 수 없는 레지스트리 항목이 되어 이력이 구성되지 않은 버전을 만들지 않습니다.
배포는 absolute mounted 기준선 JSON/DOCX 경로와 읽기 담당 허용 목록의 `FDAI_CONFIGURATION_BASELINE_RESOURCE_GROUP`을 함께 요구하고 해당 읽기 담당의 Managed Identity와 범위가 제한된 HTTP 클라이언트를 재사용합니다.
신원 누락, 범위 escape, malformed 파일 또는 무결성 mismatch는 시작을 차단하며 성공 시 읽기 근거, 영속 캠페인/보고 상태, independently 검토된 shadow 예약만 추가합니다.
시작 탐색 중 브라우저는 initial 골격을 유지하고 `GET /iam/self`의 fetch-level 네트워크 실패만 약 28초 동안 재시도합니다.
HTTP 응답, authentication 실패, malformed 페이로드 또는 소진된 예약은 기존 access-recovery 표면에 표시합니다.
IAM 초기화가 성공하면 대시보드는 `GET /kpi`를 필수 backbone으로 취급하고 해당 응답이
해석되는 즉시 경로 골격을 종료합니다. 선택 FinOps, promotion-gate 및 자율성 변환 결과는
독립적으로 합류하며 `404`, `501`, `503`이면 사용 불가로 표시하고 전체 대시보드를 실패시키지 않습니다.
모든 브라우저 Operator API 요청에도 구성 가능한 기본 30초 시간 초과를 적용합니다. 정지한 fetch는
abort되고 영구 골격을 남기지 않고 기존 경로 오류 표면으로 전환됩니다.
각 long-running Console 작업은 VS 코드 인스턴스 하나만 허용합니다. Core 작업과 debug launch는
`.fdai/core-runtime.lock`도 공유하므로 두 번째 프로세스는 Kafka 소비자 그룹에 참여하기 전에
실패합니다. 따라서 작업/debug overlap이 중복 Pantheon 소비자와 지속적인 rebalance를 만들지 않습니다.
Core 런타임, Operator API 및 프런트엔드 작업은 각각 별도의 dedicated 최종 그룹을 사용하며 재시작할 때 자신의 이전 출력만 지웁니다. Operator API 시작은 조용히 유지되며 editor focus를 가져가지 않습니다.
VS 코드는 Pantheon 브리지 시작, Uvicorn 애플리케이션 시작 완료 또는
Vite 로컬 주소 게시를 각각 확인한 뒤에만 background 작업을 준비된으로 표시합니다. 따라서 프로세스가
생성되기만 한 상태를 준비된 서비스로 표시하지 않습니다.
표준 로컬 Azure 프로파일은 `FDAI_RUNTIME_LOCK_FILE`이 설정되지 않아도 같은 잠금을 기본값으로 사용하므로, `python -m fdai`를 직접 실행해도 singleton 가드를 우회할 수 없습니다. 운영 런타임은 배포에서 명시적으로 구성한 경우에만 프로세스 잠금을 계속 사용합니다.
Core 런타임만 Pantheon을 소유하며 로컬 및 deployed interactive 읽기는 같은 execution-mode 정책을 사용하고 의도 ID, Heimdall 소유권 또는 계획 연결 표류 시 시작을 차단합니다. Embedded direct Pantheon 채팅 위임은 fixture-only입니다. `FDAI_OPERATOR_API_EMBED_PANTHEON=0`일 때 Operator API는 기존 `fdai.pantheon.objects` 전송 계층의 범위가 제한된 요청/응답 logical 토픽을 통해 Bragi conversational
포트에 접근합니다. 시작 탐색으로 응답 소비자 준비를 확인한 후 트래픽을 받습니다. 클라이언트는 재시도 중 joining 소비자를 재사용하고 최초 Event Hubs 그룹 결합을 최대 20초 허용합니다.
`GET /chat/health`는 semantic bridge worker 준비 상태를 직접 읽으며 영속
`conversation/chat.health` projection row를 요구하지 않습니다. 관련 없는 projection 누락을 접근할 수
없는 모델로 잘못 표시하지 않도록 `starting` 또는 `event-bridge` mode와 함께 HTTP 200을 반환합니다.
운영 복제본은 서버 소비자 그룹을 공유하므로 요청마다 복제본 하나만 응답합니다. Singleton 로컬 코어는 process-scoped 서버 그룹을 사용하므로 재시작할 때 이전 프로세스의 관련 없는 Pantheon 트래픽을 재생하지 않고 physical 토픽의 현재 오프셋에서 시작합니다.
요청은 raw 신원 대신 salted SHA-256 user/세션 참조를 전달하며, 시간 초과 또는 잘못된 응답은 전문가 답변을 꾸미지 않고 명시적인 agent-to-Bragi 인계로 표시합니다. 같은 지연 시간 프로파일은 같은 direct, streamed 또는 detached 모드를 선택하며 측정된 프로바이더 지연 시간과 구성된 근거 가용성만 모드를 바꿀 수 있습니다.
장기 실행 코어 및 Operator API 작업의 최종 출력은 `.fdai/logs/core-runtime.log`와
`.fdai/logs/operator-api.log`에 보존됩니다. 캡처된 모든 child-output 줄은 millisecond와 로컬 표준 시간대
약어를 포함한 Python 로깅 style 시각으로 시작합니다. 예시는 `2026-07-28 15:25:53,717 KST`입니다.
각 로그는 서비스 시작 및 중지 시각과 하위 exit 코드도 기록하고 비공개 로컬 권한을
사용하며, 1 MiB에서 회전하여 이전 세대를 최대 3개 유지합니다. Git에서 제외된 이 진단 로그는 작업
최종이 닫혀도 유지됩니다. 범위가 제한된 터미널 큐는 느린 VS Code 터미널이 완전한 파일 캡처를
막지 않게 하며, 과대 레코드는 구성된 파일 상한에서 명시적 표식과 함께 잘립니다. 이 진단 로그는
구조화된 경고 및 오류 기록인 `warnings.jsonl`을 대체하지 않습니다.
Core 최종은 기계가 읽는 JSON 스트림을 유지하지만, 코어 파일은 Operator API 로그와 같은
`LEVEL: logger: message` 형식으로 기록을 렌더링합니다. 로컬 Operator API는 같은 구조화된 logger를
사용하고 기본값이 `INFO`인 `FDAI_LOG_LEVEL`을 적용합니다. Uvicorn 접근 로그는 비활성화하고,
`aiokafka`, `httpx`, `weasyprint`의 `WARNING` 미만 기록은 억제하지만 FDAI 수명 주기 및 결정
기록은 `INFO`로 유지합니다. Event Hubs 어댑터는 aiokafka의 맥락이 없는 소켓별 authentication
성공 메시지도 억제하고, logical 소비자마다 토픽, 소비자 그룹, 클라이언트 id 및 authentication
방식을 포함한 `event_bus_consumer_started` 기록 하나를 내보냅니다. 의존성 경고와
오류는 계속 표시됩니다. 같은 `WARNING` 이상 aiokafka 실패는 최초 레코드와 주기적
`suppressed_count` 요약을 보존하며 서로 다르게 렌더링된 실패는 분리합니다. 로컬 경고 파일은
전체 파일을 매번 압축하지 않고 각 레코드를 추가하며 시작 시점과 공유 5분 주기에 24시간 보존
구간을 적용합니다. 구조화 레코드는 64 KiB로 제한합니다. 단기 준비 상태 소비자는 그룹 조정기와 소켓을 닫기 전에 fetch
I/O를 취소하고 배출하므로 의도적인 탐색 종료가 전송 계층 실패로 기록되지 않습니다. 시작
모델 지연 시간 탐색은 구성된 모든
reasoning 후보가 지원하는 Azure Responses API output-token 예산을 사용합니다. Core 준비 상태
샘플은 안정적인 `startup-readiness:<probe-id>` 상관관계 id를 사용하고 Operator API 지연 시간 샘플은
안정적인 `operator-api:*:latency-probe` 상관관계 id를 사용하므로 측정된 탐색 사용량이 uncorrelated
트래픽으로 기록되지 않습니다.
로컬 및 deployed 콘솔 모두 에이전트 카드의 Ask 액션에서 새 user-scoped 대화 키를
할당하고 제출 전에 선택한 에이전트를 대화 요약에 저장합니다. 브라우저는 고정된 per-agent
키를 사용해 이전 대화 기록을 묵시적으로 재개하지 않습니다.
Core, Operator API, debugger 및 로컬 작업은 담당 서비스와 shared 계약 SDK 출처 디렉터리를
Python 가져오기 경로의 첫 위치에 둡니다. 따라서 다른 워크트리의 editable-install 메타데이터가 오래된
출처를 시작하거나 independent-service 구현 경계를 넘을 수 없습니다.

### Workspace 맥락 정리

VS 코드 설정은 의존성, 캐시, 생성된 보고, 로컬 상태, 시크릿, Terraform 상태, 임시 출력 및 `.improve/`를 Explorer, 검색, 파일 watching에서 제외합니다.
이 설정은 editor 부하와 워크트리 copy로 인한 Problems 중복을 줄이며, 제외된 경로를 직접 열 수 있고 근거, 신원, 권한 또는 런타임 어댑터에는 영향을 주지 않습니다.
출처, 테스트 및 담당 design doc은 계속 검색할 수 있으며 Terraform 인덱싱은 tracked `.tf` 파일이 있는 모든 디렉터리를 보존합니다.

Workspace는 `terminal.integrated.showExitAlert`도 비활성화합니다. 0이 아닌 프로세스 종료는 터미널 출력과 작업 상태에서 계속 확인할 수 있지만, 사용자가 입력한 셸이 닫힌 뒤 VS Code가 두 번째 토스트를 표시하지 않습니다. 이 설정은 셸 통합, 종료 코드, 작업 실행 또는 백그라운드 서비스 준비 상태를 바꾸지 않습니다.

Pylance 분석은 서비스 소스 루트 5개, 공유 패키지, 독립 패키지로 제공되는 SDK와 벤치마크 소스 및
저장소 유지관리 스크립트를 대상으로 합니다. Workspace 백그라운드 인덱싱은 비활성화합니다. 열린
파일은 IntelliSense와 진단을 계속 제공하며 범위가 제한된 테스트는 테스트 실행기를 통해 사용할
수 있습니다. Pylance는 심볼릭 링크 폴더를 따라가지 않고 언어 서버 메시지는 경고 수준부터
기록합니다. 라이브러리 소스를 사용한 형식 추론을 비활성화해 `light` 모드 없이 분석 작업을
제한합니다. 프로파일 로컬 Node.js 힙 상한은 달성했다고 주장하지 않습니다. Remote WSL machine 설정은
server instance가 공유하며 clean process-command 검사에서 시도한 heap argument가 없었습니다. 구성된 workspace 분석, 열린 파일 진단, IntelliSense 및 탐색 기능은 계속
사용할 수 있습니다. 따라서 검증 워크트리와 연결된 로컬 산출물이 workspace 분석 집합에 중복으로 들어가거나 정보 수준 로그 부하를 추가하지 않습니다. Chat 맥락 사용량 표시기는 계속 활성화하므로 프롬프트 한도 전에 기록된 세션 인수인계를 사용해 긴 작업을 옮길 수 있습니다. Copilot은 선택한 모델의 맥락 창 80%에서 에이전트 대화 이력을 압축해 한도 보호를 유지하면서 고정된 조기 임계값을 피합니다. 다음 편집 제안은 계속 비활성화하며 Chat, 인라인 완성, 맥락 사용량 및 세션 기록은 그대로 사용할 수 있습니다.

Workspace는 정본 `.github/copilot-instructions.md` 진입점과 저장소의 `.github/hooks`
디렉터리를 사용합니다. FDAI에서는 중첩 `AGENTS.md` 탐색과 사용자 수준 Claude 또는 Copilot
hook 디렉터리를 비활성화하므로 같은 지침이나 도구 hook이 여러 탐색 경로를 통해 한 요청에
중복으로 들어가지 않습니다. 백그라운드 원격 동기화는 전용 `git: auto-pull` 작업이 소유하며,
이 workspace에서는 VS 코드 기본 autofetch를 비활성화합니다.

Workspace는 `.github/workflows/deploy-dev.yml` 하나만 plain YAML 언어 모드에 연결합니다.
GitHub Actions 확장은 참조한 액션 tag가 존재하고 다음 단계에서 `GITHUB_ENV` 값을 사용할 수
있는 경우에도 이 작업 흐름에 unresolved-action 및 dynamic 맥락 오류를 표시할 수 있습니다. Plain
YAML 검증은 계속 활성 상태입니다. 원격 action-tag 확인, 저장소 작업 흐름 계약 테스트 및
GitHub Actions 런타임 검증이 권위 있으며 다른 작업 흐름의 GitHub Actions 언어 support는
유지됩니다.

Workspace 설정에는 resource scope Pylance 제어만 둡니다. Shared Remote WSL server는 프로파일별로
격리할 수 없으므로 machine scope Node.js 설정은 두지 않습니다. 프로파일은
HashiCorp Terraform만 언어 서버로 유지하며 워크스테이션별 정리로 축소하지 않습니다. 현재 작업에
쓰지 않는 프로파일 외부 확장은 로컬에서 제거할 수 있습니다. WSL 초기화는 프로파일 sync가
전달하지 못하는 path-free 머신 설정을 적용합니다. 이러한 editor
설정은 신원, 근거, 런타임, 승격 또는 실행 권한을 선택하지 않습니다.

선택적 `dev-access: configure VPN on folder open` 작업은 workstation에 격리된 P2S 개발 접근
stack의 로컬 상태가 있을 때만 활성화됩니다. VPN이 연결되어 있으면 FDAI 런타임 리소스를
변경하지 않고 transient WSL 해석기 연결을 복구합니다. VPN 연결이 끊겨 있으면 Azure VPN
Client를 한 번 열고 범위가 제한된 7초 유예 시간 동안 mirrored WSL 경로를 8번 확인합니다. Direct
경로가 나타나면 DNS를 적용하고 성공하며, 계속 indirect이면 Problems 패널 오류를 보고합니다.
개발자는 Entra sign-in 및 MFA를 계속 완료합니다. 로컬 dev-access 상태가 없는 workstation에는
프롬프트나 네트워크 변경이 발생하지 않습니다.

### 로컬 개발의 Console 데이터

데이터 소스 선언, 로컬 인증, 워크로드 근거 및 인벤토리 조회 계약은
[Console 읽기 경계](console-read-boundary-ko.md)가 소유합니다. 이 동등성 문서는 아래의 나머지
로컬/배포 런타임 바인딩을 유지합니다.

런타임 policies는 배포와 로컬 PostgreSQL이 구성된 경우 동일한 StateStore 기록을
사용합니다. 영속 로컬 상태가 없으면 출처 매니페스트는 영속성을 주장하지 않고 settings
저장소를 사용 불가 또는 non-durable로 표시합니다. 읽기 담당은 정제된 환경, 영속 재정의 및
effective 값 변환 결과를 확인합니다. Owner는 optimistic 개정 번호 및 원자적 감사 검사를 통해
허용 목록만 업데이트할 수 있습니다. IRP 변경은 다음 조건을 충족한 경보에 적용되고 analyzer, 인벤토리 및
보존 cadence 변경은 다음 작업 또는 틱에 적용됩니다. 로깅 수준과 사례 보존/deletion 일
변경은 재시작 필수로 표시되며 headless 런타임이 시작될 때 로드됩니다. 어떤 설정도 로컬 읽기
API에 실행기 신원을 부여하거나 ActionType 및 작업 흐름 승격 상태를 변경하지 않습니다.

인시던트 auto-open 활성화, 최소 심각도, repeat 임계값 및 repeat 구간도 startup-bound입니다.
Headless 런타임은 영속 effective 값을 로드합니다. Embedded 로컬 Pantheon은 별도의 fixed 심각도나
구간 대신 동일하게 검증된 환경, 기본값 및 accepted-versus-held 인계 결과를 사용합니다.

Detection 준비 상태도 같은 경계를 사용합니다. 배포는 항상 PostgreSQL에서 Muninn
StateSnapshot을 읽습니다. Interactive 로컬은 로컬 PostgreSQL이 구성된 경우에만
`/detection-readiness`를 등록하며, 그렇지 않으면 경로와 출처 매니페스트가 사용 불가를
보고합니다. 로컬 브라우저는 Azure CLI 인벤토리로 대체하거나 Heimdall 판정을 다시 계산하지
않습니다.

Standard full-stack launch는 서술기 엔드포인트 조정을 유지합니다. 독립 Operator 서비스는
`RUNTIME_ENV=dev`에서만 local-only 서술기 어댑터를 연결하고 `LLM_RESOLVED_MODELS_PATH`와 수명이 짧은
Azure CLI 토큰을 사용하며 Core 가져오기 또는 실행기 권한 없이 Azure OpenAI 서술기를 시도합니다.
Health는 엔드포인트를 민감정보 제거하고 모델 지식만 쓴 답변은 검증되지 않은으로 유지합니다. 시작 훅은 권한이
있을 때 현재 공개 IP를 허용 목록할 수 있습니다. Automated 테스트는
`FDAI_NARRATOR_AUTO_OPEN_AOAI=0`을 설정하며 모델이 미구성, 승인되지 않은 또는 unreachable이면 해당
턴만 결정론적 answerer로 안전하게 대체 경로합니다.
Full-stack 준비는 명시적 재정의, 검증된 `.fdai/resolved-models-vision.json`, repository-local `resolved-models.json` 순서로 `LLM_MODE=azure`와 `LLM_RESOLVED_MODELS_PATH`를 만들고 metering을 read-model PostgreSQL에 연결합니다. Vision 산출물은 연결 가능한 T1 임베딩과 연결 가능한 기본/보조 T2 쌍 또는 명시적인 top-level `hil-only` 모드라는 코어 조립 하한도 충족할 때만 사용할 수 있습니다. 호환되지 않는 vision 산출물은 준비가 성공했다고 보고한 뒤 Core 런타임을 중지시키는 대신 정본 산출물로 대체 경로합니다. LLM 비용 패널과 `query_llm_usage` 채팅 기능은 로컬 및 deployed 프로파일에서 이 measured 읽기 담당을 공유합니다. 비용은 명시적
deployment-to-family 연결만 사용하며 누락된 계열은 unpriced 상태로 둡니다. 대화
Assurance는 배포와 같은 로컬 대화 및 평가 저장소를 사용하고 결정론적 최종
검사를 항상 실행합니다. 의미 검토는 서로 다른 resolved 모델 계열이 둘 이상일 때만
활성화되며 narrator-only 또는 `hil-only` 보조는 단일 모델 대신 inconclusive를 유지합니다.
산출물이 없으면 모델 및 assurance inference는 사용 불가이며 고정본으로 대체하지 않습니다.
PostgreSQL StateStore가 구성되면 두 프로파일은 ontology-owned failed-answer 귀속을 shadow
감사 기록이 있는 멱등적 hold-first adequacy 검토로 저장합니다. 영속 상태가 없는
interactive 로컬은 선택적 검토 싱크를 사용 불가로 유지합니다. 어느 프로파일도 이 intake
경로에서 재생을 수행하거나 제안을 만들거나 검토를 promote하지 않습니다.

`FDAI_MONITOR_WORKSPACE_ID`가 설정되면 명시적 Command Deck `query_log` 명령은 두 프로파일에서
같은 범위가 제한된 Azure Monitor Logs 프로바이더를 사용합니다. Interactive 로컬은 현재 Azure CLI
맥락에서 데이터 평면 토큰을 얻고 배포는 `FDAI_MI_CLIENT_ID`가 선택한 전용 Operator API
managed 신원을 사용합니다. Workspace는 서버 구성으로 정하며 브라우저가 변경할 수 없습니다.
Workspace, 신원, 권한 또는 텔레메트리를 사용할 수 없으면 고정본나 모델 대체 경로 없이
사용 불가로 보류합니다.
로컬 준비는 applied Terraform의 `log_workspace_customer_id` 출력에서 workspace customer GUID를 읽습니다. 이전 상태 또는 targeted 상태가 해당 출력을 노출하지 않으면 applied 리소스 그룹 안의 workspace만 나열하고 정확히 하나가 있을 때만 대체 경로를 수락합니다. Workspace가 0개이면 프로바이더를 사용 불가로 유지하고 여러 개이면 암시적으로 하나를 선택하지 않고 준비를 중지합니다. 재생성할 때 stale 로컬 workspace id는 제거합니다.
로컬 런타임 환경 generator는 applied 구독 및 리소스 그룹도 범위가 제한된 Azure
read-investigation 어댑터에 제공합니다. Terraform이 선택적 개발 operations 게이트웨이 URL과
Easy Auth 대상을 모두 출력하면 NSG 및 VNet 피어링 질문은 로컬 Azure CLI 신원으로 게이트웨이의
등록된 읽기 연산만 호출합니다. 쌍이 없으면 래퍼를 비활성화하고 구성된 게이트웨이가
실패하면 direct ARM 대체 경로 없이 사용 불가를 보고합니다. 게이트웨이는 읽기 담당/실행기 managed
신원을 분리하며 로컬 Operator API에 실행 신원을 제공하지 않습니다. 변경은 target-scoped
Blob 임차 기간과 영속 멱등성 점유를 사용하며 업스트림 Terraform은 구성된 실행기
principal에 development-only 변경 연산을 활성화하고 게이트웨이 URL과 대상은 headless 코어
Container App에만 전달합니다. 해당 런타임은 `AzureGatewayDirectApiExecutor`를 연결하며 Operator API는
읽기 전용 게이트웨이 전송 계층을 유지하고 강제 적용 기능을 받지 않습니다. 실행기는 정확한 등록된
연산, arguments, 멱등성, 감사, stop-condition, 롤백 및 영향 근거에 대해
server-issued 예행 실행 증적을 먼저 요청해야 합니다. 게이트웨이는 범위가 제한된 reader-identity ARM GET으로
대상을 확인하고 해당 증적을 비공개 Blob 저장소에 5분 동안 저장한 다음 target-scoped 리소스
임차 기간을 획득하여 ARM을 호출하기 전에 ETag compare-and-swap으로 한 번만 소비합니다. 호출자가
주장한 증적, 변경된 페이로드, 만료되거나 재생된 증적은 변경 전에 실패합니다. ARM
long-running 연산은 `submitted` 상태로 유지되며
실행기만 원래 멱등성 키를 통해 서버가 소유한 상태 URL을 조회할 수 있습니다.
Stale pending 점유는 계속 차단된 상태로 남지 않고 범위가 제한된 시간 초과 이후 ETag compare-and-swap으로
복구됩니다.
동일한 계획을 반복하면 소비되지 않은 같은 증적을 반환합니다. 소비되거나 만료된 계획은 새
멱등성 키가 필요합니다. ARM throttling은 최대 3회까지 범위가 제한된 `Retry-After`를 따르며 변경
`5xx` 응답은 결과가 모호한할 수 있으므로 자동으로 반복하지 않습니다.

동일한 read-investigation 배선이 범위가 제한된 Azure subscription-health 프로바이더를 구성합니다. 기본값은 resource-group 허용 목록이며, interactive 로컬은 권위 있는 인벤토리가 전체 구독을 이미 읽으므로 서버가 소유한 `subscription` 모드와 1,000개 리소스 상한을 선택하고 배포는 적절한 범위의 읽기 담당 신원으로 의도적으로 연결하지 않으면 `resource_groups`를 유지합니다.
브라우저와 모델 입력은 모드를 변경할 수 없습니다. 로컬 factory는 read-investigation 배선이 있을 때만
프로바이더를 주입하여 읽기 전용 data-plane 경계를 유지합니다.

Direct Command Deck 읽기도 두 프로파일에서 동일한 owner-scoped run-ledger 실행기를 사용합니다.
Interactive 로컬은 구성된 로컬 PostgreSQL 데이터베이스에 연결하고 배포는 Azure PostgreSQL에
연결합니다. 두 프로파일 모두 정본 요청 다이제스트, 임차 기간, 사용량 및 최종 결과를 저장하므로
completed 재시도는 프로바이더를 다시 호출하지 않고 재생됩니다. 브라우저 입력은 원장 소유자를
선택하거나 Azure 범위를 넓히거나 서버가 소유한 읽기 담당 자격 증명을 바꿀 수 없습니다.

두 프로파일은 범위가 제한된 PostgreSQL 타입 지도와 `InventoryQuery` 검증기를 공유합니다. Interactive 로컬은
Azure CLI 그래프와 읽기 담당 토큰으로 현재 상태 및 범위가 제한된 Activity Log를 읽고 배포는
promoted PostgreSQL 인벤토리와 전용 읽기 담당 managed 신원을 사용합니다. 두 프로파일 모두 조립에서
구독/resource-group 범위를 고정하고 후속 조치 선택자를 다시 해석하며 동일한 30일 활동
로그 규칙을 적용합니다. 브라우저/모델 입력은 범위를 넓힐 수 없고 이력 근거가 없거나 일치하지
않으면 스냅샷 inference로 대체 경로하지 않고 사용 불가 상태를 유지합니다.

로컬 factory는 15개 에이전트를 기본으로 모두 시작합니다. `FDAI_START_PANTHEON`은 disable-only
컨트롤입니다. 값이 없으면 활성화하고 `0`, `false`, `no`, `off`만 런타임을 비활성화합니다.
Event Hubs가 설정되면 에이전트는 전용 로컬 소비자 그룹으로 Azure 전송 계층을 사용합니다.
설정되지 않으면 로컬 프로세스 내 EventBus가 실제 Pantheon 메시지를 전달하고 에이전트 SSE 스냅샷을
제공합니다. 이 어댑터는 Azure 근거, 영속 상태 또는 실행 권한을 만들지 않습니다.
Kafka가 구성된 토픽을 시작 중 거부하면 Event Hubs 어댑터는 오류를 전달하기 전에 실패한 소비자를 닫습니다.

예측 learning은 두 프로파일에서 동일한 PostgreSQL 에피소드 저장소와 Heimdall 핸들러를
사용합니다. `FDAI_FORECAST_TARGETS_JSON`이 설정된 경우에만 활성화됩니다. 배포는 명시적 선택
Container Apps 작업으로 raw 틱을 제공하고 로컬 개발은 synthetic 메트릭을 만들거나
콘솔에 쓰기 경로를 주지 않고 동일한 기계적 틱 CLI를 호출할 수 있습니다.

로컬 런타임 환경 generator는 applied Terraform 출력에서 기한이 제한된 영속 재생에 사용하는
semantic logical/physical topic을 포함한 전송 계층 설정을 읽습니다. Terraform 실행기 신원의 구독과
Azure CLI 구독을 비교하고 둘이 다르면 리소스 조회나 파일 생성 전에 중단합니다. 두 프로파일은 명시적으로 타입이 지정된 동일한 semantic JSONB claim 및 변환 결과 statement를 실행합니다.
또한 로컬 user와 호스트에서 식별 정보를 노출하지 않는 소비자 인스턴스 해시를 파생하므로 동시에
실행하는 개발자가 같은 Event Hubs Kafka 소비자 그룹에 참여하지 않습니다. 자동화에서
명시적으로 안정된 이름이 필요하면 `FDAI_LOCAL_CONSUMER_INSTANCE`에 최대 20자의 lowercase
alphanumeric 및 hyphen 식별자를 설정할 수 있습니다. 생성된 코어, Pantheon 및 Operator 요청
그룹은 이 인스턴스를 사용하고 deployed Operator 요청 그룹은 런타임 hostname을 사용합니다.
Live 및 Agent 관찰에는 서로 다른 프로세스 내부 재생 규칙이 적용됩니다. 일반 Live 단계 hub는
구독 이후 이벤트만 전달합니다. Agent hub는 agent별로 검증된 최신 `agent.state` 이벤트 하나를
보존하고 새 구독자를 같은 잠금 안에서 등록하면서 이 값들을 초기값으로 제공합니다. 범위가 제한된
이 프로세스 내부 스냅샷은 polling 없이 새로 고침을 초기화하지만 영속 이력 재생은 아니며 Operator
프로세스가 다시 시작되면 사라집니다. 각 hub가 전체 `fdai.pipeline.stages` 스트림을 consume하려면
독립적으로 실행되는 Operator 프로세스 또는 복제본마다 `FDAI_LIVE_STAGE_CONSUMER_GROUP_ID`가
계속 고유해야 합니다. 기본값은 단일 프로세스 호환성만 유지합니다. 격리된 E2E launcher는 상속된
값을 항상 UUID 범위 그룹으로 교체하며 브라우저에 서비스를 제공하는 Operator가 사용하는 그룹에
참여하지 않습니다.

작업 흐름 정의는 배포 강제 적용 허용 목록을 사용하며 ActionType은 승격 및 risk 게이트를 유지합니다.
강제 적용에는 Azure 이벤트 전송 계층과 작업 흐름 승인 근거를 공유하는 영속 데이터베이스가 필요합니다.
두 프로파일은 영속 프로세스 상태에서 본문 없는 재개, safe 취소, effect-free 재시도를 제공합니다.
App 역할 및 허용 목록을 다시 검사하고 시도 상한을 공유하며 unsafe 재시도 또는 취소를 차단합니다.
Thor는 developer 자격 증명을 받지 않으며 실행은 deployed Managed Identity 런타임에 남습니다.
시나리오 재생, recording 실행기, VM-task 가짜, synthetic 데이터 및 범위 고정본은 pytest 전용입니다.
명시적 pytest 고정본 빌더는 synthetic 인벤토리 그래프를 연결하고 Azure 인벤토리 예열 또는
종료 수명 주기를 등록하지 않습니다. Interactive 로컬 조립은 항상 실제 운영 Azure 프로바이더를 유지합니다.

FDAI Azure PostgreSQL, Event Hubs, 런타임, 실행기 리소스가 없으면 해당 표면은 런타임
점유 없이 사용 불가 또는 빈으로 표시됩니다. 저장소 카탈로그와 스키마는 관찰된 런타임
근거가 아니라 configuration-as-code이므로 계속 표시합니다.
로컬 및 deployed Operator API factory는 룰의 `Controls` 참조 화면을 위해 동일한 검증된
Best Practice 정의를 로드합니다. 이 동등성은 런타임 점유를 만들지 않습니다. 권위 있는
근거 프로바이더가 없으면 두 factory 모두 모든 컨트롤과 요구사항을 `Unknown`, 출처는
`not_connected`로 노출합니다.
두 factory는 같은 온톨로지 release에 읽기 전용 카탈로그 조회 함수도 등록하므로 로컬 및 deployed
Command Deck 턴은 동일한 타입이 지정된, 범위가 제한된, non-mutating 근거 계약을 사용합니다.

로컬 API는 `GET /system/data-sources`를 제공합니다. Standard full stack에서는 운영
PostgreSQL read-model 어댑터가 로컬 pgvector를 사용합니다. 로컬 Operator API는 트래픽을 받기 전에
해당 어댑터를 통해 범위가 제한된 `SELECT 1`을 실행합니다. 탐색이 실패하면 부분적으로 연결된 콘솔을
노출하지 않고 시작을 중단합니다. 탐색이 성공하면 PostgreSQL 기반 항목은 `available` 및
`reachable=true`를 보고합니다. 구성된 원격 및 Azure request-time 출처는 자체 근거
계약이 검증할 때까지 `unknown`을 유지합니다.
`FDAI_DATABASE_URL`과 `FDAI_AUTHORITATIVE_OPERATOR_API_BASE_URL`은 상호배타적인 출처 프로파일을
선택합니다. 둘을 함께 구성하면 프로바이더를 만들기 전에 시작을 중단하므로 매니페스트가 로컬
PostgreSQL을 설명하면서 허용 목록 요청을 원격 API가 처리하는 상태를 허용하지 않습니다.
원격 forwarding은 decoded 정본 허용 목록에 있는 경로만 일치시키며 정규화된, encoded, 중복
구분자 및 control-character 변형은 로컬에 유지합니다. 업스트림 캐시 directive를 폐기하고
모든 proxy 응답에 `Cache-Control: no-store`를 보내므로 인증된 operational 근거가 브라우저
또는 shared 캐시에 저장되지 않습니다. 응답 헤더 전에 발생한 원격 실패는 범위가 제한된 JSON
`503`으로 변환하고, 헤더 이후 실패는 두 번째 ASGI 응답 시작 없이 응답 본문을 닫습니다.

런타임 스킬 점검도 같은 규칙을 따릅니다. 운영은 트래픽을 받기 전에 signed
PostgreSQL trusted-artifact 기록에서 활성화된 카탈로그를 재구성합니다. Interactive 로컬은 영속
검증된 저장소가 명시적으로 compose되지 않으면 빈 실패 시 차단 스냅샷으로 같은 Reader-gated
`/skills` 계약과 서술기 동사를 노출하며 installed 스킬이나 부하 결과를 만들지 않습니다.

에이전트 활동은 실제 운영 런타임 프레임과 영속 원본 변환 결과를 분리합니다. 로컬 및 배포
프로파일은 모두 `/agents/stream`을 적용하기 전에 `GET /agents/activity`를 불러오며 검사 또는 읽기
이력을 액션 감사 체인에 복사하지 않습니다. 관찰된 에이전트를 선택하면 감사 이벤트를 추론하지 않고
실제 운영 상태, 현재 작업, 런타임 연결, 상태 시각, 스트림 출처 이력 및 인시던트 맥락을 표시합니다.
Headless Pantheon은 control-loop 진행 상황을 전달하는 동일한 `fdai.pipeline.stages` 전송 계층에 실제
상태에서 파생한 `agent.runtime-state` 프레임을 발행합니다. Operator API는 runtime-state 프레임과 단계
프레임을 구분하고 소비자가 실제 운영이며 상태 탐색이 오류가 아닌 에이전트만 전달합니다. Interactive
로컬과 배포는 같은 프로세스 간 경로를 사용하며 로컬 프로파일은 에이전트 activation이나 스트림
의미가 아니라 PostgreSQL 연결만 바꿉니다.
브라우저는 해당 탭이 열려 있는 동안 최근 100개 SSE 프레임도 보존하고 별도 실제 운영 저널로
표시합니다. 런타임 하트비트는 연결을 증명하지만 작업으로 계산하지 않습니다. Collecting,
analyzing, deciding, executing, approving, auditing, 인시던트 및 인계 프레임은 작업으로 계산합니다.
이 저널은 범위가 제한된 및 non-durable이며 reload 시 초기화되고 각 프레임에 기록된 출처를
보존합니다. 추가 전용 감사 로그를 대체하지 않습니다.

완료된 대화 검토도 같은 분리를 따릅니다. Interactive 로컬 전송 계층은 범위가 제한된 Bragi
`object.turn` 묶음을 발행할 수 있지만 검토자나 영속 제안 저장소를 만들어 내지
않습니다. Deployed headless 런타임은 결정론적 ineligible/지원하지 않는 사유를 기록하고 서로 다른
두 모델 계열이 해석된 경우에만 Azure 검토자를 사용합니다. PostgreSQL은 restart-safe 검토
및 초안 상태를 보관하며 운영 Operator API는 프로세스 기억을 공유하거나 승인 엔드포인트를
추가하지 않고 해당 행을 변환 결과합니다.

Approval 결정 전달도 재시작 전후에 같은 형태를 유지합니다. 운영은 서명된 A1
결정을 게시하기 전에 PostgreSQL에 기록하고 전달 시도를 체크포인트하며 시작 및 주기적
루프에서 적격한 미전달 증적을 배출합니다. 최종 delivered 또는 abandoned 증적은 이전
상태로 돌아가지 않으며 종료는 이벤트 전송 계층을 닫기 전에 복구를 중지합니다. 배포는
`FDAI_HIL_DECISION_RECOVERY_INTERVAL_SECONDS`,
`FDAI_HIL_DECISION_PUBLISH_TIMEOUT_SECONDS`,
`FDAI_HIL_DECISION_MAX_DELIVERY_ATTEMPTS`로 간격, publish 시간 초과, 전체 시도 상한을
조정할 수 있습니다. 테스트는 in-memory 저장소 및 발행기와 같은 레지스트리 계약을 사용합니다.
Interactive 로컬은 승인자를 만들어 내거나 signed 콜백 auth를 우회하지 않습니다.

Headless Bragi 의미 라우팅은 T1과 같은 한계 임베딩 기능을 사용합니다. 배포는
`FDAI_AGENT_SEMANTIC_COSINE_THRESHOLD`, `FDAI_AGENT_SEMANTIC_MARGIN_THRESHOLD`를 설정할 수 있으며
잘못된 값은 시작을 실패시킵니다. 임베딩 연결이 없으면 명시적, read-intent, 도메인
라우팅을 결정론적하게 유지합니다. 임베딩은 conversational 대체 경로이며 타입이 지정된 액션
트래픽에 들어가지 않습니다.

의미 질의 계획은 모든 실행 장소에서 같은 tier 계약을 따릅니다. Core는 해석된 narrator 또는
`t1.judge` 후보를 최초 frame 및 plan 제안에 사용합니다. T1 제안을 사용할 수 없거나 결정론적
검증을 통과하지 못한 경우에만 별도로 해석된 T2 reasoner로 실패한 단계를 한 번 다시 시도할 수
있습니다. 유효한 명확화, 범위 거부 또는 근거 보류는 모델 tier를 바꾸지 않습니다. T1 용량이
없으면 의미 계획을 사용할 수 없으며 T2부터 시작하지 않습니다.

### Azure-backed 통합

| 서브시스템 | 상태 | 갭 |
|-----------|------|-----|
| 권한 인식 Azure 관측 | 로컬과 배포는 같은 등록 출처 카탈로그, 실행 조건 게이트, 범위가 제한된 프로바이더 probe, PostgreSQL 결과 상태 및 Agent Activity 계약을 사용합니다. | 같은 카탈로그 digest와 출처 결과를 입증하는 통제된 로컬 및 배포 실행 전까지 런타임 검증은 열려 있습니다. |
| Azure Monitor Logs KQL | 운영과 로컬 어댑터가 `AzureLogAnalyticsQueryProvider`를 공유합니다. | 서버가 소유한 `FDAI_MONITOR_WORKSPACE_ID`가 필요하며 명시적 `query_log`는 사용 불가일 때 실패 시 차단합니다. |
| Managed Identity 토큰 (`WorkloadIdentity`) | Deployed 어댑터 존재 | interactive 로컬은 deployed 실행기로 publish하며 고정본 테스트만 로컬 발급자 사용 |
| 통제된 실행 백엔드 | 프로바이더 중립적인 프로토콜, 프로파일 레지스트리, 영속 PostgreSQL 원장, bubblewrap/VM 어댑터, Azure Container Apps 작업 어댑터가 존재합니다. | 프로파일은 기본적으로 비활성화된이고 로컬 interactive에는 실행기 연결이 없으며 승격 전에 실제 운영 Azure 작업 근거가 필요합니다. |
| 브라우저 근거 | 프로바이더 중립적인 계약, 선택적 Playwright 어댑터, PostgreSQL 산출물, GET-only 점검이 존재합니다. | 기본 unbound이며 interactive 로컬에는 실행기 신원이 없습니다. Isolated restricted-egress 브라우저 런타임과 exact 출처 정책을 구성하기 전에는 사용 불가로 표시합니다. |
| Key Vault 시크릿 프로바이더 (`SecretProvider`) | 배포가 Key Vault 참조 주입 | interactive 어댑터는 환경 참조 사용, 고정본 값은 테스트 전용 |
| GitOps PR 발행기 | 실제 GitHub 어댑터 존재 | interactive 실행은 구성된 어댑터 사용, recording 발행기는 테스트 전용 |
[권한 인식 관측 캠페인](../operations/observation-campaign-ko.md)은 인벤토리, Activity Log,
Resource 및 Service Health, 메트릭, Log Analytics, 게스트 로그, 네트워크, 비용 및 복구 출처의
주기 커버리지 검사를 조정합니다. 권위 있는 인벤토리 CLI가 전체 조정을 소유합니다. Full-stack
로컬과 배포는 같은 출처 카탈로그와 실행 조건을 확인하는 CLI를 실행합니다. 로컬 PostgreSQL과
승인된 로컬 읽기 자격 증명은 managed 배포 연결을 대체하지만 예약, 커서, 정규화 또는 근거
의미론을 바꾸지 않습니다. Operator API는 승격된 PostgreSQL 상태를 읽으며 프로세스 내부
인벤토리 또는 로그 새로 고침을 소유하지 않습니다.
로컬 그래프 기본값은 500개 리소스와 synthetic 구독 루트입니다. 더 큰 인벤토리는 완전한
커버리지를 조용히 주장하지 않고 `truncated=true`를 설정합니다.
로컬 변환 결과는 링크 타입이 등록되어 있고 두 엔드포인트 id가 모두 선택되며 엔드포인트 타입이 리소스
기록과 일치할 때만 discovered 관계를 보존합니다. 이미 변환 결과된 관계와 엔드포인트
타입까지 정확히 같은 중복은 멱등적 no-op으로 처리합니다. 알 수 없음, mismatched, dangling, self,
conflicting 중복 및 over-limit 링크는 count-only 경고와 함께 폐기합니다. 완전한 리소스
스냅샷은 유지되고 `truncated=true`를 보고합니다.
Resource Graph CLI 확장 또는 ARG 요청을 사용할 수 없으면 로컬 발견은 코어
`az resource list`로 대체 경로합니다. 이 대체 경로는 등록된 리소스 커버리지를 보존하지만 해당
명령이 모든 타입의 관계 속성을 반환하지 않으므로 부분 그래프를 보고할 수 있습니다.

## 동등성 컨트랙트 (MUST)

out-of-process 의존을 건드리는 모든 경계는 다음을 갖춰야:

1. **`shared/providers/` 의 프로토콜** - 중립 wire 계약. `core/` 는 프로토콜만 가져오기.
   `EventBus`, `StateStore`, `SecretProvider`, `WorkloadIdentity`, `Inventory` 및 LLM 경계
   (`EmbeddingModel`, `CrossCheckModel`, `VerifierPolicy`, `GroundingSource`) 이미 준수.
2. **테스트 가짜 구현** - 결정론적, 프로세스 내, secret-free입니다. 자동화 테스트 또는
  committed mock/예시 앱이 명시적 고정본 빌더로만 선택하며 interactive 로컬
  Console은 사용하지 않습니다.
3. **런타임 어댑터** - interactive 프로파일은 전송 계층 및 SSE에 범위가 제한된 로컬 어댑터를 사용할
  수 있습니다. Azure 어댑터는 `delivery/azure/` 하위에 두며 `core/`에는 두지 않습니다.
  어댑터 선택은 Pantheon을 활성화하거나 비활성화하지 않습니다.
4. **Mismatch 시 fail-fast 또는 사용 불가** - interactive/deployed 런타임은 테스트 가짜로
  대체 경로하지 않습니다. 필수 시작 출처는 시작을 실패시키고 선택적 읽기 패널은
  사용 불가로 표시합니다. 조용한 대체 경로는 **금지**
   ([llm-strategy.md § 초기화 Provisioner](../architecture/llm-strategy-ko.md#bootstrap-provisioner) 의
   "no HIL-silent 대체 경로" 룰과 일치).

파이프라인을 exercise하는 모든 테스트는 (1)+(2) 모드로 실행 → CI 동등성 게이트가 Azure 토큰
필요 없음.

자동화 액션 테스트는 에이전트 실행이 예상 최종 상태에 도달할 때까지 기다립니다. 관측된
`verdicted` 같은 intermediate 상태를 완료로 취급하지 않습니다. CI는 서술기 엔드포인트
auto-open도 비활성화하므로 결정론적 동등성 테스트가 Azure CLI를 호출하거나 firewall 룰을
변경하지 않습니다.

실행 백엔드 동등성도 같은 규칙을 따릅니다. 자동화 테스트는 in-memory 원장과 mock HTTP
전송 계층을 연결할 수 있습니다. Interactive 로컬은 비활성화된 프로파일을 shadow 상태 또는 계획
탐색으로 inspect할 수 있지만 작업을 제출하거나 Thor 신원을 받지 않습니다. 배포는 같은
프로바이더 중립적인 조정기를 PostgreSQL 및 injected 실행기 `WorkloadIdentity`에 연결하며 Azure
어댑터는 `delivery/azure/` 아래에 유지합니다.
[거버넌스 적용 실행 백엔드](../interfaces/execution-backends-ko.md)를 참조하세요.

## 배포자-스코프 LLM 프로비저닝

Cognitive deployment를 변경할 수 있는 보호된 전체 계획은 해석기를 실행하고 적용할 정확한 매니페스트를 봉인합니다. 개발 게이트웨이 대상 계획도 기존 모델 계정, 호출자 RBAC 및 수집
종속성을 보존하도록 현재 기능 맵을 해석합니다. 대상 집합에 cognitive deployment가 없으므로 완결성 결과는 차단하지 않습니다.

![배포자-스코프 LLM 프로비저닝. 주요 단계는 [terraform apply\], az account show / + 배포자 principal 해결, Bootstrap audit entry: / deployer_object_id, sub, region, rule-catalog/llm-registry.yaml 읽기, Azure 카탈로그 조회: / var.region 에서 / 사용가능한 Foundry / AOAI SKU, 배포자가 / Cognitive Services Contributor / 대상 subscription에 있음?, 경고 emit: / LLM 프로비저닝 스킵 / T2 capability = HIL-only, preferred family 사용가능 / AND 배포자 sub 쿼터 있음?, 이 capability HIL-only 마킹 / 나머지는 계속, deployment 프로비저닝 / cap_tpm 은 registry에서, mixed-model 불변식: / primary.publisher != secondary.publisher?, 명확한 에러로 abort / (fork가 preference 확장)입니다.](../../diagrams/generated/fdai-roadmap-deployment-dev-and-deploy-parity-01.ko.svg)

**배포자 권한 게이트** (해석기가 카탈로그 건드리기 전 확인):

| 체크 | 실패 모드 | 후속조치 |
|------|---------|--------|
| `az account show` 가 로그인된 principal 반환 | abort - 배포자가 `az login` 필요 | 한 줄 진단 |
| principal이 대상 구독에 `Cognitive Services Contributor` (또는 `Owner`) 보유 | LLM 프로비저닝 스킵, 모든 `t2.*` 및 `t1.judge` 기능을 `hil-only` 로, 경고 발행 | 포크가 역할 부여 후 재실행 |
| 리전이 각 기능 선호 설정 중 최소 하나 계열 노출 | 해당 기능만 `hil-only` 마킹, 경고 | 포크가 `llm-registry.yaml` 선호 설정 확장 후 재실행 |
| 배포자 구독이 요청한 `capacity_tpm` 쿼터 보유 | 요청의 ≥ 20% 이상 큰 최대 사용가능 용량으로 축소; 미만이면 거부 | 포크가 쿼터 증가 요청 |
| Mixed-model 불변식 (`t2.reasoner.primary.publisher != t2.reasoner.secondary.publisher`) 해석 후 만족 | **abort** - quality 게이트 통과 못하는 T2 계층 부분 배포 안 함 | 포크가 선호 설정 조정 |

해석기 결과 산출물은 배포자 `object_id`, 구독, 리전, resolved 기능 지도와 사유를 포함합니다. 동일 레지스트리 + 카탈로그 + 권한 + 할당량 입력은 동일 JSON을 산출합니다.
감사 저장소 덧붙이기는 해석기 호출자가 소유합니다.

## 작업 계획 (phased, 가산)

각 단계는 헤드에서 빌드/테스트 가능한 상태 유지. 멀티 클라우드는 **TBD**
([copilot-instructions § 구현 Focus](../../../.github/copilot-instructions.md#implementation-focus-must)).

**2026-07-21 기준 상태**: W-A에서 W-G까지 **배포됨**; W-H (문서 동기화)는
이 문서 초안과 함께 배포된 상태; W-I (매주 조정기 작업)는 연기. 각 작업 항목은
실제 럭딩된 범위(코드, 테스트, 게이트 커버리지)를 반영.

### W-A: LLM용 구성 스키마 + dev-mode 플래그 ✅  *(기준선, 배포)*

- `services/core-control-plane/src/fdai/shared/config/schema.json` + `models.py` 에 `LlmConfig` 추가:
  - `mode`: `local-fake` | `azure`. `local-fake`는 명시적 테스트/mock 연결이며 배포
    환경이 선택하지 않습니다.
  - `resolved_models_path`: 옵셔널 KV 시크릿 이름 또는 파일시스템 경로.
  - `capabilities`: 기능 이름 리스트 (`t1.embedding`, `t1.judge`,
    `t2.reasoner.primary`, `t2.reasoner.secondary`) - 레지스트리를 미러.
  - `t2_primary_latency_routing`: bool, 기본값 `true`. T2 기본
    제안자를 동일 발행기 후보 풀 내에서 지연 라우팅(invariant-safe;
    강제 적용 on). 리졸버가 >= 2 풀 을 발행(`--emit-primary-pool`) 할 때만
    적용; 단일 기본 로 pin 하려면 `false`.
    [llm-strategy-ko.md](../architecture/llm-strategy-ko.md) 의
    "T2 기본 지연 시간 풀" 참조.
- Fail-fast 검증기: `mode == "azure"` 는 `resolved_models_path` 필수.
- 테스트: 스키마 + pydantic 검증기.

### W-B: `rule-catalog/llm-registry.yaml` + 스키마 ✅ *(catalog-as-code, 배포)*

- 신규 파일: 업스트림 기본값 있는 `rule-catalog/llm-registry.yaml` (mini → Opus 계층).
- JSON 스키마: `rule-catalog/schema/llm-registry.schema.json`.
- Python 로더: `fdai.rule_catalog.schema.llm_registry` - 다른 곳에서 쓰는 aggregating
  fail-close 패턴 사용 (`exemption.py` 참고).
- 테스트: 스키마 검증, mixed-model 불변식 체크.

### W-C: 초기화 해석기 CLI ✅ *(배포자-스코프, 배포)*

- 신규: `services/core-control-plane/src/fdai/rule_catalog/schema/llm_resolver_cli.py`.
- 입력: `--registry`, `--region`, `--subscription-id`, `--dry-run`, `--out`.
- 기본 고정본 모드는 카탈로그/권한/할당량 JSON 세 개를 요구해 offline CI를 지원합니다.
- `--use-azure-cli` 모드는 기존 `az login` 맥락과 선택적 `AZURE_CONFIG_DIR`을 사용해
  모델 카탈로그, 역할 배정, 사용량/할당량, 프로비저닝된 용량을 읽기 전용 조회합니다.
- `resolved-models.json` 발행 (또는 `--dry-run` 은 stdout).
- [배포자-스코프 LLM 프로비저닝](#배포자-스코프-llm-프로비저닝) 의 모든 체크 강제.
- 테스트: 두 SDK 클라이언트 mock; precedence + mixed-model 불변식 + `hil-only` 대체 경로 +
  동일 입력 멱등적 출력 assert.

### W-D: Azure OpenAI Terraform 모듈 + preflight ✅ *(infra, 배포)*

- 신규: `infra/modules/llm/azure-openai/`.
  - `main.tf`: `azurerm_cognitive_account` (종류=`OpenAI`) + 입력 변수의
    `resolved_capabilities` 로부터 N개 `azurerm_cognitive_deployment`.
  - `variables.tf`: `enable_llm` (기본값 `false` - 최소 배포도 성공하도록),
    `resolved_capabilities` (해석기 로부터의 객체 목록).
  - `outputs.tf`: `endpoint`, `deployments` 지도, `resource_id`.
- 역할 배정: 실행기 MI → 계정의 `Cognitive Services OpenAI User`.
- 루트 `infra/main.tf` 에서 `var.enable_llm` 조건부로 모듈 wire.
- `infra/README.md` 갱신: 해석기 먼저 → `enable_llm=true` 로 `terraform apply`.

### W-E: Azure OpenAI 어댑터 클래스 ✅ *(전달, 배포)*

- `services/core-control-plane/src/fdai/delivery/azure/llm/embeddings.py` - `EmbeddingModel` 을 구현하는
  `AzureOpenAIEmbeddingModel`, injected 비동기 `httpx` + `WorkloadIdentity`.
- `services/core-control-plane/src/fdai/delivery/azure/llm/cross_check.py` - `CrossCheckModel` 구현
  `AzureOpenAICrossCheckModel`.
- 타임아웃, retry-after honouring, 구조화된 출력 (`response_format={"type":"json_object"}`)
  - [llm-strategy.md § 프로바이더 Abstraction](../architecture/llm-strategy-ko.md#provider-abstraction) 참조.
- 테스트: `httpx.MockTransport` + 녹화 고정본 - 라이브 네트워크 없음.

### W-F: Composition-root 배선 ✅ *(연결, 배포)*

- `Container` 확장: `embedding_model: EmbeddingModel`, `cross_check_models`,
  `verifier_policy`, `grounding_source` 필드.
- `default_container(config)`는 `local-fake`에 결정론적 연결을 넣고 `azure`에는
  아직 연결되지 않은 컨테이너를 반환합니다. 런타임 초기화가
  `bind_azure_llm_bindings`/`wire_azure_container`를 호출해 `resolved-models.json`을 로드하고
  기능별 어댑터를 연결합니다. 누락 항목은 fail fast합니다.
- 테스트: 양쪽 가지; `local-fake` 가 `delivery.azure.llm` 을 가져오기 안 함 assert.

### W-G: 고정본 신원 + 시크릿 + 인벤토리 어댑터 ✅ *(테스트 지원, 배포)*

- `shared/providers/testing/` 의 `EnvSecretProvider` (dev 사용 반영해
  `shared/providers/local/` 로 이름 변경).
- `LocalWorkloadIdentity` - 고정본 어댑터만 수락하는 인-메모리 OIDC 토큰을 발급합니다.
  Interactive 로컬은 이를 Thor 신원으로 사용하지 않습니다.
- `FileFixtureInventory` - 포크 가 생성자에 넘긴 어떤 YAML 고정본 든 (`fixture=Path(...)`) 에서 `Resource` 레코드를 읽는다. 업스트림은 시드 고정본 를 배송하지 않으며, 권장 컨벤션은 `services/core-control-plane/tests/scenarios/inventory/*.yaml` (고정된 시나리오 재생 옆) 이라 verticals 가 ARG 없이 예행 실행 가능.
- 테스트 + docstring이 정확한 fork-side 패턴 시연.

### W-H: 문서 동기화  *(이 단계)*

- ✅ 이 문서 자체.
- [deploy-and-onboard.md § 런타임 구성 매트릭스](deploy-and-onboard-ko.md#runtime-configuration-matrix)
  에 `LLM_MODE`, `LLM_RESOLVED_MODELS_PATH` 추가.
- [deploy-and-onboard.md § Azure Resource 인벤토리](deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set)
  에 행 11 (Azure OpenAI, 명시적 선택) 추가.
- [tech-stack.md § 로컬 개발](../architecture/tech-stack-ko.md#local-development) 에서
  권위 있는 interactive 어댑터와 명시적 고정본을 구분합니다.
- [llm-strategy.md § 초기화 Provisioner](../architecture/llm-strategy-ko.md#bootstrap-provisioner) 를
  배포자-권한 게이트에 대해 이 문서 참조로.

### W-I: 조정기 weekly 작업  *(later 단계 - deferred)*

Future 작업으로 유지. 전체 설계는 이미
[llm-strategy.md § 조정기 작업](../architecture/llm-strategy-ko.md#reconciler-job) 에 있음;
`infra/modules/compute/container-apps-job/` 재사용 + Python 엔트리로 shipping.

## Fork-Side 오버라이드 지점

위 모든 게 customer-agnostic 유지. 포크는 `core/` 를 안 건드리고 커스텀:

- 리전/컴플라이언스 오버라이드 있는 자체 `llm-registry.yaml` 제공.
- 포크의 구독을 가리키는 `AZURE_TENANT_ID` / `AZURE_SUBSCRIPTION_ID` env 제공.
  **이 리포는 그 값들을 절대 저장 안 함.**
- 추가 LLM 프로바이더 (예: Anthropic 직접 API) 등록: 조립 루트에서 포크 소유
  `CrossCheckModel` 구현 바인딩 - [llm-strategy.md § Mixed-Model 계열 Strategies](../architecture/llm-strategy-ko.md#mixed-model-family-strategies)
  의 `azure-foundry` / `external` / `hil-only` 토글.

## 검증 게이트

각 작업 항목은 CI에서 증명 가능해야:

- 명시적 고정본 프로파일은 `delivery.azure.*` 모듈을 가져오기하지 않습니다. Interactive 로컬은
  권위 있는 프로파일이 선택한 Azure 어댑터를 사용합니다.
- 동일한 입력, App 역할, 승격 상태, risk 구성은 로컬 및 deployed에서 같은 판정과
  프로세스 전이를 만듭니다.
- Interactive 로컬은 15개 에이전트를 기본 시작합니다. Event Hubs가 있으면 Azure 전송 계층을,
  없으면 범위가 제한된 프로세스 내 EventBus/SSE를 사용하며 recording/in-memory 실행기는 연결하지 않습니다.
- `Reader` 롤만 있는 fresh 구독에서 `enable_llm=false` 로 Terraform 계획 성공 →
  LLM 모듈이 정말 명시적 선택 임을 증명.
- 녹화된 리전 카탈로그에 대한 해석기 예행 실행이 고정된 `resolved-models.json` 해시 →
  멱등성 증명.
