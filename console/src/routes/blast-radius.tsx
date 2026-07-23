import { useEffect, useRef, useState } from "preact/hooks";
import { isOptionalReadApiUnavailable, type ReadApiClient } from "../api";
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
import { currentRoute, navigate, replaceRouteState, routeHref } from "../router";
import {
  BLAST_RADIUS_LINKS,
  blastRadiusHref,
  blastRadiusQueryFromSearch,
  blastRadiusRequestIsCurrent,
  DEFAULT_BLAST_RADIUS_LINKS,
  type BlastRadiusQuery,
} from "./blast-radius.model";
import { formatNumber, t } from "./i18n/ontology";

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

export function blastRadiusFailure(error: unknown): AsyncState<never> {
  if (isOptionalReadApiUnavailable(error)) {
    return {
      status: "unavailable",
      message: t("ontology.blast.unavailable"),
    };
  }
  return {
    status: "error",
    message: error instanceof Error ? error.message : String(error),
  };
}

export function BlastRadiusRoute({ client }: Props) {
  const initialQuery = blastRadiusQueryFromSearch(window.location.search);
  const [target, setTarget] = useState(() => initialQuery.target ?? "");
  const [architectureView, setArchitectureView] = useState(initialQuery.architectureView);
  const [depth, setDepth] = useState(initialQuery.depth);
  const [linkSet, setLinkSet] = useState<Set<string>>(() => new Set(initialQuery.links));
  const [state, setState] = useState<AsyncState<BlastRadiusResponse>>({ status: "idle" });
  const requestGeneration = useRef(0);
  const initialSimulationStarted = useRef(false);

  useEffect(() => {
    if (initialSimulationStarted.current) return;
    const query = blastRadiusQueryFromSearch(window.location.search);
    if (query.target === null) return;
    initialSimulationStarted.current = true;
    void runSimulation({
      target: query.target,
      depth: query.depth,
      links: query.links,
      architectureView: query.architectureView,
    });
  }, [client]);

  useEffect(() => {
    const sync = () => {
      requestGeneration.current += 1;
      const query = blastRadiusQueryFromSearch(window.location.search);
      setTarget(query.target ?? "");
      setDepth(query.depth);
      setLinkSet(new Set(query.links));
      setArchitectureView(query.architectureView);
      if (query.target) void runSimulation(query);
      else setState({ status: "idle" });
    };
    window.addEventListener("popstate", sync);
    window.addEventListener("fdai:route-changed", sync);
    return () => {
      window.removeEventListener("popstate", sync);
      window.removeEventListener("fdai:route-changed", sync);
    };
  }, []);

  function syncDraft(next: BlastRadiusQuery): void {
    requestGeneration.current += 1;
    setState({ status: "idle" });
    replaceRouteState(blastRadiusHref(next, currentRoute().search.get("result")));
  }

  function toggleLink(name: string): void {
    setLinkSet((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      syncDraft({
        target: target.trim() || null,
        depth,
        links: [...next],
        architectureView,
      });
      return next;
    });
  }

  async function runSimulation(query: BlastRadiusQuery = {
    target,
    depth,
    links: [...linkSet],
    architectureView,
  }): Promise<void> {
    if (!query.target) return;
    const generation = requestGeneration.current + 1;
    requestGeneration.current = generation;
    setState({ status: "loading" });
    try {
      const params = new URLSearchParams();
      params.set("target", query.target);
      params.set("depth", String(query.depth));
      for (const link of query.links) params.append("link", link);
      const url = `/simulate/blast-radius?${params.toString()}`;
      const data = await client.panel<BlastRadiusResponse>(url);
      if (blastRadiusRequestIsCurrent(requestGeneration.current, generation)) {
        setState({ status: "ready", data });
      }
    } catch (err) {
      if (blastRadiusRequestIsCurrent(requestGeneration.current, generation)) {
        setState(blastRadiusFailure(err));
      }
    }
  }

  return (
    <div class="stack governance-route blast-radius-route">
      <PageHeader
        title={t("route.blastRadius")}
        subtitle={t("ontology.blast.subtitle")}
      />

      <section class="impact-query-panel" aria-labelledby="impact-query-title">
        <header class="impact-query-head">
          <h3 id="impact-query-title">{t("ontology.blast.queryTitle")}</h3>
          <p>{t("ontology.blast.queryDescription")}</p>
        </header>
        <form
          class="impact-query-grid"
          onSubmit={(e) => {
            e.preventDefault();
            navigate(blastRadiusHref({
              target: target.trim(),
              depth,
              links: [...linkSet],
              architectureView,
            }));
          }}
        >
          <label class="impact-query-field">
            <span>{t("ontology.blast.targetResourceId")}</span>
            <input
              class="impact-query-input"
              type="text"
              value={target}
              onInput={(e) => {
                const nextTarget = (e.target as HTMLInputElement).value;
                setTarget(nextTarget);
                syncDraft({
                  target: nextTarget.trim() || null,
                  depth,
                  links: [...linkSet],
                  architectureView,
                });
              }}
              required
            />
          </label>
          <label class="impact-query-field is-compact">
            <span>{t("ontology.blast.depthInput")}</span>
            <input
              class="impact-query-input"
              type="number"
              min={1}
              max={5}
              value={depth}
              onInput={(e) => {
                const nextDepth = Number((e.target as HTMLInputElement).value);
                setDepth(nextDepth);
                syncDraft({
                  target: target.trim() || null,
                  depth: nextDepth,
                  links: [...linkSet],
                  architectureView,
                });
              }}
              required
            />
          </label>
          <fieldset class="impact-query-checks">
            <legend>{t("ontology.blast.linkTypes")}</legend>
            <div class="impact-query-options">
              {BLAST_RADIUS_LINKS.map((name) => (
                <label key={name} class="impact-query-check">
                  <input
                    type="checkbox"
                    checked={linkSet.has(name)}
                    onChange={() => toggleLink(name)}
                  />
                  <span class="impact-query-check-box" aria-hidden="true" />
                  <span>{name}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <div class="impact-query-action">
            <span>{t("ontology.blast.runReadOnly")}</span>
            <button
              type="submit"
              class="btn primary impact-query-submit"
              disabled={state.status === "loading" || target.trim().length === 0 || linkSet.size === 0}
            >
              {t("ontology.blast.simulate")}
            </button>
          </div>
        </form>
      </section>

      <AsyncBoundary
        state={state}
        resourceLabel={t("ontology.blast.loadingLabel")}
        idle={<p class="muted footnote">{t("ontology.blast.idle")}</p>}
      >
        {(data) => <ReportView data={data} client={client} architectureView={architectureView} />}
      </AsyncBoundary>
    </div>
  );
}
function ReportView({ data, client, architectureView }: { readonly data: BlastRadiusResponse; readonly client: ReadApiClient; readonly architectureView: string | null }) {
  const initialResult = currentRoute().search.get("result");
  const evidenceHref = blastRadiusHref({
    target: data.target,
    depth: data.traversal_depth,
    links: data.traversal_links,
    architectureView,
  }, "table");
  const [view, setView] = useState<"impact" | "map" | "table">(
    initialResult === "map" || initialResult === "table" ? initialResult : "impact",
  );
  const selectView = (next: "impact" | "map" | "table"): void => {
    const params = Object.fromEntries(currentRoute().search.entries());
    setView(next);
    replaceRouteState(routeHref("blast-radius", {
      params: { ...params, result: next === "impact" ? null : next },
    }));
  };
  usePublishViewContext(
    () => ({
      routeId: "blast-radius",
      routeLabel: t("ontology.context.impactLabel"),
      purpose: t("ontology.context.impactPurpose"),
      glossary: composeGlossary([TERMS.blastRadius, TERMS.actionType]),
      headline: t(data.truncated_at_depth
        ? "ontology.context.impactHeadlineTruncated"
        : "ontology.context.impactHeadline", {
        resources: formatNumber(data.affected_count),
        depth: formatNumber(data.traversal_depth),
      }),
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "target", value: data.target, group: "query" },
        { key: "depth", value: data.traversal_depth, group: "query" },
        { key: "links", value: data.traversal_links.join(", ") || t("ontology.context.none"), group: "query" },
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
    { key: "d", header: t("ontology.blast.columnDepth"), render: (n) => formatNumber(n.depth), cellClass: "num", headerClass: "num" },
    {
      key: "id",
      header: t("ontology.blast.columnResourceId"),
      render: (n) => <a href={architectureHref(n.resource_id, architectureView)}>{n.resource_id}</a>,
      cellClass: "mono",
    },
    {
      key: "via",
      header: t("ontology.blast.columnReachedVia"),
      render: (n) => n.via_link_type ?? <span class="muted">{t("ontology.blast.targetMarker")}</span>,
      cellClass: "mono",
    },
  ];
  const edgeColumns: readonly Column<TraversedEdge>[] = [
    { key: "d", header: t("ontology.blast.columnDepth"), render: (e) => formatNumber(e.depth), cellClass: "num", headerClass: "num" },
    {
      key: "s",
      header: t("ontology.blast.columnSource"),
      render: (e) => <a href={architectureHref(e.source, architectureView)}>{e.source}</a>,
      cellClass: "mono",
    },
    { key: "l", header: t("ontology.blast.columnLink"), render: (e) => e.link_type, cellClass: "mono" },
    {
      key: "t",
      header: t("ontology.blast.columnTarget"),
      render: (e) => <a href={architectureHref(e.target, architectureView)}>{e.target}</a>,
      cellClass: "mono",
    },
  ];

  return (
    <div class="stack">
      <div class="governance-summary-strip" aria-label={t("ontology.blast.contextLabel")}>
        <span class="is-steel"><strong>{data.target}</strong></span>
        <span>{t("ontology.blast.depthSummary", { depth: formatNumber(data.traversal_depth) })}</span>
        <span>{data.traversal_links.join(" + ") || t("ontology.blast.noLinks")}</span>
        <span class={data.truncated_at_depth ? "is-plum" : "is-teal"}>
          {data.truncated_at_depth ? t("ontology.blast.truncated") : t("ontology.blast.complete")}
        </span>
      </div>
      <KpiGrid>
        <KpiCard
          href={evidenceHref}
          label={t("ontology.blast.affectedResources")}
          value={formatNumber(data.affected_count)}
          tone={data.affected_count > 25 ? "warning" : "default"}
        />
        <KpiCard
          href={evidenceHref}
          label={t("ontology.blast.traversalDepth")}
          value={formatNumber(data.traversal_depth)}
        />
        <KpiCard
          href={evidenceHref}
          label={t("ontology.blast.truncatedAtCap")}
          value={data.truncated_at_depth ? t("ontology.common.yes") : t("ontology.common.no")}
          tone={data.truncated_at_depth ? "warning" : "positive"}
          hint={data.truncated_at_depth ? t("ontology.blast.raiseDepth") : t("ontology.blast.fullGraph")}
        />
      </KpiGrid>

      <section class="stack-section">
        <div class="section-header">
          <h3 class="section-title">{t("ontology.blast.topology")}</h3>
          <div class="segmented-control" role="group" aria-label={t("ontology.blast.viewLabel")}>
            <button type="button" class={view === "impact" ? "active" : ""} onClick={() => selectView("impact")}>{t("ontology.blast.viewImpact")}</button>
            <button type="button" class={view === "map" ? "active" : ""} onClick={() => selectView("map")}>{t("ontology.blast.viewMap")}</button>
            <button type="button" class={view === "table" ? "active" : ""} onClick={() => selectView("table")}>{t("ontology.blast.viewTable")}</button>
          </div>
        </div>
        {view === "impact" ? (
          <BlastImpact data={data} architectureView={architectureView} />
        ) : view === "map" ? (
          <BlastRadiusMap client={client} data={data} architectureView={architectureView} />
        ) : (
          <DataTable
            columns={reachedColumns}
            rows={data.reached}
            keyOf={(node) => `${node.depth}:${node.resource_id}`}
            empty={t("ontology.blast.noReachable")}
          />
        )}
      </section>

      <section class="stack-section">
        <h3 class="section-title">{t("ontology.blast.edgesTraversed", { count: formatNumber(data.edges.length) })}</h3>
        <DataTable
          columns={edgeColumns}
          rows={data.edges}
          keyOf={(_e, i) => `${i}`}
          empty={t("ontology.blast.noEdges")}
        />
      </section>
    </div>
  );
}
function BlastImpact({
  data,
  architectureView,
}: {
  readonly data: BlastRadiusResponse;
  readonly architectureView: string | null;
}) {
  const nodes = data.reached.filter((node) => node.resource_id !== data.target);
  const maxDepth = Math.max(1, data.traversal_depth);
  return (
    <div class="blast-impact-layout">
      <div class="blast-rings" role="img" aria-label={t("ontology.blast.scopeAround", { target: data.target })}>
        <svg viewBox="0 0 560 430">
          {Array.from({ length: maxDepth }, (_, index) => {
            const depth = maxDepth - index;
            const radius = 58 + depth * 58;
            return <circle key={depth} cx="280" cy="215" r={radius} class={`blast-ring depth-${depth}`} />;
          })}
          <circle cx="280" cy="215" r="42" class="blast-target" />
          <text x="280" y="211" text-anchor="middle" class="blast-target-label">{t("ontology.common.target")}</text>
          <text x="280" y="229" text-anchor="middle" class="blast-target-name">{shortResource(data.target)}</text>
          {nodes.slice(0, 24).map((node, index) => {
            const peers = nodes.filter((candidate) => candidate.depth === node.depth);
            const peerIndex = peers.indexOf(node);
            const angle = (Math.PI * 2 * peerIndex) / Math.max(1, peers.length) - Math.PI / 2;
            const radius = 58 + Math.max(1, node.depth) * 58;
            const x = 280 + Math.cos(angle) * radius;
            const y = 215 + Math.sin(angle) * radius;
            return (
              <g key={`${node.resource_id}:${index}`}>
                <circle cx={x} cy={y} r="8" class={`blast-node depth-${node.depth}`} />
                <text x={x} y={y + 20} text-anchor="middle" class="blast-node-label">{shortResource(node.resource_id)}</text>
              </g>
            );
          })}
        </svg>
      </div>
      <section class="blast-impact-list">
        <header>
          <h4>{t("ontology.blast.impactTree")}</h4>
          <span>{t("ontology.blast.affectedCount", { count: formatNumber(data.affected_count) })}</span>
        </header>
        <ol>
          <li class="is-target"><span>{formatNumber(0)}</span><a href={architectureHref(data.target, architectureView)}><code>{data.target}</code></a><small>{t("ontology.common.target")}</small></li>
          {data.reached.map((node) => (
            <li key={`${node.depth}:${node.resource_id}`}>
              <span>{formatNumber(node.depth)}</span>
              <a href={architectureHref(node.resource_id, architectureView)}><code>{node.resource_id}</code></a>
              <small>{node.via_link_type ?? t("ontology.common.direct")}</small>
            </li>
          ))}
        </ol>
      </section>
    </div>
  );
}
function shortResource(value: string): string {
  const parts = value.split("/").filter(Boolean);
  const last = parts[parts.length - 1] ?? value;
  return last.length > 22 ? `${last.slice(0, 20)}...` : last;
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
  if (message) return <p class="muted footnote">{t("ontology.blast.mapUnavailable", { message })}</p>;
  if (!graph) return <p class="muted footnote">{t("ontology.blast.mapLoading")}</p>;
  const highlighted = new Set([data.target, ...data.reached.map((node) => node.resource_id)]);
  return (
    <div class="blast-map-wrap">
      <ArchitectureMap graph={graph} highlightedIds={highlighted} selectedId={data.target} />
      <a class="btn blast-map-open" href={architectureHref(data.target, architectureView)}>{t("ontology.blast.openArchitecture")}</a>
    </div>
  );
}
