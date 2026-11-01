import { authenticatedFetch } from "../../../hub/ui/src/auth";

export type Release = {
  id: string; label: string; manifest: string; digest: string; signed_payload_sha256: string; signature: string | null;
  signature_status: string; state: "draft" | "published" | "recalled";
  channels: string[]; published_at: string | null; recalled_at: string | null;
};
export type Event = {
  revision: number; release_id: string; action: string; reason: string;
  channel: string | null; occurred_at: string;
  actor?: string;
};
export type Catalog = {
  revision: number; updated_at: string; expires_at: string; expired: boolean;
  key_id: string; mode: string; releases: Release[];
  channels: Record<string, string[]>; events: Event[]; export_sha256?: string;
};
export type Action = "register" | "publish" | "contribute" | "promote" | "recall" | "renew";
export type CanaryObservationInput = {
  installation_id: string; release_id: string; healthy: boolean; soak_seconds: number;
};
export type Change = {
  revision: number; confirmation: string; reason: string; channel?: string; channel_confirmation?: string;
  label?: string; manifest?: string;
  source_channel?: string; target_channel?: string;
  required_labels?: string[]; labels?: string[];
  min_soak_seconds?: number; min_healthy_canaries?: number;
  max_stage_timeout_seconds?: number; elapsed_stage_seconds?: number;
  canary_observations?: CanaryObservationInput[];
};

export class CatalogRequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "CatalogRequestError";
  }
}

export function catalogRecovery(failure: unknown): string {
  if (failure instanceof CatalogRequestError) {
    if (failure.status === 401) return "Session expired. Sign in again, then refresh the catalog before another action.";
    if (failure.status === 403) return "Operator access denied. Ask the Hub owner to review your existing access; do not expand permissions.";
    if (failure.status === 409) return "Catalog state changed or a server guard blocked the request. Refresh and review the release activity.";
    if (failure.status === 503) return "Hub configuration or service readiness is unavailable. Ask the Hub owner to inspect readiness.";
    return `The Hub rejected the request (${failure.status}). Review the input and current catalog before another action.`;
  }

  if (failure instanceof DOMException && ["AbortError", "TimeoutError"].includes(failure.name)) {
    return "The request timed out. Read the catalog before another action.";
  }
  if (failure instanceof Error && failure.name === "InteractionRequiredAuthError") {
    return "Session renewal requires sign-in. Sign in again, then refresh the catalog before another action.";
  }
  return "The Hub response is unavailable or invalid. Refresh the catalog and inspect the current state before another action.";
}

export function catalogChangeObserved(catalog: Catalog, action: Action, id: string, change: Change): boolean {
  const expectedAction = action === "promote" ? "contribute" : action;
  const expectedChannel = action === "contribute"
    ? change.channel
    : action === "promote"
    ? (change.target_channel ?? change.channel ?? null)
    : null;
  return catalog.revision > change.revision && catalog.events.some((event) =>
    event.revision === change.revision + 1
    && event.action === expectedAction
    && event.release_id === (action === "renew" ? "catalog" : id)
    && event.reason === change.reason.trim()
    && event.channel === expectedChannel);
}

export type DeploymentRequest = {
  request_id: string; subscription_id: string; release_id: string; channel: string;
  region: string; source_commit: string; catalog_digest: string; recorded_at: string;
  status: "requested"; trust: "self-reported";
};
export type DeploymentRequestPage = {
  requests: DeploymentRequest[]; limit: number; offset: number; has_more: boolean;
};

export async function requestDeploymentRequests(
  subscriptionId = "", offset = 0, limit = 25,
): Promise<DeploymentRequestPage> {
  const query = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (subscriptionId) query.set("subscription_id", subscriptionId);
  const response = await authenticatedFetch(`/v1/deployment-requests?${query}`, {
    signal: AbortSignal.timeout(10_000),
  });
  let result: unknown;
  try { result = await response.json(); }
  catch { throw new Error(`Deployment requests unavailable (${response.status}).`); }
  if (!response.ok) {
    throw new Error("Deployment requests unavailable. Check operator access and refresh.");
  }
  if (typeof result !== "object" || result === null) throw new Error("Invalid deployment request page.");
  const page = result as DeploymentRequestPage;
  if (!Array.isArray(page.requests) || page.requests.length > limit
    || page.limit !== limit || page.offset !== offset || typeof page.has_more !== "boolean"
    || !page.requests.every((record) => typeof record === "object" && record !== null
      && record.status === "requested" && record.trust === "self-reported"
      && ["request_id", "subscription_id", "release_id", "channel", "region", "source_commit", "catalog_digest", "recorded_at"]
        .every((key) => typeof record[key as keyof DeploymentRequest] === "string")
      && Number.isFinite(Date.parse(record.recorded_at)))) {
    throw new Error("Invalid deployment request page.");
  }
  return page;
}

export type ReleaseManifest = Record<string, unknown> & {
  product?: string;
  source_commit?: string;
  platform_tag?: string;
  capability_maximums?: Record<string, unknown>;
  schema?: { target: number; tolerates: { minimum: number; maximum: number } };
};

