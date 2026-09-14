import { useEffect, useRef, useState } from "preact/hooks";
import { isOptionalOperatorApiUnavailable, type OperatorApiClient } from "../api";
import { ArchitectureMap } from "../components/architecture-map";
import {
  architectureHref,
  type InventoryGraphResponse,
} from "../components/architecture-map.model";
import {
  AsyncBoundary,
  DataTable,
  PageHeader,
  StatusPill,
  type AsyncState,
  type Column,
} from "../components/ui";
import { usePublishViewContext } from "../deck/context";
import { TERMS, composeGlossary } from "../deck/glossary";
import { currentRoute, navigate, replaceRouteState, routeHref } from "../router";
import { isRfc3339Timestamp } from "../time-format";
import {
  BlastImpact,
  BlastTraversalContract,
  ImpactSummary,
  impactEvidencePresentation,
} from "./blast-radius-impact";
import { ImpactResourcePicker } from "./blast-radius-resource-picker";
import {
  BLAST_RADIUS_LINKS,
  decodeBlastRadiusResponse,
  blastRadiusHref,
  blastRadiusQueryFromSearch,
  blastRadiusRequestIsCurrent,
  blastRadiusResponseMatchesQuery,
  DEFAULT_BLAST_RADIUS_LINKS,
  type BlastRadiusResponse,
  type BlastRadiusQuery,
  type ReachedNode,
  type TraversedEdge,
} from "./blast-radius.model";
import { formatNumber, t } from "./i18n/ontology";

/**
 * Blast-radius simulator panel. Wraps ``GET /simulate/blast-radius`` -
 * the caller supplies a target Resource id + depth + traversal links,
 * the panel renders a bounded relationship workbench, evidence inspector,
 * and exact tables so a reviewer can see which resources may be affected.
 *
 * Purely read-only. There is no button that mutates state; the panel
 * is a projection over the ontology graph the API knows about.
 */

interface Props {
  readonly client: OperatorApiClient;
}

export function inventoryGraphContainsImpactTarget(
  graph: Pick<InventoryGraphResponse, "resources">,
  target: string,
): boolean {
  return graph.resources.some((resource) => resource.id === target);
}

