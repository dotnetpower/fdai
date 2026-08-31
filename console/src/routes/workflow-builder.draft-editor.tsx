import { Tooltip } from "../components/tooltip";
import type { ActionTypePaletteEntry } from "../workflow/validate";
import { cloneForm } from "./workflow-builder.chat.builders";
import {
  addDraftListItem,
  addDraftStep,
  coerceDraftParam,
  draftParamType,
  moveDraftStep,
  removeDraftListItem,
  removeDraftParam,
  removeDraftStep,
  setDraftParam,
  setDraftStepAction,
  setDraftStepApprovalRole,
  setDraftStepKind,
  setDraftStepNoSelfApproval,
  setDraftListItem,
  updateDraftStepField,
  type DraftParamType,
  type DraftParamValue,
} from "./workflow-builder.editor";
import {
  APPROVAL_ROLES,
  AUTHORABLE_STEP_KINDS,
  type ApprovalRole,
  type FormState,
} from "./workflow-builder.model";
import { t } from "./i18n/workflow";

export function WorkflowDraftEditor({
  form,
  palette,
  gateRefs,
  onChange,
}: {
  readonly form: FormState;
  readonly palette: readonly ActionTypePaletteEntry[];
  readonly gateRefs: readonly string[];
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
                <span class="form-label">{t("workflow.editor.stepKind")}</span>
                <select
                  class="form-input"
                  value={step.kind}
                  onChange={(event) => onChange(setDraftStepKind(
                    form,
                    step.key,
                    (event.target as HTMLSelectElement).value as typeof step.kind,
                  ))}
                >
                  {AUTHORABLE_STEP_KINDS.map((kind) => (
                    <option key={kind} value={kind}>{t(`workflow.stepKind.${kind}`)}</option>
                  ))}
                </select>
              </label>
              <label class="form-field">
                <span class="form-label">{t("workflow.editor.stepId")}</span>
                <input class="form-input mono" required value={step.id} onInput={(event) => onChange(updateDraftStepField(form, step.key, "id", (event.target as HTMLInputElement).value))} />
              </label>
              {step.kind === "action" ? (
              <label class="form-field">
                <span class="form-label">{t("workflow.editor.actionType")}</span>
                <select class="form-input mono" required value={step.action_type_ref} onChange={(event) => onChange(setDraftStepAction(form, step.key, (event.target as HTMLSelectElement).value))}>
                  <option value="">{t("workflow.editor.chooseAction")}</option>
                  {palette.map((entry) => <option key={entry.name} value={entry.name}>{entry.name}</option>)}
                </select>
              </label>
              ) : null}
              {step.kind === "wait" ? (
                <>
                  <label class="form-field">
                    <span class="form-label">{t("workflow.editor.waitFor")}</span>
                    <input class="form-input mono" required value={step.wait_for} onInput={(event) => onChange(updateDraftStepField(form, step.key, "wait_for", (event.target as HTMLInputElement).value))} />
                    <span class="field-hint">{t("workflow.editor.waitForHint")}</span>
                  </label>
                  <TimeoutField form={form} stepKey={step.key} value={step.timeout_seconds} onChange={onChange} />
                </>
              ) : null}
              {step.kind === "approval" ? (
                <>
                  <label class="form-field">
                    <span class="form-label">{t("workflow.editor.approvalRole")}</span>
                    <select class="form-input" required value={step.approval_role} onChange={(event) => onChange(setDraftStepApprovalRole(form, step.key, (event.target as HTMLSelectElement).value as ApprovalRole | ""))}>
                      <option value="">{t("workflow.editor.chooseApprovalRole")}</option>
                      {APPROVAL_ROLES.map((role) => <option key={role} value={role}>{t(`workflow.approvalRole.${role}`)}</option>)}
                    </select>
                  </label>
                  <label class="form-field">
                    <span class="form-label">{t("workflow.editor.quorum")}</span>
                    <input class="form-input" type="number" min="1" step="1" required value={step.quorum} onInput={(event) => onChange(updateDraftStepField(form, step.key, "quorum", (event.target as HTMLInputElement).value))} />
                    <span class="field-hint">{t("workflow.editor.quorumHint")}</span>
                  </label>
                  <TimeoutField form={form} stepKey={step.key} value={step.timeout_seconds} onChange={onChange} />
                  <label class="form-field wf-checkbox-field">
                    <input
                      type="checkbox"
                      checked={step.no_self_approval}
                      onChange={(event) => onChange(setDraftStepNoSelfApproval(
                        form,
                        step.key,
                        (event.target as HTMLInputElement).checked,
                      ))}
                    />
                    <span>
                      <span class="form-label">{t("workflow.editor.noSelfApproval")}</span>
                      <span class="field-hint">{t("workflow.editor.noSelfApprovalHint")}</span>
                    </span>
                  </label>
                </>
              ) : null}
              {step.kind === "decision" ? (
                <StringListField
                  form={form}
                  stepKey={step.key}
                  field="outcomes"
                  values={step.outcomes}
                  labelKey="workflow.editor.outcomes"
                  itemLabelKey="workflow.editor.outcomeNumber"
                  addLabelKey="workflow.editor.addOutcome"
                  hintKey="workflow.editor.outcomesHint"
                  onChange={onChange}
                />
              ) : null}
              {step.kind === "parallel" ? (
                <>
                  <StringListField
                    form={form}
                    stepKey={step.key}
                    field="branches"
                    values={step.branches}
                    labelKey="workflow.editor.branches"
                    itemLabelKey="workflow.editor.branchNumber"
                    addLabelKey="workflow.editor.addBranch"
                    hintKey="workflow.editor.branchesHint"
                    onChange={onChange}
                  />
                  <label class="form-field">
                    <span class="form-label">{t("workflow.editor.joinBehavior")}</span>
                    <input class="form-input" value={t("workflow.editor.joinAll")} disabled />
                    <span class="field-hint">{t("workflow.editor.joinHint")}</span>
                  </label>
                </>
              ) : null}
              {step.kind === "gate" ? (
                <label class="form-field form-field-wide">
                  <span class="form-label">{t("workflow.editor.gateRef")}</span>
                  <input
                    class="form-input mono"
                    list={`workflow-gate-refs-${step.key}`}
                    required
                    value={step.gate_ref}
                    onInput={(event) => onChange(updateDraftStepField(
                      form,
                      step.key,
                      "gate_ref",
                      (event.target as HTMLInputElement).value,
                    ))}
                  />
                  <datalist id={`workflow-gate-refs-${step.key}`}>
                    {gateRefs.map((gateRef) => <option key={gateRef} value={gateRef} />)}
                  </datalist>
                  <span class="field-hint">{t("workflow.editor.gateRefHint")}</span>
                </label>
              ) : null}
            </div>
            <details class="step-advanced">
              <summary>{t("workflow.editor.advanced")}</summary>
              <div class="wf-editor-grid">
                {([
                  "guard_rule_ref",
                  ...(step.kind === "action" ? ["compensated_by"] as const : []),
                  "on_failure",
                ] as const).map((field) => (
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

function StringListField({
  form,
  stepKey,
  field,
  values,
  labelKey,
  itemLabelKey,
  addLabelKey,
  hintKey,
  onChange,
}: {
  readonly form: FormState;
  readonly stepKey: number;
  readonly field: "outcomes" | "branches";
  readonly values: readonly string[];
  readonly labelKey: string;
  readonly itemLabelKey: string;
  readonly addLabelKey: string;
  readonly hintKey: string;
  readonly onChange: (form: FormState) => void;
}) {
  return (
    <fieldset class="form-field form-field-wide wf-string-list">
      <legend class="form-label">{t(labelKey)}</legend>
      {values.map((value, index) => (
        <div class="wf-string-list-row" key={index}>
          <input
            class="form-input mono"
            aria-label={t(itemLabelKey, { number: index + 1 })}
            required
            value={value}
            onInput={(event) => onChange(setDraftListItem(
              form,
              stepKey,
              field,
              index,
              (event.target as HTMLInputElement).value,
            ))}
          />
          <Tooltip content={t("workflow.editor.removeListItem")}>
            <button
              type="button"
              class="btn btn-small btn-danger"
              aria-label={t("workflow.editor.removeListItem")}
              onClick={() => onChange(removeDraftListItem(form, stepKey, field, index))}
            >
              &times;
            </button>
          </Tooltip>
        </div>
      ))}
      <button
        type="button"
        class="btn btn-small"
        onClick={() => onChange(addDraftListItem(form, stepKey, field))}
      >
        + {t(addLabelKey)}
      </button>
      <span class="field-hint">{t(hintKey)}</span>
    </fieldset>
  );
}

function TimeoutField({
  form,
  stepKey,
  value,
  onChange,
}: {
  readonly form: FormState;
  readonly stepKey: number;
  readonly value: string;
  readonly onChange: (form: FormState) => void;
}) {
  return (
    <label class="form-field">
      <span class="form-label">{t("workflow.editor.timeoutSeconds")}</span>
      <input class="form-input" type="number" min="1" step="1" required value={value} onInput={(event) => onChange(updateDraftStepField(form, stepKey, "timeout_seconds", (event.target as HTMLInputElement).value))} />
      <span class="field-hint">{t("workflow.editor.timeoutHint")}</span>
    </label>
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
