import * as THREE from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { agents, agentColor } from "../agents";
import { CameraDirector } from "../camera/director";
import { activityEnergy, projectTimeline } from "../playback/timeline";
import type { AgentId, Scenario } from "../model";
import { createPointMaterial, createPointOcclusionMaterial, makeNeuralGeometry, BUS_POSITION } from "./geometry";
import { EventField, ARG_ENTRY, AZURE_SERVICE_POSITION } from "./event-field";
import { EventLaunchLabels } from "./event-launch-labels";
import { ExternalServices } from "./external-services";
import { FunctionSelection } from "./function-selection";
import { eventFlowAt } from "../playback/event-flow";
import { sampleTour } from "../camera/tour";
import { codeGraph } from "../source-graph";
import { ScreenLabels } from "./screen-labels";
import { registerFunctionLabels } from "./function-labels";
import { StarField, STAR_COUNT } from "./star-field";
import { installLabelWheelZoom } from "../camera/label-wheel";
import { RecordedRelationScene } from "../recorded/scene";
import { recorded } from "../recorded/state";
import type { RecordedAxis as StateAxis } from "../recorded/contract";
import { layoutRelationships } from "../recorded/layout";
import { SceneResources, disposeSceneObjects } from "./resources";
import { setAttribute } from "../ui/dom-state";

interface SceneOptions {
  readonly container: HTMLElement;
  readonly scenario: Scenario;
  readonly onSelect: (id: AgentId) => void;
  readonly onManual: () => void;
  readonly onContextLost: () => void;
  readonly onFunction: (id: string) => void;
  readonly onBus: () => void;
  readonly onInstance: (id: string) => void;
}

const DEFAULT_TOUR_FUNCTION = codeGraph.functions.find(
  (fn) => fn.direct_owners.includes("Huginn") && fn.name === "ingest",
)?.id ?? ARG_ENTRY;

/** A disposable WebGL view. The application owns playback; the scene never changes domain state. */
export class NeuralScene {
  readonly director: CameraDirector;
  readonly nodeCount: number;
  private readonly renderer: THREE.WebGLRenderer;
  private readonly scene = new THREE.Scene();
  private readonly camera = new THREE.PerspectiveCamera(48, 1, 0.1, 500);
  private readonly composer: EffectComposer;
  private readonly bloom: UnrealBloomPass;
  private readonly resizeObserver: ResizeObserver;
  private readonly neural = makeNeuralGeometry();
  private readonly pointGeometry = new THREE.BufferGeometry();
  private readonly pointMaterial: THREE.ShaderMaterial;
  private readonly events: EventField;
  private readonly launchLabels: EventLaunchLabels;
  private readonly external: ExternalServices;
  private readonly functionSelection: FunctionSelection;
  private readonly nodePoints: THREE.Points;
  private readonly labels = new Map<AgentId, HTMLButtonElement>();
  private readonly rings = new Map<AgentId, THREE.Mesh<THREE.RingGeometry, THREE.MeshBasicMaterial>>();
  private readonly labelLayer = document.createElement("div");
  private readonly screenLabels: ScreenLabels;
  private readonly stars: StarField;
  private readonly stopLabelWheel: () => void;
  private readonly activity = new THREE.Group();
  private readonly ontology: RecordedRelationScene;
  private view: "activity" | "ontology" = "activity";
  private disposed = false;
  private width = 1;
  private height = 1;
  private readonly listeners = new AbortController();
  private readonly container: HTMLElement;
  private activityKey = "";
  private previousScenario: Scenario | null = null;
  private previousFocus: Element | null = null;
  private readonly renderedCamera = new THREE.Matrix4();
  private readonly renderedProjection = new THREE.Matrix4();

  /** Construction either returns a complete view or releases all acquired resources before throwing. */
  static create(options: SceneOptions): NeuralScene {
    const resources = new SceneResources();
    try {
      return new NeuralScene(options, resources);
    } catch (error) {
      try { resources.dispose(); } catch (cleanupError) {
        throw new AggregateError([error, cleanupError], "Scene initialization and cleanup failed.");
      }
      throw error;
    }
  }

