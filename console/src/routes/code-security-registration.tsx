import { useState } from "preact/hooks";
import { OperatorApiError } from "../api";
import type { OperatorApiClient, CodeSecurityRepositoryChange } from "../api";
import { SelectField, TextInput } from "../components/form-controls";
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
      url.hostname !== "github.com"
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
          <div class="code-security-register-primary" onFocusOut={normalizeLocationField}>
            <TextInput
              className="code-security-register-location"
              label={t("codeSecurity.register.location")}
              value={location}
              required
              disabled={submitting}
              placeholder={t("codeSecurity.register.locationPlaceholder")}
              autoComplete="off"
              hint={t("codeSecurity.register.locationHint")}
              onInput={(value) => updateLocation(value)}
            />
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
              <TextInput
                className="code-security-register-alias"
                label={t("codeSecurity.register.alias")}
                value={alias}
                required
                disabled={submitting}
                autoComplete="off"
                hint={t("codeSecurity.register.aliasHint")}
                onInput={(value) => {
                  setAliasEdited(true);
                  setAlias(value);
                }}
              />
              <TextInput
                className="code-security-register-ref"
                label={t("codeSecurity.register.defaultRef")}
                value={ref}
                disabled={submitting}
                placeholder="HEAD"
                autoComplete="off"
                hint={t("codeSecurity.register.defaultRefHint")}
                onInput={(value) => setRef(value)}
              />
              <SelectField
                className="code-security-register-exposure"
                label={t("codeSecurity.register.exposure")}
                ariaLabel={t("codeSecurity.register.exposure")}
                value={exposure}
                disabled={submitting}
                options={EXPOSURES.map((item) => ({
                  value: item,
                  label: t(`codeSecurity.exposure.${item}`),
                }))}
                onChange={(value) => setExposure(value as (typeof EXPOSURES)[number])}
              />
            </div>
          </details>
          <FeedbackLine feedback={feedback} />
        </form>
      </div>
    </details>
  );
}
