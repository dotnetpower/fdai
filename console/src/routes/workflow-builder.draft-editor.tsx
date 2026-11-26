import {
  CheckboxField,
  SelectField,
  TextInput,
  TextareaField,
} from "../components/form-controls";
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
        <TextInput
          label={t("workflow.editor.name")}
          mono
          value={form.name}
          onInput={(next) => patch({ name: next })}
        />
        <TextareaField
          label={t("workflow.editor.description")}
          rows={2}
          className="form-field-wide"
          value={form.description}
          onInput={(next) => patch({ description: next })}
        />
        <SelectField
          label={t("workflow.editor.triggerKind")}
          value={form.triggerKind}
          options={[
            { value: "signal", label: t("workflow.automations.signal") },
            { value: "schedule", label: t("workflow.automations.schedule") },
          ]}
          onChange={(next) => patch({ triggerKind: next as FormState["triggerKind"] })}
        />
        <TextInput
          label={t(form.triggerKind === "signal" ? "workflow.editor.signalType" : "workflow.editor.schedule")}
          mono
          value={form.triggerKind === "signal" ? form.signalType : form.schedule}
          onInput={(next) => form.triggerKind === "signal" ? patch({ signalType: next }) : patch({ schedule: next })}
        />
        <TextareaField
          label={t("workflow.editor.antiScope")}
          rows={2}
          className="form-field-wide"
          value={form.antiScope}
          onInput={(next) => patch({ antiScope: next })}
        />
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
              <SelectField
                label={t("workflow.editor.stepKind")}
                value={step.kind}
                options={AUTHORABLE_STEP_KINDS.map((kind) => ({
                  value: kind,
                  label: t(`workflow.stepKind.${kind}`),
                }))}
                onChange={(next) => onChange(setDraftStepKind(
                  form,
                  step.key,
                  next as typeof step.kind,
                ))}
              />
              <TextInput
                label={t("workflow.editor.stepId")}
                mono
                required
                value={step.id}
                onInput={(next) => onChange(updateDraftStepField(form, step.key, "id", next))}
              />
              {step.kind === "action" ? (
                <SelectField
                  label={t("workflow.editor.actionType")}
                  required
                  value={step.action_type_ref}
                  options={[
                    { value: "", label: t("workflow.editor.chooseAction") },
                    ...palette.map((entry) => ({ value: entry.name, label: entry.name })),
                  ]}
                  onChange={(next) => onChange(setDraftStepAction(form, step.key, next))}
                />
              ) : null}
              {step.kind === "wait" ? (
                <>
                  <TextInput
                    label={t("workflow.editor.waitFor")}
                    mono
                    required
                    value={step.wait_for}
                    hint={t("workflow.editor.waitForHint")}
                    onInput={(next) => onChange(updateDraftStepField(form, step.key, "wait_for", next))}
                  />
                  <TimeoutField form={form} stepKey={step.key} value={step.timeout_seconds} onChange={onChange} />
                </>
              ) : null}
              {step.kind === "approval" ? (
                <>
                  <SelectField
                    label={t("workflow.editor.approvalRole")}
                    required
                    value={step.approval_role}
                    options={[
                      { value: "", label: t("workflow.editor.chooseApprovalRole") },
                      ...APPROVAL_ROLES.map((role) => ({ value: role, label: t(`workflow.approvalRole.${role}`) })),
                    ]}
                    onChange={(next) => onChange(setDraftStepApprovalRole(form, step.key, next as ApprovalRole | ""))}
                  />
                  <TextInput
                    label={t("workflow.editor.quorum")}
                    type="number"
                    min="1"
                    step="1"
                    required
                    value={step.quorum}
                    hint={t("workflow.editor.quorumHint")}
                    onInput={(next) => onChange(updateDraftStepField(form, step.key, "quorum", next))}
                  />
                  <TimeoutField form={form} stepKey={step.key} value={step.timeout_seconds} onChange={onChange} />
                  <CheckboxField
                    label={t("workflow.editor.noSelfApproval")}
                    hint={t("workflow.editor.noSelfApprovalHint")}
                    checked={step.no_self_approval}
                    className="wf-checkbox-field"
                    onChange={(checked) => onChange(setDraftStepNoSelfApproval(form, step.key, checked))}
                  />
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
                  <TextInput
                    label={t("workflow.editor.joinBehavior")}
                    value={t("workflow.editor.joinAll")}
                    disabled
                    hint={t("workflow.editor.joinHint")}
                    onInput={() => {}}
                  />
                </>
              ) : null}
              {step.kind === "gate" ? (
                <div class="cs-field form-field-wide">
                  <label for={`workflow-gate-ref-input-${step.key}`} class="cs-field-label">
                    <span>{t("workflow.editor.gateRef")}</span>
                  </label>
                  <input
                    id={`workflow-gate-ref-input-${step.key}`}
                    class="cs-field-control cs-field-control--mono"
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
                  <span class="cs-field-hint">{t("workflow.editor.gateRefHint")}</span>
                </div>
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
                  <TextInput
                    key={field}
                    label={t(`workflow.editor.${field}`)}
                    mono
                    value={step[field]}
                    onInput={(next) => onChange(updateDraftStepField(form, step.key, field, next))}
                  />
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
            <TextInput
              key={field}
              label={t(`workflow.editor.${field}`)}
              type="number"
              step={field === "minAccuracy" ? "0.01" : "1"}
              value={form[field]}
              onInput={(next) => patch({ [field]: next })}
            />
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
          <TextInput
            label={t(itemLabelKey, { number: index + 1 })}
            hideLabel
            mono
            required
            value={value}
            onInput={(next) => onChange(setDraftListItem(
              form,
              stepKey,
              field,
              index,
              next,
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
    <TextInput
      label={t("workflow.editor.timeoutSeconds")}
      type="number"
      min="1"
      step="1"
      required
      value={value}
      hint={t("workflow.editor.timeoutHint")}
      onInput={(next) => onChange(updateDraftStepField(form, stepKey, "timeout_seconds", next))}
    />
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
      <TextInput
        label={t("workflow.editor.parameterName")}
        hideLabel
        mono
        value={name}
        onInput={(next) => onChange(next, value)}
      />
      <SelectField
        label={t("workflow.editor.parameterType")}
        hideLabel
        value={type}
        options={[
          { value: "string", label: "string" },
          { value: "number", label: "number" },
          { value: "boolean", label: "boolean" },
        ]}
        onChange={(next) => updateType(next as DraftParamType)}
      />
      {type === "boolean" ? (
        <SelectField
          label={t("workflow.editor.parameterValue")}
          hideLabel
          value={String(value)}
          options={[
            { value: "true", label: "true" },
            { value: "false", label: "false" },
          ]}
          onChange={(next) => onChange(name, next === "true")}
        />
      ) : (
        <TextInput
          label={t("workflow.editor.parameterValue")}
          hideLabel
          type={type === "number" ? "number" : "text"}
          value={String(value)}
          onInput={(next) => onChange(name, coerceDraftParam(next, type))}
        />
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
