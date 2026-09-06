const mounts = [...document.querySelectorAll("[data-teams-workflow-preview]")];

async function loadPreview() {
  if (!mounts.length) return;
  mounts.forEach((mount) => {
    delete mount.dataset.teamsWorkflowReady;
    mount.innerHTML = '<div class="cs-state-block" role="status" aria-busy="true" aria-label="Loading Teams Workflows preview"><div class="cs-state-loading-lines" aria-hidden="true"><span></span><span></span><span></span></div></div>';
  });
  try {
    const response = await fetch(new URL("./settings-teams-workflow-content.html?v=2", import.meta.url), {
      signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) throw new Error("Teams Workflows preview returned HTTP " + response.status);
    const html = await response.text();
    const template = new DOMParser().parseFromString(html, "text/html").querySelector("[data-teams-workflow-content]");
    if (!template) throw new Error("Teams Workflows preview has no content root.");
    mounts.forEach((mount) => {
      mount.replaceChildren(template.cloneNode(true));
      mount.dataset.teamsWorkflowReady = "true";
    });
  } catch (error) {
    console.error("Teams Workflows preview could not load.", error);
    mounts.forEach((mount) => {
      const message = document.createElement("p");
      message.setAttribute("role", "alert");
      message.textContent = "Unable to load the Teams Workflows preview.";
      const retry = document.createElement("button");
      retry.className = "cs-control-button";
      retry.type = "button";
      retry.textContent = "Retry Teams preview";
      retry.addEventListener("click", loadPreview, { once: true });
      mount.replaceChildren(message, retry);
    });
  }
}

loadPreview();
