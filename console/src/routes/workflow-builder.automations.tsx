import { useState } from "preact/hooks";
import {
  createWorkflowBinding,
  deleteWorkflowBinding,
  type WorkflowBindingEntry,
  type WorkflowDefinitionCatalogResponse,
  type WorkflowDefinitionEntry,
} from "../workflow/validate";
import { Tooltip } from "../components/tooltip";
import { formatNumber, t, triggerLabel } from "./i18n/workflow";
import { browserTimeZone, describeSchedule, isFiveFieldCron } from "./workflow-builder.browse";
import { signalLabel } from "./workflow-builder.helpers";
import { SIGNAL_TYPE_OPTIONS } from "./workflow-builder.model";

export function hasEquivalentWorkflowBinding(
  bindings: readonly WorkflowBindingEntry[],
  definitionId: string,
  trigger: WorkflowBindingEntry["trigger"],
  cronExpression: string,
  timezone: string,
  signalType: string,
): boolean {
  const cron = trigger === "schedule" ? cronExpression.trim() : null;
  const zone = trigger === "schedule" ? timezone.trim() : null;
  const signal = trigger === "signal" ? signalType.trim() : null;
  return bindings.some((binding) =>
    binding.definition_id === definitionId &&
    binding.trigger === trigger &&
    binding.scope_ref === null &&
    binding.cron_expression === cron &&
    binding.timezone === zone &&
    binding.signal_type === signal
  );
}

