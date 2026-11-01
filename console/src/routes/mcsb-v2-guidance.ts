import type { McsbControl, McsbControlDetail } from "./mcsb-controls.model";
import { FRAMEWORK_TITLES_BY_KEY, resolveControlReferenceImage } from "./reference-images.catalog";
import type { GuidanceNode, GuidancePresentation, GuidanceText } from "./wara-guidance.model";

function text(en: string, ko: string): GuidanceText {
  return { en, ko };
}

interface AiControlAuthored {
  readonly titleKo: string;
  readonly summary: GuidanceText;
  readonly benefits: GuidanceText;
  readonly before: GuidanceText;
  readonly after: GuidanceText;
  readonly verify: GuidanceText;
  readonly caution: GuidanceText;
}

const AI_CONTROLS: Readonly<Record<string, AiControlAuthored>> = {
  "AI-1": {
    titleKo: "승인된 AI 모델만 사용하도록 보장",
    summary: text(
      "Governed model registries and deployment policies restrict workloads to reviewed foundation and fine-tuned models with verified provenance.",
      "통제된 모델 레지스트리와 배포 정책을 통해 출처와 안전성이 검토된 기반 모델 및 파인튜닝 모델만 워크로드에 배포하도록 제한합니다.",
    ),
    benefits: text(
      "Prevents shadow AI endpoints, unreviewed model weights, and licensing or data-residency violations.",
      "미승인 섀도 AI 엔드포인트, 검증되지 않은 모델 가중치, 라이선스 및 데이터 상주 규정 위반을 사전에 차단합니다.",
    ),
    before: text(
      "Application teams deploy arbitrary external or unreviewed model endpoints without model card, provenance, or data-handling review.",
      "애플리케이션 팀이 모델 카드, 출처, 데이터 처리 방식에 대한 검토 없이 임의의 외부 또는 미검증 모델 엔드포인트를 직접 연결합니다.",
    ),
    after: text(
      "Bind workloads only to catalog-approved Azure AI / Foundry model deployments with pinned versions, regional compliance, and audit logging.",
      "버전이 고정되고 리전 규정 준수 및 감사 로깅이 적용된 승인된 Azure AI / Foundry 모델 배포만 워크로드에 바인딩합니다.",
    ),
    verify: text(
      "Reconcile active model deployment endpoints and model versions against the approved model inventory and Azure Policy guardrails.",
      "활성 모델 배포 엔드포인트와 모델 버전을 승인된 모델 목록 및 Azure Policy 가드레일과 대조하여 검증합니다.",
    ),
    caution: text(
      "An approved model identifier does not guarantee safe output without runtime content filtering and prompt boundary controls.",
      "모델 자체가 승인되었더라도 런타임 콘텐츠 필터링과 프롬프트 경계 통제가 없으면 출력의 안전성이 자동으로 보장되지 않습니다.",
    ),
  },
  "AI-2": {
    titleKo: "다계층 콘텐츠 필터링 및 안전 가드레일 구현",
    summary: text(
      "Multi-layered input and output content safety classifiers inspect prompts and completions for harmful content, jailbreaks, and sensitive data leakage.",
      "입력 프롬프트와 모델 응답 양단에 다계층 콘텐츠 안전 분류기를 적용하여 유해 콘텐츠, 탈옥(Jailbreak) 시도, 민감 데이터 유출을 검사합니다.",
    ),
    benefits: text(
      "Blocks prompt-injection payloads and unsafe completions before they reach downstream tools or end users.",
      "프롬프트 인젝션 공격과 위험한 생성 결과가 하위 도구나 최종 사용자에게 전달되기 전에 차단합니다.",
    ),
    before: text(
      "Raw user prompts and retrieved external documents pass directly to the model and responses return unfiltered.",
      "사용자 입력과 외부 검색 문서가 별도 검사 없이 모델에 전달되고, 모델 응답이 필터링 없이 그대로 반환됩니다.",
    ),
    after: text(
      "Enforce Azure AI Content Safety shields on both ingress prompts (including RAG grounding chunks) and egress model completions.",
      "입력 프롬프트(RAG 검색 문서 조각 포함)와 출력 응답 모두에 Azure AI Content Safety 정책과 프롬프트 실드를 강제 적용합니다.",
    ),
    verify: text(
      "Test representative jailbreak, indirect injection, and policy-violating inputs against the endpoint and confirm deterministic block receipts.",
      "대표적인 탈옥, 간접 프롬프트 인젝션, 정책 위반 입력을 시험하여 차단 응답과 감사 증적이 기록되는지 확인합니다.",
    ),
    caution: text(
      "Content filters reduce risk but cannot replace deterministic authorization and schema validation on downstream actions.",
      "콘텐츠 필터는 위험을 줄여주지만 하위 작업에 대한 결정론적 권한 검증과 스키마 검증을 대체할 수 없습니다.",
    ),
  },
  "AI-3": {
    titleKo: "안전 메타 프롬프트 및 지침 경계 채택",
    summary: text(
      "System meta-prompts define explicit trust boundaries, role constraints, abstention rules, and untrusted-data handling instructions.",
      "시스템 메타 프롬프트에 신뢰 경계, 역할 제약, 판단 보류(Abstention) 규칙, 비신뢰 데이터 처리 지침을 명시적으로 정의합니다.",
    ),
    benefits: text(
      "Reduces instruction-override drift and ensures the model treats retrieved documents and telemetry as untrusted data, never instructions.",
      "지침 무시(Override) 유도를 억제하고 모델이 검색 문서나 원격 분석 데이터를 명령이 아닌 비신뢰 데이터로만 취급하도록 유도합니다.",
    ),
    before: text(
      "System prompts mix formatting hints with business authority and fail to separate untrusted user or document text from system instructions.",
      "시스템 프롬프트가 단순 형식 지시와 권한 판단을 혼용하며 비신뢰 사용자/문서 텍스트와 시스템 지침을 구분하지 않습니다.",
    ),
    after: text(
      "Version-control structured system meta-prompts with explicit untrusted-content delimiters, grounding requirements, and refusal behavior.",
      "비신뢰 콘텐츠 구분자, 근거 인용 요구사항, 거부/보류 동작이 명시된 구조화된 시스템 메타 프롬프트를 버전 관리하여 적용합니다.",
    ),
    verify: text(
      "Inspect prompt catalog versions and run adversarial override test cases to confirm the model preserves its declared role boundary.",
      "프롬프트 카탈로그 버전과 해시를 확인하고 적대적 지침 우회 테스트를 실행하여 역할 경계가 유지되는지 검증합니다.",
    ),
    caution: text(
      "Meta-prompts are probabilistic guidance; never rely on a system prompt alone as a security boundary for privileged execution.",
      "메타 프롬프트는 확률적 가드레일이므로 권한 있는 작업 실행의 유일한 보안 경계로 의존해서는 안 됩니다.",
    ),
  },
  "AI-4": {
    titleKo: "에이전트 함수 및 도구에 최소 권한 적용",
    summary: text(
      "Agent tool bindings use narrowly scoped identities, typed parameter schemas, and read/write separation so an agent cannot invoke arbitrary mutations.",
      "에이전트가 호출하는 함수와 도구에 최소 권한 신원, 엄격한 타입 스키마, 읽기/쓰기 분리를 적용하여 임의의 변경 실행을 방지합니다.",
    ),
    benefits: text(
      "Contains the blast radius of a confused-deputy or prompt-injected agent to bounded, authorized operations only.",
      "프롬프트 인젝션이나 대리인 혼동(Confused Deputy) 발생 시에도 에이전트의 영향 반경을 허용된 최소 범위로 제한합니다.",
    ),
    before: text(
      "An AI agent holds subscription-wide contributor credentials or can invoke shell/API tools with unvalidated free-form parameters.",
      "AI 에이전트가 구독 전체의 기여자 권한을 직접 보유하거나 검증되지 않은 자유 형식 인자로 셸/API 도구를 호출합니다.",
    ),
    after: text(
      "Restrict agent tools to read-only projections by default and route any state-changing proposal through typed ActionType schemas and separate executor identity.",
      "에이전트 도구를 기본적으로 읽기 전용 프로젝션으로 제한하고 상태 변경 제안은 타입이 지정된 ActionType 스키마와 분리된 실행기 신원을 거치도록 구성합니다.",
    ),
    verify: text(
      "Audit every registered agent tool, its Managed Identity RBAC scope, and schema validation rejection on out-of-scope parameters.",
      "등록된 모든 에이전트 도구의 목록, Managed Identity RBAC 권한 범위, 범위 외 인자에 대한 스키마 차단 여부를 감사하고 검증합니다.",
    ),
    caution: text(
      "Even read-only tools must respect tenant and scope isolation so an agent cannot exfiltrate cross-scope sensitive records.",
      "읽기 전용 도구라 하더라도 테넌트 및 범위 격리를 준수해야 하며 다른 범위의 민감 정보를 조회·유출할 수 없어야 합니다.",
    ),
  },
  "AI-5": {
    titleKo: "고위험 결정 및 실행에 인간 개입(HIL) 승인 보장",
    summary: text(
      "High-impact, irreversible, or low-confidence AI proposals require explicit human-in-the-loop (HIL) review and approval before execution.",
      "영향도가 크거나 되돌릴 수 없거나 신뢰도가 낮은 AI 에이전트의 조치 제안은 실행 전에 반드시 명시적인 인간 개입(HIL) 검토와 승인을 거치도록 강제합니다.",
    ),
    benefits: text(
      "Preserves human accountability and prevents autonomous execution of destructive or unverified cloud mutations.",
      "인간의 최종 책임성을 보존하고 파괴적이거나 검증되지 않은 클라우드 변경이 자율적으로 실행되는 것을 방지합니다.",
    ),
    before: text(
      "Model-generated remediation plans execute automatically on production resources without risk gating or human confirmation.",
      "모델이 생성한 교정 계획이 위험 게이트나 사람의 승인 확인 없이 운영 리소스에 즉시 자동 실행됩니다.",
    ),
    after: text(
      "Enforce risk-gate classification, dry-run preview, blast-radius check, and distinct human approver sign-off before any high-risk action.",
      "고위험 작업 실행 전 위험 게이트 분류, 사전 시뮬레이션(Dry-run), 영향 반경 확인, 요청자와 분리된 승인자의 명시적 서명을 강제합니다.",
    ),
    verify: text(
      "Verify that high-risk and irreversible ActionTypes cannot transition to execution without a valid, non-expired human approval receipt.",
      "고위험 및 비가역적 ActionType이 유효하고 만료되지 않은 인간 승인 증적 없이는 실행 단계로 전환될 수 없음을 검증합니다.",
    ),
    caution: text(
      "Approval prompts must show the exact target resource, predicted effect, and rollback plan so human review is meaningful rather than rubber-stamping.",
      "승인 요청 화면에는 정확한 대상 리소스, 예상 효과, 롤백 계획을 함께 제시하여 형식적인 승인이 되지 않도록 해야 합니다.",
    ),
  },
  "AI-6": {
    titleKo: "AI 입출력 모니터링 및 이상 징후 탐지 체계 수립",
    summary: text(
      "Continuous telemetry captures model invocations, token anomalies, tool-call trajectories, grounding failures, and safety filter triggers.",
      "모델 호출, 토큰 급증, 도구 호출 궤적(Trajectory), 근거 검증 실패, 안전 필터 차단 이벤트를 지속적으로 수집하고 이상 징후를 탐지합니다.",
    ),
    benefits: text(
      "Enables rapid detection of prompt-injection campaigns, model drift, runaway token spend, and unauthorized tool probing.",
      "프롬프트 인젝션 시도, 모델 품질 저하(Drift), 비정상적 토큰 비용 급증, 비인가 도구 탐색 시도를 신속히 감지하고 대응할 수 있습니다.",
    ),
    before: text(
      "Model API calls and agent tool trajectories are ephemeral and leave no structured audit trail or anomaly alerts.",
      "모델 API 호출과 에이전트 도구 실행 궤적이 휘발성으로 사라져 구조화된 감사 추적이나 이상 징후 경보가 남지 않습니다.",
    ),
    after: text(
      "Stream structured agent trajectories, safety filter verdicts, and token/latency metrics to immutable audit logs and SIEM detection rules.",
      "구조화된 에이전트 실행 궤적, 안전 필터 판정 결과, 토큰·지연 메트릭을 변경 불가능한 감사 로그 및 SIEM 탐지 규칙으로 스트리밍합니다.",
    ),
    verify: text(
      "Trigger a synthetic safety-filter block and tool-call rejection and confirm correlated telemetry and alert generation in the monitoring workspace.",
      "안전 필터 차단 및 도구 호출 거부 테스트 이벤트를 발생시켜 모니터링 워크스페이스에 상관관계가 부여된 로그와 경보가 생성되는지 확인합니다.",
    ),
    caution: text(
      "Diagnostic logs must redact secrets, credentials, and raw customer PII before storage in shared observability workspaces.",
      "진단 로그를 공유 관측성 워크스페이스에 저장하기 전에 비밀값, 자격 증명, 민감 개인정보(PII)를 반드시 마스킹해야 합니다.",
    ),
  },
  "AI-7": {
    titleKo: "지속적인 AI 레드팀(Red Teaming) 및 적대적 검증 수행",
    summary: text(
      "Structured adversarial testing continuously probes prompts, RAG retrieval, and agent tool boundaries for jailbreaks, hallucinations, and policy bypasses.",
      "프롬프트, RAG 검색, 에이전트 도구 경계를 대상으로 탈옥, 환각(Hallucination), 정책 우회 여부를 점검하는 구조화된 AI 레드팀 평가를 정기적으로 수행합니다.",
    ),
    benefits: text(
      "Uncovers novel prompt-injection vectors and grounding weaknesses before model or prompt updates reach production.",
      "모델 업그레이드나 프롬프트 변경이 운영 환경에 반영되기 전에 새로운 프롬프트 인젝션 경로와 근거 검증 취약점을 사전에 발견합니다.",
    ),
    before: text(
      "Prompts and models are updated in production without adversarial evaluation datasets or regression gates.",
      "적대적 평가 데이터셋이나 회귀 검증 게이트 없이 프롬프트와 모델 버전이 운영 환경에 바로 배포됩니다.",
    ),
    after: text(
      "Run automated and human-led AI red-teaming suites across jailbreak, indirect RAG injection, and cross-scope leakage scenarios on every change.",
      "프롬프트·모델·RAG 파이프라인 변경 시마다 탈옥, 간접 RAG 인젝션, 범위 간 정보 유출 시나리오를 포함한 AI 레드팀 평가 스위트를 실행합니다.",
    ),
    verify: text(
      "Review red-team evaluation receipts, failure reproduction records, and verified mitigations before promoting a model or prompt revision.",
      "모델이나 프롬프트 리비전을 승격하기 전에 레드팀 평가 증적, 실패 재현 기록, 완화 조치 검증 결과를 대조하여 확인합니다.",
    ),
    caution: text(
      "Passing a static benchmark does not guarantee immunity to novel attacks; red-team corpora must evolve with new threat intelligence.",
      "정적 벤치마크를 통과했다고 해서 새로운 공격에 완전히 면역되는 것은 아니므로 레드팀 시나리오를 최신 위협 인텔리전스에 맞춰 지속적으로 갱신해야 합니다.",
    ),
  },
};

