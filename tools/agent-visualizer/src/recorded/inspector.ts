import type { Locale } from "../model";
import { t } from "../ui/i18n";
import type { RecordedAxis } from "./contract";
import { recorded } from "./state";
import { relationshipSubset } from "./layout";
import { renderMapDetail } from "./map-detail";

const date = (value: string | null) => value ? new Date(value).toISOString().replace("T", " ") : "-";
const PAGE_SIZE = 100;

/** The entire stored ontology map is primary; no Resource-only root or specimen scope is imposed. */
export class RecordedInspector {
  private key = "";
  private page = 0;
  private readonly rootSelect: HTMLSelectElement;
  private readonly typeSelect: HTMLSelectElement;
  private readonly linkSelect: HTMLSelectElement;
  private readonly controls: HTMLElement;

  constructor(private readonly panel: HTMLElement, private readonly detail: HTMLElement, onSelect: (id: string) => void) {
    panel.innerHTML = `<div class="ontology-heading"><span data-copy="fullMapTitle"></span><span id="recorded-status"></span></div>
      <div class="full-map-counts">
        <span><strong id="full-type-count">-</strong><small data-copy="allObjectTypes"></small></span>
        <span><strong id="full-catalog-count">-</strong><small data-copy="catalogNodes"></small></span>
        <span><strong id="full-instance-count">-</strong><small data-copy="databaseInstances"></small></span>
        <span><strong id="full-link-count">-</strong><small data-copy="storedRelationships"></small></span>
      </div>
      <div class="recorded-actions"><button id="snapshot-reload" data-copy="readLocalDatabase"></button>
        <div class="map-lenses" role="group" data-label="mapLayers">
          <button data-map-lens="all" data-copy="allMapObjects" aria-pressed="true"></button>
          <button data-map-lens="catalog" data-copy="catalogLayer" aria-pressed="false"></button>
          <button data-map-lens="instances" data-copy="instanceLayer" aria-pressed="false"></button>
        </div>
      </div>
      <div class="full-map-controls"><div class="ontology-settings">
        <label><span data-copy="objectTypeFilter"></span><select id="map-object-type"><option value="all">All</option></select></label>
        <label><span data-copy="relationshipFilter"></span><select id="relationship-filter"><option value="all">All</option></select></label>
        <label><span data-copy="jumpToType"></span><select id="recorded-root"><option value="">-</option></select></label>
      </div>
      <form id="recorded-search-form"><label class="sr-only" for="recorded-search" data-copy="searchMap"></label>
        <input id="recorded-search" type="search" maxlength="256"><button data-copy="searchMap"></button>
      </form>
      <div class="map-results"><select id="map-result-select" data-label="mapResults"></select>
        <button id="map-prev" data-label="previousMapPage">&lt;</button><span id="map-page"></span><button id="map-next" data-label="nextMapPage">&gt;</button></div></div>
      <div class="recorded-summary"><span id="recorded-counts"></span><span id="recorded-changes-count"></span></div>
      <div class="history-controls"><label class="check"><input id="map-history-replay" type="checkbox"><span data-copy="replayDbHistory"></span></label>
        <select id="map-history-axis" data-label="historyStateType"></select></div>
      <p id="recorded-cutoff"></p><p id="snapshot-replay-time"></p><p id="full-map-coverage"></p>
      <p id="recorded-error" role="status"></p><p class="ontology-disclaimer" data-copy="dbPrivacy"></p>`;
    detail.innerHTML = `<h2 class="micro" data-copy="mapSelection"></h2><div id="recorded-details"></div>`;
    this.rootSelect = panel.querySelector("#recorded-root")!;
    this.typeSelect = panel.querySelector("#map-object-type")!;
    this.linkSelect = panel.querySelector("#relationship-filter")!;
    this.controls = panel.querySelector(".full-map-controls")!;
    panel.querySelector("#snapshot-reload")!.addEventListener("click", () => { void recorded.reload(); });
    panel.querySelectorAll<HTMLButtonElement>("[data-map-lens]").forEach((button) => {
      button.onclick = () => {
        recorded.lens = button.dataset.mapLens as typeof recorded.lens;
        if (recorded.lens === "all") recorded.objectType = "all";
        this.page = 0;
        recorded.onChange();
      };
    });
    this.typeSelect.onchange = () => { this.page = 0; recorded.setObjectType(this.typeSelect.value); };
    this.rootSelect.onchange = () => { if (this.rootSelect.value) onSelect(this.rootSelect.value); };
    panel.querySelector("#recorded-search-form")!.addEventListener("submit", (event) => {
      event.preventDefault(); this.page = 0;
      recorded.search(this.controls.querySelector<HTMLInputElement>("#recorded-search")!.value);
    });
    panel.querySelector<HTMLSelectElement>("#map-result-select")!.onchange = (event) => {
      const value = (event.currentTarget as HTMLSelectElement).value;
      if (value) onSelect(value);
    };
    panel.querySelector<HTMLButtonElement>("#map-prev")!.onclick = () => { this.page--; this.key = ""; recorded.onChange(); };
    panel.querySelector<HTMLButtonElement>("#map-next")!.onclick = () => { this.page++; this.key = ""; recorded.onChange(); };
    panel.querySelector<HTMLInputElement>("#map-history-replay")!.onchange = (event) =>
      recorded.setReplayEnabled((event.currentTarget as HTMLInputElement).checked);
    panel.querySelector<HTMLSelectElement>("#map-history-axis")!.onchange = (event) =>
      recorded.setReplayStateType((event.currentTarget as HTMLSelectElement).value);
    detail.addEventListener("click", (event) => {
      const button = (event.target as HTMLElement).closest<HTMLButtonElement>("[data-map-node]");
      if (button?.dataset.mapNode) onSelect(button.dataset.mapNode);
      if ((event.target as HTMLElement).closest("#expand-type")) {
        const selected = recorded.graph?.resources.find((node) => node.id === recorded.selectedId);
        if (selected?.objectType) { recorded.objectType = selected.objectType; recorded.lens = "instances"; recorded.onChange(); }
      }
    });
    panel.closest("main")!.querySelector(".intro-panel")!.append(this.controls);
  }

