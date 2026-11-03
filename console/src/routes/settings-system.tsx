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
  LoadingState,
  PageHeader,
  StatusPill,
} from "../components/ui";
import { BrowserNotificationControl } from "../components/browser-notification-control";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";
import { routeHref } from "../router";
import { formatConsoleTimestamp } from "../time-format";
import { SettingRow } from "./settings";
import { ForecastHistorySourceDetails } from "./settings-forecast-history";
import { settingsIntegrationsText } from "./settings-integrations.i18n";
import {
  decodeEmailTemplatePreview,
  type EmailTemplatePreview,
} from "./settings-email-template.model";
import {
  decodeRuntimeSettings,
  type RuntimeIntegrationView,
} from "./settings-runtime.model";
import { testSlackWebhook } from "./settings-slack-webhook.command";
import {
  newSlackWebhookTestRequestId,
  type SlackWebhookTestResult,
} from "./settings-slack-webhook.model";
import {
  loadTeamsWorkflowBinding,
  revealTeamsWorkflowBinding,
  testTeamsWorkflowWebhook,
} from "./settings-teams-workflow.command";
import {
  ALL_TEAMS_NOTIFICATION_DELIVERY_TARGETS,
  canSubmitTeamsWorkflow,
  confirmsTeamsWorkflowPreferences,
  DEFAULT_TEAMS_NOTIFICATION_DELIVERY_TARGETS,
  maskSavedTeamsWorkflowUrl,
  newTeamsWorkflowTestRequestId,
  resolveTeamsDeliveryTargets,
  resolveTeamsWorkflowChannels,
  type TeamsEmailRecipientMode,
  type TeamsNotificationDeliveryTargetKey,
  type TeamsWorkflowSavedBinding,
  type TeamsWorkflowTestResult,
} from "./settings-teams-workflow.model";
import { TeamsA1OnboardingGuide } from "./settings-teams-a1-onboarding";
import { DocumentOcrSettingsPanel } from "./document-ocr-settings";
import { useAdministrationRead } from "./settings-administration-read";
import { authenticationMode } from "./settings-diagnostics";
export {
  SettingsDiagnosticsRoute, authenticationMode, isCurrentDiagnosticCheck, isHealthy,
} from "./settings-diagnostics";
import {
  decodeLicensingWarningProjection as decodeLicensingWarningProjectionModel,
  formatLicensingStatusBadge as formatLicensingStatusBadgeModel,
  type LicensingLocale,
  type LicensingStatusBadgeViewModel,
  type LicensingWarningProjectionPayload,
} from "./licensing-status-badge.model";

export type { LicensingStatusBadgeViewModel, LicensingWarningProjectionPayload };

export function decodeLicensingWarningProjection(
  value: unknown,
): LicensingWarningProjectionPayload | null {
  if (value === null || value === undefined) return null;
  return decodeLicensingWarningProjectionModel(value);
}

export function formatLicensingStatusBadge(
  payload: LicensingWarningProjectionPayload | null | undefined,
  locale: LicensingLocale = "en",
): LicensingStatusBadgeViewModel {
  return formatLicensingStatusBadgeModel(payload ?? null, locale);
}
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

export function personalNotificationPrincipalLabel(auth: AuthContext): string | null {
  const displayName = auth.account?.name?.trim();
  return displayName || auth.account?.username || null;
}

