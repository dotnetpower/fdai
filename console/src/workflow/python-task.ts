import type { AuthContext } from "../auth";
import { loadConfig } from "../config";

export type PythonTaskCapability =
  | "gpu"
  | "network"
  | "filesystem_read"
  | "filesystem_write"
  | "process";

export interface PythonTaskOperations {
  readonly generate: boolean;
  readonly validate: boolean;
  readonly stage: boolean;
  readonly test: boolean;
  readonly request_run: boolean;
  readonly schedule: boolean;
}

export interface PythonTaskAvailability {
  readonly available: true;
  readonly operations: PythonTaskOperations;
}

export interface PythonTaskFileDraft {
  readonly path: string;
  readonly content: string;
}

export interface PythonTaskDraft {
  readonly task_id: string;
  readonly version: string;
  readonly entrypoint: string;
  readonly files: readonly PythonTaskFileDraft[];
  readonly required_modules: readonly string[];
  readonly capabilities: readonly PythonTaskCapability[];
  readonly timeout_seconds: number;
  readonly python_executable: string;
}

export interface PythonTaskValidationIssue {
  readonly code: string;
  readonly path: string;
  readonly message: string;
}

export interface PythonTaskValidation {
  readonly valid: boolean;
  readonly artifact_hash: string;
  readonly artifact_ref: string | null;
  readonly detected_capabilities: readonly string[];
  readonly imported_modules: readonly string[];
  readonly issues: readonly PythonTaskValidationIssue[];
  readonly staged?: boolean;
}

export interface PythonTaskPlanResponse extends PythonTaskValidation {
  readonly plan: {
    readonly run_ref: string;
    readonly status: string;
    readonly detail: string;
    readonly target_resource_ref: string;
    readonly target_capabilities: readonly string[];
    readonly files_would_copy: number;
    readonly bytes_would_copy: number;
  };
}

export interface PythonTaskRunRequestResponse {
  readonly submitted: boolean;
  readonly correlation_id: string;
  readonly action_type: string;
  readonly artifact_ref: string;
  readonly target_resource_ref: string;
}

export interface PythonTaskScheduleResponse {
  readonly scheduled: boolean;
  readonly task_id: string;
  readonly workflow_ref: string;
  readonly artifact_ref: string;
  readonly target_resource_ref: string;
  readonly cron_expression: string;
  readonly event_type: string;
}

export interface PythonTaskGenerationResponse {
  readonly task: PythonTaskDraft;
  readonly validation: PythonTaskValidation;
}

export function pythonTaskDraftKey(task: PythonTaskDraft): string {
  return JSON.stringify(task);
}

export function decodePythonTaskAvailability(value: unknown): PythonTaskAvailability {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error("Python task capability API returned an invalid response.");
  }
  const record = value as Record<string, unknown>;
  const operations = record["operations"];
  if (
    record["available"] !== true
    || operations === null
    || typeof operations !== "object"
    || Array.isArray(operations)
  ) {
    throw new Error("Python task capability API returned an invalid response.");
  }
  const operationRecord = operations as Record<string, unknown>;
  const keys = ["generate", "validate", "stage", "test", "request_run", "schedule"] as const;
  if (keys.some((key) => typeof operationRecord[key] !== "boolean")) {
    throw new Error("Python task capability API returned an invalid response.");
  }
  return {
    available: true,
    operations: {
      generate: operationRecord["generate"] as boolean,
      validate: operationRecord["validate"] as boolean,
      stage: operationRecord["stage"] as boolean,
      test: operationRecord["test"] as boolean,
      request_run: operationRecord["request_run"] as boolean,
      schedule: operationRecord["schedule"] as boolean,
    },
  };
}

export function pythonTaskGenerationCanApply(currentRevision: number, submittedRevision: number): boolean {
  return currentRevision === submittedRevision;
}

let authContext: AuthContext | null = null;

