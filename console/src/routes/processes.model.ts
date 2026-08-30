import { isOptionalOperatorApiUnavailable } from "../api";
import { panelPath } from "../router";

export interface ProcessSummary {
  readonly id: string;
  readonly workflow_ref: string;
  readonly workflow_version: string;
  readonly status: string;
  readonly current_step: string;
  readonly target_resource_id: string;
  readonly updated_at: string;
  readonly has_view: boolean;
}

export interface ProcessListResponse {
  readonly source: string;
  readonly synthetic: boolean | null;
  readonly durable: boolean | null;
  readonly items: readonly ProcessSummary[];
}

export interface ProcessRefreshCycle {
  readonly generation: number;
  readonly refreshing: boolean;
}

export type ProcessRefreshAction =
  | { readonly type: "start" }
  | { readonly type: "finish"; readonly generation: number };

export const INITIAL_PROCESS_REFRESH: ProcessRefreshCycle = {
  generation: 0,
  refreshing: false,
};

export function reduceProcessRefresh(
  state: ProcessRefreshCycle,
  action: ProcessRefreshAction,
): ProcessRefreshCycle {
  if (action.type === "start") {
    return state.refreshing
      ? state
      : { generation: state.generation + 1, refreshing: true };
  }
  return state.refreshing && action.generation === state.generation
    ? { ...state, refreshing: false }
    : state;
}

export interface ProcessEvent {
  readonly event_id: string;
  readonly kind: string;
  readonly recorded_at: string;
  readonly correlation_id: string;
  readonly causation_id: string | null;
  readonly step_id: string | null;
  readonly attempt: number;
  readonly payload: Readonly<Record<string, unknown>>;
}

export interface ProcessJournalResponse {
  readonly process: ProcessSummary & {
    readonly started_at: string;
    readonly correlation_id: string;
    readonly revision: number;
  };
  readonly events: readonly ProcessEvent[];
  readonly count: number;
  readonly planning: PlanningRoom | null;
  readonly investigation: InvestigationRoom | null;
}

export interface InvestigationExecution {
  readonly candidate_digest: string;
  readonly verification_receipt_digest: string;
  readonly plan_digest: string;
  readonly result_digest: string;
  readonly execution_digest: string;
  readonly query_status: string;
  readonly evidence_refs: readonly string[];
  readonly reserved_cost_units: number;
  readonly actual_cost_units: number | null;
}

export interface InvestigationRevision {
  readonly revision_digest: string;
  readonly active_hypothesis_ids: readonly string[];
  readonly active_set_receipt_digest: string;
  readonly disposition: string;
  readonly complete: boolean;
  readonly truncated: boolean;
  readonly evidence_refs: readonly string[];
}

export interface InvestigationRound {
  readonly round_index: number;
  readonly iteration_digest: string;
  readonly frame_digest: string;
  readonly evidence_cutoff: string;
  readonly graph_revision: string;
  readonly active_hypothesis_ids: readonly string[];
  readonly active_set_receipt_digest: string;
  readonly selection_digest: string;
  readonly selected_candidate_id: string | null;
  readonly separated_pair_count: number;
  readonly total_pair_count: number;
  readonly hold_reason: string | null;
  readonly shadow_comparison_digest: string | null;
  readonly execution: InvestigationExecution | null;
  readonly revision: InvestigationRevision | null;
}

export interface InvestigationRoom {
  readonly read_only: true;
  readonly mutation_controls: false;
  readonly process_revision: number;
  readonly process_id: string;
  readonly workflow_version: string;
  readonly incident_id: string;
  readonly initial_frame_digest: string;
  readonly initial_active_set_receipt_digest: string;
  readonly active_strategy_digest: string;
  readonly challenger_strategy_digest: string | null;
  readonly budget: {
    readonly max_rounds: number;
    readonly max_queries: number;
    readonly max_cost_units: number;
    readonly deadline_at: string;
    readonly policy_digest: string;
  };
  readonly rounds: readonly InvestigationRound[];
  readonly round_count: number;
  readonly terminal: {
    readonly result_digest: string;
    readonly disposition: string;
    readonly terminal_frame_digest: string;
    readonly terminal_active_set_receipt_digest: string;
    readonly used_queries: number;
    readonly used_cost_units: number;
  } | null;
  readonly closure: {
    readonly record_type: string;
    readonly reason: string;
  } | null;
}

