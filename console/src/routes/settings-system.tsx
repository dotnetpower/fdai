import type preact from "preact";
import type { OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";
import { useEffect, useRef, useState } from "preact/hooks";
import "./settings-email-template.css";
import "./settings-webhook-diagnostic.css";
import {
  AsyncBoundary,
  CopyButton,
  ExternalLink,
  type AsyncState,
  PageHeader,
  StatusPill,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { routeHref } from "../router";
import { SettingRow } from "./settings";
import { settingsIntegrationsText } from "./settings-integrations.i18n";
import {
  decodeEmailTemplatePreview,
  type EmailTemplatePreview,
} from "./settings-email-template.model";
import {
  decodeRuntimeSettings,
  type RuntimeIntegrationView,
  type RuntimeSettingsView,
} from "./settings-runtime.model";
import { testSlackWebhook } from "./settings-slack-webhook.command";
import {
  newSlackWebhookTestRequestId,
  type SlackWebhookTestResult,
} from "./settings-slack-webhook.model";
import {
  loadTeamsWorkflowBinding,
  testTeamsWorkflowWebhook,
} from "./settings-teams-workflow.command";
import {
  newTeamsWorkflowTestRequestId,
  type TeamsWorkflowSavedBinding,
  type TeamsWorkflowTestResult,
} from "./settings-teams-workflow.model";
import { DocumentOcrSettingsPanel } from "./document-ocr-settings";

/**
 * A1 approvals, A2/A4 notifications, and A3 conversations use separate
 * transports and separate trust. Grouping them here keeps an operator from
 * reading a healthy notification binding as a working approval path.
 */
const APPROVAL_INTEGRATION_KEYS: ReadonlySet<string> = new Set([
  "teams-a1-approval-send",
  "teams-a1-approval-callback",
]);
const NOTIFICATION_INTEGRATION_KEYS: ReadonlySet<string> = new Set([
  "teams-a2-operational-alert",
  "teams-a4-digest",
  "notification-bindings",
  "email",
]);
const CONVERSATION_INTEGRATION_KEYS: ReadonlySet<string> = new Set(["teams-a3-conversation"]);

interface Props {
  readonly client: OperatorApiClient;
  readonly auth: AuthContext;
}

const TEAMS_WORKFLOW_SETUP_URL = "https://make.powerautomate.com/";
const TEAMS_WORKFLOW_ACCOUNT_HINT = normalizeTeamsWorkflowAccountHint(
  import.meta.env.VITE_TEAMS_WORKFLOW_ACCOUNT_HINT,
);

function isEmailStyleUserPrincipalName(value: string): boolean {
  return (
    value.length > 0
    && value.length <= 254
    && !value.includes(" ")
    && value.split("@").length === 2
    && !value.startsWith("@")
    && !value.endsWith("@")
  );
}

export function normalizeTeamsWorkflowAccountHint(value: unknown): string {
  if (value === undefined) return "";
  if (typeof value !== "string") {
    throw new Error("VITE_TEAMS_WORKFLOW_ACCOUNT_HINT must be a string.");
  }
  const normalized = value.trim();
  if (normalized && !isEmailStyleUserPrincipalName(normalized)) {
    throw new Error(
      "VITE_TEAMS_WORKFLOW_ACCOUNT_HINT must be an email-style user principal name.",
    );
  }
  return normalized;
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
            <div class="stack">
              <IntegrationGroup
                headingId="settings-a1-approvals"
                title={settingsIntegrationsText("groupApprovals")}
                description={settingsIntegrationsText("groupApprovalsHint")}
                integrations={runtime.integrations.filter((integration) =>
                  APPROVAL_INTEGRATION_KEYS.has(integration.key)
                )}
              />
              <IntegrationGroup
                headingId="settings-a2-a4-notifications"
                title={settingsIntegrationsText("groupNotifications")}
                description={settingsIntegrationsText("groupNotificationsHint")}
                integrations={runtime.integrations.filter((integration) =>
                  NOTIFICATION_INTEGRATION_KEYS.has(integration.key)
                )}
              >
                <TeamsWorkflowTestPanel
                  auth={auth}
                  operatorApiBaseUrl={client.operatorApiBaseUrl}
                  canManage={runtime.canManage}
                />
                <SlackWebhookTestPanel
                  auth={auth}
                  operatorApiBaseUrl={client.operatorApiBaseUrl}
                  canManage={runtime.canManage}
                />
              </IntegrationGroup>
              <IntegrationGroup
                headingId="settings-a3-conversations"
                title={settingsIntegrationsText("groupConversations")}
                description={settingsIntegrationsText("groupConversationsHint")}
                integrations={runtime.integrations.filter((integration) =>
                  CONVERSATION_INTEGRATION_KEYS.has(integration.key)
                )}
              />
              <IntegrationGroup
                headingId="settings-other-integrations"
                title={settingsIntegrationsText("groupOther")}
                description={settingsIntegrationsText("groupOtherHint")}
                integrations={runtime.integrations.filter(
                  (integration) =>
                    !APPROVAL_INTEGRATION_KEYS.has(integration.key)
                    && !NOTIFICATION_INTEGRATION_KEYS.has(integration.key)
                    && !CONVERSATION_INTEGRATION_KEYS.has(integration.key)
                )}
              />
            </div>
          )}
        </AsyncBoundary>
        <nav class="settings-integration-links" aria-label={t("settings.integrationEvidence")}>
          <a href={routeHref("settings-diagnostics")}>{t("route.settingsDiagnostics")}</a>
          <a href={routeHref("onboarding")}>{t("route.onboarding")}</a>
        </nav>
      </section>
      <DocumentOcrSettingsPanel client={client} auth={auth} />
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

function TeamsWorkflowTestPanel({
  auth,
  operatorApiBaseUrl,
  canManage,
}: {
  readonly auth: AuthContext;
  readonly operatorApiBaseUrl: string;
  readonly canManage: boolean;
}) {
  const [webhookUrl, setWebhookUrl] = useState("");
  const [accountHint, setAccountHint] = useState(TEAMS_WORKFLOW_ACCOUNT_HINT);
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [bindingError, setBindingError] = useState<string | null>(null);
  const [bindingVisibility, setBindingVisibility] = useState<
    "loading" | "hidden" | "visible" | "missing"
  >("loading");
  const [bindingSaved, setBindingSaved] = useState<TeamsWorkflowSavedBinding | null>(null);
  const [result, setResult] = useState<TeamsWorkflowTestResult | null>(null);
  const accountIsValid = !accountHint.trim() || isEmailStyleUserPrincipalName(accountHint.trim());

  useEffect(() => {
    let active = true;
    void (async () => {
      try {
        const binding = await loadTeamsWorkflowBinding(auth, operatorApiBaseUrl);
        if (!active) return;
        if (!binding.visible) {
          setBindingVisibility("hidden");
          return;
        }
        if (!binding.configured) {
          setBindingVisibility("missing");
          return;
        }
        // The saved URL is password-equivalent and is never returned, so the
        // field stays empty and an Owner replaces the binding by submitting a
        // new URL.
        setBindingSaved({
          bindingVersion: binding.bindingVersion,
          savedAt: binding.savedAt,
          observedAt: binding.observedAt,
        });
        setBindingVisibility("visible");
      } catch (reason) {
        if (!active) return;
        setBindingError(reason instanceof Error ? reason.message : String(reason));
        setBindingVisibility("missing");
      }
    })();
    return () => {
      active = false;
    };
  }, [auth, operatorApiBaseUrl]);

  const submit = async (event: SubmitEvent) => {
    event.preventDefault();
    if (!canManage || testing || !webhookUrl.trim()) return;
    const submittedUrl = webhookUrl.trim();
    setWebhookUrl("");
    setTesting(true);
    setError(null);
    setResult(null);
    try {
      const saved = await testTeamsWorkflowWebhook(
        auth,
        operatorApiBaseUrl,
        submittedUrl,
        newTeamsWorkflowTestRequestId(),
      );
      setResult(saved);
      setBindingSaved({
        bindingVersion: saved.bindingVersion,
        savedAt: saved.savedAt,
        observedAt: saved.testedAt,
      });
      setBindingVisibility("visible");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setTesting(false);
    }
  };

  return (
    <div class="settings-webhook-diagnostic settings-teams-workflow-setup">
      <div class="settings-webhook-diagnostic-copy">
        <h4>{t("settings.teamsWorkflowTest.heading")}</h4>
        <p>{t("settings.teamsWorkflowTest.description")}</p>
        <p>{settingsIntegrationsText("saveBoundary")}</p>
      </div>
      <ol class="settings-teams-workflow-steps">
        <li>
          <span class="settings-teams-workflow-step-index" aria-hidden="true">1</span>
          <div class="settings-teams-workflow-step">
            <strong>{t("settings.teamsWorkflowTest.accountStep")}</strong>
            <p>{settingsIntegrationsText("accountStepHint")}</p>
            <div class="settings-teams-workflow-identities">
              <span>
                <small>{t("settings.teamsWorkflowTest.fdaiAccount")}</small>
                <code>{auth.account?.username ?? t("settings.teamsWorkflowTest.accountUnavailable")}</code>
              </span>
              <label>
                <small>{settingsIntegrationsText("m365Account")}</small>
                <span class="settings-teams-workflow-account-control">
                  <input
                    class="form-input"
                    type="email"
                    autocomplete="username"
                    maxlength={254}
                    aria-invalid={!accountIsValid ? "true" : undefined}
                    aria-describedby="teams-workflow-account-note"
                    value={canManage ? accountHint : ""}
                    disabled={!canManage}
                    placeholder={canManage
                      ? t("settings.teamsWorkflowTest.accountPlaceholder")
                      : t("settings.teamsWorkflowTest.ownerOnly")}
                    onInput={(event) => setAccountHint(event.currentTarget.value)}
                  />
                  {canManage && accountHint.trim() ? (
                    <CopyButton
                      text={accountHint.trim()}
                      label={t("settings.teamsWorkflowTest.copyAccount")}
                    />
                  ) : null}
                </span>
                {canManage ? (
                  <small id="teams-workflow-account-note">
                    {!accountIsValid
                      ? settingsIntegrationsText("accountInvalid")
                      : settingsIntegrationsText("accountUsageHint")}
                  </small>
                ) : null}
              </label>
            </div>
          </div>
        </li>
        <li>
          <span class="settings-teams-workflow-step-index" aria-hidden="true">2</span>
          <div class="settings-teams-workflow-step">
            <strong>
              {canManage ? (
                <ExternalLink href={TEAMS_WORKFLOW_SETUP_URL}>
                  {settingsIntegrationsText("workflowStep")}
                </ExternalLink>
              ) : settingsIntegrationsText("workflowStep")}
            </strong>
            <p>{settingsIntegrationsText("workflowStepHint")}</p>
            <details class="settings-teams-workflow-guide">
              <summary>{settingsIntegrationsText("guideSummary")}</summary>
              <div class="settings-teams-workflow-guide-body">
                <p>{settingsIntegrationsText("guideIntro")}</p>
                <ol class="settings-teams-workflow-guide-steps">
                  <li>
                    <strong>{settingsIntegrationsText("guideVerifyAccountTitle")}</strong>
                    <p>
                      {settingsIntegrationsText("guideVerifyAccountBody")}{" "}
                      <code>
                        {canManage && accountHint.trim()
                          ? accountHint.trim()
                          : t("settings.teamsWorkflowTest.accountUnavailable")}
                      </code>
                    </p>
                  </li>
                  <li>
                    <strong>{settingsIntegrationsText("guideCreateTitle")}</strong>
                    <p>{settingsIntegrationsText("guideCreateBody")}</p>
                    <figure>
                      <img
                        src="/guides/power-automate/create-automated-cloud-flow.png"
                        width="671"
                        height="317"
                        loading="lazy"
                        decoding="async"
                        alt={settingsIntegrationsText("guideCreateImageAlt")}
                      />
                      <figcaption>
                        {settingsIntegrationsText("guideCreateImageCaption")}
                      </figcaption>
                    </figure>
                  </li>
                  <li>
                    <strong>{settingsIntegrationsText("guideNameFlowTitle")}</strong>
                    <p>{settingsIntegrationsText("guideNameFlowBody")}</p>
                    <figure>
                      <img
                        src="/guides/power-automate/name-flow-and-skip.png"
                        width="897"
                        height="565"
                        loading="lazy"
                        decoding="async"
                        alt={settingsIntegrationsText("guideNameFlowImageAlt")}
                      />
                      <figcaption>
                        {settingsIntegrationsText("guideNameFlowImageCaption")}
                      </figcaption>
                    </figure>
                  </li>
                  <li>
                    <strong>{settingsIntegrationsText("guideAddTriggerTitle")}</strong>
                    <p>{settingsIntegrationsText("guideAddTriggerBody")}</p>
                    <figure>
                      <img
                        src="/guides/power-automate/add-trigger.png"
                        width="312"
                        height="114"
                        loading="lazy"
                        decoding="async"
                        alt={settingsIntegrationsText("guideAddTriggerImageAlt")}
                      />
                      <figcaption>
                        {settingsIntegrationsText("guideAddTriggerImageCaption")}
                      </figcaption>
                    </figure>
                  </li>
                  <li>
                    <strong>{settingsIntegrationsText("guideSelectTriggerTitle")}</strong>
                    <p>{settingsIntegrationsText("guideSelectTriggerBody")}</p>
                    <figure>
                      <img
                        src="/guides/power-automate/select-teams-webhook-trigger.png"
                        width="423"
                        height="135"
                        loading="lazy"
                        decoding="async"
                        alt={settingsIntegrationsText("guideSelectTriggerImageAlt")}
                      />
                      <figcaption>
                        {settingsIntegrationsText("guideSelectTriggerImageCaption")}
                      </figcaption>
                    </figure>
                  </li>
                  <li>
                    <strong>{settingsIntegrationsText("guideConfigureTriggerTitle")}</strong>
                    <p>{settingsIntegrationsText("guideConfigureTriggerBody")}</p>
                    <figure>
                      <img
                        src="/guides/power-automate/configure-teams-webhook-trigger.png"
                        width="626"
                        height="267"
                        loading="lazy"
                        decoding="async"
                        alt={settingsIntegrationsText("guideConfigureTriggerImageAlt")}
                      />
                      <figcaption>
                        {settingsIntegrationsText("guideConfigureTriggerImageCaption")}
                      </figcaption>
                    </figure>
                  </li>
                  <li>
                    <strong>{settingsIntegrationsText("guideAddActionTitle")}</strong>
                    <p>{settingsIntegrationsText("guideAddActionBody")}</p>
                    <figure>
                      <img
                        src="/guides/power-automate/add-teams-action.png"
                        width="265"
                        height="147"
                        loading="lazy"
                        decoding="async"
                        alt={settingsIntegrationsText("guideAddActionImageAlt")}
                      />
                      <figcaption>
                        {settingsIntegrationsText("guideAddActionImageCaption")}
                      </figcaption>
                    </figure>
                  </li>
                  <li>
                    <strong>{settingsIntegrationsText("guideConfigureActionTitle")}</strong>
                    <p>{settingsIntegrationsText("guideConfigureActionBody")}</p>
                    <figure>
                      <img
                        src="/guides/power-automate/configure-post-card-action.png"
                        width="623"
                        height="572"
                        loading="lazy"
                        decoding="async"
                        alt={settingsIntegrationsText("guideConfigureActionImageAlt")}
                      />
                      <figcaption>
                        {settingsIntegrationsText("guideConfigureActionImageCaption")}
                      </figcaption>
                    </figure>
                  </li>
                  <li>
                    <strong>{settingsIntegrationsText("guideFinishTitle")}</strong>
                    <p>{settingsIntegrationsText("guideFinishBody")}</p>
                    <figure>
                      <img
                        src="/guides/power-automate/save-flow.png"
                        width="463"
                        height="92"
                        loading="lazy"
                        decoding="async"
                        alt={settingsIntegrationsText("guideFinishImageAlt")}
                      />
                      <figcaption>
                        {settingsIntegrationsText("guideFinishImageCaption")}
                      </figcaption>
                    </figure>
                  </li>
                  <li>
                    <strong>{settingsIntegrationsText("guideCopyUrlTitle")}</strong>
                    <p>{settingsIntegrationsText("guideCopyUrlBody")}</p>
                    <figure>
                      <img
                        src="/guides/power-automate/confirm-flow-and-copy-http-url.png"
                        width="672"
                        height="360"
                        loading="lazy"
                        decoding="async"
                        alt={settingsIntegrationsText("guideCopyUrlImageAlt")}
                      />
                      <figcaption>
                        {settingsIntegrationsText("guideCopyUrlImageCaption")}
                      </figcaption>
                    </figure>
                  </li>
                </ol>
                <p class="settings-teams-workflow-guide-note">
                  {settingsIntegrationsText("guideSecretNote")}
                </p>
              </div>
            </details>
          </div>
        </li>
        <li>
          <span class="settings-teams-workflow-step-index" aria-hidden="true">3</span>
          <div class="settings-teams-workflow-step">
            <strong>{settingsIntegrationsText("saveTestStep")}</strong>
            <p>{settingsIntegrationsText("saveTestStepHint")}</p>
            {canManage || bindingVisibility === "visible" ? (
              <form
                class="settings-webhook-diagnostic-form"
                onSubmit={(event) => { void submit(event); }}
              >
                <label class="settings-webhook-diagnostic-field">
                <span>{settingsIntegrationsText("saveUrlLabel")}</span>
                <input
                  class="form-input"
                  type="text"
                  inputMode="url"
                  autocomplete="off"
                  data-1p-ignore
                  data-bwignore
                  data-lpignore="true"
                  spellcheck={false}
                  maxlength={4096}
                  value={webhookUrl}
                  readOnly={!canManage}
                  disabled={testing}
                  placeholder={t("settings.teamsWorkflowTest.urlPlaceholder")}
                  onInput={(event) => setWebhookUrl(event.currentTarget.value)}
                />
                {!canManage ? (
                  <small>{settingsIntegrationsText("contributorReadOnly")}</small>
                ) : null}
                <small>{settingsIntegrationsText("bindingNeverReturned")}</small>
                </label>
                {canManage ? (
                <button
                  type="submit"
                  class="btn primary"
                  disabled={testing || !webhookUrl.trim()}
                >
                  {testing
                    ? settingsIntegrationsText("savingAndTesting")
                    : settingsIntegrationsText("saveAndTest")}
                </button>
                ) : null}
              </form>
            ) : bindingVisibility === "loading" ? (
              <div class="state-block" role="status">
                {settingsIntegrationsText("bindingLoading")}
              </div>
            ) : bindingVisibility === "hidden" ? (
              <div class="state-block" role="note">
                {settingsIntegrationsText("bindingHidden")}
              </div>
            ) : (
              <div class="state-block" role="note">
                {settingsIntegrationsText("bindingMissing")}
              </div>
            )}
            {bindingSaved ? (
              <p class="settings-teams-workflow-binding-state">
                <StatusPill kind="success" label={settingsIntegrationsText("bindingSavedPill")} />
                <small class="muted">
                  {bindingSaved.savedAt
                    ? settingsIntegrationsText("bindingSavedDetail", {
                        version: bindingSaved.bindingVersion,
                        time: new Date(bindingSaved.savedAt).toLocaleString(),
                      })
                    : settingsIntegrationsText("bindingSavedVersionOnly", {
                        version: bindingSaved.bindingVersion,
                      })}
                </small>
              </p>
            ) : null}
            {bindingError ? <div class="error" role="alert">{bindingError}</div> : null}
          </div>
        </li>
      </ol>
      {error ? <div class="error" role="alert">{error}</div> : null}
      {result ? (
        <div class="settings-webhook-diagnostic-result" role="status">
          <StatusPill kind="success" label={settingsIntegrationsText("savedAndAccepted")} />
          <small class="muted">
            {settingsIntegrationsText("savedAndAcceptedDetail", {
              status: result.providerStatus,
              time: new Date(result.testedAt).toLocaleString(),
            })}
          </small>
        </div>
      ) : null}
    </div>
  );
}

function SlackWebhookTestPanel({
  auth,
  operatorApiBaseUrl,
  canManage,
}: {
  readonly auth: AuthContext;
  readonly operatorApiBaseUrl: string;
  readonly canManage: boolean;
}) {
  const [webhookUrl, setWebhookUrl] = useState("");
  const [testing, setTesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SlackWebhookTestResult | null>(null);

  const submit = async (event: SubmitEvent) => {
    event.preventDefault();
    if (!canManage || testing || !webhookUrl.trim()) return;
    const transientUrl = webhookUrl.trim();
    setWebhookUrl("");
    setTesting(true);
    setError(null);
    setResult(null);
    try {
      setResult(
        await testSlackWebhook(
          auth,
          operatorApiBaseUrl,
          transientUrl,
          newSlackWebhookTestRequestId(),
        ),
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setTesting(false);
    }
  };

  return (
    <div class="settings-webhook-diagnostic">
      <div class="settings-webhook-diagnostic-copy">
        <strong>{t("settings.slackWebhookTest.heading")}</strong>
        <p>{t("settings.slackWebhookTest.description")}</p>
        <p>{t("settings.slackWebhookTest.boundary")}</p>
      </div>
      <form class="settings-webhook-diagnostic-form" onSubmit={(event) => { void submit(event); }}>
        <label class="settings-webhook-diagnostic-field">
          <span>{t("settings.slackWebhookTest.urlLabel")}</span>
          <input
            class="form-input"
            type="password"
            inputMode="url"
            autocomplete="off"
            data-1p-ignore
            data-bwignore
            data-lpignore="true"
            spellcheck={false}
            maxlength={2048}
            value={webhookUrl}
            disabled={!canManage || testing}
            placeholder={t("settings.slackWebhookTest.urlPlaceholder")}
            onInput={(event) => setWebhookUrl(event.currentTarget.value)}
          />
        </label>
        <button
          type="submit"
          class="btn primary"
          disabled={!canManage || testing || !webhookUrl.trim()}
        >
          {testing ? t("settings.slackWebhookTest.testing") : t("settings.slackWebhookTest.test")}
        </button>
      </form>
      {!canManage ? (
        <div class="state-block" role="note">{t("settings.slackWebhookTest.ownerRequired")}</div>
      ) : null}
      {error ? <div class="error" role="alert">{error}</div> : null}
      {result ? (
        <div class="settings-webhook-diagnostic-result" role="status">
          <StatusPill kind="success" label={t("settings.slackWebhookTest.accepted")} />
          <small class="muted">
            {t("settings.slackWebhookTest.acceptedDetail", {
              status: result.providerStatus,
              time: new Date(result.testedAt).toLocaleString(),
            })}
          </small>
        </div>
      ) : null}
    </div>
  );
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

function IntegrationGroup({
  headingId,
  title,
  description,
  integrations,
  children,
}: {
  readonly headingId: string;
  readonly title: string;
  readonly description: string;
  readonly integrations: readonly RuntimeIntegrationView[];
  readonly children?: preact.ComponentChildren;
}) {
  if (integrations.length === 0 && children === undefined) return null;
  return (
    <section class="settings-integration-group" aria-labelledby={headingId}>
      <h4 id={headingId}>{title}</h4>
      <p class="muted">{description}</p>
      <div class="settings-list">
        {integrations.map((integration) => (
          <IntegrationRow key={integration.key} integration={integration} />
        ))}
        {children}
      </div>
    </section>
  );
}

function IntegrationRow({ integration }: { readonly integration: RuntimeIntegrationView }) {
  // A row this runtime cannot observe is not the same as an unconfigured row.
  // Rendering both as "Not configured" would invite an operator to fix the
  // wrong surface, so an unobserved row stays explicitly unknown.
  const status = !integration.observed
    ? settingsIntegrationsText("statusNotObserved")
    : integration.ready
      ? t("settings.statusReady")
      : integration.configured
        ? t("settings.statusIncomplete")
        : t("settings.statusNotConfigured");
  const kind = !integration.observed
    ? "neutral"
    : integration.ready
      ? "success"
      : integration.configured
        ? "warning"
        : "neutral";
  return (
    <SettingRow
      label={integrationLabel(integration.key)}
      hint={integrationHint(integration.key)}
    >
      <span class="settings-integration-status">
        <StatusPill kind={kind} label={status} />
        <small class="muted">
          {t("settings.integrationMode", {
            mode: t(`settings.integrationModes.${integration.mode}`),
          })}
        </small>
        <small class="muted">
          {settingsIntegrationsText("integrationSource", {
            source: integrationSource(integration.source),
          })}
        </small>
        {integration.reason ? <small class="muted">{integration.reason}</small> : null}
      </span>
    </SettingRow>
  );
}

function integrationLabel(key: string): string {
  switch (key) {
    case "teams-a1-approval-send": return settingsIntegrationsText("teamsA1SendLabel");
    case "teams-a1-approval-callback": return settingsIntegrationsText("teamsA1CallbackLabel");
    case "teams-a2-operational-alert": return settingsIntegrationsText("teamsA2Label");
    case "teams-a4-digest": return settingsIntegrationsText("teamsA4Label");
    case "teams-a3-conversation": return settingsIntegrationsText("teamsA3Label");
    default: return t(`settings.integrations.${key}.label`);
  }
}

function integrationHint(key: string): string {
  switch (key) {
    case "teams-a1-approval-send": return settingsIntegrationsText("teamsA1SendHint");
    case "teams-a1-approval-callback": return settingsIntegrationsText("teamsA1CallbackHint");
    case "teams-a2-operational-alert": return settingsIntegrationsText("teamsA2Hint");
    case "teams-a4-digest": return settingsIntegrationsText("teamsA4Hint");
    case "teams-a3-conversation": return settingsIntegrationsText("teamsA3Hint");
    default: return t(`settings.integrations.${key}.hint`);
  }
}

function integrationSource(source: RuntimeIntegrationView["source"]): string {
  if (source === "core-control-plane") return settingsIntegrationsText("sourceCore");
  if (source === "operator-service") return settingsIntegrationsText("sourceOperator");
  return settingsIntegrationsText("sourceUnspecified");
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
