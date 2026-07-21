import {
  RESOURCE_COLOR_TOKENS,
  resourceColorTokenOf,
  type InventoryGraphResponse,
  type InventoryResource,
} from "./architecture-map.model";

interface Props {
  readonly graph: InventoryGraphResponse;
  readonly onSelect: (resource: InventoryResource | null) => void;
}

const RELATIONSHIP_LABELS = {
  contains: "Contains ->",
  attached_to: "Attached to",
  depends_on: "Depends on ->",
} as const;

export function ArchitectureRelationIndex({ graph, onSelect }: Props) {
  const byId = new Map(graph.resources.map((resource) => [resource.id, resource]));
  return (
    <details class="architecture-relation-index">
      <summary>Resource and relationship index</summary>
      <div class="architecture-index-grid">
        <section aria-labelledby="architecture-resource-index-title">
          <h3 id="architecture-resource-index-title">Resources</h3>
          <div class="architecture-index-table-wrap">
            <table>
              <thead><tr><th>Name</th><th>Type</th><th>Status</th></tr></thead>
              <tbody>
                {graph.resources.map((resource) => (
                  <tr key={resource.id}>
                    <th scope="row"><button type="button" onClick={() => onSelect(resource)}>{resource.name}</button></th>
                    <td>{RESOURCE_COLOR_TOKENS[resourceColorTokenOf(resource)].label}</td>
                    <td>{resource.status.toLowerCase() === "unknown" ? "Unavailable" : resource.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <section aria-labelledby="architecture-relationship-index-title">
          <h3 id="architecture-relationship-index-title">Relationships</h3>
          {graph.links.length > 0 ? (
            <ul class="architecture-index-relationships">
              {graph.links.map((link) => (
                <li key={`${link.source}:${link.type}:${link.target}`}>
                  <button type="button" onClick={() => onSelect(byId.get(link.source) ?? null)}>
                    {byId.get(link.source)?.name ?? link.source}
                  </button>
                  <span>{RELATIONSHIP_LABELS[link.type]}</span>
                  <button type="button" onClick={() => onSelect(byId.get(link.target) ?? null)}>
                    {byId.get(link.target)?.name ?? link.target}
                  </button>
                </li>
              ))}
            </ul>
          ) : <p>No relationships were reported.</p>}
        </section>
      </div>
    </details>
  );
}