export interface PlanningPhaseRecord {
  readonly phase: string;
  readonly actor_agent: string;
  readonly recorded_at: string;
  readonly event_id: string;
  readonly evidence_refs: readonly string[];
}

export interface PlanningExpectedEffect {
  readonly objective_id: string;
  readonly metric: string;
  readonly expected_min: number | null;
  readonly expected_max: number | null;
  readonly confidence: number | null;
}

export interface PlanningCandidate {
  readonly candidate_id: string;
  readonly action_type: string | null;
  readonly disposition: string;
  readonly reasons: readonly string[];
  readonly proposing_agents: readonly string[];
  readonly logic_receipt_refs: readonly string[];
  readonly simulation_receipt_refs: readonly string[];
  readonly constraint_evaluation_refs: readonly string[];
  readonly expected_effects: readonly PlanningExpectedEffect[];
}

export interface PlanningPlan {
  readonly plan_id: string;
  readonly logic_release_digest: string;
  readonly complete: boolean;
  readonly reason: string;
  readonly selected_option_id: string | null;
  readonly requires_human_approval: boolean;
  readonly margin: number | null;
  readonly candidates: readonly PlanningCandidate[];
}

export interface PlanningRoom {
  readonly current_phase: string;
  readonly phase_count: number;
  readonly phases: readonly PlanningPhaseRecord[];
  readonly plan: PlanningPlan | null;
}

export interface ProcessDetailData {
  readonly journal: ProcessJournalResponse;
  readonly view: RenderedProcessView | null;
}

export interface RenderedWidget {
  readonly id: string;
  readonly type: string;
  readonly title: string;
  readonly data: Readonly<Record<string, unknown>>;
  readonly options: Readonly<Record<string, unknown>>;
  readonly error?: string;
  readonly children?: readonly RenderedWidget[];
}

export interface RenderedReport {
  readonly id: string;
  readonly name: string;
  readonly description: string;
  readonly generated_at: string;
  readonly widgets: readonly RenderedWidget[];
}

export interface RenderedProcessView {
  readonly id: string;
  readonly version: string;
  readonly name: string;
  readonly description: string;
  readonly route: string;
  readonly process: ProcessSummary & {
    readonly started_at: string;
    readonly correlation_id: string;
    readonly revision: number;
  };
  readonly regions: readonly {
    readonly id: string;
    readonly column_span: number;
    readonly report: RenderedReport;
  }[];
}

export function processIdFromHash(hash: string): string | null {
  let normalized = hash;
  try {
    normalized = decodeURIComponent(hash);
  } catch {
    // Preserve the raw hash when a malformed percent escape is present.
  }
  const queryIndex = normalized.indexOf("?");
  if (queryIndex < 0) return null;
  return new URLSearchParams(normalized.slice(queryIndex + 1)).get("process");
}

export function processHref(processId: string): string {
  return `${panelPath("processes")}/${encodeURIComponent(processId)}`;
}

export function processEventHref(processId: string, eventId: string): string {
  const search = new URLSearchParams({ event: eventId });
  return `${processHref(processId)}?${search.toString()}`;
}

export function processTone(status: string): "success" | "warning" | "danger" | "info" {
  if (["succeeded", "approved", "ready", "compensated"].includes(status)) return "success";
  if (["failed", "rejected", "cancelled", "timed_out", "blocked"].includes(status)) return "danger";
  if (["waiting", "conditional", "pending"].includes(status)) return "warning";
  return "info";
}

export function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function defaultProcessId(
  items: readonly ProcessSummary[],
  currentHash: string,
): string | null {
  return processIdFromHash(currentHash) ?? items[0]?.id ?? null;
}

