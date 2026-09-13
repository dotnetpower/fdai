import type { RecordedDirectory, RecordedGraph } from "./contract";
import { loadOntologySnapshot, type OntologySnapshot, type SnapshotEvent } from "./snapshot";

/** The full stored catalog and actual DB rows remain distinct, with explicit display filtering. */
export class RecordedStore {
  directory: RecordedDirectory | null = null;
  graph: RecordedGraph | null = null;
  snapshot: OntologySnapshot | null = null;
  events: readonly SnapshotEvent[] = [];
  changes: readonly { resourceId: string; readAt: string }[] = [];
  selectedId = "";
  status: "idle" | "loading" | "ready" | "error" = "idle";
  error = "";
  replayAt: string | null = null;
  replayEnabled = false;
  replayStateType = "resource.operational_state";
  lens: "all" | "catalog" | "instances" = "all";
  objectType = "all";
  busy = false;
  onChange: () => void = () => {};
  private controller: AbortController | null = null;
  private frameKey = "";
  private seconds = 0;
  private duration = 72;

  ensureLoaded() { if (this.status === "idle") void this.reload(); }

  async reload() {
    this.controller?.abort();
    const controller = new AbortController();
    this.controller = controller;
    const deadline = setTimeout(() => controller.abort(), 50000);
    this.busy = true;
    this.status = "loading";
    this.error = "";
    this.onChange();
    try {
      const snapshot = await loadOntologySnapshot(controller.signal);
      if (controller !== this.controller) return;
      this.snapshot = snapshot;
      this.graph = snapshot.graph;
      this.selectedId = snapshot.graph.root;
      this.directory = { kind: "directory", generation: snapshot.graph.generation, cutoff: snapshot.graph.cutoff,
        complete: true, resources: snapshot.graph.resources };
      this.events = snapshot.events;
      this.replayAt = null;
      this.changes = [];
      this.replayEnabled = false;
      this.status = "ready";
      this.frameKey = "";
    } catch (error) {
      if (controller !== this.controller) return;
      this.status = "error";
      this.error = error instanceof Error ? error.message : "local-db-unavailable";
      this.graph = null;
      this.directory = null;
      this.snapshot = null;
      this.events = [];
      this.changes = [];
    } finally {
      clearTimeout(deadline);
      if (controller === this.controller) { this.busy = false; this.onChange(); }
    }
  }

  search(query: string) {
    if (!this.snapshot) throw new Error("Load the ontology before searching.");
    const normalized = query.toLowerCase().trim();
    this.directory = {
      kind: "directory", generation: this.snapshot.graph.generation, cutoff: this.snapshot.graph.cutoff, complete: true,
      resources: this.snapshot.graph.resources.filter((node) =>
        `${node.name} ${node.resourceType} ${node.objectType ?? ""}`.toLowerCase().includes(normalized)),
    };
    this.onChange();
  }

  load(root: string) {
    if (!this.snapshot?.graph.resources.some((node) => node.id === root)) throw new Error("Unknown stored ontology node.");
    this.selectedId = root;
    this.onChange();
  }

  setLens(lens: "all" | "catalog" | "instances") { this.lens = lens; this.onChange(); }
  setObjectType(type: string) { this.objectType = type; this.onChange(); }

  setReplayEnabled(enabled: boolean) {
    this.replayEnabled = enabled;
    this.frameKey = "";
    if (!enabled && this.snapshot) {
      this.graph = this.snapshot.graph;
      this.events = this.snapshot.events;
      this.changes = [];
      this.replayAt = null;
    } else this.setReplay(this.seconds, this.duration);
    this.onChange();
  }
  setReplayStateType(value: string) {
    this.replayStateType = value;
    this.frameKey = "";
    this.setReplay(this.seconds, this.duration);
    this.onChange();
  }

  setReplay(seconds: number, duration: number) {
    this.seconds = seconds;
    this.duration = duration;
    if (!this.snapshot || !this.replayEnabled) return;
    const fraction = Math.max(0, Math.min(1, seconds / duration));
    const at = Date.parse(this.snapshot.startAt) + fraction * (Date.parse(this.snapshot.endAt) - Date.parse(this.snapshot.startAt));
    this.replayAt = new Date(at).toISOString();
    const events = this.snapshot.events.filter((event) => Date.parse(event.at) <= at);
    if (String(events.length) === this.frameKey) return;
    const states = new Map(events.filter((event) => event.stateType === this.replayStateType && event.lane === "observed" && !event.synthetic && event.conflicts === 0 && event.state !== null)
      .map((event) => [event.resourceId, event.state]));
    const previous = new Map(this.graph?.resources.map((node) => [node.id, node.presentationState]) ?? []);
    const resources = this.snapshot.graph.resources.map((node) => ({
      ...node, ...(node.nodeKind === "instance" ? { presentationState: states.get(node.id) ?? null } : {}),
    }));
    const forward = events.length > this.events.length;
    this.changes = forward ? resources.filter((node) => node.presentationState !== previous.get(node.id))
      .map((node) => ({ resourceId: node.id, readAt: new Date().toISOString() })) : [];
    this.graph = { ...this.snapshot.graph, resources };
    this.events = events;
    this.frameKey = String(events.length);
  }

  dispose() { this.controller?.abort(); this.controller = null; }
}
