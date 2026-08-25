import type { AuthContext } from "../auth";
import { GovernedCommandError, putGovernedJson } from "../governed-command";
import { decodeModelSettings, type ModelSettingsView } from "./settings-models.model";

export { GovernedCommandError as ModelSettingsCommandError };

export interface ModelBindingProposalReceipt {
  readonly proposalId: string;
  readonly acceptedAt: string;
  readonly duplicate: boolean;
  readonly state: "draft" | "assessment-requested" | "plan-requested";
  readonly policyDigest: string;
  readonly policyRevision: number;
  readonly executionAuthority: false;
  readonly activationBoundary: "protected-plan-only";
}

export async function saveNarratorPreference(
  auth: AuthContext,
  operatorApiBaseUrl: string,
  preferredNarratorModel: string,
  expectedRevision: number,
): Promise<ModelSettingsView> {
  return putModelSettings(auth, operatorApiBaseUrl, "/me/model-preferences", {
    preferred_narrator_model: preferredNarratorModel,
    expected_revision: expectedRevision,
  });
}

export async function saveWebSearchSettings(
  auth: AuthContext,
  operatorApiBaseUrl: string,
  input: {
    readonly enabled: boolean;
    readonly allowedDomains: readonly string[];
    readonly expectedRevision: number;
  },
): Promise<ModelSettingsView> {
  return putModelSettings(auth, operatorApiBaseUrl, "/models/web-search-settings", {
    enabled: input.enabled,
    allowed_domains: [...input.allowedDomains],
    expected_revision: input.expectedRevision,
  });
}

export async function saveModelBindingPolicy(
  auth: AuthContext,
  operatorApiBaseUrl: string,
  input: {
    readonly policy: Record<string, unknown>;
    readonly expectedRevision: number;
    readonly idempotencyKey: string;
  },
): Promise<ModelBindingProposalReceipt> {
  return decodeModelBindingProposalReceipt(await putGovernedJson(
    auth,
    operatorApiBaseUrl,
    "/models/binding-policy",
    {
      policy: input.policy,
      expected_revision: input.expectedRevision,
      idempotency_key: input.idempotencyKey,
    },
  ));
}

export async function requestModelBindingOperation(
  auth: AuthContext,
  operatorApiBaseUrl: string,
  operation: "assess" | "plan",
  input: {
    readonly environment: string;
    readonly policyRevision: number;
    readonly policyDigest: string;
    readonly idempotencyKey: string;
  },
): Promise<ModelBindingProposalReceipt> {
  return decodeModelBindingProposalReceipt(await putGovernedJson(
    auth,
    operatorApiBaseUrl,
    `/models/binding-policy/${operation}`,
    {
      environment: input.environment,
      policy_revision: input.policyRevision,
      policy_digest: input.policyDigest,
      idempotency_key: input.idempotencyKey,
    },
    "POST",
  ));
}

async function putModelSettings(
  auth: AuthContext,
  operatorApiBaseUrl: string,
  path: string,
  body: Record<string, unknown>,
): Promise<ModelSettingsView> {
  return decodeModelSettings(await putGovernedJson(auth, operatorApiBaseUrl, path, body));
}

export function decodeModelBindingProposalReceipt(value: unknown): ModelBindingProposalReceipt {
  const item = requiredObject(value, "model binding receipt");
  const proposalId = requiredString(item["proposal_id"], "proposal_id");
  const acceptedAt = requiredString(item["accepted_at"], "accepted_at");
  if (
    !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(acceptedAt)
    || Number.isNaN(Date.parse(acceptedAt))
  ) {
    throw new Error("model binding receipt accepted_at is invalid");
  }
  const duplicate = requiredBoolean(item["duplicate"], "duplicate");
  const state = requiredLiteral(item["state"], "state", [
    "draft",
    "assessment-requested",
    "plan-requested",
  ]) as ModelBindingProposalReceipt["state"];
  const policyDigest = requiredString(item["policy_digest"], "policy_digest");
  const policyRevision = requiredNonNegativeInteger(item["policy_revision"], "policy_revision");
  if (item["execution_authority"] !== false) {
    throw new Error("model binding receipt execution_authority MUST be false");
  }
  const activationBoundary = requiredLiteral(
    item["activation_boundary"],
    "activation_boundary",
    ["protected-plan-only"],
  ) as ModelBindingProposalReceipt["activationBoundary"];
  return {
    proposalId,
    acceptedAt,
    duplicate,
    state,
    policyDigest,
    policyRevision,
    executionAuthority: false,
    activationBoundary,
  };
}

function requiredObject(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} MUST be an object`);
  }
  return value as Record<string, unknown>;
}

function requiredString(value: unknown, label: string): string {
  if (typeof value !== "string") {
    throw new Error(`${label} MUST be a string`);
  }
  return value;
}

function requiredBoolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`${label} MUST be a boolean`);
  }
  return value;
}

function requiredNonNegativeInteger(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isInteger(value) || value < 0) {
    throw new Error(`${label} MUST be a non-negative integer`);
  }
  return value;
}

function requiredLiteral(value: unknown, label: string, allowed: readonly string[]): string {
  const parsed = requiredString(value, label);
  if (!allowed.includes(parsed)) {
    throw new Error(`${label} is invalid`);
  }
  return parsed;
}