export function decodeProcessList(value: unknown): ProcessListResponse {
  const root = record(value, "process list");
  if (!Array.isArray(root["items"])) throw new Error("process list items MUST be an array");
  const synthetic = root["synthetic"];
  const durable = root["durable"];
  if (synthetic !== undefined && synthetic !== null && typeof synthetic !== "boolean") {
    throw new Error("process list synthetic MUST be boolean or null");
  }
  if (durable !== undefined && durable !== null && typeof durable !== "boolean") {
    throw new Error("process list durable MUST be boolean or null");
  }
  const items = root["items"].map((item, index) => decodeSummary(item, `items[${index}]`));
  assertUnique(items.map((item) => item.id), "process list item ids");
  return {
    source: typeof root["source"] === "string" ? root["source"] : "unknown",
    synthetic: synthetic === undefined ? null : synthetic,
    durable: durable === undefined ? null : durable,
    items,
  };
}

export function decodeProcessJournal(value: unknown): ProcessJournalResponse {
  const root = record(value, "process journal");
  const process = record(root["process"], "process journal process");
  if (!Array.isArray(root["events"])) throw new Error("process journal events MUST be an array");
  const events = root["events"].map((value, index) => decodeProcessEvent(value, `events[${index}]`));
  assertUnique(events.map((event) => event.event_id), "process journal event ids");
  const count = nonNegativeIntegerField(root, "count", "process journal");
  if (count !== events.length) throw new Error("process journal.count MUST equal the returned event count");
  const decodedProcess = {
    ...decodeSummary(process, "process journal process"),
    started_at: stringField(process, "started_at", "process journal process"),
    correlation_id: stringField(process, "correlation_id", "process journal process"),
    revision: nonNegativeIntegerField(process, "revision", "process journal process"),
  };
  if (events.some((event) => event.correlation_id !== decodedProcess.correlation_id)) {
    throw new Error("process journal events MUST match the process correlation_id");
  }
  const planning = root["planning"] === undefined || root["planning"] === null
    ? null
    : decodePlanningRoom(root["planning"]);
  const investigation = root["investigation"] === undefined || root["investigation"] === null
    ? null
    : decodeInvestigationRoom(root["investigation"]);
  if (investigation !== null && investigation.process_revision !== decodedProcess.revision) {
    throw new Error("investigation room process_revision MUST match the process revision");
  }
  if (investigation !== null && investigation.process_id !== decodedProcess.id) {
    throw new Error("investigation room process_id MUST match the process identity");
  }
  if (
    investigation !== null
    && investigation.workflow_version !== decodedProcess.workflow_version
  ) {
    throw new Error("investigation room workflow_version MUST match the process");
  }
  return {
    process: decodedProcess,
    events,
    count,
    planning,
    investigation,
  };
}

function decodeInvestigationRoom(value: unknown): InvestigationRoom {
  const root = record(value, "investigation room");
  if (root["read_only"] !== true || root["mutation_controls"] !== false) {
    throw new Error("investigation room MUST be read-only without mutation controls");
  }
  if (!Array.isArray(root["rounds"])) throw new Error("investigation room rounds MUST be an array");
  const rounds = root["rounds"].map((item, index) => decodeInvestigationRound(item, index));
  const roundCount = nonNegativeIntegerField(root, "round_count", "investigation room");
  if (roundCount !== rounds.length) throw new Error("investigation room round_count MUST match rounds");
  if (rounds.some((round, index) => round.round_index !== index + 1)) {
    throw new Error("investigation room rounds MUST be contiguous");
  }
  const budget = record(root["budget"], "investigation room budget");
  return {
    read_only: true,
    mutation_controls: false,
    process_revision: nonNegativeIntegerField(root, "process_revision", "investigation room"),
    process_id: stringField(root, "process_id", "investigation room"),
    workflow_version: stringField(root, "workflow_version", "investigation room"),
    incident_id: stringField(root, "incident_id", "investigation room"),
    initial_frame_digest: digestField(root, "initial_frame_digest", "investigation room"),
    initial_active_set_receipt_digest: digestField(root, "initial_active_set_receipt_digest", "investigation room"),
    active_strategy_digest: digestField(root, "active_strategy_digest", "investigation room"),
    challenger_strategy_digest: nullableDigest(root["challenger_strategy_digest"], "investigation challenger strategy"),
    budget: {
      max_rounds: nonNegativeIntegerField(budget, "max_rounds", "investigation room budget"),
      max_queries: nonNegativeIntegerField(budget, "max_queries", "investigation room budget"),
      max_cost_units: nonNegativeIntegerField(budget, "max_cost_units", "investigation room budget"),
      deadline_at: stringField(budget, "deadline_at", "investigation room budget"),
      policy_digest: digestField(budget, "policy_digest", "investigation room budget"),
    },
    rounds,
    round_count: roundCount,
    terminal: root["terminal"] === null ? null : decodeInvestigationTerminal(root["terminal"]),
    closure: root["closure"] === null || root["closure"] === undefined
      ? null
      : decodeInvestigationClosure(root["closure"]),
  };
}

