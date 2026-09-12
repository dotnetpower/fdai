---
title: 배포(Deployment)
translation_of: deployment.md
translation_source_sha: 77219b7d15506c503eb0e0f7826d887b3411c345
translation_revised: 2026-09-12
---

# 배포(배포)

배포는 앱 형상을 따릅니다: 기본 1 복제본의 **headless 이벤트-기반 코어**, 명시적 선택
**얇은 콘솔 + Operator API**, 그리고 **PR-네이티브 + ChatOps** 딜리버리
([app-shape.instructions.md](../../../.github/instructions/app-shape.instructions.md) 참조).
인프라는 코드이며, 모든 릴리스는 [release and Rollback](#release-and-rollback) 에 정의된
계층화된 롤백 경로로 되돌릴 수 있습니다.

코어는 **CSP-중립 설계** 입니다: 클라우드 접근은 프로바이더 어댑터 뒤에 있으므로, 아래 Azure
매핑이 유일한 구현 대상입니다. **비-Azure 프로바이더는 TBD** 입니다
([구현 Focus](../../../.github/copilot-instructions.md#implementation-focus-must)).
어댑터 표면은 보존되어 향후 대상은 추가적입니다. 다운스트림 분포는 코어를 편집하지
않고 프로바이더 구현을 제공할 수 있으며, 각 배포는 구성으로 신원과
상태 연결을 제공합니다.
([generic-scope.instructions.md](../../../.github/instructions/generic-scope.instructions.md)).

## 구현 상태

### 구현 범위

| 영역 | 상태 | 근거 | 참고 |
|------|------|------|------|
| 새 clone 공개 개발 Core 경로 | implemented | `azd-up.sh`, 플랫폼 및 Core Terraform 루트, 기여자 배포 테스트, 집중 Terraform 계획 | 확인된 clean-checkout 실행은 공개 `dev` 구독 하나에서 플랫폼, 이미지, 스키마, 카탈로그, Core, Job, canary 및 초기 인벤토리를 단계적으로 배포합니다. 관찰 모드를 유지하며 비공개, 공유, 스테이징 또는 운영 경로가 아닙니다. |
| 기능 라이선스 Trial 전달 | implemented | Core 라이선스 및 실행 게이트 테스트, 독립 Core Terraform 검증, 기여자 배포 계약 | 토큰 없는 배포는 관찰 전용으로 유지됩니다. 공개 개발 경로는 소유자 전용 로컬 키가 검증될 때만 최대 30일의 전체 카탈로그 토큰을 발급하고 파일 입력으로 토큰별 다이제스트 이름의 Key Vault 시크릿에 전송하며, 버전 없는 참조와 비밀이 아닌 다이제스트만 Terraform에 전달합니다. 실제 Azure 발급, 갱신 또는 만료 증적은 아직 보존하지 않았습니다. |
| Terraform 계획/적용 및 공급망 게이트 | implemented | `.github/workflows/deploy-dev.yml`, `.github/workflows/container-supply-chain.yml` 및 집중 workflow 테스트 | 운영 입력, 이미지 증명, 표류 계획 및 post-apply smoke 검사가 제공됩니다. |
| 명시적 이미지 후보와 PR 패키징 집중 검사 | implemented | `container-supply-chain.yml`, 이미지 선택기, 워크플로 및 Genesis 회귀 검사; 집중 테스트 182개 통과 | 게시에는 보호된 main의 디스패치와 명시적 이미지 선택이 필요합니다. Genesis는 필요한 이미지만 요청하며 성공한 PR이나 일부 후보를 재사용할 수 없습니다. 다이제스트 검증은 독립적으로 유지합니다. |
| 보호된 구독 생성 plan-only 검증 | validated | 보호된 실행 `34436576350`, 정제된 `fdai.deployment-plan.v1` 메타데이터, 정확한 이행 및 파괴적 계획 가드 | 필수 CI를 통과한 개정 번호에서 선택한 Console, 운영 게이트웨이, Operator API, 문서 수집, 격리 실행기 범위의 준비된 계획을 생성했습니다. 전체 계획을 검토했으며 apply는 실행하지 않았습니다. |
| 독립 서비스 protected 배포 | validated | `config/independent-service-live-evidence-manifest.json` 및 `config/independent-service-remote-evidence.json` | Protected 계획은 출처, 백엔드, 대상, 신원 및 이미지를 결합하고 peer 격리와 롤백 증적을 보존합니다. |
| 단독 유지관리자 직접 개발 적용 | implemented | `.github/workflows/service-deploy.yml`, `.github/workflows/deploy-dev.yml`, `verify-github-environment.py` 및 집중 검증기와 작업 흐름 테스트 | `DEV_DEPLOY_REQUIRED_APPROVALS=0`은 검토자 규칙 없는 직접 개발 적용에만 허용됩니다. 정확한 계획, 이미지 증명, 신원 검사, 상태 확인 및 롤백은 계속 필요하며 스테이징, 운영 및 봇 소유 경로는 독립 승인을 유지합니다. |
| Bot 소유의 보호된 Core 적용 요청 | validated | PR #455, 보호된 계획 `33965356996`, Bot 요청 `33965478498`, 정확한 적용 `33965498775` 및 이슈 #454 | Bot 요청자를 사용해 FDAI 유지관리자와 배포 요청자를 분리합니다. 운영 외 Core 경로는 계획에 계속 결합되며 사람의 Environment 승인이 필요합니다. |
| 범위가 제한된 데이터베이스 호스트 연결 | implemented | 현재 변경의 `.github/workflows/service-deploy.yml`, `guard_plan.py`, `plan_bundle.py` 및 집중 service-deploy 테스트 | 봉인된 mode는 비밀이 아닌 host 연결만 허용합니다. 통제된 apply 근거는 아직 열려 있습니다. |
| 시작 준비 상태 새로 고침 복구 | implemented | `runtime/readiness.py` 및 `tests/runtime/test_readiness.py`, 현재 변경의 집중 transient-failure, expiry 및 programming-error 회귀 검사 | Supervisor는 가장 이른 근거 만료 시점에 보호된 처리를 닫습니다. 복구 가능한 연결 실패는 Core를 유지하지만 programming error는 준비 상태를 닫은 뒤 전파합니다. |
| 독립 서비스 롤백 기준 | implemented | 현재 변경의 `deployment_recovery.py`, 공유 서비스 Container App 모듈 및 집중 service-deploy 롤백 검사 | 적용 전 수집은 비정상 또는 비활성 개정 번호를 차단하고, 각 서비스는 복구를 위해 비활성 개정 번호 1개를 보존합니다. 성공한 protected 롤백 증적은 아직 필요합니다. |
| 성능 저하 상태의 Operator 복구 기준 | validated | Protected 계획 `33957891101`, 정확한 적용 `33957993467` 및 집중 복구 검사 | 명시적 모드는 실행 중인 비정상 Operator 개정 번호를 봉인된 롤백 기준으로 사용해 서비스를 정상 상태로 복원했습니다. |
| 권위 있는 Operator Console origin | validated | Protected 계획 `33959768010`, 적용 `33959860773` 및 이슈 #414의 인증된 브라우저 근거 | 계획은 보호된 Console 게시 연결에서 단일 HTTPS CORS origin을 가져옵니다. 적용과 상태 검증은 성공했으며, 동시에 Core 상태가 이동해 peer 격리 증적만 생성되지 않았습니다. |
| Operator schema 및 catalog 초기화 | implemented | 현재 변경의 `infra/modules/operator-api/container-app/`, `.github/workflows/deploy-dev.yml` 및 `tests/integration/scripts/test_service_deploy_workflow.py` | Alembic Job 성공 후 별도의 Core-image Job이 변경 불가능한 Rule 및 Ontology 참조 projection을 기록합니다. |
| 브라우저 근거 보존 Job | implemented | `infra/modules/compute/container-apps/browser_evidence_cleanup_job.tf`; focused Terraform 계약 검사(`4 passed`) 및 `terraform validate` | 명시적으로 선택하는 예약 Job은 실행기 신원이 아닌 신원과 범위가 제한된 1회 정리를 사용합니다. 관리되는 적용 및 실행 증적은 보존되지 않았습니다. |
| 자동 승격 및 점진적 배포 | not-started | 이 문서의 목표 설계 | 자동 dev -> staging -> prod 승격, traffic-split canary, SLO 롤백 및 콘솔 blue/green은 구현되지 않았습니다. |

### 구현 이력

| 날짜 | 상태 | 변경 | 근거 | 남은 작업 |
|------|------|------|------|-----------|
| 2026-09-12 | implemented | 모델 전용 Terraform 계획의 대상을 Azure OpenAI 기능 배포 컬렉션으로 제한했습니다. 이제 상위 모듈 전체를 대상으로 지정해 기존 계정 및 역할 할당 리소스가 계획에 포함되는 일이 없습니다. | `current change`; 실패한 보호 계획 `34677766334`; `.github/workflows/deploy-dev.yml`; 모델 수명 주기 및 배포 작업 흐름 집중 테스트 87개; CI 계약 검사. | 수정된 작업 흐름을 게시하고 관련 없는 변경이 없는 모델 연결 계획을 보존한 뒤 이슈 #90의 정확한 Core 이미지 연결 및 런타임 근거를 완료합니다. |
| 2026-09-10 | implemented | 배포 실행기가 사용하는 ops 소유의 비공개 DNS 영역에 운영 이력 Blob 계정 전용 A record를 추가했습니다. 범위가 제한된 운영 이력 target은 lifecycle Job 종속성을 통해 record를 가져오고 plan 범위 guard는 해당 주소만 허용합니다. 공용 네트워크 접근과 key 인증은 계속 비활성화합니다. | `current change`; 보호된 OI-12 실행 `34447462177`은 실행기 readback 실패 전에 7개 축을 모두 완료하고 비공개 증적을 기록함; 실행기 VM의 guest DNS 진단; 프로바이더에서 관측한 앱 영역 A record와 누락된 ops 영역 record; 집중 Terraform 및 범위 검사. | 실행기 DNS 연결을 게시하고 보호된 운영 이력 plan/apply를 실행 및 검토한 뒤 실행기의 비공개 Blob 해석을 증명하고 통과한 보호 OI-12 artifact를 보존합니다. |
| 2026-09-10 | implemented | OI-12 프로바이더 실패 및 복구 쿼리를 현재 활성 세대의 원본과 관측 종류로 제한했습니다. 폐기한 원본이 현재 운영 인스턴스 축을 영구 unavailable 상태로 유지할 수 없습니다. 복구는 여전히 실패 이후에 발생해야 하며 실패의 원본, 관측 종류, 범위와 리소스 종류에 정확히 일치해야 합니다. | `current change`; 실패한 보호 인증 `34445258249`; 정제한 읽기 전용 운영 집계에서 폐기한 `arm/observed` 원본은 이후 성공이 없고 활성 `arg/observed` 원본에는 정확한 194.335387초 복구가 있음을 확인; 집중 PostgreSQL 인증 검사. | 활성 원본 fence를 게시하고 정확히 증명된 Core 이미지를 생성한 뒤 통과한 보호 OI-12 증적을 보존합니다. |
| 2026-09-10 | implemented | 실제 endpoint가 Job 소유의 `volumes`를 거부한 뒤 인벤토리 ARM 시작 본문을 안정 `JobExecutionTemplate` schema로 제한했습니다. Materializer는 검토된 전체 Job을 계속 검증하고 컨테이너 명령, 인자, 환경, 리소스, 시크릿 참조, 볼륨 mount와 초기화 컨테이너를 보존하지만 `containers`와 `initContainers`만 내보냅니다. 구성된 볼륨은 Job에서 제공합니다. | `current change`; 실패한 보호 인증 `34442888325`; 안정 Container Apps `2024-03-01` OpenAPI schema; 집중 materializer 및 작업 흐름 검사. | Schema에 맞는 시작 본문을 게시하고 정확히 증명된 Core 이미지를 생성한 뒤 통과한 보호 OI-12 증적을 보존합니다. |
| 2026-09-10 | implemented | 인벤토리 새로 고침 CLI 이미지 override를 검토된 실제 실행 템플릿을 복사하고 정식 `inventory` 컨테이너 이미지만 바꾸는 안정 ARM 시작 요청으로 교체했습니다. 이 요청은 mode 0600의 일시적 본문에서 명령, 인자, 환경, 리소스, 볼륨, 시크릿 참조를 보존합니다. | `current change`; 실패한 보호 인증 `34440577232`; 정제한 실패 execution 템플릿에서 CLI override가 정식 이름, 명령, 환경을 제거함을 확인; 집중 작업 흐름 검사. | 템플릿을 보존하는 시작 경로를 게시하고 정확히 증명된 Core 이미지를 생성한 뒤 통과한 보호 OI-12 증적을 보존합니다. |
| 2026-09-10 | implemented | 보호된 실행기가 `!=` 뒤의 줄바꿈을 거부한 뒤 리소스 그룹 동등성 guard를 유효한 Bash 이항 조건식 하나로 수정했습니다. 공급자가 관측한 값의 정확한 동등성 요구 사항은 바뀌지 않습니다. | `current change`; 실패한 보호 인증 `34439221020`; 집중 작업 흐름 계약 검사; actionlint. | 구문 수정 사항을 게시하고 정확히 증명된 Core 이미지를 생성한 뒤 통과한 보호 OI-12 증적을 보존합니다. |
| 2026-09-10 | validated | 선택한 애플리케이션 범위의 보호된 구독 생성 plan-only 검증을 완료했습니다. 검토한 계획에는 추가 26건, 제자리 변경 11건, 삭제 14건이 있습니다. 모든 삭제는 정확한 교체 12건과 비활성화된 측정 Job 제거 2건으로 설명되며, 일반 파괴 가드에서 검토되지 않은 삭제가 발견되지 않았습니다. 비용 검토에는 embedding 교체, ontology council 배포 3건, 파트너 AI 계정 1건, PostgreSQL SKU 하향이 포함되었습니다. | 보호된 실행 `34436576350`, 준비된 계획 `plan-34436576350-1`, 소스 개정 번호 `8a3bfc3b560034f564b0648c8ff10cb80e8bdfa8`, 검증된 런타임 이미지 개정 번호 `5eb80b2b5e74868dd9ccf7a0dcfeac8d8de1b630`, 정제된 계획 및 사전 점검 다이제스트. | Apply는 실행하지 않았습니다. Apply하려면 만료되지 않은 정확한 계획 ID와 다이제스트에 연결된 별도의 현재 사람 승인이 필요합니다. |
| 2026-09-10 | implemented | 비활성화된 측정 기능이 unindexed 후속 항목을 만들지 않고 이전 indexed Job 두 개를 삭제한다는 보호 계획 결과에 맞춰 검토된 측정 제거 계약을 정정했습니다. 허용되는 각 제거는 정확한 관리형 리소스 종류, 이름, 인덱스, 삭제 전용 작업, 이전 객체, null 결과, 교체 경로 부재를 모두 충족해야 합니다. | 실패한 보호 계획 `34435072691`; `guard_platform_migration_plan.py`; 집중 positive 및 negative 제거 테스트. | Plan-only를 다시 실행해 정제한 메타데이터를 보존하고 모든 변경과 비용 민감 리소스를 검토한 뒤 apply 전에 중단합니다. |
| 2026-09-10 | implemented | 검토된 플랫폼 역할 이행 검증을 권한에 영향을 주는 안정 필드로 제한하고 선택적 프로바이더 메타데이터 비교를 중단했습니다. 정확한 주소, 작업, 유일한 교체 경로, 역할 이름, 바뀌지 않은 범위 또는 principal은 계속 필수입니다. | 실패한 보호 계획 `34431365390`; 집중 프로바이더 변형 및 negative 이행 테스트. | Plan-only를 다시 실행해 정제한 메타데이터를 보존하고 모든 변경과 비용 민감 리소스를 검토한 뒤 apply 전에 중단합니다. |
| 2026-09-10 | implemented | OI-12 기존 연결이 누락된 플랫폼 리소스 그룹 출력을 복구하도록 확장했습니다. fallback은 64개 리소스 한도 아래에서 `Microsoft.App/jobs`만 열거하고, 고유한 인벤토리 및 이력 런타임 계약이 공급자가 관측한 동일한 그룹을 보고할 때만 리소스 그룹을 채택합니다. 비어 있지 않은 최상위 출력은 이 그룹과 일치해야 합니다. | `current change`; 실패한 보호 인증 `34431383809`; 정제한 정확한 실행기 guard 재현; 집중 작업 흐름 검사. | 리소스 그룹 fallback을 게시하고 정확히 증명된 Core 이미지를 생성한 뒤 통과한 보호 OI-12 증적을 보존합니다. |
| 2026-09-10 | implemented | 여섯 역할 principal 또는 범위 교체, unindexed create 후속 항목이 있는 indexed 측정 Job 제거 두 건, 검토된 `t1.embedding` 제품군, SKU, 용량 교체를 위한 별도의 정확한 이행 검증기를 추가했습니다. 검증된 파괴적 레코드만 임시 검토 복사본에서 제거하며 apply 권한은 바뀌지 않습니다. | 보호 계획 `34430417852`; Terraform 정의; 집중 positive 및 negative 이행 테스트. | Plan-only를 다시 실행해 정제한 메타데이터를 보존하고 모든 변경과 비용 민감 리소스를 검토한 뒤 apply 전에 중단합니다. |
| 2026-09-10 | implemented | OI-12 Job 해석, 정확한 OCI 출처 증명 검증, ACR 연결을 별도의 보호된 단계로 분리했습니다. 검증된 저장소, 개정 번호, 다이제스트만 `GITHUB_ENV`를 통해 단계 경계를 넘으며 각 단계는 자체 실패 경계를 보고합니다. | `current change`; 실패한 보호 인증 `34429999806`; `.github/workflows/operational-instance-certification.yml`; 집중 작업 흐름 계약 검사. | 분리된 작업 흐름을 게시하고 정확히 증명된 Core 이미지를 생성한 뒤 통과한 보호 OI-12 증적을 보존합니다. |
| 2026-09-10 | implemented | 일시적 GHCR 인증에서 Docker CLI 의존성을 제거했습니다. Binder는 기존 workflow 자격 증명을 프로세스 내부에서 mode 0600 파일로 렌더링하고 인자나 출력에 넣지 않으며 레지스트리 전용 출처 증명 검증을 유지합니다. | `current change`; Terraform과 Azure 전에 중단된 실패한 plan-only 실행 `34427330193`; 실행 가능한 binder 및 자격 증명 위생 회귀 검사. | 수정된 검증기를 게시하고 exact CI를 통과한 뒤 이미지를 승격하지 않는 보호 계획을 다시 실행합니다. |
| 2026-09-10 | implemented | OCI 증명 검증을 위해 일시적인 GHCR 인증을 추가했습니다. binder는 mode 0700 Docker 구성에만 자격 증명을 쓰고 stdin으로 토큰을 받으며 종료할 때 디렉터리를 제거하고 인증 및 검증 실패를 명시적으로 보고합니다. | `current change`; 실패한 보호 인증 `34419767892`; 일시적 구성으로 수행한 로컬 다이제스트 검증 통과; 집중 자격 증명 위생 및 이미지 연결 검사. | 검증기 인증 수정 사항을 게시하고 정확히 증명된 Core 이미지를 생성한 뒤 통과한 보호 OI-12 증적을 보존합니다. |
| 2026-09-10 | implemented | Terraform 최상위 출력에서 기존 이력 Job ID와 보관 컨테이너 URL이 모두 비어 있음을 확인한 뒤 범위가 제한된 ARM fallback을 확장했습니다. 한 번의 열거로 인벤토리 런타임과 이력 런타임을 각각 정확히 하나 해석하고, 비어 있지 않은 최상위 출력과 교차 확인하며, 선택한 이력 Job을 안정 리소스 API로 다시 읽습니다. | `current change`; 실패한 보호 인증 `34416935783`; 정제한 실행기 재현; 범위가 제한된 실제 ARM 검증에서 정확한 인벤토리 계약과 이력 계약을 각각 1개 확인; 집중 작업 흐름 검사. | 이력 fallback을 게시하고 정확히 증명된 Core 이미지를 생성한 뒤 통과한 보호 OI-12 증적을 보존합니다. |
| 2026-09-09 | implemented | 사용할 수 없는 프로바이더 컬렉션 엔드포인트를 범위가 제한된 일반 ARM 리소스 열거와 리소스별 안정 Container Apps 조회로 교체했습니다. fallback은 Job ID를 최대 64개까지 허용하고 각 조회 시간을 30초로 제한하며, 검토된 인벤토리 런타임 계약이 정확히 하나여야 한다는 조건을 유지합니다. | `current change`; 실패한 보호 인증 `34410700086`; 범위가 제한된 실제 열거에서 Job 12개와 정확한 계약 일치 항목 1개 확인; 집중 작업 흐름 계약 검사. | 범위가 제한된 열거를 게시하고 정확히 증명된 Core 이미지를 생성한 뒤 통과한 보호 OI-12 증적을 보존합니다. |
| 2026-09-09 | implemented | ARM으로 관측하는 인벤토리 Job 조회가 실행기 CLI 확장의 잘못된 기본 버전 대신 지원되는 안정 Container Apps `2024-03-01` API를 사용하도록 고정했습니다. 정확한 리소스 그룹과 런타임 계약 카디널리티 검사는 그대로 유지합니다. | `current change`; 실패한 보호 인증 `34406488996`; 안정 API 실제 조회에서 검토된 계약 일치 항목 1개 확인; 집중 작업 흐름 계약 검사. | API 고정 사항을 게시하고 정확히 증명된 Core 이미지를 생성한 뒤 통과한 보호 OI-12 증적을 보존합니다. |
| 2026-09-09 | implemented | 사용할 수 없는 Terraform 상태 스냅샷 fallback을 정확한 플랫폼 리소스 그룹 안에서 ARM으로 관측한 인벤토리 Job 조회로 교체했습니다. fallback은 검토된 이름, 명령, 빈 인자를 가진 컨테이너가 정확히 하나여야 하며 Job 이름에서 신원을 유추하지 않습니다. | `current change`; 실패한 보호 인증 `34403565287`; 범위가 제한된 실제 ARM 카디널리티 진단; 집중 작업 흐름 계약 검사. | ARM fallback을 게시하고 정확히 증명된 Core 이미지를 생성한 뒤 통과한 보호 OI-12 증적을 보존합니다. |
| 2026-09-09 | implemented | 역할과 범위가 바뀌지 않고, `principal_id`만 유일한 교체 경로이며 apply 전까지 알 수 없는 상태이고, 같은 계획에서 새 Operator API UAMI를 생성할 때만 정확한 Operator API OpenAI User 역할 교체를 보호된 계획으로 보존하도록 허용했습니다. 이는 apply를 승인하지 않습니다. | 실패한 보호 계획 `34404837936`; 정제한 계획 검토; 집중 positive 및 negative guard 테스트. | Plan-only를 다시 실행하고 보존된 모든 변경과 비용 민감 리소스를 검토한 뒤 apply 전에 중단합니다. |
| 2026-09-09 | implemented | 실제 계획을 바탕으로 초기 가정을 수정했습니다. 함께 처리하는 Operator API UAMI는 신규 생성이 아니라 이름만 바꾸는 교체입니다. 이제 guard는 위치, 리소스 그룹, 태그가 바뀌지 않고 계산되는 신원 필드만 apply 전까지 알 수 없는 상태인지 확인합니다. | 실패한 보호 계획 `34411374082`; 정제한 교체 경로 검토; 확대된 positive 및 negative guard 테스트. | Plan-only를 다시 실행하고 보존된 모든 변경과 비용 민감 리소스를 검토한 뒤 apply 전에 중단합니다. |
| 2026-09-10 | implemented | 정확한 역할 및 UAMI 교체 경로와 모든 안정 값 동일성 검사는 유지하면서 프로바이더가 계산하는 `after_unknown` 인코딩을 권한 판단에서 제거했습니다. | 실패한 보호 계획 `34420153874`; 정제한 Terraform 블록 비교; 집중 인코딩 변형 및 negative guard 테스트. | Plan-only를 다시 실행하고 보존된 모든 변경과 비용 민감 리소스를 검토한 뒤 apply 전에 중단합니다. |
| 2026-09-10 | implemented | Operator 역할 guard를 권한에 영향을 주는 안정 필드로 제한했습니다. 정확한 주소와 작업, 유일한 교체 경로, 바뀌지 않은 역할 범위와 이름, 바뀌지 않은 UAMI 위치, 리소스 그룹, 태그를 확인합니다. 선택적 프로바이더 상태는 더 이상 잘못된 거부를 만들지 않습니다. | 실패한 보호 계획 `34421874225`; 정제한 교체 구조; 확대된 안정 필드 및 프로바이더 변형 테스트. | Plan-only를 다시 실행하고 보존된 모든 변경과 비용 민감 리소스를 검토한 뒤 apply 전에 중단합니다. |
| 2026-09-10 | implemented | 검증된 Operator 역할/UAMI 교체 쌍에서 역할 할당만 제거해 이미 검증한 UAMI를 다시 거부하지 않도록, 임시 파괴적 검토 복사본에서 두 구성원을 모두 제거했습니다. 그 밖의 파괴적 변경은 일반 guard에서 계속 확인합니다. | 실패한 보호 계획 `34424719829`; 집중 pair-filter 및 negative guard 테스트. | 런타임 이미지에 결속된 계획을 다시 실행하고 보존된 모든 변경과 비용 민감 리소스를 검토한 뒤 apply 전에 중단합니다. |
| 2026-09-09 | implemented | 암시적 상태 렌더링에서 일치하는 리소스를 찾지 못한 뒤 OI-12 기존 인벤토리 Job 조회를 mode 0600의 특정 시점 Terraform 상태 스냅샷에 결속했습니다. 실행기는 단계가 끝날 때 스냅샷을 삭제하며 추적된 주소가 정확히 하나여야 한다는 조건을 유지합니다. | `current change`; 실패한 보호 인증 `34400981555`; 실제 비공개 상태 주소 진단; 집중 작업 흐름 계약 검사. | 스냅샷 수정 사항을 게시하고 정확히 증명된 Core 이미지를 생성한 뒤 통과한 보호 OI-12 증적을 보존합니다. |
| 2026-09-09 | implemented | 보호된 OI-12 인벤토리 새로 고침이 최상위 인벤토리 Job 출력보다 먼저 배포된 플랫폼 상태와 호환되도록 수정했습니다. 작업 흐름은 최상위 출력을 우선 사용하고, 이름에서 신원을 유추하지 않은 채 상태에 추적된 인벤토리 Job 리소스 하나만 정확히 확인합니다. | `current change`; 실패한 보호 인증 `34389423964`; `.github/workflows/operational-instance-certification.yml`; 집중 작업 흐름 계약 검사. | 호환성 수정 사항을 게시하고 정확히 증명된 Core 이미지를 생성한 뒤 통과한 보호 OI-12 증적을 보존합니다. |
| 2026-09-09 | implemented | 기존 out-of-band Job과 rule-watcher Job을 개발 운영 게이트웨이 대상 의존성 집합에 추가했습니다. 이제 Terraform은 선언되지 않은 의존성 대상을 요구하지 않고 이미 선택한 게이트웨이 및 측정 리소스의 계획을 만들 수 있습니다. | `current change`; 실패한 보호 계획 `34316856951`; `.github/workflows/deploy-dev.yml`; 집중 workflow 대상 검사. | workflow 수정 사항을 게시하고 적용 전에 정확한 런타임 이미지 승격 계획을 다시 실행합니다. |
| 2026-09-09 | implemented | 라이선스 필수 Trial 동작, 암호학적으로 검증된 로컬 발급자 예외, 소비자가 강제하는 30일 토큰, 다이제스트 이름의 Key Vault 시크릿을 통한 격리된 갱신 및 보호된 공개 Core 경로의 재시작 가능한 tfvars 구체화를 추가했습니다. | `current change`; 결합된 집중 회귀 검사 228개, 검토 후 기여자 검사 9개와 air-gap 제품화 검사 6개 통과, 두 Core Terraform 계층 검증 완료, 빌드한 Core wheel에 공개 키 포함 확인. | 키 없는 새 Azure 배포의 Trial, 활성 토큰이 있는 발급자 배포, 만료 차단 및 동일 이미지 갱신 증적을 보존합니다. |
| 2026-09-09 | implemented | 공개 `dev` 플랫폼과 독립 Core 루트를 정확한 ACR 빌드, 스키마 및 카탈로그 부트스트랩, 예약 Job 활성화, 범위가 제한된 상태 검사를 포함하는 하나의 보호된 fresh-clone 경로로 조합했습니다. | `current change`; 집중 배포 workflow 테스트 86개, 집중 native Terraform 계획 46개 통과, Terraform 구성 검증 통과. | 경로를 validated로 분류하기 전에 통제된 새 구독 적용, 정리, 두 번째 실행 no-change, Core 상태, canary 및 인벤토리 증적을 보존합니다. |
| 2026-09-07 | implemented | 예약된 외부 변경 감지와 원하는 상태의 배포 계획을 분리했습니다. 이제 모든 표류 검사 루트가 새로 고침 전용 계획을 사용하므로, 전달 시점에만 사용하는 기능 입력이 누락되어도 활성 리소스가 삭제 대상으로 표시되지 않습니다. | `current change`, `.github/workflows/infra-drift.yml` 및 집중 표류 workflow 계약 테스트 | 삭제가 없는 새로 고침 계획을 보여 주는 정확한 보호 실행을 하나 보존합니다. 적용되지 않은 코드와 구성 변경은 보호된 배포 계획에서 확인합니다. |
| 2026-09-07 | implemented | 정확한 계획과 런타임 안전성 검사를 유지하면서 검토 없는 환경을 검증하는 명시적인 단독 유지관리자 개발 정책을 추가했습니다. | `current change`, 집중 검증기 및 배포 작업 흐름 테스트 | 직접 개발 적용 하나를 성공시키고 적용 후 projection 조회 결과를 보존합니다. |
| 2026-09-05 | validated | 독립된 사람의 Environment 승인, 성공한 상태 및 peer 격리 검사, 독립적인 이미지 및 신원 확인을 거쳐 첫 번째 Bot 요청 보호 Core 서비스 적용을 완료했습니다. | PR #455, 계획 `33965356996`, 요청 `33965478498`, 적용 `33965498775`, 이슈 #454 | 이 경로를 운영 외 범위와 정확한 계획에 계속 결합하고 보호된 Environment 정책을 적용합니다. |
| 2026-09-05 | implemented | 정확한 성공 계획 실행, 만료되지 않은 산출물, 이미지 digest, 커밋 및 Environment 정책을 전달 전에 검증하는 운영 외 Bot 소유 Core 서비스 적용 요청을 추가했습니다. | `current change`, 보호된 작업 workflow, 요청 검증기 및 성공과 차단 기본 동작에 대한 집중 테스트 | 이슈 #454에서 첫 번째 독립 요청자 Environment 승인과 성공한 Core 서비스 적용 증적을 수집합니다. |
| 2026-08-13 | implemented | 이전 provenance를 재구성하지 않고 implementation ledger를 도입하고 schema migration 뒤 배포된 Operator catalog 초기화를 추가했습니다. | current change, 집중 deployment workflow 및 Terraform 검사 | Catalog Job의 통제된 적용 증적을 수집하고 점진적 배포 목표를 구현합니다. |
| 2026-08-14 | implemented | Co-host 호환 경로가 제거된 뒤 인제스트 롤백 지침을 수정했습니다. 이제 롤백은 독립 API 및 워커의 정확한 이전 개정 번호를 복원합니다. | `current change`, 집중 Terraform 검증 및 mock 인제스트 테스트 5개 통과 | 배포 가이드와 mock 테스트를 독립 서비스 루트에 맞게 유지합니다. |
| 2026-08-15 | implemented | 실행기 신원이나 즉시 플랫폼 재시도 없이 범위가 제한된 브라우저 근거 보존을 수행하는 명시적 선택 예약 Container Apps Job을 추가했습니다. | `current change`; focused Terraform 계약 검사 `4 passed`; `terraform validate`. | Protected 적용 및 성공과 실패 Job 실행 증적을 수집합니다. |
| 2026-08-20 | implemented | 정지한 migration이 service job의 2시간 전체 예산을 소진한 뒤 모든 service migration 연결, service 간 잠금 및 protected workflow 단계에 경계를 추가했습니다. Cleanup은 이제 원래 migration 오류를 보존합니다. | `current change`; service migration 및 protected workflow 계약 검사 204개 통과; Ruff 및 strict mypy 통과. | Protected exact 적용 하나를 완료하고 migration, service 상태 및 rollback 경계 근거를 보존합니다. |
| 2026-08-24 | implemented | 봉인된 database host binding mode를 추가하고 Core의 중복 host 선언을 제거했으며 in-place 갱신을 위한 명시적 legacy Operator 이름 호환 경계를 유지했습니다. | `current change`; focused guard, bundle, workflow, naming 및 Terraform validation 검사. | Zero-destroy plan 5개와 exact apply를 완료한 뒤 이슈 #262에 독립 runtime 및 inventory 근거를 보존합니다. |
| 2026-08-24 | implemented | 같은 namespace의 두 번째 zone을 만들지 않고 일회용 scenario OpenAI private endpoint를 기존 중앙 Private DNS zone에 연결했습니다. Scenario state는 lab VNet link와 endpoint zone group을 소유하며, 중앙에서 소유하는 runner 및 P2S link는 바꾸지 않습니다. | 실패한 protected apply `32752288798`; `infra/scenario-lab/` 및 `.github/workflows/sre-demo-lab.yml`의 `current change`; 집중 Terraform 및 workflow 검사입니다. | Protected scenario apply, 승인된 sweep 및 최종 destroy 증적을 완료합니다. |
| 2026-08-25 | implemented | 복구 가능한 provider 실패가 발생해도 시작 준비 상태 새로 고침 supervisor를 유지하고, 가장 이른 근거 만료 시점에 보호된 처리를 닫으며, programming error는 준비 상태를 닫은 뒤 계속 전파하도록 했습니다. 마지막 성공 보고서는 진단을 위해 유지하고 완전한 새로 고침이 성공해야만 복구 가능한 실패 fence를 해제합니다. | `current change`, 집중 transient-failure, evidence-expiry, programming-error 및 통합 검사 | 런타임 validated 상태를 주장하기 전에 exact-revision 배포 복구 근거를 별도로 보존합니다. |
| 2026-08-25 | implemented | 완료된 Event Bus 이행 모드를 platform 및 service workflow에서 제거하고 helper API도 삭제했습니다. 현재 배포는 다시 실행할 수 있는 일회성 전환을 노출하지 않고 정본 `fdai.*` 토픽 연결만 수락합니다. | `current change`, 집중 배포 workflow, service helper, Terraform 및 문서 검사 | 완료된 토픽 이행 모드에 남은 구현 작업은 없습니다. |
| 2026-08-25 | implemented | Protected 계획과 예약 표류 검사가 서비스 입력을 선택하기 전에 권위 있는 플랫폼 상태에서 기본 유입 토픽을 채우도록 했습니다. 오래된 쓰기 전용 tfvars 시크릿이 폐기된 토픽 연결을 복원할 수 없습니다. | `current change`, `hydrate_event_topic.py`, protected 서비스 및 표류 workflow, 집중 hydration 및 workflow 계약 검사 | 이슈 #262에서 추적하는 zero-destroy 계획 5개와 exact apply를 완료합니다. |
| 2026-08-25 | implemented | Protected Core apply가 Terraform 전에 statement deadline에 도달한 뒤 canonical Incident migration의 projection별 audit scan을 index 기반 lifecycle interval로 교체했습니다. Historical as-of identity와 runtime trigger 계약은 바뀌지 않습니다. | 실패한 apply `32825805596`, `current change`, 집중 migration 계약 및 일회용 PostgreSQL 테스트 4개 통과, 5초 statement budget 안에서 무관한 audit row 20,000개와 projection version 2,002개 검증 | Exact protected Core 계획을 다시 만들고 적용한 뒤 migration, 상태 및 peer 격리 증적을 보존합니다. |
| 2026-08-25 | implemented | 실패한 Core 개정 번호가 다음 적용의 복구 출처가 되고 비활성 개정 번호 보존 수가 0이라 즉시 제거되면서 드러난 롤백 기준 결함을 닫았습니다. 이제 스냅샷 수집은 정상인 활성 개정 번호를 요구하고, 공유 서비스 모듈은 비활성 개정 번호 1개를 보존하며, 계획 가드는 일회성 `0 -> 1` 보존 강화만 허용합니다. | 실패한 Core 적용 `32839129965` 및 `32842018230`, `current change`, 집중 롤백 기준 및 보존 가드 검사 | 독립 서비스 배포 상태를 다시 `validated`로 올리기 전에 정상 Core 기준 하나를 복원하고 zero-destroy protected 계획, 성공한 exact 적용 및 검증된 자동 롤백 증적을 보존합니다. |
| 2026-08-26 | implemented | 중지된 개발 PostgreSQL server를 복구한 뒤 준비 상태가 다시 열리면서 서로 독립적인 Core crash 경로 두 개가 드러났습니다. 이제 consumer progress는 commit과 highwater 관측 사이의 partition 회수를 허용하고, 새 Core migration은 detached background-task 조정기에 소유 테이블 3개의 정확한 접근 권한을 부여합니다. | Live revision `ca-fdai-dev-krc-core--p20260825121110`, `current change`, 집중 Event Bus race 및 migration grant 회귀 검사 3개 통과 | 정확히 증명된 이미지를 게시하고 보호된 workflow를 통해 정상 Core 기준 하나를 복원한 뒤, provider-schema 적용 전에 crash-free 상태 및 rollback 보존 근거를 보존합니다. |
| 2026-09-05 | implemented | Azure에 별도의 정상 개정 번호가 없을 때 Operator 데이터베이스 연결 복구에 사용하는 봉인된 성능 저하 복구 경계를 추가했습니다. 기준 개정 번호는 활성, 프로비저닝 완료, 실행 중, 정확히 복원 가능한 상태여야 하며 이 모드는 보호된 Terraform 계획의 범위를 넓히지 않습니다. | `current change`, 집중 계획 묶음, 작업 흐름, 기준 선택, 스냅샷 및 롤백 검사 | 정확한 protected Operator 적용 1회를 실행하고 상태 및 롤백 경계 근거를 보존합니다. |
| 2026-09-05 | implemented | 성능 저하 상태의 Operator 복구를 검증한 다음, 실제 브라우저 preflight에서 빈 CORS 연결을 확인한 뒤 권위 있는 Console origin hydration을 추가했습니다. 데이터베이스 연결 검증기는 정규화된 단일 Static Web Apps HTTPS origin만 수락하고 관련 없는 환경 변경은 계속 차단합니다. | Protected 계획 `33957891101`, 정확한 적용 `33957993467`, `current change`, 집중 hydration, 검증기 및 작업 흐름 검사 | Console origin 연결을 적용하고 인증된 브라우저 근거를 보존합니다. |
| 2026-09-05 | validated | 보호된 Console origin을 적용하고 인증된 Help drawer 검증을 완료했습니다. Drawer는 경고나 가로 overflow 없이 여정 단계 5개, manual card 11개 및 로드된 cover image 22개를 표시했고, 선택한 동일 origin manual은 HTTP 200을 반환했습니다. | Protected 계획 `33959768010`, 적용 `33959860773`, 이슈 #414 브라우저 근거. 적용과 상태 검증 단계는 성공했으며, peer 격리 중 Core 상태 serial이 53에서 54로 동시에 증가해 최종 workflow만 실패했습니다. | Operator Console origin 연결에 남은 작업이 없습니다. |
| 2026-09-12 | in-progress | PR 패키징 집중 검사와 보호된 main의 명시적 이미지 게시를 분리했습니다. main/tag 자동 게시와 PR SBOM 생성을 제거하고 전체 이미지 기본값 없이 입력을 검증하는 이미지 선택을 추가했습니다. | `current change`; `container-supply-chain.yml`, `select_changed_images.py`, 선택기 및 작업 흐름 집중 회귀 테스트를 추가했으나 아직 실행하지 않았습니다. | 집중 검사 통과 결과를 기록합니다. 별도로 승인한 후보 실행은 로컬 구현과 구분합니다. |
| 2026-09-12 | implemented | PR 패키징 집중 검사와 보호된 main의 명시적 게시를 분리했습니다. main/tag 자동 게시와 PR SBOM 생성을 제거하고 알려진 소스 전용 PR 변경을 트리거에서 제외했으며 이미지 선택을 필수로 만들었습니다. Genesis 디스패치와 재사용은 필요한 이미지 집합을 확인하고 PR 또는 일부 후보의 성공을 수락하지 않습니다. | `current change`; 선택기, CI 계약, Genesis 애플리케이션, 감독기 및 이미지 테스트 182개와 CI 계약 검사 통과. | 명시적으로 승인한 후보 실행과 변경 후 지연 측정은 로컬 구현과 별도로 남습니다. |
| 2026-09-12 | implemented | 모든 Core `FDAI_SOURCE_REVISION` 변경을 정확한 보호 커밋에 결속하고, 고정 Heimdall 복구 관찰자의 최초 채택을 명시적 Core 근거 전환으로 제한했습니다. | 실패한 보호 Core 계획 `34637615112`; 현재 변경의 `guard_plan.py`, `service-deploy.yml`, `service-matrix.json` 및 집중 service-deploy 검사 299개 통과. | 수정한 제어를 게시하고 새 exact Core 후보를 만든 뒤 이슈 #290에 필요한 zero-destroy 계획, exact 적용 및 롤백 근거를 보존합니다. |
### 남은 작업

- [ ] 정확한 clean revision, 검토한 미리보기, 임시 접근 정리, Core 상태, canary, 초기
  인벤토리 및 두 번째 실행 no-change 계획을 포함하는 저장소 안전 공개 새 구독 증적 하나를 보존합니다.
- [x] 후보 전용 게시, PR 패키징 집중 검사 및 Genesis 호출 호환성에 대한 선택기, 워크플로,
  애플리케이션, 감독기 및 이미지 집중 테스트가 통과했습니다.
- [ ] Operator migration Job이 catalog Job보다 먼저 성공하고 이후 두 immutable projection
  key를 읽을 수 있음을 보여 주는 리포지토리에 안전한 통제된 적용 증적을 보존합니다.
- [ ] 브라우저 근거 보존 Job의 리포지토리에 안전한 protected 적용 및 성공과 실패 실행 증적을 보존합니다.
- [ ] 이슈 #262의 zero-destroy database host plan 5개와 exact apply를 완료한 뒤 workload
  환경 존재 여부, authoritative inventory 및 독립 endpoint 근거를 보존합니다.
- [ ] 정상 Core 기준 하나를 복원하고 수집한 개정 번호가 계속 사용 가능하며 실패한 개정 번호가
  비활성임을 증명하는 protected 서비스 적용 및 자동 롤백 증적을 보존합니다.
- [x] 계획 `33965356996`, 요청 `33965478498`, 적용 `33965498775` 및 이슈 #454에 첫 번째
  Bot 요청 Core 서비스 적용과 독립된 사람의 Environment 승인 증적을 보존했습니다.
- [ ] 문서화된 자동 artifact 승격, traffic-split canary, SLO 롤백 및 콘솔 blue/green
  흐름을 집중 테스트와 통제된 런타임 증적으로 구현합니다.

## 환경(Environments)

승격은 **단방향** (`dev → staging → prod`) 이며 **아티팩트 단위** 입니다: staging을
통과한 동일한 서명된 이미지가 prod로 승격됩니다 - 절대 환경별로 재빌드하지 않습니다.
Staging은 prod 토폴로지를 미러링하여 shadow 평가가 대표성을 갖도록 합니다.

| 환경 | 목적 | 자율성 수준 |
|------|------|-------------|
| `dev` | 개발 및 통합 검증 | 권위 있는 승격 상태, 동일한 risk/HIL 게이트 |
| `staging` | pre-prod 검증, 신규 규칙/액션 shadow 평가 (prod 미러) | shadow, 선택적 강제 적용 |
| `prod` | 라이브 운영 | 저위험은 강제 적용; 고위험은 HIL |

- 환경별로 설정이 다름; **소스에 환경 값 없음** - 모두 런타임 주입.
- 배포는 코어 편집 없이 환경 구성을 제공합니다. 환경은 기능을
  promote하거나 demote하지 않습니다. [ADR-0002](../architecture/decisions/0002-independent-runtime-axes-ko.md)를
  참조하세요.
- **콘솔과 실행기는 별개 신원으로 배포** - 콘솔은 읽기 전용이며 실행기의 privileged
  Managed Identity를 절대 보유하지 않음
  ([security-and-identity-ko.md](../architecture/security-and-identity-ko.md) 참조).

## Infrastructure as 코드

- 모든 인프라는 `infra/` 에 정의(Terraform 주, Azure-only 부분은 Bicep 선택). **코어 엔진은
  CSP-중립 유지**; 벤더 특이 IaC는 런타임 어댑터와 동일한 프로바이더 경계 뒤에 있습니다.
- **상태 관리**: 앱 계층은 원격 백엔드 + locking + **환경별 상태 격리**를 사용합니다.
  첫 `infra/bootstrap/` 적용은 상태 백엔드를 만들기 때문에 로컬 상태를 사용합니다. 백엔드와
  VNet 실행기가 준비되면 초기화 상태를 전용 `ops/bootstrap/<environment>.tfstate` 키로
  이동합니다. 이동한 원격 키가 권위 상태이며, 로컬 출처는 계보, serial, 리소스 개수를
  검증할 때까지만 제한된 이행 백업으로 유지합니다.
- **독립 서비스 상태 전환**: 각 런타임 서비스는 별도 백엔드 키를 사용합니다. 이행
  도구는 두 상태를 모두 백업하고 선언된 주소 하나를 이동합니다. 출처에 copy가 0개이고
  대상에 정확히 1개일 때만 전환을 수락합니다. 이전 방식 배포 계획 게이트는 migrated
  출처 주소의 이후 생성, 갱신, replacement, 삭제를 차단합니다. Protected 서비스 계획과
  성공한 적용은 작업 전후 peer 상태 4개를 모두 pull합니다. 각 peer의 정본 상태 다이제스트,
  serial, 계보 다이제스트 및 managed-resource 개수를 비교합니다. Raw 상태는 즉시 삭제하고
  업로드하지 않으며, 작업 흐름은 sealed peer-isolation 증적을 90일 동안 보존합니다.
- **최초 서비스 런타임 전환**: 상태 소유권을 이동한 뒤 첫 protected 계획은 명시적
  `initial_cutover` 모드를 사용합니다. Sealed 계획은 리소스 신원, platform, 워크로드
  신원, 리소스 한도, 시크릿 출처 이력, sidecar를 그대로 유지하면서 이전 방식 명령,
  환경, 시크릿 연결, 기본 탐색을 서비스 소유 계약으로 바꿀 수 있습니다.
  Core는 이미 활성화된 isolated-Executor 전환 표시를 제거할 수 있지만 어떤 서비스도
  권한을 추가할 수 없습니다. 이후 계획은 별도로 검토된 배포 모드가 추가되지 않는
  한 image-only 갱신으로 돌아갑니다. 서비스 계약에는 운영 항목 지점이 소비하는
  모든 환경 값이 포함됩니다. 예를 들어 Core는 protected 계획이 시작 검증을
  통과하기 전에 Azure 테넌트, 구독, 지역, PostgreSQL 호스트 및 데이터베이스를 연결합니다.
- **범위가 제한된 데이터베이스 호스트 연결**: 최초 전환 뒤 명시적
  `database_host_binding` 모드는 리소스 신원, 명령, 관련 없는 환경 값, 워크로드 신원,
  플랫폼, sidecar, 시크릿 및 롤백 필드를 유지하면서 비밀이 아닌 `POSTGRES_HOST` 환경
  연결과 아래의 정본 런타임 연결만 추가하거나 바꿀 수 있습니다. 역사적 `-readapi` suffix를 사용하는 기존 Operator workload는
  in-place 갱신 대상으로 유지하고 새 Operator 리소스는 계속 `-operator-api`를 사용합니다.
  입력을 구체화할 때 작업 흐름은 플랫폼 상태의 `postgres_fqdn` 출력에서 호스트 이름을
  확인하고 `database.host`만 덮어씁니다. Operator의 경우 보호된 `CONSOLE_DEFAULT_HOSTNAME`
  게시 연결을 사용하고 `cors_allow_origins`를 정규화된 단일 Static Web Apps HTTPS origin으로
  바꿉니다. 또한 플랫폼 상태에서 정본 기본 유입, pipeline-stage 및 Pantheon-object 토픽을 확인하고 Core, Operator 및
  document service의 소유 `event_topics` 필드만 덮어씁니다. 쓰기 전용 service tfvars 시크릿은 DSN 참조, 역할 및 기타 입력의 출처로
  남습니다. 관련 없는 현재 Operator channel edge와 플랫폼 신원은 정확한 service-state 재확인 결과에 따라
  보존합니다. 이전에 없던 `FDAI_EXECUTION_VENUE` 연결은 정확한 `deployed` 값으로만 채택할 수
  있습니다. Core는 정본 `fdai.notifications.delivery-receipts` 토픽을 한 번 추가할 수 있습니다.
  Guard는 비밀이 아닌 이 정확한 값만 허용하고 함께 발생하는 명령, 신원 또는 다른 환경 변경을
  모두 차단합니다. 모든 primary container 비교는 동등한 숫자 CPU 표현을 정규화하고 정확한 환경
  이름과 binding map을 사용합니다. 따라서 공급자 숫자 형식이나 Terraform 목록 순서만 바뀌어도
  잘못된 drift 결과가 생기지 않습니다. 차단 결과는 변경된
  binding 이름만 보고하고 값은 기록하지 않습니다.
- **성능 저하 상태의 Operator 복구 기준**: `degraded_recovery`는 Operator
  `database_host_binding` 계획에만 함께 사용할 수 있습니다. 이 모드는 허용되는 Terraform
  변경 범위를 넓히지 않습니다. Azure에 별도의 정상 개정 번호가 없으면 적용 전 수집은 현재
  개정 번호가 활성 상태이고, 프로비저닝을 완료했으며, 복제본 하나 이상으로 실행 중이고, 이미
  비정상 상태로 표시된 경우에만 해당 개정 번호를 사용할 수 있습니다. 계획과 컨텍스트는 명시적
  복구 의도를 봉인합니다. 적용 또는 상태 검증이 실패하면 롤백은 수집한 이미지, 컨테이너,
  sidecar, 시크릿 참조, 신원 및 플랫폼 계약을 정확히 복원합니다. 성능 저하 상태의 롤백은 복원된
  개정 번호가 동일하게 범위가 제한된 실행 상태에 도달한 경우에만 수락합니다. 배포는 계속 실패
  상태로 남고 롤백 근거를 보존합니다.
- **범위가 제한된 Core 모델 연결**: Core 전용 `model_binding_transition` 모드는 증명된
  resolved-model 다이제스트, 고정된 런타임 모드와 매니페스트 경로, 확인된 HTTPS
  엔드포인트 및 검증된 웹 검색 설정만 변경할 수 있습니다. 활성 Core revision은 이미 정본
  Event Bus topic 연결을 사용해야 합니다. 플랫폼의 모델 전용 계획은 상위 모델 모듈 전체가
  아니라 `azurerm_cognitive_deployment.capability` 리소스 컬렉션만 직접 대상으로 지정합니다.
  따라서 기존 계정과 역할 할당 리소스가 대상 확장을 통해 계획에 포함되지 않습니다. 계획은
  이 모드를 `database_host_binding` 및 정확한
  최초 notification receipt topic 추가와만 함께 사용할 수 있습니다. 각 guard는 전체 허용 목록을
  검증하고 호스트, topic 및 endpoint map은 권위 있는 platform state 출력에서 가져오며 봉인된
  배포 모드는 정확한 조합을 기록합니다. 검증된 endpoint map을 처음 추가하는 model binding이면
  증명된 model digest가 그대로일 수 있습니다. 신원, 권한, 시크릿, 명령 또는 관련 없는 환경
  변경은 허용되지 않습니다.
- **범위가 제한된 Core 근거 연결 도입**: Core 전용
  `core_evidence_bindings_transition` 모드는 이전에 없던 의사 결정 근거 저장소와 운영 의도
  원본 연결만 추가할 수 있습니다. 최초 전환, 데이터베이스, 모델, 채널 edge 및 SharePoint
  전환과는 별도로 실행합니다. 가드는 HTTPS Blob 컨테이너 URL 하나, `/app/config/` 아래의
  경로, 정확한 개정, SHA-256 콘텐츠 다이제스트, 양의 rollout 세대 및 운영 의도 유형 6개의
  정확한 양의 개수를 요구합니다. 선택적 재검증 간격은 8시간 이하로 제한합니다. 봉인된 배포
  모드와 이전의 정상 개정은 롤백을 보존하며, 명령, 신원, 시크릿, 권한, 재연결, 제거 및 관련
  없는 환경 변경은 계속 차단합니다.
- **측정 원장 소유권**: Core는 `SELECT, INSERT` 권한만 사용해 `llm_invocation` 레코드를
  소유하고 추가합니다. Operator는 같은 테이블을 `SELECT` 권한으로만 사용합니다. 서비스
  migration graph는 Operator를 읽기 전용 consumer로 취급하고 Operator 측정 grant가
  제거될 때까지 provider rollback을 차단합니다. Provider와 consumer migration은 모두
  `PUBLIC` 접근을 revoke하며 두 runtime 모두 update 또는 delete 권한을 받지 않습니다.
  Core는 준비 상태 전에 incident lifecycle 상태를 다시 구성한 뒤 준비 상태로 게이팅되는
  background worker에서 영속 A2 알림을 재생합니다. 느리거나 사용할 수 없는 알림 subscriber는
  관련 없는 Core 시작을 차단하지 않습니다. 전송 checkpoint가 replay idempotency를 유지하고,
  transient 전달 실패는 권한을 부여하지 않은 채 재시도합니다. Incident lifecycle recovery는
  index가 있는 `audit_log.action_kind` 경로를 읽고 partial index를 concurrently 생성해 active audit writer를 계속 사용할 수 있게 합니다.
  이후 준비 상태 새로 고침에서 예외가 발생하면 보호된 처리를 즉시 닫지만, 복구 가능한 연결,
  timeout, 운영 체제 또는 PostgreSQL operational error일 때는 Core를 종료하지 않습니다.
  Supervisor는 가장 이른 근거 만료 시점보다 늦지 않게 다음 검사를 예약하고 재평가 전에 처리를
  닫으며 진단을 위해 이전 보고서를 유지합니다. Programming error는 준비 상태를 닫은 뒤 계속
  전파하고, 완전한 새로 고침이 성공해야만 처리를 다시 엽니다.
- **표류 감지**: 환경별로 예약된 읽기 전용 새로 고침 계획은 이전 방식 platform 루트, 독립
  서비스 루트 5개, 초기화 루트를 모두 검사합니다. 새로 고침 전용 계획은 라이브 리소스와 마지막
  적용 상태를 비교하며, 전달 시점에만 사용하는 기능 입력 누락을 삭제 의도로 해석하지 않습니다.
  보호된 배포 계획은 코드 및 배포 구성과 상태의 차이를 별도로 확인합니다. 표류 workflow 또는
  상태 파서가 변경되면 `main`에서도 이 읽기 전용 검사를 시작하므로 별도 전달 없이 감지기를
  검증할 수 있습니다. 루트 계약은 서로 다른 백엔드 키를 사용하고 새로 고침 전 상태에서 서비스
  이미지를 해석하므로 대역 외 이미지 변경도 드러납니다. 상태나 입력이 없거나 근거를 읽을 수
  없거나 표류가 발견되면 실행이 실패합니다. 표류는 자동으로 적용되지 않습니다.
- 프로비저닝 리소스 - **최소 비용 효율 세트** (전체 인벤토리 + 티어 결정은
  [deploy-and-onboard-ko.md](deploy-and-onboard-ko.md#azure-resource-inventory-minimum-set);
  인벤토리는 [csp-neutrality-ko.md](../architecture/csp-neutrality-ko.md) 의 CSP-중립 계약을 렌더링):
  - **Container Apps 환경** (Consumption) 에서 실행되는 **하나의 control-loop 코어
    Container App** 으로 `event-ingest` + `trust-router` + `executor`
    + `audit-writer`, 런타임이 이식 가능하도록 **OCI 이미지 + Knative 호환 매니페스트 서브셋**
    에서 배포 ([csp-neutrality-ko.md § 런타임 계약](../architecture/csp-neutrality-ko.md#2-런타임-계약--oci-이미지--knative-호환-매니페스트)).
    Core에는 sidecar/유입이 없습니다. 명시적 선택 Operator API, 공개 인제스트 API, ClamAV
    sidecar를 가진 내부 인제스트 워커 및 Isolated 실행기는 별도 Container App입니다.
    실행기 앱은 유입이 없고 기본 배포는 shadow-only를 유지합니다. 명시적 SD-08
    전환이 게이트웨이 호출자 권한과 액션 신원을 Core에서 이동합니다.
  - **Container Apps Jobs** (같은 환경) 로 스케줄 프로브, 경량 트리거 및 범위가 제한된 배포
    준비를 실행하며 런타임 예약에서 Azure Functions를 대체합니다. Operator 배포는 schema
    migration Job을 먼저 실행한 뒤 별도의 digest-pinned Core-image Job으로 변경 불가능한 Rule
    및 Ontology 참조 projection을 기록합니다. 명시적 선택 개발 전용 FC1 Function App은
    예외이며, 비공개 리소스에 등록된 연산을 중계할 뿐 스케줄러나 control-loop 런타임이
    아닙니다.
  - **Event Hubs** (Standard 1-TU 이름 공간 샤드 2개, auto-inflate off) 를 **`:9093` 의
    Kafka 엔드포인트 로만** 소비 - CSP-중립 이벤트 버스 계약
    ([csp-neutrality-ko.md § 이벤트버스 계약](../architecture/csp-neutrality-ko.md#1-이벤트버스-계약--kafka-와이어-프로토콜)).
    기본 샤드는 통제된 유입, 해당 DLQ, HIL, 파이프라인 단계를 소유합니다. Operational
    샤드는 canary + DLQ, 시작 round-trip, raw 인벤토리, 실행기 명령 + DLQ 및 실행기
    증적 개체를 소유하며 Standard 계층의 이름 공간당 개체 10개 제한을 지킵니다.
    구독 리소스 쓰기/삭제는 managed-identity Event Grid 구독이
    `fdai.inventory.raw`로 forward합니다. 독립 Service Bus와 custom Event Grid 토픽은 없습니다.
  - **PostgreSQL Flexible Server** (Burstable B1ms, 1 영역, 7일 백업) 을 감사 + KPI +
    패턴 라이브러리 + **pgvector** T1 임베딩의 단일 저장소로.
  - **비공개 StorageV2 case-history 계정**에 Shared Key 비활성화, Blob versioning,
    soft 삭제, 범위가 제한된 버전 수명 주기, 전용 non-executor 워크로드 신원, 비공개 엔드포인트를
    적용합니다. 내용 기반 주소를 가진 사례 개정 번호를 저장하고 PostgreSQL에는 rebuildable hot
    인덱스만 유지합니다.
  - **Key Vault** 를 시크릿 백엔드 로, 앱은 **Container Apps native 시크릿 + Key Vault
    참조** 를 통해 소비 - 앱은 env vars 만 읽고 시크릿 SDK 를 가져오기 하지 않음
    ([csp-neutrality-ko.md § 시크릿 계약](../architecture/csp-neutrality-ko.md#3-시크릿-계약--환경변수--k8s-secret)).
  - **여러 User-assigned Managed Identity** + 범위된 롤 할당, `WorkloadIdentity` 인터페이스
    (OIDC 토큰) 로 코어에 노출 - [security-and-identity-ko.md](../architecture/security-and-identity-ko.md)
    및 [csp-neutrality-ko.md § 워크로드 아이덴티티 계약](../architecture/csp-neutrality-ko.md#4-워크로드-아이덴티티-계약--oidc-토큰) 참조.
    실행기, 인벤토리, canary, 세 버티컬 신원이 기본 배포되고 읽기/명령/isolated-
    실행기 shadow 전송 계층/인제스트 API/인제스트 워커/인제스트 이행/알림
    신원은 기능별 명시적 선택입니다. Shadow 전송 계층 신원에는 효과 역할이 없습니다.
  - **Log Analytics workspace + workspace-based Application Insights** (기본 30일 보존).
  - **Azure Container Registry** (Basic) 로 서명된 이미지.
  - 무료 티어 / 비-과금 요소: 명시적 선택 Static Web Apps (콘솔), 워크로드 신원 federation
    (CI/CD), 콘솔 SPA + API + 승인 봇의 앱 등록. Azure Bot은 다운스트림 Teams 채널이
    선택적으로 제공하며 업스트림 Terraform은 프로비저닝하지 않습니다
    ([user-rbac-and-identity-ko.md](../interfaces/user-rbac-and-identity-ko.md)).
- 명시적으로 연기: 별도 vector DB, 독립 Service Bus / 커스텀 Event Grid 토픽,
  Front Door / API 관리, secondary-region DR 리소스 (단계 4 - TBD).
- IaC는 CI에서 Terraform validate + pinned Trivy + Checkov로 스캔됩니다.

## CI/CD 파이프라인

![CI/CD 파이프라인. 주요 단계는 Pull Request, lint + repository gates, unit tests: T0 engine + risk gate, block merge/promotion, IaC + dependency + secret scan, build + SBOM + sign + attest, deploy same artifact to staging, shadow evaluation + regression, promote code?, deploy same image to prod, enable enforce?, enforce per action입니다.](../../diagrams/generated/fdai-roadmap-deployment-deployment-01.ko.svg)

- **CI 신원**: 파이프라인은 **단명, OIDC-federated** 신원으로 인증(장기 클라우드 키 CI에
  없음). 시크릿은 런타임에 시크릿 저장소에서 pull, 로그·빌드 아티팩트에 **절대 쓰지 않음**
  (시크릿 검사가 머지를 게이팅).
- **PR 패키징 검사**: `.github/workflows/container-supply-chain.yml`은 Dockerfile, 기본 이미지
  고정값, 의존성 메타데이터, 빌드 보조 도구 또는 패키지에 포함되는 자산이 바뀔 때만 영향을
  받는 이미지를 빌드하고 검사합니다. 일반 Python 소스, 단위 테스트, 패키지 문서 변경은 이미지
  빌드를 실행하지 않습니다. 공용 잠금 파일, 작업 영역 메타데이터, 빌드 재정의 및 알 수 없는
  서비스 입력은 안전을 위해 모든 이미지를 선택합니다. 패키지에 포함되는 시나리오를 비롯한
  런타임 자산은 해당 소비자 검사를 유지합니다. 포크 PR을 포함한 모든 PR 작업은 호스팅된
  실행기에서 읽기 전용으로 실행되며 시크릿을 사용하지 않습니다. 이미지 게시, 릴리스 SBOM
  생성 또는 증명은 수행할 수 없습니다.
- **명시적 이미지 후보**: 전체 빌드, 검사, 게시, 소프트웨어 구성 명세서(SBOM) 및 출처 증명은
  보호된 `main`에서 명시적으로 승인한 `workflow_dispatch`로만 실행합니다. 일반 `main` 푸시와
  버전 태그는 이미지를 게시하지 않습니다. `commit_sha`는 해당 작업 흐름 실행의 `github.sha`와
  같아야 하며 과거 개정 번호나 다른 참조의 빌드는 지원하지 않습니다. 보호된 작업 흐름
  검증기는 입력 검증 코드나 후보 소스 체크아웃보다 먼저 실행됩니다. 푸시된 SHA의 필수 CI와
  배포 사전 검증은 별도의 릴리스 요구 사항으로 유지됩니다.
- **이미지 선택**: `images`는 필수이며 기본값이 없습니다. 대상을 쉼표로 구분해 입력합니다:
  `core-control-plane`, `cost-governance`, `operator-service`, `document-ingestion-api`,
  `document-processing-worker`, `isolated-executor`, `system-knowledge-service`.
  `fdai-` 접두사가 붙은 이미지 이름도 사용할 수 있습니다. 런타임 서비스를 선택하면 기본
  이미지만 선택되며 선택적 Cost Governance 프로필은 별도로 선택해야 합니다. 모든 이미지가
  필요한 경우에만 `all`을 단독으로 사용하세요. 빈 입력, 알 수 없는 대상, 중복 대상 또는
  다른 대상과 함께 입력한 `all`은 빌드 전에 실패합니다. 예를 들어
  `images=operator-service,document-ingestion-api`는 두 후보 이미지만 게시합니다.
- **감독되는 호출 경로**: Genesis는 이미지 해석기가 사용하는 세 이미지만 요청합니다. 성공한
  실행을 재사용하려면 후보 실행 메타데이터가 이 집합을 포함해야 하며, PR이나 일부 집합의
  성공으로 대신할 수 없습니다. 해석기는 각 다이제스트와 증명을 계속 독립적으로 검증합니다.
- **후보 근거**: 선택한 빌드는 게시 전과 정확한 게시 다이제스트 검사에서 모두
  MEDIUM/HIGH/CRITICAL Trivy 발견 사항을 차단합니다. 각 이미지는 CycloneDX SBOM 근거,
  빌드 출처 증명 및 SPDX SBOM 증명을 보존하며 Core는 해석된 모델 자료의 다이제스트도
  연결합니다. 기본 이미지는 다이제스트로 고정하고 uid 65532로 실행합니다. Core 빌더는 wheel
  설치 후 운영 부트스트랩을 처음 가져오므로 런타임 의존성이 없으면 게시를 차단합니다.
  배포는 롤아웃 전에 정확한 소스 개정 번호, 신뢰하는 서명 작업 흐름, 증명 및 이미지
  다이제스트를 계속 검증합니다.
- **근거 재사용**: 배포 검증기가 소스와 근거를 수락하면 일치하는 기존 검증 다이제스트를
  다시 빌드하지 않고 승격합니다. 적용되는 최신성 요건과 정책을 다시 확인합니다. 로컬 검증
  캐시, PR 검사 또는 이미지 태그만으로는 배포 권한을 얻을 수 없습니다.
- **아티팩트 레지스트리**: 이미지와 그 SBOM/증명을 명시적 보존 정책으로 유지하여 어떤
  prod 개정 번호도 추적·재검증 가능.
- **ACR 인계**: 업스트림 GHCR은 범용 build-evidence 레지스트리입니다. ACR이 필요한 포크는
  재구축 없이 검증된 이미지를 copy하여 다이제스트를 유지하고 target-registry 증명을
  생성하거나 복사한 뒤 해당 ACR 다이제스트를 ARB 근거 매니페스트의
  `signed-image-provenance`로 연결합니다. ACR용 두 번째 빌드는 다른 대상을 만들기 때문에
  수락하지 않습니다. Private-runner 실행기 계획은 하나의 출처 개정 번호를 attested GHCR
  다이제스트로 해석합니다. OCI 검증은 workflow 토큰을 프로세스 내부에서 mode 0700의 일시적
  Docker 구성 안의 mode 0600 파일로 렌더링하고 프로세스 인자나 출력에 넣지 않으며 단계가 끝날 때
  자격 증명 디렉터리를 제거합니다. 계획은 명시적 승격
  입력이 있을 때만 해당 exact 대상을 가져오기하며 ACR Terraform 출력 또는 검증된 배포 Job
  이미지를 정확한 Azure login host로 정규화합니다. 이후 ACR 다이제스트가 동일한지 검증하고
  Terraform에 연결합니다. Exact 적용은 protected 계획에 기록된 이미지를 promote하거나 교체할
  수 없습니다.
  보호된 OI-12 연결은 인벤토리 Job, 이력 Job, 보관 컨테이너 URL의 플랫폼 최상위 출력을 우선
  사용합니다. 배포된 상태가 해당 출력보다 오래된 경우에는 64개 리소스 한도 아래에서
  `Microsoft.App/jobs`만 열거하고 각 리소스를 안정 Container Apps `2024-03-01` API로 최대
  30초 동안 조회합니다. 리소스 그룹 출력이 비어 있으면 고유한 인벤토리 및 이력 런타임 계약이
  공급자가 관측한 동일한 그룹을 보고해야 작업 흐름이 해당 그룹을 채택합니다. 비어 있지 않은
  최상위 출력은 선택한 ARM 런타임과 일치해야 합니다. fallback은 이름 패턴으로 Job 신원을
  유추하지 않으며 단계가 끝난 뒤 프로바이더 출력을 보존하지 않습니다.
  Job 해석, 정확한 OCI 출처 증명 검증, ACR 연결은 별도의 보호된 단계에서 실행합니다. 정확히
  검증된 저장소, 개정 번호, 다이제스트만 작업 환경을 통해 검증 단계에서 연결 단계로 전달합니다.
  인벤토리 새로 고침은 검토된 실제 Job 템플릿으로 안정 ARM 시작 작업을 호출하고 정식
  `inventory` 컨테이너 이미지만 바꿉니다. 컨테이너 이름, 명령, 환경을 교체하는 CLI 이미지
  단축 경로는 사용하지 않습니다.
- **승격 게이트 체크리스트** (모두 통과 필수): T0-engine과 risk-gate 단위 테스트가 커버리지
  바에서 green; IaC + 의존성 + 시크릿 스캔 클린; shadow 평가에서 **정책 위반 escape 0**
  + 회귀 스위트 통과; staging SLO 건강.
- 새로운 자율 액션의 **강제 적용 승격**은 **별도의 명시적 승인** - 코드 배포가 강제 적용을
  자동 활성화하지 않음(기본은 shadow 유지,
  [security-and-identity-ko.md](../architecture/security-and-identity-ko.md) 참조).

## 점진 딜리버리(Progressive 전달, 목표 상태)

Traffic-split canary 전략은 아직 자동 배선되지 않았습니다. Platform deploy 작업 흐름은 단일
개정 번호를 적용한 뒤 canary 발행기 smoke를 실행합니다. 반면 독립 서비스 작업 흐름은 exact
적용 전에 정상인 활성 개정 번호와 이미지를 수집하고 비활성 개정 번호 1개를 보존하며, 새 리소스
id, 구독, 컴포넌트 tag, 이미지 다이제스트 및 개정 번호를 검증합니다. Immediate 상태 검사가
실패하면 복구 개정 번호를 자동 생성하고 검증합니다. 비정상 기준은 적용을 차단합니다. SLO 구간
트래픽 롤백은 계속 목표 설계입니다.

- **Core (Container Apps revisions)**: 트래픽 스플릿에 의한 **canary**. 단계로 승격(예: 5% →
  25% → 100%) 하며 헬스 신호로 게이팅. SLO burn, 에러율 급증, 가드 메트릭 상승 시 **자동
  롤백**([goals-and-metrics-ko.md](../architecture/goals-and-metrics-ko.md)).
- **Console (정적 호스팅)**: **blue/green** - 새 버전을 기존 옆에 게시하고 원자적으로 컷오버.
  읽기 전용이며 상태 없음.
- **DB 마이그레이션**: **expand/계약**, 전방향 전용. 추가 스키마 먼저 배포, 양쪽 형태를
  허용하는 코드 배포, 이후 릴리스에서 옛 형태 제거. 마이그레이션은 앱 개정 번호가 트래픽 받기
  **전에** 게이트된 스텝으로 실행되고, 개정 번호 롤백이 스키마를 깨지 않도록 하위 호환되는
  상태를 유지합니다. Online Alembic 실행은 database-scoped 트랜잭션 잠금으로 개정 번호 확인,
  DDL 및 version-row 갱신을 직렬화하므로 동시 시작 또는 테스트 워커가 같은 개정 번호를
  두 번 적용하지 않습니다. 연결은 10초 안에 실패하고 잠금 대기는 5분 안에 실패하며 protected
  migration 단계는 20분 안에 종료됩니다. 2시간 배포 예산이 첫 migration deadline이 되지 않습니다.
  Operator migration이 성공하면 배포는 별도의 Core-image Job을 실행해
  변경 불가능한 리포지토리 catalog projection을 결정론적으로 새로 고칩니다. 이 행은 검토된 참조
  선언을 설명할 뿐 finding, inventory, incident, readiness 또는 실행 권한을 만들지 않습니다.

## 릴리스와 롤백(release and Rollback)

모든 자율 액션은
[architecture.instructions.md](../../../.github/instructions/architecture.instructions.md) 의
7개 안전조건(stop-condition, 롤백 경로, blast-radius 한도, 예행 실행, 리소스 잠금,
멱등성, 감사 항목)을
운반합니다; 배포 롤백은 액션당 롤백을 대체하지 않고 보완합니다.

- **애플리케이션 롤백**: 독립 서비스 배포는 정상인 활성 롤백 기준만 수락하고 비활성 개정 번호
  1개를 보존합니다. Immediate 상태 실패 뒤 정확히 수집한 개정 번호와 digest-pinned 이미지를
  복원하고 복구 개정 번호를 검증한 다음 실패한 개정 번호를 비활성화하고
  비활성 상태를 확인한 뒤 배포를 실패로 닫습니다. Core 이미지를 변경할 때는
  `FDAI_SOURCE_REVISION`도 정확한 보호 커밋에 결속합니다. 고정 Azure Heimdall 복구 관찰자는
  명시적 `core_evidence_bindings_transition`을 통해 한 번만 추가할 수 있으며, 신원 재결속이나
  관련 없는 환경 표류가 있으면 계획을 차단합니다. Isolated 실행기는 전환 설정도 선언된
  `core-in-process` 권한 대체 경로로 되돌립니다.
- **인제스트 토폴로지 롤백**: 소비자 그룹이나 오프셋을 변경하지 않고 Document Ingestion
  API와 Document Processing Worker의 정확한 이전 개정 번호 및 digest-pinned 이미지를
  복원합니다. 제거된 `ingestion_cohost_worker` 입력은 계획 전에 거부됩니다.
- **액션 롤백**: PR-네이티브 액션은 git으로 되돌림; stateful 액션(예: DB DR)은 액션당 롤백 경로
  (스냅샷/복제본 복원)를 따르고 종료 전에 액션의 stop-condition에 대해 **복원을 검증**.
- **Rule-catalog 롤백**: 규칙은 catalog-as-code이며 버전 관리; 나쁜 규칙 세트는 업데이트
  파이프라인으로 되돌림. 규칙 세트 승격은 **회귀 스위트가 escape 0으로 통과** 를 요구; 실패한
  회귀는 승격을 블록하거나 규칙 세트를 강등 (
  [phase-2-quality-and-t1-ko.md](../phases/phase-2-quality-and-t1-ko.md) 참조).

## 컨트롤 플레인 재해 복구(Disaster 복구)

컨트롤 플레인은 다른 대상을 remediate하는 것뿐 아니라 자신도 복구해야 합니다. 정본
[컨트롤 플레인 재해 복구 설계](control-plane-disaster-recovery-ko.md)는 active-passive 프로파일,
single-writer 복구 에포크, 기본 fencing, 상태와 이벤트 복구, failback 및 근거
게이트를 정의합니다.

Dead-letter 큐만으로 regional 이벤트 복구를 수행할 수 없습니다. Event Hubs 메타데이터
disaster 복구는 이벤트 데이터를 복제하지 않으며 PostgreSQL geo-redundant 백업은 원격
point-in-time 복원이 아닙니다. 각 운영 배포는 명시적 이벤트 출처, 데이터 복구
방법, numeric RPO/RTO, 트래픽 strategy 및 측정된 장애 조치/failback 훈련 근거를
연결합니다.

## 관측성, SLO, 알림

- **원격측정**: OpenTelemetry 트레이스/메트릭/로그가 KPI 대시보드(metrics 1-4 및
  [goals-and-metrics-ko.md](../architecture/goals-and-metrics-ko.md) 의 가드 메트릭) 에 공급; 모든 자율 액션은
  상관 id 있는 감사 기록과 KPI 이벤트를 발행.
- **SLO**: 컨트롤 플레인 SLO 정의 (티어당 이벤트 처리 지연, 액션 성공률, 콘솔 가용성) + **에러
  예산**; SLO burn이 progressive-delivery 롤백에 공급.
- **알림**: 두 라인 - **운영** 알림(파이프라인 실패, IaC 표류, DLQ 깊이, SLO burn,
  검증기 실패율) 은 on-call로; **HIL** 알림은 고위험 승인을 Teams 채널로.
- **On-call과 런북**: 롤백, DR 장애 조치, DLQ 배출, 표류 조정에 대한 런북 유지. ChatOps
  다운 시 고위험 HIL 항목은 **큐잉되고 대체 경로로 알림** ; 승인 없이 auto-execute 없음.

## 비용 자세(비용 자세)

아래의 모든 비용 주장은 **측정된 베이스라인에 대해 검증할 방향 목표**
([goals-and-metrics-ko.md](../architecture/goals-and-metrics-ko.md)) 이지 보장이 아닙니다.

- 코어는 검증된 Kafka scaler가 없으므로 기본 1 복제본을 유지합니다. Scheduled 작업만 실행
  사이에 scale-to-zero합니다.
- 이벤트의 **작은 소수 (~5-10%)** 만 프론티어 모델에 도달하도록 설계; 토큰 예산이 지출 상한을
  두고 초과는 uncapped inference가 아니라 HIL로 강등.
- OSS 컴포넌트(OPA, IaC 스캐너, OpenCost, Chaos Mesh)가 per-seat 라이선스 비용 회피.

## 미결 결정(열림 Decisions)

- [x] IaC 엔진 - **해결: Terraform**. Bicep과 OpenTofu는 호환 대안이며 현재 배포 그래프는
  `infra/` HCL이 소유합니다([tech-stack-ko.md](../architecture/tech-stack-ko.md) 참조).
- [x] Compute 대상 - **해결: Azure Container Apps + Jobs**. AKS는 custom networking,
  DaemonSet, GPU 같은 측정된 요구가 생길 때만 재검토합니다.
- [ ] 강제 적용 승격을 위한 canary 스텝 함수와 자동 롤백 임계값.
- [x] Azure 원격 상태와 신원 - **해결: 비공개 Storage 백엔드 + VNet 자체 호스팅 실행기에
  연결된 안정적인 배포 UAMI**, 환경별 상태 키. 비-Azure 대상의 per-CSP 신원은 TBD;
      [구현 Focus](../../../.github/copilot-instructions.md#implementation-focus-must)
      와 [security-and-identity-ko.md](../architecture/security-and-identity-ko.md) 참조).
