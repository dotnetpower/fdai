import "./styles.css";
import "./source-view.css";
import "./ontology/styles.css";
import "./recorded/styles.css";
import "./recorded/full-map.css";
import "./ui/controls-dock.css";
import { scenarios } from "../scenarios";
import { advancePlayback, DEFAULT_PLAYBACK_SPEED, projectTimeline } from "./playback/timeline";
import { VisualizerUI, type ViewState } from "./ui/shell";
import { NeuralScene } from "./scene/neural-scene";
import { t } from "./ui/i18n";
import type { AgentId, CameraMode } from "./model";
import { functionById, homeAgent } from "./source-graph";
import { recorded } from "./recorded/state";
import { relationshipSubset } from "./recorded/layout";
import { DEFAULT_ACTIVITY_CAMERA } from "./camera/director";
import { observeControlsDock } from "./ui/controls-dock";

const root = document.querySelector<HTMLElement>("#app");
if (!root) throw new Error("The visualizer root is missing.");
const motionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
const ui = new VisualizerUI(root, scenarios, selectFunction, selectInstance);
const stopDockObserver = observeControlsDock(root);
const state: ViewState = {
  locale: "en", scenario: scenarios[0]!, time: 0, playing: !motionPreference.matches,
  loop: true, speed: DEFAULT_PLAYBACK_SPEED, selected: null, camera: DEFAULT_ACTIVITY_CAMERA, cinema: false,
  reduced: motionPreference.matches, labels: true, glow: 0.8, selectedFunction: null, transportTime: 0, stars: true,
  view: "activity", stateAxis: "operational", relationshipType: "all",
};
let scene: NeuralScene | null = null;
let graphicsReady = false;
let previousFrame = performance.now();
let lastUi = 0;
let lastFps = previousFrame;
let frames = 0;
let frame = 0;
const lifetime = new AbortController();
recorded.onChange = () => {
  if (recorded.graph && state.relationshipType !== "all" && !recorded.graph.links.some((link) => link.type === state.relationshipType)) state.relationshipType = "all";
  ui.update(state);
};

function selectAgent(id: AgentId) {
  state.selected = state.selected === id ? null : id;
  state.selectedFunction = null;
  if (scene) {
    if (state.camera === "tour") {
      state.camera = "follow";
      scene.director.mode = "follow";
    }
    scene.director.focus = state.selected;
    scene.director.focusPoint = null;
  }
  ui.update(state);
}

function selectFunction(id: string) {
  const fn = functionById.get(id);
  if (!fn) throw new Error("Unknown Python source function.");
  state.selectedFunction = id;
  state.view = "activity";
  state.selected = homeAgent(fn);
  state.camera = "follow";
  scene?.focusFunction(id);
  ui.update(state);
}

function selectInstance(id: string) {
  const node = recorded.graph?.resources.find((resource) => resource.id === id);
  if (!recorded.graph || !node) throw new Error("Unknown recorded ontology instance.");
  if (recorded.objectType !== "all" && recorded.objectType !== node.objectType) recorded.objectType = "all";
  if ((recorded.lens === "catalog" && node.nodeKind === "instance")
    || (recorded.lens === "instances" && node.nodeKind !== "instance" && node.nodeKind !== "object_type")) recorded.lens = "all";
  if (!relationshipSubset(recorded.graph, state.relationshipType, recorded.lens, recorded.objectType).resources.some((resource) => resource.id === id)) state.relationshipType = "all";
  recorded.selectedId = id;
  state.view = "ontology";
  state.selected = null;
  state.camera = "follow";
  scene?.focusInstance(id);
  ui.update(state);
}

function duration() {
  return state.scenario.duration;
}

ui.translate(state.locale, scenarios);
ui.update(state);
try {
  scene = new NeuralScene(ui.stage, state.scenario, selectAgent,
    () => { state.camera = "manual"; ui.update(state); },
    () => {
      graphicsReady = false;
      state.playing = false;
      ui.setGraphicsAvailable(false);
      ui.showError("contextLost");
      ui.update(state);
    }, selectFunction, () => {
      const panel = ui.element<HTMLDetailsElement>("broadcast-panel");
      panel.open = true;
      panel.focus();
    }, selectInstance);
  graphicsReady = true;
  ui.setGraphicsAvailable(true);
  ui.ready();
} catch (error) {
  console.error("Neural View could not initialize WebGL.", error);
  state.playing = false;
  ui.setGraphicsAvailable(false);
  ui.showError("webglError");
}

