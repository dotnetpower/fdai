/** Keep the native menu button's expanded state aligned with Starlight's host. */
export function synchronizeMobileNavigation(root = document) {
  const host = root.querySelector("starlight-menu-button");
  const button = host?.querySelector("button[aria-controls]");
  if (!host || !button) return;

  const synchronize = () => button.setAttribute("aria-expanded", String(host.getAttribute("aria-expanded") === "true"));
  synchronize();
  new MutationObserver(synchronize).observe(host, {
    attributes: true,
    attributeFilter: ["aria-expanded"],
  });
}
