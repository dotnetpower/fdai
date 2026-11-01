import type { MsrcCsafControlRow } from "./msrc-csaf-controls.model";
import { resolveControlReferenceImage } from "./reference-images.catalog";
import type { GuidanceNode, GuidancePresentation, GuidanceText } from "./wara-guidance.model";

function text(en: string, ko: string): GuidanceText {
  return { en, ko };
}

const VULNERABILITY_SUFFIX_TRANSLATIONS: readonly (readonly [RegExp, string])[] = [
  [/\bRemote Code Execution Vulnerability$/i, "원격 코드 실행(RCE) 취약점"],
  [/\bElevation of Privilege Vulnerability$/i, "권한 상승(EoP) 취약점"],
  [/\bPrivilege Escalation Vulnerability$/i, "권한 상승(EoP) 취약점"],
  [/\bInformation Disclosure Vulnerability$/i, "정보 노출(ID) 취약점"],
  [/\bDenial of Service Vulnerability$/i, "서비스 거부(DoS) 취약점"],
  [/\bSecurity Feature Bypass Vulnerability$/i, "보안 기능 우회(SFB) 취약점"],
  [/\bSpoofing Vulnerability$/i, "스푸핑(Spoofing) 취약점"],
  [/\bTampering Vulnerability$/i, "데이터·구성 변조(Tampering) 취약점"],
  [/\bCross-Site Scripting \(XSS\) Vulnerability$/i, "사이트 간 스크립팅(XSS) 취약점"],
  [/\bCross-Site Scripting Vulnerability$/i, "사이트 간 스크립팅(XSS) 취약점"],
  [/\bCross-Site Request Forgery \(CSRF\) Vulnerability$/i, "사이트 간 요청 위조(CSRF) 취약점"],
  [/\bCross-Site Request Forgery Vulnerability$/i, "사이트 간 요청 위조(CSRF) 취약점"],
  [/\bAuthentication Bypass Vulnerability$/i, "인증 우회 취약점"],
  [/\bImproper Access Control Vulnerability$/i, "부적절한 접근 통제 취약점"],
  [/\bImproper Certificate Validation Vulnerability$/i, "인증서 검증 미흡 취약점"],
  [/\bDeserialization of Untrusted Data Vulnerability$/i, "비신뢰 데이터 역직렬화 취약점"],
  [/\bCommand Injection Vulnerability$/i, "명령어 인젝션 취약점"],
  [/\bPrompt Injection Vulnerability$/i, "프롬프트 인젝션(Prompt Injection) 취약점"],
  [/\bModel Weight Exfiltration Vulnerability$/i, "모델 가중치 유출 취약점"],
  [/\bDirectory Traversal Vulnerability$/i, "디렉터리 트래버설(경로 조작) 취약점"],
  [/\bPath Traversal Vulnerability$/i, "경로 탐색(Path Traversal) 취약점"],
  [/\bInteger Overflow Vulnerability$/i, "정수 오버플로(Integer Overflow) 취약점"],
  [/\bRace Condition Vulnerability$/i, "경쟁 조건(Race Condition) 취약점"],
  [/\bCryptographic Weakness Vulnerability$/i, "암호화 약점 취약점"],
  [/\bNull Pointer Dereference Vulnerability$/i, "널 포인터 역참조 취약점"],
  [/\bMemory Corruption Vulnerability$/i, "메모리 손상 취약점"],
  [/\bOut-of-bounds Read Vulnerability$/i, "경계 밖 읽기(OOB Read) 취약점"],
  [/\bOut-of-bounds Write Vulnerability$/i, "경계 밖 쓰기(OOB Write) 취약점"],
  [/\bUse After Free Vulnerability$/i, "해제 후 재사용(UAF) 취약점"],
  [/\bHeap-based Buffer Overflow Vulnerability$/i, "힙 버퍼 오버플로 취약점"],
  [/\bStack-based Buffer Overflow Vulnerability$/i, "스택 버퍼 오버플로 취약점"],
  [/\bServer-Side Request Forgery \(SSRF\) Vulnerability$/i, "서버 측 요청 위조(SSRF) 취약점"],
  [/\bServer-Side Request Forgery Vulnerability$/i, "서버 측 요청 위조(SSRF) 취약점"],
  [/\bSQL Injection Vulnerability$/i, "SQL 인젝션 취약점"],
  [/\bCross-Tenant Information Disclosure$/i, "테넌트 간 정보 노출 취약점"],
  [/\bContainer Escape and Privilege Escalation$/i, "컨테이너 이스케이프 및 권한 상승 취약점"],
  [/\bProtocol Downgrade and Session Hijacking$/i, "프로토콜 다운그레이드 및 세션 하이재킹 취약점"],
  [/\bUnauthenticated Administrative API Exposure$/i, "비인증 관리 API 노출 취약점"],
  [/\bVulnerability$/i, "보안 취약점"],
];

