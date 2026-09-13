import logoUrl from "../../../../console/public/brand/fdai-logo.png";
import { agents, agentById, agentColor } from "../agents";
import { localized, type AgentId, type CameraMode, type Locale, type Scenario } from "../model";
import { DEFAULT_PLAYBACK_SPEED, formatTime, projectTimeline } from "../playback/timeline";
import { t, type MessageKey } from "./i18n";
import { icon } from "./icons";
import { FunctionInspector } from "./function-inspector";
import { FlowPanel } from "./flow-panel";
import { codeGraph, homeAgent, functionById } from "../source-graph";
import { eventFlowAt } from "../playback/event-flow";
import { TopicInspector } from "./topic-inspector";
import { tourShotAt } from "../camera/tour";
import { RecordedInspector } from "../recorded/inspector";
import type { RecordedAxis as StateAxis } from "../recorded/contract";
import { recorded } from "../recorded/state";

export interface ViewState {
  locale: Locale;
  scenario: Scenario;
  time: number;
  playing: boolean;
  loop: boolean;
  speed: number;
  selected: AgentId | null;
  camera: CameraMode;
  cinema: boolean;
  reduced: boolean;
  labels: boolean;
  glow: number;
  selectedFunction: string | null;
  transportTime: number;
  stars: boolean;
  view: "activity" | "ontology";
  stateAxis: StateAxis;
  relationshipType: string;
}

/** All markup uses authored, local catalog/scenario text. There is no HTML import surface. */
export class VisualizerUI {
  readonly stage: HTMLElement;
  private detailKey = "";
  private locale: Locale = "en";
  private errorKey: MessageKey | null = null;
  private graphicsAvailable = false;
  private readonly agentButtons = new Map<AgentId, HTMLButtonElement>();
  private readonly functions: FunctionInspector;
  private readonly flow: FlowPanel;
  private readonly topics: TopicInspector;
  private readonly ontology: RecordedInspector;