function decodeInvestigationClosure(
  value: unknown,
): NonNullable<InvestigationRoom["closure"]> {
  const item = record(value, "investigation closure");
  return {
    record_type: stringField(item, "record_type", "investigation closure"),
    reason: stringField(item, "reason", "investigation closure"),
  };
}

function decodeInvestigationRound(value: unknown, index: number): InvestigationRound {
  const label = `investigation rounds[${index}]`;
  const round = record(value, label);
  return {
    round_index: nonNegativeIntegerField(round, "round_index", label),
    iteration_digest: digestField(round, "iteration_digest", label),
    frame_digest: digestField(round, "frame_digest", label),
    evidence_cutoff: stringField(round, "evidence_cutoff", label),
    graph_revision: stringField(round, "graph_revision", label),
    active_hypothesis_ids: stringArray(round["active_hypothesis_ids"], `${label}.active_hypothesis_ids`),
    active_set_receipt_digest: digestField(round, "active_set_receipt_digest", label),
    selection_digest: digestField(round, "selection_digest", label),
    selected_candidate_id: nullableString(round["selected_candidate_id"], `${label}.selected_candidate_id`),
    separated_pair_count: nonNegativeIntegerField(round, "separated_pair_count", label),
    total_pair_count: nonNegativeIntegerField(round, "total_pair_count", label),
    hold_reason: nullableString(round["hold_reason"], `${label}.hold_reason`),
    shadow_comparison_digest: nullableDigest(
      round["shadow_comparison_digest"],
      `${label}.shadow_comparison_digest`,
    ),
    execution: round["execution"] === null ? null : decodeInvestigationExecution(round["execution"], label),
    revision: round["revision"] === null ? null : decodeInvestigationRevision(round["revision"], label),
  };
}

function decodeInvestigationExecution(value: unknown, parent: string): InvestigationExecution {
  const item = record(value, `${parent}.execution`);
  return {
    candidate_digest: digestField(item, "candidate_digest", `${parent}.execution`),
    verification_receipt_digest: digestField(item, "verification_receipt_digest", `${parent}.execution`),
    plan_digest: digestField(item, "plan_digest", `${parent}.execution`),
    result_digest: digestField(item, "result_digest", `${parent}.execution`),
    execution_digest: digestField(item, "execution_digest", `${parent}.execution`),
    query_status: stringField(item, "query_status", `${parent}.execution`),
    evidence_refs: stringArray(item["evidence_refs"], `${parent}.execution.evidence_refs`),
    reserved_cost_units: nonNegativeIntegerField(item, "reserved_cost_units", `${parent}.execution`),
    actual_cost_units: nullableNonNegativeInteger(item["actual_cost_units"], `${parent}.execution.actual_cost_units`),
  };
}

function decodeInvestigationRevision(value: unknown, parent: string): InvestigationRevision {
  const item = record(value, `${parent}.revision`);
  return {
    revision_digest: digestField(item, "revision_digest", `${parent}.revision`),
    active_hypothesis_ids: stringArray(item["active_hypothesis_ids"], `${parent}.revision.active_hypothesis_ids`),
    active_set_receipt_digest: digestField(item, "active_set_receipt_digest", `${parent}.revision`),
    disposition: stringField(item, "disposition", `${parent}.revision`),
    complete: booleanField(item, "complete", `${parent}.revision`),
    truncated: booleanField(item, "truncated", `${parent}.revision`),
    evidence_refs: stringArray(item["evidence_refs"], `${parent}.revision.evidence_refs`),
  };
}

