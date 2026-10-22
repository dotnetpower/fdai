import { useEffect, useState } from "preact/hooks";
import { OperatorApiError } from "../api";
import type { OperatorApiClient } from "../api";
import {
  stewardshipActivationIdempotencyKey,
  type StewardshipCandidate,
} from "../api-stewardship";
import { t } from "../i18n";

type CandidateClient = Pick<OperatorApiClient, "stewardshipCandidates" | "activateStewardshipCandidate">;
export type ActivationFeedback = "queued" | "forbidden" | "failed";

/** Queue one digest-bound activation and classify the result for the Owner. */
export async function submitActivation(
  client: Pick<OperatorApiClient, "activateStewardshipCandidate">,
  candidate: StewardshipCandidate,
  nonce: string,
): Promise<ActivationFeedback> {
  const body = { candidate_id: candidate.candidate_id, candidate_digest: candidate.candidate_digest };
  try {
    await client.activateStewardshipCandidate(body, stewardshipActivationIdempotencyKey(body, nonce));
    return "queued";
  } catch (error) {
    return error instanceof OperatorApiError && error.status === 403 ? "forbidden" : "failed";
  }
}

/** Owner-only list of Console ownership revision candidates with a digest-bound activation. */
export function StewardshipCandidates({ client }: { readonly client: CandidateClient }) {
  const [items, setItems] = useState<readonly StewardshipCandidate[] | null>(null);
  const [error, setError] = useState(false);
  const [feedback, setFeedback] = useState<Readonly<Record<string, ActivationFeedback>>>({});
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    client.stewardshipCandidates().then(
      (next) => { if (!cancelled) setItems(next); },
      () => { if (!cancelled) setError(true); },
    );
    return () => { cancelled = true; };
  }, [client]);

  if (error) {
    return <section class="state-block state-unavailable" role="status"><p>{t("handover.candidates.unavailable")}</p></section>;
  }
  if (items === null) return <p role="status">{t("handover.candidates.loading")}</p>;

  async function activate(candidate: StewardshipCandidate) {
    setBusy(candidate.candidate_id);
    const result = await submitActivation(client, candidate, crypto.randomUUID());
    setFeedback((current) => ({ ...current, [candidate.candidate_id]: result }));
    setBusy(null);
  }

  return (
    <section class="panel stewardship-candidates" aria-labelledby="stewardship-candidates-title">
      <h2 id="stewardship-candidates-title">{t("handover.candidates.title")}</h2>
      <p>{t("handover.candidates.hint")}</p>
      {items.length === 0 ? <p>{t("handover.candidates.empty")}</p> : null}
      <ul class="stewardship-candidate-list">
        {items.map((candidate) => (
          <li key={candidate.candidate_id}>
            <strong>{candidate.title}</strong>
            <p>{candidate.body}</p>
            <dl>
              <dt>{t("handover.candidates.digest")}</dt>
              <dd><code>{candidate.candidate_digest}</code></dd>
              <dt>{t("handover.candidates.state")}</dt>
              <dd>{candidate.state === "open" ? t("handover.candidates.stateOpen") : t("handover.candidates.stateActivated")}</dd>
            </dl>
            <details>
              <summary>{t("handover.candidates.review")}</summary>
              <pre>{candidate.yaml}</pre>
            </details>
            {candidate.state === "open" ? (
              <button
                type="button"
                class="btn primary"
                disabled={busy !== null}
                onClick={() => { void activate(candidate); }}
              >
                {busy === candidate.candidate_id ? t("handover.candidates.activating") : t("handover.candidates.activate")}
              </button>
            ) : null}
            {feedback[candidate.candidate_id] === "queued" ? <p role="status">{t("handover.candidates.queued")}</p> : null}
            {feedback[candidate.candidate_id] === "forbidden" ? <p role="alert">{t("handover.candidates.forbidden")}</p> : null}
            {feedback[candidate.candidate_id] === "failed" ? <p role="alert">{t("handover.candidates.failed")}</p> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
