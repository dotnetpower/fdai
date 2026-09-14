(function () {
  "use strict";
  const dialog = document.getElementById("activityRolesDialog");
  const open = document.getElementById("activityRolesOpen");
  const close = document.getElementById("activityRolesClose");
  const organizationFrame = dialog.querySelector("iframe");
  let closing = false;
  function syncOrganizationRoute() {
    if (!organizationFrame) return;
    const current = new URL(location.href);
    const target = new URL("agents-constellation.html", location.href);
    target.searchParams.set("overlay", "1");
    target.searchParams.set("preview", "3");
    for (const key of ["agent", "sampleState"]) {
      const value = key === "agent"
        ? current.searchParams.get("roleAgent") ?? current.searchParams.get("agent")
        : current.searchParams.get(key);
      if (value) target.searchParams.set(key, value);
    }
    const next = target.pathname.split("/").pop() + target.search;
    const frameLocation = organizationFrame.contentWindow?.location;
    if (!frameLocation) return;
    const loaded = new URL(frameLocation.href);
    const loadedRoute = loaded.pathname.split("/").pop() + loaded.search;
    if (loadedRoute !== next) frameLocation.replace(next);
  }
  function redrawOrganization() {
    organizationFrame?.contentWindow?.dispatchEvent(new Event("resize"));
  }
  function showDialog() {
    syncOrganizationRoute();
    dialog.showModal();
    open.setAttribute("aria-expanded", "true");
    window.setTimeout(redrawOrganization, 0);
    window.setTimeout(redrawOrganization, 100);
  }
  function hasRoute() {
    return new URL(location.href).searchParams.get("roles") === "1";
  }
  function sync() {
    if (hasRoute() && !dialog.open) showDialog();
    if (!hasRoute() && dialog.open) {
      dialog.close();
      open.setAttribute("aria-expanded", "false");
      open.focus();
    }
    closing = false;
    window.fdaiPublishMockRoute?.();
  }
  function replaceClosedRoute() {
    const url = new URL(location.href);
    url.searchParams.delete("roles");
    url.searchParams.delete("roleAgent");
    history.replaceState(null, "", url);
    dialog.close();
    open.setAttribute("aria-expanded", "false");
    open.focus();
    closing = false;
    window.fdaiPublishMockRoute?.();
  }
  function closeRoute() {
    if (closing) return;
    closing = true;
    if (history.state?.fdaiAgentRolesOverlay === true) {
      history.back();
      return;
    }
    replaceClosedRoute();
  }
  function handlePopState() {
    if (
      dialog.open &&
      hasRoute() &&
      history.state?.fdaiAgentRolesOverlay === true
    ) {
      window.setTimeout(() => history.back(), 0);
      return;
    }
    sync();
  }
  open.addEventListener("click", (event) => {
    event.preventDefault();
    const url = new URL(location.href);
    url.searchParams.set("roles", "1");
    history.pushState({ fdaiAgentRolesOverlay: true }, "", url);
    showDialog();
    close.focus();
    window.fdaiPublishMockRoute?.();
  });
  close.addEventListener("click", closeRoute);
  dialog.addEventListener("cancel", (event) => {
    event.preventDefault();
    closeRoute();
  });
  dialog.addEventListener("click", (event) => {
    if (event.target === dialog) closeRoute();
  });
  window.addEventListener("popstate", handlePopState);
  window.addEventListener("message", (event) => {
    if (event.origin !== location.origin || event.source !== organizationFrame?.contentWindow) return;
    if (event.data?.type === "fdai:role-agent") {
      if (!dialog.open) return;
      const url = new URL(location.href);
      if (event.data.agent) url.searchParams.set("roleAgent", String(event.data.agent));
      else url.searchParams.set("roleAgent", "");
      history.replaceState(history.state, "", url);
      window.fdaiPublishMockRoute?.();
    } else if (event.data?.type === "fdai:role-dialog-close") {
      closeRoute();
    }
  });
  organizationFrame?.addEventListener("load", redrawOrganization);
  if ("ResizeObserver" in window && organizationFrame) {
    new ResizeObserver(redrawOrganization).observe(organizationFrame);
  }
  sync();
}());
