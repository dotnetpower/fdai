import { chatUrl, requestHeaders } from "./backend-endpoints";

export interface TestContextCommandStatus {
  readonly proposalId: string;
  readonly operation: "propose" | "review" | "revoke";
  readonly delivery: "pending" | "claimed" | "published" | "rejected";
  readonly acceptedAt: string;
  readonly policyApplication: "unknown" | "recorded";
  readonly currentAuthorization: "not_evaluated" | "unavailable" | "pending" | "revoked" | "expired";
  readonly application?: {
    readonly state: "proposed" | "reviewed" | "revoked";
    readonly revision: number;
  };
}

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? value as Record<string, unknown> : null;
}

export function validProposalId(value: string): boolean {
  return value.length > 0 && value.length <= 256 && value.trim() === value &&
    !/[\x00-\x1f\x7f]/.test(value);
}

/** Unknown, inconsistent, or authority-bearing projections are never rendered as success. */
export function decodeTestContextStatus(value: unknown, requestedId: string): TestContextCommandStatus | null {
  const status = record(value);
  const application = record(status?.context_application);
  const operation = status?.operation;
  const delivery = status?.dispatch_status;
  const policyApplication = status?.policy_application;
  const currentAuthorization = status?.current_authorization;
  const expectedState = operation === "test-context.propose" ? "proposed"
    : operation === "test-context.review" ? "reviewed"
    : operation === "test-context.revoke" ? "revoked" : null;
  if (!status || !validProposalId(requestedId) || status.proposal_id !== requestedId ||
    !expectedState || !["pending", "claimed", "published", "rejected"].includes(String(delivery)) ||
    typeof status.accepted_at !== "string" ||
    !/^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(status.accepted_at) ||
    !Number.isFinite(Date.parse(status.accepted_at)) ||
    !["unknown", "recorded"].includes(String(policyApplication)) ||
    !["not_evaluated", "unavailable", "pending", "revoked", "expired"].includes(String(currentAuthorization)) ||
    status.execution_authority !== false ||
    (policyApplication === "recorded") !== (application !== null) ||
    (policyApplication === "recorded" && delivery !== "published") ||
    (application && (application.execution_authority !== false ||
      application.state !== expectedState || !Number.isSafeInteger(application.revision) ||
      (application.revision as number) < 1))) return null;
  return {
    proposalId: requestedId,
    operation: (operation as string).slice("test-context.".length) as TestContextCommandStatus["operation"],
    delivery: delivery as TestContextCommandStatus["delivery"],
    acceptedAt: status.accepted_at,
    policyApplication: policyApplication as TestContextCommandStatus["policyApplication"],
    currentAuthorization: currentAuthorization as TestContextCommandStatus["currentAuthorization"],
    ...(application ? { application: {
      state: application.state as "proposed" | "reviewed" | "revoked",
      revision: application.revision as number,
    } } : {}),
  };
}

export type StatusReadResult =
  | { readonly kind: "ready"; readonly status: TestContextCommandStatus }
  | { readonly kind: "unavailable" | "error" };

/** Read only the authenticated requesting principal's command; do not poll or cache. */
export async function readTestContextStatus(proposalId: string, signal?: AbortSignal): Promise<StatusReadResult> {
  if (!validProposalId(proposalId)) return { kind: "error" };
  try {
    const response = await fetch(
      `${chatUrl().replace(/\/chat$/, "")}/test-context/commands/${encodeURIComponent(proposalId)}`,
      { headers: await requestHeaders(), cache: "no-store", ...(signal ? { signal } : {}) },
    );
    if ([404, 501].includes(response.status)) return { kind: "unavailable" };
    if (!response.ok) return { kind: "error" };
    const status = decodeTestContextStatus(await response.json(), proposalId);
    return status ? { kind: "ready", status } : { kind: "error" };
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    return { kind: "error" };
  }
}