function listen(element: EventTarget, name: string, handler: EventListener) {
  element.addEventListener(name, handler, { signal: lifetime.signal });
}
function click(id: string, handler: () => void) {
  listen(ui.element(id), "click", () => { handler(); ui.update(state); });
}
function setCamera(mode: CameraMode) {
  state.camera = mode;
  if (scene) {
    scene.director.mode = mode;
    scene.director.focus = null;
    scene.director.focusPoint = null;
  }
}
function togglePlayback() {
  if (state.time >= duration()) { state.time = 0; state.transportTime = 0; }
  state.playing = !state.playing;
}
function setCinema(enabled: boolean) {
  state.cinema = enabled;
  ui.setCinema(enabled);
}

root.querySelectorAll<HTMLButtonElement>("[data-agent]").forEach((button) => {
  listen(button, "click", () => selectAgent(button.dataset.agent as AgentId));
});
root.querySelectorAll<HTMLButtonElement>("[data-camera]").forEach((button) => {
  listen(button, "click", () => { setCamera(button.dataset.camera as CameraMode); ui.update(state); });
});
root.querySelectorAll<HTMLButtonElement>("[data-view]").forEach((button) => {
  listen(button, "click", () => {
    state.view = button.dataset.view === "ontology" ? "ontology" : "activity";
    if (state.view === "ontology") recorded.ensureLoaded();
    state.time = Math.min(state.time, duration());
    scene?.director.reset();
    setCamera(state.view === "activity" ? DEFAULT_ACTIVITY_CAMERA : "orbit");
    ui.update(state);
  });
});
listen(ui.element("relationship-filter"), "change", () => {
  state.relationshipType = ui.element<HTMLSelectElement>("relationship-filter").value;
  ui.update(state);
});
listen(ui.element("map-history-replay"), "change", () => {
  if (recorded.replayEnabled) { state.time = 0; state.playing = !state.reduced; }
  else state.playing = false;
  ui.update(state);
});
click("play", togglePlayback);
click("restart", () => { state.time = 0; state.transportTime = 0; });
click("loop", () => { state.loop = !state.loop; });
click("reset", () => { state.selected = null; state.selectedFunction = null; scene?.director.reset(); setCamera("orbit"); });
click("focus", () => {
  const id = state.selected ?? projectTimeline(state.scenario, state.time).latest?.agent;
  if (id && scene) {
    state.selected = id;
    state.camera = "follow";
    scene.director.mode = "follow";
    scene.director.focus = id;
  }
});
click("clear", () => {
  state.selected = null;
  state.selectedFunction = null;
  if (scene) { scene.director.focus = null; scene.director.focusPoint = null; }
});
click("zoom-in", () => { scene?.director.zoom(0.84); state.camera = "manual"; });
click("zoom-out", () => { scene?.director.zoom(1.18); state.camera = "manual"; });
click("cinema", () => setCinema(true));
click("exit-cinema", () => setCinema(false));
click("language", () => {
  state.locale = state.locale === "en" ? "ko" : "en";
  ui.translate(state.locale, scenarios);
});
click("reload", () => window.location.reload());

