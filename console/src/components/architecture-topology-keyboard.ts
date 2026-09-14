import type { JSX } from "preact";
import type { InventoryResource } from "./architecture-map.model";

/** Applies one roving-focus or selection key without changing graph data. */
export function handleArchitectureTopologyKeyDown(
  event: JSX.TargetedKeyboardEvent<SVGGElement>,
  resource: InventoryResource,
  focusOrder: readonly InventoryResource[],
  onSelect: ((resource: InventoryResource) => void) | undefined,
): void {
  if (!onSelect) return;
  if (event.key === "Enter" || event.key === " ") {
    event.preventDefault();
    onSelect(resource);
    return;
  }
  const currentIndex = focusOrder.findIndex((candidate) => candidate.id === resource.id);
  let nextIndex = currentIndex;
  if (event.key === "ArrowRight" || event.key === "ArrowDown") nextIndex += 1;
  else if (event.key === "ArrowLeft" || event.key === "ArrowUp") nextIndex -= 1;
  else if (event.key === "Home") nextIndex = 0;
  else if (event.key === "End") nextIndex = focusOrder.length - 1;
  else return;
  event.preventDefault();
  const next = focusOrder[(nextIndex + focusOrder.length) % focusOrder.length];
  [...(event.currentTarget.ownerSVGElement
    ?.querySelectorAll<SVGGElement>(".architecture-topology-resource") ?? [])]
    .find((element) => element.dataset.resourceId === next?.id)
    ?.focus();
}