function decodeInvestigationTerminal(value: unknown): NonNullable<InvestigationRoom["terminal"]> {
  const item = record(value, "investigation terminal");
  return {
    result_digest: digestField(item, "result_digest", "investigation terminal"),
    disposition: stringField(item, "disposition", "investigation terminal"),
    terminal_frame_digest: digestField(item, "terminal_frame_digest", "investigation terminal"),
    terminal_active_set_receipt_digest: digestField(item, "terminal_active_set_receipt_digest", "investigation terminal"),
    used_queries: nonNegativeIntegerField(item, "used_queries", "investigation terminal"),
    used_cost_units: nonNegativeIntegerField(item, "used_cost_units", "investigation terminal"),
  };
}

function decodePlanningRoom(value: unknown): PlanningRoom {
  const root = record(value, "planning room");
  if (!Array.isArray(root["phases"])) throw new Error("planning room phases MUST be an array");
  const phases = root["phases"].map((value, index) => {
    const phase = record(value, `planning room phases[${index}]`);
    return {
      phase: stringField(phase, "phase", `planning room phases[${index}]`),
      actor_agent: stringField(phase, "actor_agent", `planning room phases[${index}]`),
      recorded_at: stringField(phase, "recorded_at", `planning room phases[${index}]`),
      event_id: stringField(phase, "event_id", `planning room phases[${index}]`),
      evidence_refs: stringArray(phase["evidence_refs"], `planning room phases[${index}].evidence_refs`),
    };
  });
  const phaseCount = nonNegativeIntegerField(root, "phase_count", "planning room");
  if (phaseCount !== phases.length) throw new Error("planning room phase_count MUST match phases");
  return {
    current_phase: stringField(root, "current_phase", "planning room"),
    phase_count: phaseCount,
    phases,
    plan: root["plan"] === null ? null : decodePlanningPlan(root["plan"]),
  };
}

function decodePlanningPlan(value: unknown): PlanningPlan {
  const plan = record(value, "planning plan");
  if (!Array.isArray(plan["candidates"])) throw new Error("planning candidates MUST be an array");
  const selected = plan["selected_option_id"];
  if (selected !== null && typeof selected !== "string") {
    throw new Error("planning selected_option_id MUST be a string or null");
  }
  const margin = nullableFiniteNumber(plan["margin"], "planning margin");
  const candidates = plan["candidates"].map((value, index) => decodePlanningCandidate(value, index));
  assertUnique(candidates.map((candidate) => candidate.candidate_id), "planning candidate ids");
  if (selected !== null && !candidates.some((candidate) => candidate.candidate_id === selected)) {
    throw new Error("planning selection MUST reference a returned candidate");
  }
  return {
    plan_id: stringField(plan, "plan_id", "planning plan"),
    logic_release_digest: stringField(plan, "logic_release_digest", "planning plan"),
    complete: booleanField(plan, "complete", "planning plan"),
    reason: stringField(plan, "reason", "planning plan"),
    selected_option_id: selected,
    requires_human_approval: booleanField(plan, "requires_human_approval", "planning plan"),
    margin,
    candidates,
  };
}

function decodePlanningCandidate(value: unknown, index: number): PlanningCandidate {
  const label = `planning candidates[${index}]`;
  const candidate = record(value, label);
  const actionType = candidate["action_type"];
  if (actionType !== null && typeof actionType !== "string") {
    throw new Error(`${label}.action_type MUST be a string or null`);
  }
  if (!Array.isArray(candidate["expected_effects"])) {
    throw new Error(`${label}.expected_effects MUST be an array`);
  }
  return {
    candidate_id: stringField(candidate, "candidate_id", label),
    action_type: actionType,
    disposition: stringField(candidate, "disposition", label),
    reasons: stringArray(candidate["reasons"], `${label}.reasons`),
    proposing_agents: stringArray(candidate["proposing_agents"], `${label}.proposing_agents`),
    logic_receipt_refs: stringArray(candidate["logic_receipt_refs"], `${label}.logic_receipt_refs`),
    simulation_receipt_refs: stringArray(candidate["simulation_receipt_refs"], `${label}.simulation_receipt_refs`),
    constraint_evaluation_refs: stringArray(candidate["constraint_evaluation_refs"], `${label}.constraint_evaluation_refs`),
    expected_effects: candidate["expected_effects"].map((value, effectIndex) => {
      const effectLabel = `${label}.expected_effects[${effectIndex}]`;
      const effect = record(value, effectLabel);
      return {
        objective_id: stringField(effect, "objective_id", effectLabel),
        metric: stringField(effect, "metric", effectLabel),
        expected_min: nullableFiniteNumber(effect["expected_min"], `${effectLabel}.expected_min`),
        expected_max: nullableFiniteNumber(effect["expected_max"], `${effectLabel}.expected_max`),
        confidence: nullableFiniteNumber(effect["confidence"], `${effectLabel}.confidence`),
      };
    }),
  };
}