  private constructor(options: SceneOptions, private readonly resources: SceneResources) {
    const { container, scenario, onSelect, onManual, onContextLost, onFunction, onBus, onInstance } = options;
    this.container = container;
    resources.add(() => { this.disposed = true; });
    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    resources.add(() => {
      this.renderer.dispose();
      this.renderer.forceContextLoss();
      this.renderer.domElement.remove();
    });
    resources.add(() => disposeSceneObjects(this.scene));
    resources.add(() => this.listeners.abort());
    resources.add(() => this.labelLayer.remove());
    const ratio = Math.min(window.devicePixelRatio, 1.75);
    this.renderer.setPixelRatio(ratio);
    this.renderer.setClearColor(0x070d13, 0);
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.2;
    this.renderer.domElement.setAttribute("aria-hidden", "true");
    this.stars = new StarField(ratio);
    this.scene.add(this.stars.object);
    this.scene.add(this.activity);
    this.ontology = new RecordedRelationScene(container, onInstance, ratio);
    resources.add(() => {
      this.scene.remove(this.ontology.group);
      this.ontology.dispose();
    });
    this.ontology.group.visible = false;
    this.ontology.labelLayer.hidden = true;
    this.scene.add(this.ontology.group);
    container.dataset.decorativeStarCount = String(STAR_COUNT);
    this.renderer.domElement.addEventListener("webglcontextlost", (event) => {
      event.preventDefault();
      onContextLost();
    }, { signal: this.listeners.signal });
    container.append(this.renderer.domElement);
    this.director = new CameraDirector(this.camera, this.renderer.domElement, this.neural.anchors, onManual);
    resources.add(() => this.director.controls.dispose());
    this.stopLabelWheel = installLabelWheelZoom(container, this.renderer.domElement);
    resources.add(this.stopLabelWheel);

    this.pointMaterial = createPointMaterial(ratio);
    this.nodeCount = this.neural.points.length;
    container.dataset.functionCount = String(this.neural.functionPositions.size);
    this.pointGeometry.setAttribute("position", new THREE.Float32BufferAttribute(
      this.neural.points.flatMap((point) => point.position.toArray()), 3,
    ));
    this.pointGeometry.setAttribute("color", new THREE.Float32BufferAttribute(
      this.neural.points.flatMap((point) => point.color.toArray()), 3,
    ));
    this.pointGeometry.setAttribute("size", new THREE.Float32BufferAttribute(this.neural.points.map((point) => point.size), 1));
    this.pointGeometry.setAttribute("energy", new THREE.Float32BufferAttribute(new Float32Array(this.nodeCount), 1));
    this.nodePoints = new THREE.Points(this.pointGeometry, this.pointMaterial);
    const nodeOccluder = new THREE.Points(this.pointGeometry, createPointOcclusionMaterial(ratio));
    nodeOccluder.name = "node-star-occlusion";
    nodeOccluder.renderOrder = 90;
    this.activity.add(this.nodePoints, nodeOccluder);
    this.activity.add(new THREE.LineSegments(this.neural.lines,
      new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.42, blending: THREE.AdditiveBlending })));

    this.labelLayer.className = "node-labels activity-labels";
    container.append(this.labelLayer);
    this.screenLabels = new ScreenLabels(this.labelLayer);
    for (const agent of agents) {
      const label = document.createElement("button");
      label.className = "node-label";
      label.textContent = agent.id;
      label.type = "button";
      label.style.setProperty("--agent-color", agentColor(agent.id));
      label.addEventListener("click", () => onSelect(agent.id), { signal: this.listeners.signal });
      this.labelLayer.append(label);
      this.labels.set(agent.id, label);
      this.screenLabels.register(agent.id, label, () => this.neural.anchors.get(agent.id)!);
      const ring = new THREE.Mesh(new THREE.RingGeometry(0.9, 0.94, 48),
        new THREE.MeshBasicMaterial({ color: agentColor(agent.id), side: THREE.DoubleSide,
          transparent: true, opacity: 0.2, depthWrite: false, blending: THREE.AdditiveBlending }));
      ring.position.copy(this.neural.anchors.get(agent.id)!);
      this.rings.set(agent.id, ring);
      this.activity.add(ring);
    }
    for (const [text, position, handler] of [
      ["EVENT BUS", BUS_POSITION, onBus],
      ["AZURE RESOURCE GRAPH", AZURE_SERVICE_POSITION, () => onFunction(ARG_ENTRY)],
    ] as const) {
      const label = document.createElement("button");
      label.type = "button";
      label.className = "node-label service-label";
      label.textContent = text;
      label.addEventListener("click", handler, { signal: this.listeners.signal });
      this.labelLayer.append(label);
      this.screenLabels.register(text, label, () => position);
    }
    const raycaster = new THREE.Raycaster();
    raycaster.params.Points.threshold = 0.4;
    const pointer = new THREE.Vector2();
    let pressed = { x: 0, y: 0 };
    this.renderer.domElement.addEventListener("pointerdown", (event) => { pressed = { x: event.clientX, y: event.clientY }; }, { signal: this.listeners.signal });
    this.renderer.domElement.addEventListener("pointerup", (event) => {
      if (Math.hypot(event.clientX - pressed.x, event.clientY - pressed.y) > 5) return;
      const rect = this.renderer.domElement.getBoundingClientRect();
      pointer.set((event.clientX - rect.left) / rect.width * 2 - 1, -(event.clientY - rect.top) / rect.height * 2 + 1);
      raycaster.setFromCamera(pointer, this.camera);
      if (this.view === "ontology") { this.ontology.pick(raycaster); return; }
      const hit = raycaster.intersectObject(this.nodePoints)[0];
      const point = hit?.index === undefined ? null : this.neural.points[hit.index];
      if (point?.functionId) onFunction(point.functionId);
    }, { signal: this.listeners.signal });
    this.addAmbientField();
    this.events = new EventField(this.neural.anchors, this.neural.functionPositions, ratio);
    resources.add(() => disposeSceneObjects(this.events.group));
    this.external = new ExternalServices(this.neural.functionPositions, ratio);
    resources.add(() => disposeSceneObjects(this.external.group));
    for (const port of this.external.ports) {
      const label = document.createElement("button");
      label.type = "button";
      label.className = "node-label service-label";
      label.dataset.servicePort = port.id;
      label.textContent = port.label;
      label.title = port.functionId;
      label.addEventListener("click", () => onFunction(port.functionId), { signal: this.listeners.signal });
      this.labelLayer.append(label);
      this.screenLabels.register(port.label, label, () => port.position);
    }
    this.launchLabels = new EventLaunchLabels(this.labelLayer, this.screenLabels, this.neural.anchors);
    this.functionSelection = new FunctionSelection(this.neural.functionPositions, this.labelLayer);
    resources.add(() => this.functionSelection.dispose());
    this.screenLabels.register("function", this.functionSelection.label, () => this.functionSelection.anchor);
    registerFunctionLabels(this.labelLayer, this.screenLabels, this.neural.functionPositions, onFunction, this.listeners.signal);
    this.activity.add(this.events.group, this.external.group, this.functionSelection.object);
    this.composer = new EffectComposer(this.renderer);
    resources.add(() => {
      for (const pass of this.composer.passes) pass.dispose();
      this.composer.dispose();
    });
    this.composer.addPass(new RenderPass(this.scene, this.camera));
    this.bloom = new UnrealBloomPass(new THREE.Vector2(1, 1), 0.8, 0.7, 0.5);
    this.composer.addPass(this.bloom);
    this.composer.addPass(new OutputPass());
    this.resizeObserver = new ResizeObserver(() => this.resize());
    resources.add(() => this.resizeObserver.disconnect());
    this.resizeObserver.observe(container);
    this.resize();
  }

  private addAmbientField() {
    const orbitPoints: THREE.Vector3[] = [];
    for (let i = 0; i <= 192; i++) {
      const angle = i / 192 * Math.PI * 2;
      orbitPoints.push(new THREE.Vector3(Math.cos(angle) * 32, -19, Math.sin(angle) * 20));
    }
    this.activity.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(orbitPoints),
      new THREE.LineDashedMaterial({ color: "#4a747c", transparent: true, opacity: 0.22, dashSize: 0.5, gapSize: 0.5 })).computeLineDistances());
  }

  private resize() {
    if (this.disposed) return;
    this.width = Math.max(1, this.container.clientWidth);
    this.height = Math.max(1, this.container.clientHeight);
    this.camera.aspect = this.width / this.height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(this.width, this.height);
    this.composer.setSize(this.width, this.height);
  }

  focusFunction(id: string) {
    this.director.focusPoint = this.neural.functionPositions.get(id) ?? null;
    this.director.mode = "follow";
  }

  focusInstance(id: string) {
    if (!this.ontology.positions.has(id) && recorded.graph) this.ontology.positions = layoutRelationships(recorded.graph);
    const point = this.ontology.positions.get(id);
    if (!point) throw new Error(`Unknown ontology instance: ${id}`);
    this.director.focusPoint = new THREE.Vector3(...point);
    this.director.mode = "follow";
  }

  render(scenario: Scenario, time: number, transportTime: number, delta: number, reduced: boolean, glow: number, selected: AgentId | null, selectedFunction: string | null, stars: boolean,
    view: "activity" | "ontology", stateAxis: StateAxis, relationshipType: string) {
    if (this.disposed) return false;
    this.view = view;
    this.activity.visible = view === "activity";
    if (this.labelLayer.hidden !== (view !== "activity")) this.labelLayer.hidden = view !== "activity";
    this.ontology.group.visible = view === "ontology";
    if (this.ontology.labelLayer.hidden !== (view !== "ontology")) this.ontology.labelLayer.hidden = view !== "ontology";
    this.stars.update(transportTime, stars, reduced);
    setAttribute(this.container, "data-stars-visible", String(this.stars.object.visible));
    setAttribute(this.container, "data-star-time", String(this.stars.object.material.uniforms.time!.value));
    setAttribute(this.container, "data-view", view);
    setAttribute(this.container, "data-transport-time", transportTime.toFixed(4));
    if (view === "ontology") {
      this.activityKey = "";
      const tour = sampleTour(0, 72, this.camera.aspect, {
        bus: [0, 0, 0], source: [0, 0, 0], azure: [0, 0, 0],
      });
      this.director.update(transportTime, delta, null, reduced, tour);
      this.container.dataset.cameraDistance = this.director.controls.getDistance().toFixed(4);
      this.container.dataset.cameraMode = this.director.mode;
      this.container.dataset.cameraShot = this.director.mode === "tour" ? tour.shot : "";
      this.camera.updateMatrixWorld();
      this.ontology.render(recorded.graph, relationshipType, recorded.selectedId, stateAxis, recorded.changes, this.camera, this.width, this.height, delta, reduced);
      this.container.dataset.recordedResources = String(recorded.graph?.resources.length ?? 0);
      this.container.dataset.recordedLinks = String(recorded.graph?.links.length ?? 0);
      this.bloom.strength = glow * 0.65;
      this.composer.render();
      return true;
    }
    const projection = projectTimeline(scenario, time);
    const tourFunction = selectedFunction ?? DEFAULT_TOUR_FUNCTION;
    const source = this.neural.functionPositions.get(tourFunction)!;
    const tour = sampleTour(time, scenario.duration, this.camera.aspect, {
      bus: [BUS_POSITION.x, BUS_POSITION.y, BUS_POSITION.z],
      source: [source.x, source.y, source.z],
      azure: [AZURE_SERVICE_POSITION.x, AZURE_SERVICE_POSITION.y, AZURE_SERVICE_POSITION.z],
    });
    this.director.update(time, delta, projection.latest?.agent ?? null, reduced, tour);
    setAttribute(this.container, "data-camera-distance", this.director.controls.getDistance().toFixed(4));
    this.camera.updateMatrixWorld();
    setAttribute(this.container, "data-camera-mode", this.director.mode);
    setAttribute(this.container, "data-camera-shot", this.director.mode === "tour" ? tour.shot : "");
    const key = JSON.stringify([time, transportTime, reduced, glow, selected, selectedFunction, stars,
      this.director.mode, this.width, this.height]);
    const focus = document.activeElement;
    const sameCamera = this.renderedCamera.equals(this.camera.matrixWorld)
      && this.renderedProjection.equals(this.camera.projectionMatrix);
    if (sameCamera && !this.screenLabels.pendingAnimation && this.activityKey === key
      && this.previousScenario === scenario && this.previousFocus === focus) return false;
    const highlightedFunction = selectedFunction ?? (this.director.mode === "tour" && tour.shot === "function" ? tourFunction : null);
    const energies = new Map(agents.map((agent) => [agent.id, activityEnergy(scenario.events, time, agent.id)]));
    const flow = eventFlowAt(time, scenario);
    const workEnergy = new Map(flow.independent.map((work) => [work.functionId, work.energy]));
    for (const work of flow.independent) energies.set(work.agent, Math.max(energies.get(work.agent)!, work.energy * 0.8));
    const attribute = this.pointGeometry.getAttribute("energy");
    this.neural.points.forEach((point, index) => {
      const base = point.functionId ? (workEnergy.get(point.functionId) ?? 0.07) : point.owner ? energies.get(point.owner)! : 0.1;
      const ripple = reduced ? 1 : 0.8 + 0.2 * Math.sin(time * 2 - point.position.length() * 0.45);
      attribute.setX(index, point.functionId === highlightedFunction && highlightedFunction ? 1.6 : base * ripple + (selected && selected === point.owner ? 0.25 : 0));
    });
    attribute.needsUpdate = true;
    this.events.update(time, transportTime, scenario, this.camera, reduced);
    const serviceTraffic = this.external.update(transportTime, reduced);
    this.container.dataset.serviceParticles = String(serviceTraffic.count);
    this.container.dataset.channelStreamParticles = String(serviceTraffic.channelStreamCount);
    this.functionSelection.update(highlightedFunction);
    const priorities = new Map<string, number>([["function", 300], ["EVENT BUS", 180], ["AZURE RESOURCE GRAPH", 180]]);
    for (const port of this.external.ports) priorities.set(port.label, 180);
    for (const work of flow.independent) priorities.set(`python:${work.functionId}`, -80);
    if (selected) {
      for (const fn of codeGraph.functions) if (fn.direct_owners.includes(selected)) priorities.set(`python:${fn.id}`, -60);
    }
    this.container.dataset.transportTime = transportTime.toFixed(4);
    for (const agent of agents) {
      const energy = energies.get(agent.id)!;
      const ring = this.rings.get(agent.id)!;
      ring.quaternion.copy(this.camera.quaternion);
      ring.scale.setScalar(1 + energy * (reduced ? 0.5 : 0.8));
      ring.material.opacity = 0.18 + energy * 0.6;
      const label = this.labels.get(agent.id)!;
      label.classList.toggle("is-active", energy > 0.2);
      label.classList.toggle("is-selected", selected === agent.id);
      setAttribute(label, "aria-pressed", String(selected === agent.id));
      priorities.set(agent.id, selected === agent.id ? 200 : energy > 0.2 ? 100 : 0);
    }
    this.launchLabels.update(flow, reduced, priorities);
    this.screenLabels.update(this.camera, this.width, this.height, priorities, delta, reduced);
    this.bloom.strength = glow;
    this.composer.render();
    this.activityKey = key;
    this.previousScenario = scenario;
    this.previousFocus = focus;
    this.renderedCamera.copy(this.camera.matrixWorld);
    this.renderedProjection.copy(this.camera.projectionMatrix);
    return true;
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    this.resources.dispose();
    this.labels.clear();
    this.rings.clear();
  }
}