const MCSB_V2_DOMAIN_URLS: Readonly<Record<string, string>> = {
  NS: "https://learn.microsoft.com/en-us/security/benchmark/azure/mcsb-v2-network-security",
  IM: "https://learn.microsoft.com/en-us/security/benchmark/azure/mcsb-v2-identity-management",
  PA: "https://learn.microsoft.com/en-us/security/benchmark/azure/mcsb-v2-privileged-access",
  DP: "https://learn.microsoft.com/en-us/security/benchmark/azure/mcsb-v2-data-protection",
  AM: "https://learn.microsoft.com/en-us/security/benchmark/azure/mcsb-v2-asset-management",
  LT: "https://learn.microsoft.com/en-us/security/benchmark/azure/mcsb-v2-logging-threat-detection",
  IR: "https://learn.microsoft.com/en-us/security/benchmark/azure/mcsb-v2-incident-response",
  PV: "https://learn.microsoft.com/en-us/security/benchmark/azure/mcsb-v2-posture-vulnerability-management",
  ES: "https://learn.microsoft.com/en-us/security/benchmark/azure/mcsb-v2-endpoint-security",
  BR: "https://learn.microsoft.com/en-us/security/benchmark/azure/mcsb-v2-backup-recovery",
  DS: "https://learn.microsoft.com/en-us/security/benchmark/azure/mcsb-v2-devops-security",
  AI: "https://learn.microsoft.com/en-us/security/benchmark/azure/mcsb-v2-artificial-intelligence-security",
};