  update(_axis: RecordedAxis, type: string, locale: Locale) {
    const graph = recorded.graph;
    const snapshot = recorded.snapshot;
    const subset = graph ? relationshipSubset(graph, type, recorded.lens, recorded.objectType) : null;
    this.panel.querySelector("#recorded-status")!.textContent = t(recorded.busy ? "readingDatabase"
      : recorded.status === "ready" ? "databaseSnapshotReady" : recorded.status === "error" ? "databaseReadFailed" : "readingDatabase", locale);
    this.panel.querySelector("#recorded-error")!.textContent = recorded.error ? t("databaseReadFailed", locale) : "";
    this.panel.querySelector<HTMLButtonElement>("#snapshot-reload")!.disabled = recorded.busy;
    this.panel.querySelector<HTMLInputElement>("#map-history-replay")!.checked = recorded.replayEnabled;
    this.panel.querySelector<HTMLInputElement>("#map-history-replay")!.disabled = !snapshot?.events.length;
    this.panel.querySelectorAll<HTMLButtonElement>("[data-map-lens]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.mapLens === recorded.lens)));
    this.panel.querySelector("#recorded-counts")!.textContent = graph
      ? `${subset!.resources.length}/${graph.resources.length} ${t("snapshotNodes", locale)} / ${subset!.links.length}/${graph.links.length} ${t("realLinks", locale)}` : "";
    this.panel.querySelector("#recorded-changes-count")!.textContent = snapshot ? `${snapshot.counts.history} ${t("dbTransitions", locale)}` : "";
    this.panel.querySelector("#recorded-cutoff")!.textContent = snapshot ? `${t("dbCapturedAt", locale)} ${date(snapshot.source.capturedAt)}` : "";
    this.panel.querySelector("#full-map-coverage")!.textContent = snapshot ? [
      snapshot.source.catalogComplete ? "" : t("catalogCoveragePartial", locale),
      snapshot.counts.unresolvedStoredLinks ? `${snapshot.counts.unresolvedStoredLinks} ${t("unresolvedDbLinks", locale)}` : "",
    ].filter(Boolean).join(" / ") : "";
    this.panel.querySelector("#snapshot-replay-time")!.textContent = recorded.replayEnabled
      ? `${t("dbHistoryTime", locale)} ${date(recorded.replayAt)}` : t("currentTopology", locale);
    for (const [id, value] of [
      ["full-type-count", snapshot?.counts.objectTypes], ["full-catalog-count", snapshot?.counts.catalogNodes],
      ["full-instance-count", snapshot?.counts.instances], ["full-link-count", snapshot?.counts.storedLinks],
    ] as const) this.panel.querySelector(`#${id}`)!.textContent = value === undefined ? "-" : value.toLocaleString("en-US");
    const key = `${graph?.generation}:${recorded.selectedId}:${type}:${recorded.lens}:${recorded.objectType}:${this.page}:${recorded.directory?.resources.length}:${recorded.events.length}:${recorded.replayEnabled}:${locale}:${recorded.status}`;
    if (key === this.key) return;
    this.key = key;
    const types = graph?.resources.filter((node) => node.nodeKind === "object_type") ?? [];
    this.typeSelect.replaceChildren(new Option(t("allObjectTypes", locale), "all"), ...types.map((node) =>
      new Option(`${node.name} (${node.instanceCount ?? 0})`, node.objectType!)));
    this.typeSelect.value = recorded.objectType;
    this.rootSelect.replaceChildren(new Option(t("jumpToType", locale), ""), ...types.map((node) => new Option(node.name!, node.id)));
    this.rootSelect.value = types.some((node) => node.id === recorded.selectedId) ? recorded.selectedId : "";
    const linkTypes = [...new Set(graph?.links.map((link) => link.type) ?? [])].sort();
    this.linkSelect.replaceChildren(new Option(t("allRelationships", locale), "all"), ...linkTypes.map((name) => new Option(name, name)));
    this.linkSelect.value = type;
    const stateTypes = [...new Set(snapshot?.events.map((event) => event.stateType) ?? [])].sort();
    const history = this.panel.querySelector<HTMLSelectElement>("#map-history-axis")!;
    history.replaceChildren(...stateTypes.map((name) => new Option(name, name)));
    history.value = recorded.replayStateType;
    const visible = new Set(subset?.resources.map((node) => node.id));
    const matches = recorded.directory?.resources.filter((node) => visible.has(node.id)) ?? [];
    const pages = Math.max(1, Math.ceil(matches.length / PAGE_SIZE));
    this.page = Math.max(0, Math.min(pages - 1, this.page));
    this.controls.querySelector<HTMLSelectElement>("#map-result-select")!.replaceChildren(new Option(t("chooseMapNode", locale), ""),
      ...matches.slice(this.page * PAGE_SIZE, (this.page + 1) * PAGE_SIZE).map((node) => new Option(`${node.name} / ${node.nodeKind}`, node.id)));
    this.controls.querySelector("#map-page")!.textContent = `${this.page + 1}/${pages} (${matches.length})`;
    this.controls.querySelector<HTMLButtonElement>("#map-prev")!.disabled = this.page === 0;
    this.controls.querySelector<HTMLButtonElement>("#map-next")!.disabled = this.page + 1 >= pages;
    this.controls.querySelector<HTMLInputElement>("#recorded-search")!.disabled = !snapshot || recorded.busy;
    this.controls.querySelector<HTMLButtonElement>("#recorded-search-form button")!.disabled = !snapshot || recorded.busy;
    renderMapDetail(this.detail.querySelector("#recorded-details")!, graph, recorded.selectedId, recorded.events, locale, recorded.replayEnabled);
  }
}