export function WorkflowAutomations({
  bindings,
  definitions,
  selectedDefinition,
  onCreated,
  onDeleted,
}: {
  readonly bindings: readonly WorkflowBindingEntry[];
  readonly definitions: WorkflowDefinitionCatalogResponse;
  readonly selectedDefinition: WorkflowDefinitionEntry | null;
  readonly onCreated: (binding: WorkflowBindingEntry) => void;
  readonly onDeleted: (bindingId: string) => void;
}) {
  const [trigger, setTrigger] = useState<"deck_open" | "schedule" | "signal">("deck_open");
  const [cronExpression, setCronExpression] = useState("0 7 * * *");
  const [timezone, setTimezone] = useState(browserTimeZone);
  const [signalType, setSignalType] = useState("object.event");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingRemoval, setPendingRemoval] = useState<string | null>(null);
  const cronValid = trigger !== "schedule" || isFiveFieldCron(cronExpression);
  const schedulePreview = trigger === "schedule" && cronValid
    ? describeSchedule(cronExpression, timezone.trim() || "UTC")
    : null;
  const incomplete = (trigger === "schedule" && (!cronValid || timezone.trim() === ""))
    || (trigger === "signal" && signalType.trim() === "");
  const definitionById = new Map(
    Object.values(definitions.groups)
      .flat()
      .map((definition) => [definition.definition_id, definition] as const),
  );
  const equivalentBinding = selectedDefinition !== null && hasEquivalentWorkflowBinding(
    bindings,
    selectedDefinition.definition_id,
    trigger,
    cronExpression,
    timezone,
    signalType,
  );

  const createBinding = async (): Promise<void> => {
    if (selectedDefinition === null) return;
    setSaving(true);
    try {
      const binding = await createWorkflowBinding({
        definition_id: selectedDefinition.definition_id,
        trigger,
        ...(trigger === "schedule" ? { cron_expression: cronExpression, timezone } : {}),
        ...(trigger === "signal" ? { signal_type: signalType } : {}),
      });
      onCreated(binding);
      setError(null);
      setNotice(t("workflow.automations.created", { workflow: selectedDefinition.workflow_name }));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSaving(false);
    }
  };

  const removeBinding = async (binding: WorkflowBindingEntry): Promise<void> => {
    setSaving(true);
    try {
      await deleteWorkflowBinding(binding.binding_id, binding.revision);
      onDeleted(binding.binding_id);
      setPendingRemoval(null);
      setError(null);
      setNotice(t("workflow.automations.removed"));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSaving(false);
    }
  };

  return (
    <section class="workflow-automation-section">
      <header>
        <div>
          <h3>{t("workflow.automations.heading")} <span>{formatNumber(bindings.length)}</span></h3>
          <p>
            {t("workflow.automations.description")}
          </p>
        </div>
      </header>
      {error ? <p class="error-text" role="alert">{error}</p> : null}
      {notice && error === null ? <p class="workflow-automation-notice" role="status">{notice}</p> : null}
      <div class="workflow-automation-layout">
        <div class="workflow-binding-list">
          {bindings.map((binding) => {
            const definition = definitionById.get(binding.definition_id);
            const workflowName = definition?.workflow_name ?? binding.definition_id;
            const confirming = pendingRemoval === binding.binding_id;
            const detail = binding.trigger === "schedule"
              ? describeSchedule(binding.cron_expression ?? "", binding.timezone ?? "UTC")
                ?? `${binding.cron_expression} - ${binding.timezone}`
              : binding.trigger === "signal"
                ? signalLabel(binding.signal_type ?? "") || binding.signal_type || ""
                : t("workflow.automations.configuredInactive");
            return (
              <article key={binding.binding_id}>
                <div>
                  <strong>{workflowName}</strong>
                  <span>{triggerLabel(binding.trigger)}</span>
                  <small>{detail}</small>
                  <Tooltip content={t("workflow.automations.dispatchInactiveHint")}>
                    <span class="status-pill status-pill-neutral">
                      {t("workflow.automations.dispatchInactive")}
                    </span>
                  </Tooltip>
                </div>
                {confirming ? (
                  <div class="workflow-binding-confirm" role="group" aria-label={t("workflow.automations.removeConfirm", { workflow: workflowName })}>
                    <button
                      type="button"
                      class="btn btn-small btn-danger"
                      disabled={saving}
                      onClick={() => void removeBinding(binding)}
                    >
                      {t("workflow.automations.confirmRemove")}
                    </button>
                    <button
                      type="button"
                      class="btn btn-small secondary"
                      disabled={saving}
                      onClick={() => setPendingRemoval(null)}
                    >
                      {t("workflow.automations.cancel")}
                    </button>
                  </div>
                ) : (
                  <button
                    type="button"
                    class="btn btn-small secondary"
                    disabled={saving}
                    onClick={() => setPendingRemoval(binding.binding_id)}
                  >
                    {t("workflow.automations.remove")}
                  </button>
                )}
              </article>
            );
          })}
          {bindings.length === 0 ? <p class="muted small">{t("workflow.automations.empty")}</p> : null}
        </div>

        <div class="workflow-binding-create">
          <strong>
            {selectedDefinition
              ? t("workflow.automations.useWorkflow", { workflow: selectedDefinition.workflow_name })
              : t("workflow.automations.selectDefinition")}
          </strong>
          <label>
            <span>{t("workflow.automations.trigger")}</span>
            <select
              value={trigger}
              disabled={selectedDefinition === null}
              onChange={(event) => setTrigger(event.currentTarget.value as typeof trigger)}
            >
              <option value="deck_open">{t("workflow.automations.deckOpen")}</option>
              <option value="schedule">{t("workflow.automations.schedule")}</option>
              <option value="signal">{t("workflow.automations.signal")}</option>
            </select>
          </label>
          {trigger === "schedule" ? (
            <>
              <label>
                <span>{t("workflow.automations.cronExpression")}</span>
                <input
                  class="form-input mono"
                  value={cronExpression}
                  aria-invalid={!cronValid}
                  aria-describedby="workflow-binding-cron-hint"
                  onInput={(event) => setCronExpression(event.currentTarget.value)}
                />
                <small id="workflow-binding-cron-hint" class={cronValid ? undefined : "error-text"}>
                  {cronValid
                    ? schedulePreview
                      ? t("workflow.automations.cronPreview", { description: schedulePreview })
                      : null
                    : t("workflow.automations.cronInvalid")}
                </small>
              </label>
              <label>
                <span>{t("workflow.automations.timezone")}</span>
                <input
                  class="form-input"
                  value={timezone}
                  aria-describedby="workflow-binding-timezone-hint"
                  onInput={(event) => setTimezone(event.currentTarget.value)}
                />
                <small id="workflow-binding-timezone-hint">{t("workflow.automations.timezoneHint")}</small>
              </label>
            </>
          ) : null}
          {trigger === "signal" ? (
            <label>
              <span>{t("workflow.automations.signalType")}</span>
              <input
                class="form-input mono"
                list="workflow-binding-signals"
                value={signalType}
                aria-describedby="workflow-binding-signal-hint"
                onInput={(event) => setSignalType(event.currentTarget.value)}
              />
              <datalist id="workflow-binding-signals">
                {SIGNAL_TYPE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>{signalLabel(option.value)}</option>
                ))}
              </datalist>
              <small id="workflow-binding-signal-hint">{t("workflow.automations.signalHint")}</small>
            </label>
          ) : null}
          <button
            type="button"
            class="btn"
            disabled={saving || selectedDefinition === null || equivalentBinding || incomplete}
            onClick={() => void createBinding()}
          >
            {t(equivalentBinding
              ? "workflow.automations.configurationSaved"
              : "workflow.automations.saveConfiguration")}
          </button>
        </div>
      </div>
    </section>
  );
}