const MCSB_DOMAIN_PROFILES: Readonly<Record<string, {
  readonly kind: string;
  readonly nameEn: string;
  readonly nameKo: string;
  readonly configLabel: GuidanceText;
  readonly mechLabel: GuidanceText;
  readonly evLabel: GuidanceText;
  readonly mechanism: GuidanceText;
}>> = {
  NS: {
    kind: "mcsb-v2-network-security",
    nameEn: "Network Security",
    nameKo: "네트워크 보안",
    configLabel: text("Zero-trust segmentation and edge firewall", "제로 트러스트 분할 및 경계 방화벽 구성"),
    mechLabel: text("Private Link, NSG, WAF and DDoS boundary", "Private Link·NSG·WAF·DDoS 방어 경계"),
    evLabel: text("Flow logs and route table verification", "흐름 로그 및 라우팅·방화벽 규칙 검증"),
    mechanism: text(
      "Network security controls isolate workload tiers, block unauthorized public ingress/egress, and inspect traffic at defined perimeter boundaries.",
      "네트워크 보안 통제는 워크로드 계층을 격리하고 비인가 공용 인바운드·아웃바운드를 차단하며 지정된 경계에서 트래픽을 심층 검사합니다.",
    ),
  },
  IM: {
    kind: "mcsb-v2-identity-management",
    nameEn: "Identity Management",
    nameKo: "ID 및 신원 관리",
    configLabel: text("Entra ID SSO and Managed Identity policy", "Entra ID 중앙 인증 및 관리 ID 정책"),
    mechLabel: text("Conditional Access and phishing-resistant MFA", "조건부 액세스 및 피싱 저항성 MFA 경계"),
    evLabel: text("Sign-in logs and credential hygiene check", "로그인 감사 로그 및 자격 증명 상태 검증"),
    mechanism: text(
      "Centralized identity governance replaces static secrets with short-lived federated tokens, strong authentication, and conditional access evaluation.",
      "중앙 집중식 신원 거버넌스는 정적 비밀값을 단기 연합 토큰, 강력한 다중 인증(MFA), 조건부 액세스 정책 평가로 대체합니다.",
    ),
  },
  PA: {
    kind: "mcsb-v2-privileged-access",
    nameEn: "Privileged Access",
    nameKo: "권한 있는 액세스",
    configLabel: text("Least privilege RBAC and JIT PIM policy", "최소 권한 RBAC 및 JIT 권한 승격 정책"),
    mechLabel: text("Approval workflow and break-glass isolation", "승인 워크플로 및 비상 계정 격리 경계"),
    evLabel: text("Access review and role assignment audit", "정기 액세스 검토 및 역할 배정 감사"),
    mechanism: text(
      "Privileged access controls eliminate standing administrative permissions, enforce just-in-time elevation, and bound blast radius per scope.",
      "권한 있는 액세스 통제는 상시 관리자 권한을 제거하고 적시(JIT) 권한 승격을 강제하며 범위별 영향 반경을 최소화합니다.",
    ),
  },
  DP: {
    kind: "mcsb-v2-data-protection",
    nameEn: "Data Protection",
    nameKo: "데이터 보호",
    configLabel: text("Data classification, TLS and at-rest encryption", "데이터 분류·전송 암호화(TLS)·저장 암호화"),
    mechLabel: text("Key Vault CMK and certificate lifecycle boundary", "Key Vault 고객 관리형 키(CMK)·인증서 경계"),
    evLabel: text("Encryption state and key custody audit", "암호화 설정 및 키 보관소 접근 감사"),
    mechanism: text(
      "Data protection controls safeguard sensitive information across discovery, transit, storage, and cryptographic key lifecycle management.",
      "데이터 보호 통제는 민감 데이터의 식별·분류부터 전송 구간, 저장소, 암호화 키·인증서 수명주기에 걸쳐 기밀성과 무결성을 보호합니다.",
    ),
  },
  AM: {
    kind: "mcsb-v2-asset-management",
    nameEn: "Asset Management",
    nameKo: "자산 관리",
    configLabel: text("Approved service catalog and tagging policy", "승인된 서비스 목록 및 메타데이터 태깅 정책"),
    mechLabel: text("Azure Resource Graph inventory and lifecycle gate", "리소스 그래프 인벤토리 및 수명주기 경계"),
    evLabel: text("Inventory completeness and drift verification", "자산 인벤토리 완전성 및 드리프트 검증"),
    mechanism: text(
      "Asset management tracks every cloud resource, enforces approved service types and ownership metadata, and governs decommissioning.",
      "자산 관리는 모든 클라우드 리소스를 실시간 인벤토리로 추적하고 승인된 서비스 유형과 소유자 메타데이터를 강제하며 수명주기를 통제합니다.",
    ),
  },
  LT: {
    kind: "mcsb-v2-logging-threat-detection",
    nameEn: "Logging and Threat Detection",
    nameKo: "로깅 및 위협 탐지",
    configLabel: text("Diagnostic settings and SIEM detection rules", "진단 설정 및 중앙 SIEM 위협 탐지 규칙"),
    mechLabel: text("Log Analytics retention and time-sync pipeline", "로그 분석 보존 및 시간 동기화 파이프라인"),
    evLabel: text("Telemetry coverage and alert routing check", "원격 분석 수집 범위 및 경보 전달 검증"),
    mechanism: text(
      "Logging and threat detection collect control-plane, data-plane, and network telemetry into a tamper-evident analytical workspace.",
      "로깅 및 위협 탐지는 컨트롤 플레인, 데이터 플레인, 네트워크 원격 분석 로그를 중앙 분석 워크스페이스로 수집하여 이상 징후를 포착합니다.",
    ),
  },
  IR: {
    kind: "mcsb-v2-incident-response",
    nameEn: "Incident Response",
    nameKo: "인시던트 대응",
    configLabel: text("Incident response plan and alert correlation", "인시던트 대응 계획 및 고품질 경보 상관분석"),
    mechLabel: text("Automated triage, containment and forensics loop", "자동 분류·격리·포렌식 증거 보존 경계"),
    evLabel: text("Response drill and post-incident review check", "대응 모의 훈련 및 사후 교훈 검토 검증"),
    mechanism: text(
      "Incident response connects high-signal detections to accountable responders, bounded containment workflows, and forensic evidence retention.",
      "인시던트 대응은 정밀하게 필터링된 탐지 신호를 책임 담당자, 범위가 제한된 격리 워크플로, 포렌식 증거 보존 절차와 연결합니다.",
    ),
  },
  PV: {
    kind: "mcsb-v2-posture-vulnerability",
    nameEn: "Posture and Vulnerability Management",
    nameKo: "보안 태세 및 취약성 관리",
    configLabel: text("Secure configuration baseline and vulnerability scan", "보안 구성 기준선 및 지속적 취약점 스캔"),
    mechLabel: text("Automated patching and red-team validation loop", "패치 자동화 및 레드팀 검증 파이프라인"),
    evLabel: text("Baseline drift and CVE exposure verification", "기준선 이탈 및 CVE 노출 해소 검증"),
    mechanism: text(
      "Posture and vulnerability management continuously audits resource configurations and software versions against hardened baselines and MSRC advisories.",
      "보안 태세 및 취약성 관리는 리소스 구성과 소프트웨어 버전을 강화된 보안 기준선 및 MSRC 보안 권고와 지속적으로 대조·교정합니다.",
    ),
  },
  ES: {
    kind: "mcsb-v2-endpoint-security",
    nameEn: "Endpoint Security",
    nameKo: "엔드포인트 보안",
    configLabel: text("EDR deployment and anti-malware policy", "EDR 배포 및 최신 맬웨어 방지 정책"),
    mechLabel: text("Behavioral telemetry and signature update loop", "행위 기반 원격 분석 및 서명 자동 갱신 경계"),
    evLabel: text("Endpoint agent health and signature freshness check", "엔드포인트 에이전트 상태 및 서명 최신성 검증"),
    mechanism: text(
      "Endpoint security enforces real-time anti-malware, automatic signature updates, and Endpoint Detection and Response (EDR) on compute hosts.",
      "엔드포인트 보안은 컴퓨팅 호스트에 실시간 맬웨어 방지, 서명 자동 갱신, 엔드포인트 탐지 및 대응(EDR) 에이전트를 강제합니다.",
    ),
  },
  BR: {
    kind: "mcsb-v2-backup-recovery",
    nameEn: "Backup and Recovery",
    nameKo: "백업 및 복구",
    configLabel: text("Automated backup schedule and vault immutability", "자동 백업 일정 및 자격 증명 모음 불변성 정책"),
    mechLabel: text("Soft delete, CMK encryption and cross-zone/region copy", "소프트 삭제·CMK 암호화·교차 영역 복제 경계"),
    evLabel: text("Restore drill and recovery point verification", "정기 복원 훈련 및 복구 지점(RPO/RTO) 검증"),
    mechanism: text(
      "Backup and recovery controls protect stateful data against accidental deletion, ransomware, and regional outages with tested restore procedures.",
      "백업 및 복구 통제는 우발적 삭제, 랜섬웨어, 리전 장애로부터 상태 저장 데이터를 보호하고 실제 복원 훈련으로 복구 가능성을 검증합니다.",
    ),
  },
  DS: {
    kind: "mcsb-v2-devops-security",
    nameEn: "DevOps Security",
    nameKo: "DevOps 보안",
    configLabel: text("Threat modeling, SAST/DAST and supply-chain gates", "위협 모델링·SAST/DAST·공급망 보안 게이트"),
    mechLabel: text("Hardened CI/CD runner and signed artifact registry", "강화된 CI/CD 러너 및 서명된 아티팩트 경계"),
    evLabel: text("Pipeline audit log and dependency scan verification", "파이프라인 감사 로그 및 의존성 검증"),
    mechanism: text(
      "DevOps security embeds threat modeling, static/dynamic scanning, dependency verification, and runner isolation throughout the delivery lifecycle.",
      "DevOps 보안은 위협 모델링, 정적·동적 보안 분석(SAST/DAST), 의존성 무결성 검증, 빌드 러너 격리를 배포 전 과정에 내재화합니다.",
    ),
  },
  AI: {
    kind: "mcsb-v2-ai-security",
    nameEn: "Artificial Intelligence Security",
    nameKo: "인공 지능(AI) 보안",
    configLabel: text("Approved model registry, meta-prompt and content shield", "승인 모델 레지스트리·메타 프롬프트·콘텐츠 실드"),
    mechLabel: text("Least-privilege agent tools, HIL gate and AI red-teaming", "최소 권한 에이전트 도구·HIL 승인·AI 레드팀 경계"),
    evLabel: text("Trajectory audit, filter receipts and red-team verification", "실행 궤적 감사·필터 증적·레드팀 검증"),
    mechanism: text(
      "AI security governs model provenance, multi-layered input/output safety shields, prompt boundaries, least-privilege agent tools, HIL approvals, and continuous AI red-teaming.",
      "인공 지능(AI) 보안은 모델 출처 검증, 다계층 입출력 안전 필터, 프롬프트 경계, 최소 권한 에이전트 도구, 인간 개입(HIL) 승인, 지속적 AI 레드팀 검증을 통합 통제합니다.",
    ),
  },
};

