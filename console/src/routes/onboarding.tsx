import { useEffect, useRef, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import { AsyncBoundary, ErrorState, PageHeader, type AsyncState } from "../components/ui";
import type { ConsoleDataMode } from "../console-data-mode";
import { t } from "../i18n";
import { OnboardingBody, OnboardingLoadingState } from "./onboarding.presentation";
import { panelArray, panelBoolean, panelNumber, panelRecord, panelString, panelStringArray } from "./panel-decode";

export interface OnboardingResponse {
  readonly probe_mode: "configured" | "not-configured";
  readonly ready: boolean;
  readonly blocked: boolean;
  readonly missing_resources: readonly string[];
  readonly missing_role_assignments: readonly (readonly [string, string, string])[];
  readonly present_resource_count: number;
  readonly present_role_count: number;
  readonly error: string | null;
}

export async function loadOnboardingState(
  client: Pick<OperatorApiClient, "panel">,
): Promise<AsyncState<OnboardingResponse>> {
  try {
    return {
      status: "ready",
      data: decodeOnboarding(await client.panel<unknown>("/onboarding")),
    };
  } catch (error) {
    return isOptionalOperatorApiUnavailable(error)
      ? { status: "unavailable", message: t("onboardingView.notConfigured") }
      : { status: "error", message: error instanceof Error ? error.message : String(error) };
  }
}

export function OnboardingRoute({
  client,
  dataMode,
  embedded = false,
}: {
  readonly client: OperatorApiClient;
  readonly dataMode: ConsoleDataMode;
  readonly embedded?: boolean;
}) {
  const [state, setState] = useState<AsyncState<OnboardingResponse>>({ status: "loading" });
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const generation = useRef(0);
  const load = async (showLoading: boolean): Promise<void> => {
    const request = ++generation.current;
    if (showLoading) setState({ status: "loading" });
    else setRefreshing(true);
    try {
      const nextState = await loadOnboardingState(client);
      if (request !== generation.current) return;
      setState(nextState);
      if (nextState.status === "ready") setCheckedAt(new Date().toISOString());
    } finally {
      if (request === generation.current) setRefreshing(false);
    }
  };
  useEffect(() => {
    void load(true);
    return () => { generation.current += 1; };
  }, [client]);
  const refreshAction = (
    <button
      type="button"
      class="btn secondary"
      disabled={state.status === "loading" || refreshing}
      aria-busy={refreshing}
      onClick={() => { void load(false); }}
    >
      {refreshing ? t("onboardingView.refreshing") : t("onboardingView.refresh")}
    </button>
  );
  return (
    <div class="stack onboarding-route">
      {embedded ? (
        <header class="environment-deployment-section-header">
          <div>
            <h2>{t("onboardingView.title")}</h2>
            <p>{t("onboardingView.viewPurpose")}</p>
          </div>
          {refreshAction}
        </header>
      ) : (
        <PageHeader
          title={t("onboardingView.title")}
          subtitle={t("onboardingView.viewPurpose")}
          actions={refreshAction}
        />
      )}
      {state.status === "error" ? (
        <ErrorState
          message={t("shared.loadFailed", {
            resource: t("onboardingView.resourceLabel"),
            message: state.message,
          })}
          onRetry={() => { void load(true); }}
          retryLabel={t("onboardingView.retry")}
        />
      ) : (
        <AsyncBoundary
          state={state}
          resourceLabel={t("onboardingView.resourceLabel")}
          loading={<OnboardingLoadingState />}
        >
          {(data) => <OnboardingBody data={data} checkedAt={checkedAt} dataMode={dataMode} />}
        </AsyncBoundary>
      )}
    </div>
  );
}

export function decodeOnboarding(value: unknown): OnboardingResponse {
  const root = panelRecord(value, "onboarding");
  const probeMode = panelString(root, "probe_mode", "onboarding");
  if (probeMode !== "configured" && probeMode !== "not-configured") {
    throw new Error("onboarding.probe_mode MUST be configured or not-configured");
  }
  const error = root["error"];
  if (error !== undefined && error !== null && typeof error !== "string") {
    throw new Error("onboarding.error MUST be a string or null");
  }
  const missingResources = panelStringArray(root["missing_resources"], "onboarding.missing_resources");
  const missingRoleAssignments = panelArray(root["missing_role_assignments"], "onboarding.missing_role_assignments").map((item, index) => {
    const assignment = panelStringArray(item, `onboarding.missing_role_assignments[${index}]`);
    const [principal, role, target, ...extra] = assignment;
    if (principal === undefined || role === undefined || target === undefined || extra.length > 0) {
      throw new Error(`onboarding.missing_role_assignments[${index}] MUST contain principal, role, and target`);
    }
    return [principal, role, target] as const;
  });
  const ready = panelBoolean(root, "ready", "onboarding");
  const blocked = panelBoolean(root, "blocked", "onboarding");
  const presentResourceCount = nonNegativeInteger(root, "present_resource_count");
  const presentRoleCount = nonNegativeInteger(root, "present_role_count");
  if (ready && blocked) throw new Error("onboarding.ready and onboarding.blocked MUST NOT both be true");
  if (probeMode === "configured" && error == null && ready === blocked) {
    throw new Error("configured onboarding readiness MUST be either ready or blocked");
  }
  const gapCount = missingResources.length + missingRoleAssignments.length;
  if (probeMode === "configured" && error == null && ready !== (gapCount === 0)) {
    throw new Error("configured onboarding readiness MUST agree with the reported gaps");
  }
  return {
    probe_mode: probeMode,
    ready,
    blocked,
    missing_resources: missingResources,
    missing_role_assignments: missingRoleAssignments,
    present_resource_count: presentResourceCount,
    present_role_count: presentRoleCount,
    error: typeof error === "string" ? error : null,
  };
}

function nonNegativeInteger(root: Readonly<Record<string, unknown>>, key: string): number {
  const value = panelNumber(root, key, "onboarding");
  if (!Number.isInteger(value) || value < 0) {
    throw new Error(`onboarding.${key} MUST be a non-negative integer`);
  }
  return value;
}
