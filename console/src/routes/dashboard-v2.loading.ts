import {
  decodeRecordedResourceStates,
  isRecordedStateGenerationTransition,
  latestRecordedStateObservedAt,
  stateRecord,
  stateText,
  stateTime,
} from "../recorded-resource-state";
import { isOperationalResourceType } from "../resource-presentation";
import type { DashboardResource, DashboardSnapshot } from "./dashboard-v2.model";

const LIMIT = 500;
const MAX_RECORDS = 20000;
const MAX_READ_MS = 45_000;
const GENERATION_RETRY_DELAYS_MS = [
  250,
  500,
  1_000,
  2_000,
  4_000,
  8_000,
  12_000,
  12_000,
] as const;
interface RecordedStateClient {
  readonly panel: (path: string, params?: Record<string, string>) => Promise<unknown>;
}

function nullable(value: unknown, name: string): string | null {
  return value === null ? null : stateText(value, name);
}

async function readWithinDeadline(read: () => Promise<unknown>, remaining: number): Promise<unknown> {
  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    return await Promise.race([
      read(),
      new Promise<never>((_resolve, reject) => {
        timer = setTimeout(() => reject(new Error("Recorded resource query exceeded its total deadline")), remaining);
      }),
    ]);
  } finally { clearTimeout(timer); }
}

function wait(delayMs: number): Promise<void> {
  return new Promise((resolve) => globalThis.setTimeout(resolve, delayMs));
}

