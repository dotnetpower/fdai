import { useState } from "preact/hooks";
import {
  createWorkflowBinding,
  deleteWorkflowBinding,
  type WorkflowBindingEntry,
  type WorkflowDefinitionCatalogResponse,
  type WorkflowDefinitionEntry,
} from "../workflow/validate";
import { formatNumber, t, triggerLabel } from "./i18n/workflow";

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
  const [timezone, setTimezone] = useState("Asia/Seoul");
  const [signalType, setSignalType] = useState("object.event");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
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
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : String(caught));
    } finally {
      setSaving(false);
    }
  };

  const removeBinding = async (binding: WorkflowBindingEntry): Promise<void> => {
    const definition = definitionById.get(binding.definition_id);
    const workflowName = definition?.workflow_name ?? binding.definition_id;
    if (!window.confirm(t("workflow.automations.removeConfirm", { workflow: workflowName }))) return;
    setSaving(true);
    try {
      await deleteWorkflowBinding(binding.binding_id, binding.revision);
      onDeleted(binding.binding_id);
      setError(null);
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
      {error ? <p class="error-text">{error}</p> : null}
      <div class="workflow-automation-layout">
        <div class="workflow-binding-list">
          {bindings.map((binding) => {
            const definition = definitionById.get(binding.definition_id);
            return (
              <article key={binding.binding_id}>
                <div>
                  <strong>{definition?.workflow_name ?? binding.definition_id}</strong>
                  <span>{triggerLabel(binding.trigger)}</span>
                  <small>
                    {binding.trigger === "schedule"
                      ? `${binding.cron_expression} - ${binding.timezone}`
                      : binding.signal_type ?? t("workflow.automations.configuredInactive")}
                  </small>
                </div>
                <button
                  type="button"
                  class="secondary"
                  disabled={saving}
                  onClick={() => void removeBinding(binding)}
                >
                  {t("workflow.automations.remove")}
                </button>
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
                <input value={cronExpression} onInput={(event) => setCronExpression(event.currentTarget.value)} />
              </label>
              <label>
                <span>{t("workflow.automations.timezone")}</span>
                <input value={timezone} onInput={(event) => setTimezone(event.currentTarget.value)} />
              </label>
            </>
          ) : null}
          {trigger === "signal" ? (
            <label>
              <span>{t("workflow.automations.signalType")}</span>
              <input value={signalType} onInput={(event) => setSignalType(event.currentTarget.value)} />
            </label>
          ) : null}
          <button
            type="button"
            class="btn"
            disabled={saving || selectedDefinition === null || equivalentBinding}
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
