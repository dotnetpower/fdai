import { HubApiError, type InstallationDetail, type PlanReportView, type Suppression } from "./api";
import { isTimingReason } from "./constraint-status";

export type ErrorClassificationKind =
  | "session-expired"
  | "access-denied"
  | "prerequisite-unavailable"
  | "timeout"
  | "network-unreachable"
  | "request-failed";

export interface ClassifiedHubError {
  readonly kind: ErrorClassificationKind;
  readonly title: string;
  readonly guidance: string;
  readonly reasonCode: string | null;
}

const PREREQUISITE_GUIDANCE: Readonly<Record<string, string>> = {
  catalog_not_imported_approve_pin_and_import:
    "No verified catalog is imported yet. Open Catalog import or Updates to approve and import a catalog before reading releases.",
  catalog_unavailable_review_trust_and_expiry:
    "The accepted catalog failed verification or expired. Review catalog trust and freshness on Updates or Catalog import.",
  schema_migration_pending:
    "A Hub database schema migration is pending completion. Writes remain paused until an operator completes the migration.",
  operator_auth_not_configured:
    "Operator sign-in is not configured on this Hub instance. Management endpoints remain unavailable.",
};

/** Classify data-loading and action errors into safe recovery states (UXH-02, UXH-03, UXH-04). */
export function classifyHubError(error: unknown): ClassifiedHubError {
  if (error instanceof HubApiError) {
    if (error.status === 401) {
      return {
        kind: "session-expired",
        title: "Session expired",
        guidance:
          "Sign in again to renew your operator session, then retry this read. Uncertain writes are never replayed automatically.",
        reasonCode: error.reasonCode,
      };
    }
    if (error.status === 403) {
      return {
        kind: "access-denied",
        title: "Operator access or boundary denied",
        guidance:
          "Verify your operator identity and approved network source range. Do not expand application roles to bypass an ingress block.",
        reasonCode: error.reasonCode,
      };
    }
    if (error.status === 503) {
      return {
        kind: "prerequisite-unavailable",
        title: "Service or prerequisite unavailable",
        guidance:
          PREREQUISITE_GUIDANCE[error.reasonCode] ??
          "Check Hub database readiness and prerequisite configuration before retrying.",
        reasonCode: error.reasonCode,
      };
    }
    return {
      kind: "request-failed",
      title: "Could not load Hub data",
      guidance:
        "Review the current Hub state and request parameters before retrying.",
      reasonCode: error.reasonCode,
    };
  }
  if (error instanceof DOMException && ["AbortError", "TimeoutError"].includes(error.name)) {
    return {
      kind: "timeout",
      title: "Request timed out",
      guidance:
        "The Hub did not respond within the request deadline. Refresh to read authoritative state before another action.",
      reasonCode: null,
    };
  }
  if (error instanceof Error && error.name === "InteractionRequiredAuthError") {
    return {
      kind: "session-expired",
      title: "Session renewal requires sign-in",
      guidance:
        "Sign in again to restore your operator session, then refresh the current screen.",
      reasonCode: null,
    };
  }
  if (error instanceof TypeError) {
    return {
      kind: "network-unreachable",
      title: "Hub API unreachable",
      guidance:
        "Check network reachability, DNS resolution, and private ingress rules before diagnosing application permissions.",
      reasonCode: null,
    };
  }
  return {
    kind: "request-failed",
    title: "Could not load Hub data",
    guidance: "Refresh this screen to read the latest authoritative Hub state.",
    reasonCode: null,
  };
}

export type ReadinessPosture =
  | "ready"
  | "scheduled"
  | "in-progress"
  | "waiting"
  | "blocked"
  | "recovery-needed";

export interface ReadinessNextStep {
  readonly posture: ReadinessPosture;
  readonly headline: string;
  readonly headlineKo: string;
  readonly detail: string;
  readonly detailKo: string;
  readonly owner: string;
  readonly ownerKo: string;
  readonly targetTab: "constraints" | "entities" | "schedule" | "configuration" | "application";
}

export interface PrerequisiteFacet {
  readonly id: "entities" | "configuration" | "artifacts" | "agent";
  readonly label: string;
  readonly labelKo: string;
  readonly status: "ok" | "warn" | "fail" | "mute";
  readonly summary: string;
  readonly summaryKo: string;
  readonly owner: string;
}

