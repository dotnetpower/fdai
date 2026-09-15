/** Accessible single-axis proposal forms; baseline entries and acknowledgements grant no authority. */
import { useState } from "preact/hooks";
import { alertTreatmentCandidates, type AlertQualityPayload } from "./alert-quality.model";
import {
  alertProposalEvidenceReady, initialAlertProposal, validateAlertProposal,
  type AlertEvaluationDraft, type AlertProposalDraft, type AlertProposalErrors,
  type AlertProposalField, type AlertProposalIssue, type AlertQualityProposal,
} from "./alert-quality.proposal";
import { AlertQualityFact as Fact, AlertQualityFacts as Facts } from "./alert-quality.presentation";
import { alertQualityText as text, type AlertQualityMessage } from "./i18n/alert-quality";

const control = { minHeight: 44, minWidth: 0, width: "100%" };
const grid = { gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 220px), 1fr))" };
const fieldset = { minWidth: 0, border: 0, padding: 0, margin: 0 };
const fieldId = (field: AlertProposalField) => `alert-quality-input-${field.replaceAll(".", "-")}`;

interface ProposalProps {
  readonly data: AlertQualityPayload;
  readonly scope: string;
  readonly held: boolean;
  readonly now: number;
  readonly onSubmit: (draft: AlertProposalDraft) => void;
}

/** Draft values survive a rejected/unknown request while the same report remains displayed. */
export function AlertQualityProposalForm(props: ProposalProps) {
  const [draft, setDraft] = useState<AlertProposalDraft>(() => initialAlertProposal());
  return <AlertQualityProposalEditor {...props} draft={draft} onDraft={setDraft} />;
}

/** Pure form presentation is independently testable without browser or provider side effects. */
export function AlertQualityProposalEditor({ data, scope, held, now, onSubmit, draft, onDraft }: ProposalProps & {
  readonly draft: AlertProposalDraft;
  readonly onDraft: (draft: AlertProposalDraft) => void;
}) {
  const ready = alertProposalEvidenceReady(data, scope, draft.kind, now);
  const { body, errors } = validateAlertProposal(data, scope, draft, now);
  const blocked = held || !ready;
  const candidates = data.assessment === null ? [] : alertTreatmentCandidates(data.assessment, draft.kind);
  return <form class="stack" style={{ gap: 24 }} aria-labelledby="alert-quality-proposal-title" onSubmit={(event) => {
    event.preventDefault();
    if (!blocked && body !== null) onSubmit(draft);
  }}>
    <div class="stack-section">
      <h3 id="alert-quality-proposal-title">{text("proposal")}</h3>
      <p>{text("proposalHelp")}</p>
      <p class="muted">{text("noChange")}</p>
    </div>
    <label style={{ minWidth: 0, maxWidth: 480, display: "grid", gap: 8 }}>
      <span>{text("treatment")}</span>
      <select class="cs-control-select" name="treatment_kind" value={draft.kind} disabled={held} style={control}
        aria-describedby="alert-quality-axis-help" onChange={(event) => {
          const kind = event.currentTarget.value;
          if (kind === "routing" || kind === "suppression" || kind === "evaluation") onDraft(initialAlertProposal(kind));
        }}>
        {(["routing", "suppression", "evaluation"] as const).map((kind) => <option key={kind} value={kind}>{text(`kind.${kind}`)}</option>)}
      </select>
    </label>
    <p id="alert-quality-axis-help" class="muted">{text("otherTreatments")}</p>
    <p id="alert-quality-proposal-help" class="muted">{text(ready ? "proposalFields" : "proposalHold")}</p>
    <fieldset class="stack" disabled={blocked} aria-describedby="alert-quality-proposal-help" style={fieldset}>
      <legend class="sr-only">{text("proposal")}</legend>
      <SelectField field="target_ref" label="rule" value={draft.target_ref} error={errors.target_ref}
        choices={candidates.map((value) => ({ value, label: value }))} placeholder="chooseRule"
        onValue={(target_ref) => onDraft({ ...draft, target_ref })} />
      {draft.kind === "routing" ? <>
        <p class="muted">{text("routingFieldsHelp")}</p>
        <div class="form-grid" style={grid}>
          <InputField field="remove_group_ref" label="removeGroup" value={draft.remove_group_ref} error={errors.remove_group_ref}
            onValue={(remove_group_ref) => onDraft({ ...draft, remove_group_ref })} />
          <InputField field="replacement_group_ref" label="replacementGroup" value={draft.replacement_group_ref} error={errors.replacement_group_ref}
            onValue={(replacement_group_ref) => onDraft({ ...draft, replacement_group_ref })} />
        </div>
      </> : draft.kind === "suppression" ? <SuppressionFields draft={draft} errors={errors} onDraft={onDraft} />
        : <EvaluationFields draft={draft} errors={errors} onDraft={onDraft} />}
    </fieldset>
    {body !== null ? <DraftPreview draft={draft} body={body} /> : null}
    <button class="btn" type="submit" style={{ minHeight: 44, alignSelf: "start" }}
      aria-describedby="alert-quality-proposal-help" disabled={blocked || body === null}>{text("submitProposal")}</button>
  </form>;
}