export function mcsbDisplayTitle(
  version: "v1" | "v2-preview",
  control: Pick<McsbControl, "control_id" | "title" | "title_ko">,
  locale: string,
): string {
  if (locale !== "ko") return control.title;
  if (control.title_ko) return control.title_ko;
  const ai = AI_CONTROLS[control.control_id];
  if (ai) return ai.titleKo;
  const v1Entry = FRAMEWORK_TITLES_BY_KEY[`azure-mcsb:${control.control_id}`];
  if (v1Entry && (version === "v2-preview" || v1Entry.en === control.title)) {
    return v1Entry.ko;
  }
  return control.title;
}

export function buildMcsbV2Guidance(detail: McsbControlDetail): GuidancePresentation {
  const domain = detail.domain in MCSB_DOMAIN_PROFILES ? detail.domain : detail.control_id.split("-")[0] ?? "NS";
  const profile = MCSB_DOMAIN_PROFILES[domain] ?? MCSB_DOMAIN_PROFILES["NS"]!;
  const ai = AI_CONTROLS[detail.control_id];
  const titleKo = mcsbDisplayTitle("v2-preview", detail, "ko");
  const title: GuidanceText = text(detail.title, titleKo);
  const learnUrl = (typeof detail.source["source_url"] === "string" && detail.source["source_url"].startsWith("https://learn.microsoft.com/"))
    ? detail.source["source_url"]
    : (MCSB_V2_DOMAIN_URLS[domain] ?? "https://learn.microsoft.com/en-us/security/benchmark/azure/overview");

  const summary = ai
    ? ai.summary
    : text(
        `${detail.title} (${detail.control_id}) defines the MCSB v2 preview security expectation for ${profile.nameEn}. ${profile.mechanism.en}`,
        `${titleKo}(${detail.control_id}) 항목은 ${profile.nameKo} 도메인의 MCSB v2 미리 보기 보안 기준을 정의합니다. ${profile.mechanism.ko}`,
      );
  const benefits = ai
    ? ai.benefits
    : text(
        `Establishes a verifiable ${profile.nameEn.toLowerCase()} boundary across cloud workloads and reduces exposure to configuration drift or unmonitored attack paths.`,
        `클라우드 워크로드 전반에 검증 가능한 ${profile.nameKo} 경계를 수립하고 구성 드리프트나 모니터링되지 않는 공격 경로 노출을 줄입니다.`,
      );
  const before = ai
    ? ai.before
    : text(
        `Workloads operate without standardized ${detail.control_id} (${detail.title.toLowerCase()}) guardrails or rely on ad-hoc per-resource configuration.`,
        `워크로드가 표준화된 ${detail.control_id}(${titleKo}) 가드레일 없이 운영되거나 리소스별 임시 수동 설정에 의존합니다.`,
      );
  const after = ai
    ? ai.after
    : text(
        `Enforce ${detail.control_id} (${detail.title}) across the target workload scope and retain auditable configuration, policy, and operational evidence.`,
        `대상 워크로드 범위에 ${detail.control_id}(${titleKo}) 통제를 일관되게 구성하고 감사 가능한 정책·런타임·운영 근거를 보존합니다.`,
      );
  const verify = ai
    ? ai.verify
    : text(
        `Inspect authoritative resource configuration, policy compliance state, and operational logs for ${detail.control_id} across the workload scope.`,
        `대상 워크로드 범위에서 ${detail.control_id} 관련 리소스 구성, 정책 준수 상태, 운영 감사 로그를 독립적으로 대조하여 검증합니다.`,
      );
  const caution = ai
    ? ai.caution
    : text(
        `MCSB v2 preview definitions are cataloged for architectural review; never conflate v2 preview catalog presence with v1 shadow assessment results.`,
        `MCSB v2 미리 보기 정의는 아키텍처 및 보안 기준 검토용으로 제공되며, v1 섀도 평가 결과와 혼동하거나 자동 충족으로 간주하지 않습니다.`,
      );

  const nodes: readonly GuidanceNode[] = [
    {
      id: "subject",
      label: title,
      detail: before,
      role: "subject",
    },
    {
      id: "configuration",
      label: profile.configLabel,
      detail: after,
      role: "configuration",
    },
    {
      id: "evidence",
      label: profile.evLabel,
      detail: verify,
      role: "evidence",
    },
    {
      id: "mechanism",
      label: profile.mechLabel,
      detail: profile.mechanism,
      role: "dependency",
    },
    {
      id: "outcome",
      label: text("Expected security outcome", "기대 보안 효과"),
      detail: benefits,
      role: "outcome",
    },
  ];

  const referenceImage = resolveControlReferenceImage("mcsb-v2-preview", detail.control_id);

  return {
    title,
    summary,
    benefits,
    rationale: text(
      `${summary.en} In FDAI, MCSB v2 preview (${detail.control_id}) is tracked as an explicit preview benchmark definition (${detail.coverage} crosswalk state) and never silently inherits MCSB v1 assessment verdicts.`,
      `${summary.ko} FDAI에서 MCSB v2 미리 보기(${detail.control_id})는 명시적인 미리 보기 벤치마크 정의(교차 매핑 상태: ${detail.coverage})로 관리되며, MCSB v1 섀도 평가 판정을 임의로 상속하지 않습니다.`,
    ),
    applicability: [
      text(
        `Applies to Azure workloads and platform services governed under the MCSB v2 preview ${profile.nameEn} (${domain}) domain.`,
        `MCSB v2 미리 보기 ${profile.nameKo}(${domain}) 도메인 적용을 받는 Azure 워크로드 및 플랫폼 서비스 범위에 적용합니다.`,
      ),
      text(
        "Preview benchmark mapping status remains distinct from runtime compliance or execution authority.",
        "미리 보기 벤치마크 매핑 상태는 실제 런타임 준수 판정이나 실행 권한과 엄격히 구분됩니다.",
      ),
    ],
    configuration: {
      before: [
        before,
        text(
          `Illustrative gap: ${detail.control_id} has no reviewed v2-preview evidence bundle or automated rule binding yet.`,
          `예시 공백: ${detail.control_id} 항목에 대해 검토된 v2 미리 보기 근거 묶음이나 자동 규칙 바인딩이 아직 연결되지 않았습니다.`,
        ),
      ],
      after: [
        after,
        text(
          `Illustrative target: align workload controls with ${detail.control_id} and verify through independent telemetry and review.`,
          `예시 목표: 워크로드 통제를 ${detail.control_id} 기준에 맞추고 독립적인 원격 분석 및 보안 검토로 확인합니다.`,
        ),
      ],
    },
    implementation_steps: [
      text(
        `Review the official MCSB v2 preview ${profile.nameEn} (${detail.control_id}) specification and identify in-scope workload resources.`,
        `공식 MCSB v2 미리 보기 ${profile.nameKo}(${detail.control_id}) 명세를 검토하고 적용 대상 워크로드 리소스를 식별합니다.`,
      ),
      after,
      text(
        "Document accountable ownership, required policy/telemetry evidence, and any scoped exceptions before promoting to operational enforcement.",
        "운영 강제 적용으로 전환하기 전에 책임 담당자, 필수 정책·원격 분석 근거, 범위가 지정된 예외 조건을 문서화합니다.",
      ),
    ],
    verification_steps: [
      verify,
      text(
        `Confirm that ${detail.control_id} evidence covers the complete target workload scope and meets freshness requirements.`,
        `${detail.control_id} 검증 근거가 대상 워크로드 전체 범위를 포괄하고 최신성 기준을 충족하는지 확인합니다.`,
      ),
      text(
        "Preserve unmapped or pending items explicitly rather than treating this architectural guide as compliance proof.",
        "이 아키텍처 가이드를 규정 준수 증거로 간주하지 말고 미매핑 또는 검토 대기 항목을 명시적으로 유지합니다.",
      ),
    ],
    cautions: [
      caution,
      text(
        "These before/after examples are instructional only. Reading this guide grants no execution authority.",
        "변경 전후 예시는 이해를 돕기 위한 설명용입니다. 이 안내를 열람해도 실행 권한은 부여되지 않습니다.",
      ),
    ],
    ...(referenceImage ? { reference_image: referenceImage } : {}),
    diagram: {
      id: `mcsb-v2.${detail.control_id.toLowerCase()}`,
      kind: profile.kind,
      title,
      description: text(
        "Illustrative MCSB v2 preview security architecture relationship, not an observed installation result.",
        "관측한 설치 환경이나 준수 결과가 아닌, MCSB v2 미리 보기 보안 아키텍처 관계 도식입니다.",
      ),
      nodes,
      edges: [
        {
          from: "subject",
          to: "configuration",
          label: text("Apply domain control", "도메인 보안 통제 적용"),
          style: "solid",
        },
        {
          from: "subject",
          to: "mechanism",
          label: text("Bind defense boundary", "방어 경계 결합"),
          style: "solid",
        },
        {
          from: "configuration",
          to: "evidence",
          label: text("Verify independently", "독립적으로 검증"),
          style: "solid",
        },
        {
          from: "mechanism",
          to: "evidence",
          label: text("Inspect security telemetry", "보안 원격 분석 및 상태 확인"),
          style: "dashed",
        },
        {
          from: "evidence",
          to: "outcome",
          label: text("Assess, do not assume", "가정하지 않고 평가"),
          style: "dashed",
        },
      ],
    },
    sources: [
      {
        kind: "learn",
        url: learnUrl,
        label: text(
          `Microsoft Learn - MCSB v2 Preview (${profile.nameEn}); source license CC BY 4.0`,
          `Microsoft Learn - MCSB v2 미리 보기 (${profile.nameKo}), 원천 라이선스 CC BY 4.0`,
        ),
      },
    ],
  };
}