export function blastRadiusFailure(error: unknown): AsyncState<never> {
  if (isOptionalOperatorApiUnavailable(error)) {
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

export function inventoryGraphContainsImpact(
  graph: Pick<InventoryGraphResponse, "resources" | "links">,
  impact: Pick<BlastRadiusResponse, "target" | "reached" | "edges">,
): boolean {
  const resourceIds = new Set(graph.resources.map((resource) => resource.id));
  if (
    !resourceIds.has(impact.target)
    || impact.reached.some((resource) => !resourceIds.has(resource.resource_id))
  ) {
    return false;
  }
  const linkSignatures = new Set(
    graph.links.map((link) => `${link.source}\0${link.type}\0${link.target}`),
  );
  return impact.edges.every((edge) =>
    linkSignatures.has(`${edge.source}\0${edge.link_type}\0${edge.target}`));
}

export function inventoryGraphMatchesImpact(
  graph: Pick<InventoryGraphResponse, "snapshot_id" | "snapshot_at">,
  impact: Pick<BlastRadiusResponse, "source_generation" | "source_cutoff">,
): boolean {
  if (graph.snapshot_id !== undefined) {
    return graph.snapshot_id === impact.source_generation;
  }
  if (
    !isRfc3339Timestamp(graph.snapshot_at)
    || !isRfc3339Timestamp(impact.source_cutoff)
  ) {
    return false;
  }
  const graphCutoff = Date.parse(graph.snapshot_at);
  const impactCutoff = Date.parse(impact.source_cutoff);
  return Number.isFinite(graphCutoff)
    && Number.isFinite(impactCutoff)
    && graphCutoff === impactCutoff;
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

  function selectTarget(nextTarget: string): void {
    setTarget(nextTarget);
    setArchitectureView(null);
    syncDraft({
      target: nextTarget || null,
      depth,
      links: [...linkSet],
      architectureView: null,
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
      const payload = await client.panel<unknown>(url);
      const data = decodeBlastRadiusResponse(payload);
      if (!blastRadiusResponseMatchesQuery(data, query)) {
        throw new Error("impact response does not match the submitted query");
      }
      if (blastRadiusRequestIsCurrent(requestGeneration.current, generation)) {
        setState({ status: "ready", data });
      }
    } catch (err) {
      if (blastRadiusRequestIsCurrent(requestGeneration.current, generation)) {
        setState(blastRadiusFailure(err));
      }
    }
  }

  const reportData = state.status === "ready" ? state.data : null;

  return (
    <div class="stack governance-route blast-radius-route">
      <PageHeader
        title={t("route.blastRadius")}
        subtitle={t("ontology.blast.subtitle")}
        actions={reportData ? (
          <div class="blast-projection-meta">
            <span>{t("ontology.blast.projectionCutoff")}</span>
            <time dateTime={reportData.source_cutoff}>
              {reportData.source_cutoff}
            </time>
          </div>
        ) : undefined}
      />

      <div class="blast-readonly-banner" role="note">
        <strong>{t("ontology.blast.boundaryTitle")}</strong>
        <span>{t("ontology.blast.boundaryDescription")}</span>
      </div>

      {reportData ? (
        <ImpactSummary
          data={reportData}
        />
      ) : null}

      <section class="impact-query-panel" aria-labelledby="impact-query-title">
        <h3 id="impact-query-title" class="sr-only">{t("ontology.blast.queryTitle")}</h3>
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
          <ImpactResourcePicker
            client={client}
            selectedId={target}
            onSelect={selectTarget}
          />
          <label class="impact-query-field is-compact">
            <span>{t("ontology.blast.depthInput")}</span>
            <select
              class="impact-query-input"
              value={depth}
              onInput={(e) => {
                const nextDepth = Number((e.target as HTMLSelectElement).value);
                setDepth(nextDepth);
                syncDraft({
                  target: target.trim() || null,
                  depth: nextDepth,
                  links: [...linkSet],
                  architectureView,
                });
              }}
            >
              {[1, 2, 3, 4, 5].map((option) => (
                <option key={option} value={option}>
                  {option === 1
                    ? t("ontology.blast.depthOneOption")
                    : t("ontology.blast.depthOption", { depth: option })}
                </option>
              ))}
            </select>
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

function ReportView({ data, client, architectureView }: { readonly data: BlastRadiusResponse; readonly client: OperatorApiClient; readonly architectureView: string | null }) {
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
  const sourceCoverage = data.relationship_source_coverage;
  const sourceFullyMaterialized = sourceCoverage !== null
    && sourceCoverage.complete
    && sourceCoverage.reviewed_unavailable === 0
    && sourceCoverage.unclassified === 0;
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
      headline: t(!data.complete
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
        { key: "complete", value: data.complete, group: "result" },
        {
          key: "relationship_evidence_complete",
          value: data.relationship_evidence_complete ?? "legacy",
          group: "result",
        },
        {
          key: "relationship_source_accounting_complete",
          value: sourceCoverage?.complete ?? "unavailable",
          group: "evidence",
        },
        {
          key: "relationship_source_fully_materialized",
          value: sourceFullyMaterialized,
          group: "evidence",
        },
        {
          key: "relationship_source_materialized",
          value: sourceCoverage?.materialized ?? "unavailable",
          group: "evidence",
        },
        {
          key: "relationship_source_reviewed_unavailable",
          value: sourceCoverage?.reviewed_unavailable ?? "unavailable",
          group: "evidence",
        },
        {
          key: "relationship_source_unclassified",
          value: sourceCoverage?.unclassified ?? "unavailable",
          group: "evidence",
        },
        { key: "truncation_reasons", value: data.truncation_reasons.join(", "), group: "result" },
        { key: "source_generation", value: data.source_generation, group: "evidence" },
        { key: "source_cutoff", value: data.source_cutoff, group: "evidence" },
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
          verification_status: e.verification_status,
          evidence_status: e.evidence?.status ?? "legacy",
          evidence_verification: e.evidence?.verification_status ?? "legacy",
          evidence_source: e.evidence?.source,
          evidence_cutoff: e.evidence?.cutoff,
          evidence_reason: e.evidence?.reason,
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
    {
      key: "v",
      header: t("ontology.blast.columnVerification"),
      render: (e) => {
        const evidence = impactEvidencePresentation(e);
        return <StatusPill kind={evidence.kind} label={evidence.label} />;
      },
    },
  ];

  return (
    <div class="stack blast-results">
      <section class="stack-section">
        <div class="section-header">
          <h3 class="section-title">{t("ontology.blast.topology")}</h3>
          <div class="segmented-control" role="group" aria-label={t("ontology.blast.viewLabel")}>
            <button type="button" class={view === "impact" ? "active" : ""} aria-pressed={view === "impact"} onClick={() => selectView("impact")}>{t("ontology.blast.viewImpact")}</button>
            <button type="button" class={view === "map" ? "active" : ""} aria-pressed={view === "map"} onClick={() => selectView("map")}>{t("ontology.blast.viewMap")}</button>
            <button type="button" class={view === "table" ? "active" : ""} aria-pressed={view === "table"} onClick={() => selectView("table")}>{t("ontology.blast.viewTable")}</button>
          </div>
        </div>
        {view === "impact" ? (
          <BlastImpact
            data={data}
            architectureView={architectureView}
            evidenceHref={evidenceHref}
          />
        ) : view === "map" ? (
          <BlastRadiusMap client={client} data={data} architectureView={architectureView} />
        ) : (
          <div class="stack blast-table-view">
            <section class="stack-section">
              <h4 class="section-title">
                {t("ontology.blast.reachedResources", {
                  count: formatNumber(data.reached.length),
                })}
              </h4>
              <DataTable
                columns={reachedColumns}
                rows={data.reached}
                keyOf={(node) => `${node.depth}:${node.resource_id}`}
                empty={t("ontology.blast.noReachable")}
              />
            </section>
            <section class="stack-section">
              <h4 class="section-title">
                {t("ontology.blast.edgesTraversed", {
                  count: formatNumber(data.edges.length),
                })}
              </h4>
              <DataTable
                columns={edgeColumns}
                rows={data.edges}
                keyOf={(_edge, index) => `${index}`}
                empty={t("ontology.blast.noEdges")}
              />
            </section>
          </div>
        )}
      </section>

      <BlastTraversalContract data={data} />
    </div>
  );
}
function BlastRadiusMap({ client, data, architectureView }: { readonly client: OperatorApiClient; readonly data: BlastRadiusResponse; readonly architectureView: string | null }) {
  const [graph, setGraph] = useState<InventoryGraphResponse | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  useEffect(() => {
    let cancelled = false;
    setGraph(null);
    setMessage(null);
    const params: Record<string, string> = {
      depth: String(data.traversal_depth),
      include: "contains,attached_to,depends_on,runtime_calls",
    };
    if (architectureView) params.scope = architectureView;
    client.panel<unknown>("/inventory/graph", params).then(
      (payload) => {
        if (cancelled) return;
        if (!isImpactMapGraph(payload)) {
          setMessage(t("ontology.blast.mapPayloadInvalid"));
          return;
        }
        const value = payload;
        if (!inventoryGraphMatchesImpact(value, data)) {
          setMessage(t("ontology.blast.mapSnapshotMismatch"));
          return;
        }
        if (!inventoryGraphContainsImpactTarget(value, data.target)) {
          setMessage(t("ontology.blast.mapTargetMissing"));
          return;
        }
        if (!inventoryGraphContainsImpact(value, data)) {
          setMessage(t("ontology.blast.mapImpactIncomplete"));
          return;
        }
        setGraph(value);
      },
      (error: unknown) => { if (!cancelled) setMessage(error instanceof Error ? error.message : String(error)); },
    );
    return () => { cancelled = true; };
  }, [client, architectureView, data.source_generation, data.source_cutoff]);
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

function isImpactMapGraph(value: unknown): value is InventoryGraphResponse {
  if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
  const record = value as Record<string, unknown>;
  if (
    typeof record.snapshot_at !== "string"
    || !isRfc3339Timestamp(record.snapshot_at)
    || !Array.isArray(record.resources)
    || !Array.isArray(record.links)
    || typeof record.truncated !== "boolean"
  ) {
    return false;
  }
  const resources = record.resources;
  if (
    resources.length > 1_000
    || resources.some((resource) => {
      if (typeof resource !== "object" || resource === null || Array.isArray(resource)) {
        return true;
      }
      const item = resource as Record<string, unknown>;
      return typeof item.id !== "string"
        || item.id.length === 0
        || typeof item.type !== "string"
        || item.type.length === 0
        || typeof item.name !== "string"
        || item.name.length === 0
        || typeof item.status !== "string"
        || item.status.length === 0;
    })
  ) {
    return false;
  }
  const resourceIds = new Set(
    resources.map((resource) => (resource as Record<string, unknown>).id as string),
  );
  const linkTypes = new Set([
    "contains",
    "attached_to",
    "depends_on",
    "peered_with",
    "runtime_calls",
  ]);
  return record.links.length <= 8_000 && record.links.every((link) => {
    if (typeof link !== "object" || link === null || Array.isArray(link)) return false;
    const item = link as Record<string, unknown>;
    return typeof item.source === "string"
      && typeof item.target === "string"
      && typeof item.type === "string"
      && item.source !== item.target
      && resourceIds.has(item.source)
      && resourceIds.has(item.target)
      && linkTypes.has(item.type);
  });
}