export function decodeRenderedProcessView(value: unknown): RenderedProcessView {
  const root = record(value, "process view");
  const process = record(root["process"], "process view process");
  if (!Array.isArray(root["regions"])) throw new Error("process view regions MUST be an array");
  const regions = root["regions"].map((item, index) => {
      const region = record(item, `regions[${index}]`);
      const report = record(region["report"], `regions[${index}].report`);
      if (!Array.isArray(report["widgets"])) {
        throw new Error(`regions[${index}].report widgets MUST be an array`);
      }
      const widgets = report["widgets"].map((widget, widgetIndex) =>
        decodeRenderedWidget(widget, `regions[${index}].report.widgets[${widgetIndex}]`));
      assertUnique(widgets.map((widget) => widget.id), `regions[${index}].report widget ids`);
      const columnSpan = nonNegativeIntegerField(region, "column_span", `regions[${index}]`);
      if (columnSpan < 1 || columnSpan > 12) {
        throw new Error(`regions[${index}].column_span MUST be between 1 and 12`);
      }
      return {
        id: stringField(region, "id", `regions[${index}]`),
        column_span: columnSpan,
        report: {
          id: stringField(report, "id", `regions[${index}].report`),
          name: stringField(report, "name", `regions[${index}].report`),
          description: stringField(report, "description", `regions[${index}].report`),
          generated_at: stringField(report, "generated_at", `regions[${index}].report`),
          widgets,
        },
      };
    });
  assertUnique(regions.map((region) => region.id), "process view region ids");
  return {
    id: stringField(root, "id", "process view"),
    version: stringField(root, "version", "process view"),
    name: stringField(root, "name", "process view"),
    description: stringField(root, "description", "process view"),
    route: stringField(root, "route", "process view"),
    process: {
      ...decodeSummary(process, "process view process", false),
      started_at: stringField(process, "started_at", "process view process"),
      correlation_id: stringField(process, "correlation_id", "process view process"),
      revision: nonNegativeIntegerField(process, "revision", "process view process"),
    },
    regions,
  };
}

export function assertProcessDetailSelection(
  selectedId: string,
  journal: ProcessJournalResponse,
  view: RenderedProcessView | null,
): void {
  if (journal.process.id !== selectedId) {
    throw new Error("process journal id does not match the selected process");
  }
  if (view !== null && view.process.id !== selectedId) {
    throw new Error("rendered process view id does not match the selected process");
  }
}

export function processListFailure(error: unknown):
  | { readonly status: "unavailable"; readonly message: string }
  | { readonly status: "error"; readonly message: string } {
  if (isOptionalOperatorApiUnavailable(error)) {
    return {
      status: "unavailable",
      message: "Process projections are not wired on this deployment.",
    };
  }
  return {
    status: "error",
    message: error instanceof Error ? error.message : String(error),
  };
}

function decodeSummary(value: unknown, label: string, requireHasView = true): ProcessSummary {
  const item = record(value, label);
  return {
    id: stringField(item, "id", label),
    workflow_ref: stringField(item, "workflow_ref", label),
    workflow_version: stringField(item, "workflow_version", label),
    status: stringField(item, "status", label),
    current_step: stringField(item, "current_step", label),
    target_resource_id: stringField(item, "target_resource_id", label),
    updated_at: stringField(item, "updated_at", label),
    has_view: requireHasView ? booleanField(item, "has_view", label) : true,
  };
}

