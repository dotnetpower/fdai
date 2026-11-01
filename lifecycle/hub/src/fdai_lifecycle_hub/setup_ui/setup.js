"use strict";

(() => {
  const en = {
    skip: "Skip to setup", local: "Local setup", language: "Language", eyebrow: "INSTALLATION",
    title: "Set up FDAI in Azure",
    intro: "Connect your Azure account, choose an installation target, and review each exact plan before applying it.",
    standalone: "This local Hub starts without an FDAI Runtime or PostgreSQL.",
    stepConnect: "Connect Azure", stepTarget: "Choose target", stepReview: "Review & apply", stepReady: "Ready",
    status: "Installation status", refresh: "Refresh status", connecting: "Connecting",
    initializing: "Opening your authenticated setup session...", request: "Request", action: "Action",
    errorCode: "Error code", account: "Connect Azure",
    loginHelp: "Microsoft browser sign-in opens on the machine running this Hub. Complete sign-in there, then return here and list subscriptions. Never enter credentials on this setup screen.",
    tenant: "Azure tenant ID or domain (optional)",
    tenantHelp: "Leave blank to use your active Azure CLI tenant, or enter a tenant ID or domain before signing in.",
    deviceCode: "Use device code sign-in (for SSH or headless terminals without a local browser)",
    invalidTenant: "Enter a valid Azure tenant ID or domain.",
    orderedLifecycle: "ORDERED LIFECYCLE", stagesTitle: "Setup stages",
    login: "Sign in to Azure", accounts: "List subscriptions", configure: "Choose your installation",
    subscription: "Azure subscription", noAccounts: "List subscriptions to choose a target",
    subscriptionHelp: "Only subscriptions returned by your authenticated Azure session appear here.",
    region: "Azure region",
    regionHelp: "Enter the supported Azure location name for your target, using lowercase letters and digits.",
    cost: "Monthly cost ceiling (USD)", costHelp: "A planning limit, not a billing cap or a cost estimate.",
    workload: "Workload token (optional)",
    workloadHelp: "Leave blank to auto-select a non-colliding name (such as fdai or fdaiboot).",
    approvalMode: "Checkpoint approval mode",
    approvalContinuous: "Continuous non-destructive (recommended)",
    approvalStepwise: "Review every checkpoint manually",
    approvalModeHelp: "Destructive changes always pause for explicit confirmation.",
    invalidWorkload: "Enter a lowercase alphanumeric workload token (2-12 characters).",
    artifacts: "Installation artifacts", hubMode: "Signed prebuilt images",
    hubHelp: "Default. Verify Release Hub artifacts using an independently trusted public key. No source-build fallback.",
    sourceMode: "Build from a clean source checkout",
    sourceHelp: "Explicit source installation, independent of Release Hub images.",
    publicKey: "Trusted Release Hub public key (Ed25519 PEM)",
    keyWarning: "Verify this public key through an independent trusted channel. Never paste or upload a private key, credential, or secret.",
    keyFile: "Or read a public PEM file (maximum 4 KiB)",
    sourceRoot: "Clean checkout path on this Hub host",
    sourcePathHelp: "Use an absolute local path. The backend verifies the committed source before preparing the plan.",
    baselineTitle: "Existing AKS resource baseline",
    baseline: "The read-only-console runtime profile still deploys the existing AKS infrastructure and its supporting resources. It is not a reduced-cost runtime. Review the actual resources and cost evidence in each plan.",
    prepareHelp: "Preparation and non-destructive installation stages run continuously to completion once authorized. Only plans that delete or replace existing resources pause for extra confirmation.",
    prepare: "Authorize preparation", decision: "YOUR DECISION", review: "Review the exact plan",
    reviewHelp: "Approval applies only to this request, review, and digest. Read every detail before continuing.",
    reviewId: "Review", digest: "Plan digest", expires: "Expires",
    confirmation: "Type this exact confirmation", fillConfirmation: "Fill confirmation",
    expired: "This review has expired or its expiry cannot be verified. Refresh status and request a current plan before approving.",
    approve: "Approve this exact plan", decline: "Decline", recovery: "Inspect before resuming",
    recoveryHelp: "The job is not verified ready. Inspect the retained state, resolve the reported problem, then explicitly resume. Requests are never automatically replayed.",
    inspect: "Inspect retained state", resume: "Resume explicitly", reset: "Reset setup", readyTitle: "Installation verified ready",
    readyHelp: "The backend reports deployment readiness. Open Console only through the verified HTTPS destination below.",
    openConsole: "Open FDAI Console",
    copyConsoleUrl: "Copy Console URL",
    copiedConsoleUrl: "Copied!",
    hideCompletedStages: "Hide completed",
    showCompletedStages: "Show all",
    consoleUnavailable: "A safe HTTPS Console destination is unavailable. Inspect the deployment before continuing.",
    next: "Review, apply, verify",
    nextReview: "Review the actual plan, immutable digest, scope, and confirmation.",
    nextApply: "Approve each stage separately and follow its reported progress.",
    nextVerify: "Open Console only after authoritative readiness verification.",
    disconnect: "You can reconnect to observe the same job. Closing this page does not cancel it or submit another installation.",
    scope: "Installation scope",
    enrollment: "Installation does not enroll this target in managed lifecycle or prove managed-lifecycle readiness.",
    offline: "Offline installation is not supported in this screen. The existing signed offline CLI workflow remains unchanged.",
    footer: "Local session. Explicit approvals. Verified outcomes.",
    idle: "Not started", working: "Working", reviewPhase: "Approval required", ready: "Verified ready", unverified: "Readiness not verified",
    blocked: "Blocked", failed: "Failed", interrupted: "Interrupted", disconnected: "Status unavailable",
    observed: "Last checked", network: "Cannot contact the local Hub. No request was automatically retried. Refresh status before taking another action.",
    uncertain: "The request response was lost. Its outcome is unknown. Refresh status or inspect the retained state before resuming; do not submit another installation.",
    auth: "Setup authentication failed. Reopen setup from the Hub launcher to establish a local session.",
    invalid: "The Hub returned an invalid status. No action is available until a valid status is received.",
    requestFailed: "The Hub rejected the request. Refresh status and inspect the reported problem.",
    tooLarge: "The request exceeds 16 KiB. Shorten the supplied input.",
    invalidKey: "Provide only a public PEM key, no larger than 4 KiB. Private keys and credentials are not accepted.",
    invalidCost: "Enter a positive whole-number monthly cost ceiling in USD.",
    keyRead: "The public key file could not be read. Choose a readable public PEM file.",
    themeToggle: "Dark / Light",
    railRuntime: "Runtime", railDb: "Database", railRegion: "Region", railWorkload: "Workload",
    permVerified: "✓ Account & required permissions",
    permSummaryDefault: "Subscription Owner/Contributor, UAMI RBAC delegation, Entra ID apps/groups, and 18 Azure resource providers",
    showPermDetails: "Permission details ⌄", hidePermDetails: "Hide details ⌃",
    permSubTitle: "Subscription provisioning",
    permSubDesc: "Create ops/app resource groups, VNet, Bastion, AKS/ACA, PostgreSQL, and Key Vault (Owner or Contributor)",
    permUamiTitle: "Managed Identity RBAC delegation",
    permUamiDesc: "Assign Reader, AcrPull, and Key Vault Secrets User roles to workload identities (Owner or User Access Admin)",
    permEntraTitle: "Entra ID apps & RBAC groups",
    permEntraDesc: "Configure fdai-api, fdai-console-spa, and 5 role groups (aw-owners, aw-approvers, aw-contributors, aw-readers, aw-break-glass)",
    permRpTitle: "Azure Policy & 18 Resource Providers",
    permRpDesc: "No blocking Deny assignments; Microsoft.ContainerService, Microsoft.App, Microsoft.DBforPostgreSQL, Microsoft.KeyVault registered",
    permStateReady: "✓ Required", permStateVerified: "✓ Verified",
    runtimePlatformLabel: "Deployment runtime platform",
    runtimeAksTitle: "AKS (Azure Kubernetes Service)", recommendedTag: "Recommended",
    runtimeAksDesc: "Isolated executor, NetworkPolicy, full observability topology, and production baseline",
    runtimeAcaTitle: "ACA (Azure Container Apps)", compatTag: "Compatibility",
    runtimeAcaDesc: "Serverless managed Container Apps and Jobs without Kubernetes cluster management",
    databasePlacement: "Database placement",
    dbPostgresFlex: "PostgreSQL Flexible Server (recommended)",
    dbPostgresAks: "In-cluster AKS PostgreSQL (non-production)",
    dbHelp: "Managed PostgreSQL Flexible Server with pgvector and per-service roles.",
    stageColTitle: "STAGE", stageColTiming: "START ~ END · DURATION",
    configSummaryTitle: "✓ Target & connection summary",
    showConfigForm: "Show settings ⌄", hideConfigForm: "Hide settings ⌃",
  };
  const ko = {
    skip: "설정으로 이동", local: "로컬 설치 설정", language: "언어", eyebrow: "설치",
    title: "Azure에 FDAI 설치",
    intro: "Azure 계정을 연결하고 설치 대상을 선택한 다음, 각 단계의 실제 계획을 검토하고 승인하세요.",
    standalone: "이 로컬 Hub는 FDAI Runtime이나 PostgreSQL 없이 시작됩니다.",
    stepConnect: "Azure 연결", stepTarget: "설치 대상 선택", stepReview: "계획 검토 및 실행", stepReady: "설치 완료",
    status: "설치 상태", refresh: "상태 새로 고침", connecting: "연결 중",
    initializing: "인증된 로컬 설정 세션을 여는 중입니다...", request: "요청", action: "작업",
    errorCode: "오류 코드", account: "Azure 연결",
    loginHelp: "이 Hub를 실행하는 컴퓨터에서 Microsoft 로그인 창이 열립니다. 로그인을 완료한 다음 이 화면으로 돌아와 구독 목록을 조회하세요. 이 설정 화면에는 자격 증명을 입력하지 마세요.",
    tenant: "Azure 테넌트 ID 또는 도메인 (선택 사항)",
    tenantHelp: "비워 두면 현재 활성화된 Azure CLI 테넌트를 사용하며, 다른 테넌트로 로그인하려면 테넌트 ID 또는 도메인을 입력하세요.",
    deviceCode: "브라우저 없는 터미널/SSH 환경: 디바이스 코드로 로그인 (https://microsoft.com/devicelogin)",
    invalidTenant: "유효한 Azure 테넌트 ID 또는 도메인을 입력하세요.",
    orderedLifecycle: "순서가 지정된 수명 주기", stagesTitle: "구성 단계",
    login: "Azure 로그인", accounts: "구독 목록 조회", configure: "설치 대상 선택",
    subscription: "Azure 구독", noAccounts: "구독 목록을 조회한 후 대상을 선택하세요",
    subscriptionHelp: "인증된 Azure 세션에서 조회한 구독만 표시됩니다.",
    region: "Azure 지역", regionHelp: "대상에서 지원하는 Azure 위치 이름을 영문 소문자와 숫자로 입력하세요.",
    cost: "월 비용 상한 (USD)", costHelp: "계획 수립용 한도입니다. 청구 한도나 예상 비용이 아닙니다.",
    workload: "워크로드 토큰 (선택 사항)",
    workloadHelp: "비워 두면 충돌하지 않는 이름(fdai, fdaiboot 등)을 자동으로 선택합니다.",
    approvalMode: "체크포인트 승인 모드",
    approvalContinuous: "비파괴 단계 자동 연속 실행 (권장)",
    approvalStepwise: "모든 단계마다 수동 검토 및 승인",
    approvalModeHelp: "리소스 삭제·교체가 포함된 계획은 항상 별도 확인을 위해 일시 중지됩니다.",
    invalidWorkload: "영문 소문자와 숫자로 된 2~12자 워크로드 이름을 입력하세요.",
    artifacts: "설치 아티팩트", hubMode: "서명된 사전 빌드 이미지",
    hubHelp: "기본 방식입니다. 별도로 신뢰를 확인한 공개 키로 Release Hub 아티팩트를 검증합니다. 실패해도 소스 빌드로 자동 전환하지 않습니다.",
    sourceMode: "정리된 소스 체크아웃에서 빌드",
    sourceHelp: "Release Hub 이미지에 의존하지 않는 소스 설치를 명시적으로 선택합니다.",
    publicKey: "신뢰할 수 있는 Release Hub 공개 키 (Ed25519 PEM)",
    keyWarning: "독립적으로 신뢰할 수 있는 경로에서 공개 키를 확인하세요. 개인 키, 자격 증명, 비밀 값은 붙여 넣거나 업로드하지 마세요.",
    keyFile: "또는 공개 PEM 파일 읽기 (최대 4 KiB)", sourceRoot: "이 Hub 호스트의 정리된 체크아웃 경로",
    sourcePathHelp: "로컬 절대 경로를 입력하세요. 백엔드는 계획을 준비하기 전에 커밋된 소스를 검증합니다.",
    baselineTitle: "기존 AKS 리소스 구성",
    baseline: "read-only-console 런타임 프로파일도 기존 AKS 인프라와 지원 리소스를 배포합니다. 비용을 줄인 런타임이 아닙니다. 각 계획에서 실제 리소스와 비용 근거를 검토하세요.",
    prepareHelp: "준비 작업을 승인하면 리소스 삭제·교체가 없는 모든 설치 단계(01~15단계)가 중간 멈춤 없이 완료까지 자동으로 연속 실행됩니다. 기존 리소스를 삭제하거나 교체하는 경우에만 추가 승인을 요청합니다.",
    prepare: "준비 작업 승인", decision: "승인 검토", review: "실제 계획 검토",
    reviewHelp: "승인은 이 요청, 검토 항목, 다이제스트에만 적용됩니다. 모든 세부 정보를 읽고 진행하세요.",
    reviewId: "검토 항목", digest: "계획 다이제스트", expires: "만료 시각", confirmation: "다음 확인 문구를 정확히 입력하세요",
    fillConfirmation: "확인 문구 자동 입력",
    expired: "검토 항목이 만료되었거나 만료 시각을 검증할 수 없습니다. 상태를 새로 고치고 유효한 계획을 요청한 후 승인하세요.",
    approve: "이 계획만 승인", decline: "거절", recovery: "재개 또는 다시 설정",
    recoveryHelp: "작업이 중단되었거나 준비 완료가 검증되지 않았습니다. 저장된 상태를 점검해 재개하거나, 리소스 생성 전이라면 설정을 초기화해 다른 지역·대상을 선택하세요.",
    inspect: "저장된 상태 점검", resume: "작업 재개", reset: "설정 초기화 (다시 선택)", readyTitle: "설치 준비 완료 검증됨",
    readyHelp: "백엔드에서 배포 준비 완료를 보고했습니다. 아래의 검증된 HTTPS 주소로만 Console을 여세요.",
    openConsole: "FDAI Console 열기",
    copyConsoleUrl: "콘솔 주소 복사",
    copiedConsoleUrl: "복사됨!",
    hideCompletedStages: "완료 단계 접기",
    showCompletedStages: "전체 단계 보기",
    consoleUnavailable: "안전한 HTTPS Console 주소가 없습니다. 진행하기 전에 배포 상태를 점검하세요.",
    next: "검토, 적용, 검증", nextReview: "실제 계획, 변경 불가능한 다이제스트, 범위, 확인 문구를 검토합니다.",
    nextApply: "각 단계를 별도로 승인하고 보고된 진행 상황을 확인합니다.",
    nextVerify: "권위 있는 관측으로 준비 완료를 검증한 후에만 Console을 엽니다.",
    disconnect: "다시 연결해도 같은 작업을 조회합니다. 이 페이지를 닫아도 작업이 취소되거나 새 설치가 요청되지 않습니다.",
    scope: "설치 범위", enrollment: "설치만으로 이 대상이 관리형 수명 주기에 등록되거나 관리형 수명 주기의 준비 완료가 검증되지는 않습니다.",
    offline: "이 화면은 오프라인 설치를 지원하지 않습니다. 기존의 서명된 오프라인 CLI 설치 절차는 그대로 유지됩니다.",
    footer: "로컬 세션. 명시적 승인. 결과 검증.",
    idle: "시작 전", working: "진행 중", reviewPhase: "승인 필요", ready: "준비 완료 검증됨", unverified: "준비 완료 미검증",
    blocked: "차단됨", failed: "실패", interrupted: "중단됨", disconnected: "상태 조회 불가",
    observed: "마지막 조회", network: "로컬 Hub에 연결할 수 없습니다. 요청을 자동으로 재시도하지 않았습니다. 다른 작업을 실행하기 전에 상태를 새로 고치세요.",
    uncertain: "요청 응답을 받지 못해 결과를 알 수 없습니다. 재개하기 전에 상태를 새로 고치거나 저장된 상태를 점검하세요. 새 설치를 요청하지 마세요.",
    auth: "설정 세션 인증에 실패했습니다. Hub 실행기에서 설정 화면을 다시 열어 로컬 세션을 시작하세요.",
    invalid: "Hub가 유효하지 않은 상태를 반환했습니다. 유효한 상태를 받기 전에는 작업을 실행할 수 없습니다.",
    requestFailed: "Hub가 요청을 거절했습니다. 상태를 새로 고치고 보고된 문제를 점검하세요.",
    tooLarge: "요청이 16 KiB를 초과했습니다. 입력 내용을 줄이세요.",
    invalidKey: "최대 4 KiB의 공개 PEM 키만 입력하세요. 개인 키와 자격 증명은 허용되지 않습니다.",
    invalidCost: "월 비용 상한을 양의 정수로 입력하세요. 단위는 USD입니다.",
    keyRead: "공개 키 파일을 읽을 수 없습니다. 읽을 수 있는 공개 PEM 파일을 선택하세요.",
    themeToggle: "다크 / 라이트",
    railRuntime: "배포 런타임", railDb: "데이터베이스", railRegion: "대상 리전", railWorkload: "워크로드",
    permVerified: "✓ 로그인 계정 및 필요 권한 안내",
    permSummaryDefault: "구독 Owner/Contributor · UAMI RBAC 위임 · Entra ID 앱/그룹 · 18개 Azure 리소스 공급자",
    showPermDetails: "권한 상세 보기 ⌄", hidePermDetails: "상세 접기 ⌃",
    permSubTitle: "구독 리소스 프로비저닝 권한",
    permSubDesc: "운영/앱 리소스 그룹, VNet, Bastion, AKS/ACA, PostgreSQL, Key Vault 생성 (Owner 또는 Contributor)",
    permUamiTitle: "Managed Identity RBAC 위임 권한",
    permUamiDesc: "워크로드 UAMI에 Reader, AcrPull, Key Vault Secrets User 등 최소 권한 할당 (Owner 또는 User Access Admin)",
    permEntraTitle: "Entra ID 앱 및 5개 RBAC 그룹",
    permEntraDesc: "fdai-api, fdai-console-spa 등록 및 aw-owners·approvers·contributors·readers·break-glass 구성",
    permRpTitle: "Azure Policy 및 18개 리소스 공급자",
    permRpDesc: "차단 Deny 정책 없음 · Microsoft.ContainerService, Microsoft.App, Microsoft.DBforPostgreSQL, Microsoft.KeyVault 등록",
    permStateReady: "✓ 필수", permStateVerified: "✓ 검증 완료",
    runtimePlatformLabel: "배포 런타임 아키텍처 (AKS vs ACA)",
    runtimeAksTitle: "AKS (Azure Kubernetes Service)", recommendedTag: "권장 · 기본값",
    runtimeAksDesc: "격리된 실행기, NetworkPolicy, 전체 관측 토폴로지 및 프로덕션 표준 구성",
    runtimeAcaTitle: "ACA (Azure Container Apps)", compatTag: "호환성 모드",
    runtimeAcaDesc: "클러스터 관리 없이 서버리스 컨테이너 앱 및 Job으로 경량 실행",
    databasePlacement: "데이터베이스 배치",
    dbPostgresFlex: "PostgreSQL Flexible Server (권장)",
    dbPostgresAks: "AKS 클러스터 내부 PostgreSQL (비프로덕션)",
    dbHelp: "pgvector 및 서비스별 최소 권한 역할이 분리된 관리형 PostgreSQL Flexible Server입니다.",
    stageColTitle: "단계 (STAGE)", stageColTiming: "시작 ~ 완료 · 소요 시간",
    configSummaryTitle: "✓ Azure 연결 및 설치 대상 요약",
    showConfigForm: "설정 상세 보기 ⌄", hideConfigForm: "설정 상세 접기 ⌃",
  };
  const $ = id => document.getElementById(id);
  let savedLocale = "";
  try { savedLocale = localStorage.getItem("fdai_setup_locale") || ""; } catch { savedLocale = ""; }
  let locale = (savedLocale === "ko" || savedLocale === "en")
    ? savedLocale
    : (navigator.language.toLowerCase().startsWith("ko") ? "ko" : "en");
  let status = null, csrf = "", connected = false, pending = false, loading = false;
  let authenticating = false, sessionVersion = 0, statusTask = null;
  let timer = null, observedAt = null, reviewKey = "", accountKey = "", noticeKey = "", noticeDetail = "";
  const text = key => (locale === "ko" && ko[key]) || en[key] || en.requestFailed;
  const koMessages = {
    "Sign in to Azure to begin first installation.": "1단계에서 'Azure 로그인' 또는 '구독 목록 조회'를 눌러 시작하세요.",
    "Signed in. Select the intended subscription.": "Azure 연결이 완료되었습니다. 2단계에서 구독과 지역을 선택하고 '준비 작업 승인'을 누르세요.",
    "Available Azure subscriptions refreshed.": "사용 가능한 Azure 구독 목록을 불러왔습니다. 2단계에서 대상을 선택하세요.",
    "Request queued for the local customer executor.": "요청을 로컬 실행기에 전달했습니다. 사전 점검 및 계획 생성을 준비하고 있습니다...",
    "Decision submitted to the exact checkpoint.": "승인 결정을 전달했습니다. 승인된 단계를 실행하고 있습니다...",
    "Review this exact checkpoint before continuing.": "계획 생성이 완료되었습니다. 아래 '실제 계획 검토' 카드에서 확인 후 승인하세요.",
    "Setup configuration reset. Choose a subscription and region to start again.": "설정이 초기화되었습니다. 구독과 지역을 다시 선택해 진행하세요.",
    "No first-install configuration has been retained.": "저장된 설치 구성이 없습니다. 2단계에서 구독과 지역을 선택해 시작하세요.",
    "Retained installation exists. Explicitly resume to refresh plans and health.": "저장된 설치 구성이 있습니다. '작업 재개'를 눌러 진행하거나 '설정 초기화'로 다시 선택하세요.",
    "Retained installation preserved. Resume to refresh its exact target, plans and health.": "저장된 설치 구성이 유지되고 있습니다. '작업 재개' 또는 '설정 초기화'를 선택하세요.",
    "Executor stopped. Inspect private traces and retained evidence before resuming.": "실행기가 중단되었습니다. 상태를 점검한 뒤 재개하거나 '설정 초기화'로 다시 시작하세요.",
    "Independent health and zero-change acceptance completed.": "독립 상태 점검 및 Terraform 무변경 검증이 모두 완료되었습니다. 아래 '콘솔 열기' 버튼을 눌러 배포된 FDAI 웹 콘솔에 접속하세요.",
    "Installation is not accepted. Inspect retained private evidence before resuming.": "사전 점검(해당 리전 VM SKU/쿼터 제한 등)에서 차단되었습니다. '설정 초기화 (다시 선택)'를 누른 뒤 가용한 리전(예: westus3)을 선택하세요.",
  };
  const koStageDetails = {
    "Preparing the clean source snapshot": "1/5 소스 체크아웃 스냅샷 검증 및 준비 중",
    "Verifying source and tenant-local identity names": "2/5 테넌트 내 Entra ID 표시 이름 중복 검사 중",
    "Checking AKS SKU, quota, and PostgreSQL availability": "3/5 선택한 리전의 AKS VM SKU, 쿼터 및 PostgreSQL 가용성 점검 중",
    "Checking the public compute estimate": "4/5 리전 컴퓨트 예상 비용 산정 중",
    "Preparing the checksum-pinned Terraform executable": "5/5 해시 검증된 Terraform 실행 파일 준비 중",
    "Preparing Foundation inputs and the retained execution context": "Foundation 입력 및 Terraform 계획 컨텍스트 준비 중",
    "Verifying the handoff and preparing the source snapshot for Bastion transfer": "[13/15] 애플리케이션 및 Entra 계획 (12 단계 완료) · Bastion을 통한 배포 스냅샷 전송 준비 중",
    "Verifying the handoff and preparing the signed kit for Bastion transfer": "[13/15] 애플리케이션 및 Entra 계획 (12 단계 완료) · Bastion을 통한 서명 키트 전송 준비 중",
    "Converging the focused private data-plane access path": "[14/15] 애플리케이션 및 런타임 배포 (13 단계 완료) · 프라이빗 데이터 플레인 접근 경로 구성 중",
    "Converging policy-forced private access before effect recovery": "[14/15] 애플리케이션 및 런타임 배포 (13 단계 완료) · 테넌트 정책에 따른 프라이빗 엔드포인트 연결 구성 중",
    "Recovering the failed infrastructure apply without repeating its effect": "[14/15] 애플리케이션 및 런타임 배포 (13 단계 완료) · 프라이빗 엔드포인트 구성 후 인프라 상태 검증 중",
    "Recovering by verification, or planning private infrastructure": "[14/15] 애플리케이션 및 런타임 배포 (13 단계 완료) · 프라이빗 인프라(PostgreSQL·ACR·Key Vault) 계획 수립 중",
    "Applying the approved infrastructure plan and verifying its effects": "[14/15] 애플리케이션 및 런타임 배포 (13 단계 완료) · 프라이빗 인프라(PostgreSQL·ACR·Key Vault) 생성 및 검증 중",
    "Preparing and planning the private AKS runtime": "[14/15] 애플리케이션 및 런타임 배포 (13 단계 완료) · 프라이빗 AKS 런타임 클러스터 계획 수립 중",
    "Planning Container Insights association after AKS cluster creation": "[14/15] 애플리케이션 및 런타임 배포 (13 단계 완료) · AKS 클러스터 생성 완료 후 Container Insights 연결 중",
    "Importing runtime images and reading back their digests": "[14/15] 애플리케이션 및 런타임 배포 (13 단계 완료) · 컨테이너 런타임 이미지 빌드 및 ACR 가져오기 중",
    "No capability token; the keyless Trial opens after the application deploys": "[14/15] 애플리케이션 및 런타임 배포 (13 단계 완료) · 30일 평가판(Trial) 라이선스 모드 준비 중",
    "Running database migrations and materializing catalogs": "[14/15] 애플리케이션 및 런타임 배포 (13 단계 완료) · 데이터베이스 스키마 마이그레이션 및 카탈로그 적재 중",
    "Recovering by verification, or planning the application": "[14/15] 애플리케이션 및 런타임 배포 (13 단계 완료) · AKS 애플리케이션 워크로드 배포 계획 수립 중",
    "Applying the approved application plan and verifying its effects": "[14/15] 애플리케이션 및 런타임 배포 (13 단계 완료) · AKS 애플리케이션 및 콘솔 서비스 배포 및 검증 중",
    "Opening the Trial window at the installation's anchored creation time": "[15/15] 최종 상태 및 무변경 검증 (14 단계 완료) · 30일 평가판(Trial) 활성화 중",
    "Collecting and independently reading back the initial inventory": "[15/15] 최종 상태 및 무변경 검증 (14 단계 완료) · 초기 리소스 인벤토리 수집 및 검증 중",
    "Publishing or explicitly skipping the frozen catalog review": "[15/15] 최종 상태 및 무변경 검증 (14 단계 완료) · 카탈로그 검토 체크포인트 확인 중",
    "Checking service health and a second zero-change Terraform plan": "[15/15] 최종 상태 및 무변경 검증 (14 단계 완료) · 서비스 상태 응답 및 2차 Terraform 무변경 검증 중",
    "Registering the Console redirect and publishing verified static files": "[15/15] 최종 상태 및 무변경 검증 (14 단계 완료) · 콘솔 Entra 리디렉션 등록 및 정적 웹 앱 게시 중",
  };
  function localizeMessage(value) {
    if (!value || locale !== "ko") return value;
    if (koMessages[value]) return koMessages[value];
    const pfBlocked = value.match(/^Azure region '([^']+)' preflight blocked \((.+)\)\./);
    if (pfBlocked) {
      return `선택한 '${pfBlocked[1]}' 리전에서 사전 점검이 차단되었습니다 (사유: ${pfBlocked[2]} - 이 구독에서 해당 리전의 VM SKU가 제한되어 있습니다). 우측 '설정 초기화 (다시 선택)'를 누른 뒤 가용한 리전(예: westus3)을 선택하세요.`;
    }
    const groups = value.match(/^Existing FDAI resource groups \((.+)\) already exist in region '([^']+)'/);
    if (groups) {
      return `선택한 '${groups[2]}' 지역에 이미 FDAI 리소스 그룹(${groups[1]})이 존재합니다. '설정 초기화 (다시 선택)'를 누른 뒤 다른 지역을 선택하세요.`;
    }
    const stopped = value.match(/^Stage '([^']+)' stopped \(([^)]+)\)/);
    if (stopped) {
      return `'${stopped[1]}' 단계에서 일시 중단되었습니다 (사유: ${stopped[2]}). 아래 '보류된 작업 재개' 버튼을 눌러 완료된 단계 이후부터 이어서 진행하거나, 초기 상태라면 '설정 초기화 (다시 선택)'를 누르세요.`;
    }
    for (const [enPrefix, koPrefix] of Object.entries(koStageDetails)) {
      if (value === enPrefix) return `${koPrefix}...`;
      if (value.startsWith(`${enPrefix} - elapsed `)) {
        return `${koPrefix}... (경과 ${value.split(" - elapsed ")[1]})`;
      }
    }
    const tfMatch = value.match(/^"[a-z0-9_]+":\s*\d+(?:\s*-\s*elapsed\s+([0-9:]+))?$/);
    if (tfMatch) {
      return `[14/15] 애플리케이션 및 런타임 배포 (13 단계 완료) · 승인된 Terraform 리소스 변경 적용 중...${tfMatch[1] ? ` (경과 ${tfMatch[1]})` : ""}`;
    }
    const dcMatch = value.match(/^Device code sign-in: open (https:\/\/[^\s]+) and enter code ([A-Z0-9]+) to authenticate\.$/);
    if (dcMatch) {
      return `디바이스 코드 로그인: 브라우저에서 ${dcMatch[1]} 를 열고 코드 [${dcMatch[2]}] 를 입력해 인증을 완료하세요.`;
    }
    if (value.startsWith("[") && value.includes("] ")) {
      const koSubPhases = {
        "Application identity": "애플리케이션 Entra ID 구성",
        "Managed-host transfer": "관리형 실행기(Runner)로 배포 패키지 전송 중",
        "Private infrastructure": "프라이빗 인프라(PostgreSQL·ACR·Key Vault) 계획 및 배포 중",
        "AKS cluster and node pools": "AKS 클러스터 및 노드 풀 프로비저닝 중",
        "Runtime images": "컨테이너 런타임 이미지 빌드 및 ACR 가져오기 중",
        "Database placement": "데이터베이스 배치 구성 중",
        "Capability mode": "런타임 기능 및 라이선스 모드 설정 중",
        "Database and catalogs": "데이터베이스 마이그레이션 및 카탈로그 적재 중",
        "Application deployment": "AKS 워크로드 및 콘솔 서비스 배포 중",
        "Initial resource inventory": "초기 리소스 인벤토리 수집 및 검증 중",
        "Frozen catalog review": "카탈로그 검토 체크포인트 확인 중",
        "Health and zero-change plan": "서비스 상태 응답 및 Terraform 무변경 검증 중",
        "Cleanup and final receipt": "임시 전송 파일 정리 및 최종 영수증 기록 중",
      };
      let out = value.replace(" complete", " 단계 완료").replace("- elapsed ", "· 경과 ");
      const idxMatch = out.match(/^\[(\d{2})\/15\]\s+([^(]+)\((\d+\s*단계 완료)\)(.*)$/);
      if (idxMatch) {
        const stIdx = Number(idxMatch[1]) - 1;
        const stMeta = STAGE_CATALOG[stIdx];
        const koTitle = stMeta ? stMeta.koTitle : idxMatch[2].trim();
        let rest = idxMatch[4] || "";
        for (const [enSub, koSub] of Object.entries(koSubPhases)) {
          if (rest.includes(`- ${enSub}`)) rest = rest.replace(`- ${enSub}`, `· ${koSub}`);
        }
        return `[${idxMatch[1]}/15] ${koTitle} (${idxMatch[3]})${rest}`;
      }
      return out;
    }
    return value;
  }
  const STAGE_CATALOG = [
    { id: "toolchain", enTitle: "Toolchain prerequisites", enDesc: "Verify Terraform and CLI binaries", koTitle: "도구 체인 사전 점검", koDesc: "Terraform 및 실행 도구 해시 검증" },
    { id: "target", enTitle: "Azure target & quota check", enDesc: "Verify subscription, tenant, and VM/DB SKU quota", koTitle: "Azure 대상 및 쿼터 검증", koDesc: "구독·테넌트 권한 및 VM/DB SKU 가용성 확인" },
    { id: "source", enTitle: "Source snapshot verification", enDesc: "Verify clean committed source checkout", koTitle: "소스 스냅샷 무결성 검증", koDesc: "커밋된 소스 체크아웃 및 스냅샷 검증" },
    { id: "providers", enTitle: "Azure resource providers", enDesc: "Reconcile required Azure resource providers", koTitle: "Azure 리소스 공급자 확인", koDesc: "필수 Azure 리소스 공급자 등록 상태 확인" },
    { id: "policy", enTitle: "Tenant policy inspection", enDesc: "Inspect Azure Policy assignments in scope", koTitle: "테넌트 정책 경로 확인", koDesc: "구독 내 Azure Policy 할당 및 제약 확인" },
    { id: "route", enTitle: "Deployment route selection", enDesc: "Select private-runner foundation route", koTitle: "배포 경로 결정", koDesc: "프라이빗 실행기(Runner) 기반 배포 경로 설정" },
    { id: "runner-image-plan", enTitle: "Runner image plan", enDesc: "Online marketplace image selected (skipped)", koTitle: "실행기 이미지 계획", koDesc: "온라인 마켓플레이스 이미지 사용 (건너뜀)" },
    { id: "runner-image-apply", enTitle: "Runner image apply", enDesc: "Online bootstrap mode (skipped)", koTitle: "실행기 이미지 생성", koDesc: "온라인 부트스트랩 모드 사용 (건너뜀)" },
    { id: "foundation-plan", enTitle: "Foundation exact plan", enDesc: "Generate VNet, Storage, Bastion & Runner VM plan", koTitle: "Foundation 계획 생성", koDesc: "VNet·상태 저장소·Bastion·VM Terraform 계획 수립" },
    { id: "foundation-apply", enTitle: "Foundation exact apply", enDesc: "Provision ops RG, VNet, Storage, Bastion & Runner VM", koTitle: "Foundation 인프라 배포", koDesc: "운영 리소스 그룹·VNet·저장소·Bastion·실행기 VM 생성" },
    { id: "runner-enrollment", enTitle: "Runner enrollment", enDesc: "Attest and enroll private deployment runner VM", koTitle: "프라이빗 실행기 등록 및 검증", koDesc: "배포 실행기 VM 상태 확인 및 등록 승인" },
    { id: "foundation-state", enTitle: "Foundation state handoff", enDesc: "Migrate Terraform state to private Azure Blob", koTitle: "Foundation 상태 저장소 이관", koTitleDesc: "", koDesc: "로컬 Terraform 상태를 프라이빗 Blob으로 이관" },
    { id: "application-plan", enTitle: "Application & Entra plan", enDesc: "Plan Entra ID roles, AKS, PostgreSQL & services", koTitle: "애플리케이션 및 Entra 계획", koDesc: "Entra ID·AKS·PostgreSQL·서비스 배포 계획 수립" },
    { id: "application-apply", enTitle: "Application exact apply", enDesc: "Deploy AKS, PostgreSQL, migrations & workloads", koTitle: "애플리케이션 및 런타임 배포", koDesc: "AKS·PostgreSQL·마이그레이션·컨테이너 배포" },
    { id: "verification", enTitle: "Health & zero-change verification", enDesc: "Verify service health and second zero-change plan", koTitle: "최종 상태 및 무변경 검증", koDesc: "서비스 정상 응답 및 Terraform 무변경 검증" },
  ];
  const stageStateLabels = {
    en: { completed: "Completed", skipped: "Skipped", active: "In progress", waiting: "Approval required", failed: "Failed", blocked: "Blocked", pending: "Pending" },
    ko: { completed: "완료", skipped: "건너뜀", active: "진행 중", waiting: "승인 필요", failed: "실패", blocked: "차단됨", pending: "대기 중" },
  };
  function resolveStageProgress() {
    const phase = status?.phase || "idle";
    const msg = status?.message || "";
    const total = STAGE_CATALOG.length;
    if (phase === "ready" && status?.deployment_ready) {
      return { currentIdx: 14, completedCount: 15, activeCount: 0, queuedCount: 0, elapsed: "", states: STAGE_CATALOG.map((_, i) => (i === 6 || i === 7 ? "skipped" : "completed")) };
    }
    let currentIdx = -1;
    let elapsed = "";
    const elapsedMatch = msg.match(/elapsed\s+([0-9:]+)/);
    if (elapsedMatch) elapsed = elapsedMatch[1];
    const bracketMatch = msg.match(/^\[(\d{2})\/15\]/);
    if (bracketMatch) {
      currentIdx = Math.max(0, Math.min(14, Number(bracketMatch[1]) - 1));
    } else if (phase === "review" && status?.review) {
      const details = (status.review.details || []).join(" ") + " " + (status.review.title || "");
      if (details.includes("foundation-apply")) currentIdx = 9;
      else if (details.includes("runner-enrollment")) currentIdx = 10;
      else if (details.includes("foundation-state")) currentIdx = 11;
      else if (details.includes("entra-config") || details.includes("application-plan")) currentIdx = 12;
      else if (details.includes("application")) currentIdx = 13;
      else currentIdx = 9;
    } else if (msg.startsWith("Stage '")) {
      const stName = msg.split("'")[1];
      currentIdx = STAGE_CATALOG.findIndex(s => s.id === stName);
    } else if (phase === "working" && ["install", "resume"].includes(status?.action)) {
      if (msg.includes("zero-change Terraform") || msg.includes("Console redirect") || msg.includes("initial inventory") || msg.includes("catalog review") || msg.includes("Trial window")) currentIdx = 14;
      else if (msg.includes("infrastructure") || msg.includes("private access") || /^"[a-z0-9_]+":\s*\d+/.test(msg) || msg.includes("AKS runtime") || msg.includes("Container Insights") || msg.includes("runtime images") || msg.includes("database migrations") || msg.includes("application plan") || msg.includes("planning the application") || msg.includes("keyless Trial")) currentIdx = 13;
      else if (msg.includes("Bastion transfer")) currentIdx = 12;
      else if (msg.includes("source snapshot")) currentIdx = 2;
      else if (msg.includes("AKS SKU") || msg.includes("identity names") || msg.includes("compute estimate")) currentIdx = 1;
      else if (msg.includes("Terraform executable")) currentIdx = 0;
      else if (msg.includes("Foundation inputs")) currentIdx = 5;
      else if (msg.includes("Decision submitted")) currentIdx = 9;
      else currentIdx = 0;
    } else if (["blocked", "failed", "interrupted"].includes(phase) && status?.request_id) {
      currentIdx = msg.includes("preflight") ? 1 : 9;
    }
    const states = STAGE_CATALOG.map((item, idx) => {
      if (currentIdx < 0) return "pending";
      if (idx < currentIdx) return (idx === 6 || idx === 7) ? "skipped" : "completed";
      if (idx === currentIdx) {
        if (phase === "review") return "waiting";
        if (phase === "failed") return "failed";
        if (phase === "blocked" || phase === "interrupted") return "blocked";
        return "active";
      }
      return "pending";
    });
    const completedCount = states.filter(s => s === "completed" || s === "skipped").length;
    const activeCount = states.filter(s => s === "active" || s === "waiting" || s === "failed" || s === "blocked").length;
    const queuedCount = total - completedCount - activeCount;
    return { currentIdx, completedCount, activeCount, queuedCount, elapsed, states };
  }
  function renderTelemetryAndArch() {
    const tel = status?.telemetry || null;
    const formEditable = !$("configuration-fields")?.disabled;
    const checkedRuntime = document.querySelector('input[name="runtime-platform"]:checked')?.value || "aks";
    const runtimeVal = formEditable ? checkedRuntime : (tel?.runtime_platform || checkedRuntime);
    const dbSelectVal = $("database-placement")?.value || "postgres-flex";
    const dbVal = formEditable ? dbSelectVal : (tel?.database_placement || dbSelectVal);
    const regionVal = ($("region")?.value || "").trim() || tel?.region || "westus3";
    const workloadVal = ($("workload")?.value || "").trim() || tel?.workload || "fdai";
    const runtimeLabel = runtimeVal === "container-apps" ? "ACA" : "AKS";
    const dbLabel = dbVal === "postgres-aks" ? "In-cluster PG" : "Postgres Flex";
    if ($("header-arch-tag")) setText("header-arch-tag", `${runtimeLabel} · ${dbLabel}`);
    if ($("rail-runtime-val")) setText("rail-runtime-val", runtimeLabel);
    if ($("rail-db-val")) setText("rail-db-val", dbLabel);
    if ($("rail-region-val")) setText("rail-region-val", regionVal);
    if ($("rail-workload-val")) setText("rail-workload-val", workloadVal);
    if ($("rg-preview-text")) {
      const opsRg = tel?.ops_rg || `rg-${workloadVal}-ops`;
      const devRg = tel?.dev_rg || `rg-${workloadVal}-dev`;
      setText("rg-preview-text", locale === "ko"
        ? `생성될 리소스 그룹: ${opsRg}, ${devRg}`
        : `Target resource groups: ${opsRg}, ${devRg}`);
    }
    if ($("config-summary-text")) {
      const subName = status?.accounts?.[0]?.name || $("subscription")?.selectedOptions?.[0]?.textContent || "Azure";
      const opsRg = tel?.ops_rg || `rg-${workloadVal}-ops`;
      const devRg = tel?.dev_rg || `rg-${workloadVal}-dev`;
      setText("config-summary-text", `${subName} · ${runtimeLabel} (${dbLabel}) · ${regionVal} · ${opsRg} / ${devRg}`);
    }
    const opPill = $("operator-pill");
    if (opPill) {
      const user = tel?.operator_user || "";
      opPill.hidden = !user;
      if (user) {
        setText("operator-user", user);
        const initials = user.slice(0, 2).toUpperCase();
        setText("operator-avatar", initials);
      }
    }
    const perms = tel?.permissions || null;
    if (perms) {
      const isVer = Boolean(perms.verified);
      const verifiedText = text("permStateVerified");
      if ($("perm-sub-state") && (isVer || perms.subscription_role === "verified")) setText("perm-sub-state", verifiedText);
      if ($("perm-uami-state") && (isVer || perms.rbac_delegation === "verified")) setText("perm-uami-state", verifiedText);
      if ($("perm-entra-state") && (isVer || perms.entra_directory === "verified")) setText("perm-entra-state", verifiedText);
      if ($("perm-rp-state") && (isVer || perms.policy_and_providers === "verified")) {
        setText("perm-rp-state", locale === "ko"
          ? `✓ ${perms.registered_providers || 18}/18 등록됨`
          : `✓ ${perms.registered_providers || 18}/18 RP`);
      }
      if (tel?.operator_user && $("perm-summary-text")) {
        setText("perm-summary-text", locale === "ko"
          ? `${tel.operator_user} · 구독 Owner/Contributor · UAMI RBAC 위임 · Entra ID 앱/그룹 · ${perms.registered_providers || 18}개 RP 확인됨`
          : `${tel.operator_user} · Subscription RBAC · UAMI delegation · Entra ID apps/groups · ${perms.registered_providers || 18} RPs verified`);
      }
    }
  }
  let stageRenderKey = "";
  function renderProvisionStages() {
    const prog = resolveStageProgress();
    const total = STAGE_CATALOG.length;
    const tel = status?.telemetry || null;
    const timings = Array.isArray(tel?.stage_timings) ? tel.stage_timings : [];
    const hasRun = prog.currentIdx >= 0 || (status?.phase === "ready" && status?.deployment_ready) || timings.some(t => t && t.start_time);
    const nextStageKey = JSON.stringify([locale, status?.phase, prog, timings, tel?.total_duration, tel?.region, tel?.ops_rg, tel?.dev_rg, tel?.runtime_platform, tel?.started_at, tel?.completed_at]);
    if (stageRenderKey === nextStageKey) return;
    stageRenderKey = nextStageKey;
    const bar = $("provision-progress");
    if (bar) {
      bar.hidden = !hasRun;
      if (hasRun) {
        const curNum = Math.min(total, Math.max(1, prog.currentIdx + 1));
        const curStage = STAGE_CATALOG[Math.max(0, prog.currentIdx)] || STAGE_CATALOG[0];
        const curTitle = locale === "ko" ? curStage.koTitle : curStage.enTitle;
        const pct = Math.min(100, Math.round((prog.completedCount / total) * 1000) / 10);
        setText("stage-progress-label", locale === "ko"
          ? `전체 ${total}단계 중 ${curNum}단계 (${curTitle})`
          : `Stage ${curNum} of ${total} (${curTitle})`);
        setText("stage-progress-percent", `${pct.toFixed(1)}%`);
        if ($("deploy-sub-meta")) {
          const runtimeLabel = (tel?.runtime_platform === "container-apps") ? "ACA" : "AKS";
          const metaParts = [];
          if (tel?.region) metaParts.push(tel.region);
          if (tel?.ops_rg && tel?.dev_rg) metaParts.push(`${tel.ops_rg} / ${tel.dev_rg}`);
          metaParts.push(runtimeLabel);
          if (tel?.started_at && tel?.completed_at) metaParts.push(`${tel.started_at} ~ ${tel.completed_at}`);
          setText("deploy-sub-meta", metaParts.join(" · "));
        }
        const meter = $("provision-meter");
        if (meter) {
          meter.className = `provision-meter${["failed", "blocked"].includes(status?.phase) ? " is-failed" : ""}${status?.phase === "ready" && status?.deployment_ready ? " is-done" : ""}`;
          meter.setAttribute("aria-valuenow", String(pct));
        }
        const fill = $("stage-progress-fill");
        if (fill) fill.dataset.completed = String(prog.completedCount);
        $("fact-complete").replaceChildren();
        const cStrong = document.createElement("strong"); cStrong.textContent = String(prog.completedCount);
        $("fact-complete").append(cStrong, locale === "ko" ? " 완료" : " complete");
        $("fact-active").replaceChildren();
        const aStrong = document.createElement("strong"); aStrong.textContent = String(prog.activeCount);
        $("fact-active").append(aStrong, locale === "ko" ? (status?.phase === "review" ? " 승인 대기" : " 진행 중") : " active");
        $("fact-queued").replaceChildren();
        const qStrong = document.createElement("strong"); qStrong.textContent = String(prog.queuedCount);
        $("fact-queued").append(qStrong, locale === "ko" ? " 남은 단계" : " remaining");
        const elapsedStr = tel?.total_duration || prog.elapsed;
        setText("fact-elapsed", elapsedStr ? (locale === "ko" ? `총 소요 ${elapsedStr}` : `elapsed ${elapsedStr}`) : "");
      }
    }
    setText("stages-summary", locale === "ko"
      ? `전체 ${total}단계 중 ${prog.completedCount}단계 완료 · ${prog.queuedCount}단계 남음`
      : `${prog.completedCount} of ${total} stages completed · ${prog.queuedCount} remaining`);
    const list = $("provision-stages");
    if (!list) return;
    const labels = stageStateLabels[locale === "ko" ? "ko" : "en"];
    list.replaceChildren(...STAGE_CATALOG.map((stage, idx) => {
      const st = prog.states[idx];
      const timing = timings[idx] || null;
      const li = document.createElement("li");
      li.className = `provision-stage provision-stage--${st}`;
      if (idx === prog.currentIdx) li.setAttribute("aria-current", "step");
      const num = document.createElement("span");
      num.className = "provision-stage-index";
      num.textContent = String(idx + 1).padStart(2, "0");
      const body = document.createElement("div");
      body.className = "provision-stage-body";
      const title = document.createElement("strong");
      title.className = "provision-stage-title";
      title.textContent = locale === "ko" ? stage.koTitle : stage.enTitle;
      const desc = document.createElement("span");
      desc.className = "provision-stage-desc";
      desc.textContent = locale === "ko" ? stage.koDesc : stage.enDesc;
      body.append(title, desc);
      const right = document.createElement("div");
      right.className = "stage-right";
      if (timing && (timing.start_time || timing.end_time)) {
        const tSpan = document.createElement("span");
        tSpan.className = "stage-timing";
        const sTime = timing.start_time || "--:--:--";
        const eTime = timing.end_time || (st === "active" ? (locale === "ko" ? "진행중" : "running") : "--:--:--");
        tSpan.textContent = `${sTime} ~ ${eTime}`;
        right.append(tSpan);
      }
      if (timing && timing.duration) {
        const dSpan = document.createElement("span");
        dSpan.className = "stage-dur";
        dSpan.textContent = timing.duration;
        right.append(dSpan);
      }
      const pill = document.createElement("span");
      pill.className = "provision-stage-state";
      pill.textContent = labels[st] || st;
      right.append(pill);
      li.append(num, body, right);
      return li;
    }));
  }
  function setText(id, value) {
    const el = $(id);
    if (el && el.textContent !== value) el.textContent = value;
  }
  function notice(key, detail = "") {
    noticeKey = key;
    noticeDetail = detail;
    $("notice").textContent = detail || (key ? text(key) : "");
    $("notice").hidden = !key && !detail;
  }
  function localize() {
    document.documentElement.lang = locale;
    document.title = `FDAI Lifecycle Hub - ${locale === "ko" ? "설치 설정" : "Setup"}`;
    $("locale").value = locale;
    document.querySelectorAll("[data-i18n]").forEach(node => { node.textContent = text(node.dataset.i18n); });
    if (noticeKey) notice(noticeKey, noticeDetail);
    if ($("subscription").options[0]) $("subscription").options[0].textContent = text("noAccounts");
    if (status) render();
    else renderTelemetryAndArch();
  }
  function artifactFields() {
    const source = document.querySelector('input[name="artifact"]:checked').value === "source";
    $("hub-fields").hidden = source;
    $("source-fields").hidden = !source;
    $("public-key").disabled = source;
    $("public-key").required = !source;
    $("key-file").disabled = source;
    $("source-root").disabled = !source;
    $("source-root").required = source;
  }
  function safeConsole(value) {
    if (typeof value !== "string") return null;
    try {
      const url = new URL(value);
      return url.protocol === "https:" && !url.username && !url.password ? url.href : null;
    } catch { return null; }
  }
  function reviewCurrent() {
    return connected && status?.phase === "review" && status.request_id && status.review &&
      Number.isFinite(Date.parse(status.review.expires_at)) && Date.parse(status.review.expires_at) > Date.now();
  }
  function controls() {
    const available = connected && !pending && !loading && !authenticating;
    const active = status?.phase === "working" || status?.phase === "review";
    const fresh = available && !active && !status?.request_id;
    const recovery = ["failed", "blocked", "interrupted"].includes(status?.phase);
    $("login").disabled = !fresh && !(available && recovery);
    $("tenant").disabled = $("login").disabled;
    if ($("device-code")) $("device-code").disabled = $("login").disabled;
    $("accounts").disabled = !fresh;
    $("configuration-fields").disabled = !fresh;
    $("refresh").disabled = loading;
    $("approve").disabled = !available || !reviewCurrent() ||
      $("confirmation").value !== (status?.review?.confirmation_required || "");
    $("decline").disabled = !available || !reviewCurrent();
    $("resume").disabled = !available || active || status?.phase === "ready";
    $("inspect").disabled = !available || active;
    if ($("reset")) $("reset").disabled = !available || active || status?.phase === "ready";
    if ($("fill-confirmation")) $("fill-confirmation").disabled = !available || !reviewCurrent();
  }
  let configFormExpanded = false;
  function updateStepper(phase) {
    const hasAccounts = Array.isArray(status?.accounts) && status.accounts.length > 0;
    const ready = connected && phase === "ready" && status?.deployment_ready === true;
    const inReviewOrApply = ["review", "blocked", "failed", "interrupted"].includes(phase) ||
      (phase === "working" && ["install", "resume"].includes(status?.action));
    const states = [
      hasAccounts || inReviewOrApply || ready ? "done" : "active",
      ready || inReviewOrApply ? "done" : hasAccounts ? "active" : "pending",
      ready ? "done" : inReviewOrApply ? "active" : "pending",
      ready ? "active" : "pending",
    ];
    states.forEach((st, idx) => {
      const node = $(`step-${idx + 1}`);
      if (node) node.dataset.state = st;
    });
    const compactMode = phase === "ready" || phase === "review" ||
      (phase === "working" && ["install", "resume"].includes(status?.action));
    if (!compactMode) configFormExpanded = false;
    if ($("config-summary-card")) $("config-summary-card").hidden = !compactMode;
    if ($("config-form-wrap")) $("config-form-wrap").hidden = compactMode && !configFormExpanded;
    const workspace = document.querySelector(".workspace");
    if (workspace) {
      workspace.dataset.activeDecision = String(
        phase === "working" || phase === "review" || ["blocked", "failed", "interrupted"].includes(phase) || ready
      );
      workspace.dataset.compactConfig = String(compactMode && !configFormExpanded);
    }
    const accountSec = $("account-section");
    if (accountSec) accountSec.dataset.connected = String(hasAccounts);
  }
  function render() {
    const phase = status.phase;
    updateStepper(phase);
    renderProvisionStages();
    $("skeleton").hidden = phase !== "working";
    $("status-live").setAttribute("aria-busy", String(phase === "working"));
    const phaseKey = phase === "review" ? "reviewPhase" :
      phase === "ready" && !status.deployment_ready ? "unverified" : phase;
    setText("phase", text(connected ? phaseKey : "disconnected"));
    $("phase").dataset.phase = connected ? phase : "disconnected";
    setText("message", localizeMessage(status.message) || text(phase === "review" ? "reviewPhase" : phase));
    $("request-meta").hidden = !status.request_id && !status.error_code;
    $("request-id").textContent = status.request_id || "-";
    $("action-name").textContent = status.action || "-";
    $("error-row").hidden = !status.error_code;
    $("error-code").textContent = status.error_code || "";
    $("observed").textContent = observedAt ? `${text("observed")}: ${observedAt.toLocaleString(locale === "ko" ? "ko-KR" : "en-US")}` : "";
    const accounts = JSON.stringify(status.accounts);
    if (accountKey !== accounts) {
      const selected = $("subscription").value;
      $("subscription").replaceChildren(new Option(text("noAccounts"), ""));
      for (const account of status.accounts) {
        $("subscription").add(new Option(`${account.name} (${account.id})`, account.id));
      }
      if (selected && status.accounts.some(account => account.id === selected)) {
        $("subscription").value = selected;
      } else if (status.accounts.length > 0) {
        $("subscription").value = status.accounts[0].id;
      }
      const chosenAcc = status.accounts.find(a => a.id === $("subscription").value);
      if (chosenAcc && $("tenant") && !$("tenant").value) {
        $("tenant").placeholder = chosenAcc.tenant_id;
      }
      accountKey = accounts;
    }
    const review = phase === "review" ? status.review : null;
    $("review-section").hidden = !review;
    const nextKey = review ? JSON.stringify([status.request_id, review]) : "";
    if (review && reviewKey !== nextKey) {
      $("review-title").textContent = review.title;
      $("review-id").textContent = review.id;
      $("review-digest").textContent = review.digest;
      $("review-expires").textContent = review.expires_at;
      $("review-details").replaceChildren(...review.details.map(detail => {
        const item = document.createElement("li"); item.textContent = detail; return item;
      }));
      $("confirmation-field").hidden = !review.confirmation_required;
      $("confirmation-required").textContent = review.confirmation_required;
      $("confirmation").value = "";
      $("review-heading").focus();
    }
    if (review) $("expired").hidden = Boolean(reviewCurrent());
    reviewKey = nextKey;
    const recovery = ["failed", "blocked", "interrupted"].includes(phase);
    const ready = connected && phase === "ready" && status.deployment_ready === true;
    $("ready-section").hidden = !ready;
    $("next-section").hidden = Boolean(review) || recovery || ready;
    const url = ready ? safeConsole(status.console_url) : null;
    $("recovery-section").hidden = !recovery && !(ready && !url);
    $("console-link").removeAttribute("href");
    $("console-link").hidden = !url;
    if ($("console-origin-text")) {
      $("console-origin-text").hidden = !url;
      $("console-origin-text").textContent = url || "";
    }
    if ($("copy-console-url")) $("copy-console-url").hidden = !url;
    if (url) $("console-link").href = url;
    $("console-unavailable").hidden = Boolean(url);
    controls();
    renderTelemetryAndArch();
  }
  function validStatus(value) {
    const nullableString = item => item === null || typeof item === "string";
    if (!value || !["idle", "working", "review", "ready", "blocked", "failed", "interrupted"].includes(value.phase) ||
      typeof value.csrf_token !== "string" || !value.csrf_token ||
      !nullableString(value.request_id) || !nullableString(value.action) || !nullableString(value.error_code) ||
      !nullableString(value.console_url) || typeof value.message !== "string" ||
      typeof value.deployment_ready !== "boolean" || !Array.isArray(value.accounts) ||
      !value.accounts.every(item => item && ["id", "name", "tenant_id"].every(key => typeof item[key] === "string"))) return false;
    const review = value.review;
    return review === null || (review && ["id", "digest", "title", "confirmation_required", "expires_at"]
      .every(key => typeof review[key] === "string") && Array.isArray(review.details) &&
      review.details.every(detail => typeof detail === "string") && Boolean(value.request_id));
  }
  async function request(path, body) {
    const options = { credentials: "same-origin", cache: "no-store", redirect: "error", signal: AbortSignal.timeout(10000) };
    if (body !== undefined) {
      options.method = "POST";
      options.body = JSON.stringify(body);
      if (new TextEncoder().encode(options.body).byteLength > 16384) throw new Error(text("tooLarge"));
      options.headers = { "Content-Type": "application/json" };
      if (path !== "session") options.headers["X-FDAI-CSRF"] = csrf;
    }
    const response = await fetch(`/setup/api/${path}`, options);
    let data;
    try { data = await response.json(); } catch { throw new Error(text("invalid")); }
    if (!response.ok) {
      if (response.status === 401) {
        if (path === "status" && !window.__fdaiLoopbackRetried) {
          window.__fdaiLoopbackRetried = true;
          try {
            await request("session", { token: "local-loopback" });
            return await request(path, body);
          } catch { /* fall through */ }
        }
        throw new Error(text("auth"));
      }
      throw new Error(typeof data.error === "string" ? data.error : text("requestFailed"));
    }
    return data;
  }
  function schedule() {
    clearTimeout(timer);
    const syntheticHidden = Object.prototype.hasOwnProperty.call(document, "hidden") && document.hidden;
    const keepPolling = !syntheticHidden && (
      !document.hidden || status?.phase === "working" || status?.phase === "review"
    );
    if (keepPolling && !pending && !authenticating) {
      timer = setTimeout(loadStatus, status?.phase === "working" ? 1500 : 2000);
    }
  }
  function loadStatus() {
    if (pending || authenticating) return Promise.resolve();
    if (statusTask) return statusTask;
    const version = sessionVersion;
    statusTask = (async () => {
      loading = true; controls();
      try {
        const data = await request("status");
        if (version !== sessionVersion) return;
        if (!validStatus(data)) throw new Error(text("invalid"));
        status = data; csrf = data.csrf_token; connected = true; observedAt = new Date();
        render();
      } catch (error) {
        if (version !== sessionVersion) return;
        connected = false;
        notice("network", error instanceof TypeError || error.name === "TimeoutError" ? "" : error.message);
        if (status) render();
        else {
          $("phase").textContent = text("disconnected"); $("message").textContent = text("network");
          $("skeleton").hidden = true; $("status-live").setAttribute("aria-busy", "false");
        }
      } finally { loading = false; statusTask = null; controls(); schedule(); }
    })();
    return statusTask;
  }
  async function mutate(path, body) {
    if (pending || !connected) return;
    pending = true; clearTimeout(timer); notice(""); controls();
    const statusSec = document.querySelector(".status-section");
    if (statusSec && typeof statusSec.scrollIntoView === "function") {
      statusSec.scrollIntoView({ behavior: "smooth", block: "start" });
    }
    try { await request(path, body); }
    catch (error) { notice("uncertain", error instanceof TypeError || error.name === "TimeoutError" ? text("uncertain") : error.message); }
    finally { pending = false; await loadStatus(); controls(); }
  }
  const action = (name, payload = {}) => mutate("actions", { action: name, payload });
  function publicKey(value) {
    return new TextEncoder().encode(value).byteLength <= 4096 &&
      /^-----BEGIN PUBLIC KEY-----\r?\n[A-Za-z0-9+/=\r\n]+-----END PUBLIC KEY-----\s*$/.test(value);
  }
  $("install-form").addEventListener("submit", event => {
    event.preventDefault();
    const payload = {
      subscription_id: $("subscription").value, region: $("region").value,
      monthly_cost_ceiling: Number($("cost").value),
      artifact_source: document.querySelector('input[name="artifact"]:checked').value,
    };
    const workload = ($("workload")?.value || "").trim();
    if (workload) {
      if (!/^[a-z][a-z0-9]{1,11}$/.test(workload)) return notice("invalidWorkload");
      payload.workload = workload;
    }
    const approvalMode = $("approval-mode")?.value || "continuous";
    if (approvalMode === "stepwise") payload.approval_mode = "stepwise";
    const runtimePlatform = document.querySelector('input[name="runtime-platform"]:checked')?.value || "aks";
    if (runtimePlatform !== "aks") payload.runtime_platform = runtimePlatform;
    const dbPlacement = $("database-placement")?.value || "postgres-flex";
    if (dbPlacement !== "postgres-flex") payload.database_placement = dbPlacement;
    if (!Number.isSafeInteger(payload.monthly_cost_ceiling) || payload.monthly_cost_ceiling < 1) return notice("invalidCost");
    if (payload.artifact_source === "source") payload.source_root = $("source-root").value;
    else {
      if (!publicKey($("public-key").value.trim())) return notice("invalidKey");
      payload.hub_public_key = $("public-key").value.trim();
    }
    action("install", payload);
  });
  $("subscription").addEventListener("change", () => {
    const chosenAcc = (status?.accounts || []).find(a => a.id === $("subscription").value);
    if (chosenAcc && $("tenant") && !$("tenant").value) {
      $("tenant").placeholder = chosenAcc.tenant_id;
    }
  });
  if ($("copy-console-url")) {
    $("copy-console-url").addEventListener("click", async () => {
      const url = safeConsole(status?.console_url);
      if (!url || !navigator.clipboard) return;
      try {
        await navigator.clipboard.writeText(url);
        $("copy-console-url").textContent = text("copiedConsoleUrl");
        setTimeout(() => { $("copy-console-url").textContent = text("copyConsoleUrl"); }, 1800);
      } catch { /* ignore */ }
    });
  }
  if ($("toggle-config-btn") && $("config-form-wrap")) {
    $("toggle-config-btn").addEventListener("click", () => {
      configFormExpanded = !configFormExpanded;
      $("config-form-wrap").hidden = !configFormExpanded;
      const workspace = document.querySelector(".workspace");
      if (workspace) workspace.dataset.compactConfig = String(!configFormExpanded);
      $("toggle-config-btn").setAttribute("aria-expanded", String(configFormExpanded));
      const key = configFormExpanded ? "hideConfigForm" : "showConfigForm";
      $("toggle-config-btn").dataset.i18n = key;
      $("toggle-config-btn").textContent = text(key);
    });
  }
  if ($("toggle-perm-btn") && $("perm-drawer")) {
    $("toggle-perm-btn").addEventListener("click", () => {
      const drawer = $("perm-drawer");
      const open = !drawer.hidden;
      drawer.hidden = open;
      $("toggle-perm-btn").setAttribute("aria-expanded", String(!open));
      const key = open ? "showPermDetails" : "hidePermDetails";
      $("toggle-perm-btn").dataset.i18n = key;
      $("toggle-perm-btn").textContent = text(key);
    });
  }
  if ($("theme-toggle")) {
    $("theme-toggle").addEventListener("click", () => {
      const isDark = document.body.dataset.theme === "dark";
      if (isDark) delete document.body.dataset.theme;
      else document.body.dataset.theme = "dark";
    });
  }
  document.querySelectorAll('input[name="runtime-platform"]').forEach(node => {
    node.addEventListener("change", () => {
      const val = document.querySelector('input[name="runtime-platform"]:checked')?.value || "aks";
      if ($("card-runtime-aks")) $("card-runtime-aks").classList.toggle("is-selected", val === "aks");
      if ($("card-runtime-aca")) $("card-runtime-aca").classList.toggle("is-selected", val === "container-apps");
      if (val === "container-apps" && $("database-placement")?.value === "postgres-aks") {
        $("database-placement").value = "postgres-flex";
      }
      renderTelemetryAndArch();
    });
  });
  for (const id of ["database-placement", "region", "workload"]) {
    if ($(id)) $(id).addEventListener("input", renderTelemetryAndArch);
    if ($(id)) $(id).addEventListener("change", renderTelemetryAndArch);
  }
  if ($("toggle-completed-stages")) {
    $("toggle-completed-stages").addEventListener("click", () => {
      const list = $("provision-stages");
      const hidden = list.dataset.hideCompleted === "true";
      list.dataset.hideCompleted = String(!hidden);
      $("toggle-completed-stages").setAttribute("aria-expanded", String(hidden));
      $("toggle-completed-stages").dataset.i18n = !hidden ? "showCompletedStages" : "hideCompletedStages";
      $("toggle-completed-stages").textContent = text(!hidden ? "showCompletedStages" : "hideCompletedStages");
    });
  }
  function decide(approved) {
    if (!reviewCurrent()) return;
    const review = status.review;
    mutate("decisions", {
      request_id: status.request_id, review_id: review.id, digest: review.digest,
      approved, confirmation: approved ? $("confirmation").value : "",
    });
  }
  $("decision-form").addEventListener("submit", event => { event.preventDefault(); if (!$("approve").disabled) decide(true); });
  $("decline").addEventListener("click", () => decide(false));
  $("confirmation").addEventListener("input", controls);
  const fillConfirmation = () => {
    if (!reviewCurrent() || !status?.review?.confirmation_required) return;
    $("confirmation").value = status.review.confirmation_required;
    controls();
    $("approve").focus();
  };
  if ($("fill-confirmation")) $("fill-confirmation").addEventListener("click", fillConfirmation);
  $("confirmation-required").addEventListener("click", fillConfirmation);
  $("login").addEventListener("click", () => {
    const tenant = $("tenant").value.trim();
    const useDeviceCode = Boolean($("device-code")?.checked);
    const payload = {};
    if (tenant) {
      if (!/^[A-Za-z0-9._-]{1,128}$/.test(tenant) || tenant === "." || tenant === "..") return notice("invalidTenant");
      payload.tenant_id = tenant;
    }
    if (useDeviceCode) payload.use_device_code = true;
    action("login", payload);
  });
  for (const name of ["accounts", "resume", "inspect", "reset"]) {
    if ($(name)) $(name).addEventListener("click", () => action(name));
  }
  $("refresh").addEventListener("click", () => { notice(""); loadStatus(); });
  const refreshIfStale = () => {
    const syntheticHidden = Object.prototype.hasOwnProperty.call(document, "hidden") && document.hidden;
    if (!syntheticHidden && !pending && !loading && !authenticating && (!observedAt || Date.now() - observedAt.getTime() > 1500)) {
      loadStatus();
    }
  };
  window.addEventListener("focus", refreshIfStale);
  document.addEventListener("pointerenter", refreshIfStale);
  document.addEventListener("mousemove", refreshIfStale);
  document.querySelectorAll('input[name="artifact"]').forEach(node => node.addEventListener("change", artifactFields));
  $("key-file").addEventListener("change", async () => {
    const file = $("key-file").files[0];
    if (!file) return;
    try {
      if (file.size > 4096) { notice("invalidKey"); return; }
      const value = await file.text();
      if (!publicKey(value.trim())) { notice("invalidKey"); return; }
      $("public-key").value = value.trim(); notice("");
    } catch { notice("keyRead"); }
    finally { $("key-file").value = ""; }
  });
  $("locale").addEventListener("change", () => {
    locale = $("locale").value === "ko" ? "ko" : "en";
    try { localStorage.setItem("fdai_setup_locale", locale); } catch { /* ignore */ }
    localize();
  });
  document.addEventListener("visibilitychange", () => { clearTimeout(timer); if (!document.hidden) loadStatus(); });
  async function initialize() {
    let token = new URLSearchParams(location.hash.slice(1)).get("session");
    if (location.hash) history.replaceState(null, "", location.pathname + location.search);
    if (token) {
      if (authenticating) { token = null; return; }
      authenticating = true; connected = false; csrf = ""; sessionVersion += 1;
      clearTimeout(timer); notice(""); controls();
      if (status) render();
      try {
        await request("session", { token });
        if (statusTask) await statusTask;
      } catch {
        notice("auth"); $("phase").textContent = text("disconnected"); $("message").textContent = text("auth");
        $("skeleton").hidden = true; $("status-live").setAttribute("aria-busy", "false");
        return;
      } finally { token = null; authenticating = false; controls(); }
    }
    await loadStatus();
  }
  window.addEventListener("hashchange", () => {
    if (new URLSearchParams(location.hash.slice(1)).has("session")) initialize();
  });
  localize(); artifactFields();
  initialize();
})();
