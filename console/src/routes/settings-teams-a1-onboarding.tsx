import type { AuthContext } from "../auth";
import { ExternalLink } from "../components/ui";
import { settingsIntegrationsText } from "./settings-integrations.i18n";
import { requestTeamsA1Plan } from "./settings-runtime.command";
import type { TeamsA1OnboardingView } from "./settings-runtime.model";
import { useEffect, useRef, useState } from "preact/hooks";

const AZURE_PORTAL_URL = "https://portal.azure.com/";
const TEAMS_ADMIN_URL = "https://admin.teams.microsoft.com/policies/manage-apps";

/**
 * Explains the split between protected FDAI automation and provider-hosted
 * human approval without collecting credentials in the Console.
 */
export function TeamsA1OnboardingGuide({
  auth,
  operatorApiBaseUrl,
  onboarding,
}: {
  readonly auth: AuthContext;
  readonly operatorApiBaseUrl: string;
  readonly onboarding: TeamsA1OnboardingView;
}) {
  const [state, setState] = useState(onboarding.state);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestKey = useRef(`teams-a1-plan-${globalThis.crypto.randomUUID()}`);
  const generation = useRef(0);
  const environment = onboarding.environment;
  useEffect(() => {
    generation.current += 1;
    setState(onboarding.state);
    setSubmitting(false);
    setError(null);
    requestKey.current = `teams-a1-plan-${globalThis.crypto.randomUUID()}`;
    return () => { generation.current += 1; };
  }, [onboarding.state, onboarding.environment, onboarding.revision, auth, operatorApiBaseUrl]);
  const canRequest = onboarding.canManage
    && state !== "plan-requested"
    && isDeployEnvironment(environment)
    && !submitting;
  const requestPlan = async () => {
    if (!canRequest || !isDeployEnvironment(environment)) return;
    const candidate = generation.current;
    setSubmitting(true);
    setError(null);
    try {
      await requestTeamsA1Plan(auth, operatorApiBaseUrl, environment, requestKey.current);
      if (generation.current !== candidate) return;
      setState("plan-requested");
    } catch (reason) {
      if (generation.current !== candidate) return;
      setError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      if (generation.current === candidate) setSubmitting(false);
    }
  };
  return (
    <section
      class="settings-teams-a1-onboarding"
      aria-labelledby="settings-teams-a1-onboarding-title"
    >
      <div>
        <h5 id="settings-teams-a1-onboarding-title">
          {settingsIntegrationsText("a1OnboardingTitle")}
        </h5>
        <p>{settingsIntegrationsText("a1OnboardingDescription")}</p>
      </div>
      <div class="settings-teams-a1-onboarding-columns">
        <div>
          <strong>{settingsIntegrationsText("a1AutomatedTitle")}</strong>
          <ul>
            <li>{settingsIntegrationsText("a1AutomatedBot")}</li>
            <li>{settingsIntegrationsText("a1AutomatedSso")}</li>
            <li>{settingsIntegrationsText("a1AutomatedDeployment")}</li>
          </ul>
        </div>
        <div>
          <strong>{settingsIntegrationsText("a1HumanTitle")}</strong>
          <ol>
            <li>{settingsIntegrationsText("a1HumanOauth")}</li>
            <li>{settingsIntegrationsText("a1HumanInstall")}</li>
            <li>{settingsIntegrationsText("a1HumanApproval")}</li>
          </ol>
        </div>
      </div>
      <p class="settings-teams-a1-onboarding-note">
        {settingsIntegrationsText("a1SecretBoundary")}
      </p>
      <div class="settings-teams-a1-onboarding-request">
        <button
          type="button"
          class="btn primary"
          disabled={!canRequest}
          onClick={() => { void requestPlan(); }}
        >
          {submitting
            ? settingsIntegrationsText("a1Requesting")
            : state === "plan-requested"
              ? settingsIntegrationsText("a1Requested")
              : settingsIntegrationsText("a1Request")}
        </button>
        <span>{settingsIntegrationsText(
          state === "plan-requested" ? "a1RequestedHint" : "a1RequestHint",
        )}</span>
      </div>
      {error ? <div class="error" role="alert">{error}</div> : null}
      <div class="settings-teams-a1-onboarding-actions">
        <ExternalLink href={AZURE_PORTAL_URL}>
          {settingsIntegrationsText("a1OpenAzure")}
        </ExternalLink>
        <ExternalLink href={TEAMS_ADMIN_URL}>
          {settingsIntegrationsText("a1OpenTeamsAdmin")}
        </ExternalLink>
      </div>
    </section>
  );
}

function isDeployEnvironment(
  value: TeamsA1OnboardingView["environment"],
): value is "dev" | "staging" | "prod" {
  return value !== "unspecified";
}
