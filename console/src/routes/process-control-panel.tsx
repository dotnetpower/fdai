import { useState } from "preact/hooks";
import { StatusPill, UnavailableState } from "../components/ui";
import {
  displayValue,
  processTone,
  type ProcessControlProjection,
  type ProcessTransition,
} from "./processes.model";
import { requestProcessTransition } from "./processes.transitions";
import { t } from "./i18n/processes";

export function ProcessControlPanel({
  processId,
  control,
}: {
  readonly processId: string;
  readonly control: ProcessControlProjection;
}) {
  const [pending, setPending] = useState<string | null>(null);
  const [accepted, setAccepted] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!control.available || control.step === null) {
    return (
      <section class="process-control-panel" aria-labelledby="process-control-title">
        <h3 id="process-control-title">{t("processesView.controlTitle")}</h3>
        <UnavailableState message={control.reason ?? t("processesView.controlUnavailable")} />
      </section>
    );
  }
  const request = async (transition: ProcessTransition): Promise<void> => {
    if (
      transition.requires_confirmation
      && !window.confirm(t("processesView.transitionConfirm", {
        transition: t(`processesView.transition.${transition.id}`),
      }))
    ) return;
    setPending(transition.id);
    setAccepted(null);
    setError(null);
    try {
      const receipt = await requestProcessTransition(processId, transition);
      setAccepted(receipt.proposalId);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setPending(null);
    }
  };
  return (
    <section class="process-control-panel" aria-labelledby="process-control-title">
      <div class="process-section-heading">
        <div>
          <span class="eyebrow">{t("processesView.controlEyebrow")}</span>
          <h3 id="process-control-title">{t("processesView.controlTitle")}</h3>
          <p class="muted">{t("processesView.controlBody")}</p>
        </div>
        <StatusPill kind={processTone(control.step.state)} label={control.step.state} />
      </div>
      <dl class="process-control-meta">
        <div><dt>{t("processesView.controlKind")}</dt><dd>{t(`processesView.controlStep.${control.step.kind}`)}</dd></div>
        <div><dt>{t("processesView.controlAttempt")}</dt><dd>{control.step.attempt}</dd></div>
        <div><dt>{t("processesView.revision")}</dt><dd>{control.process_revision}</dd></div>
        <div><dt>{t("processesView.controlReason")}</dt><dd>{control.step.reason ?? t("processesView.controlPending")}</dd></div>
        {Object.entries(control.step.requirements).map(([key, value]) => (
          <div key={key}>
            <dt>{t(`processesView.controlField.${key}`)}</dt>
            <dd>{displayValue(value)}</dd>
          </div>
        ))}
      </dl>
      <div class="process-transition-actions" aria-label={t("processesView.transitionActions")}>
        {control.permitted_transitions.map((transition) => (
          <button
            type="button"
            class="btn btn-small"
            key={transition.id}
            disabled={pending !== null}
            aria-busy={pending === transition.id}
            onClick={() => void request(transition)}
          >
            {pending === transition.id
              ? t("processesView.transitionRequesting")
              : t(`processesView.transition.${transition.id}`)}
          </button>
        ))}
        {control.permitted_transitions.length === 0 ? (
          <span class="muted">{t("processesView.noPermittedTransitions")}</span>
        ) : null}
      </div>
      {accepted ? (
        <p class="callout" role="status">
          {t("processesView.transitionAccepted", { proposalId: accepted })}
        </p>
      ) : null}
      {error ? (
        <p class="wf-test-fail" role="alert">
          {t("processesView.transitionDenied", { error })}
        </p>
      ) : null}
    </section>
  );
}
