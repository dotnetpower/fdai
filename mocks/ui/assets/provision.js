(function () {
  "use strict";

  var STAGE_INTERVAL_MS = 1800;
  var stages = [
    ["request", "Request accepted", "Scope and idempotency key validated."],
    ["policy", "Identity verified", "Runner identity, approval, and policy ceiling verified."],
    ["network", "Network path verified", "Route, DNS, TCP, and authorization checks passed."],
    ["scan", "Inventory scanned", "Authoritative resource inventory returned 23 resources."],
    ["compare", "Baseline compared", "Three managed resources found; one drift item classified."],
    ["plan", "Plan verified", "Seven creates, one update, zero destroys; rollback is available."],
    ["foundation", "Foundation provisioned", "Resource group, app VNet, private connectivity, registry, and observability are ready."],
    ["data", "State and event plane provisioned", "Key Vault, PostgreSQL, Event Hubs shards, and inventory feed are ready."],
    ["services", "Control plane deployed", "Container Apps environment, services, scheduled jobs, and Console are deployed."],
    ["ontology", "Operating ontology composed", "Contracts, vocabulary, relationships, rules, and topic ownership validated."],
    ["agents", "Agent pantheon activated", "All 15 fixed agents started with typed pub/sub ports."],
    ["access", "Access bindings applied", "Least-privilege workload role assignments completed."],
    ["readiness", "Service readiness confirmed", "All service probes and all 15 agent heartbeats passed."],
    ["setup", "Operator setup assessed", "Three tenant-specific human configuration actions require attention."],
    ["verify", "Operational effect verified", "Independent inventory observation confirmed the deployment."]
  ];

  var state = {
    activeStage: 0,
    completedStages: 0,
    paused: false,
    startedAt: 0,
    pausedAt: 0,
    pausedTotal: 0,
    stageStartedAt: 0,
    timer: null,
    clock: null
  };

  var elements = {};

  function cacheElements() {
    elements.status = document.getElementById("pv-status");
    elements.currentDetail = document.getElementById("pv-current-detail");
    elements.progressLabel = document.getElementById("pv-progress-label");
    elements.progressTrack = document.getElementById("pv-progress-track");
    elements.progressFill = document.getElementById("pv-progress-fill");
    elements.elapsed = document.getElementById("pv-elapsed");
    elements.completeCount = document.getElementById("pv-complete-count");
    elements.activeCount = document.getElementById("pv-active-count");
    elements.pendingCount = document.getElementById("pv-pending-count");
    elements.eta = document.getElementById("pv-eta");
    elements.stageSummary = document.getElementById("pv-stage-summary");
    elements.pause = document.getElementById("pv-pause");
    elements.restart = document.getElementById("pv-restart");
    elements.stream = document.getElementById("pv-stream");
    elements.networkState = document.getElementById("pv-network-state");
    elements.networkNote = document.getElementById("pv-network-note");
    elements.scanState = document.getElementById("pv-scan-state");
    elements.handoff = document.getElementById("pv-handoff");
    elements.handoffTitle = document.getElementById("pv-handoff-title");
    elements.handoffDetail = document.getElementById("pv-handoff-detail");
    elements.stageRows = Array.prototype.slice.call(document.querySelectorAll(".pv-stage"));
    elements.resourceRows = Array.prototype.slice.call(document.querySelectorAll(".pv-resource"));
    elements.pathRows = Array.prototype.slice.call(document.querySelectorAll("[data-path-step]"));
    elements.scanSources = Array.prototype.slice.call(document.querySelectorAll("[data-scan-source]"));
    elements.ontologyState = document.getElementById("pv-ontology-state");
    elements.ontologyItems = Array.prototype.slice.call(document.querySelectorAll("[data-ontology-item]"));
    elements.agentsState = document.getElementById("pv-agents-state");
    elements.agentItems = Array.prototype.slice.call(document.querySelectorAll("[data-agent-index]"));
    elements.actionCount = document.getElementById("pv-action-count");
    elements.requiredActions = Array.prototype.slice.call(document.querySelectorAll("[data-required-action]"));
  }

  function formatDuration(milliseconds) {
    var totalSeconds = Math.max(0, Math.floor(milliseconds / 1000));
    var minutes = Math.floor(totalSeconds / 60);
    var seconds = totalSeconds % 60;
    return String(minutes).padStart(2, "0") + ":" + String(seconds).padStart(2, "0");
  }

  function timestamp() {
    return new Intl.DateTimeFormat("en-GB", {
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: false
    }).format(new Date());
  }

  function elapsedMilliseconds() {
    var end = state.paused ? state.pausedAt : performance.now();
    return end - state.startedAt - state.pausedTotal;
  }

  function addEvent(type, message, complete) {
    var row = document.createElement("div");
    row.className = "pv-event" + (complete ? " is-complete" : "");

    var time = document.createElement("time");
    time.textContent = timestamp();
    var eventType = document.createElement("span");
    eventType.className = "pv-event-type";
    eventType.textContent = type;
    var detail = document.createElement("span");
    detail.textContent = message;

    row.appendChild(time);
    row.appendChild(eventType);
    row.appendChild(detail);
    elements.stream.appendChild(row);
    elements.stream.scrollTop = elements.stream.scrollHeight;
  }

  function resetEvidence() {
    elements.networkState.textContent = "Queued";
    elements.networkNote.textContent = "No connectivity conclusion has been made.";
    elements.pathRows.forEach(function (row) {
      row.className = "";
      row.querySelector("em").textContent = "Queued";
    });

    elements.scanState.textContent = "Queued";
    document.getElementById("pv-resource-progress").textContent = "Not measured";
    document.getElementById("pv-page-progress").textContent = "Not measured";
    document.querySelectorAll("[data-pv-readiness]").forEach(function (node) { node.textContent = "Pending"; });
    ["pv-scan-discovered", "pv-scan-managed", "pv-scan-drifted", "pv-scan-imports"].forEach(function (id) {
      document.getElementById(id).textContent = "-";
    });
    elements.scanSources.forEach(function (source) {
      source.textContent = "Queued";
    });

    elements.ontologyState.textContent = "Queued";
    elements.ontologyItems.forEach(function (item) {
      item.className = "pv-ontology-item";
      item.querySelector("em").textContent = "Queued";
    });

    elements.agentsState.textContent = "0 active / 15 queued";
    elements.agentItems.forEach(function (agent) {
      agent.className = "pv-agent";
      agent.querySelector("em").textContent = "Queued";
    });

    elements.actionCount.className = "pv-action-count";
    elements.actionCount.textContent = "Checking";
    elements.requiredActions.forEach(function (action) {
      action.className = "pv-required-action";
      action.querySelector(".pv-action-status").textContent = "Queued";
    });

    elements.handoff.classList.remove("is-ready", "is-attention");
    elements.handoffTitle.textContent = "Waiting for independent verification";
    elements.handoffDetail.textContent =
      "The console destination is withheld until infrastructure, ontology, agents, and expected effects are independently verified.";
    var handoffLink = elements.handoff.querySelector("a");
    handoffLink.setAttribute("aria-disabled", "true");
    handoffLink.setAttribute("tabindex", "-1");
  }

  function resetRows() {
    elements.stageRows.forEach(function (row) {
      row.className = "pv-stage";
      row.querySelector(".pv-stage-state").textContent = "Queued";
      row.querySelector("time").textContent = "-";
    });
    elements.resourceRows.forEach(function (row) {
      if (row.getAttribute("data-resource-static") === "true") {
        row.className = "pv-resource is-prerequisite";
        row.querySelector(".pv-resource-state").textContent = "Ready";
        return;
      }
      if (row.getAttribute("data-resource-enabled") === "false") {
        row.className = "pv-resource is-conditional";
        row.querySelector(".pv-resource-state").textContent = "Not enabled";
        return;
      }
      row.className = "pv-resource";
      row.querySelector(".pv-resource-state").textContent = "Queued";
    });
  }

  function setNetworkProgress(activeIndex) {
    elements.networkState.textContent = activeIndex >= elements.pathRows.length ? "Verified" : "Checking";
    elements.pathRows.forEach(function (row, index) {
      row.className = index < activeIndex ? "is-complete" : index === activeIndex ? "is-active" : "";
      row.querySelector("em").textContent =
        index < activeIndex ? "Passed" : index === activeIndex ? "Checking" : "Queued";
    });
    elements.networkNote.textContent = activeIndex >= elements.pathRows.length
      ? "Runner-to-service private path verified. Peering, DNS, endpoint ports, and scoped identity authorization passed independently."
      : "Each connectivity dimension is checked independently; a route alone does not prove private service access.";
  }

  function setScanProgress(complete) {
    elements.scanState.textContent = complete ? "Complete" : "Scanning";
    elements.scanSources.forEach(function (source, index) {
      source.textContent = complete || index === 0 ? "Complete" : index === 1 ? "Reading" : "Queued";
    });
    document.getElementById("pv-scan-discovered").textContent = complete ? "23" : "12...";
    document.getElementById("pv-scan-managed").textContent = complete ? "3" : "-";
    document.getElementById("pv-scan-drifted").textContent = complete ? "1" : "-";
    document.getElementById("pv-scan-imports").textContent = complete ? "0" : "-";
    document.getElementById("pv-resource-progress").textContent = complete ? "23 / 23 (estimate)" : "12 / 23 (estimate)";
    document.getElementById("pv-page-progress").textContent = complete ? "2 / 2 (estimate)" : "1 / 2 (estimate)";
  }

  function setOntologyProgress(activeIndex) {
    var complete = activeIndex >= elements.ontologyItems.length;
    elements.ontologyState.textContent = complete ? "Validated" : "Composing";
    elements.ontologyItems.forEach(function (item, index) {
      item.className = "pv-ontology-item" +
        (index < activeIndex ? " is-complete" : index === activeIndex && !complete ? " is-active" : "");
      item.querySelector("em").textContent =
        index < activeIndex || complete ? "Validated" : index === activeIndex ? "Loading" : "Queued";
    });
  }

  function setAgentProgress(activeCount) {
    var boundedCount = Math.min(activeCount, elements.agentItems.length);
    elements.agentsState.textContent = boundedCount === elements.agentItems.length
      ? "15 active"
      : boundedCount + " active / " + (elements.agentItems.length - boundedCount) + " queued";
    elements.agentItems.forEach(function (agent, index) {
      agent.className = "pv-agent" +
        (index < boundedCount ? " is-complete" : index === boundedCount ? " is-active" : "");
      agent.querySelector("em").textContent =
        index < boundedCount ? "Active" : index === boundedCount ? "Starting" : "Queued";
    });
  }

  function setActionRequirements(required) {
    elements.actionCount.className = "pv-action-count" + (required ? " is-required" : "");
    elements.actionCount.textContent = required ? "3 actions required" : "Checking";
    elements.requiredActions.forEach(function (action) {
      action.className = "pv-required-action" + (required ? " is-required" : "");
      action.querySelector(".pv-action-status").textContent = required ? "Action required" : "Queued";
    });
  }

  function currentStatusLabel() {
    if (state.activeStage < 6 || state.activeStage === 12 || state.activeStage === 14) {
      return "Verifying";
    }
    if (state.activeStage < 9 || state.activeStage === 11) {
      return "Applying";
    }
    if (state.activeStage === 9) {
      return "Composing";
    }
    if (state.activeStage === 10) {
      return "Activating";
    }
    return "Preparing";
  }

  function updateResourceRows() {
    elements.resourceRows.forEach(function (row) {
      if (row.getAttribute("data-resource-static") === "true") {
        row.className = "pv-resource is-prerequisite";
        row.querySelector(".pv-resource-state").textContent = "Ready";
        return;
      }
      if (row.getAttribute("data-resource-enabled") === "false") {
        row.className = "pv-resource is-conditional";
        row.querySelector(".pv-resource-state").textContent = "Not enabled";
        return;
      }
      var resourceStage = Number(row.getAttribute("data-resource-stage"));
      var resourceState = row.querySelector(".pv-resource-state");
      if (state.completedStages > resourceStage) {
        row.className = "pv-resource is-complete";
        resourceState.textContent = "Ready";
      } else if (state.activeStage === resourceStage && state.completedStages < stages.length) {
        row.className = "pv-resource is-active";
        resourceState.textContent = "Applying";
      } else {
        row.className = "pv-resource";
        resourceState.textContent = state.completedStages >= 5 ? "Planned" : "Queued";
      }
    });
  }

  function updateStageRows() {
    elements.stageRows.forEach(function (row, index) {
      var rowState = row.querySelector(".pv-stage-state");
      if (index < state.completedStages) {
        row.className = "pv-stage is-complete";
        rowState.textContent = "Complete";
      } else if (index === state.activeStage && state.completedStages < stages.length) {
        row.className = "pv-stage is-active";
        rowState.textContent = state.paused ? "Paused" : "In progress";
      } else {
        row.className = "pv-stage";
        rowState.textContent = "Queued";
      }
    });
  }

  function updateSummary() {
    var finished = state.completedStages >= stages.length;
    var pending = Math.max(0, stages.length - state.completedStages - (finished ? 0 : 1));
    var progress = state.completedStages / stages.length * 100;

    elements.completeCount.textContent = String(state.completedStages);
    elements.activeCount.textContent = finished ? "0" : "1";
    elements.pendingCount.textContent = String(pending);
    elements.progressTrack.setAttribute("aria-valuenow", String(state.completedStages));
    elements.progressFill.style.width = progress + "%";
    elements.progressLabel.textContent = finished
      ? "All " + stages.length + " stages complete"
      : "Stage " + (state.activeStage + 1) + " of " + stages.length;
    elements.stageSummary.textContent = finished
      ? stages.length + " complete"
      : state.completedStages + " complete / 1 active / " + pending + " queued";
    elements.eta.textContent = finished
      ? "Complete"
      : "ETA " + formatDuration((stages.length - state.completedStages) * STAGE_INTERVAL_MS);
    var receipts = { database: 8, semantic: 10, models: 10, runtime: 13, system: 13, inventory: 15 };
    document.querySelectorAll("[data-pv-readiness]").forEach(function (node) {
      node.textContent = state.completedStages >= receipts[node.dataset.pvReadiness] ? "Verified example" : "Pending";
    });
    if (finished) {
      document.getElementById("pv-resource-progress").textContent = "23 / 23 - verified example";
      document.getElementById("pv-page-progress").textContent = "2 / 2 - verified example";
    }
  }

  function updateClock() {
    elements.elapsed.textContent = formatDuration(elapsedMilliseconds()) + " elapsed";
    if (state.completedStages < stages.length) {
      var activeRow = elements.stageRows[state.activeStage];
      activeRow.querySelector("time").textContent =
        formatDuration(performance.now() - state.stageStartedAt);

      if (state.activeStage === 2) {
        var pathIndex = Math.min(
          elements.pathRows.length - 1,
          Math.floor((performance.now() - state.stageStartedAt) / (STAGE_INTERVAL_MS / elements.pathRows.length))
        );
        setNetworkProgress(pathIndex);
      }
      if (state.activeStage === 9) {
        var ontologyIndex = Math.min(
          elements.ontologyItems.length - 1,
          Math.floor((performance.now() - state.stageStartedAt) /
            (STAGE_INTERVAL_MS / elements.ontologyItems.length))
        );
        setOntologyProgress(ontologyIndex);
      }
      if (state.activeStage === 10) {
        var activeAgents = Math.min(
          elements.agentItems.length - 1,
          Math.floor((performance.now() - state.stageStartedAt) /
            (STAGE_INTERVAL_MS / elements.agentItems.length))
        );
        setAgentProgress(activeAgents);
      }
    }
  }

  function finishRun() {
    window.clearTimeout(state.timer);
    updateClock();
    window.clearInterval(state.clock);
    state.completedStages = stages.length;
    state.activeStage = stages.length;
    elements.status.className = "pv-status is-attention";
    elements.status.textContent = "Setup required";
    elements.currentDetail.textContent =
      "Infrastructure, ontology, and all 15 agents are verified. Three tenant-specific operator actions remain.";
    elements.pause.disabled = true;
    elements.pause.textContent = "Replay complete";
    setNetworkProgress(elements.pathRows.length);
    setScanProgress(true);
    setOntologyProgress(elements.ontologyItems.length);
    setAgentProgress(elements.agentItems.length);
    setActionRequirements(true);
    updateStageRows();
    updateResourceRows();
    updateSummary();

    elements.handoff.classList.add("is-attention");
    elements.handoffTitle.textContent = "Infrastructure verified - 3 actions remain";
    elements.handoffDetail.textContent =
      "The console is available for configuration. Production onboarding remains incomplete until administrators, accountable stewards, and notification channels are configured.";
    var handoffLink = elements.handoff.querySelector("a");
    handoffLink.removeAttribute("aria-disabled");
    handoffLink.removeAttribute("tabindex");
    addEvent("done", "provision.done - independent effect verified", true);
  }

  function startCurrentStage() {
    if (state.completedStages >= stages.length) {
      finishRun();
      return;
    }

    state.activeStage = state.completedStages;
    state.stageStartedAt = performance.now();
    elements.status.className = "pv-status is-running";
    elements.status.textContent = currentStatusLabel();
    elements.currentDetail.textContent = stages[state.activeStage][2];
    updateStageRows();
    updateResourceRows();
    updateSummary();

    if (state.activeStage === 2) {
      setNetworkProgress(0);
    }
    if (state.activeStage === 3) {
      setScanProgress(false);
    }
    if (state.activeStage === 9) {
      setOntologyProgress(0);
    }
    if (state.activeStage === 10) {
      setAgentProgress(0);
    }
    if (state.activeStage === 13) {
      setActionRequirements(false);
    }
    addEvent(stages[state.activeStage][0], stages[state.activeStage][1], false);
    state.timer = window.setTimeout(completeCurrentStage, STAGE_INTERVAL_MS);
  }

  function completeCurrentStage() {
    if (state.paused) {
      return;
    }

    var completedIndex = state.activeStage;
    var completedRow = elements.stageRows[completedIndex];
    completedRow.querySelector("time").textContent =
      formatDuration(performance.now() - state.stageStartedAt);
    state.completedStages += 1;

    if (completedIndex === 2) {
      setNetworkProgress(elements.pathRows.length);
    }
    if (completedIndex === 3 || completedIndex === 4) {
      setScanProgress(true);
    }
    if (completedIndex === 9) {
      setOntologyProgress(elements.ontologyItems.length);
    }
    if (completedIndex === 10) {
      setAgentProgress(elements.agentItems.length);
    }
    if (completedIndex === 13) {
      setActionRequirements(true);
    }

    addEvent(stages[completedIndex][0], stages[completedIndex][1] + " - complete", true);
    startCurrentStage();
  }

  function restart() {
    window.clearTimeout(state.timer);
    window.clearInterval(state.clock);
    state.activeStage = 0;
    state.completedStages = 0;
    state.paused = false;
    state.startedAt = performance.now();
    state.pausedAt = 0;
    state.pausedTotal = 0;
    state.stageStartedAt = state.startedAt;

    elements.stream.replaceChildren();
    elements.pause.disabled = false;
    elements.pause.textContent = "Pause replay";
    elements.pause.setAttribute("aria-pressed", "false");
    resetRows();
    resetEvidence();
    addEvent("requested", "provision.requested - replay cursor created", false);
    startCurrentStage();
    updateClock();
    state.clock = window.setInterval(updateClock, 250);
  }

  function togglePause() {
    if (state.completedStages >= stages.length) {
      return;
    }

    state.paused = !state.paused;
    if (state.paused) {
      window.clearTimeout(state.timer);
      state.pausedAt = performance.now();
      elements.status.className = "pv-status is-paused";
      elements.status.textContent = "Paused";
      elements.pause.textContent = "Resume replay";
      elements.pause.setAttribute("aria-pressed", "true");
      addEvent("paused", "Live replay paused by operator", false);
    } else {
      var pauseDuration = performance.now() - state.pausedAt;
      state.pausedTotal += pauseDuration;
      state.stageStartedAt += pauseDuration;
      elements.status.className = "pv-status is-running";
      elements.status.textContent = currentStatusLabel();
      elements.pause.textContent = "Pause replay";
      elements.pause.setAttribute("aria-pressed", "false");
      addEvent("resumed", "Live replay resumed", false);
      state.timer = window.setTimeout(completeCurrentStage, STAGE_INTERVAL_MS);
    }
    updateStageRows();
  }

  function initialize() {
    cacheElements();
    elements.pause.addEventListener("click", togglePause);
    elements.restart.addEventListener("click", restart);
    restart();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize);
  } else {
    initialize();
  }
}());
