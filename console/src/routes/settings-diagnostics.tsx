import { useEffect, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";
import { AsyncBoundary, LoadingState, PageHeader, StatusPill } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { t } from "../i18n";
import { routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { SettingRow } from "./settings";
import { useAdministrationRead } from "./settings-administration-read";
import { decodeRuntimeSettings, type RuntimeSettingsView } from "./settings-runtime.model";
import { settingsDiagnosticsText as text } from "./settings-diagnostics.i18n";
import {
  diagnosticBooleanKind, diagnosticSummary, diagnosticSupportSummary,
  observeDiagnostic, type DiagnosticResult,
} from "./settings-diagnostics.model";

export function isCurrentDiagnosticCheck(current: number, candidate: number): boolean {
  return current === candidate;
}

export function isHealthy(value: unknown): boolean {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    && (value as Record<string, unknown>)["status"] === "ok";
}

export function authenticationMode(auth: AuthContext): string {
  if (auth.localAzureCli) return "Azure CLI";
  if (auth.devMode && auth.account) return "Local Entra";
  if (auth.devMode) return "Development";
  return "Microsoft Entra ID";
}

export function SettingsDiagnosticsRoute({ client, auth }: {
  readonly client: OperatorApiClient; readonly auth: AuthContext;
}) {
  const [results, setResults] = useState<readonly (DiagnosticResult | null)[]>([null, null]);
  const [checking, setChecking] = useState<readonly boolean[]>([true, true]);
  const [copyState, setCopyState] = useState<"idle" | "copied" | "error">("idle");
  const generations = useRef([0, 0]);
  const pending = useRef([false, false]);
  const runtime = useAdministrationRead(client, async () =>
    decodeRuntimeSettings(await client.panel<unknown>("/runtime/settings")));
  const check = async (index: number) => {
    if (pending.current[index]) return;
    pending.current[index] = true;
    const generation = (generations.current[index] ?? 0) + 1;
    generations.current[index] = generation;
    setChecking((current) => current.map((value, i) => i === index ? true : value));
    const result = await observeDiagnostic(
      index === 0 ? () => client.panel<unknown>("/healthz") : () => client.dashboardMetrics(),
      index === 0 ? isHealthy : undefined,
    );
    if (generations.current[index] !== generation) return;
    pending.current[index] = false;
    setResults((current) => current.map((value, i) => i === index ? result : value));
    setChecking((current) => current.map((value, i) => i === index ? false : value));
  };
  useEffect(() => {
    pending.current = [false, false];
    setResults([null, null]);
    setChecking([true, true]);
    void check(0);
    void check(1);
    return () => { generations.current = generations.current.map((value) => value + 1); };
  }, [client]);
  const counts = diagnosticSummary(results, checking);
  const summary = text("summary", counts);
  usePublishViewContext(() => ({
    routeId: "settings-diagnostics",
    routeLabel: t("route.settingsDiagnostics"),
    purpose: t("settings.diagnosticsPurpose"),
    headline: summary,
    capturedAt: results.map((result) => result?.checkedAt ?? "").sort().at(-1) || new Date().toISOString(),
    facts: results.map((result, index) => ({
      key: index === 0 ? "operator_api_liveness" : "kpi_read_path",
      value: checking[index] ? "checking" : result?.status ?? "checking",
      group: "runtime",
    })),
    records: { observations: results.flatMap((result, index) => result === null ? [] : [{
      probe: index === 0 ? "operator_api_liveness" : "kpi_read_path", ...result,
    }]) },
  }), [results, checking, summary]);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(diagnosticSupportSummary(
        pending.current[0] ? null : results[0] ?? null,
        pending.current[1] ? null : results[1] ?? null,
        runtime.state.status === "ready" ? runtime.state.data.runtime : null,
        runtime.observedAt, Boolean(runtime.error || runtime.refreshing),
      ));
      setCopyState("copied");
    } catch { setCopyState("error"); }
  };
  const anyPending = checking.some(Boolean) || runtime.refreshing;
  return (
    <div class="stack settings-route">
      <PageHeader title={t("route.settingsDiagnostics")} subtitle={t("settings.diagnosticsSubtitle")} />
      <div class="settings-actions">
        <button type="button" class="secondary" disabled={anyPending} onClick={() => {
          void check(0); void check(1); runtime.refresh(); setCopyState("idle");
        }}>{text("refreshAll")}</button>
        <button type="button" class="secondary" onClick={() => { void copy(); }}>{text("copySummary")}</button>
      </div>
      <p class="muted">{text("copyBoundary")}</p>
      {copyState !== "idle" ? <p role="status">{text(copyState === "copied" ? "copied" : "copyFailed")}</p> : null}
      <p role="status" aria-live="polite">{summary}</p>
      <p class="muted">{text("boundary")}</p>
      <section class="settings-section" aria-labelledby="settings-runtime">
        <h3 id="settings-runtime">{t("settings.runtime")}</h3>
        <div class="settings-list">
          {([0, 1] as const).map((index) => {
            const result = results[index];
            const busy = checking[index] ?? true;
            const label = t(index === 0 ? "settings.operatorApiLiveness" : "settings.readPath");
            return (
              <SettingRow key={index} label={label} hint={t(index === 0 ? "settings.operatorApiLivenessHint" : "settings.readPathHint")}>
                <div class="settings-diagnostic-result" aria-busy={busy}>
                  {result ? (
                    <>
                      <StatusPill kind={result.status === "available" ? "success" : "danger"} label={t(`settings.health.${result.status}`)} />
                      <small>{text("checkedAt", { time: formatConsoleTimestamp(result.checkedAt) })}</small>
                      <small>{text("duration", { duration: result.durationMs })}</small>
                    </>
                  ) : <LoadingState label={`${label}: ${text("checking")}`} />}
                  {busy && result ? <span>{text("checking")}</span> : null}
                  {result?.status === "unavailable" && !busy ? <p class="error">{text("probeError")}</p> : null}
                  <span class="settings-diagnostic-action">
                    <button type="button" class="secondary" disabled={busy} onClick={() => { void check(index); }}>
                      {text(index === 0 ? "retryLiveness" : "retryReadPath")}
                    </button>
                  </span>
                  <a href={routeHref(index === 0 ? "settings-integrations" : "dashboard")}>
                    {text(index === 0 ? "openIntegrations" : "openReadModel")}
                  </a>
                </div>
              </SettingRow>
            );
          })}
          <SettingRow label={t("settings.authentication")} hint={t("settings.authenticationHint")}>
            <code class="settings-runtime-value">{authenticationMode(auth)}</code>
          </SettingRow>
          <SettingRow label={t("settings.principal")} hint={text(auth.devMode || auth.localAzureCli ? "localAuthority" : "productionAuthority")}>
            <span class="stack">
              <code class="settings-runtime-value">{auth.account?.username ?? t("settings.unavailable")}</code>
              <a href={routeHref("settings-iam")}>{text("openIam")}</a>
            </span>
          </SettingRow>
        </div>
      </section>
      <section class="settings-section" aria-labelledby="settings-runtime-policy-status">
        <h3 id="settings-runtime-policy-status">{t("settings.runtimePolicyStatus")}</h3>
        <div class="settings-actions">
          <button type="button" class="secondary" disabled={runtime.refreshing} onClick={runtime.refresh}>{text("refreshPolicy")}</button>
          <a href={routeHref("settings-integrations")}>{text("openIntegrations")}</a>
        </div>
        {runtime.error ? <p role="alert">{text(runtime.state.status === "ready" ? "policyError" : "policyUnavailable")}</p> : null}
        {runtime.refreshing && runtime.state.status === "ready" ? <p role="status">{text("refreshing")}</p> : null}
        {runtime.observedAt ? <small>{text("checkedAt", { time: formatConsoleTimestamp(runtime.observedAt) })}</small> : null}
        {runtime.state.status !== "unavailable" ? (
          <AsyncBoundary state={runtime.state} resourceLabel={t("settings.runtimeStatusResource")}>
            {(view) => <RuntimeDiagnosticRows view={view} />}
          </AsyncBoundary>
        ) : null}
      </section>
    </div>
  );
}

function RuntimeDiagnosticRows({ view }: { readonly view: RuntimeSettingsView }) {
  const runtime = view.runtime;
  const rows = [
    ["environment", runtime.environment], ["stateStore", runtime.stateStoreDurable],
    ["autonomyDefault", runtime.autonomyDefault], ["pantheon", runtime.pantheonEnabled],
    ["workflowObservation", runtime.workflowObservationEnabled],
    ["primaryTransport", runtime.primaryTransportConfigured],
    ["auxiliaryTransport", runtime.auxiliaryTransportConfigured], ["caseHistory", runtime.caseHistoryConfigured],
  ] as const;
  return <div class="settings-list">{rows.map(([key, value]) => (
    <SettingRow key={key} label={t(`settings.runtimeDiagnostics.${key}.label`)} hint={t(`settings.runtimeDiagnostics.${key}.hint`)}>
      {typeof value === "boolean"
        ? <StatusPill kind="neutral" label={text(`${diagnosticBooleanKind(key)}.${value}`)} />
        : <code class="settings-runtime-value">{value}</code>}
    </SettingRow>
  ))}</div>;
}
