import { createHash } from "node:crypto";

export interface BrowserEvidenceProvenance {
  readonly source_revision: string;
  readonly configuration_digest: string;
  readonly workspace_patch_digest: string;
}

const SOURCE_REVISION = /^[0-9a-f]{40}$/;
const SHA256_DIGEST = /^sha256:[0-9a-f]{64}$/;

export function buildBrowserEvidenceProvenance(
  sourceRevision: string | undefined,
  workspacePatchDigest: string | undefined,
  configuration: object,
): BrowserEvidenceProvenance {
  if (!sourceRevision || !SOURCE_REVISION.test(sourceRevision)) {
    throw new Error("FDAI_E2E_SOURCE_REVISION must be a lowercase 40-character git SHA");
  }
  if (!workspacePatchDigest || !SHA256_DIGEST.test(workspacePatchDigest)) {
    throw new Error("FDAI_E2E_WORKSPACE_PATCH_SHA256 must be a sha256-prefixed digest");
  }
  return {
    source_revision: sourceRevision,
    configuration_digest: canonicalJsonDigest(configuration),
    workspace_patch_digest: workspacePatchDigest,
  };
}

/** Returns the stable `sha256:` digest of a JSON value with order-independent object keys. */
export function canonicalJsonDigest(value: unknown): string {
  const digest = createHash("sha256")
    .update(JSON.stringify(canonicalJsonValue(value)))
    .digest("hex");
  return `sha256:${digest}`;
}

function canonicalJsonValue(value: unknown): unknown {
  if (
    value === undefined || typeof value === "function" ||
    typeof value === "symbol" || typeof value === "bigint"
  ) {
    throw new Error("browser evidence configuration must contain JSON values only");
  }
  if (typeof value === "number" && !Number.isFinite(value)) {
    throw new Error("browser evidence configuration numbers must be finite");
  }
  if (Array.isArray(value)) return value.map(canonicalJsonValue);
  if (typeof value !== "object" || value === null) return value;
  if (Object.getPrototypeOf(value) !== Object.prototype) {
    throw new Error("browser evidence configuration objects must be plain JSON objects");
  }
  return Object.fromEntries(
    Object.entries(value)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, canonicalJsonValue(item)]),
  );
}
