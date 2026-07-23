import { Tooltip } from "../components/tooltip";
import type { ActionTypePaletteEntry } from "../workflow/validate";
import { cloneForm } from "./workflow-builder.chat.builders";
import {
  addDraftStep,
  coerceDraftParam,
  draftParamType,
  moveDraftStep,
  removeDraftParam,
  removeDraftStep,
  setDraftParam,
  setDraftStepAction,
  updateDraftStepField,
  type DraftParamType,
  type DraftParamValue,
} from "./workflow-builder.editor";
import type { FormState } from "./workflow-builder.model";
import { t } from "./i18n/workflow";

export function WorkflowDraftEditor({
  form,
  palette,
  onChange,
}: {
  readonly form: FormState;
  readonly palette: readonly ActionTypePaletteEntry[];
  readonly onChange: (form: FormState) => void;
}) {
  const patch = (values: Partial<FormState>) => onChange({ ...cloneForm(form), ...values });
  return (
    <details class="wf-draft-editor">
      <summary>{t("workflow.editor.heading")}</summary>
      <div class="wf-editor-grid">
        <label class="form-field">
          <span class="form-label">{t("workflow.editor.name")}</span>
          <input class="form-input mono" value={form.name} onInput={(event) => patch({ name: (event.target as HTMLInputElement).value })} />
        </label>
        <label class="form-field form-field-wide">
          <span class="form-label">{t("workflow.editor.description")}</span>
          <textarea class="form-input" rows={2} value={form.description} onInput={(event) => patch({ description: (event.target as HTMLTextAreaElement).value })} />
        </label>
        <label class="form-field">
          <span class="form-label">{t("workflow.editor.triggerKind")}</span>
          <select class="form-input" value={form.triggerKind} onChange={(event) => patch({ triggerKind: (event.target as HTMLSelectElement).value as FormState["triggerKind"] })}>
            <option value="signal">{t("workflow.automations.signal")}</option>
            <option value="schedule">{t("workflow.automations.schedule")}</option>
          </select>
        </label>
        <label class="form-field">
          <span class="form-label">{t(form.triggerKind === "signal" ? "workflow.editor.signalType" : "workflow.editor.schedule")}</span>
          <input class="form-input mono" value={form.triggerKind === "signal" ? form.signalType : form.schedule} onInput={(event) => form.triggerKind === "signal" ? patch({ signalType: (event.target as HTMLInputElement).value }) : patch({ schedule: (event.target as HTMLInputElement).value })} />
        </label>
        <label class="form-field form-field-wide">
          <span class="form-label">{t("workflow.editor.antiScope")}</span>
          <textarea class="form-input" rows={2} value={form.antiScope} onInput={(event) => patch({ antiScope: (event.target as HTMLTextAreaElement).value })} />
        </label>
      </div>

      <div class="wf-editor-section-head">
        <h5>{t("workflow.editor.steps")}</h5>
        <button type="button" class="btn btn-small" onClick={() => onChange(addDraftStep(form))}>
          + {t("workflow.editor.addStep")}
        </button>
      </div>
      <div class="wf-editor-steps">
        {form.steps.map((step, index) => (
          <div class="step-editor" key={step.key}>
            <div class="step-editor-head">
              <strong>{t("workflow.editor.step", { number: index + 1 })}</strong>
              <div class="step-move">
                <Tooltip content={t("workflow.editor.moveUp")}>
                  <button type="button" class="btn btn-small" disabled={index === 0} aria-label={t("workflow.editor.moveUp")} onClick={() => onChange(moveDraftStep(form, step.key, -1))}>&uarr;</button>
                </Tooltip>
                <Tooltip content={t("workflow.editor.moveDown")}>
                  <button type="button" class="btn btn-small" disabled={index === form.steps.length - 1} aria-label={t("workflow.editor.moveDown")} onClick={() => onChange(moveDraftStep(form, step.key, 1))}>&darr;</button>
                </Tooltip>
                <Tooltip content={t("workflow.editor.removeStep")}>
                  <button type="button" class="btn btn-small btn-danger" aria-label={t("workflow.editor.removeStep")} onClick={() => onChange(removeDraftStep(form, step.key))}>&times;</button>
                </Tooltip>
              </div>
            </div>
            <div class="wf-editor-grid">
              <label class="form-field">
                <span class="form-label">{t("workflow.editor.actionType")}</span>
                <select class="form-input mono" value={step.action_type_ref} onChange={(event) => onChange(setDraftStepAction(form, step.key, (event.target as HTMLSelectElement).value))}>
                  <option value="">{t("workflow.editor.chooseAction")}</option>
                  {palette.map((entry) => <option key={entry.name} value={entry.name}>{entry.name}</option>)}
                </select>
              </label>
              <label class="form-field">
                <span class="form-label">{t("workflow.editor.stepId")}</span>
                <input class="form-input mono" value={step.id} onInput={(event) => onChange(updateDraftStepField(form, step.key, "id", (event.target as HTMLInputElement).value))} />
              </label>
            </div>
            <details class="step-advanced">
              <summary>{t("workflow.editor.advanced")}</summary>
              <div class="wf-editor-grid">
                {(["guard_rule_ref", "compensated_by", "on_failure"] as const).map((field) => (
                  <label class="form-field" key={field}>
                    <span class="form-label">{t(`workflow.editor.${field}`)}</span>
                    <input class="form-input mono" value={step[field]} onInput={(event) => onChange(updateDraftStepField(form, step.key, field, (event.target as HTMLInputElement).value))} />
                  </label>
                ))}
              </div>
              <div class="wf-editor-section-head">
                <h6>{t("workflow.editor.parameters")}</h6>
                <button type="button" class="btn btn-small" onClick={() => onChange(setDraftParam(form, step.key, "", nextParamName(step.params), ""))}>+ {t("workflow.editor.addParameter")}</button>
              </div>
              <div class="wf-param-list">
                {Object.entries(step.params).map(([name, value]) => (
                  <ParameterRow key={name} name={name} value={value} onChange={(nextName, nextValue) => onChange(setDraftParam(form, step.key, name, nextName, nextValue))} onRemove={() => onChange(removeDraftParam(form, step.key, name))} />
                ))}
              </div>
            </details>
          </div>
        ))}
      </div>

      <details class="step-advanced">
        <summary>{t("workflow.editor.promotionGate")}</summary>
        <div class="wf-editor-grid">
          {(["minShadowDays", "minSamples", "minAccuracy", "maxPolicyEscapes"] as const).map((field) => (
            <label class="form-field" key={field}>
              <span class="form-label">{t(`workflow.editor.${field}`)}</span>
              <input class="form-input" type="number" step={field === "minAccuracy" ? "0.01" : "1"} value={form[field]} onInput={(event) => patch({ [field]: (event.target as HTMLInputElement).value })} />
            </label>
          ))}
        </div>
      </details>
    </details>
  );
}