export interface TimeHorizonSummary {
  readonly environmentReportedAt: string;
  readonly schemaRevision: number;
  readonly windowCount: number;
  readonly scheduleSummary: string;
  readonly scheduleSummaryKo: string;
  readonly planValiditySummary: string;
  readonly planValiditySummaryKo: string;
  readonly planExpired: boolean;
}

export interface RecoveryTimeline {
  readonly currentWorkloadSummary: string;
  readonly currentWorkloadSummaryKo: string;
  readonly latestFailedReport: PlanReportView | null;
  readonly activeHolds: readonly Suppression[];
  readonly recallBlockCodes: readonly string[];
  readonly nextOwner: string;
  readonly nextActionSummary: string;
  readonly nextActionSummaryKo: string;
}

export interface InstallationReadinessView {
  readonly nextStep: ReadinessNextStep;
  readonly prerequisites: readonly PrerequisiteFacet[];
  readonly timeHorizons: TimeHorizonSummary;
  readonly recovery: RecoveryTimeline | null;
}

const STALE_AGENT_REPORT_MS = 24 * 60 * 60 * 1000;

export function deriveInstallationReadiness(
  installation: InstallationDetail,
  nowMs = Date.now(),
): InstallationReadinessView {
  const managedCount = installation.entities.filter((e) => e.managed).length;
  const totalEntities = installation.entities.length;
  const latestReport =
    installation.reports.length > 0
      ? installation.reports[installation.reports.length - 1]!
      : null;
  const latestFailedReport =
    [...installation.reports]
      .reverse()
      .find((r) => r.outcome === "rolled-back" || r.outcome === "rejected") ?? null;
  const failureHold = installation.suppressions.some((s) => s.origin === "failure");
  const manualHold = installation.suppressions.some((s) => s.origin === "manual");
  const allBlocks =
    installation.last_evaluation?.checks.flatMap((check) => check.blocks) ?? [];
  const recallBlockCodes = [
    ...new Set(
      allBlocks
        .map((b) => b.reason_code)
        .filter((code) => code === "recalled_release" || code === "recalled_capability"),
    ),
  ];
  const hasArtifactBlock = allBlocks.some((b) => b.reason_code === "artifact_unavailable");
  const hasHardBlock = allBlocks.some((b) => !isTimingReason(b.reason_code));
  const openPlan = installation.open_plan;
  const openPlanExpired = openPlan !== null && Date.parse(openPlan.expires_at) <= nowMs;
  const openPlanReports = openPlan
    ? installation.reports.filter((r) => r.plan_id === openPlan.plan_id)
    : [];
  const latestOpenPlanReport =
    openPlanReports.length > 0 ? openPlanReports[openPlanReports.length - 1]! : null;

  let nextStep: ReadinessNextStep;
  if (managedCount === 0) {
    nextStep = {
      posture: "blocked",
      headline: "No managed Entity is eligible for planning",
      headlineKo: "계획 대상인 관리형 엔티티가 없습니다",
      detail:
        "Every discovered Entity starts unmanaged. Verify ownership and accept Entity settings before the Hub issues a Plan.",
      detailKo:
        "발견된 모든 엔티티는 비관리 상태로 시작합니다. Hub가 계획을 발급하기 전에 소유권을 검증하고 엔티티 설정을 승인하세요.",
      owner: "Customer Operator",
      ownerKo: "고객 운영자",
      targetTab: "entities",
    };
  } else if (failureHold || latestOpenPlanReport?.outcome === "rolled-back" || latestOpenPlanReport?.outcome === "rejected") {
    nextStep = {
      posture: "recovery-needed",
      headline: "Update held after rollback or execution rejection",
      headlineKo: "롤백 또는 실행 거부로 인해 업데이트가 보류되었습니다",
      detail:
        "Review the original failure report and current workload health below. Automatic failure suppressions hold new upgrades until lifted or expired.",
      detailKo:
        "아래에서 최초 실패 보고와 현재 워크로드 상태를 확인하세요. 자동 실패 억제 구간이 해제되거나 만료될 때까지 새 업그레이드가 보류됩니다.",
      owner: "Customer Operator",
      ownerKo: "고객 운영자",
      targetTab: "constraints",
    };
  } else if (recallBlockCodes.length > 0) {
    nextStep = {
      posture: "recovery-needed",
      headline: "Candidate blocked by vendor recall notice",
      headlineKo: "공급자 회수 공지로 인해 후보 릴리스가 차단되었습니다",
      detail:
        "A release or capability recall blocks promotion to the candidate version. Import the latest catalog or await a non-recalled roll-off Plan.",
      detailKo:
        "릴리스 또는 기능 회수로 인해 해당 후보 버전으로의 전환이 차단되었습니다. 최신 카탈로그를 가져오거나 회수 제외 대상 계획을 확인하세요.",
      owner: "Vendor / Customer Operator",
      ownerKo: "공급자 / 고객 운영자",
      targetTab: "constraints",
    };
  } else if (manualHold) {
    nextStep = {
      posture: "waiting",
      headline: "Held by active manual suppression window",
      headlineKo: "수동 억제 구간이 활성화되어 대기 중입니다",
      detail:
        "Planned upgrades remain held while the manual suppression window is active. Lift the suppression on Commands when ready.",
      detailKo:
        "수동 억제 구간이 활성화된 동안 계획된 업그레이드가 보류됩니다. 준비되면 명령(Commands) 화면에서 억제를 해제하세요.",
      owner: "Customer Operator",
      ownerKo: "고객 운영자",
      targetTab: "constraints",
    };
  } else if (openPlan !== null) {
    if (openPlanExpired) {
      nextStep = {
        posture: "waiting",
        headline: `Open Plan ${openPlan.plan_id} has expired`,
        headlineKo: `열린 계획 ${openPlan.plan_id}의 유효 기간이 만료되었습니다`,
        detail:
          "Expired Plans cannot be dispatched by the Agent. Recompute during the next maintenance window.",
        detailKo:
          "만료된 계획은 에이전트가 실행할 수 없습니다. 다음 유지보수 구간에 계획을 다시 계산하세요.",
        owner: "Hub Planner",
        ownerKo: "Hub 플래너",
        targetTab: "constraints",
      };
    } else if (latestOpenPlanReport?.outcome === "apply-started") {
      nextStep = {
        posture: "in-progress",
        headline: `Agent is applying Plan ${openPlan.plan_id}`,
        headlineKo: `에이전트가 계획 ${openPlan.plan_id}을 적용 중입니다`,
        detail:
          "Execution has started inside the installation cluster. Dispatch is not operational success until the final applied report and health readback arrive.",
        detailKo:
          "설치 클러스터 내부에서 실행이 시작되었습니다. 최종 적용 완료 보고와 상태 확인이 도착하기 전까지는 완료로 간주하지 않습니다.",
        owner: "Installation Agent",
        ownerKo: "설치 에이전트",
        targetTab: "constraints",
      };
    } else if (latestOpenPlanReport?.outcome === "applied") {
      nextStep = {
        posture: "ready",
        headline: `Plan ${openPlan.plan_id} applied; awaiting next state evaluation`,
        headlineKo: `계획 ${openPlan.plan_id} 적용 완료 · 다음 상태 평가 대기 중`,
        detail:
          "The Agent reported applied for the target release. Next state report and recomputation will close out the cycle.",
        detailKo:
          "에이전트가 대상 릴리스 적용 완료를 보고했습니다. 다음 상태 보고 및 재계산 시 주기가 완료됩니다.",
        owner: "Installation Agent",
        ownerKo: "설치 에이전트",
        targetTab: "constraints",
      };
    } else {
      nextStep = {
        posture: "ready",
        headline: `Signed Plan ${openPlan.plan_id} ready for Agent pickup`,
        headlineKo: `서명된 계획 ${openPlan.plan_id}이 에이전트 수령 대기 중입니다`,
        detail: `Target release ${openPlan.target_release_id} is signed and eligible for outbound Agent polling within the active window.`,
        detailKo: `대상 릴리스 ${openPlan.target_release_id}에 대한 서명된 계획이 발급되었으며 에이전트가 폴링하여 실행할 수 있습니다.`,
        owner: "Installation Agent",
        ownerKo: "설치 에이전트",
        targetTab: "constraints",
      };
    }
  } else if (installation.last_evaluation?.outcome === "waiting") {
    if (!hasHardBlock) {
      const target = installation.last_evaluation.target_release_id ?? "next release";
      nextStep = {
        posture: "scheduled",
        headline: `Preauthorized update to ${target} scheduled for next window`,
        headlineKo: `${target} 사전 승인 업데이트가 다음 유지보수 구간에 예약됨`,
        detail:
          "All compatibility and artifact checks passed. The Hub will issue the signed Plan automatically when the maintenance window opens; no manual apply button is needed.",
        detailKo:
          "호환성 및 아티팩트 검사를 모두 통과했습니다. 유지보수 구간이 열리면 서명된 계획이 자동 발급되므로 별도의 수동 실행 버튼이 필요하지 않습니다.",
        owner: "Hub Planner / Installation Agent",
        ownerKo: "Hub 플래너 / 설치 에이전트",
        targetTab: "schedule",
      };
    } else {
      nextStep = {
        posture: "blocked",
        headline: "Update blocked by unmet prerequisite or constraint",
        headlineKo: "선결 조건 또는 제약 미충족으로 업데이트가 차단되었습니다",
        detail:
          "Resolve the non-timing constraint blocks (such as missing mirrored artifacts, schema range, or entity overrides) before the Hub can issue a Plan.",
        detailKo:
          "미러링된 아티팩트 누락, 스키마 범위 불일치 또는 엔티티 재정의 누락 등 차단 사유를 먼저 해결하세요.",
        owner: "Customer Operator / Git Signer",
        ownerKo: "고객 운영자 / 구성 서명자",
        targetTab: "constraints",
      };
    }
  } else if (installation.last_evaluation?.outcome === "up-to-date") {
    nextStep = {
      posture: "ready",
      headline: "Installation is up to date on its subscribed channel",
      headlineKo: "구독 채널의 최신 릴리스가 적용되어 있습니다",
      detail: `Current release ${installation.current_release ?? "installed"} matches the newest eligible release on ${installation.settings.channel}.`,
      detailKo: `현재 릴리스(${installation.current_release ?? "설치됨"})가 ${installation.settings.channel} 채널의 최신 적격 버전과 일치합니다.`,
      owner: "None",
      ownerKo: "조치 불필요",
      targetTab: "constraints",
    };
  } else {
    nextStep = {
      posture: "waiting",
      headline: "Awaiting catalog evaluation",
      headlineKo: "카탈로그 기반 계획 평가 대기 중",
      detail:
        "No Plan evaluation has been recorded yet, or no eligible release matched the subscribed channel and version range.",
      detailKo:
        "아직 계획 평가 기록이 없거나 구독 채널 및 버전 범위에 부합하는 적격 릴리스가 없습니다.",
      owner: "Hub Planner",
      ownerKo: "Hub 플래너",
      targetTab: "constraints",
    };
  }

  const reportedMs = Date.parse(installation.reported_at);
  const agentAgeMs = Number.isFinite(reportedMs) ? Math.max(0, nowMs - reportedMs) : Infinity;
  const agentStale = agentAgeMs > STALE_AGENT_REPORT_MS;

  const prerequisites: PrerequisiteFacet[] = [
    {
      id: "entities",
      label: "Ownership & Entities",
      labelKo: "소유권 및 엔티티",
      status: managedCount > 0 ? "ok" : "fail",
      summary: `${managedCount} of ${totalEntities} managed`,
      summaryKo: `전체 ${totalEntities}개 중 ${managedCount}개 관리됨`,
      owner: "Customer Operator",
    },
    {
      id: "configuration",
      label: "Configuration revision",
      labelKo: "구성 개정본",
      status: "mute",
      summary: `${installation.configuration_digest.slice(0, 19)}... (signature provenance not recorded in inventory)`,
      summaryKo: `${installation.configuration_digest.slice(0, 19)}... (인벤토리에 서명 출처 미기록)`,
      owner: "Customer Git Signer",
    },
    {
      id: "artifacts",
      label: "Artifacts & compatibility",
      labelKo: "아티팩트 및 호환성",
      status: hasArtifactBlock || hasHardBlock ? "fail" : installation.last_evaluation ? "ok" : "mute",
      summary: hasArtifactBlock
        ? "Blocked: required image digest missing in boundary registry"
        : hasHardBlock
        ? "Blocked: constraint check failed"
        : installation.last_evaluation
        ? "Compatible with evaluated release"
        : "Not evaluated yet",
      summaryKo: hasArtifactBlock
        ? "차단됨: 경계 레지스트리에 필수 이미지 다이제스트 누락"
        : hasHardBlock
        ? "차단됨: 제약 조건 검사 실패"
        : installation.last_evaluation
        ? "평가된 릴리스와 호환됨"
        : "아직 평가되지 않음",
      owner: "Boundary Registry / Planner",
    },
    {
      id: "agent",
      label: "Agent contact & last report",
      labelKo: "에이전트 접촉 및 최근 보고",
      status: agentStale ? "warn" : latestFailedReport ? "warn" : "ok",
      summary: latestReport
        ? `Last report: ${latestReport.outcome} (attempt ${latestReport.attempt})${agentStale ? " · state report >24h old" : ""}`
        : agentStale
        ? "State report >24h old · no Plan execution reports yet"
        : "State report fresh · no Plan execution reports yet",
      summaryKo: latestReport
        ? `최근 보고: ${latestReport.outcome} (시도 ${latestReport.attempt})${agentStale ? " · 상태 보고 24시간 경과" : ""}`
        : agentStale
        ? "상태 보고 24시간 경과 · 실행 보고 없음"
        : "상태 보고 최신 · 실행 보고 없음",
      owner: "Installation Agent",
    },
  ];

  const windowCount = installation.settings.windows.length;
  const timeHorizons: TimeHorizonSummary = {
    environmentReportedAt: installation.reported_at,
    schemaRevision: installation.schema_revision,
    windowCount,
    scheduleSummary:
      windowCount > 0
        ? `${windowCount} daily window(s) configured (${installation.settings.windows.map((w) => `${w.start} ${w.timezone}`).join(", ")})`
        : "No daily maintenance window configured",
    scheduleSummaryKo:
      windowCount > 0
        ? `일일 유지보수 구간 ${windowCount}개 설정됨 (${installation.settings.windows.map((w) => `${w.start} ${w.timezone}`).join(", ")})`
        : "설정된 일일 유지보수 구간 없음",
    planValiditySummary: openPlan
      ? openPlanExpired
        ? `Plan ${openPlan.plan_id} expired at ${openPlan.expires_at} (not dispatchable)`
        : `Plan ${openPlan.plan_id} valid until ${openPlan.expires_at}`
      : "No open Plan currently issued",
    planValiditySummaryKo: openPlan
      ? openPlanExpired
        ? `계획 ${openPlan.plan_id} 만료됨 (${openPlan.expires_at}, 실행 불가)`
        : `계획 ${openPlan.plan_id} 유효 기한: ${openPlan.expires_at}`
      : "현재 발급된 열린 계획 없음",
    planExpired: openPlanExpired,
  };

  const hasRecoveryContext =
    latestFailedReport !== null ||
    installation.suppressions.length > 0 ||
    recallBlockCodes.length > 0;

  const recovery: RecoveryTimeline | null = hasRecoveryContext
    ? {
        currentWorkloadSummary: `Release ${installation.current_release ?? "uninstalled"} · health ${installation.health ?? "unknown"}`,
        currentWorkloadSummaryKo: `릴리스 ${installation.current_release ?? "미설치"} · 상태 ${installation.health ?? "unknown"}`,
        latestFailedReport,
        activeHolds: installation.suppressions,
        recallBlockCodes,
        nextOwner: failureHold || manualHold ? "Customer Operator" : "Hub Planner / Agent",
        nextActionSummary: failureHold
          ? "Inspect the failed Plan report, verify cluster workload recovery, then lift the suppression on Commands when safe."
          : recallBlockCodes.length > 0
          ? "Adopt a catalog with a non-recalled release or capability lift so the planner can issue a recall-rolloff Plan."
          : manualHold
          ? "Wait for the manual suppression window to expire or lift it on the Commands screen."
          : "Review the previous failed execution report; no active suppression hold remains.",
        nextActionSummaryKo: failureHold
          ? "실패한 계획 보고서를 확인하고 클러스터 워크로드 복구를 검증한 뒤, 안전할 때 명령(Commands) 화면에서 억제를 해제하세요."
          : recallBlockCodes.length > 0
          ? "회수되지 않은 릴리스 또는 기능 회수 해제가 포함된 카탈로그를 반영하여 회수 전환(recall-rolloff) 계획을 발급받으세요."
          : manualHold
          ? "수동 억제 구간이 만료될 때까지 기다리거나 명령(Commands) 화면에서 해제하세요."
          : "이전 실패 실행 보고서를 검토하세요. 현재 활성화된 억제 보류는 없습니다.",
      }
    : null;

  return {
    nextStep,
    prerequisites,
    timeHorizons,
    recovery,
  };
}
