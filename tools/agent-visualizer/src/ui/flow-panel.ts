import { codeGraph } from "../source-graph";
import { eventFlowAt, ARG_VISUAL_HZ } from "../playback/event-flow";
import { ARG_WORKFLOWS, independentWorkloads } from "../playback/workloads";
import { localized, type AgentId, type Locale, type Scenario } from "../model";
import { t } from "./i18n";
import { agentColor } from "../agents";

/** Independent lanes and overlapping broadcasts are explicitly synthetic, even over real source paths. */
export class FlowPanel {
  private key = "";
  private readonly lanes = new Map<AgentId, HTMLButtonElement>();
  private readonly parallelCount: HTMLElement;
  private readonly broadcastTopic: HTMLElement;
  private readonly fanoutCount: HTMLElement;
  private readonly broadcastDetail: HTMLElement;

  constructor(private readonly root: HTMLElement, onFunction: (id: string) => void) {
    root.innerHTML = `<div class="flow-heading">
        <span data-copy="parallelDemo"></span><strong id="parallel-count">0</strong>
        <span id="tour-status" class="tour-status" hidden></span>
        <span class="ast-badge">PYTHON AST</span>
      </div>
      <div id="concurrent-agents" class="concurrent-agents"></div>
      <details id="broadcast-panel" tabindex="-1">
        <summary><span id="broadcast-topic"></span><span id="fanout-count"></span></summary>
        <div id="broadcast-detail"></div>
      </details>
      <div class="arg-budget"><span>Huginn / <span data-copy="inventoryWorker"></span></span>
        <strong>Azure Resource Graph ${ARG_VISUAL_HZ} req/s</strong></div>
      <div class="arg-workflows"></div>
      <p class="rate-note" data-copy="argRateNote"></p>`;
    this.parallelCount = root.querySelector("#parallel-count")!;
    this.broadcastTopic = root.querySelector("#broadcast-topic")!;
    this.fanoutCount = root.querySelector("#fanout-count")!;
    this.broadcastDetail = root.querySelector("#broadcast-detail")!;
    const group = root.querySelector("#concurrent-agents")!;
    for (const work of independentWorkloads) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "workload-lane";
      button.dataset.workloadAgent = work.agent;
      button.style.setProperty("--agent-color", agentColor(work.agent));
      button.innerHTML = `<span>${work.agent}</span><span class="lane-state"></span><i aria-hidden="true"></i>`;
      button.addEventListener("click", () => onFunction(work.functionId));
      this.lanes.set(work.agent, button);
      group.append(button);
    }
    for (const workflow of ARG_WORKFLOWS) {
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.argWorkflow = workflow.id;
      button.addEventListener("click", () => onFunction(workflow.query));
      root.querySelector(".arg-workflows")!.append(button);
    }
  }

  update(time: number, scenario: Scenario, locale: Locale) {
    const flow = eventFlowAt(time, scenario);
    for (const work of flow.independent) {
      const lane = this.lanes.get(work.agent)!;
      lane.classList.toggle("is-active", work.active);
      lane.dataset.active = String(work.active);
      lane.style.setProperty("--lane-progress", `${work.progress * 100}%`);
      lane.querySelector(".lane-state")!.textContent = t(work.active ? "working" : "waitingLane", locale);
      lane.title = `${localized(work.purpose, locale)}\n${work.functionId}()`;
      lane.setAttribute("aria-label", `${work.agent}: ${localized(work.purpose, locale)}. ${t(work.active ? "working" : "waitingLane", locale)}`);
    }
    this.parallelCount.textContent = String(flow.independent.filter((work) => work.active).length);
    const key = `${flow.broadcasts.map((broadcast) => `${broadcast.topic.id}:${broadcast.phase}`).join(",")}:${locale}`;
    if (key === this.key) return;
    this.key = key;
    this.broadcastTopic.textContent = `${t("overlappingBroadcasts", locale)}: ${flow.broadcasts.length}`;
    this.fanoutCount.textContent = `${new Set(flow.broadcasts.flatMap((broadcast) => broadcast.subscribers)).size} ${t("subscribers", locale)}`;
    this.broadcastDetail.replaceChildren();
    for (const broadcast of flow.broadcasts) {
      const route = document.createElement("p");
      route.textContent = `${t(broadcast.phase, locale)}: ${broadcast.topic.publisher} -> ${broadcast.topic.id} -> ${broadcast.subscribers.join(", ")}`;
      this.broadcastDetail.append(route);
      for (const record of codeGraph.agents.filter((agent) => broadcast.topic.subscribers.includes(agent.id))) {
        const handler = document.createElement("code");
        handler.textContent = record.handler ?? `${record.id}: unresolved handler`;
        this.broadcastDetail.append(handler);
      }
    }
    const note = document.createElement("p");
    note.textContent = t("declarationOnly", locale);
    this.broadcastDetail.append(note);
    for (const workflow of ARG_WORKFLOWS) {
      const button = this.root.querySelector<HTMLButtonElement>(`[data-arg-workflow="${workflow.id}"]`)!;
      button.textContent = localized(workflow.purpose, locale);
      button.title = `${workflow.entry}() -> ${workflow.query}() -> Azure Resource Graph`;
    }
  }
}
