export type ProcessTransitionId = "resume" | "cancel" | "retry";

export interface ProcessTransition {
  readonly id: ProcessTransitionId;
  readonly method: "POST";
  readonly path: string;
  readonly expected_revision: number;
  readonly requires_confirmation: boolean;
  readonly runtime_recheck: true;
}

export interface ProcessControlProjection {
  readonly authoritative: true;
  readonly principal_scoped: true;
  readonly available: boolean;
  readonly process_revision: number;
  readonly catalog_revision: string | null;
  readonly mode: "shadow" | "enforce" | null;
  readonly reason: string | null;
  readonly step: {
    readonly id: string;
    readonly kind: string;
    readonly state: string;
    readonly attempt: number;
    readonly reason: string | null;
    readonly requirements: Readonly<Record<string, unknown>>;
  } | null;
  readonly permitted_transitions: readonly ProcessTransition[];
  readonly acceptance_is_success: false;
}

interface ProcessControlIdentity {
  readonly id: string;
  readonly current_step: string;
  readonly status: string;
  readonly revision: number;
}

export function decodeProcessControl(
  value: unknown,
  process: ProcessControlIdentity,
): ProcessControlProjection {
  if (value === undefined || value === null) {
    return {
      authoritative: true,
      principal_scoped: true,
      available: false,
      process_revision: process.revision,
      catalog_revision: null,
      mode: null,
      reason: "Authoritative Process transition projection is unavailable.",
      step: null,
      permitted_transitions: [],
      acceptance_is_success: false,
    };
  }
  const control = record(value, "process control");
  if (
    control["authoritative"] !== true
    || control["principal_scoped"] !== true
    || control["acceptance_is_success"] !== false
    || typeof control["available"] !== "boolean"
  ) {
    throw new Error(
      "process control MUST be authoritative, principal-scoped, and non-success-bearing",
    );
  }
  const processRevision = nonNegativeInteger(control, "process_revision", "process control");
  if (processRevision !== process.revision) {
    throw new Error("process control revision MUST match the Process revision");
  }
  if (control["available"] === false) {
    if (
      typeof control["reason"] !== "string"
      || !control["reason"]
      || control["step"] !== null
      || !Array.isArray(control["permitted_transitions"])
      || control["permitted_transitions"].length !== 0
    ) {
      throw new Error("unavailable process control MUST deny transitions with a reason");
    }
    return {
      authoritative: true,
      principal_scoped: true,
      available: false,
      process_revision: processRevision,
      catalog_revision: null,
      mode: null,
      reason: control["reason"],
      step: null,
      permitted_transitions: [],
      acceptance_is_success: false,
    };
  }
  const mode = control["mode"];
  if (mode !== "shadow" && mode !== "enforce") {
    throw new Error("available process control mode MUST be shadow or enforce");
  }
  const stepValue = record(control["step"], "process control step");
  const reason = stepValue["reason"];
  if (reason !== null && typeof reason !== "string") {
    throw new Error("process control step reason MUST be a string or null");
  }
  const step = {
    id: stringField(stepValue, "id", "process control step"),
    kind: stringField(stepValue, "kind", "process control step"),
    state: stringField(stepValue, "state", "process control step"),
    attempt: nonNegativeInteger(stepValue, "attempt", "process control step"),
    reason,
    requirements: record(stepValue["requirements"], "process control step requirements"),
  };
  if (step.id !== process.current_step || step.state !== process.status) {
    throw new Error("process control step MUST match the authoritative Process snapshot");
  }
  if (!Array.isArray(control["permitted_transitions"])) {
    throw new Error("process control permitted_transitions MUST be an array");
  }
  const transitions = control["permitted_transitions"].map((raw, index) =>
    decodeTransition(raw, index, process));
  if (new Set(transitions.map((transition) => transition.id)).size !== transitions.length) {
    throw new Error("process transition ids MUST be unique");
  }
  return {
    authoritative: true,
    principal_scoped: true,
    available: true,
    process_revision: processRevision,
    catalog_revision: stringField(control, "catalog_revision", "process control"),
    mode,
    reason: null,
    step,
    permitted_transitions: transitions,
    acceptance_is_success: false,
  };
}

function decodeTransition(
  value: unknown,
  index: number,
  process: ProcessControlIdentity,
): ProcessTransition {
  const transition = record(value, `process transitions[${index}]`);
  const id = transition["id"];
  if (!["resume", "cancel", "retry"].includes(String(id))) {
    throw new Error(`process transitions[${index}].id is unsupported`);
  }
  if (transition["method"] !== "POST") {
    throw new Error(`process transitions[${index}].method MUST be POST`);
  }
  const expectedRevision = nonNegativeInteger(
    transition,
    "expected_revision",
    `process transitions[${index}]`,
  );
  if (
    expectedRevision !== process.revision
    || typeof transition["requires_confirmation"] !== "boolean"
    || transition["runtime_recheck"] !== true
  ) {
    throw new Error("process transition MUST remain revision-bound and runtime-rechecked");
  }
  const path = stringField(transition, "path", `process transitions[${index}]`);
  if (path !== `/workflows/${process.id}/${String(id)}`) {
    throw new Error("process transition path does not match its operation");
  }
  return {
    id: id as ProcessTransitionId,
    method: "POST",
    path,
    expected_revision: expectedRevision,
    requires_confirmation: transition["requires_confirmation"],
    runtime_recheck: true,
  };
}

function record(value: unknown, label: string): Readonly<Record<string, unknown>> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} MUST be an object`);
  }
  return value as Readonly<Record<string, unknown>>;
}

function stringField(
  value: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): string {
  if (typeof value[key] !== "string") throw new Error(`${label}.${key} MUST be a string`);
  return value[key];
}

function nonNegativeInteger(
  value: Readonly<Record<string, unknown>>,
  key: string,
  label: string,
): number {
  const result = value[key];
  if (typeof result !== "number" || !Number.isInteger(result) || result < 0) {
    throw new Error(`${label}.${key} MUST be a non-negative integer`);
  }
  return result;
}
