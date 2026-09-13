// Static mock-only read boundary. No ontology runtime, catalog, or provider API access.
const snapshotUrl = new URL("./ontology-instance-snapshot.json", import.meta.url);
const sourceId = "ontology-instances-2d-mock";
const text = (value) => typeof value === "string" && value.trim().length > 0;

function validate(snapshot) {
  const invalid = () => { throw new Error("Invalid synthetic ontology snapshot. No targets can be selected."); };
  if (snapshot?.schemaVersion !== 1 || snapshot.source?.id !== sourceId
      || snapshot.source.kind !== "synthetic-mock" || !text(snapshot.source.label)
      || !text(snapshot.source.derivedFrom) || !text(snapshot.source.derivation)
      || !text(snapshot.generation) || !text(snapshot.coverage)
      || !text(snapshot.recordedAt) || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(snapshot.recordedAt)
      || !Number.isFinite(Date.parse(snapshot.recordedAt))
      || !["complete", "partial"].includes(snapshot.completeness)
      || !Array.isArray(snapshot.instances) || !Array.isArray(snapshot.relations)) invalid();
  const identities = new Map();
  for (const item of snapshot.instances) {
    if (!text(item?.id) || !item.id.startsWith("mock:ontology-2d:")
        || !text(item.name) || !text(item.resourceType)
        || !["Resource", "ResourceGroup"].includes(item.objectType)
        || identities.has(item.id)) invalid();
    identities.set(item.id, item);
  }
  const members = new Set();
  for (const relation of snapshot.relations) {
    if (relation?.type !== "member_of" || members.has(relation.from)
        || identities.get(relation.from)?.objectType !== "Resource"
        || identities.get(relation.to)?.objectType !== "ResourceGroup") invalid();
    members.add(relation.from);
  }
  if (snapshot.completeness === "complete"
      && snapshot.instances.some((item) => item.objectType === "Resource" && !members.has(item.id))) invalid();
  return snapshot;
}

function project(snapshot) {
  const instances = snapshot.instances.map((item) => {
    const groupId = snapshot.relations.find((edge) => edge.from === item.id)?.to;
    const group = snapshot.instances.find((candidate) => candidate.id === groupId);
    const memberCount = snapshot.relations.filter((edge) => edge.to === item.id).length;
    return Object.freeze({
      ...item, sourceId: snapshot.source.id, generation: snapshot.generation,
      recordedAt: snapshot.recordedAt, groupId,
      description: item.objectType === "ResourceGroup"
        ? `Resource group / ${memberCount} recorded mock members`
        : `${item.resourceType} / ${group?.name ?? "Membership not recorded"}`,
    });
  });
  return Object.freeze({ ...snapshot, instances: Object.freeze(instances) });
}

/** Read and validate one fixed local JSON asset; explicit scenarios never substitute failed reads. */
export async function readOntologySnapshot({ signal, scenario = "ready" } = {}) {
  if (!["ready", "loading", "unavailable", "error", "empty", "partial"].includes(scenario)) {
    throw new Error("Unknown synthetic source scenario.");
  }
  if (scenario === "unavailable") throw new Error("Synthetic ontology source unavailable. No targets were loaded.");
  if (scenario === "error") throw new Error("Synthetic ontology read error. No targets were loaded.");
  const controller = new AbortController();
  const cancel = () => controller.abort();
  signal?.addEventListener("abort", cancel, { once: true });
  if (signal?.aborted) cancel();
  const timeout = setTimeout(cancel, scenario === "loading" ? 3000 : 5000);
  try {
    if (scenario === "loading") {
      await new Promise((_, reject) => {
        controller.signal.addEventListener("abort", () => reject(new Error("Synthetic loading deadline reached. Source unavailable.")), { once: true });
        if (controller.signal.aborted) reject(new Error("Synthetic source read cancelled."));
      });
    }
    const response = await fetch(snapshotUrl, {
      signal: controller.signal, credentials: "omit", cache: "no-store", redirect: "error",
    });
    if (!response.ok) throw new Error(`Synthetic ontology snapshot unavailable (HTTP ${response.status}).`);
    const snapshot = validate(await response.json());
    if (scenario === "empty") {
      snapshot.instances = [];
      snapshot.relations = [];
      snapshot.generation += "-empty";
      snapshot.coverage = "Explicit empty mock scenario; no recorded instances in this snapshot.";
    } else if (scenario === "partial") {
      snapshot.completeness = "partial";
      snapshot.generation += "-partial";
      snapshot.instances = snapshot.instances.filter((item) => item.objectType === "ResourceGroup" || item.name === "checkout-api");
      snapshot.relations = snapshot.relations.filter((edge) => snapshot.instances.some((item) => item.id === edge.from));
      snapshot.coverage = "Explicit partial mock scenario; resource and membership coverage is incomplete. Selection is disabled.";
    }
    return project(snapshot);
  } finally {
    clearTimeout(timeout);
    signal?.removeEventListener("abort", cancel);
  }
}
