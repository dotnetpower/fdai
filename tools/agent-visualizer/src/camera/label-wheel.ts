/** Labels are canvas siblings. Relay only their wheel input, keeping native camera math and label clicks. */
export function installLabelWheelZoom(container: HTMLElement, canvas: HTMLCanvasElement): () => void {
  const listener = (event: WheelEvent) => {
    if (!(event.target instanceof Element) || !event.target.closest(".node-labels")) return;
    const forwarded = new WheelEvent("wheel", {
      cancelable: true,
      deltaX: event.deltaX, deltaY: event.deltaY, deltaZ: event.deltaZ, deltaMode: event.deltaMode,
      clientX: event.clientX, clientY: event.clientY, screenX: event.screenX, screenY: event.screenY,
      ctrlKey: event.ctrlKey, shiftKey: event.shiftKey, altKey: event.altKey, metaKey: event.metaKey,
    });
    if (!canvas.dispatchEvent(forwarded)) event.preventDefault();
  };
  container.addEventListener("wheel", listener, { passive: false });
  return () => container.removeEventListener("wheel", listener);
}
