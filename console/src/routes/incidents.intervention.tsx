import { useEffect, useRef, useState } from "preact/hooks";
import type { OperatorApiClient } from "../api";
import type {
  IncidentInterventionAction,
  IncidentInterventionBody,
  IncidentInterventionReceipt,
} from "../api-operations-client";
import type { IncidentSummary } from "../types";
import { t } from "./i18n/evidence";

type Duration = NonNullable<IncidentInterventionBody["duration"]>;
type Step = "edit" | "review" | "queued";

const ACTIONS: readonly IncidentInterventionAction[] = [
  "operator_guidance",
  "close_as_development",
  "create_development_exception",
  "revoke_development_exception",
];
const DURATIONS: readonly Duration[] = ["one_day", "one_week", "one_month", "until_revoked"];
const UUID_PATTERN = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;

interface Props {
  readonly client: OperatorApiClient;
  readonly incident: IncidentSummary;
}

export function IncidentIntervention({ client, incident }: Props) {
  const dialog = useRef<HTMLDialogElement>(null);
  const [open, setOpen] = useState(false);
  const [step, setStep] = useState<Step>("edit");
  const [action, setAction] = useState<IncidentInterventionAction>("operator_guidance");
  const [comment, setComment] = useState("");
  const [duration, setDuration] = useState<Duration>("one_week");
  const [exceptionId, setExceptionId] = useState("");
  const [receipt, setReceipt] = useState<IncidentInterventionReceipt | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const idempotencyKey = useRef("");
  const available = incident.incident_id !== null
    && incident.lifecycle_state !== null
    && incident.target_ref !== null;

  useEffect(() => {
    const node = dialog.current;
    if (node === null) return;
    if (open && !node.open) node.showModal();
    if (!open && node.open) node.close();
  }, [open]);

  const close = () => {
    setOpen(false);
    setStep("edit");
    setError(null);
    setReceipt(null);
    setSubmitting(false);
    idempotencyKey.current = "";
  };

  const body = (): IncidentInterventionBody | null => {
    if (!available || incident.incident_id === null || incident.lifecycle_state === null) return null;
    const base = {
      action,
      incident_id: incident.incident_id,
      correlation_id: incident.correlation_id,
      expected_state: incident.lifecycle_state,
      comment: comment.trim(),
    } as const;
    if (action === "create_development_exception") return { ...base, duration };
    if (action === "revoke_development_exception") {
      return { ...base, exception_id: exceptionId.trim() };
    }
    return base;
  };

  const validation = (() => {
    if (!comment.trim()) return t("incidents.intervention.validation.comment");
    if (comment.trim().length > 500) return t("incidents.intervention.validation.commentLength");
    if (action === "revoke_development_exception" && !UUID_PATTERN.test(exceptionId.trim())) {
      return t("incidents.intervention.validation.exceptionId");
    }
    return null;
  })();

  const submit = async () => {
    const request = body();
    if (request === null || validation !== null || submitting) return;
    if (!idempotencyKey.current) idempotencyKey.current = globalThis.crypto.randomUUID();
    setSubmitting(true);
    setError(null);
    try {
      const accepted = await client.interveneIncident(request, idempotencyKey.current);
      setReceipt(accepted);
      setStep("queued");
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : String(failure));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <button
        type="button"
        class="incident-intervene-button"
        disabled={!available}
        aria-describedby={!available ? "incident-intervention-unavailable" : undefined}
        onClick={() => {
          setOpen(true);
          setStep("edit");
          setError(null);
        }}
      >
        {t("incidents.intervention.open")}
      </button>
      {!available ? (
        <span id="incident-intervention-unavailable" class="visually-hidden">
          {t("incidents.intervention.unavailable")}
        </span>
      ) : null}
      <dialog
        ref={dialog}
        class="incident-intervention-dialog"
        aria-labelledby="incident-intervention-title"
        onClose={close}
        onCancel={(event) => {
          event.preventDefault();
          close();
        }}
      >
        <div class="incident-intervention-shell">
          <header>
            <div>
              <span>{t("incidents.intervention.eyebrow")}</span>
              <h2 id="incident-intervention-title">{t("incidents.intervention.title")}</h2>
            </div>
            <button type="button" class="icon-button" aria-label={t("incidents.intervention.close")} onClick={close}>×</button>
          </header>
          <div class="incident-intervention-target">
            <strong>{incident.incident_number ?? incident.incident_id}</strong>
            <span>{incident.lifecycle_state}</span>
          </div>
          {step === "edit" ? (
            <div class="incident-intervention-form">
              <label>
                <span>{t("incidents.intervention.actionLabel")}</span>
                <select value={action} onChange={(event) => {
                  setAction(event.currentTarget.value as IncidentInterventionAction);
                  setError(null);
                  idempotencyKey.current = "";
                }}>
                  {ACTIONS.map((value) => (
                    <option key={value} value={value}>{t(`incidents.intervention.action.${value}`)}</option>
                  ))}
                </select>
              </label>
              <p>{t(`incidents.intervention.help.${action}`)}</p>
              {action === "create_development_exception" ? (
                <label>
                  <span>{t("incidents.intervention.durationLabel")}</span>
                  <select value={duration} onChange={(event) => {
                    setDuration(event.currentTarget.value as Duration);
                    setError(null);
                    idempotencyKey.current = "";
                  }}>
                    {DURATIONS.map((value) => (
                      <option key={value} value={value}>{t(`incidents.intervention.duration.${value}`)}</option>
                    ))}
                  </select>
                </label>
              ) : null}
              {action === "revoke_development_exception" ? (
                <label>
                  <span>{t("incidents.intervention.exceptionId")}</span>
                  <input value={exceptionId} maxLength={36} onInput={(event) => {
                    setExceptionId(event.currentTarget.value);
                    setError(null);
                    idempotencyKey.current = "";
                  }} />
                </label>
              ) : null}
              <label>
                <span>{t("incidents.intervention.comment")}</span>
                <textarea
                  rows={5}
                  maxLength={500}
                  value={comment}
                  onInput={(event) => {
                    setComment(event.currentTarget.value);
                    setError(null);
                    idempotencyKey.current = "";
                  }}
                />
                <small>{t("incidents.intervention.commentCount", { count: comment.length })}</small>
              </label>
              {validation !== null && comment.length > 0 ? <p class="state-error-text">{validation}</p> : null}
            </div>
          ) : step === "review" ? (
            <div class="incident-intervention-review">
              <p>{t("incidents.intervention.reviewBody")}</p>
              <dl>
                <div><dt>{t("incidents.intervention.actionLabel")}</dt><dd>{t(`incidents.intervention.action.${action}`)}</dd></div>
                <div><dt>{t("incidents.intervention.expectedState")}</dt><dd>{incident.lifecycle_state}</dd></div>
                {action === "create_development_exception" ? <div><dt>{t("incidents.intervention.durationLabel")}</dt><dd>{t(`incidents.intervention.duration.${duration}`)}</dd></div> : null}
                <div><dt>{t("incidents.intervention.comment")}</dt><dd>{comment.trim()}</dd></div>
              </dl>
              <aside>{t("incidents.intervention.authorityNotice")}</aside>
            </div>
          ) : (
            <div class="incident-intervention-queued" role="status">
              <strong>{t("incidents.intervention.queuedTitle")}</strong>
              <p>{t("incidents.intervention.queuedBody")}</p>
              <code>{receipt?.request_id}</code>
            </div>
          )}
          {error !== null ? <p class="state-error-text" role="alert">{error}</p> : null}
          <footer>
            {step === "edit" ? (
              <>
                <button type="button" onClick={close}>{t("incidents.intervention.cancel")}</button>
                <button type="button" class="primary" disabled={validation !== null} onClick={() => setStep("review")}>{t("incidents.intervention.review")}</button>
              </>
            ) : step === "review" ? (
              <>
                <button type="button" onClick={() => {
                  setStep("edit");
                  setError(null);
                }}>{t("incidents.intervention.back")}</button>
                <button type="button" class="primary" disabled={submitting} onClick={() => void submit()}>{submitting ? t("incidents.intervention.submitting") : t("incidents.intervention.confirm")}</button>
              </>
            ) : <button type="button" class="primary" onClick={close}>{t("incidents.intervention.done")}</button>}
          </footer>
        </div>
      </dialog>
    </>
  );
}