export function SettingsIntegrationsRoute({ client, auth }: Props) {
  const authMode = authenticationMode(auth);
  const [refreshEpoch, setRefreshEpoch] = useState(0);
  const runtimeSettings = useRuntimeSettings(client, refreshEpoch);
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
      records: runtimeSettings.state.status === "ready"
       ? { integrations: runtimeSettings.state.data.integrations.map((item) => ({ ...item })) }
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
      <section class="settings-section" aria-labelledby="settings-personal-notification-channels">
        <h3 id="settings-personal-notification-channels">
          {settingsIntegrationsText("personalChannelsTitle")}
        </h3>
        <p class="muted">{settingsIntegrationsText("personalChannelsDescription")}</p>
        <div class="settings-list">
          <SettingRow
            label={settingsIntegrationsText("consoleWebPersonalLabel")}
            hint={settingsIntegrationsText("consoleWebPersonalHint", {
              user: personalNotificationPrincipalLabel(auth)
                ?? settingsIntegrationsText("localPrincipal"),
            })}
          >
            <BrowserNotificationControl
              client={client}
              principalId={auth.account?.homeAccountId ?? null}
              presentation="settings"
            />
          </SettingRow>
        </div>
      </section>
      <section class="settings-section" aria-labelledby="settings-delivery-integrations">
        <h3 id="settings-delivery-integrations">{t("settings.delivery")}</h3>
        <IntegrationReadFeedback read={runtimeSettings} />
        {runtimeSettings.state.status !== "unavailable" ? <AsyncBoundary
          state={runtimeSettings.state}
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
                children={(
                  <TeamsA1OnboardingGuide
                    auth={auth}
                    operatorApiBaseUrl={client.operatorApiBaseUrl}
                    onboarding={runtime.teamsA1Onboarding}
                  />
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
                  onBindingChanged={() => setRefreshEpoch((value) => value + 1)}
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
        </AsyncBoundary> : null}
        <nav class="settings-integration-links" aria-label={t("settings.integrationEvidence")}>
          <a href={routeHref("settings-diagnostics")}>{t("route.settingsDiagnostics")}</a>
          <a href={routeHref("settings-environment")}>{t("route.settingsEnvironment")}</a>
        </nav>
      </section>
      <DocumentOcrSettingsPanel client={client} auth={auth} />
      <section class="settings-section" aria-labelledby="settings-incident-email-template">
        <h3 id="settings-incident-email-template">{t("settings.emailTemplateHeading")}</h3>
        <IntegrationReadFeedback read={incidentEmailTemplate} />
        {incidentEmailTemplate.state.status !== "unavailable" ? <AsyncBoundary
          state={incidentEmailTemplate.state}
          resourceLabel={t("settings.emailTemplateResource")}
        >
          {(template) => <EmailTemplatePreviewPanel template={template} />}
        </AsyncBoundary> : null}
      </section>
    </div>
  );
}

function useRuntimeSettings(
  client: OperatorApiClient,
  refreshEpoch = 0,
) {
  return useAdministrationRead(client, async () =>
    decodeRuntimeSettings(await client.panel<unknown>("/runtime/settings")), refreshEpoch);
}

function useIncidentEmailTemplate(client: OperatorApiClient) {
  return useAdministrationRead(client, async () => decodeEmailTemplatePreview(
    await client.panel<unknown>("/notification-templates/incident-opened")));
}

function IntegrationReadFeedback({ read }: {
  readonly read: ReturnType<typeof useAdministrationRead<unknown>>;
}) {
  return <div class="settings-read-feedback">
    <button type="button" class="secondary" disabled={read.refreshing} onClick={read.refresh}>
      {read.state.status === "ready" ? settingsIntegrationsText("readRefresh") : t("settings.retry")}
    </button>
    {read.observedAt ? <small>{settingsIntegrationsText("readObservedAt", { time: formatConsoleTimestamp(read.observedAt) })}</small> : null}
    {read.refreshing && read.state.status === "ready" ? <span role="status">{settingsIntegrationsText("readRefreshing")}</span> : null}
    {read.error ? <p role="alert">{settingsIntegrationsText(read.state.status === "ready" ? "readStale" : "readUnavailable")}</p> : null}
  </div>;
}

export function TeamsWorkflowTestPanel({
  auth,
  operatorApiBaseUrl,
  canManage,
  onBindingChanged,
}: {
  readonly auth: AuthContext;
  readonly operatorApiBaseUrl: string;
  readonly canManage: boolean;
  readonly onBindingChanged?: () => void;
}) {
  const [webhookUrl, setWebhookUrl] = useState("");
  const [channelLabel, setChannelLabel] = useState("");
  const [isEditingUrl, setIsEditingUrl] = useState(false);
  const [accountHint, setAccountHint] = useState(TEAMS_WORKFLOW_ACCOUNT_HINT);
  const [testing, setTesting] = useState(false);
  const [savingPreferences, setSavingPreferences] = useState(false);
  const preferencePending = useRef(false);
  const [preferenceNotice, setPreferenceNotice] = useState(false);
  const [bindingRevision, setBindingRevision] = useState(0);
  const [revealing, setRevealing] = useState(false);
  const [isUrlRevealed, setIsUrlRevealed] = useState(false);
  const [revealedBinding, setRevealedBinding] = useState<{
    readonly bindingVersion: string;
    readonly webhookUrl: string;
  } | null>(null);
  const [revealedChannelUrls, setRevealedChannelUrls] = useState<Readonly<Record<string, string>>>({});
  const [urlCopied, setUrlCopied] = useState(false);
  const copyTimerRef = useRef<number | null>(null);
  const preferenceGenerationRef = useRef(0);
  const [error, setError] = useState<string | null>(null);
  const [bindingError, setBindingError] = useState<string | null>(null);
  const [bindingVisibility, setBindingVisibility] = useState<
    "loading" | "hidden" | "visible" | "missing" | "unavailable"
  >("loading");
  const [bindingSaved, setBindingSaved] = useState<TeamsWorkflowSavedBinding | null>(null);
  const [selectedTargets, setSelectedTargets] = useState<
    readonly TeamsNotificationDeliveryTargetKey[]
  >(DEFAULT_TEAMS_NOTIFICATION_DELIVERY_TARGETS);
  const [emailRecipientMode, setEmailRecipientMode] =
    useState<TeamsEmailRecipientMode>("login");
  const [customEmail, setCustomEmail] = useState("");
  const [result, setResult] = useState<TeamsWorkflowTestResult | null>(null);
  const accountIsValid = !accountHint.trim() || isEmailStyleUserPrincipalName(accountHint.trim());
  const customEmailIsValid =
    emailRecipientMode !== "custom"
    || (Boolean(customEmail.trim()) && isEmailStyleUserPrincipalName(customEmail.trim()));
  const loginEmail =
    auth.account?.username ?? t("settings.teamsWorkflowTest.accountUnavailable");
  const effectiveRecipientEmail =
    bindingSaved?.emailRecipientMode === "custom" && bindingSaved.customEmail.trim()
      ? bindingSaved.customEmail.trim()
      : loginEmail;

  useEffect(() => () => {
    if (copyTimerRef.current !== null) {
      window.clearTimeout(copyTimerRef.current);
    }
  }, []);

  useEffect(() => {
    let active = true;
    setBindingVisibility("loading");
    setBindingError(null);
    setBindingSaved(null);
    setRevealedBinding(null);
    setRevealedChannelUrls({});
    setIsUrlRevealed(false);
    setWebhookUrl("");
    setChannelLabel("");
    setSelectedTargets(DEFAULT_TEAMS_NOTIFICATION_DELIVERY_TARGETS);
    setEmailRecipientMode("login");
    setCustomEmail("");
    setSavingPreferences(false);
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
        const resolvedTargets = resolveTeamsDeliveryTargets(binding);
        const resolvedEmailMode = binding.emailRecipientMode ?? "login";
        const resolvedCustomEmail = binding.customEmail ?? "";
        setSelectedTargets(resolvedTargets);
        setEmailRecipientMode(resolvedEmailMode);
        setCustomEmail(resolvedCustomEmail);
        setBindingSaved({
          bindingVersion: binding.bindingVersion,
          endpointIdentifier: binding.endpointIdentifier,
          savedAt: binding.savedAt,
          observedAt: binding.observedAt,
          channels: resolveTeamsWorkflowChannels(binding),
          deliveryTargets: resolvedTargets,
          emailRecipientMode: resolvedEmailMode,
          customEmail: resolvedCustomEmail,
        });
        setBindingVisibility("visible");
      } catch (reason) {
        if (!active) return;
        setBindingError(settingsIntegrationsText("bindingUnavailable"));
        setBindingVisibility("unavailable");
      }
    })();
    return () => {
      active = false;
      preferenceGenerationRef.current += 1;
      preferencePending.current = false;
    };
  }, [auth, operatorApiBaseUrl, bindingRevision]);

  const markUrlCopied = () => {
    setUrlCopied(true);
    if (copyTimerRef.current !== null) {
      window.clearTimeout(copyTimerRef.current);
    }
    copyTimerRef.current = window.setTimeout(() => {
      setUrlCopied(false);
      copyTimerRef.current = null;
    }, 1500);
  };

  const toggleRevealSavedUrl = async () => {
    if (testing || revealing || !bindingSaved) return;
    if (isUrlRevealed) {
      setIsUrlRevealed(false);
      setIsEditingUrl(false);
      return;
    }
    if (revealedBinding && revealedBinding.bindingVersion === bindingSaved.bindingVersion) {
      setWebhookUrl("");
      setIsEditingUrl(false);
      setIsUrlRevealed(true);
      return;
    }
    setRevealing(true);
    setBindingError(null);
    try {
      const revealed = await revealTeamsWorkflowBinding(auth, operatorApiBaseUrl);
      setRevealedBinding({
        bindingVersion: revealed.bindingVersion,
        webhookUrl: revealed.webhookUrl,
      });
      setWebhookUrl("");
      setIsEditingUrl(false);
      setIsUrlRevealed(true);
    } catch {
      setBindingError(settingsIntegrationsText("bindingUnavailable"));
    } finally {
      setRevealing(false);
    }
  };

  const copySavedOrDraftUrl = async () => {
    if (testing || revealing) return;
    const draft = webhookUrl.trim();
    if (draft) {
      try {
        await navigator.clipboard.writeText(draft);
        markUrlCopied();
      } catch {
        setBindingError(settingsIntegrationsText("clipboardFailed"));
      }
      return;
    }
    if (!bindingSaved) return;
    setRevealing(true);
    setBindingError(null);
    try {
      let fullUrl =
        revealedBinding && revealedBinding.bindingVersion === bindingSaved.bindingVersion
          ? revealedBinding.webhookUrl
          : null;
      if (!fullUrl) {
        const revealed = await revealTeamsWorkflowBinding(auth, operatorApiBaseUrl);
        setRevealedBinding({
          bindingVersion: revealed.bindingVersion,
          webhookUrl: revealed.webhookUrl,
        });
        fullUrl = revealed.webhookUrl;
      }
      await navigator.clipboard.writeText(fullUrl);
      markUrlCopied();
    } catch {
      setBindingError(settingsIntegrationsText("clipboardFailed"));
    } finally {
      setRevealing(false);
    }
  };

  const persistChannelPreferences = async (options: {
    readonly selectedChannelIds?: readonly string[];
    readonly deliveryTargets?: readonly TeamsNotificationDeliveryTargetKey[];
    readonly removeChannelId?: string;
    readonly emailRecipientMode?: TeamsEmailRecipientMode;
    readonly customEmail?: string;
  }) => {
    if (!canManage || !bindingSaved || preferencePending.current || testing) return;
    preferencePending.current = true;
    setSavingPreferences(true);
    setPreferenceNotice(false);
    const confirmedBinding = bindingSaved;
    const generation = ++preferenceGenerationRef.current;
    setBindingError(null);
    try {
      const receipt = await testTeamsWorkflowWebhook(
        auth,
        operatorApiBaseUrl,
        "",
        newTeamsWorkflowTestRequestId(),
        {
          ...(options.selectedChannelIds !== undefined
            ? { selectedChannelIds: options.selectedChannelIds }
            : {}),
          ...(options.deliveryTargets !== undefined
            ? { deliveryTargets: options.deliveryTargets }
            : {}),
          ...(options.removeChannelId !== undefined
            ? { removeChannelId: options.removeChannelId }
            : {}),
          ...(options.emailRecipientMode !== undefined
            ? { emailRecipientMode: options.emailRecipientMode }
            : {}),
          ...(options.customEmail !== undefined
            ? { customEmail: options.customEmail }
            : {}),
          selectionOnly: true,
        },
      );
      const refreshed = await loadTeamsWorkflowBinding(auth, operatorApiBaseUrl);
      if (preferenceGenerationRef.current !== generation) return;
      if (refreshed.visible && refreshed.configured
        && refreshed.bindingVersion === receipt.bindingVersion
        && confirmsTeamsWorkflowPreferences(refreshed, options)) {
        const nextTargets =
          refreshed.deliveryTargets !== undefined
            ? resolveTeamsDeliveryTargets(refreshed)
            : options.deliveryTargets ?? selectedTargets;
        const nextEmailMode =
          refreshed.emailRecipientMode
          ?? options.emailRecipientMode
          ?? emailRecipientMode;
        const nextCustomEmail =
          refreshed.customEmail !== undefined
            ? refreshed.customEmail
            : options.customEmail ?? customEmail;
        setSelectedTargets(nextTargets);
        setEmailRecipientMode(nextEmailMode);
        setCustomEmail(nextCustomEmail);
        setBindingSaved((current) => ({
          bindingVersion: refreshed.bindingVersion,
          endpointIdentifier: refreshed.endpointIdentifier,
          savedAt: refreshed.savedAt,
          observedAt: refreshed.observedAt,
          channels:
            refreshed.channels !== undefined
              ? resolveTeamsWorkflowChannels(refreshed)
              : current?.channels ?? resolveTeamsWorkflowChannels(refreshed),
          deliveryTargets: nextTargets,
          emailRecipientMode: nextEmailMode,
          customEmail: nextCustomEmail,
        }));
        onBindingChanged?.();
        setPreferenceNotice(true);
      } else {
        throw new Error("Binding confirmation unavailable");
      }
    } catch {
      if (preferenceGenerationRef.current !== generation) return;
      setBindingSaved(confirmedBinding);
      setSelectedTargets(confirmedBinding.deliveryTargets ?? DEFAULT_TEAMS_NOTIFICATION_DELIVERY_TARGETS);
      setEmailRecipientMode(confirmedBinding.emailRecipientMode ?? "login");
      setCustomEmail(confirmedBinding.customEmail ?? "");
      setBindingError(settingsIntegrationsText("preferenceFailed"));
    } finally {
      if (preferenceGenerationRef.current === generation) {
        preferencePending.current = false;
        setSavingPreferences(false);
      }
    }
  };

  const selectEmailRecipientMode = (nextMode: TeamsEmailRecipientMode) => {
    if (!canManage || testing || preferencePending.current) return;
    setEmailRecipientMode(nextMode);
    if (nextMode === "login" && bindingSaved) {
      void persistChannelPreferences({
        selectedChannelIds: bindingSaved.channels
          .filter((ch) => ch.enabled)
          .map((ch) => ch.channelId),
        deliveryTargets: selectedTargets,
        emailRecipientMode: "login",
        customEmail: customEmail.trim(),
      });
    } else if (
      nextMode === "custom"
      && bindingSaved
      && customEmail.trim()
      && isEmailStyleUserPrincipalName(customEmail.trim())
    ) {
      void persistChannelPreferences({
        selectedChannelIds: bindingSaved.channels
          .filter((ch) => ch.enabled)
          .map((ch) => ch.channelId),
        deliveryTargets: selectedTargets,
        emailRecipientMode: "custom",
        customEmail: customEmail.trim(),
      });
    }
  };

  const saveCustomRecipientEmail = () => {
    if (!canManage || testing || preferencePending.current || !customEmailIsValid) return;
    if (bindingSaved) {
      void persistChannelPreferences({
        selectedChannelIds: bindingSaved.channels
          .filter((ch) => ch.enabled)
          .map((ch) => ch.channelId),
        deliveryTargets: selectedTargets,
        emailRecipientMode,
        customEmail: customEmail.trim(),
      });
    }
  };

  const toggleDeliveryTarget = (target: TeamsNotificationDeliveryTargetKey) => {
    if (!canManage || testing || preferencePending.current) return;
    const exists = selectedTargets.includes(target);
    if (exists && selectedTargets.length <= 1) return;
    const next = exists
      ? selectedTargets.filter((item) => item !== target)
      : [...selectedTargets, target];
    setSelectedTargets(next);
    if (bindingSaved) {
      setBindingSaved({ ...bindingSaved, deliveryTargets: next });
      void persistChannelPreferences({
        selectedChannelIds: bindingSaved.channels
          .filter((ch) => ch.enabled)
          .map((ch) => ch.channelId),
        deliveryTargets: next,
      });
    }
  };

  const applyDeliveryTargetsPreset = (
    next: readonly TeamsNotificationDeliveryTargetKey[],
  ) => {
    if (!canManage || testing || preferencePending.current) return;
    setSelectedTargets(next);
    if (bindingSaved) {
      setBindingSaved({ ...bindingSaved, deliveryTargets: next });
      void persistChannelPreferences({
        selectedChannelIds: bindingSaved.channels
          .filter((ch) => ch.enabled)
          .map((ch) => ch.channelId),
        deliveryTargets: next,
      });
    }
  };

  const toggleSavedChannel = (channelId: string) => {
    if (!canManage || testing || preferencePending.current || !bindingSaved) return;
    const enabledCount = bindingSaved.channels.filter((ch) => ch.enabled).length;
    const targetChannel = bindingSaved.channels.find((ch) => ch.channelId === channelId);
    if (!targetChannel) return;
    if (targetChannel.enabled && enabledCount <= 1) return;
    const nextChannels = bindingSaved.channels.map((ch) =>
      ch.channelId === channelId ? { ...ch, enabled: !ch.enabled } : ch,
    );
    setBindingSaved({ ...bindingSaved, channels: nextChannels });
    void persistChannelPreferences({
      selectedChannelIds: nextChannels.filter((ch) => ch.enabled).map((ch) => ch.channelId),
      deliveryTargets: selectedTargets,
    });
  };

  const removeSavedChannel = (channelId: string) => {
    if (!canManage || testing || preferencePending.current || !bindingSaved || bindingSaved.channels.length <= 1) return;
    if (channelId in revealedChannelUrls) {
      const nextRevealed = { ...revealedChannelUrls };
      delete nextRevealed[channelId];
      setRevealedChannelUrls(nextRevealed);
    }
    const remaining = bindingSaved.channels.filter((ch) => ch.channelId !== channelId);
    const normalized = remaining.some((ch) => ch.enabled)
      ? remaining
      : remaining.map((ch, index) => (index === 0 ? { ...ch, enabled: true } : ch));
    setBindingSaved({ ...bindingSaved, channels: normalized });
    void persistChannelPreferences({
      selectedChannelIds: normalized.filter((ch) => ch.enabled).map((ch) => ch.channelId),
      deliveryTargets: selectedTargets,
      removeChannelId: channelId,
    });
  };

  const toggleRevealChannelRow = async (channelId: string) => {
    if (testing || revealing) return;
    if (channelId in revealedChannelUrls) {
      const next = { ...revealedChannelUrls };
      delete next[channelId];
      setRevealedChannelUrls(next);
      return;
    }
    setRevealing(true);
    setBindingError(null);
    try {
      const revealed = await revealTeamsWorkflowBinding(auth, operatorApiBaseUrl, channelId);
      setRevealedChannelUrls({
        ...revealedChannelUrls,
        [channelId]: revealed.webhookUrl,
      });
    } catch (reason) {
      setBindingError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setRevealing(false);
    }
  };

  const submit = async (event: SubmitEvent) => {
    event.preventDefault();
    if (
      !canManage
      || testing
      || preferencePending.current
      || !customEmailIsValid
      || !canSubmitTeamsWorkflow(webhookUrl, bindingSaved !== null)
    ) return;
    const submittedUrl = webhookUrl.trim();
    const submittedLabel = channelLabel.trim();
    setWebhookUrl("");
    setChannelLabel("");
    setIsEditingUrl(false);
    setIsUrlRevealed(false);
    if (submittedUrl) {
      setRevealedBinding(null);
      setRevealedChannelUrls({});
    }
    setTesting(true);
    setError(null);
    setResult(null);
    try {
      const saved = await testTeamsWorkflowWebhook(
        auth,
        operatorApiBaseUrl,
        submittedUrl,
        newTeamsWorkflowTestRequestId(),
        {
          ...(submittedLabel ? { channelLabel: submittedLabel } : {}),
          ...(bindingSaved
            ? {
                selectedChannelIds: bindingSaved.channels
                  .filter((ch) => ch.enabled)
                  .map((ch) => ch.channelId),
              }
            : {}),
          deliveryTargets: selectedTargets,
          emailRecipientMode,
          customEmail: customEmail.trim(),
        },
      );
      const refreshedBinding = await loadTeamsWorkflowBinding(auth, operatorApiBaseUrl);
      if (!refreshedBinding.visible || !refreshedBinding.configured) {
        throw new Error("Saved Teams Workflow binding metadata is unavailable");
      }
      if (refreshedBinding.bindingVersion !== saved.bindingVersion || !confirmsTeamsWorkflowPreferences(refreshedBinding, {
        deliveryTargets: selectedTargets, emailRecipientMode, customEmail: customEmail.trim(),
      })) {
        throw new Error(settingsIntegrationsText("bindingConfirmationUnavailable"));
      }
      const nextTargets = resolveTeamsDeliveryTargets(refreshedBinding);
      const nextEmailMode =
        refreshedBinding.emailRecipientMode ?? emailRecipientMode;
      const nextCustomEmail =
        refreshedBinding.customEmail !== undefined
          ? refreshedBinding.customEmail
          : customEmail;
      setSelectedTargets(nextTargets);
      setEmailRecipientMode(nextEmailMode);
      setCustomEmail(nextCustomEmail);
      setBindingSaved({
        bindingVersion: saved.bindingVersion,
        endpointIdentifier: refreshedBinding.endpointIdentifier,
        savedAt: saved.savedAt,
        observedAt: saved.testedAt,
        channels: resolveTeamsWorkflowChannels(refreshedBinding),
        deliveryTargets: nextTargets,
        emailRecipientMode: nextEmailMode,
        customEmail: nextCustomEmail,
      });
      setBindingVisibility("visible");
      onBindingChanged?.();
      if (!saved.accepted) {
        setError(
          saved.providerStatus > 0
            ? `Binding saved, but Teams rejected the test card with HTTP ${saved.providerStatus}`
            : "Binding saved, but the Teams test acknowledgement was not observed",
        );
        return;
      }
      setResult(saved);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setTesting(false);
    }
  };

  const displayedWebhookUrl =
    webhookUrl !== "" || (canManage && isEditingUrl && !isUrlRevealed)
      ? webhookUrl
      : isUrlRevealed
          && revealedBinding
          && bindingSaved
          && revealedBinding.bindingVersion === bindingSaved.bindingVersion
        ? revealedBinding.webhookUrl
        : bindingSaved
          ? maskSavedTeamsWorkflowUrl(bindingSaved.endpointIdentifier)
          : "";
  const canInspectSavedUrl = bindingSaved !== null;

  return (
    <div class="settings-webhook-diagnostic settings-teams-workflow-setup">
      <div class="settings-webhook-diagnostic-copy">
        <h4>{t("settings.teamsWorkflowTest.heading")}</h4>
        <p>{t("settings.teamsWorkflowTest.description")}</p>
        <p>{settingsIntegrationsText("saveBoundary")}</p>
      </div>
      <div class="settings-read-feedback">
        <button type="button" class="secondary"
          disabled={testing || savingPreferences || revealing || bindingVisibility === "loading"}
          onClick={() => setBindingRevision((value) => value + 1)}>
          {settingsIntegrationsText("bindingRefresh")}
        </button>
        <small>{settingsIntegrationsText("bindingRefreshHint")}</small>
      </div>
      <span class="sr-only" role="status">{urlCopied ? t("shared.copied") : ""}</span>
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
            {(canManage && bindingVisibility === "missing") || bindingVisibility === "visible" ? (
              <form
                class="settings-webhook-diagnostic-form"
                onSubmit={(event) => { void submit(event); }}
              >
                <div class="settings-webhook-diagnostic-field">
                  <label for="teams-workflow-webhook-url">
                    {settingsIntegrationsText("saveUrlLabel")}
                  </label>
                  <div class="settings-teams-workflow-url-control">
                    <input
                      id="teams-workflow-webhook-url"
                      class="form-input"
                      type="text"
                      inputMode="url"
                      autocomplete="off"
                      data-1p-ignore
                      data-bwignore
                      data-lpignore="true"
                      spellcheck={false}
                      maxlength={4096}
                      value={displayedWebhookUrl}
                      readOnly={!canManage}
                      disabled={testing}
                      placeholder={
                        bindingSaved?.endpointIdentifier
                        ?? t("settings.teamsWorkflowTest.urlPlaceholder")
                      }
                      onFocus={() => {
                        if (canManage && !isUrlRevealed && !webhookUrl) {
                          setIsEditingUrl(true);
                        }
                      }}
                      onBlur={() => {
                        if (!webhookUrl.trim()) {
                          setIsEditingUrl(false);
                        }
                      }}
                      onInput={(event) => {
                        setIsUrlRevealed(false);
                        setIsEditingUrl(true);
                        setWebhookUrl(event.currentTarget.value);
                      }}
                    />
                    {canInspectSavedUrl ? (
                      <div class="settings-teams-workflow-url-actions">
                        <button
                          type="button"
                          class="settings-teams-workflow-icon-btn"
                          disabled={testing || revealing}
                          aria-pressed={isUrlRevealed}
                          aria-label={
                            isUrlRevealed
                              ? settingsIntegrationsText("hideSavedUrl")
                              : settingsIntegrationsText("revealSavedUrl")
                          }
                          onClick={() => {
                            void toggleRevealSavedUrl();
                          }}
                        >
                          {isUrlRevealed ? (
                            <svg
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              stroke-width="2"
                              stroke-linecap="round"
                              stroke-linejoin="round"
                              aria-hidden="true"
                            >
                              <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                              <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
                              <line x1="1" y1="1" x2="23" y2="23" />
                            </svg>
                          ) : (
                            <svg
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              stroke-width="2"
                              stroke-linecap="round"
                              stroke-linejoin="round"
                              aria-hidden="true"
                            >
                              <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                              <circle cx="12" cy="12" r="3" />
                            </svg>
                          )}
                        </button>
                        <button
                          type="button"
                          class="settings-teams-workflow-icon-btn"
                          disabled={testing || revealing}
                          aria-label={
                            urlCopied
                              ? t("shared.copied")
                              : settingsIntegrationsText("copySavedUrl")
                          }
                          onClick={() => {
                            void copySavedOrDraftUrl();
                          }}
                        >
                          {urlCopied ? (
                            <svg
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              stroke-width="2"
                              stroke-linecap="round"
                              stroke-linejoin="round"
                              aria-hidden="true"
                            >
                              <polyline points="20 6 9 17 4 12" />
                            </svg>
                          ) : (
                            <svg
                              viewBox="0 0 24 24"
                              fill="none"
                              stroke="currentColor"
                              stroke-width="2"
                              stroke-linecap="round"
                              stroke-linejoin="round"
                              aria-hidden="true"
                            >
                              <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
                              <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
                            </svg>
                          )}
                        </button>
                      </div>
                    ) : null}
                  </div>
                </div>
                {canManage ? (
                <button
                  type="submit"
                  class="btn primary"
                  disabled={
                    testing || savingPreferences || !customEmailIsValid
                    || !canSubmitTeamsWorkflow(webhookUrl, bindingSaved !== null)
                  }
                >
                  {testing
                    ? settingsIntegrationsText("savingAndTesting")
                    : webhookUrl.trim()
                      ? settingsIntegrationsText("saveAndTest")
                      : settingsIntegrationsText("testSaved")}
                </button>
                ) : null}
                <small class="settings-webhook-diagnostic-help">
                  {canManage
                    ? settingsIntegrationsText("bindingNeverReturned")
                    : settingsIntegrationsText("contributorReadOnly")}
                </small>
              </form>
            ) : bindingVisibility === "loading" ? (
              <LoadingState label={settingsIntegrationsText("bindingLoading")} />
            ) : bindingVisibility === "unavailable" ? (
              <div class="state-block">
                <p>{settingsIntegrationsText("bindingUnavailable")}</p>
                <button type="button" class="secondary" onClick={() => setBindingRevision((value) => value + 1)}>
                  {t("settings.retry")}
                </button>
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
            {(canManage && bindingVisibility === "missing") || bindingVisibility === "visible" ? (
              <div class="settings-teams-workflow-channel-selector">
                <div class="settings-teams-workflow-channel-selector-head">
                  <strong>{settingsIntegrationsText("channelSelectionTitle")}</strong>
                  <div class="settings-teams-workflow-channel-selector-actions">
                    <StatusPill
                      kind={selectedTargets.length > 1 ? "success" : "neutral"}
                      label={
                        selectedTargets.length > 1
                          ? settingsIntegrationsText("channelModeMultiple", {
                              count: selectedTargets.length,
                            })
                          : settingsIntegrationsText("channelModeSingle")
                      }
                    />
                    {canManage ? (
                      <>
                        <button
                          type="button"
                          class="btn btn-small"
                          disabled={
                            testing
                            || savingPreferences
                            || selectedTargets.length
                              === ALL_TEAMS_NOTIFICATION_DELIVERY_TARGETS.length
                          }
                          onClick={() =>
                            applyDeliveryTargetsPreset(ALL_TEAMS_NOTIFICATION_DELIVERY_TARGETS)
                          }
                        >
                          {settingsIntegrationsText("selectAllChannels")}
                        </button>
                        <button
                          type="button"
                          class="btn btn-small"
                          disabled={
                            testing
                            || savingPreferences
                            || (selectedTargets.length === 1
                              && selectedTargets[0] === "teams-a2-operational-alert")
                          }
                          onClick={() =>
                            applyDeliveryTargetsPreset(["teams-a2-operational-alert"])
                          }
                        >
                          {settingsIntegrationsText("selectSingleChannel")}
                        </button>
                      </>
                    ) : null}
                  </div>
                </div>
                <p>{settingsIntegrationsText("channelSelectionHint")}</p>
                <p id="teams-minimum-selection" class="muted">{settingsIntegrationsText("minimumSelection")}</p>
                {savingPreferences ? <p role="status">{settingsIntegrationsText("preferenceSaving")}</p> : null}
                {preferenceNotice ? <p role="status">{settingsIntegrationsText("preferenceSaved")}</p> : null}
                <div class="settings-teams-workflow-checkbox-grid">
                  {ALL_TEAMS_NOTIFICATION_DELIVERY_TARGETS.map((targetKey) => {
                    const checked = selectedTargets.includes(targetKey);
                    return (
                      <label
                        key={targetKey}
                        class={`settings-teams-workflow-checkbox-option${
                          checked ? " is-checked" : ""
                        }`}
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          disabled={!canManage || testing || savingPreferences || (checked && selectedTargets.length === 1)}
                          aria-describedby="teams-minimum-selection"
                          onChange={() => toggleDeliveryTarget(targetKey)}
                        />
                        <span class="settings-teams-workflow-checkbox-copy">
                          <strong>
                            {settingsIntegrationsText(`target.${targetKey}.label`)}
                          </strong>
                          <small>
                            {settingsIntegrationsText(`target.${targetKey}.hint`)}
                          </small>
                        </span>
                      </label>
                    );
                  })}
                </div>
                <div class="settings-teams-workflow-email-recipient">
                  <div class="settings-teams-workflow-channel-selector-head">
                    <strong>{settingsIntegrationsText("emailRecipientTitle")}</strong>
                    <StatusPill
                      kind="neutral"
                      label={bindingSaved ? settingsIntegrationsText("emailRecipientActivePill", {
                        email: effectiveRecipientEmail,
                      }) : settingsIntegrationsText("recipientDraftPill")}
                    />
                  </div>
                  <p>{settingsIntegrationsText("emailRecipientHint")}</p>
                  {(!bindingSaved || emailRecipientMode !== bindingSaved.emailRecipientMode
                    || customEmail.trim() !== bindingSaved.customEmail) ? (
                    <p class="muted">{settingsIntegrationsText("recipientDraft")}</p>
                  ) : null}
                  <div class="settings-teams-workflow-email-modes">
                    <label>
                      <input
                        type="radio"
                        name="teams-workflow-email-recipient-mode"
                        checked={emailRecipientMode === "login"}
                        disabled={!canManage || testing || savingPreferences}
                        onChange={() => selectEmailRecipientMode("login")}
                      />
                      <span>
                        {settingsIntegrationsText("emailRecipientModeLogin", {
                          email: loginEmail,
                        })}
                      </span>
                    </label>
                    <label>
                      <input
                        type="radio"
                        name="teams-workflow-email-recipient-mode"
                        checked={emailRecipientMode === "custom"}
                        disabled={!canManage || testing || savingPreferences}
                        onChange={() => selectEmailRecipientMode("custom")}
                      />
                      <span>{settingsIntegrationsText("emailRecipientModeCustom")}</span>
                    </label>
                  </div>
                  {emailRecipientMode === "custom" ? (
                    <>
                    <div class="settings-teams-workflow-email-custom-row">
                      <input
                        class="form-input"
                        type="email"
                        maxlength={254}
                        aria-label={settingsIntegrationsText("emailRecipientCustomLabel")}
                        aria-invalid={!customEmailIsValid ? "true" : undefined}
                        aria-describedby="teams-recipient-help"
                        value={customEmail}
                        disabled={!canManage || testing || savingPreferences}
                        placeholder={settingsIntegrationsText(
                          "emailRecipientCustomPlaceholder",
                        )}
                        onInput={(event) => setCustomEmail(event.currentTarget.value)}
                      />
                      {canManage ? (
                        <button
                          type="button"
                          class="btn btn-small primary"
                          disabled={
                            testing
                            || savingPreferences || !bindingSaved
                            || !customEmail.trim()
                            || !customEmailIsValid
                          }
                          onClick={() => saveCustomRecipientEmail()}
                        >
                          {settingsIntegrationsText("emailRecipientSave")}
                        </button>
                      ) : null}
                    </div>
                    <small id="teams-recipient-help">
                      {settingsIntegrationsText(customEmailIsValid ? "recipientDraft" : "recipientInvalid")}
                    </small>
                    </>
                  ) : null}
                </div>
                {bindingSaved && bindingSaved.channels.length > 0 ? (
                  <div class="settings-teams-workflow-saved-channels">
                    <div class="settings-teams-workflow-channel-selector-head">
                      <strong>{settingsIntegrationsText("savedTeamsChannelsTitle")}</strong>
                      <StatusPill
                        kind={
                          bindingSaved.channels.filter((ch) => ch.enabled).length > 1
                            ? "success"
                            : "neutral"
                        }
                        label={
                          bindingSaved.channels.filter((ch) => ch.enabled).length > 1
                            ? settingsIntegrationsText("channelModeMultiple", {
                                count: bindingSaved.channels.filter((ch) => ch.enabled).length,
                              })
                            : settingsIntegrationsText("channelModeSingle")
                        }
                      />
                    </div>
                    <p>{settingsIntegrationsText("savedTeamsChannelsHint")}</p>
                    {canManage ? (
                      <div class="settings-teams-workflow-label-input">
                        <label for="teams-workflow-channel-label">
                          {settingsIntegrationsText("channelLabelInput")}
                        </label>
                        <input
                          id="teams-workflow-channel-label"
                          class="form-input"
                          type="text"
                          maxlength={80}
                          disabled={testing}
                          value={channelLabel}
                          placeholder={settingsIntegrationsText("channelLabelPlaceholder")}
                          onInput={(event) => setChannelLabel(event.currentTarget.value)}
                        />
                      </div>
                    ) : null}
                    {bindingSaved.channels.map((channel) => {
                      const rowRevealedUrl = revealedChannelUrls[channel.channelId];
                      return (
                        <div
                          key={channel.channelId}
                          class={`settings-teams-workflow-saved-channel-row${
                            channel.enabled ? " is-checked" : ""
                          }`}
                        >
                          <input
                            type="checkbox"
                            checked={channel.enabled}
                            disabled={!canManage || testing || savingPreferences || (channel.enabled && bindingSaved.channels.filter((item) => item.enabled).length === 1)}
                            aria-describedby="teams-minimum-selection"
                            aria-label={channel.label}
                            onChange={() => toggleSavedChannel(channel.channelId)}
                          />
                          <div class="settings-teams-workflow-saved-channel-info">
                            <strong>{channel.label}</strong>
                            <code>
                              {rowRevealedUrl
                                ?? maskSavedTeamsWorkflowUrl(channel.endpointIdentifier)}
                            </code>
                          </div>
                          <div class="settings-teams-workflow-url-actions">
                            <button
                              type="button"
                              class="settings-teams-workflow-icon-btn"
                              disabled={testing || revealing || savingPreferences}
                              aria-pressed={Boolean(rowRevealedUrl)}
                              aria-label={
                                rowRevealedUrl
                                  ? settingsIntegrationsText("hideChannelUrl", {
                                      label: channel.label,
                                    })
                                  : settingsIntegrationsText("revealChannelUrl", {
                                      label: channel.label,
                                    })
                              }
                              onClick={() => {
                                void toggleRevealChannelRow(channel.channelId);
                              }}
                            >
                              {rowRevealedUrl ? (
                                <svg
                                  viewBox="0 0 24 24"
                                  fill="none"
                                  stroke="currentColor"
                                  stroke-width="2"
                                  stroke-linecap="round"
                                  stroke-linejoin="round"
                                  aria-hidden="true"
                                >
                                  <path d="M17.94 17.94A10.07 10.07 0 0 1 12 20c-7 0-11-8-11-8a18.45 18.45 0 0 1 5.06-5.94" />
                                  <path d="M9.9 4.24A9.12 9.12 0 0 1 12 4c7 0 11 8 11 8a18.5 18.5 0 0 1-2.16 3.19" />
                                  <line x1="1" y1="1" x2="23" y2="23" />
                                </svg>
                              ) : (
                                <svg
                                  viewBox="0 0 24 24"
                                  fill="none"
                                  stroke="currentColor"
                                  stroke-width="2"
                                  stroke-linecap="round"
                                  stroke-linejoin="round"
                                  aria-hidden="true"
                                >
                                  <path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
                                  <circle cx="12" cy="12" r="3" />
                                </svg>
                              )}
                            </button>
                            {canManage && bindingSaved.channels.length > 1 ? (
                              <button
                                type="button"
                                class="settings-teams-workflow-icon-btn"
                                disabled={testing || revealing || savingPreferences}
                                aria-label={settingsIntegrationsText("removeChannel", {
                                  label: channel.label,
                                })}
                                onClick={() => removeSavedChannel(channel.channelId)}
                              >
                                <svg
                                  viewBox="0 0 24 24"
                                  fill="none"
                                  stroke="currentColor"
                                  stroke-width="2"
                                  stroke-linecap="round"
                                  stroke-linejoin="round"
                                  aria-hidden="true"
                                >
                                  <polyline points="3 6 5 6 21 6" />
                                  <path d="M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                                  <path d="M10 11v6" />
                                  <path d="M14 11v6" />
                                </svg>
                              </button>
                            ) : null}
                          </div>
                        </div>
                      );
                    })}
                  </div>
                ) : null}
              </div>
            ) : null}
            {bindingSaved ? (
              <>
                <p class="settings-teams-workflow-binding-state">
                  <StatusPill kind="success" label={settingsIntegrationsText("bindingSavedPill")} />
                  <small class="muted">
                    {bindingSaved.savedAt
                      ? settingsIntegrationsText("bindingSavedDetail", {
                          version: bindingSaved.bindingVersion,
                          time: formatConsoleTimestamp(bindingSaved.savedAt),
                        })
                      : settingsIntegrationsText("bindingSavedVersionOnly", {
                          version: bindingSaved.bindingVersion,
                        })}
                  </small>
                </p>
                <p class="settings-teams-workflow-binding-state">
                  <small class="muted">
                    {settingsIntegrationsText("bindingIdentifier", {
                      identifier: bindingSaved.endpointIdentifier,
                    })}
                  </small>
                </p>
              </>
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
              time: formatConsoleTimestamp(result.testedAt),
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
              time: formatConsoleTimestamp(result.testedAt),
            })}
          </small>
        </div>
      ) : null}
    </div>
  );
}