export type CvePriorityTier = "P0" | "P1" | "P2" | "P3";

export function computeCvePriorityTier(
  row: Pick<MsrcCsafControlRow, "exploit_status" | "publicly_disclosed" | "cvss_base_score" | "exposure">,
): CvePriorityTier {
  if (
    row.exploit_status === "exploited"
    || (row.publicly_disclosed && row.cvss_base_score >= 9.0)
    || (row.exposure === "affected" && row.cvss_base_score >= 8.5)
  ) {
    return "P0";
  }
  if (
    row.exploit_status === "exploitation_more_likely"
    || row.cvss_base_score >= 8.0
    || row.exposure === "affected"
  ) {
    return "P1";
  }
  if (row.cvss_base_score >= 6.5 || row.publicly_disclosed) {
    return "P2";
  }
  return "P3";
}

export interface AttackSurfaceSummary {
  readonly summary: GuidanceText;
  readonly tone: "danger" | "warning" | "info" | "neutral";
}

export function summarizeAttackSurface(cvssVector: string): AttackSurfaceSummary {
  const tokens = new Map<string, string>();
  for (const part of cvssVector.split("/")) {
    const [key, val] = part.split(":");
    if (key && val) tokens.set(key, val);
  }
  const isRemote = tokens.get("AV") === "N";
  const isUnauth = tokens.get("PR") === "N";
  const isZeroClick = tokens.get("UI") === "N";
  const isScopeChanged = tokens.get("S") === "C";

  if (isRemote && isUnauth && isZeroClick) {
    return {
      summary: text(
        isScopeChanged
          ? "Remote · Unauthenticated · Zero-Click · Cross-Boundary Scope (Critical exposure)"
          : "Remote · Unauthenticated · Zero-Click (High network exposure)",
        isScopeChanged
          ? "원격 네트워크 · 무인증 · 제로클릭 · 타 계층 확산(Scope Changed) - 최우선 격리 대상"
          : "원격 네트워크 · 무인증 · 제로클릭 - 고위험 네트워크 노출",
      ),
      tone: "danger",
    };
  }
  if (isRemote && (isUnauth || isZeroClick)) {
    return {
      summary: text(
        `Remote Network Vector · ${isUnauth ? "Unauthenticated" : "Authenticated"} · ${isZeroClick ? "Zero-Click" : "User Interaction Required"}`,
        `원격 네트워크 경로 · ${isUnauth ? "무인증 공격 가능" : "인증 권한 필요"} · ${isZeroClick ? "제로클릭" : "사용자 상호작용 필요"}`,
      ),
      tone: "warning",
    };
  }
  if (tokens.get("AV") === "A") {
    return {
      summary: text(
        "Adjacent Network Vector (VNet / Subnet / L2 broadcast domain)",
        "인접 네트워크 경로 (동일 VNet·서브넷·브로드캐스트 도메인)",
      ),
      tone: "warning",
    };
  }
  return {
    summary: text(
      `Local / Authenticated Vector (${isScopeChanged ? "Cross-Boundary Scope" : "Component-Local Scope"})`,
      `로컬·인증 필요 경로 (${isScopeChanged ? "타 계층 확산 가능" : "단일 구성요소 내 제한"})`,
    ),
    tone: isScopeChanged ? "warning" : "info",
  };
}

