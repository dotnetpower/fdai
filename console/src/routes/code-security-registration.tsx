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
}: {
  readonly client: ChangeClient;
  readonly onQueued: () => void;
}) {
  const [alias, setAlias] = useState("");
  const [location, setLocation] = useState("");
  const [ref, setRef] = useState("");
  const [exposure, setExposure] = useState<(typeof EXPOSURES)[number]>("unknown");
  const [submitting, setSubmitting] = useState(false);
  const [feedback, setFeedback] = useState<RegistrationFeedback>(null);
  const trimmedRef = ref.trim();
  const valid = registrationInputValid(alias.trim(), location.trim(), trimmedRef);
  const submit = async (event: Event) => {
    event.preventDefault();
    if (!valid || submitting) return;
    setSubmitting(true);
    setFeedback(null);
    const result = await submitRepositoryChange(client, {
      action: "register",
      repository_alias: alias.trim(),
      location: location.trim(),
      exposure,
      ...(trimmedRef ? { default_ref: trimmedRef } : {}),
    });
    setFeedback(result);
    setSubmitting(false);
    if (result?.kind === "queued") {
      setAlias("");
      setLocation("");
      setRef("");
      onQueued();
    }
  };
  return (
    <details class="code-security-register">
      <summary>{t("codeSecurity.register.title")}</summary>
      <p class="muted">{t("codeSecurity.register.body")}</p>
      <form class="code-security-register-form" onSubmit={submit}>
        <label>
          <span>{t("codeSecurity.register.alias")}</span>
          <input value={alias} disabled={submitting} onInput={(event) => setAlias((event.currentTarget as HTMLInputElement).value)} />
        </label>
        <label>
          <span>{t("codeSecurity.register.location")}</span>
          <input
            value={location}
            disabled={submitting}
            placeholder="owner/repository"
            onInput={(event) => setLocation((event.currentTarget as HTMLInputElement).value)}
          />
        </label>
        <label>
          <span>{t("codeSecurity.register.defaultRef")}</span>
          <input
            value={ref}
            disabled={submitting}
            placeholder="main"
            onInput={(event) => setRef((event.currentTarget as HTMLInputElement).value)}
          />
        </label>
        <label>
          <span>{t("codeSecurity.register.exposure")}</span>
          <select
            aria-label={t("codeSecurity.register.exposure")}
            value={exposure}
            disabled={submitting}
            onChange={(event) => setExposure(event.currentTarget.value as (typeof EXPOSURES)[number])}
          >
            {EXPOSURES.map((item) => <option key={item} value={item}>{t(`codeSecurity.exposure.${item}`)}</option>)}
          </select>
        </label>
        <button type="submit" class="btn" disabled={!valid || submitting}>
          {submitting ? t("codeSecurity.scan.submitting") : t("codeSecurity.register.submit")}
        </button>
        <FeedbackLine feedback={feedback} />
      </form>
    </details>
  );
}
