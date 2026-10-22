import { OperatorApiError } from "./api-transport";
import type { OperatorApiClient } from "./api";

export interface StewardshipCandidate {
  readonly candidate_id: string;
  readonly candidate_digest: string;
  readonly title: string;
  readonly body: string;
  readonly yaml: string;
  readonly state: "open" | "activated";
  readonly recorded_at: string;
}

export interface StewardshipActivationBody {
  readonly candidate_id: string;
  readonly candidate_digest: string;
}

const CANDIDATE_ID = /^[0-9a-f]{16}$/;
const DIGEST = /^[0-9a-f]{64}$/;

function text(value: unknown, label: string): string {
  if (typeof value !== "string") throw new Error(`stewardship candidate ${label} is malformed`);
  return value;
}

/** Decode the Core-written candidate projection; a malformed item fails the whole read. */
export function decodeStewardshipCandidates(value: unknown): readonly StewardshipCandidate[] {
  if (typeof value !== "object" || value === null || !Array.isArray((value as { items?: unknown }).items)) {
    throw new Error("stewardship candidate projection is malformed");
  }
  return (value as { items: readonly unknown[] }).items.map((raw) => {
    if (typeof raw !== "object" || raw === null) throw new Error("stewardship candidate is malformed");
    const item = raw as Record<string, unknown>;
    const candidateId = text(item["candidate_id"], "id");
    const digest = text(item["candidate_digest"], "digest");
    const state = item["state"];
    if (!CANDIDATE_ID.test(candidateId) || !DIGEST.test(digest) || (state !== "open" && state !== "activated")) {
      throw new Error("stewardship candidate is malformed");
    }
    return {
      candidate_id: candidateId,
      candidate_digest: digest,
      title: text(item["title"], "title"),
      body: text(item["body"], "body"),
      yaml: text(item["yaml"], "yaml"),
      state,
      recorded_at: text(item["recorded_at"], "time"),
    };
  });
}

/** A fresh key per deliberate activation; retries of one activation reuse it. */
export function stewardshipActivationIdempotencyKey(body: StewardshipActivationBody, nonce: string): string {
  return `stewardship-activation:${body.candidate_id}:${body.candidate_digest.slice(0, 16)}:${nonce}`;
}

/**
 * Queue one Owner activation (`POST /stewardship/candidates/activate`). Core rechecks the Owner
 * role and the digest; acceptance is not activation.
 */
export async function queueActivation(
  client: Pick<OperatorApiClient, "postJson">,
  body: StewardshipActivationBody,
  idempotencyKey: string,
): Promise<{ readonly request_id: string; readonly dispatch_status: string }> {
  const raw = await client.postJson<unknown>(
    "/stewardship/candidates/activate", { ...body }, idempotencyKey,
  );
  const receipt = raw as { request_id?: unknown; dispatch_status?: unknown };
  if (typeof receipt.request_id !== "string" || typeof receipt.dispatch_status !== "string") {
    throw new OperatorApiError(502, "stewardship activation receipt is malformed");
  }
  return { request_id: receipt.request_id, dispatch_status: receipt.dispatch_status };
}