listen(ui.element("fullscreen"), "click", () => {
  const request = document.fullscreenElement ? document.exitFullscreen() : root.requestFullscreen?.();
  if (!request) { ui.showError("fullscreenError"); return; }
  void request.catch(() => ui.showError("fullscreenError"));
});
listen(document, "fullscreenchange", () => {
  const label = t(document.fullscreenElement ? "exitFullscreen" : "fullscreen", state.locale);
  ui.element("fullscreen").setAttribute("aria-label", label);
  ui.element("fullscreen").title = label;
});
listen(ui.element("scenario"), "change", () => {
  const id = ui.element<HTMLSelectElement>("scenario").value;
  const scenario = scenarios.find((candidate) => candidate.id === id);
  if (!scenario) throw new Error("Unknown visualizer scenario.");
  state.scenario = scenario;
  state.time = 0;
  state.transportTime = 0;
  state.selected = null;
  state.selectedFunction = null;
  if (scene) { scene.director.focus = null; scene.director.focusPoint = null; }
  ui.update(state);
});
listen(ui.element("timeline"), "input", () => {
  state.time = Number(ui.element<HTMLInputElement>("timeline").value);
  state.transportTime = state.time / DEFAULT_PLAYBACK_SPEED;
  ui.update(state);
});
listen(ui.element("speed"), "change", () => {
  state.speed = Number(ui.element<HTMLSelectElement>("speed").value);
});
listen(ui.element("glow"), "input", () => { state.glow = Number(ui.element<HTMLInputElement>("glow").value); });
listen(ui.element("labels"), "change", () => {
  state.labels = ui.element<HTMLInputElement>("labels").checked;
  ui.update(state);
});
listen(ui.element("stars"), "change", () => {
  state.stars = ui.element<HTMLInputElement>("stars").checked;
  ui.update(state);
});
listen(ui.element("motion"), "change", () => {
  state.reduced = ui.element<HTMLInputElement>("motion").checked;
  if (state.reduced) {
    state.playing = false;
    if (state.camera === "tour") setCamera("manual");
  }
  ui.update(state);
});
listen(motionPreference, "change", () => {
  state.reduced = motionPreference.matches;
  if (state.reduced) {
    state.playing = false;
    if (state.camera === "tour") setCamera("manual");
  }
  ui.update(state);
});
listen(document, "keydown", (raw) => {
  const event = raw as KeyboardEvent;
  if (event.key === "Escape" && state.cinema) { setCinema(false); return; }
  if (event.ctrlKey || event.metaKey || event.altKey || event.repeat) return;
  const target = event.target;
  if (target instanceof HTMLElement && target.closest("input, select, button, a, textarea, [contenteditable]")) return;
  if (event.code === "Space") { event.preventDefault(); togglePlayback(); ui.update(state); }
  if (event.key.toLowerCase() === "c") { event.preventDefault(); setCinema(!state.cinema); }
});
listen(document, "visibilitychange", () => {
  previousFrame = performance.now();
  if (document.hidden) cancelAnimationFrame(frame);
  else {
    cancelAnimationFrame(frame);
    previousFrame = performance.now();
    frame = requestAnimationFrame(animate);
  }
});

function animate(now: number) {
  const delta = Math.max(0, (now - previousFrame) / 1000);
  previousFrame = now;
  if (state.playing) {
    const next = advancePlayback(state.time, state.transportTime, delta, state.speed, duration(), state.loop);
    state.time = next.time;
    state.transportTime = next.transportTime;
    if (!state.loop && state.time === duration()) state.playing = false;
  }
  if (state.view === "ontology") recorded.setReplay(state.time, duration());
  if (graphicsReady) scene?.render(state.scenario, state.time, state.transportTime, delta, state.reduced, state.glow, state.selected, state.selectedFunction, state.stars,
    state.view, state.stateAxis, state.relationshipType);
  if (now - lastUi > 100) { ui.update(state); lastUi = now; }
  frames++;
  if (now - lastFps >= 1000) {
    ui.element("fps").textContent = graphicsReady ? String(Math.round(frames * 1000 / (now - lastFps))) : "--";
    frames = 0;
    lastFps = now;
  }
  frame = requestAnimationFrame(animate);
}
frame = requestAnimationFrame(animate);

function dispose() {
  cancelAnimationFrame(frame);
  lifetime.abort();
  stopDockObserver();
  recorded.dispose();
  scene?.dispose();
}
window.addEventListener("pagehide", (event) => {
  if (event.persisted) cancelAnimationFrame(frame);
  else dispose();
});
window.addEventListener("pageshow", (event) => {
  if (event.persisted) {
    previousFrame = performance.now();
    cancelAnimationFrame(frame);
    frame = requestAnimationFrame(animate);
  }
});
if (import.meta.hot) import.meta.hot.dispose(dispose);
