import { useEffect, useRef, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import { ArchitectureMap } from "../components/architecture-map";
import {
  architectureHref,
  type InventoryGraphResponse,
} from "../components/architecture-map.model";
import {
  AsyncBoundary,
  DataTable,
  KpiCard,
  KpiGrid,
  PageHeader,
  type AsyncState,
  type Column,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { t } from "../i18n";

/**
 * Blast-radius simulator panel. Wraps ``GET /simulate/blast-radius`` -
 * the caller supplies a target Resource id + depth + traversal links,
 * the panel renders the reachable subgraph as a table so a reviewer
 * eyeballs "which resources would this action touch" before approving.
 *
 * Purely read-only. There is no button that mutates state; the panel
 * is a projection over the ontology graph the API knows about.
 */

interface ReachedNode {
  readonly resource_id: string;
  readonly depth: number;
  readonly via_link_type: string | null;
}

interface TraversedEdge {
  readonly source: string;
  readonly target: string;
  readonly link_type: string;
  readonly depth: number;
}

interface BlastRadiusResponse {
  readonly target: string;
  readonly traversal_depth: number;
  readonly traversal_links: readonly string[];
  readonly reached: readonly ReachedNode[];
  readonly edges: readonly TraversedEdge[];
  readonly affected_count: number;
  readonly truncated_at_depth: boolean;
}

interface Props {
  readonly client: ReadApiClient;
}

const DEFAULT_LINKS: readonly string[] = ["contains", "depends_on"];
const AVAILABLE_LINKS = ["contains", "depends_on", "attached_to"] as const;

export function BlastRadiusRoute({ client }: Props) {
  const [target, setTarget] = useState(() => targetFromHash(window.location.hash) ?? "web-api");
  const [architectureView, setArchitectureView] = useState(() => viewFromHash(window.location.hash));
  const [depth, setDepth] = useState(2);
  const [linkSet, setLinkSet] = useState<Set<string>>(new Set(DEFAULT_LINKS));
  const [state, setState] = useState<AsyncState<BlastRadiusResponse>>({ status: "idle" });
  const requestGeneration = useRef(0);

  useEffect(() => {
    const sync = () => {
      requestGeneration.current += 1;
      const nextTarget = targetFromHash(window.location.hash);
      setTarget(nextTarget ?? "web-api");
      setArchitectureView(viewFromHash(window.location.hash));
      setState({ status: "idle" });
    };
    window.addEventListener("hashchange", sync);
    return () => window.removeEventListener("hashchange", sync);
  }, []);

  function toggleLink(name: string): void {
    setLinkSet((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  }

  async function runSimulation(): Promise<void> {
    const generation = requestGeneration.current + 1;
    requestGeneration.current = generation;
    setState({ status: "loading" });
    try {
      const params = new URLSearchParams();
      params.set("target", target);
      params.set("depth", String(depth));
      for (const link of linkSet) params.append("link", link);
      const url = `/simulate/blast-radius?${params.toString()}`;
      const data = await client.panel<BlastRadiusResponse>(url);
      if (requestGeneration.current === generation) setState({ status: "ready", data });
    } catch (err) {
      if (requestGeneration.current === generation) {
        setState({
          status: "error",
          message: err instanceof Error ? err.message : String(err),
        });
      }
    }
  }

  return (
    <div class="stack">
      <PageHeader
        title={t("route.blastRadius")}
        subtitle="Simulate the reachable subgraph before approving a change. Read-only projection over the ontology - no resources are touched."
      />

      <section class="stack-section">
        <h3 class="section-title">Query</h3>
        <form
          class="form-grid"
          onSubmit={(e) => {
            e.preventDefault();
            void runSimulation();
          }}
        >
          <label>
            Target resource id
            <input
              type="text"
              value={target}
              onInput={(e) => setTarget((e.target as HTMLInputElement).value)}
              required
            />
          </label>
          <label>
            Traversal depth (1-5)
            <input
              type="number"
              min={1}
              max={5}
              value={depth}
              onInput={(e) => setDepth(Number((e.target as HTMLInputElement).value))}
              required
            />
          </label>
          <fieldset class="chip-fieldset">
            <legend>Link types</legend>
            <div class="chip-options">
              {AVAILABLE_LINKS.map((name) => (
                <label key={name} class="chip-option">
                  <input
                    type="checkbox"
                    checked={linkSet.has(name)}
                    onChange={() => toggleLink(name)}
                  />
                  <span>{name}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <button
            type="submit"
            class="btn primary"
            disabled={state.status === "loading" || linkSet.size === 0}
          >
            Simulate
          </button>
        </form>
      </section>

      <AsyncBoundary
        state={state}
        resourceLabel="blast-radius simulation"
        idle={<p class="muted footnote">Enter a target and click Simulate.</p>}
      >
        {(data) => <ReportView data={data} client={client} architectureView={architectureView} />}
      </AsyncBoundary>
    </div>
  );
}

function ReportView({ data, client, architectureView }: { readonly data: BlastRadiusResponse; readonly client: ReadApiClient; readonly architectureView: string | null }) {
  const [view, setView] = useState<"map" | "table">("map");
  usePublishViewContext(
    () => ({
      routeId: "blast-radius",
      routeLabel: "Blast radius",
      purpose:
        "Simulates how many resources one action could reach by traversing the " +
        "resource graph from a target. The risk gate caps blast radius so a " +
        "single change can never touch more than its scope. Read-only what-if.",
      glossary: composeGlossary([TERMS.blastRadius, TERMS.actionType]),
      headline: `${data.affected_count} resource(s) reachable at depth ${data.traversal_depth}${data.truncated_at_depth ? " (truncated)" : ""}`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "target", value: data.target, group: "query" },
        { key: "depth", value: data.traversal_depth, group: "query" },
        { key: "links", value: data.traversal_links.join(", ") || "(none)", group: "query" },
        { key: "affected_count", value: data.affected_count, group: "result" },
        { key: "edge_count", value: data.edges.length, group: "result" },
        { key: "truncated", value: data.truncated_at_depth, group: "result" },
      ],
      records: {
        reached: data.reached.map((n) => ({
          resource_id: n.resource_id,
          depth: n.depth,
          via_link_type: n.via_link_type,
        })),
        edges: data.edges.map((e) => ({
          source: e.source,
          target: e.target,
          link_type: e.link_type,
          depth: e.depth,
        })),
      },
    }),
    [data],
  );

  const reachedColumns: readonly Column<ReachedNode>[] = [
    { key: "d", header: "Depth", render: (n) => n.depth, cellClass: "num", headerClass: "num" },
    { key: "id", header: "Resource id", render: (n) => n.resource_id, cellClass: "mono" },
    {
      key: "via",
      header: "Reached via",
      render: (n) => n.via_link_type ?? <span class="muted">(target)</span>,
      cellClass: "mono",
    },
  ];
  const edgeColumns: readonly Column<TraversedEdge>[] = [
    { key: "d", header: "Depth", render: (e) => e.depth, cellClass: "num", headerClass: "num" },
    { key: "s", header: "Source", render: (e) => e.source, cellClass: "mono" },
    { key: "l", header: "Link", render: (e) => e.link_type, cellClass: "mono" },
    { key: "t", header: "Target", render: (e) => e.target, cellClass: "mono" },
  ];

  return (
    <div class="stack">
      <KpiGrid>
        <KpiCard
          label="Affected resources"
          value={data.affected_count}
          tone={data.affected_count > 25 ? "warning" : "default"}
        />
        <KpiCard label="Traversal depth" value={data.traversal_depth} />
        <KpiCard
          label="Truncated at cap"
          value={data.truncated_at_depth ? "yes" : "no"}
          tone={data.truncated_at_depth ? "warning" : "positive"}
          hint={data.truncated_at_depth ? "raise --depth to see more" : "full graph explored"}
        />
      </KpiGrid>

      <section class="stack-section">
        <div class="section-header">
          <h3 class="section-title">Affected topology</h3>
          <div class="segmented-control" role="group" aria-label="Blast radius view">
            <button type="button" class={view === "map" ? "active" : ""} onClick={() => setView("map")}>Map</button>
            <button type="button" class={view === "table" ? "active" : ""} onClick={() => setView("table")}>Table</button>
          </div>
        </div>
        {view === "map" ? (
          <BlastRadiusMap client={client} data={data} architectureView={architectureView} />
        ) : (
          <DataTable
            columns={reachedColumns}
            rows={data.reached}
            keyOf={(node) => `${node.depth}:${node.resource_id}`}
            empty="No reachable resources at this depth."
          />
        )}
      </section>

      <section class="stack-section">
        <h3 class="section-title">Edges traversed ({data.edges.length})</h3>
        <DataTable
          columns={edgeColumns}
          rows={data.edges}
          keyOf={(_e, i) => `${i}`}
          empty="No edges walked."
        />
      </section>
    </div>
  );
}

function BlastRadiusMap({ client, data, architectureView }: { readonly client: ReadApiClient; readonly data: BlastRadiusResponse; readonly architectureView: string | null }) {
  const [graph, setGraph] = useState<InventoryGraphResponse | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    const params: Record<string, string> = {
      depth: "4",
      include: "contains,attached_to,depends_on",
    };
    if (architectureView) params.scope = architectureView;
    client.panel<InventoryGraphResponse>("/inventory/graph", params).then(
      (value) => { if (!cancelled) setGraph(value); },
      (error: unknown) => { if (!cancelled) setMessage(error instanceof Error ? error.message : String(error)); },
    );
    return () => { cancelled = true; };
  }, [client, architectureView]);
  if (message) return <p class="muted footnote">Map unavailable: {message}</p>;
  if (!graph) return <p class="muted footnote">Loading architecture map...</p>;
  const highlighted = new Set([data.target, ...data.reached.map((node) => node.resource_id)]);
  return (
    <div class="blast-map-wrap">
      <ArchitectureMap graph={graph} highlightedIds={highlighted} selectedId={data.target} />
      <a class="btn blast-map-open" href={architectureHref(data.target, architectureView)}>Open full architecture</a>
    </div>
  );
}

function targetFromHash(hash: string): string | null {
  const queryIndex = hash.indexOf("?");
  if (queryIndex < 0) return null;
  return new URLSearchParams(hash.slice(queryIndex + 1)).get("target");
}

function viewFromHash(hash: string): string | null {
  const queryIndex = hash.indexOf("?");
  if (queryIndex < 0) return null;
  return new URLSearchParams(hash.slice(queryIndex + 1)).get("view");
}