function FieldError({ field, error, visible }: {
  readonly field: AlertProposalField; readonly error: AlertProposalIssue | undefined; readonly visible: boolean;
}) {
  return visible && error !== undefined
    ? <span id={`${fieldId(field)}-error`} class="muted">{text(`validation.${error}`)}</span> : null;
}

function InputField({ field, label, value, error, onValue, format = "reference" }: {
  readonly field: AlertProposalField; readonly label: AlertQualityMessage; readonly value: string;
  readonly error: AlertProposalIssue | undefined; readonly onValue: (value: string) => void;
  readonly format?: "reference" | "timestamp" | "number" | "seconds";
}) {
  const invalid = value !== "" && error !== undefined;
  return <label style={{ minWidth: 0, display: "grid", gap: 8 }} htmlFor={fieldId(field)}>
    <span>{text(label)}</span>
    <input class="cs-control-input" id={fieldId(field)} name={field} type="text" required value={value} style={control}
      maxLength={format === "reference" ? 160 : format === "timestamp" ? 40 : 128}
      autoComplete="off" spellcheck={false} inputMode={format === "seconds" ? "numeric" : "text"}
      aria-invalid={invalid} aria-describedby={invalid ? `${fieldId(field)}-error` : undefined}
      placeholder={format === "timestamp" ? "YYYY-MM-DDTHH:mm:ss+00:00" : undefined}
      onInput={(event) => onValue(event.currentTarget.value)} />
    <FieldError field={field} error={error} visible={invalid} />
  </label>;
}

function SelectField({ field, label, value, error, choices, onValue, placeholder = "chooseValue" }: {
  readonly field: AlertProposalField; readonly label: AlertQualityMessage; readonly value: string;
  readonly error: AlertProposalIssue | undefined;
  readonly choices: readonly { readonly value: string; readonly label: string }[];
  readonly onValue: (value: string) => void;
  readonly placeholder?: AlertQualityMessage;
}) {
  const invalid = value !== "" && error !== undefined;
  return <label style={{ minWidth: 0, display: "grid", gap: 8 }} htmlFor={fieldId(field)}>
    <span>{text(label)}</span>
    <select class="cs-control-select" id={fieldId(field)} name={field} required style={control} value={value} aria-invalid={invalid}
      aria-describedby={invalid ? `${fieldId(field)}-error` : undefined} onChange={(event) => onValue(event.currentTarget.value)}>
      <option value="" disabled={value !== ""}>{text(placeholder)}</option>
      {choices.map((choice) => <option key={choice.value} value={choice.value}>{choice.label}</option>)}
    </select>
    <FieldError field={field} error={error} visible={invalid} />
  </label>;
}

function SuppressionFields({ draft, errors, onDraft }: {
  readonly draft: Extract<AlertProposalDraft, { kind: "suppression" }>;
  readonly errors: AlertProposalErrors; readonly onDraft: (draft: AlertProposalDraft) => void;
}) {
  return <>
    <p id="alert-quality-processing-help" class="muted">{text("suppressionPrerequisite")}</p>
    <InputField field="processing_rule_ref" label="processingRule" value={draft.processing_rule_ref} error={errors.processing_rule_ref}
      onValue={(processing_rule_ref) => onDraft({ ...draft, processing_rule_ref })} />
    <label style={{ display: "flex", alignItems: "center", gap: 12, minHeight: 44 }}>
      <input name="preprovisioned" type="checkbox" required checked={draft.preprovisioned}
        aria-describedby="alert-quality-processing-help" style={{ minWidth: 24, minHeight: 24 }}
        onChange={(event) => onDraft({ ...draft, preprovisioned: event.currentTarget.checked })} />
      <span>{text("preprovisionedConfirm")}</span>
    </label>
    <div class="form-grid" style={grid}>
      <InputField field="starts_at" label="starts" format="timestamp" value={draft.starts_at} error={errors.starts_at}
        onValue={(starts_at) => onDraft({ ...draft, starts_at })} />
      <InputField field="ends_at" label="ends" format="timestamp" value={draft.ends_at} error={errors.ends_at}
        onValue={(ends_at) => onDraft({ ...draft, ends_at })} />
    </div>
    <p class="muted">{text("windowInputHelp")}</p>
    <p class="muted">{text("suppressionHelp")}</p>
    <p class="muted">{text("propagationHelp")}</p>
  </>;
}