export function nextPromotionTransition(
  release: Release,
): { sourceChannel: "DEV" | "RELEASE_CANDIDATE"; targetChannel: "RELEASE_CANDIDATE" | "RELEASE" } | null {
  if (release.state !== "published") return null;
  if (release.channels.includes("RELEASE")) return null;
  if (release.channels.includes("RELEASE_CANDIDATE")) {
    return { sourceChannel: "RELEASE_CANDIDATE", targetChannel: "RELEASE" };
  }
  if (release.channels.includes("DEV")) {
    return { sourceChannel: "DEV", targetChannel: "RELEASE_CANDIDATE" };
  }
  return null;
}

export function activeCapabilityRecalls(events: readonly Event[]): string[] {
  const ordered = [...events].sort((a, b) => a.revision - b.revision);
  const active = new Set<string>();
  for (const event of ordered) {
    if (event.action === "recall_capability") active.add(event.release_id);
    else if (event.action === "lift_capability") active.delete(event.release_id);
  }
  return [...active].sort();
}

export function blockedReleaseCapabilities(
  manifest: ReleaseManifest,
  events: readonly Event[],
): string[] {
  const declared = manifest.capability_maximums && typeof manifest.capability_maximums === "object"
    ? Object.keys(manifest.capability_maximums)
    : [];
  if (declared.length === 0) return [];
  const recalled = new Set(activeCapabilityRecalls(events));
  return declared.filter((cap) => recalled.has(cap)).sort();
}

export function parseReleaseManifest(manifest: string): ReleaseManifest {
  const parsed: unknown = JSON.parse(manifest);
  if (typeof parsed !== "object" || parsed === null) throw new Error("Invalid manifest.");
  return parsed as ReleaseManifest;
}

export function releaseTitle(release: Release, manifest = parseReleaseManifest(release.manifest)): string {
  return `${manifest.product ?? "Release"} ${release.id}`;
}

export function schemaCompatibility(manifest: ReleaseManifest): string {
  if (!manifest.schema) return "Not declared (stateless package)";
  return `${manifest.schema.tolerates.minimum} - ${manifest.schema.tolerates.maximum} (target ${manifest.schema.target})`;
}

function parseCatalog(value: unknown): Catalog {
  if (typeof value !== "object" || value === null) throw new Error("Release Hub returned an invalid catalog.");
  const candidate = value as Record<string, unknown>;
  if (
    typeof candidate.revision !== "number"
    || !Number.isSafeInteger(candidate.revision)
    || candidate.revision < 0
    || !Array.isArray(candidate.releases)
    || !Array.isArray(candidate.events)
    || typeof candidate.channels !== "object"
    || candidate.channels === null
  ) {
    throw new Error("Release Hub returned an invalid catalog.");
  }
  return candidate as Catalog;
}

export async function requestCatalog(path = "/v1/catalog", body?: Change): Promise<Catalog> {
  const response = await authenticatedFetch(path, {
    cache: "no-store",
    signal: AbortSignal.timeout(10_000),
    ...(body ? {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    } : {}),
  });
  let result: unknown;
  try {
    result = await response.json();
  } catch {
    if (!response.ok) throw new CatalogRequestError(`Request failed (${response.status}).`, response.status);
    throw new Error("Release Hub returned invalid JSON.");
  }
  if (!response.ok) {
    const message = typeof result === "object" && result !== null && "error" in result
      && typeof result.error === "string" && result.error.trim()
      ? result.error : `Request failed (${response.status}).`;
    throw new CatalogRequestError(message, response.status);
  }
  return parseCatalog(result);
}

export function actionsFor(release: Release): Action[] {
  if (release.state === "recalled") return [];
  return release.state === "draft" ? ["publish"] : ["contribute", "recall"];
}

export function releaseStateIndex(releases: Release[]): ReadonlyMap<string, Release["state"]> {
  return new Map(releases.map((release) => [release.id, release.state]));
}

export function isCustomChannel(value: string): boolean {
  return value.length <= 64 && value === value.trim() && /^custom-[a-z0-9]+(?:-[a-z0-9]+)*$/.test(value);
}

export function artifacts(root: ReleaseManifest): { component: string; digest: string; sbom: string }[] {
  const result: { component: string; digest: string; sbom: string }[] = [];
  for (const section of ["services", "sidecars", "installation_agents", "workloads", "console", "deployment_support"]) {
    const group = root[section];
    if (typeof group !== "object" || group === null) continue;
    const entries = section === "console" || section === "deployment_support"
      ? [[section, group] as const] : Object.entries(group);
    for (const [component, value] of entries) {
      if (typeof value !== "object" || value === null) continue;
      const record = value as Record<string, unknown>;
      const digest = typeof record.image_digest === "string"
        ? record.image_digest
        : typeof record.archive_sha256 === "string" ? record.archive_sha256 : null;
      if (!digest) throw new Error(`Artifact ${component} has no digest.`);
      result.push({
        component,
        digest,
        sbom: typeof record.sbom_sha256 === "string" ? record.sbom_sha256 : "Not declared",
      });
    }
  }
  return result;
}