  constructor(readonly root: HTMLElement, scenarios: readonly Scenario[], onFunction: (id: string) => void, onInstance: (id: string) => void) {
    root.innerHTML = `
      <a class="skip-link" href="#playback" data-copy="skip"></a>
      <header class="topbar">
        <div class="brand"><img src="${logoUrl}" alt="FDAI"><span class="brand-divider"></span>
          <div><span class="micro" data-copy="experiment"></span><strong data-copy="title"></strong></div>
        </div>
        <div class="provenance"><span class="demo-badge" data-copy="demo"></span><span data-copy="noExecution"></span></div>
        <nav class="top-actions" data-label="viewControls">
          <button id="language" class="text-button" aria-label="Language">EN / KO</button>
          <button id="fullscreen" class="icon-button" data-title="fullscreen">${icon("fullscreen")}</button>
          <button id="cinema" class="outline-button">${icon("cinema")}<span data-copy="cinema"></span></button>
        </nav>
      </header>
      <main>
        <aside class="intro-panel">
          <p class="eyebrow" data-copy="eyebrow"></p>
          <h1 data-copy="headline"></h1><p class="intro" data-copy="intro"></p>
          <div class="view-switch" role="group" data-label="viewMode">
            <button data-view="activity" aria-pressed="true" data-copy="activityView"></button>
            <button data-view="ontology" aria-pressed="false" data-copy="ontologyView"></button>
          </div>
          <div class="scenario-picker">
            <label for="scenario" class="micro" data-copy="scenario"></label>
            <select id="scenario">${scenarios.map((scenario) => `<option value="${scenario.id}">${localized(scenario.title, "en")}</option>`).join("")}</select>
            <p id="scenario-description"></p>
          </div>
          <section class="roster" aria-labelledby="roster-heading">
            <div class="section-heading"><h2 id="roster-heading" class="micro" data-copy="agents"></h2><span>15</span></div>
            <div class="agent-grid">${agents.map((agent, index) => `
              <button type="button" class="agent-chip" data-agent="${agent.id}" style="--agent-color:${agentColor(agent.id)}" aria-pressed="false">
                <span class="agent-index">${String(index + 1).padStart(2, "0")}</span>
                <span>${agent.id}</span><span class="activity-mark" aria-hidden="true"></span>
              </button>`).join("")}</div>
          </section>
        </aside>
        <section class="visual-field" data-label="field">
          <div id="stage"></div>
          <div id="flow-panel" class="flow-panel"></div>
          <div id="ontology-panel" class="flow-panel ontology-panel"></div>
          <p id="loading" class="scene-message" role="status" data-copy="loading"></p>
          <div class="field-caption"><span class="crosshair">+</span><span data-copy="source"></span><span class="crosshair">+</span></div>
        </section>
        <aside class="inspector activity-inspector">
          <div class="section-heading"><h2 class="micro" data-copy="inspect"></h2><span class="tiny-index">01 / 15</span></div>
          <div id="agent-detail"></div>
          <div class="inspector-actions">
            <button id="focus" class="outline-button">${icon("focus")}<span data-copy="focus"></span></button>
            <button id="clear" class="icon-button" data-title="clear">${icon("cross")}</button>
          </div>
          <div id="source-browser"></div>
          <div id="topic-browser"></div>
          <section class="event-panel" aria-labelledby="event-heading">
            <h2 id="event-heading" class="micro" data-copy="event"></h2>
            <div id="event-detail" aria-live="off"></div>
          </section>
          <p class="semantic-note" data-copy="notCalls"></p>
        </aside>
        <aside id="ontology-inspector" class="inspector ontology-inspector"></aside>
        <div id="controls-dock" class="controls-dock" role="group" data-label="controlsDock">
        <div class="playback-reveal"><div class="playback-clip">
        <footer id="playback" class="playback" tabindex="-1">
          <div class="transport">
            <button id="play" class="play-button" data-title="pause">${icon("pause")}</button>
            <button id="restart" class="icon-button" data-title="restart">${icon("restart")}</button>
            <span class="clock"><span id="time">00:00</span><span class="separator">/</span><span id="duration"></span></span>
          </div>
          <div class="timeline-container">
            <div class="timeline-heading"><span id="current-stage"></span><span id="event-count"></span></div>
            <label class="sr-only" for="timeline" data-copy="timeline"></label>
            <input id="timeline" type="range" min="0" max="72" step="0.05" value="0">
            <div id="timeline-markers" aria-hidden="true"></div>
          </div>
          <div class="playback-options">
            <button id="loop" class="icon-button" aria-pressed="true" data-title="loop">${icon("loop")}</button>
            <label class="sr-only" for="speed" data-copy="speed"></label>
            <select id="speed">${[0.5, 1, 1.5, 2].map((speed) => `<option value="${speed}" ${speed === DEFAULT_PLAYBACK_SPEED ? "selected" : ""}>${speed}x</option>`).join("")}</select>
          </div>
        </footer>
        </div></div>
        <section class="view-toolbar" data-label="appearance">
          <div class="camera-group" role="group" data-label="camera">
            <span class="micro" data-copy="camera"></span>
            <button data-camera="orbit" aria-pressed="false">${icon("orbit")}<span data-copy="orbit"></span></button>
            <button data-camera="follow" aria-pressed="true">${icon("focus")}<span data-copy="follow"></span></button>
            <button data-camera="tour" aria-pressed="false">${icon("cinema")}<span data-copy="tour"></span></button>
            <button data-camera="manual" aria-pressed="false"><span data-copy="manual"></span></button>
          </div>
          <div class="view-options">
            <button id="zoom-out" class="icon-button" data-title="zoomOut">${icon("minus")}</button>
            <button id="zoom-in" class="icon-button" data-title="zoomIn">${icon("plus")}</button>
            <button id="reset" class="icon-button" data-title="reset">${icon("restart")}</button>
            <label class="glow-control"><span data-copy="glow"></span><input id="glow" type="range" min="0" max="1.6" step="0.1" value="0.8"></label>
            <label class="check"><input id="labels" type="checkbox" checked><span data-copy="showLabels"></span></label>
            <label class="check"><input id="stars" type="checkbox" checked><span data-copy="stars"></span></label>
            <label class="check"><input id="motion" type="checkbox"><span data-copy="motion"></span></label>
          </div>
        </section>
        </div>
        <div class="bottom-line"><span data-copy="help"></span><span><span id="fps">--</span> <span data-copy="frameRate"></span></span></div>
      </main>
      <div id="error" class="error-banner" role="alert" hidden><span></span><button id="reload" data-copy="reload"></button></div>
      <div class="cinema-watermark"><span class="demo-badge" data-copy="demo"></span><span data-copy="noExecution"></span></div>
      <button id="exit-cinema" class="outline-button">${icon("cross")}<span data-copy="exitCinema"></span></button>
      <div class="cinema-caption"><span data-copy="cinemaHint"></span><strong id="cinema-event"></strong></div>
    `;
    this.stage = this.element("stage");
    this.functions = new FunctionInspector(this.element("source-browser"), onFunction);
    this.flow = new FlowPanel(this.element("flow-panel"), onFunction);
    this.topics = new TopicInspector(this.element("topic-browser"), onFunction);
    this.ontology = new RecordedInspector(this.element("ontology-panel"), this.element("ontology-inspector"), onInstance);
    root.querySelectorAll<HTMLButtonElement>("[data-agent]").forEach((button) => {
      this.agentButtons.set(button.dataset.agent as AgentId, button);
    });
  }

