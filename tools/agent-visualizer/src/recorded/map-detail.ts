import type { RecordedGraph } from "./contract";
import type { SnapshotEvent } from "./snapshot";
import type { Locale } from "../model";
import { t } from "../ui/i18n";

const date = (value: string | null) => value ? new Date(value).toISOString().replace("T", " ") : "-";

/** Render exact catalog meaning and private DB metadata without exporting original names or bodies. */
export function renderMapDetail(container: HTMLElement, graph: RecordedGraph | null, selected: string, events: readonly SnapshotEvent[], locale: Locale, replay: boolean) {
  container.replaceChildren();
  const node = graph?.resources.find((item) => item.id === selected);
  const paragraph = (text: string, className = "") => {
    const element = document.createElement("p"); element.textContent = text; element.className = className; return element;
  };
  if (!graph || !node) { container.append(paragraph(t("databaseReadHint", locale))); return; }
  const heading = document.createElement("h3");
  heading.className = "instance-name";
  heading.textContent = node.name;
  container.append(heading, paragraph(`${node.nodeKind} / ${node.objectType ?? node.resourceType}`, "source-location"));
  if (node.detail) container.append(paragraph(node.detail, "map-description"));
  if (node.nodeKind === "object_type") {
    container.append(paragraph(`${node.instanceCount ?? 0} ${t("databaseInstances", locale)}`, "type-instance-count"));
    const expand = document.createElement("button"); expand.id = "expand-type";
    expand.textContent = t("expandTypeInstances", locale); expand.disabled = !node.instanceCount;
    container.append(expand);
  }
  if (node.nodeKind === "instance") {
    container.append(paragraph(`${t("privateInstanceId", locale)} ${node.id}`, "source-location"));
    const state = node.storedState;
    const facts = document.createElement("dl"); facts.className = "instance-facts";
    const term = document.createElement("dt"); term.textContent = t("storedDbState", locale);
    const value = document.createElement("dd"); value.id = "snapshot-current-state"; value.textContent = state?.value ?? t("unknown", locale);
    facts.append(term, value); container.append(facts);
    if (replay) container.append(paragraph(`${t("replayedState", locale)} ${node.presentationState ?? t("unknown", locale)}`, "coverage-note"));
    container.append(paragraph(`${state?.lane ?? "stored"} / revision ${node.revision ?? "-"}\n${t("effectiveTime", locale)} ${date(state?.effectiveAt ?? null)}\n${t("recordedTime", locale)} ${date(state?.recordedAt ?? null)}`, "coverage-note"));
    container.append(paragraph(t("storedStateLimit", locale), "ontology-disclaimer"));
  }
  const related = graph.links.filter((link) => link.source === node.id || link.target === node.id)
    .sort((a, b) => Number(a.origin === "classification") - Number(b.origin === "classification") || a.type.localeCompare(b.type));
  const relations = document.createElement("section"); relations.className = "recorded-relationships";
  const title = document.createElement("h4"); title.textContent = `${t("realLinks", locale)} (${related.length})`;
  relations.append(title);
  const byId = new Map(graph.resources.map((item) => [item.id, item]));
  for (const link of related.slice(0, 80)) {
    const target = byId.get(link.source === node.id ? link.target : link.source)!;
    const button = document.createElement("button"); button.type = "button"; button.dataset.mapNode = target.id;
    button.textContent = `${link.source === node.id ? "->" : "<-"} ${link.type} / ${link.origin}\n${target.name}`;
    relations.append(button);
  }
  if (related.length > 80) relations.append(paragraph(t("detailRelationLimit", locale)));
  container.append(relations);
  const history = events.filter((event) => node.nodeKind === "object_type" ? byId.get(event.resourceId)?.objectType === node.objectType : event.resourceId === node.id);
  const section = document.createElement("section");
  const historyTitle = document.createElement("h4"); historyTitle.textContent = `${t("dbTransitions", locale)} (${history.length})`;
  section.append(historyTitle, paragraph(t("historyCoverageLimit", locale)));
  for (const event of history.slice(-40)) {
    section.append(paragraph(
      `${event.before ?? t("unknown", locale)} -> ${event.state ?? t("unknown", locale)}\n${event.stateType} / ${event.lane}${event.synthetic ? " / synthetic" : ""}\n${date(event.at)}\n${t("recordedTime", locale)} ${date(event.recordedAt)}\n${event.completeness * 100}% / ${event.conflicts} conflicts`,
      "history-row",
    ));
  }
  if (history.length > 40) section.append(paragraph(t("detailHistoryLimit", locale)));
  container.append(section);
}