async function loadDashboardRecordedStateGeneration(
  client: RecordedStateClient,
  cancelled: () => boolean,
  started: number,
): Promise<DashboardSnapshot | null> {
  let generation: string | null = null;
  let ontologyGeneration: string | null = null;
  let ontologyManifestDigest: string | null = null;
  let invalidationWatermark: number | null | undefined;
  let cutoff: string | null = null;
  let release: string | null = null;
  let total: number | null = null;
  let cursor: string | null = null;
  const resources: DashboardResource[] = [];
  const ids = new Set<string>();
  const cursors = new Set<string>();
  for (let page = 0; page < MAX_RECORDS / LIMIT; page += 1) {
    if (cancelled()) return null;
    if (Date.now() - started >= MAX_READ_MS) throw new Error("Recorded resource query exceeded its total deadline");
    const params = { limit: String(LIMIT), ...(cursor ? { cursor } : {}) };
    const raw = await readWithinDeadline(() => client.panel("/ontology/instances/states", params), MAX_READ_MS - (Date.now() - started));
    if (cancelled()) return null;
    if (Date.now() - started >= MAX_READ_MS) throw new Error("Recorded resource query exceeded its total deadline");
    const payload = stateRecord(raw, "resource page");
    if (payload.schema_version !== "1.0.0" || payload.execution_authority !== false || payload.mutation_authority !== false) throw new Error("Invalid recorded resource page authority/version");
    const nextGeneration = stateText(payload.source_generation, "generation");
    const nextOntologyGeneration = stateText(payload.ontology_generation, "ontology generation");
    const nextOntologyManifestDigest = stateText(payload.ontology_manifest_digest, "ontology manifest");
    const rawInvalidationWatermark = payload.invalidation_watermark;
    if (
      rawInvalidationWatermark !== undefined
      && rawInvalidationWatermark !== null
      && (
        typeof rawInvalidationWatermark !== "number"
        || !Number.isSafeInteger(rawInvalidationWatermark)
        || rawInvalidationWatermark < 1
      )
    ) throw new Error("Invalid recorded resource invalidation watermark");
    const nextInvalidationWatermark = rawInvalidationWatermark ?? null;
    const sourceKind = stateText(payload.source_kind, "source kind");
    const nextCutoff = stateTime(payload.source_cutoff, "cutoff");
    const nextRelease = stateText(payload.ontology_release_digest, "ontology release");
    if (!/^sha256:[a-f0-9]{64}$/.test(nextRelease)) throw new Error("Invalid recorded resource ontology release");
    if (!/^sha256:[a-f0-9]{64}$/.test(nextOntologyManifestDigest)) throw new Error("Invalid recorded resource ontology manifest");
    if (nextOntologyGeneration !== nextGeneration) throw new Error("Recorded resource ontology generation does not match inventory");
    if (sourceKind !== "inventory_snapshot_resource") throw new Error("Invalid recorded resource source kind");
    if (generation !== null && (
      generation !== nextGeneration
      || ontologyGeneration !== nextOntologyGeneration
      || ontologyManifestDigest !== nextOntologyManifestDigest
      || invalidationWatermark !== nextInvalidationWatermark
      || cutoff !== nextCutoff
      || release !== nextRelease
    )) throw new Error("Recorded resource generation changed; refresh the snapshot");
    generation = nextGeneration;
    ontologyGeneration = nextOntologyGeneration;
    ontologyManifestDigest = nextOntologyManifestDigest;
    invalidationWatermark = nextInvalidationWatermark;
    cutoff = nextCutoff;
    release = nextRelease;
    if (!Number.isSafeInteger(payload.total_count) || typeof payload.total_count !== "number" || payload.total_count < 0) throw new Error("Invalid recorded resource total");
    if (total !== null && total !== payload.total_count) throw new Error("Recorded resource total changed within the snapshot");
    total = payload.total_count;
    if (!Array.isArray(payload.resources) || payload.resources.length > LIMIT) throw new Error("Invalid recorded resource page size");
    for (const rawResource of payload.resources) {
      const resource = stateRecord(rawResource, "resource");
      const id = stateText(resource.id, "resource id");
      const type = stateText(resource.resource_type, "resource type");
      if (ids.has(id)) throw new Error("Recorded resource pages overlap");
      if (resource.object_type !== "Resource" || !isOperationalResourceType(type) || ["subscription", "resource-group"].includes(type)) throw new Error("Recorded resource page contains a non-operational record");
      ids.add(id);
      const states = decodeRecordedResourceStates(resource.states);
      const group = nullable(resource.resource_group, "resource group");
      const subscription = nullable(resource.subscription_id, "subscription");
      resources.push({
        id, type, name: nullable(resource.name, "name") ?? id,
        status: nullable(resource.status, "status") ?? "",
        parentId: null, group: group === null ? null : `${subscription ?? ""}::${group}`, groupLabel: group,
        subscription, subscriptionLabel: subscription,
        observedAt: latestRecordedStateObservedAt(states), states,
      });
    }
    cursor = nullable(payload.next_cursor, "next cursor");
    if (typeof payload.complete !== "boolean" || payload.complete !== (cursor === null)) throw new Error("Recorded resource page completeness contradicts its cursor");
    if (resources.length > total) throw new Error("Recorded resources exceed the declared total");
    if (cursor === null) {
      if (resources.length !== total) throw new Error("Recorded resource terminal page is incomplete");
      break;
    }
    if (payload.resources.length === 0 || cursors.has(cursor)) throw new Error("Recorded resource cursor made no progress");
    cursors.add(cursor);
  }
  if (
    generation === null
    || ontologyGeneration === null
    || ontologyManifestDigest === null
    || cutoff === null
    || total === null
  ) throw new Error("Recorded resource snapshot is missing");
  return {
    id: generation,
    ontologyGeneration,
    ontologyManifestDigest,
    invalidationWatermark: invalidationWatermark ?? null,
    at: cutoff, source: "inventory_snapshot_resource", scope: null,
    freshness: "unknown", observationKind: null, truncated: cursor !== null,
    limitations: cursor !== null ? ["client_record_limit"] : [], resources,
    excludedContainers: 0, excludedAuthorization: 0, pendingChanges: null,
    recordedStates: true, totalCount: total,
  };
}

/** Load bounded pages of one generation; retry only a typed generation transition. */
export async function loadDashboardRecordedStates(
  client: RecordedStateClient,
  cancelled: () => boolean = () => false,
  waitForRetry: (delayMs: number) => Promise<void> = wait,
): Promise<DashboardSnapshot | null> {
  const started = Date.now();
  for (let attempt = 0; ; attempt += 1) {
    try {
      return await loadDashboardRecordedStateGeneration(client, cancelled, started);
    } catch (error) {
      if (
        !isRecordedStateGenerationTransition(error)
        || attempt >= GENERATION_RETRY_DELAYS_MS.length
      ) throw error;
      if (cancelled()) return null;
      const delay = GENERATION_RETRY_DELAYS_MS[attempt]!;
      const remaining = MAX_READ_MS - (Date.now() - started);
      if (remaining <= delay) throw error;
      await readWithinDeadline(() => waitForRetry(delay), remaining);
    }
  }
}