  element<T extends HTMLElement = HTMLElement>(id: string): T {
    const element = this.root.querySelector<T>(`#${id}`);
    if (!element) throw new Error(`Visualizer element is missing: ${id}`);
    return element;
  }

  translate(locale: Locale, scenarios: readonly Scenario[]) {
    this.locale = locale;
    document.documentElement.lang = locale;
    this.root.querySelectorAll<HTMLElement>("[data-copy]").forEach((element) => {
      element.textContent = t(element.dataset.copy as MessageKey, locale);
    });
    this.root.querySelectorAll<HTMLElement>("[data-title]").forEach((element) => {
      const text = t(element.dataset.title as MessageKey, locale);
      element.setAttribute("aria-label", text);
      element.title = text;
    });
    this.root.querySelectorAll<HTMLElement>("[data-label]").forEach((element) => {
      element.setAttribute("aria-label", t(element.dataset.label as MessageKey, locale));
    });
    this.element("language").setAttribute("aria-label", t("language", locale));
    this.element("language").textContent = locale === "en" ? "EN / KO" : "KO / EN";
    for (const scenario of scenarios) {
      const option = this.root.querySelector<HTMLOptionElement>(`option[value="${scenario.id}"]`)!;
      option.textContent = localized(scenario.title, locale);
    }
    this.detailKey = "";
    if (this.errorKey) this.showError(this.errorKey);
  }

