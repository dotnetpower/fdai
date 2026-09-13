import { callsFrom, callsTo, functionById, functionsFor } from "../source-graph";
import type { AgentId, Locale } from "../model";
import { t } from "./i18n";

/** Searchable, keyboard-operable access to every indexed function, including unresolved receivers. */
export class FunctionInspector {
  private readonly list: HTMLElement;
  private readonly detail: HTMLElement;
  private readonly query: HTMLInputElement;
  private agent: AgentId | null = null;
  private selected: string | null = null;
  private locale: Locale = "en";
  private key = "";

  constructor(root: HTMLElement, private readonly onSelect: (id: string) => void) {
    root.innerHTML = `<details class="source-browser" open>
      <summary><span data-copy="pythonFunctions"></span><span id="function-count"></span></summary>
      <label class="sr-only" for="function-query" data-copy="searchFunctions"></label>
      <input id="function-query" type="search" autocomplete="off">
      <div id="function-list" class="function-list"></div><div id="function-detail"></div>
    </details>`;
    this.list = root.querySelector("#function-list")!;
    this.detail = root.querySelector("#function-detail")!;
    this.query = root.querySelector("#function-query")!;
    this.query.addEventListener("input", () => this.renderList());
    this.list.addEventListener("click", (event) => {
      const button = (event.target as HTMLElement).closest<HTMLButtonElement>("[data-function]");
      if (button?.dataset.function) this.onSelect(button.dataset.function);
    });
    this.detail.addEventListener("click", (event) => {
      const button = (event.target as HTMLElement).closest<HTMLButtonElement>("[data-function]");
      if (button?.dataset.function) this.onSelect(button.dataset.function);
    });
  }

  update(agent: AgentId | null, selected: string | null, locale: Locale) {
    const key = `${agent}:${selected}:${locale}`;
    if (key === this.key) return;
    const agentChanged = agent !== this.agent;
    this.key = key;
    this.agent = agent;
    this.selected = selected;
    this.locale = locale;
    if (agentChanged) this.query.value = "";
    this.query.placeholder = t("searchFunctions", locale);
    this.renderList();
    this.renderDetail();
  }

  private renderList() {
    const focused = document.activeElement instanceof HTMLButtonElement && this.list.contains(document.activeElement)
      ? document.activeElement.dataset.function : null;
    const functions = functionsFor(this.agent, this.query.value);
    const fragment = document.createDocumentFragment();
    for (const fn of functions) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.function = fn.id;
      button.setAttribute("aria-pressed", String(fn.id === this.selected));
      button.textContent = `${fn.async ? "async " : ""}${fn.id.split(".").slice(-2).join(".")}()`;
      button.title = `${fn.id}\n${fn.file}:${fn.line}`;
      fragment.append(button);
    }
    this.list.replaceChildren(fragment);
    if (focused) [...this.list.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) => button.dataset.function === focused)?.focus({ preventScroll: true });
    this.list.closest(".source-browser")!.querySelector("#function-count")!.textContent = String(functions.length);
    if (!functions.length) this.list.textContent = t("noFunctions", this.locale);
  }

  private renderDetail() {
    this.detail.replaceChildren();
    const fn = this.selected ? functionById.get(this.selected) : null;
    if (!fn) return;
    const title = document.createElement("h3");
    title.textContent = `${fn.id}()`;
    const source = document.createElement("p");
    source.className = "source-location";
    source.textContent = `${fn.file}:${fn.line}`;
    const badge = document.createElement("p");
    badge.className = "source-evidence";
    badge.textContent = t("staticDefinition", this.locale);
    this.detail.append(title, source, badge);
    for (const [heading, ids] of [[t("callsTo", this.locale), callsFrom.get(fn.id)], [t("calledBy", this.locale), callsTo.get(fn.id)]] as const) {
      const label = document.createElement("h4");
      label.textContent = `${heading} (${ids?.size ?? 0})`;
      this.detail.append(label);
      for (const id of ids ?? []) {
        const button = document.createElement("button");
        button.type = "button";
        button.dataset.function = id;
        button.textContent = `${id.split(".").slice(-2).join(".")}()`;
        button.title = id;
        this.detail.append(button);
      }
    }
    if (fn.unresolved.length) {
      const unresolved = document.createElement("details");
      const summary = document.createElement("summary");
      summary.textContent = `${t("unresolvedCalls", this.locale)} (${fn.unresolved.length})`;
      unresolved.append(summary);
      for (const call of fn.unresolved) {
        const line = document.createElement("p");
        line.textContent = `${call.symbol}() :${call.line}`;
        unresolved.append(line);
      }
      this.detail.append(unresolved);
    }
  }
}