export function EmailTemplatePreviewPanel({ template }: { readonly template: EmailTemplatePreview }) {
  const [plainText, setPlainText] = useState(false);
  return (
    <div class="settings-email-template">
      <div class="settings-email-template-head">
        <span>
          <small>{t("settings.emailTemplateSubject")}</small>
          <strong>{template.subject}</strong>
        </span>
        <StatusPill kind="neutral" label={t("settings.emailTemplateSynthetic")} />
      </div>
      <div class="settings-actions" role="group" aria-label={t("settings.emailTemplatePreviewTitle")}>
        <button type="button" class="secondary" aria-pressed={!plainText} onClick={() => setPlainText(false)}>
          {settingsIntegrationsText("emailHtml")}
        </button>
        <button type="button" class="secondary" aria-pressed={plainText} onClick={() => setPlainText(true)}>
          {settingsIntegrationsText("emailPlain")}
        </button>
      </div>
      {plainText ? <pre class="settings-email-template-plain">{template.plainText}</pre> : <iframe
        class="settings-email-template-frame"
        title={t("settings.emailTemplatePreviewTitle")}
        srcDoc={template.html}
        sandbox=""
        referrerPolicy="no-referrer"
      />}
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
      <div class="settings-integration-status">
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
        <ForecastHistorySourceDetails details={integration.forecastHistory} />
      </div>
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
    case "operational-evidence.agent-discussion-read":
      return settingsIntegrationsText("opEvidence.agent-discussion-read.label");
    case "operational-evidence.case-history-read":
      return settingsIntegrationsText("opEvidence.case-history-read.label");
    case "operational-evidence.current-case-reuse":
      return settingsIntegrationsText("opEvidence.current-case-reuse.label");
    case "operational-evidence.forecast-context":
      return settingsIntegrationsText("opEvidence.forecast-context.label");
    case "operational-evidence.forecast-history-actions":
      return settingsIntegrationsText("opEvidence.forecast-history-actions.label");
    case "operational-evidence.forecast-history-changes":
      return settingsIntegrationsText("opEvidence.forecast-history-changes.label");
    case "operational-evidence.forecast-history-excluded_windows":
      return settingsIntegrationsText("opEvidence.forecast-history-excluded_windows.label");
    case "operational-evidence.forecast-history-resource_lifecycle":
      return settingsIntegrationsText("opEvidence.forecast-history-resource_lifecycle.label");
    case "operational-evidence.operational-test-context":
      return settingsIntegrationsText("opEvidence.operational-test-context.label");
    case "operational-evidence.operational-test-observation":
      return settingsIntegrationsText("opEvidence.operational-test-observation.label");
    case "operational-evidence.operator-test-context-command":
      return settingsIntegrationsText("opEvidence.operator-test-context-command.label");
    case "operational-evidence.test-context-transition":
      return settingsIntegrationsText("opEvidence.test-context-transition.label");
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
    case "operational-evidence.agent-discussion-read":
      return settingsIntegrationsText("opEvidence.agent-discussion-read.hint");
    case "operational-evidence.case-history-read":
      return settingsIntegrationsText("opEvidence.case-history-read.hint");
    case "operational-evidence.current-case-reuse":
      return settingsIntegrationsText("opEvidence.current-case-reuse.hint");
    case "operational-evidence.forecast-context":
      return settingsIntegrationsText("opEvidence.forecast-context.hint");
    case "operational-evidence.forecast-history-actions":
      return settingsIntegrationsText("opEvidence.forecast-history-actions.hint");
    case "operational-evidence.forecast-history-changes":
      return settingsIntegrationsText("opEvidence.forecast-history-changes.hint");
    case "operational-evidence.forecast-history-excluded_windows":
      return settingsIntegrationsText("opEvidence.forecast-history-excluded_windows.hint");
    case "operational-evidence.forecast-history-resource_lifecycle":
      return settingsIntegrationsText("opEvidence.forecast-history-resource_lifecycle.hint");
    case "operational-evidence.operational-test-context":
      return settingsIntegrationsText("opEvidence.operational-test-context.hint");
    case "operational-evidence.operational-test-observation":
      return settingsIntegrationsText("opEvidence.operational-test-observation.hint");
    case "operational-evidence.operator-test-context-command":
      return settingsIntegrationsText("opEvidence.operator-test-context-command.hint");
    case "operational-evidence.test-context-transition":
      return settingsIntegrationsText("opEvidence.test-context-transition.hint");
    default: return t(`settings.integrations.${key}.hint`);
  }
}

function integrationSource(source: RuntimeIntegrationView["source"]): string {
  if (source === "core-control-plane") return settingsIntegrationsText("sourceCore");
  if (source === "operator-service") return settingsIntegrationsText("sourceOperator");
  return settingsIntegrationsText("sourceUnspecified");
}
