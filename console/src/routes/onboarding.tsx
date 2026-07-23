import { useEffect, useRef, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { AsyncBoundary, KpiCard, KpiGrid, PageHeader, StatusPill, type AsyncState } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { panelArray, panelBoolean, panelNumber, panelRecord, panelString, panelStringArray } from "./panel-decode";

interface OnboardingResponse {
  readonly probe_mode: "configured" | "not-configured";
  readonly ready: boolean;
  readonly blocked: boolean;
  readonly missing_resources: readonly string[];
  readonly missing_role_assignments: readonly (readonly string[])[];
  readonly present_resource_count: number;
  readonly present_role_count: number;
  readonly error: string | null;
}

export function OnboardingRoute({ client }: { readonly client: ReadApiClient }) {
  const [state, setState] = useState<AsyncState<OnboardingResponse>>({ status: "loading" });
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);
  const generation = useRef(0);
  const load = async (showLoading: boolean): Promise<void> => {
    const request = ++generation.current;
    if (showLoading) setState({ status: "loading" });
    else setRefreshing(true);
    try {
      const data = decodeOnboarding(await client.panel<unknown>("/onboarding"));
      if (request !== generation.current) return;
      setState({ status: "ready", data });
      setCheckedAt(new Date().toISOString());
    } catch (error) {
      if (request !== generation.current) return;
      setState({ status: "error", message: error instanceof Error ? error.message : String(error) });
    } finally {
      if (request === generation.current) setRefreshing(false);
    }
  };
  useEffect(() => {
    void load(true);
    return () => { generation.current += 1; };
  }, [client]);
  return (
    <div class="stack onboarding-route">
      <PageHeader
        title={t("route.onboarding")}
        subtitle={t("nav.panelSub.onboarding")}
        actions={
          <button
            type="button"
            disabled={state.status === "loading" || refreshing}
            aria-busy={refreshing}
            onClick={() => { void load(false); }}
          >
            {refreshing ? t("onboardingView.refreshing") : t("onboardingView.refresh")}
          </button>
        }
      />
      <AsyncBoundary state={state} resourceLabel={t("onboardingView.resourceLabel")}>
        {(data) => <OnboardingBody data={data} checkedAt={checkedAt} />}
      </AsyncBoundary>
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
    if (assignment.length !== 3) {
      throw new Error(`onboarding.missing_role_assignments[${index}] MUST contain principal, role, and target`);
    }
    return assignment;
  });
  const ready = panelBoolean(root, "ready", "onboarding");
  const blocked = panelBoolean(root, "blocked", "onboarding");
  const presentResourceCount = nonNegativeInteger(root, "present_resource_count");
  const presentRoleCount = nonNegativeInteger(root, "present_role_count");
  if (ready && blocked) throw new Error("onboarding.ready and onboarding.blocked MUST NOT both be true");
  if (probeMode === "configured" && error == null && ready === blocked) {
    throw new Error("configured onboarding readiness MUST be either ready or blocked");
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

function OnboardingBody({ data, checkedAt }: { readonly data: OnboardingResponse; readonly checkedAt: string | null }) {
  const observed = data.probe_mode === "configured" && data.error === null;
  usePublishViewContext(
    () => ({
      routeId: "onboarding",
      routeLabel: t("route.onboarding"),
      purpose: t("onboardingView.viewPurpose"),
      glossary: composeGlossary([TERMS.humanRbac]),
      headline: !observed
        ? t("onboardingView.headlineUnavailable")
        : data.ready
        ? t("onboardingView.headlineReady")
        : t("onboardingView.headlineBlocked", {
            resources: data.missing_resources.length,
            roles: data.missing_role_assignments.length,
          }),
      capturedAt: checkedAt ?? new Date().toISOString(),
      facts: [
        { key: "probe_mode", value: data.probe_mode, group: "readiness" },
        { key: "ready", value: observed ? data.ready : null, group: "readiness" },
        { key: "resources_observed", value: observed ? data.present_resource_count : null, group: "readiness" },
        { key: "roles_observed", value: observed ? data.present_role_count : null, group: "readiness" },
        { key: "probe_error", value: data.error, group: "readiness" },
      ],
      records: {
        [observed ? "missing_resources" : "required_resources"]:
          data.missing_resources.map((resource) => ({ resource })),
        [observed ? "missing_role_assignments" : "required_role_assignments"]:
          data.missing_role_assignments.map(([principal, role, target]) => ({ principal, role, target })),
      },
    }),
    [checkedAt, data],
  );
  return (
    <div class="stack">
      {data.probe_mode === "not-configured" ? (
        <div class="state-block state-unavailable" role="status">
          <span class="state-icon" aria-hidden="true">?</span>
          <span>{t("onboardingView.notConfigured")}</span>
        </div>
      ) : null}
      {data.error !== null ? (
        <div class="state-block state-unavailable" role="alert">
          <span class="state-icon" aria-hidden="true">!</span>
          <span>{t("onboardingView.probeFailed")} {data.error}</span>
        </div>
      ) : null}
      <KpiGrid>
        <KpiCard href={routeHref("provision")} label={t("onboardingView.readiness")} value={observed ? <StatusPill kind={data.ready ? "success" : "danger"} label={t(data.ready ? "onboardingView.ready" : "onboardingView.blocked")} /> : "-"} />
        <KpiCard href={routeHref("architecture")} label={t("onboardingView.resourcesObserved")} value={observed ? data.present_resource_count.toLocaleString() : "-"} />
        <KpiCard href={routeHref("settings-iam", { segments: ["requests"] })} label={t("onboardingView.rolesObserved")} value={observed ? data.present_role_count.toLocaleString() : "-"} />
        <KpiCard href={routeHref("provision")} label={t("onboardingView.lastChecked")} value={formatConsoleTimestamp(checkedAt)} />
      </KpiGrid>
      <nav class="onboarding-actions" aria-label={t("onboardingView.drilldowns") }>
        <a href={routeHref("provision")}>{t("onboardingView.openProvisioning")}</a>
        <a href={routeHref("settings-iam", { segments: ["requests"] })}>{t("onboardingView.reviewAccess")}</a>
        <a href={routeHref("architecture")}>{t("onboardingView.inspectArchitecture")}</a>
      </nav>
      <section class="stack-section">
        <h3 class="section-title">{t(observed ? "onboardingView.missingResources" : "onboardingView.requiredResources")} ({data.missing_resources.length})</h3>
        {data.missing_resources.length ? (
          <ul class="onboarding-gap-list">
            {data.missing_resources.map((resource) => <li key={resource}><code>{resource}</code></li>)}
          </ul>
        ) : <p class="muted">{t("onboardingView.none")}</p>}
      </section>
      <section class="stack-section">
        <h3 class="section-title">{t(observed ? "onboardingView.missingRoles" : "onboardingView.requiredRoles")} ({data.missing_role_assignments.length})</h3>
        {data.missing_role_assignments.length ? (
          <ul class="onboarding-role-list">
            {data.missing_role_assignments.map(([principal, role, target]) => (
              <li key={`${principal}:${role}:${target}`}>
                <code>{principal}</code><span>{role}</span><code>{target}</code>
              </li>
            ))}
          </ul>
        ) : <p class="muted">{t("onboardingView.none")}</p>}
      </section>
    </div>
  );
}