function ParameterRow({
  name,
  value,
  onChange,
  onRemove,
}: {
  readonly name: string;
  readonly value: DraftParamValue;
  readonly onChange: (name: string, value: DraftParamValue) => void;
  readonly onRemove: () => void;
}) {
  const type = draftParamType(value);
  const updateType = (nextType: DraftParamType) => onChange(name, coerceDraftParam(String(value), nextType));
  return (
    <div class="wf-param-row">
      <input class="form-input mono" aria-label={t("workflow.editor.parameterName")} value={name} onInput={(event) => onChange((event.target as HTMLInputElement).value, value)} />
      <select class="form-input" aria-label={t("workflow.editor.parameterType")} value={type} onChange={(event) => updateType((event.target as HTMLSelectElement).value as DraftParamType)}>
        <option value="string">string</option>
        <option value="number">number</option>
        <option value="boolean">boolean</option>
      </select>
      {type === "boolean" ? (
        <select class="form-input" aria-label={t("workflow.editor.parameterValue")} value={String(value)} onChange={(event) => onChange(name, (event.target as HTMLSelectElement).value === "true")}>
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
      ) : (
        <input class="form-input" aria-label={t("workflow.editor.parameterValue")} type={type === "number" ? "number" : "text"} value={String(value)} onInput={(event) => onChange(name, coerceDraftParam((event.target as HTMLInputElement).value, type))} />
      )}
      <Tooltip content={t("workflow.editor.removeParameter")}>
        <button type="button" class="btn btn-small btn-danger" aria-label={t("workflow.editor.removeParameter")} onClick={onRemove}>&times;</button>
      </Tooltip>
    </div>
  );
}

function nextParamName(params: Readonly<Record<string, unknown>>): string {
  if (!("parameter" in params)) return "parameter";
  for (let index = 2; ; index += 1) {
    const candidate = `parameter_${index}`;
    if (!(candidate in params)) return candidate;
  }
}
