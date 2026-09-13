import { codeGraph, functionById } from "../source-graph";
import type { AgentId, Locale } from "../model";
import { t } from "./i18n";

/** Inspect every declared route relevant to the selected agent, not only the animated topics. */
export class TopicInspector {
  private key = "";
  private readonly content: HTMLElement;
  private readonly summary: HTMLElement;

  constructor(root: HTMLElement, onFunction: (id: string) => void) {
    root.innerHTML = `<details class="topic-browser"><summary></summary><div></div></details>`;
    this.content = root.querySelector("details > div")!;
    this.summary = root.querySelector("summary")!;
    root.addEventListener("click", (event) => {
      const button = (event.target as HTMLElement).closest<HTMLButtonElement>("[data-function]");
      if (button?.dataset.function) onFunction(button.dataset.function);
    });
  }

  update(agent: AgentId | null, locale: Locale) {
    const key = `${agent}:${locale}`;
    if (key === this.key) return;
    this.key = key;
    const topics = codeGraph.topics.filter((topic) => !agent || topic.publisher === agent || topic.subscribers.includes(agent));
    this.summary.textContent = `${t("topicDeclarations", locale)} (${topics.length})`;
    const note = document.createElement("p");
    note.textContent = t("subscriptionScope", locale);
    this.content.replaceChildren(note);
    for (const topic of topics) {
      const row = document.createElement("details");
      const title = document.createElement("summary");
      title.textContent = topic.id;
      const route = document.createElement("p");
      route.textContent = `${topic.publisher} -> ${topic.subscribers.join(", ") || "(no declared agent subscriber)"}`;
      row.append(title, route);
      const ids = [...topic.publisher_functions, ...codeGraph.agents
        .filter((record) => topic.subscribers.includes(record.id))
        .map((record) => record.handler).filter((id): id is string => id !== null)];
      for (const id of new Set(ids)) {
        if (!functionById.has(id)) continue;
        const button = document.createElement("button");
        button.type = "button";
        button.dataset.function = id;
        button.textContent = `${id.split(".").slice(-2).join(".")}()`;
        button.title = id;
        row.append(button);
      }
      this.content.append(row);
    }
  }
}
