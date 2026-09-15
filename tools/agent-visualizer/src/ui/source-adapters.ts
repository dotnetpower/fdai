import { functionById, sourceServices } from "../source-graph";

/** Keyboard access to API source entries, including markers currently outside the camera view. */
export function mountSourceAdapters(root: HTMLElement, onFunction: (id: string) => void) {
  root.innerHTML = `<details class="adapter-browser">
    <summary data-copy="sourceAdapters"></summary>
    <p data-copy="serviceTrafficNote"></p>
    <div class="adapter-entries"></div>
  </details>`;
  const entries = root.querySelector(".adapter-entries")!;
  for (const service of sourceServices) {
    for (const port of service.ports) {
      const definition = functionById.get(port.function_id);
      if (!definition) throw new Error(`Adapter source entry is missing: ${port.function_id}`);
      const button = document.createElement("button");
      button.type = "button";
      button.dataset.serviceEntry = port.id;
      button.textContent = port.label;
      button.title = `${definition.id}\n${definition.file}:${definition.line}`;
      button.addEventListener("click", () => onFunction(port.function_id));
      entries.append(button);
    }
  }
}
