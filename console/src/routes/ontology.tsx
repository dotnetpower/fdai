import { useEffect, useState } from "preact/hooks";
import type { ReadApiClient } from "../api";
import {
  AsyncBoundary,
  KpiCard,
  KpiGrid,
  PageHeader,
  type AsyncState,
} from "../components/ui";
import { MermaidDiagram } from "../components/mermaid-diagram";
import {
  OntologyGraph,
  type OntologyEdge,
  type OntologyNode,
} from "../components/ontology-graph";
import { usePublishViewContext } from "../deck/context";

/**
 * Ontology explorer panel. Fetches ``GET /ontology/graph`` and renders
 * the returned Mermaid ``classDiagram`` text as a copyable block plus
 * a small manifest of counts and known types.
 *
 * We intentionally do NOT bundle mermaid.js. A fork that wants an
 * inline rendered diagram can add ``mermaid`` as an extra dependency
 * and wrap this component; the shipped panel keeps the console
 * dependency-light and works offline.
 */

interface OntologyGraphResponse {
  readonly mermaid: string;
  readonly object_type_count: number;
  readonly link_type_count: number;
  readonly object_types: readonly string[];
  readonly link_types: readonly string[];
  /** Structured nodes for the custom SVG renderer. Absent on old servers. */
  readonly nodes?: readonly OntologyNode[];
  /** Structured edges for the custom SVG renderer. Absent on old servers. */
  readonly edges?: readonly OntologyEdge[];
}

interface Props {
  readonly client: ReadApiClient;
}

export function OntologyRoute({ client }: Props) {
  const [state, setState] = useState<AsyncState<OntologyGraphResponse>>({ status: "loading" });
  const [includeProperties, setIncludeProperties] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setState({ status: "loading" });
    (async () => {
      try {
        const data = await client.panel<OntologyGraphResponse>(
          "/ontology/graph",
          { include_properties: includeProperties ? "true" : "false" },
        );
        if (!cancelled) setState({ status: "ready", data });
      } catch (err) {
        if (!cancelled) {
          const message = err instanceof Error ? err.message : String(err);
          if (message.includes("404")) {
            setState({
              status: "unavailable",
              message:
                "The ontology explorer route is not wired on this deployment. " +
                "Set ReadApiConfig.ontology_object_types + ontology_link_types " +
                "in the composition root to enable it.",
            });
          } else {
            setState({ status: "error", message });
          }
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [client, includeProperties]);

  return (
    <div class="stack">
      <PageHeader
        title="Ontology"
        subtitle="ObjectTypes and LinkTypes registered on this deployment, rendered as a Mermaid classDiagram."
        actions={
          <label class="inline-toggle">
            <input
              type="checkbox"
              checked={includeProperties}
              onChange={(e) => setIncludeProperties((e.target as HTMLInputElement).checked)}
            />
            show properties
          </label>
        }
      />
      <AsyncBoundary state={state} resourceLabel="ontology graph">
        {(data) => <OntologyBody data={data} />}
      </AsyncBoundary>
    </div>
  );
}

function OntologyBody({
  data,
}: {
  readonly data: OntologyGraphResponse;
}) {
  usePublishViewContext(
    () => ({
      routeId: "ontology",
      routeLabel: "Ontology",
      headline: `${data.object_type_count} ObjectTypes - ${data.link_type_count} LinkTypes`,
      capturedAt: new Date().toISOString(),
      facts: [
        { key: "object_type_count", value: data.object_type_count, group: "graph" },
        { key: "link_type_count", value: data.link_type_count, group: "graph" },
      ],
      records: {
        object_types: data.object_types.map((name) => ({ name })),
        link_types: data.link_types.map((name) => ({ name })),
      },
    }),
    [data],
  );
  return (
    <div class="stack">
      <KpiGrid>
        <KpiCard label="ObjectTypes" value={data.object_type_count} />
        <KpiCard label="LinkTypes" value={data.link_type_count} />
      </KpiGrid>

      <section class="stack-section">
        <div class="section-header">
          <h3 class="section-title">Resource + link graph</h3>
        </div>
        {data.nodes && data.edges ? (
          <OntologyGraph nodes={data.nodes} edges={data.edges} />
        ) : (
          <MermaidDiagram source={data.mermaid} ariaLabel="Ontology class diagram" />
        )}
        <details class="mermaid-source-toggle">
          <summary class="details-summary">Show Mermaid source</summary>
          <pre class="mono scroll code-block">{data.mermaid}</pre>
        </details>
      </section>

      <div class="two-col">
        <section class="stack-section">
          <h3 class="section-title">ObjectTypes ({data.object_types.length})</h3>
          <TypeChipList names={data.object_types} />
        </section>
        <section class="stack-section">
          <h3 class="section-title">LinkTypes ({data.link_types.length})</h3>
          <TypeChipList names={data.link_types} />
        </section>
      </div>
    </div>
  );
}

function TypeChipList({ names }: { readonly names: readonly string[] }) {
  if (names.length === 0) {
    return <div class="muted">None registered.</div>;
  }
  return (
    <ul class="type-chip-list">
      {names.map((name) => (
        <li key={name} class="type-chip mono">{name}</li>
      ))}
    </ul>
  );
}
