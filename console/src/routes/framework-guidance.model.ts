import { OperatorApiError } from "../api";
import { panelNonEmptyString, panelRecord } from "./panel-decode";
import { decodeGuidancePresentation, verifyWaraGuidanceDigest, type GuidancePresentation } from "./wara-guidance.model";

export type GuidanceFramework = "azure-waf" | "azure-mcsb" | "azure-caf";

export interface FrameworkGuidance extends GuidancePresentation {
  readonly schema_version: "1.0.0";
  readonly framework_id: GuidanceFramework;
  readonly control_id: string;
  readonly source_revision: string;
  readonly source_digest: string;
  readonly content_digest: string;
}

interface GuidanceIdentity {
  readonly framework_id: GuidanceFramework;
  readonly control_id: string;
  readonly source_revision: unknown;
  readonly source_digest: unknown;
}

function invalid(reason: string): never {
  throw new OperatorApiError(502, `invalid Operator API response: framework guidance ${reason}`);
}

export function decodeFrameworkGuidance(value: unknown, identity: GuidanceIdentity): FrameworkGuidance | null {
  if (value === undefined || value === null) return null;
  const raw = panelRecord(value, "framework guidance");
  const keys = [
    "schema_version", "framework_id", "control_id", "source_revision", "source_digest",
    "title", "summary", "benefits", "rationale", "applicability", "configuration",
    "implementation_steps", "verification_steps", "cautions", "diagram", "sources", "content_digest",
  ];
  if (Object.keys(raw).some((key) => !keys.includes(key))) invalid("contains unsupported fields");
  if (raw["schema_version"] !== "1.0.0") invalid("schema_version MUST be 1.0.0");
  for (const field of ["framework_id", "control_id", "source_revision", "source_digest"] as const) {
    const expected = identity[field];
    if (expected === undefined || raw[field] !== expected) invalid(`${field} does not match the selected control`);
  }
  const revision = panelNonEmptyString(raw, "source_revision", "framework guidance");
  const sourceDigest = panelNonEmptyString(raw, "source_digest", "framework guidance");
  const contentDigest = panelNonEmptyString(raw, "content_digest", "framework guidance");
  if (![sourceDigest, contentDigest].every((item) => /^sha256:[a-f0-9]{64}$/.test(item))) invalid("MUST contain SHA-256 digests");
  try {
    return {
      schema_version: "1.0.0", framework_id: identity.framework_id, control_id: identity.control_id,
      source_revision: revision, source_digest: sourceDigest,
      ...decodeGuidancePresentation(raw, revision, true), content_digest: contentDigest,
    };
  } catch (error) {
    if (error instanceof OperatorApiError) invalid(error.message.replace(/^.*WARA guidance /, ""));
    throw error;
  }
}

export async function verifyFrameworkGuidanceDigest(guidance: FrameworkGuidance | null | undefined): Promise<void> {
  try {
    await verifyWaraGuidanceDigest(guidance);
  } catch (error) {
    if (error instanceof OperatorApiError) invalid("content_digest does not match the illustrated material");
    throw error;
  }
}
