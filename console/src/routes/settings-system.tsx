import type { OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";
import { useEffect, useRef, useState } from "preact/hooks";
import "./settings-email-template.css";
import {
  AsyncBoundary,
  type AsyncState,
  PageHeader,
  StatusPill,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { routeHref } from "../router";
import { SettingRow } from "./settings";
import {
  decodeEmailTemplatePreview,
  type EmailTemplatePreview,
} from "./settings-email-template.model";
import {
  decodeRuntimeSettings,
  type RuntimeIntegrationView,
  type RuntimeSettingsView,
} from "./settings-runtime.model";

interface Props {
  readonly client: OperatorApiClient;
  readonly auth: AuthContext;
}

export function isCurrentDiagnosticCheck(current: number, candidate: number): boolean {
  return current === candidate;
}

export function SettingsIntegrationsRoute({ client, auth }: Props) {
  const authMode = authenticationMode(auth);
  const runtimeSettings = useRuntimeSettings(client);
  const incidentEmailTemplate = useIncidentEmailTemplate(client);

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
      records: runtimeSettings.status === "ready"
        ? { integrations: runtimeSettings.data.integrations.map((item) => ({ ...item })) }
        : {},
    }),
    [authMode, runtimeSettings],
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
        <AsyncBoundary
          state={runtimeSettings}
          resourceLabel={t("settings.integrationStatusResource")}
        >
          {(runtime) => (
            <div class="settings-list">
              {runtime.integrations.map((integration) => (
                <IntegrationRow key={integration.key} integration={integration} />
              ))}
            </div>
          )}
        </AsyncBoundary>
        <nav class="settings-integration-links" aria-label={t("settings.integrationEvidence")}>
          <a href={routeHref("settings-diagnostics")}>{t("route.settingsDiagnostics")}</a>
          <a href={routeHref("onboarding")}>{t("route.onboarding")}</a>
        </nav>
      </section>
      <section class="settings-section" aria-labelledby="settings-incident-email-template">
        <h3 id="settings-incident-email-template">{t("settings.emailTemplateHeading")}</h3>
        <AsyncBoundary
          state={incidentEmailTemplate}
          resourceLabel={t("settings.emailTemplateResource")}
        >
          {(template) => <EmailTemplatePreviewPanel template={template} />}
        </AsyncBoundary>
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
  const runtimeSettings = useRuntimeSettings(client);

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
        { key: "operator_api_liveness", value: health, group: "runtime" },
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
          <SettingRow label={t("settings.operatorApiLiveness")} hint={t("settings.operatorApiLivenessHint")}>
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
      <section class="settings-section" aria-labelledby="settings-runtime-policy-status">
        <h3 id="settings-runtime-policy-status">{t("settings.runtimePolicyStatus")}</h3>
        <AsyncBoundary
          state={runtimeSettings}
          resourceLabel={t("settings.runtimeStatusResource")}
        >
          {(view) => <RuntimeDiagnosticRows view={view} />}
        </AsyncBoundary>
      </section>
      {healthError ? <div class="error" role="alert">{healthError}</div> : null}
    </div>
  );
}

function useRuntimeSettings(client: OperatorApiClient): AsyncState<RuntimeSettingsView> {
  const [state, setState] = useState<AsyncState<RuntimeSettingsView>>({ status: "loading" });
  useEffect(() => {
    let active = true;
    setState({ status: "loading" });
    void (async () => {
      try {
        const data = decodeRuntimeSettings(await client.panel<unknown>("/runtime/settings"));
        if (active) setState({ status: "ready", data });
      } catch (reason) {
        if (active) {
          setState({
            status: "error",
            message: reason instanceof Error ? reason.message : String(reason),
          });
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [client]);
  return state;
}

function useIncidentEmailTemplate(client: OperatorApiClient): AsyncState<EmailTemplatePreview> {
  const [state, setState] = useState<AsyncState<EmailTemplatePreview>>({ status: "loading" });
  useEffect(() => {
    let active = true;
    setState({ status: "loading" });
    void (async () => {
      try {
        const data = decodeEmailTemplatePreview(
          await client.panel<unknown>("/notification-templates/incident-opened"),
        );
        if (active) setState({ status: "ready", data });
      } catch (reason) {
        if (active) {
          setState({
            status: "error",
            message: reason instanceof Error ? reason.message : String(reason),
          });
        }
      }
    })();
    return () => {
      active = false;
    };
  }, [client]);
  return state;
}

function EmailTemplatePreviewPanel({ template }: { readonly template: EmailTemplatePreview }) {
  return (
    <div class="settings-email-template">
      <div class="settings-email-template-head">
        <span>
          <small>{t("settings.emailTemplateSubject")}</small>
          <strong>{template.subject}</strong>
        </span>
        <StatusPill kind="neutral" label={t("settings.emailTemplateSynthetic")} />
      </div>
      <iframe
        class="settings-email-template-frame"
        title={t("settings.emailTemplatePreviewTitle")}
        srcDoc={template.html}
        sandbox=""
        referrerPolicy="no-referrer"
      />
    </div>
  );
}

function IntegrationRow({ integration }: { readonly integration: RuntimeIntegrationView }) {
  const status = integration.ready
    ? t("settings.statusReady")
    : integration.configured
      ? t("settings.statusIncomplete")
      : t("settings.statusNotConfigured");
  return (
    <SettingRow
      label={t(`settings.integrations.${integration.key}.label`)}
      hint={t(`settings.integrations.${integration.key}.hint`)}
    >
      <span class="settings-integration-status">
        <StatusPill
          kind={integration.ready ? "success" : integration.configured ? "warning" : "neutral"}
          label={status}
        />
        <small class="muted">
          {t("settings.integrationMode", {
            mode: t(`settings.integrationModes.${integration.mode}`),
          })}
        </small>
      </span>
    </SettingRow>
  );
}

function RuntimeDiagnosticRows({ view }: { readonly view: RuntimeSettingsView }) {
  const runtime = view.runtime;
  const rows = [
    ["environment", runtime.environment],
    ["stateStore", runtime.stateStoreDurable],
    ["autonomyDefault", runtime.autonomyDefault],
    ["pantheon", runtime.pantheonEnabled],
    ["workflowObservation", runtime.workflowObservationEnabled],
    ["primaryTransport", runtime.primaryTransportConfigured],
    ["auxiliaryTransport", runtime.auxiliaryTransportConfigured],
    ["caseHistory", runtime.caseHistoryConfigured],
  ] as const;
  return (
    <div class="settings-list">
      {rows.map(([key, value]) => (
        <SettingRow
          key={key}
          label={t(`settings.runtimeDiagnostics.${key}.label`)}
          hint={t(`settings.runtimeDiagnostics.${key}.hint`)}
        >
          {typeof value === "boolean" ? (
            <StatusPill
              kind={value ? "success" : "neutral"}
              label={value ? t("settings.enabled") : t("settings.disabled")}
            />
          ) : (
            <code class="settings-runtime-value">{value}</code>
          )}
        </SettingRow>
      ))}
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