export function msrcCsafDisplayTitle(
  row: Pick<MsrcCsafControlRow, "title">,
  locale: string,
): string {
  if (locale !== "ko") return row.title;
  for (const [pattern, replacement] of VULNERABILITY_SUFFIX_TRANSLATIONS) {
    if (pattern.test(row.title)) {
      return row.title.replace(pattern, replacement);
    }
  }
  return `${row.title} (보안 권고)`;
}

export interface CvssVectorDimension {
  readonly code: string;
  readonly label: GuidanceText;
  readonly value: GuidanceText;
  readonly tone: "danger" | "warning" | "info" | "neutral";
}

const CVSS_DIMENSIONS: Readonly<Record<string, {
  readonly label: GuidanceText;
  readonly values: Readonly<Record<string, { readonly text: GuidanceText; readonly tone: CvssVectorDimension["tone"] }>>;
}>> = {
  AV: {
    label: text("Attack Vector", "공격 경로 (AV)"),
    values: {
      N: { text: text("Network (Remote)", "네트워크 (원격 악용 가능)"), tone: "danger" },
      A: { text: text("Adjacent Network", "인접 네트워크"), tone: "warning" },
      L: { text: text("Local Access", "로컬 접근 필요"), tone: "info" },
      P: { text: text("Physical Access", "물리적 접근 필요"), tone: "neutral" },
    },
  },
  AC: {
    label: text("Attack Complexity", "공격 복잡도 (AC)"),
    values: {
      L: { text: text("Low (Repeatable)", "낮음 (조건 없이 재현 가능)"), tone: "danger" },
      H: { text: text("High (Specialized conditions)", "높음 (특수 조건 필요)"), tone: "info" },
    },
  },
  PR: {
    label: text("Privileges Required", "필요 권한 (PR)"),
    values: {
      N: { text: text("None (Unauthenticated)", "없음 (무인증 공격 가능)"), tone: "danger" },
      L: { text: text("Low (Standard user)", "낮음 (일반 사용자 권한)"), tone: "warning" },
      H: { text: text("High (Admin privilege)", "높음 (관리자 권한 필요)"), tone: "info" },
    },
  },
  UI: {
    label: text("User Interaction", "사용자 상호작용 (UI)"),
    values: {
      N: { text: text("None (Zero-click)", "불필요 (자동 실행 가능)"), tone: "danger" },
      R: { text: text("Required", "사용자 실행·클릭 필요"), tone: "info" },
    },
  },
  S: {
    label: text("Blast Scope", "영향 범위 (Scope)"),
    values: {
      C: { text: text("Changed (Cross-boundary)", "변경됨 (타 계층·호스트로 확산)"), tone: "danger" },
      U: { text: text("Unchanged (Component-local)", "단일 구성요소 내 제한"), tone: "neutral" },
    },
  },
  C: {
    label: text("Confidentiality", "기밀성 영향 (C)"),
    values: {
      H: { text: text("High (Full disclosure)", "높음 (전체 데이터 노출 위험)"), tone: "danger" },
      L: { text: text("Low (Partial exposure)", "낮음 (일부 노출)"), tone: "warning" },
      N: { text: text("None", "없음"), tone: "neutral" },
    },
  },
  I: {
    label: text("Integrity", "무결성 영향 (I)"),
    values: {
      H: { text: text("High (Tampering / code modification)", "높음 (시스템·데이터 변조 가능)"), tone: "danger" },
      L: { text: text("Low (Limited modification)", "낮음 (제한적 변조)"), tone: "warning" },
      N: { text: text("None", "없음"), tone: "neutral" },
    },
  },
  A: {
    label: text("Availability", "가용성 영향 (A)"),
    values: {
      H: { text: text("High (Full service outage)", "높음 (서비스 전면 중단 위험)"), tone: "danger" },
      L: { text: text("Low (Degraded performance)", "낮음 (성능 저하)"), tone: "warning" },
      N: { text: text("None", "없음"), tone: "neutral" },
    },
  },
  // C36: Support CVSS v3 Temporal metrics (Exploit Code Maturity, Remediation Level, Report Confidence)
  E: {
    label: text("Exploit Maturity", "익스플로잇 성숙도 (E)"),
    values: {
      H: { text: text("High (Autonomous / widespread)", "높음 (자동화·광범위 악용)"), tone: "danger" },
      F: { text: text("Functional exploit exists", "기능적 익스플로잇 존재"), tone: "danger" },
      P: { text: text("Proof-of-concept (PoC)", "개념 증명(PoC) 공개"), tone: "warning" },
      U: { text: text("Unproven", "미확인"), tone: "neutral" },
      X: { text: text("Not defined", "미지정"), tone: "neutral" },
    },
  },
  RL: {
    label: text("Remediation Level", "패치 수준 (RL)"),
    values: {
      O: { text: text("Official fix available", "공식 패치 제공됨"), tone: "info" },
      T: { text: text("Temporary fix", "임시 패치 제공됨"), tone: "warning" },
      W: { text: text("Workaround available", "임시 완화(Workaround) 가능"), tone: "warning" },
      U: { text: text("Unavailable", "패치 미제공"), tone: "danger" },
      X: { text: text("Not defined", "미지정"), tone: "neutral" },
    },
  },
  RC: {
    label: text("Report Confidence", "보고 신뢰도 (RC)"),
    values: {
      C: { text: text("Confirmed by vendor", "공급자 공식 확인됨"), tone: "info" },
      R: { text: text("Reasonable confidence", "상당한 신뢰도"), tone: "neutral" },
      U: { text: text("Unknown confidence", "신뢰도 미확인"), tone: "warning" },
      X: { text: text("Not defined", "미지정"), tone: "neutral" },
    },
  },
};

