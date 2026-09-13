import { readOntologySnapshot } from "./ontology-instance-reader.js";

const byId = (id) => document.getElementById(id);
const node = (tag, value, className) => {
  const element = document.createElement(tag);
  if (value) element.textContent = value;
  if (className) element.className = className;
  return element;
};

/** Own draft selection by exact instance/source/generation; every reread invalidates the draft. */
export function createOntologyPicker() {
  let snapshot;
  let controller;
  let revision = 0;
  const selected = new Map();
  const picker = byId("ontology-picker");
  const search = byId("target-search");
  const group = byId("target-group");
  const scenario = byId("target-scenario");
  const save = byId("create-rule");
  const canSelect = () => snapshot?.completeness === "complete" && snapshot.instances.length > 0;
  const currentType = () => document.querySelector('[name="targetType"]:checked').value;

  function renderSelection() {
    byId("selected-count").textContent = `${selected.size} selected`;
    byId("selected-empty").hidden = selected.size > 0;
    byId("selected-targets").replaceChildren(...[...selected.values()].map((item) => {
      const row = node("li");
      row.dataset.instanceId = item.id;
      const copy = node("div");
      copy.append(node("strong", item.name), node("span", item.description), node("code", item.id));
      const remove = node("button", "Remove", "cs-btn is-quiet");
      remove.type = "button";
      remove.setAttribute("aria-label", `Remove ${item.name} / ${item.id}`);
      remove.addEventListener("click", () => {
        selected.delete(item.id);
        renderRows();
        renderSelection();
        const next = byId("selected-targets").querySelector("button");
        (next ?? search).focus();
      });
      row.append(copy, remove);
      return row;
    }));
  }

  function renderRows() {
    const type = currentType();
    byId("target-group-field").hidden = type !== "Resource";
    const candidates = snapshot?.instances.filter((item) => item.objectType === type) ?? [];
    const query = search.value.trim().toLowerCase();
    const visible = candidates.filter((item) => (!group.value || type !== "Resource" || item.groupId === group.value)
      && `${item.name} ${item.id} ${item.description}`.toLowerCase().includes(query));
    byId("target-count").textContent = snapshot
      ? `${visible.length} of ${candidates.length} recorded ${type === "Resource" ? "resources" : "resource groups"}`
      : "Recorded instance count unavailable";
    byId("target-options").replaceChildren(...visible.map((item) => {
      const row = node("label", "", "oa-instance-row");
      const input = node("input");
      input.type = "checkbox";
      input.name = "target";
      input.value = item.id;
      input.className = "cs-control-checkbox";
      input.checked = selected.has(item.id);
      input.disabled = !canSelect();
      input.setAttribute("aria-label", `${item.name} / ${item.id}`);
      const copy = node("span", "", "oa-instance-copy");
      copy.append(node("strong", item.name), node("span", item.description), node("code", item.id));
      row.append(input, copy);
      input.addEventListener("change", () => {
        if (!canSelect()) return;
        if (input.checked) selected.set(item.id, item);
        else selected.delete(item.id);
        renderSelection();
      });
      return row;
    }));
    const noMatch = byId("target-no-match");
    noMatch.hidden = !snapshot || visible.length > 0;
    noMatch.textContent = snapshot?.instances.length === 0
      ? "No recorded ontology instances in this mock snapshot. Catalog types are not selectable targets."
      : "No matching recorded instances. Change the search, resource group filter, or target type.";
    byId("clear-target-filters").hidden = !snapshot || (!query && !group.value);
  }

  async function load() {
    controller?.abort();
    controller = new AbortController();
    const currentRevision = ++revision;
    const hadSelection = selected.size > 0;
    selected.clear();
    snapshot = undefined;
    save.disabled = true;
    picker.dataset.sourceState = "loading";
    picker.setAttribute("aria-busy", "true");
    byId("target-loading").hidden = false;
    byId("target-source-error").hidden = true;
    byId("target-provenance").hidden = true;
    byId("target-source-summary").textContent = "Local synthetic snapshot / loading";
    byId("target-change").textContent = hadSelection
      ? "Source changed or reloaded. Previous selections were cleared; review and select again."
      : "";
    group.replaceChildren(new Option("All resource groups", ""));
    group.disabled = true;
    search.disabled = true;
    renderRows();
    renderSelection();
    try {
      const result = await readOntologySnapshot({ signal: controller.signal, scenario: scenario.value });
      if (currentRevision !== revision) return;
      snapshot = result;
      picker.dataset.sourceState = result.instances.length === 0 ? "empty" : result.completeness === "partial" ? "partial" : "ready";
      byId("target-source").textContent = `${result.source.label} / ${result.source.id}`;
      byId("target-generation").textContent = result.generation;
      byId("target-recorded").textContent = result.recordedAt;
      byId("target-completeness").textContent = `${result.completeness} / ${result.coverage}`;
      byId("target-source-summary").textContent = `${result.source.label} / ${result.generation} / recorded ${result.recordedAt} / ${result.completeness}. ${result.coverage}`;
      byId("target-derivation").textContent = `${result.source.derivedFrom}. ${result.source.derivation}`;
      byId("target-provenance").hidden = false;
      result.instances.filter((item) => item.objectType === "ResourceGroup").forEach((item) => group.add(new Option(item.name, item.id)));
      group.disabled = false;
      search.disabled = false;
      save.disabled = !canSelect();
      renderRows();
    } catch (error) {
      if (currentRevision !== revision) return;
      picker.dataset.sourceState = scenario.value === "unavailable" || scenario.value === "loading" ? "unavailable" : "error";
      byId("target-source-summary").textContent = "Local synthetic snapshot / no validated source available";
      const message = error.name === "AbortError" ? "Synthetic ontology read deadline reached. Source unavailable." : error.message;
      byId("target-source-error").textContent = `${message} Use Reload mock snapshot to try again. No fallback targets are used.`;
      byId("target-source-error").hidden = false;
    } finally {
      if (currentRevision === revision) {
        picker.setAttribute("aria-busy", "false");
        byId("target-loading").hidden = true;
      }
    }
  }

  search.addEventListener("input", renderRows);
  group.addEventListener("change", renderRows);
  document.querySelectorAll('[name="targetType"]').forEach((input) => input.addEventListener("change", renderRows));
  byId("clear-target-filters").addEventListener("click", () => {
    search.value = "";
    group.value = "";
    renderRows();
    search.focus();
  });
  scenario.addEventListener("change", load);
  byId("reload-targets").addEventListener("click", load);
  return {
    open() { search.value = ""; selected.clear(); load(); },
    close() {
      ++revision;
      controller?.abort();
      selected.clear();
      snapshot = undefined;
      save.disabled = true;
      picker.setAttribute("aria-busy", "false");
      byId("target-loading").hidden = true;
      renderRows();
      renderSelection();
    },
    selection() {
      if (!canSelect()) return null;
      const values = [...selected.values()];
      return values.every((item) => item.sourceId === snapshot.source.id
        && item.generation === snapshot.generation && item.recordedAt === snapshot.recordedAt
        && snapshot.instances.includes(item)) ? values : null;
    },
  };
}
