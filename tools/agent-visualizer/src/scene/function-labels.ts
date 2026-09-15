import type * as THREE from "three";
import { pythonFunctions } from "../source-graph";
import type { ScreenLabels } from "./screen-labels";

/** Exact source annotations stay quiet until camera proximity makes them legible. */
export function registerFunctionLabels(
  layer: HTMLElement,
  labels: ScreenLabels,
  positions: ReadonlyMap<string, THREE.Vector3>,
  onSelect: (id: string) => void,
  signal?: AbortSignal,
) {
  layer.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const button = target.closest<HTMLButtonElement>(".function-node-label[data-function-id]");
    if (button?.dataset.functionId) onSelect(button.dataset.functionId);
  }, { signal });
  for (const fn of pythonFunctions) {
    const label = document.createElement("button");
    label.type = "button";
    label.className = "function-node-label";
    const name = document.createElement("span");
    name.className = "function-annotation-name";
    name.textContent = fn.name;
    const suffix = document.createElement("span");
    suffix.className = "function-annotation-suffix";
    suffix.textContent = "()";
    label.append(name, suffix);
    label.style.opacity = "0";
    label.tabIndex = -1;
    label.hidden = true;
    label.title = `${fn.id}()\n${fn.file}:${fn.line}`;
    label.setAttribute("aria-label", `${fn.id}()`);
    label.dataset.functionId = fn.id;
    layer.append(label);
    labels.register(`python:${fn.id}`, label, () => positions.get(fn.id)!, true);
  }
}