export function parseCvssVector(vector: string): readonly CvssVectorDimension[] {
  const parts = vector.split("/").slice(1);
  const result: CvssVectorDimension[] = [];
  for (const part of parts) {
    const [key, val] = part.split(":");
    if (!key || !val) continue;
    const spec = CVSS_DIMENSIONS[key];
    const entry = spec?.values[val];
    if (spec && entry) {
      result.push({
        code: `${key}:${val}`,
        label: spec.label,
        value: entry.text,
        tone: entry.tone,
      });
    }
  }
  return result;
}

export function buildMsrcCsafGuidance(
  row: MsrcCsafControlRow,
  sourceRevision: string,
): GuidancePresentation {
  const titleKo = msrcCsafDisplayTitle(row, "ko");
  const title = text(`${row.cve_id}: ${row.title}`, `${row.cve_id}: ${titleKo}`);
  const productNames = row.products.map((p) => p.product_name).join(", ") || row.product_ids.join(", ");
  const vendorFix = row.remediations.find((r) => r.category === "vendor_fix");
  const workaround = row.remediations.find((r) => r.category === "workaround" || r.category === "mitigation");

  const exploitSummaryEn = row.exploit_status === "exploited"
    ? "Active exploitation in the wild has been confirmed by MSRC."
    : row.exploit_status === "exploitation_more_likely"
      ? "MSRC assesses exploitation as more likely based on attack surface and exploit maturity."
      : "Tracked in the pinned MSRC CSAF 2.0 security advisory corpus.";
  const exploitSummaryKo = row.exploit_status === "exploited"
    ? "MSRC에서 실제 악용(Exploited in the wild)이 확인된 고위험 취약점입니다."
    : row.exploit_status === "exploitation_more_likely"
      ? "공격 표면과 익스플로잇 성숙도 기준상 악용 가능성이 높은(Exploitation More Likely) 취약점입니다."
      : "버전이 고정된 MSRC CSAF 2.0 보안 권고 코퍼스에서 추적 중인 취약점입니다.";

  const summary = text(
    `${row.cve_id} (CVSS ${row.cvss_base_score.toFixed(1)}, ${row.severity.toUpperCase()}) affects ${productNames} on canonical resource type ${row.primary_resource_type} within version window ${row.version_window}. ${exploitSummaryEn}`,
    `${row.cve_id} (CVSS ${row.cvss_base_score.toFixed(1)}, 심각도 ${row.severity.toUpperCase()}) 취약점은 정규 리소스 유형 ${row.primary_resource_type}의 ${productNames} 제품(취약 버전 구간: ${row.version_window})에 영향을 미칩니다. ${exploitSummaryKo}`,
  );

  const fixTextEn = vendorFix?.fixed_version
    ? `Upgrade ${productNames} to fixed version >= ${vendorFix.fixed_version}`
    : vendorFix?.details ?? "Apply the official Microsoft security update";
  const fixTextKo = vendorFix?.fixed_version
    ? `${productNames} 버전을 패치 완료 버전(>= ${vendorFix.fixed_version}) 이상으로 업그레이드`
    : "Microsoft 공식 보안 업데이트(Vendor Fix)를 적용";

  const workaroundEn = row.workaround_property
    ? ` or enforce workaround property ${row.workaround_property} = ${String(row.workaround_expected_value)}`
    : workaround?.details
      ? ` or apply the documented MSRC workaround (${workaround.details})`
      : "";
  const workaroundKo = row.workaround_property
    ? `하거나 임시 완화 속성(${row.workaround_property} = ${String(row.workaround_expected_value)})을 강제`
    : workaround?.details
      ? `하거나 MSRC 임시 완화 조치(${workaround.details})를 적용`
      : "";

  const benefits = text(
    `Eliminates ${row.cve_id} exposure on ${row.primary_resource_type} resources and records cryptographic CSAF provenance plus Pantheon audit evidence.`,
    `${row.primary_resource_type} 리소스에서 ${row.cve_id} 취약점 노출을 제거하고 CSAF 서명 검증 출처와 판테온 감사 증적을 남깁니다.`,
  );

  const before = text(
    `${row.primary_resource_type} instances run inside vulnerable version window ${row.version_window} without the MSRC security update or compensating property guard.`,
    `${row.primary_resource_type} 리소스가 취약 버전 구간(${row.version_window})에서 보안 업데이트나 임시 완화 속성 없이 실행되고 있습니다.`,
  );

  const after = text(
    `${fixTextEn}${workaroundEn}, verified by deterministic T0 observation in shadow mode.`,
    `${fixTextKo}${workaroundKo}하고 결정론적 T0 인벤토리 관측으로 완화 상태를 검증합니다.`,
  );

  const verify = text(
    `Observe ${row.primary_resource_type} version and configuration properties in the latest inventory generation and confirm exposure transitions from affected to fixed or mitigated.`,
    `최신 인벤토리 세대에서 ${row.primary_resource_type}의 버전 및 임시 완화 속성을 독립 관측하여 노출 상태가 패치 완료(Fixed) 또는 임시 완화(Mitigated)로 전환되었는지 검증합니다.`,
  );

  const pantheonDetail = text(
    `Heimdall emits msrc_csaf.vulnerability_drift -> Forseti records risk_verdict=hil (shadow_only) -> Saga appends audit-entry -> Norns ${row.disposition === "new_rule_candidate" ? `extracts inert RuleCandidate (msrc-csaf.${row.cve_id.toLowerCase()})` : "retains existing rule mapping"}.`,
    `Heimdall이 취약점 드리프트(msrc_csaf.vulnerability_drift)를 감지하고 Forseti가 HIL/Shadow 판정을 내리면 Saga가 감사 원장에 기록하며 Norns가 ${row.disposition === "new_rule_candidate" ? `불활성 규칙 후보(msrc-csaf.${row.cve_id.toLowerCase()})를 추출` : "기존 규칙 매핑을 유지"}합니다.`,
  );

  const nodes: readonly GuidanceNode[] = [
    {
      id: "subject",
      label: text(`Vulnerable target (${row.primary_resource_type})`, `취약 대상 리소스 (${row.primary_resource_type})`),
      detail: before,
      role: "subject",
    },
    {
      id: "configuration",
      label: text("MSRC patch and workaround control", "MSRC 보안 패치 및 임시 완화 구성"),
      detail: after,
      role: "configuration",
    },
    {
      id: "evidence",
      label: text("CSAF signature and inventory check", "CSAF 서명 및 인벤토리 버전 검증"),
      detail: verify,
      role: "evidence",
    },
    {
      id: "pantheon",
      label: text("Pantheon drift and HIL governance", "판테온 드리프트 탐지 및 HIL 거버넌스"),
      detail: pantheonDetail,
      role: "dependency",
    },
    {
      id: "outcome",
      label: text("Verified exposure closure", "노출 해소 및 안전 검증 완료"),
      detail: benefits,
      role: "outcome",
    },
  ];

  const referenceImage = resolveControlReferenceImage("msrc-csaf", row.cve_id, row.primary_resource_type);

  return {
    title,
    summary,
    benefits,
    rationale: text(
      `Advisory ${row.advisory_tracking_id} (${row.advisory_title}) pins CVSS vector ${row.cvss_vector}. Disposition is ${row.disposition} (${row.mapping_state} mapping)${row.existing_rule_id ? ` linked to T0 rule ${row.existing_rule_id}` : ""}${row.candidate_action_type ? ` and candidate ActionType ${row.candidate_action_type}` : ""}.`,
      `권고문 ${row.advisory_tracking_id}(${row.advisory_title})는 CVSS 벡터 ${row.cvss_vector}를 기록합니다. 처분 유형은 ${row.disposition}(매핑 상태: ${row.mapping_state})이며${row.existing_rule_id ? ` T0 규칙 ${row.existing_rule_id}` : ""}${row.candidate_action_type ? ` 및 후보 ActionType ${row.candidate_action_type}` : ""}와 연결됩니다.`,
    ),
    applicability: [
      text(
        `Applies to ${row.primary_resource_type} resources matching CSAF product IDs (${row.product_ids.join(", ")}) within version window ${row.version_window}.`,
        `버전 구간 ${row.version_window}에 속하는 CSAF 제품 ID(${row.product_ids.join(", ")}) 기반 ${row.primary_resource_type} 리소스에 적용됩니다.`,
      ),
      text(
        row.blocked_reasons.length > 0
          ? `Blocked or manual boundary: ${row.blocked_reasons.join(", ")}. Missing version telemetry remains unknown rather than assumed safe.`
          : "Missing or stale resource version telemetry remains explicitly unknown rather than assumed patched.",
        row.blocked_reasons.length > 0
          ? `차단 또는 수동 검토 경계: ${row.blocked_reasons.join(", ")}. 버전 원격 분석 정보가 없으면 안전하다고 가정하지 않고 알 수 없음(Unknown)으로 유지합니다.`
          : "리소스 버전 원격 분석 정보가 없거나 오래된 경우 패치 완료로 가정하지 않고 명시적인 알 수 없음(Unknown) 상태로 유지합니다.",
      ),
    ],
    configuration: {
      before: [
        before,
        text(
          `Attack surface: ${row.cvss_vector} (${row.exploit_status.replace(/_/g, " ")}, publicly disclosed: ${row.publicly_disclosed ? "yes" : "no"}).`,
          `공격 표면: ${row.cvss_vector} (악용 상태: ${row.exploit_status}, 공개 여부: ${row.publicly_disclosed ? "공개됨" : "비공개"}).`,
        ),
      ],
      after: [
        after,
        text(
          `Governed action candidate: ${row.candidate_action_type ?? "manual operator remediation"} (shadow mode, execution_authority=false).`,
          `통제된 조치 후보: ${row.candidate_action_type ?? "운영자 수동 패치 조치"} (Shadow 모드, 실행 권한 없음).`,
        ),
      ],
    },
    implementation_steps: [
      text(
        `Verify the detached signature and SHA-256 digest (${row.document_digest.slice(0, 23)}...) of advisory ${row.advisory_tracking_id}.`,
        `권고문 ${row.advisory_tracking_id}의 분리 서명 검증 여부와 SHA-256 다이제스트(${row.document_digest.slice(0, 23)}...)를 확인합니다.`,
      ),
      after,
      text(
        `Route any state-changing remediation (${row.candidate_action_type ?? "manual"}) through Forseti risk gating, Var HIL approval, dry-run, and rollback verification.`,
        `상태를 변경하는 모든 교정 작업(${row.candidate_action_type ?? "수동 조치"})은 Forseti 위험 게이트, Var 인간 승인(HIL), 사전 시뮬레이션(Dry-run), 롤백 검증을 거쳐 수행합니다.`,
      ),
    ],
    verification_steps: [
      verify,
      text(
        "Confirm Heimdall vulnerability drift clears on the next complete inventory generation and Saga records the verification receipt.",
        "다음 완전한 인벤토리 세대에서 Heimdall 취약점 드리프트가 해소되고 Saga 감사 원장에 검증 증적이 기록되는지 확인합니다.",
      ),
      text(
        "Ensure no unverified or unsupported product mapping is marked fixed without independent version readback.",
        "독립적인 버전 재확인(Readback) 없이 미검증 또는 미지원 제품 매핑이 패치 완료로 표시되지 않았는지 확인합니다.",
      ),
    ],
    cautions: [
      text(
        "Advisory presence in the MSRC CSAF catalog never grants automatic execution authority; all remediation proposals remain shadow-mode and HIL-gated.",
        "MSRC CSAF 카탈로그에 권고문이 등록되어 있다는 사실만으로 자동 실행 권한이 부여되지 않으며, 모든 교정 제안은 Shadow 모드 및 HIL 승인 게이트를 따릅니다.",
      ),
      text(
        row.workaround_property
          ? `Applying workaround ${row.workaround_property}=${String(row.workaround_expected_value)} mitigates exposure temporarily but does not replace upgrading to the fixed release.`
          : "Applying a temporary network or configuration mitigation reduces immediate risk but does not replace the official security update.",
        row.workaround_property
          ? `임시 완화 속성(${row.workaround_property}=${String(row.workaround_expected_value)}) 적용은 노출을 일시적으로 완화할 뿐 공식 보안 패치 업그레이드를 대체하지 않습니다.`
          : "임시 네트워크·구성 완화는 즉각적인 위험을 줄여주지만 공식 보안 업데이트 적용을 대체하지 않습니다.",
      ),
    ],
    ...(referenceImage ? { reference_image: referenceImage } : {}),
    diagram: {
      id: `msrc-csaf.${row.cve_id.toLowerCase()}`,
      kind: "msrc-csaf-defense-flow",
      title,
      description: text(
        "Illustrative CVE exposure, remediation and 15-agent Pantheon defense flow; not an observed installation result.",
        "실제 설치 환경의 관측 결과가 아닌, CVE 취약점 노출·패치 완화 및 15인 판테온 에이전트 방어 흐름 도식입니다.",
      ),
      nodes,
      edges: [
        {
          from: "subject",
          to: "configuration",
          label: text("Apply patch or workaround", "보안 패치 또는 임시 완화 적용"),
          style: "solid",
        },
        {
          from: "subject",
          to: "pantheon",
          label: text("Heimdall detects version drift", "Heimdall 취약 버전 드리프트 감지"),
          style: "solid",
        },
        {
          from: "configuration",
          to: "evidence",
          label: text("Read back version and property", "버전 및 완화 속성 독립 확인"),
          style: "solid",
        },
        {
          from: "pantheon",
          to: "evidence",
          label: text("Forseti HIL gate and Saga audit", "Forseti HIL 게이트 및 Saga 감사"),
          style: "dashed",
        },
        {
          from: "evidence",
          to: "outcome",
          label: text("Confirm exposure closure", "노출 해소 판정 (가정 금지)"),
          style: "dashed",
        },
      ],
    },
    sources: [
      {
        kind: "learn",
        url: row.source_url,
        label: text(
          `MSRC Security Update Guide - ${row.cve_id} (${row.advisory_tracking_id}, source revision ${sourceRevision})`,
          `MSRC 보안 업데이트 가이드 - ${row.cve_id} (${row.advisory_tracking_id}, 소스 리비전 ${sourceRevision})`,
        ),
      },
    ],
  };
}
