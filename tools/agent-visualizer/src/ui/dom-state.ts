/** Commit only changed presentation values; repeated frames must not invalidate stable DOM. */
export function setText(element: Node, value: string) {
  if (element.textContent !== value) element.textContent = value;
}

export function setAttribute(element: Element, name: string, value: string) {
  if (element.getAttribute(name) !== value) element.setAttribute(name, value);
}

export function setStyle(element: HTMLElement | SVGElement, name: string, value: string) {
  if (element.style.getPropertyValue(name) !== value) element.style.setProperty(name, value);
}
