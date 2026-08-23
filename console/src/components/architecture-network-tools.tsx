import { t } from "../routes/i18n/architecture";
import {
  type ArchitectureNetworkFilters,
  type ArchitectureNetworkPathResult,
} from "./architecture-network-focus";
import type { InventoryGraphResponse } from "./architecture-map.model";

interface Props {
  readonly graph: InventoryGraphResponse;
  readonly sourceId: string | null;
  readonly targetId: string | null;
  readonly result: ArchitectureNetworkPathResult | null;
  readonly filters: ArchitectureNetworkFilters;
  readonly onSourceChange: (resourceId: string | null) => void;
  readonly onTargetChange: (resourceId: string | null) => void;
  readonly onToggleFilter: (key: keyof ArchitectureNetworkFilters) => void;
  readonly onExportSvg: () => void;
  readonly onExportPng: () => void;
}

const FILTER_LABELS: Readonly<Record<keyof ArchitectureNetworkFilters, string>> = {
  publicExposure: "network.filter.publicExposure",
  privateResources: "network.filter.privateResources",
  security: "network.filter.security",
  gateways: "network.filter.gateways",
  dns: "network.filter.dns",
  privateEndpoints: "network.filter.privateEndpoints",
};

export function ArchitectureNetworkTools({
  graph,
  sourceId,
  targetId,
  result,
  filters,
  onSourceChange,
  onTargetChange,
  onToggleFilter,
  onExportSvg,
  onExportPng,
}: Props) {
  const selectable = graph.resources.filter((resource) => resource.type !== "subscription");
  const byId = new Map(graph.resources.map((resource) => [resource.id, resource]));
  return (
    <section class="architecture-network-tools" aria-labelledby="architecture-network-tools-title">
      <div class="architecture-network-tools-heading">
        <div>
          <h3 id="architecture-network-tools-title">{t("network.title")}</h3>
          <p>{t("network.observedOnly")}</p>
        </div>
        <div class="architecture-network-export" role="group" aria-label={t("network.export") }>
          <button type="button" onClick={onExportSvg}>{t("network.svg")}</button>
          <button type="button" onClick={onExportPng}>{t("network.png")}</button>
        </div>
      </div>
      <div class="architecture-network-path-controls">
        <label>
          <span>{t("network.source")}</span>
          <select value={sourceId ?? ""} onChange={(event) => onSourceChange(event.currentTarget.value || null)}>
            <option value="">{t("network.selectSource")}</option>
            {selectable.map((resource) => <option value={resource.id}>{resource.name}</option>)}
          </select>
        </label>
        <span class="architecture-network-path-arrow" aria-hidden="true">-&gt;</span>
        <label>
          <span>{t("network.destination")}</span>
          <select value={targetId ?? ""} onChange={(event) => onTargetChange(event.currentTarget.value || null)}>
            <option value="">{t("network.selectDestination")}</option>
            {selectable.map((resource) => <option value={resource.id}>{resource.name}</option>)}
          </select>
        </label>
        <output class={`architecture-network-path-result is-${result?.status ?? "idle"}`} aria-live="polite">
          {result ? t(`network.path.${result.status}`, { count: result.hops.length }) : t("network.path.idle")}
        </output>
      </div>
      {result?.status === "found" ? (
        <ol class="architecture-network-path-hops" aria-label={t("network.observedHops") }>
          {result.hops.map((hop) => (
            <li key={`${hop.source}:${hop.link.type}:${hop.target}`}>
              <span>{byId.get(hop.source)?.name ?? t("unavailable")}</span>
              <code>{hop.link.type}</code>
              <span>{byId.get(hop.target)?.name ?? t("unavailable")}</span>
              <small>{t(`network.evidence.${hop.evidencePosture}`)}</small>
            </li>
          ))}
        </ol>
      ) : null}
      <fieldset class="architecture-network-filters">
        <legend>{t("network.filters")}</legend>
        {(Object.keys(FILTER_LABELS) as Array<keyof ArchitectureNetworkFilters>).map((key) => (
          <label>
            <input type="checkbox" checked={filters[key]} onChange={() => onToggleFilter(key)} />
            {t(FILTER_LABELS[key])}
          </label>
        ))}
      </fieldset>
    </section>
  );
}
