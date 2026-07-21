import type { ReadApiClient } from "../api";
import type { AuthContext } from "../auth";
import { useEffect, useRef, useState } from "preact/hooks";
import { PageHeader, StatusPill } from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { routeHref } from "../router";
import { SettingRow } from "./settings";

interface Props {
  readonly client: ReadApiClient;
  readonly auth: AuthContext;
}

export function isCurrentDiagnosticCheck(current: number, candidate: number): boolean {
  return current === candidate;
}

export function SettingsIntegrationsRoute({ auth }: Props) {
  const authMode = authenticationMode(auth);

  usePublishViewContext(
    () => ({
      routeId: "settings-integrations",
      routeLabel: t("route.settingsIntegrations"),
      purpose: t("settings.integrationsPurpose"),
      glossary: composeGlossary([TERMS.humanRbac]),
      headline: t("settings.authenticationHeadline", { mode: authMode }),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "authentication_mode", value: authMode, group: "identity" },
        { key: "github_app_status", value: "not-probed", group: "delivery" },
        { key: "teams_status", value: "not-probed", group: "delivery" },
      ],
      records: {},
    }),
    [authMode],
  );

  return (
    <div class="stack settings-route">
      <PageHeader
        title={t("route.settingsIntegrations")}
        subtitle={t("settings.integrationsSubtitle")}
      />
      <section class="settings-section" aria-labelledby="settings-identity-integration">
        <h3 id="settings-identity-integration">{t("settings.identity")}</h3>
        <div class="settings-list">
          <SettingRow label={t("settings.entra")} hint={t("settings.entraHint")}>
            <StatusPill kind="neutral" label={authMode} />
          </SettingRow>
        </div>
      </section>
      <section class="settings-section" aria-labelledby="settings-delivery-integrations">
        <h3 id="settings-delivery-integrations">{t("settings.delivery")}</h3>
        <p class="muted small">{t("settings.integrationProbeUnavailable")}</p>
        <div class="settings-list">
          <SettingRow label={t("settings.githubApp")} hint={t("settings.githubAppHint")}>
            <StatusPill kind="neutral" label={t("settings.statusNotProbed")} />
          </SettingRow>
          <SettingRow label={t("settings.teams")} hint={t("settings.teamsHint")}>
            <StatusPill kind="neutral" label={t("settings.statusNotProbed")} />
          </SettingRow>
        </div>
        <nav class="settings-integration-links" aria-label={t("settings.integrationEvidence")}>
          <a href={routeHref("settings-diagnostics")}>{t("route.settingsDiagnostics")}</a>
          <a href={routeHref("onboarding")}>{t("route.onboarding")}</a>
        </nav>
      </section>
    </div>
  );
}

export function SettingsDiagnosticsRoute({ client, auth }: Props) {
  const authMode = authenticationMode(auth);
  const [health, setHealth] = useState<"checking" | "available" | "unavailable">("checking");
  const [readPath, setReadPath] = useState<"checking" | "available" | "unavailable">("checking");
  const [healthError, setHealthError] = useState<string | null>(null);
  const checkGeneration = useRef(0);

  const checkHealth = async () => {
    const generation = ++checkGeneration.current;
    setHealth("checking");
    setReadPath("checking");
    setHealthError(null);
    const [liveness, kpiRead] = await Promise.allSettled([
      client.panel<unknown>("/healthz"),
      client.dashboardMetrics(),
    ]);
    if (!isCurrentDiagnosticCheck(checkGeneration.current, generation)) return;
    const errors: string[] = [];
    if (liveness.status === "fulfilled" && isHealthy(liveness.value)) {
      setHealth("available");
    } else {
      setHealth("unavailable");
      errors.push(liveness.status === "rejected"
        ? liveness.reason instanceof Error ? liveness.reason.message : String(liveness.reason)
        : t("settings.invalidLivenessResponse"));
    }
    if (kpiRead.status === "fulfilled") {
      setReadPath("available");
    } else {
      setReadPath("unavailable");
      errors.push(kpiRead.reason instanceof Error ? kpiRead.reason.message : String(kpiRead.reason));
    }
    setHealthError(errors.length > 0 ? errors.join("; ") : null);
  };

  useEffect(() => {
    void checkHealth();
    return () => {
      checkGeneration.current += 1;
    };
  }, [client]);

  usePublishViewContext(
    () => ({
      routeId: "settings-diagnostics",
      routeLabel: t("route.settingsDiagnostics"),
      purpose: t("settings.diagnosticsPurpose"),
      glossary: composeGlossary([TERMS.humanRbac]),
      headline: t("settings.diagnosticsHeadline", {
        health,
        readPath,
        mode: authMode,
      }),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "read_api_liveness", value: health, group: "runtime" },
        { key: "kpi_read_path", value: readPath, group: "runtime" },
        { key: "authentication_mode", value: authMode, group: "identity" },
      ],
      records: {},
    }),
    [authMode, health, readPath],
  );

  return (
    <div class="stack settings-route">
      <PageHeader
        title={t("route.settingsDiagnostics")}
        subtitle={t("settings.diagnosticsSubtitle")}
      />
      <section class="settings-section" aria-labelledby="settings-runtime">
        <h3 id="settings-runtime">{t("settings.runtime")}</h3>
        <div class="settings-list">
          <SettingRow label={t("settings.readApiLiveness")} hint={t("settings.readApiLivenessHint")}>
            <span class="settings-diagnostic-action">
              <StatusPill
                kind={health === "available" ? "success" : health === "unavailable" ? "danger" : "neutral"}
                label={t(`settings.health.${health}`)}
              />
              <button type="button" disabled={health === "checking"} onClick={() => { void checkHealth(); }}>
                {t("settings.retry")}
              </button>
            </span>
          </SettingRow>
          <SettingRow label={t("settings.readPath")} hint={t("settings.readPathHint")}>
            <StatusPill
              kind={readPath === "available" ? "success" : readPath === "unavailable" ? "danger" : "neutral"}
              label={t(`settings.health.${readPath}`)}
            />
          </SettingRow>
          <SettingRow label={t("settings.authentication")} hint={t("settings.authenticationHint")}>
            <code class="settings-runtime-value">{authMode}</code>
          </SettingRow>
          <SettingRow label={t("settings.principal")} hint={t("settings.principalHint")}>
            <code class="settings-runtime-value">{auth.account?.username ?? t("settings.unavailable")}</code>
          </SettingRow>
        </div>
      </section>
      {healthError ? <div class="error" role="alert">{healthError}</div> : null}
    </div>
  );
}

export function isHealthy(value: unknown): boolean {
  return typeof value === "object"
    && value !== null
    && !Array.isArray(value)
    && (value as Record<string, unknown>)["status"] === "ok";
}

export function authenticationMode(auth: AuthContext): string {
  if (auth.localAzureCli) return "Azure CLI";
  if (auth.devMode && auth.account) return "Local Entra";
  if (auth.devMode) return "Development";
  return "Microsoft Entra ID";
}
