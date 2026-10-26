import type { InvestigationActivity } from "./backend-types";
import { t } from "./i18n/investigation";

const MODEL_CALL_STAGES: ReadonlySet<string> = new Set([
  "preflight",
  "judgment",
  "form",
  "blind_review",
  "concept_chooser",
  "direction_reader",
  "ambiguity_reader",
  "frame",
  "plan",
]);

function formatDuration(durationMs: number): string {
  return durationMs < 1000
    ? `${Math.round(durationMs)} ms`
    : `${(durationMs / 1000).toFixed(1)} s`;
}

// A model-call row names its stage and outcome from closed codes, so it follows the Console
// language even when the answer follows the language of the question.
export function modelCallLabel(activity: InvestigationActivity): string {
  return activity.modelCall && MODEL_CALL_STAGES.has(activity.modelCall.stage)
    ? t("deck.investigation.modelCallLabel", {
        stage: t(`deck.investigation.modelStage.${activity.modelCall.stage}`),
      })
    : activity.label;
}

export function modelCallDetail(activity: InvestigationActivity): string | undefined {
  const call = activity.modelCall;
  if (!call || !MODEL_CALL_STAGES.has(call.stage)) return activity.detail;
  const model = call.model ?? t("deck.investigation.modelCallModel");
  if (activity.status === "running" || activity.status === "pending") {
    return t("deck.investigation.modelCallWaiting", { model });
  }
  return t("deck.investigation.modelCallSettled", {
    model,
    duration: formatDuration(call.durationMs ?? 0),
    outcome: t(activity.status === "completed"
      ? "deck.investigation.modelCallCompleted"
      : "deck.investigation.modelCallFailed"),
  });
}
