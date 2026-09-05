// Displays only the public synthetic Markdown fixture, never a runtime prompt.
(function () {
  "use strict";

  const workbench = document.getElementById("ex-workbench");
  const answer = document.getElementById("ex-final");
  const modelCall = document.getElementById("ex-model-call");
  const modelState = document.getElementById("ex-model-state");
  const availability = document.getElementById("ex-prompt-availability");
  const captureState = document.getElementById("ex-prompt-capture-state");
  const missing = document.getElementById("ex-prompt-missing");
  const openButton = document.getElementById("ex-open-prompt");
  const panel = document.getElementById("ex-prompt-panel");
  const loading = document.getElementById("ex-prompt-loading");
  const source = document.getElementById("ex-prompt-source");
  const errorMessage = document.getElementById("ex-prompt-error");
  const metadata = document.getElementById("ex-prompt-file-meta");
  const copyButton = document.getElementById("ex-copy-prompt");
  const download = document.getElementById("ex-download-prompt");
  const feedback = document.getElementById("ex-prompt-feedback");
  const promptUrl = new URL("assets/prompts/system-prompt.example.md", document.baseURI);
  let modelUsed = false;
  let requestVersion = 0;
  let activeRequest = null;
  let deadline = null;
  let markdown = "";

  function clearRequest() {
    requestVersion += 1;
    if (activeRequest) activeRequest.abort();
    activeRequest = null;
    clearTimeout(deadline);
    deadline = null;
  }

  function collapsePrompt(restoreFocus = false) {
    clearRequest();
    panel.hidden = true;
    openButton.setAttribute("aria-expanded", "false");
    markdown = "";
    source.querySelector("code").textContent = "";
    source.hidden = true;
    loading.hidden = true;
    loading.setAttribute("aria-busy", "false");
    errorMessage.hidden = true;
    feedback.textContent = "";
    copyButton.disabled = true;
    download.hidden = true;
    if (restoreFocus) {
      openButton.focus({ preventScroll: true });
      openButton.scrollIntoView({ block: "nearest" });
    }
  }

  function updateModelContext() {
    const stage = workbench.dataset.stage;
    if (stage === "answering" || stage === "complete") modelUsed = true;
    else if (stage !== "cancelled") modelUsed = false;
    modelCall.hidden = !modelUsed;
    if (stage === "complete") {
      answer.querySelector(".ex-final-copy").insertBefore(modelCall, answer.querySelector(".ex-final-reveal"));
    } else {
      answer.parentElement.insertBefore(modelCall, answer);
    }
    modelState.textContent = stage === "answering" ? "Writing answer (simulated)" : stage === "cancelled" ? "Stopped (simulated)" : "Simulated call";
    const available = modelUsed && availability.value === "available";
    openButton.disabled = !available;
    missing.hidden = available;
    captureState.textContent = available ? "Synthetic sample available" : "Not captured";
    if (!modelUsed) modelCall.open = false;
    if ((!modelUsed || !available) && !panel.hidden) collapsePrompt();
  }

  async function openPrompt() {
    if (openButton.disabled) return;
    clearRequest();
    const version = requestVersion;
    const controller = new AbortController();
    activeRequest = controller;
    markdown = "";
    source.querySelector("code").textContent = "";
    source.hidden = true;
    errorMessage.hidden = true;
    feedback.textContent = "";
    metadata.textContent = "Markdown";
    copyButton.disabled = true;
    download.hidden = true;
    loading.hidden = false;
    loading.setAttribute("aria-busy", "true");
    panel.hidden = false;
    openButton.setAttribute("aria-expanded", "true");
    deadline = setTimeout(function () { controller.abort(); }, 5000);
    try {
      const response = await fetch(promptUrl, {
        credentials: "omit",
        cache: "no-store",
        redirect: "error",
        signal: controller.signal,
      });
      if (!response.ok) throw new Error("Example prompt request failed (HTTP " + response.status + ").");
      const text = await response.text();
      if (text.length === 0 || text.length > 16384 || !text.startsWith("# ")) {
        throw new Error("The example prompt is empty, too large, or not a Markdown fixture.");
      }
      if (version !== requestVersion || panel.hidden) return;
      markdown = text;
      source.querySelector("code").textContent = markdown;
      const lineCount = markdown.replace(/\r\n/g, "\n").trimEnd().split("\n").length;
      metadata.textContent = "Markdown / " + lineCount + " lines / Example v1";
      source.hidden = false;
      copyButton.disabled = false;
      download.hidden = false;
    } catch (error) {
      if (version !== requestVersion || panel.hidden) return;
      errorMessage.textContent = controller.signal.aborted
        ? "The example prompt request timed out. Collapse and reopen the file to try again."
        : "Unable to load the example prompt. " + (error instanceof Error ? error.message : "The request failed.");
      errorMessage.hidden = false;
    } finally {
      if (version === requestVersion) {
        clearTimeout(deadline);
        deadline = null;
        activeRequest = null;
        loading.hidden = true;
        loading.setAttribute("aria-busy", "false");
      }
    }
  }

  openButton.addEventListener("click", function () {
    if (panel.hidden) openPrompt();
    else collapsePrompt();
  });
  availability.addEventListener("change", updateModelContext);
  document.getElementById("ex-collapse-prompt").addEventListener("click", function () {
    collapsePrompt(true);
  });
  modelCall.addEventListener("toggle", function () {
    if (!modelCall.open && !panel.hidden) collapsePrompt();
  });
  modelCall.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && !panel.hidden) {
      event.preventDefault();
      event.stopPropagation();
      collapsePrompt(true);
    }
  });
  copyButton.addEventListener("click", async function () {
    const version = requestVersion;
    try {
      await navigator.clipboard.writeText(markdown);
      if (version === requestVersion && !panel.hidden) feedback.textContent = "Markdown copied.";
    } catch {
      if (version === requestVersion && !panel.hidden) feedback.textContent = "Clipboard access was denied. Select the Markdown text or download the example file.";
    }
  });
  new MutationObserver(updateModelContext).observe(workbench, {
    attributes: true,
    attributeFilter: ["data-stage"],
  });
  updateModelContext();
})();