function EvaluationFields({ draft, errors, onDraft }: {
  readonly draft: Extract<AlertProposalDraft, { kind: "evaluation" }>;
  readonly errors: AlertProposalErrors; readonly onDraft: (draft: AlertProposalDraft) => void;
}) {
  const baseline = draft.baseline;
  const update = <K extends keyof AlertEvaluationDraft>(key: K, value: AlertEvaluationDraft[K]) =>
    onDraft({ ...draft, baseline: { ...baseline, [key]: value } });
  return <>
    <fieldset class="stack" style={fieldset} aria-describedby="alert-quality-baseline-help">
      <legend class="cs-type-panel-title">{text("baselineInput")}</legend>
      <p id="alert-quality-baseline-help" class="muted">{text("baselineHelp")}</p>
      <div class="form-grid" style={grid}>
        <InputField field="baseline.metric_ref" label="metric" value={baseline.metric_ref} error={errors["baseline.metric_ref"]}
          onValue={(value) => update("metric_ref", value)} />
        <SelectField field="baseline.operator" label="operator" value={baseline.operator} error={errors["baseline.operator"]}
          choices={(["above", "below"] as const).map((value) => ({ value, label: text(`operator.${value}`) }))}
          onValue={(value) => { if (value === "above" || value === "below" || value === "") update("operator", value); }} />
        <SelectField field="baseline.aggregation" label="aggregation" value={baseline.aggregation} error={errors["baseline.aggregation"]}
          choices={(["average", "maximum", "minimum"] as const).map((value) => ({ value, label: text(`aggregation.${value}`) }))}
          onValue={(value) => { if (value === "average" || value === "maximum" || value === "minimum" || value === "") update("aggregation", value); }} />
        <InputField field="baseline.threshold" label="threshold" format="number" value={baseline.threshold} error={errors["baseline.threshold"]}
          onValue={(value) => update("threshold", value)} />
        <InputField field="baseline.window_seconds" label="window" format="seconds" value={baseline.window_seconds} error={errors["baseline.window_seconds"]}
          onValue={(value) => update("window_seconds", value)} />
        <InputField field="baseline.frequency_seconds" label="frequency" format="seconds" value={baseline.frequency_seconds} error={errors["baseline.frequency_seconds"]}
          onValue={(value) => update("frequency_seconds", value)} />
      </div>
    </fieldset>
    <div class="form-grid" style={grid}>
      <SelectField field="parameter" label="evaluationParameter" value={draft.parameter} error={errors.parameter}
        choices={(["threshold", "window_seconds", "frequency_seconds"] as const).map((value) => ({ value, label: text(`parameter.${value}`) }))}
        onValue={(parameter) => {
          if (parameter === "threshold" || parameter === "window_seconds" || parameter === "frequency_seconds") {
            onDraft({ ...draft, parameter, proposed_value: "" });
          }
        }} />
      <InputField field="proposed_value" label="proposedValue" format={draft.parameter === "threshold" ? "number" : "seconds"}
        value={draft.proposed_value} error={errors.proposed_value} onValue={(proposed_value) => onDraft({ ...draft, proposed_value })} />
    </div>
    <p class="muted">{text("evaluationInputHelp")}</p>
    <p class="muted">{text("evaluationHelp")}</p>
  </>;
}

function DraftPreview({ draft, body }: { readonly draft: AlertProposalDraft; readonly body: AlertQualityProposal }) {
  const treatment = body.treatment;
  return <section class="stack-section" aria-label={text("draftPreview")}>
    <h4>{text("draftPreview")}</h4>
    <p class="muted">{text("draftPreviewHelp")}</p>
    <Facts>
      <Fact label={text("rule")}>{treatment.target_ref}</Fact>
      {treatment.kind === "routing" ? <>
        <Fact label={text("draftBefore")}>{treatment.remove_group_ref}</Fact>
        <Fact label={text("draftAfter")}>{treatment.replacement_group_ref}</Fact>
      </> : treatment.kind === "suppression" ? <>
        <Fact label={text("processingRule")}>{treatment.processing_rule_ref}</Fact>
        <Fact label={text("starts")}>{treatment.starts_at}</Fact>
        <Fact label={text("ends")}>{treatment.ends_at}</Fact>
      </> : draft.kind === "evaluation" ? <>
        <Fact label={text("evaluationParameter")}>{text(`parameter.${draft.parameter}`)}</Fact>
        <Fact label={text("draftBefore")}>{draft.baseline[draft.parameter]}</Fact>
        <Fact label={text("draftAfter")}>{String(treatment.evaluation[draft.parameter])}</Fact>
      </> : null}
    </Facts>
  </section>;
}
