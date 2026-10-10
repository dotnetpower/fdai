import { useState } from "preact/hooks";
import { OperatorApiError } from "../api";
import type { OperatorApiClient, CodeSecurityRepositoryChange } from "../api";
import { t } from "./i18n/code-security";

const ALIAS = /^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$/;
const LOCATION = /^[A-Za-z0-9](?:[A-Za-z0-9-]{0,38})\/[A-Za-z0-9._-]{1,100}$/;
const REF = /^[A-Za-z0-9][A-Za-z0-9._/-]{0,199}$/;
const EXPOSURES = ["unknown", "exposed", "internal", "not_deployed"] as const;

export type RegistrationFeedback =
  | { readonly kind: "queued" | "forbidden" | "failed"; readonly detail?: string }
  | null;

type ChangeClient = Pick<OperatorApiClient, "changeCodeSecurityRepository">;

/** A fresh key per deliberate submission; retries of one submission reuse it. */
export function repositoryChangeIdempotencyKey(change: CodeSecurityRepositoryChange, nonce: string): string {
  return `code-security-repository:${change.action}:${change.repository_alias}:${nonce}`;
}

export function normalizeGitHubLocation(value: string): string {
  const trimmed = value.trim();
  if (!/^https:\/\//i.test(trimmed)) return trimmed;
  try {
    const url = new URL(trimmed);
    const parts = url.pathname.split("/").filter(Boolean);
    if (
      url.hostname.toLowerCase() !== "github.com"
      || url.username !== ""
      || url.password !== ""
      || url.port !== ""
      || url.search !== ""
      || url.hash !== ""
      || parts.length !== 2
    ) {
      return trimmed;
    }
    const repository = parts[1]!.endsWith(".git") ? parts[1]!.slice(0, -4) : parts[1]!;
    return `${parts[0]}/${repository}`;
  } catch {
    return trimmed;
  }
}

export function repositoryAliasSuggestion(location: string): string {
  const repository = normalizeGitHubLocation(location).split("/")[1] ?? "";
  const candidate = repository.slice(0, 64);
  return ALIAS.test(candidate) ? candidate : "";
}

export function registrationInputValid(alias: string, location: string, ref: string): boolean {
  return ALIAS.test(alias) && LOCATION.test(location) && (ref === "" || (REF.test(ref) && !ref.includes("..")));
}

/** Submit one Owner registration change and classify the result for the operator. */
export async function submitRepositoryChange(
  client: ChangeClient,
  change: CodeSecurityRepositoryChange,
): Promise<RegistrationFeedback> {
  try {
    await client.changeCodeSecurityRepository(change, repositoryChangeIdempotencyKey(change, crypto.randomUUID()));
    return { kind: "queued" };
  } catch (error) {
    if (error instanceof OperatorApiError && error.status === 403) return { kind: "forbidden" };
    return { kind: "failed", detail: error instanceof Error ? error.message : String(error) };
  }
}

export function FeedbackLine({ feedback }: { readonly feedback: RegistrationFeedback }) {
  if (feedback === null) return null;
  return (
    <p
      class={feedback.kind === "queued" ? "muted code-security-scan-feedback" : "alert error code-security-scan-feedback"}
      role="status"
    >
      {t(`codeSecurity.register.${feedback.kind}`)}
      {feedback.detail ? ` ${feedback.detail}` : ""}
    </p>
  );
}

export function RepositoryRegistrationForm({
  client,
  onQueued,
  defaultOpen = false,
}: {
  readonly client: ChangeClient;
  readonly onQueued: () => void;
  readonly defaultOpen?: boolean;
}) {
  const [alias, setAlias] = useState("");
  const [location, setLocation] = useState("");
  const [ref, setRef] = useState("");
  const [exposure, setExposure] = useState<(typeof EXPOSURES)[number]>("unknown");
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<RegistrationFeedback>(null);
  const [expanded, setExpanded] = useState(defaultOpen);
  const [aliasEdited, setAliasEdited] = useState(false);
  const normalizedLocation = normalizeGitHubLocation(location);
  const trimmedRef = ref.trim();
  const valid = registrationInputValid(alias.trim(), normalizedLocation, trimmedRef);
  const updateLocation = (next: string) => {
    setLocation(next);
    if (!aliasEdited) setAlias(repositoryAliasSuggestion(next));
  };
  const normalizeLocationField = () => {
    if (normalizedLocation === location) return;
    setLocation(normalizedLocation);
    if (!aliasEdited) setAlias(repositoryAliasSuggestion(normalizedLocation));
  };
  const submit = async (event: Event) => {
    event.preventDefault();
    if (!valid || submitting) return;
    setSubmitting(true);
    setFeedback(null);
    const result = await submitRepositoryChange(client, {
      action: "register",
      repository_alias: alias.trim(),
      location: normalizedLocation,
      exposure,
      ...(trimmedRef ? { default_ref: trimmedRef } : {}),
    });
    setFeedback(result);
    setSubmitting(false);
    if (result?.kind === "queued") {
      setAlias("");
      setLocation("");
      setRef("");
      setAliasEdited(false);
      onQueued();
    }
  };
  return (
    <details
      class="code-security-register"
      open={expanded}
      onToggle={(event) => setExpanded(event.currentTarget.open)}
    >
      <summary>
        <span>{t("codeSecurity.register.title")}</span>
      </summary>
      <div class="code-security-register-content">
        <ol class="code-security-register-journey" aria-label={t("codeSecurity.register.workflowLabel")}>
          <li aria-current="step">
            <span aria-hidden="true">1</span>
            <strong>{t("codeSecurity.register.stepRegister")}</strong>
          </li>
          <li>
            <span aria-hidden="true">2</span>
            <strong>{t("codeSecurity.register.stepScan")}</strong>
          </li>
          <li>
            <span aria-hidden="true">3</span>
            <strong>{t("codeSecurity.register.stepReview")}</strong>
          </li>
        </ol>
        <p id="code-security-register-description">{t("codeSecurity.register.body")}</p>
        <form
          class="code-security-register-form"
          aria-describedby="code-security-register-description"
          onSubmit={submit}
        >
          <div class="code-security-register-primary">
            <label class="cs-control-field code-security-register-location">
              <span class="cs-control-label">{t("codeSecurity.register.location")}</span>
              <input
                class="cs-control-input"
                value={location}
                required
                disabled={submitting}
                aria-label={t("codeSecurity.register.location")}
                placeholder={t("codeSecurity.register.locationPlaceholder")}
                autoCapitalize="none"
                autoComplete="off"
                spellcheck={false}
                aria-describedby="code-security-location-hint"
                onBlur={normalizeLocationField}
                onInput={(event) => updateLocation((event.currentTarget as HTMLInputElement).value)}
              />
            </label>
            <small id="code-security-location-hint" class="cs-control-help code-security-location-hint">
              {t("codeSecurity.register.locationHint")}
            </small>
            <button type="submit" class="btn primary code-security-register-submit" disabled={!valid || submitting}>
              {submitting ? t("codeSecurity.scan.submitting") : t("codeSecurity.register.submit")}
            </button>
          </div>
          <details class="code-security-register-settings">
            <summary>
              <span>{t("codeSecurity.register.settingsTitle")}</span>
              <small>{t("codeSecurity.register.settingsSummary")}</small>
            </summary>
            <div class="code-security-register-settings-grid">
              <label class="cs-control-field code-security-register-alias">
                <span class="cs-control-label">{t("codeSecurity.register.alias")}</span>
                <input
                  class="cs-control-input"
                  value={alias}
                  required
                  disabled={submitting}
                  aria-label={t("codeSecurity.register.alias")}
                  autoComplete="off"
                  aria-describedby="code-security-alias-hint"
                  onInput={(event) => {
                    setAliasEdited(true);
                    setAlias((event.currentTarget as HTMLInputElement).value);
                  }}
                />
                <small id="code-security-alias-hint" class="cs-control-help">
                  {t("codeSecurity.register.aliasHint")}
                </small>
              </label>
              <label class="cs-control-field code-security-register-ref">
                <span class="cs-control-label">{t("codeSecurity.register.defaultRef")}</span>
                <input
                  class="cs-control-input"
                  value={ref}
                  disabled={submitting}
                  aria-label={t("codeSecurity.register.defaultRef")}
                  placeholder="HEAD"
                  autoCapitalize="none"
                  autoComplete="off"
                  spellcheck={false}
                  aria-describedby="code-security-default-ref-hint"
                  onInput={(event) => setRef((event.currentTarget as HTMLInputElement).value)}
                />
                <small id="code-security-default-ref-hint" class="cs-control-help">
                  {t("codeSecurity.register.defaultRefHint")}
                </small>
              </label>
              <label class="cs-control-field code-security-register-exposure">
                <span class="cs-control-label">{t("codeSecurity.register.exposure")}</span>
                <select
                  class="cs-control-select"
                  aria-label={t("codeSecurity.register.exposure")}
                  value={exposure}
                  disabled={submitting}
                  onChange={(event) => setExposure(event.currentTarget.value as (typeof EXPOSURES)[number])}
                >
                  {EXPOSURES.map((item) => <option key={item} value={item}>{t(`codeSecurity.exposure.${item}`)}</option>)}
                </select>
              </label>
            </div>
          </details>
          <FeedbackLine feedback={feedback} />
        </form>
      </div>
    </details>
  );
}