export function setPythonTaskAuth(auth: AuthContext | null): void {
  authContext = auth;
}

export function newPythonTaskRunIdempotencyKey(): string {
  return globalThis.crypto.randomUUID();
}

export async function validatePythonTask(
  task: PythonTaskDraft,
): Promise<PythonTaskValidation> {
  return post<PythonTaskValidation>("/python-tasks/validate", task);
}

export async function generatePythonTask(args: {
  readonly intent: string;
  readonly taskIdHint: string;
  readonly targetResourceRef: string;
  readonly allowedModules: readonly string[];
}): Promise<PythonTaskGenerationResponse> {
  return post<PythonTaskGenerationResponse>("/python-tasks/generate", {
    intent: args.intent,
    task_id_hint: args.taskIdHint,
    target_resource_ref: args.targetResourceRef,
    allowed_modules: args.allowedModules,
  });
}

export async function stagePythonTask(
  task: PythonTaskDraft,
): Promise<PythonTaskValidation> {
  return post<PythonTaskValidation>("/python-tasks/stage", task);
}

export async function testPythonTask(
  task: PythonTaskDraft,
  targetResourceRef: string,
): Promise<PythonTaskPlanResponse> {
  return post<PythonTaskPlanResponse>("/python-tasks/test", {
    task,
    target_resource_ref: targetResourceRef,
  });
}

export async function requestPythonTaskRun(args: {
  readonly artifactRef: string;
  readonly targetResourceRef: string;
  readonly reason: string;
  readonly idempotencyKey: string;
}): Promise<PythonTaskRunRequestResponse> {
  return post<PythonTaskRunRequestResponse>("/python-tasks/request-run", {
    artifact_ref: args.artifactRef,
    target_resource_ref: args.targetResourceRef,
    reason: args.reason,
    idempotency_key: args.idempotencyKey,
  });
}

export async function schedulePythonTask(args: {
  readonly artifactRef: string;
  readonly targetResourceRef: string;
  readonly workflowRef: string;
  readonly cronExpression: string;
}): Promise<PythonTaskScheduleResponse> {
  return post<PythonTaskScheduleResponse>("/python-tasks/schedule", {
    artifact_ref: args.artifactRef,
    target_resource_ref: args.targetResourceRef,
    workflow_ref: args.workflowRef,
    cron_expression: args.cronExpression,
  });
}

async function post<T>(path: string, payload: unknown): Promise<T> {
  const config = loadConfig();
  const base = config.operatorApiBaseUrl || (typeof window !== "undefined" ? window.location.origin : "");
  const headers: Record<string, string> = {
    "content-type": "application/json",
    accept: "application/json",
  };
  const authorization = authContext ? await authContext.getAuthorizationHeader() : null;
  if (authorization) headers["authorization"] = authorization;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 30_000);
  let response: Response;
  try {
    response = await fetch(`${base.replace(/\/$/, "")}${path}`, {
      method: "POST",
      headers,
      body: JSON.stringify(payload),
      credentials: "omit",
      signal: controller.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new Error("Python task request timed out.");
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
  const body = await response.json().catch(() => null) as unknown;
  if (!response.ok) {
    const detail = errorDetail(body) ?? `HTTP ${response.status}`;
    const validation = body as Partial<PythonTaskValidation> | null;
    if (response.status === 422 && validation?.issues) return body as T;
    throw new Error(detail);
  }
  if (body === null || typeof body !== "object" || Array.isArray(body)) {
    throw new Error("Python task API returned an invalid response.");
  }
  return body as T;
}

function errorDetail(value: unknown): string | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  const detail = (value as Record<string, unknown>)["error"] ?? (value as Record<string, unknown>)["detail"];
  if (typeof detail === "string") return detail;
  if (detail && typeof detail === "object" && !Array.isArray(detail)) {
    const message = (detail as Record<string, unknown>)["message"];
    return typeof message === "string" ? message : null;
  }
  return null;
}
