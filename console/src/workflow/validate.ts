/**
 * Workflow authoring client - the one non-GET call the console makes,
 * kept OUT of the GET-only `ReadApiClient` exactly like the chat backend
 * (`deck/backend.ts`).
 *
 * `POST /workflows/validate` is a pure, read-only validation: it runs the
 * server-side workflow loader against a draft and returns the aggregated
 * issues plus a canonical YAML preview. It writes no state and never
 * creates a PR - the operator copies the previewed YAML into a
 * remediation PR through the git-native path (app-shape.instructions.md
 * § Operator console). The `ActionType` palette itself is a plain GET and
 * is fetched through `ReadApiClient.panel`.
 *
 * Auth: the signed-in operator's bearer token is threaded here through a
 * module singleton set once at app init (mirroring `deck/deck-user.ts`),
 * so the Reader-gated route authenticates in production while dev mode
 * (no token) still works.
 */

import type { AuthContext } from "../auth";
import { loadConfig } from "../config";

/** One ActionType the builder maps a step onto. */
export interface ActionTypePaletteEntry {
  readonly name: string;
  readonly operation: string;
  readonly category: string | null;
  readonly rollback_contract: string;
  readonly irreversible: boolean;
  readonly default_mode: string;
  readonly execution_path: string | null;
  readonly env_scope: string;
  /** Tiers (T0/T1/T2) whose ceiling escalates this action to HIL. */
  readonly hil_tiers: readonly string[];
  readonly description: string | null;
}

export interface ActionTypePaletteResponse {
  readonly action_types: readonly ActionTypePaletteEntry[];
  readonly count: number;
}

/** One step of a built-in workflow (read-only catalog projection). */
export interface WorkflowCatalogStep {
  readonly id: string;
  readonly action_type_ref: string;
  readonly guard_rule_ref?: string;
  readonly compensated_by?: string;
  readonly on_failure?: string;
  readonly params?: Record<string, string | number | boolean>;
}

/** One built-in workflow with its full read-only content. */
export interface WorkflowCatalogEntry {
  readonly schema_version: string;
  readonly name: string;
  readonly version: string;
  readonly description?: string;
  readonly trigger: {
    readonly kind: string;
    readonly signal_type?: string;
    readonly schedule?: string;
  };
  readonly default_mode: string;
  readonly promotion_gate: {
    readonly min_shadow_days: number;
    readonly min_samples: number;
    readonly min_accuracy: number;
    readonly max_policy_escapes: number;
  };
  readonly steps: readonly WorkflowCatalogStep[];
  readonly anti_scope?: string;
  readonly step_count: number;
  readonly yaml: string;
}

export interface WorkflowCatalogResponse {
  readonly workflows: readonly WorkflowCatalogEntry[];
  readonly count: number;
}

/** One validation issue keyed to a draft path. */
export interface WorkflowIssue {
  readonly key: string;
  readonly message: string;
}

export interface ValidateResponse {
  readonly valid: boolean;
  readonly issues: readonly WorkflowIssue[];
  readonly yaml_preview: string | null;
}

let authContext: AuthContext | null = null;

/** Set once at app init so the validate POST can attach the bearer token. */
export function setWorkflowAuth(auth: AuthContext | null): void {
  authContext = auth;
}

function validateUrl(): string {
  const cfg = loadConfig();
  const base =
    cfg.readApiBaseUrl || (typeof window !== "undefined" ? window.location.origin : "");
  return `${base.replace(/\/$/, "")}/workflows/validate`;
}

/**
 * Validate a draft Workflow mapping server-side. Returns the structured
 * validation result. Throws only on a transport / non-validation error
 * (e.g. 404 when the route is not wired, network failure); a well-formed
 * draft that fails validation resolves with `valid: false`.
 */
export async function validateWorkflowDraft(
  draft: Record<string, unknown>,
): Promise<ValidateResponse> {
  const headers: Record<string, string> = {
    "content-type": "application/json",
    accept: "application/json",
  };
  const authHeader = authContext ? await authContext.getAuthorizationHeader() : null;
  if (authHeader !== null) headers["authorization"] = authHeader;

  // Bound the request so a slow / hung server cannot leave the UI stuck in a
  // "Validating..." state forever.
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 15_000);
  let response: Response;
  try {
    response = await fetch(validateUrl(), {
      method: "POST",
      headers,
      body: JSON.stringify(draft),
      credentials: "omit",
      signal: controller.signal,
    });
  } catch (err) {
    if (err instanceof DOMException && err.name === "AbortError") {
      throw new Error("Validation timed out. Check the API and try again.");
    }
    throw err;
  } finally {
    clearTimeout(timeout);
  }
  if (response.status === 404) {
    throw new Error(
      "The workflow authoring route is not wired on this deployment. " +
        "Set ReadApiConfig.workflow_authoring in the composition root to enable it.",
    );
  }
  if (response.status === 413) {
    throw new Error("The draft is too large to validate. Reduce the number of steps.");
  }
  if (!response.ok) {
    let detail = `HTTP ${response.status}`;
    try {
      const body = (await response.json()) as { error?: string | { message?: string } };
      if (typeof body.error === "string" && body.error) detail = body.error;
      else if (typeof body.error === "object" && body.error?.message) detail = body.error.message;
    } catch {
      /* non-JSON body - keep the status message */
    }
    throw new Error(detail);
  }
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new Error("Workflow validation returned invalid JSON.");
  }
  if (body === null || typeof body !== "object" || Array.isArray(body)) {
    throw new Error("Workflow validation returned an invalid response.");
  }
  const value = body as Record<string, unknown>;
  if (typeof value.valid !== "boolean" || !Array.isArray(value.issues)) {
    throw new Error("Workflow validation returned an invalid response.");
  }
  if (value.yaml_preview !== null && typeof value.yaml_preview !== "string") {
    throw new Error("Workflow validation returned an invalid response.");
  }
  const issues = value.issues.map((issue) => {
    if (issue === null || typeof issue !== "object" || Array.isArray(issue)) {
      throw new Error("Workflow validation returned an invalid response.");
    }
    const record = issue as Record<string, unknown>;
    if (typeof record.key !== "string" || typeof record.message !== "string") {
      throw new Error("Workflow validation returned an invalid response.");
    }
    return { key: record.key, message: record.message };
  });
  return {
    valid: value.valid,
    issues,
    yaml_preview: value.yaml_preview,
  };
}
