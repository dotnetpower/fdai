import {
  RESOURCE_COLOR_TOKENS,
  resourceColorTokenOf,
  type InventoryGraphResponse,
  type InventoryResource,
} from "./architecture-map.model";
import { t } from "../routes/i18n/architecture";

interface Props {
  readonly graph: InventoryGraphResponse;
  readonly onSelect: (resource: InventoryResource | null) => void;
}

const RELATIONSHIP_LABELS = {
  contains: "relationship.containsArrow",
  attached_to: "relationship.attachedTo",
  depends_on: "relationship.dependsOnArrow",
  peered_with: "relationship.peersWithArrow",
} as const;

export function architectureRelationshipIndexLabel(type: InventoryGraphResponse["links"][number]["type"]): string {
  return t(RELATIONSHIP_LABELS[type]);
}

export function ArchitectureRelationIndex({ graph, onSelect }: Props) {
  const byId = new Map(graph.resources.map((resource) => [resource.id, resource]));
  return (
    <details class="architecture-relation-index">
      <summary>{t("indexTitle")}</summary>
      <div class="architecture-index-grid">
        <section aria-labelledby="architecture-resource-index-title">
          <h3 id="architecture-resource-index-title">{t("resources")}</h3>
          <div class="architecture-index-table-wrap">
            <table>
              <thead><tr><th>{t("name")}</th><th>{t("type")}</th><th>{t("status")}</th></tr></thead>
              <tbody>
                {graph.resources.map((resource) => (
                  <tr key={resource.id}>
                    <th scope="row"><button type="button" onClick={() => onSelect(resource)}>{resource.name}</button></th>
                    <td>{RESOURCE_COLOR_TOKENS[resourceColorTokenOf(resource)].label}</td>
                    <td>{resource.status.toLowerCase() === "unknown" ? t("unavailable") : resource.status}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <section aria-labelledby="architecture-relationship-index-title">
          <h3 id="architecture-relationship-index-title">{t("relationships")}</h3>
          {graph.links.length > 0 ? (
            <ul class="architecture-index-relationships">
              {graph.links.map((link) => (
                <li key={`${link.source}:${link.type}:${link.target}`}>
                  <button type="button" onClick={() => onSelect(byId.get(link.source) ?? null)}>
                    {byId.get(link.source)?.name ?? link.source}
                  </button>
                  <span>{architectureRelationshipIndexLabel(link.type)}</span>
                  <button type="button" onClick={() => onSelect(byId.get(link.target) ?? null)}>
                    {byId.get(link.target)?.name ?? link.target}
                  </button>
                </li>
              ))}
            </ul>
          ) : <p>{t("noRelationships")}</p>}
        </section>
      </div>
    </details>
  );
}
