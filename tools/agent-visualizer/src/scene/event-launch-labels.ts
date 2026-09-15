import type { Vector3 } from "three";
import type { AgentId } from "../model";
import { isAgentId } from "../source-graph";
import { broadcastTopics, type eventFlowAt } from "../playback/event-flow";
import { BUS_LAUNCH_LABEL, eventLaunchAnnotations } from "../playback/event-launch";
import { BUS_POSITION } from "./geometry";
import type { ScreenLabels } from "./screen-labels";

interface LaunchLabel {
  readonly element: HTMLSpanElement;
  readonly leader: SVGLineElement;
  visible: boolean;
  opacity: number | null;
}

/** Non-interactive, bounded callouts share the existing collision layout with node names. */
export class EventLaunchLabels {
  private readonly labels = new Map<string, LaunchLabel>();

  constructor(layer: HTMLElement, layout: ScreenLabels, anchors: ReadonlyMap<AgentId, Vector3>) {
    const definitions = [
      ...broadcastTopics.map((topic) => ({ id: `event-launch:${topic.id}`, origin: topic.publisher, text: topic.id })),
      { id: BUS_LAUNCH_LABEL, origin: "EVENT BUS", text: "" },
    ];
    for (const definition of definitions) {
      const anchor = definition.origin === "EVENT BUS" ? BUS_POSITION
        : isAgentId(definition.origin) ? anchors.get(definition.origin) : undefined;
      if (!anchor) throw new Error(`Event annotation origin is missing: ${definition.origin}`);
      const element = document.createElement("span");
      element.className = "event-launch-label";
      element.dataset.origin = definition.origin;
      element.textContent = definition.text;
      element.hidden = true;
      element.setAttribute("aria-hidden", "true");
      layer.append(element);
      const leader = layout.register(definition.id, element,
        () => this.labels.get(definition.id)?.visible ? anchor : null, false, { nearOrigin: true });
      leader.dataset.launchOrigin = definition.origin;
      this.labels.set(definition.id, { element, leader, visible: false, opacity: null });
    }
  }

  update(flow: ReturnType<typeof eventFlowAt>, reduced: boolean, priorities: Map<string, number>) {
    const active = new Map(eventLaunchAnnotations(flow, reduced).map((annotation) => [annotation.id, annotation]));
    for (const [id, label] of this.labels) {
      const annotation = active.get(id);
      label.visible = Boolean(annotation);
      const opacity = annotation?.opacity ?? 0;
      if (label.opacity !== opacity) {
        label.element.style.opacity = String(opacity);
        label.leader.style.opacity = String(opacity);
        label.opacity = opacity;
      }
      if (annotation && label.element.textContent !== annotation.text) label.element.textContent = annotation.text;
      priorities.set(id, -20);
    }
  }
}