  update(state: ViewState) {
    const { locale, scenario, time, selected } = state;
    const isOntology = state.view === "ontology";
    const duration = scenario.duration;
    this.root.classList.toggle("ontology-mode", isOntology);
    this.root.querySelectorAll<HTMLButtonElement>("[data-view]").forEach((button) => button.setAttribute("aria-pressed", String(button.dataset.view === state.view)));
    this.root.querySelector("h1")!.textContent = t(isOntology ? "ontologyTitle" : "headline", locale);
    this.root.querySelector(".eyebrow")!.textContent = t(isOntology ? "ontologyEyebrow" : "eyebrow", locale);
    this.root.querySelector(".intro-panel > .intro")!.textContent = t(isOntology ? "ontologyIntro" : "intro", locale);
    this.root.querySelectorAll<HTMLElement>('[data-copy="noExecution"]').forEach((element) => {
      element.textContent = t(isOntology ? "ontologyProvenance" : "noExecution", locale);
    });
    this.root.querySelectorAll<HTMLElement>('.provenance .demo-badge, .cinema-watermark .demo-badge').forEach((element) => {
      element.textContent = t(isOntology ? "localDbBadge" : "demo", locale);
    });
    this.root.querySelector('.field-caption [data-copy="source"]')!.textContent = t(isOntology ? "ontologySource" : "source", locale);
    const projection = projectTimeline(scenario, time);
    const latest = projection.latest;
    const flow = eventFlowAt(time, scenario);
    this.flow.update(time, scenario, locale);
    this.element<HTMLSelectElement>("speed").value = String(state.speed);
    const functionOwner = state.selectedFunction ? homeAgent(functionById.get(state.selectedFunction)!) : null;
    this.functions.update(state.selectedFunction ? functionOwner : selected ?? latest?.agent ?? null, state.selectedFunction, locale);
    this.topics.update(selected ?? latest?.agent ?? null, locale);
    this.element("time").textContent = formatTime(time);
    this.element("duration").textContent = formatTime(duration);
    const timeline = this.element<HTMLInputElement>("timeline");
    timeline.max = String(duration);
    timeline.value = String(time);
    timeline.setAttribute("aria-valuetext", `${formatTime(time)} / ${formatTime(duration)}`);
    timeline.style.setProperty("--progress", `${time / duration * 100}%`);
    const play = this.element<HTMLButtonElement>("play");
    const historyUnavailable = isOntology && (!recorded.graph || !recorded.replayEnabled);
    play.disabled = historyUnavailable;
    timeline.disabled = historyUnavailable;
    this.element<HTMLButtonElement>("restart").disabled = historyUnavailable;
    this.element<HTMLButtonElement>("loop").disabled = historyUnavailable;
    this.element<HTMLSelectElement>("speed").disabled = historyUnavailable;
    const playLabel = t(state.playing ? "pause" : "play", locale);
    if (play.getAttribute("aria-label") !== playLabel) {
      play.innerHTML = icon(state.playing ? "pause" : "play");
      play.setAttribute("aria-label", playLabel);
      play.title = playLabel;
    }
    this.element("loop").setAttribute("aria-pressed", String(state.loop));
    this.element<HTMLInputElement>("motion").checked = state.reduced;
    this.element<HTMLInputElement>("labels").checked = state.labels;
    this.element<HTMLInputElement>("stars").checked = state.stars;
    this.root.classList.toggle("hide-labels", !state.labels);
    this.root.classList.toggle("reduced-motion", state.reduced);
    this.root.querySelectorAll<HTMLButtonElement>("[data-camera]").forEach((button) => {
      button.setAttribute("aria-pressed", String(button.dataset.camera === state.camera));
      if (button.dataset.camera === "tour") {
        button.disabled = !this.graphicsAvailable || state.reduced || isOntology;
        button.title = t(state.reduced ? "tourReduced" : "tourHint", locale);
      }
    });
    const shot = this.element("tour-status");
    shot.hidden = state.camera !== "tour";
    shot.textContent = t(`tour_${tourShotAt(time, scenario.duration)}`, locale);
    const activeIds = flow.active;
    for (const agent of agents) {
      const button = this.agentButtons.get(agent.id)!;
      const active = activeIds.has(agent.id);
      button.classList.toggle("is-active", active);
      button.setAttribute("aria-pressed", String(agent.id === selected));
      button.setAttribute("aria-label", `${agent.id}: ${localized(agent.role, locale)}. ${t(active ? "active" : "quiet", locale)}`);
    }
    if (isOntology) {
      this.ontology.update(state.stateAxis, state.relationshipType, locale);
      this.element("current-stage").textContent = t(recorded.replayEnabled ? "replayDbHistory" : "currentTopology", locale);
      this.element("event-count").textContent = recorded.graph ? `${recorded.graph.resources.length} ${t("snapshotNodes", locale)}` : t("readingDatabase", locale);
      this.element("cinema-event").textContent = t("ontologyTitle", locale).replace("\n", " ");
      this.element("timeline-markers").replaceChildren();
      this.detailKey = "";
      return;
    }
    const detailAgent = selected ?? latest?.agent ?? null;
    this.element<HTMLButtonElement>("focus").disabled = detailAgent === null || !this.graphicsAvailable;
    this.element<HTMLButtonElement>("clear").disabled = selected === null;
    const detailKey = `${scenario.id}:${selected}:${latest?.at}:${locale}`;
    if (detailKey === this.detailKey) return;
    this.detailKey = detailKey;
    this.element("scenario-description").textContent = localized(scenario.description, locale);
    this.element("current-stage").textContent = latest ? t(latest.stage, locale) : t("waiting", locale);
    this.element("event-count").textContent = `${projection.occurred.length} / ${scenario.events.length} ${t("events", locale)}`;
    this.element("cinema-event").textContent = latest ? localized(latest.title, locale) : "";
    this.element("timeline-markers").innerHTML = scenario.events.map((event) =>
      `<span style="left:${event.at / scenario.duration * 100}%"></span>`).join("");
    const agent = detailAgent ? agentById.get(detailAgent) : null;
    this.element("agent-detail").innerHTML = agent
      ? `<div class="agent-symbol" style="--agent-color:${agentColor(agent.id)}">${icon("focus")}</div>
         <h2 class="agent-name">${agent.id}</h2><p class="agent-role">${localized(agent.role, locale)}</p>
         <span class="family-tag" style="--agent-color:${agentColor(agent.id)}">${t(agent.family, locale)}</span>
         <h3 class="micro capabilities-heading">${t("capabilities", locale)}</h3>
         <ul class="capabilities">${agent.capabilities.map((capability, index) =>
           `<li><span>0${index + 1}</span>${localized(capability, locale)}</li>`).join("")}</ul>`
      : `<h2 class="empty-title">${t("selectAgent", locale)}</h2><p class="intro">${t("selectHint", locale)}</p>`;
    this.root.querySelector(".tiny-index")!.textContent = `${String(agents.findIndex((item) => item.id === detailAgent) + 1).padStart(2, "0")} / 15`;
    this.element("event-detail").innerHTML = latest
      ? `<div class="event-route"><span>${formatTime(latest.at)}</span><span>${latest.agent}</span></div>
         <h3>${localized(latest.title, locale)}</h3><p>${localized(latest.detail, locale)}</p>
         <span class="event-kind">${t(latest.from ? "illustration" : "local", locale)}</span>`
      : `<p>${t("waiting", locale)}</p>`;
    this.element("source-browser").dataset.digest = codeGraph.input_digest;
  }

  setCinema(enabled: boolean) {
    this.root.classList.toggle("cinema", enabled);
    this.element(enabled ? "exit-cinema" : "cinema").focus();
  }

  ready() {
    this.element("loading").hidden = true;
  }

  setGraphicsAvailable(available: boolean) {
    this.graphicsAvailable = available;
    this.root.querySelectorAll<HTMLButtonElement | HTMLInputElement>(
      "[data-camera], #zoom-in, #zoom-out, #reset, #glow, #labels, #stars",
    ).forEach((control) => { control.disabled = !available; });
    this.element<HTMLButtonElement>("focus").disabled = !available;
  }

  showError(key: MessageKey) {
    this.errorKey = key;
    this.ready();
    const banner = this.element("error");
    banner.hidden = false;
    banner.querySelector("span")!.textContent = t(key, this.locale);
    this.element("reload").hidden = key === "fullscreenError";
  }
}