function decodeProcessEvent(value: unknown, label: string): ProcessEvent {
  const event = record(value, label);
  const causationId = event["causation_id"];
  const stepId = event["step_id"];
  if (causationId !== null && typeof causationId !== "string") {
    throw new Error(`${label}.causation_id MUST be a string or null`);
  }
  if (stepId !== null && typeof stepId !== "string") {
    throw new Error(`${label}.step_id MUST be a string or null`);
  }
  return {
    event_id: stringField(event, "event_id", label),
    kind: stringField(event, "kind", label),
    recorded_at: stringField(event, "recorded_at", label),
    correlation_id: stringField(event, "correlation_id", label),
    causation_id: causationId,
    step_id: stepId,
    attempt: nonNegativeIntegerField(event, "attempt", label),
    payload: record(event["payload"], `${label}.payload`),
  };
}

export function decodeRenderedWidget(value: unknown, label: string): RenderedWidget {
  const widget = record(value, label);
  const children = widget["children"];
  if (children !== undefined && !Array.isArray(children)) {
    throw new Error(`${label} children MUST be an array`);
  }
  return {
    id: stringField(widget, "id", label),
    type: stringField(widget, "type", label),
    title: stringField(widget, "title", label),
    data: record(widget["data"], `${label}.data`),
    options: record(widget["options"], `${label}.options`),
    ...(typeof widget["error"] === "string" ? { error: widget["error"] } : {}),
    ...(children ? { children: children.map((child, index) => decodeRenderedWidget(child, `${label}.children[${index}]`)) } : {}),
  };
}

function record(value: unknown, label: string): Readonly<Record<string, unknown>> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} MUST be an object`);
  }
  return value as Readonly<Record<string, unknown>>;
}

function stringField(value: Readonly<Record<string, unknown>>, key: string, label: string): string {
  if (typeof value[key] !== "string") throw new Error(`${label}.${key} MUST be a string`);
  return value[key];
}

function nullableString(value: unknown, label: string): string | null {
  if (value === null) return null;
  if (typeof value !== "string") throw new Error(`${label} MUST be a string or null`);
  return value;
}

function digestField(value: Readonly<Record<string, unknown>>, key: string, label: string): string {
  const result = stringField(value, key, label);
  if (!/^sha256:[a-f0-9]{64}$/.test(result)) {
    throw new Error(`${label}.${key} MUST be a SHA-256 digest`);
  }
  return result;
}

function nullableDigest(value: unknown, label: string): string | null {
  if (value === null) return null;
  if (typeof value !== "string" || !/^sha256:[a-f0-9]{64}$/.test(value)) {
    throw new Error(`${label} MUST be a SHA-256 digest or null`);
  }
  return value;
}

function numberField(value: Readonly<Record<string, unknown>>, key: string, label: string): number {
  if (typeof value[key] !== "number" || !Number.isFinite(value[key])) {
    throw new Error(`${label}.${key} MUST be a finite number`);
  }
  return value[key];
}

function nonNegativeIntegerField(value: Readonly<Record<string, unknown>>, key: string, label: string): number {
  const result = numberField(value, key, label);
  if (!Number.isInteger(result) || result < 0) {
    throw new Error(`${label}.${key} MUST be a non-negative integer`);
  }
  return result;
}

function assertUnique(values: readonly string[], label: string): void {
  if (new Set(values).size !== values.length) throw new Error(`${label} MUST be unique`);
}

function booleanField(value: Readonly<Record<string, unknown>>, key: string, label: string): boolean {
  if (typeof value[key] !== "boolean") throw new Error(`${label}.${key} MUST be a boolean`);
  return value[key];
}

function stringArray(value: unknown, label: string): readonly string[] {
  if (!Array.isArray(value) || value.some((item) => typeof item !== "string")) {
    throw new Error(`${label} MUST be a string array`);
  }
  return value;
}

function nullableFiniteNumber(value: unknown, label: string): number | null {
  if (value === null) return null;
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${label} MUST be a finite number or null`);
  }
  return value;
}

function nullableNonNegativeInteger(value: unknown, label: string): number | null {
  if (value === null) return null;
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new Error(`${label} MUST be a non-negative integer or null`);
  }
  return value;
}
