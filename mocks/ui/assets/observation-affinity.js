// Synthetic, page-local affinity interactions. No service calls or persisted settings.
import { readOntologySnapshot } from "./ontology-instance-reader.js";
import { createOntologyPicker } from "./ontology-instance-picker.js";

(function () {
  "use strict";

  const root = document.querySelector(".oa-workspace");
  if (!root) return;
  const byId = (id) => document.getElementById(id);
  const strengths = { preferred: "Preferred", strong: "Strong preference" };
  const durations = { "24h": "24 hours", "7d": "7 days", ongoing: "Ongoing" };
  const states = {
    applied: { label: "Applied", description: "Additional change checks and availability observations are present in the illustrative observation record.", evidence: "Synthetic record OA-001 / 12:00-12:15 UTC, 13 Sep 2026. Not live telemetry." },
    limited: { label: "Budget limited", description: "The preference is recognized, but the extra observation budget is exhausted. Baseline checks continue; no additional collection is confirmed for this window.", evidence: "Synthetic budget record OA-002 / 12:00-12:15 UTC, 13 Sep 2026." },
    unavailable: { label: "Evidence unavailable", description: "No current observation receipt is available. The rule is configured, but its application and the target's health cannot be confirmed.", evidence: "Synthetic source gap / expected receipt for 12:00-12:15 UTC, 13 Sep 2026 is missing." },
    paused: { label: "Paused", description: "This rule requests no additional attention while paused. It does not stop baseline monitoring or suppress incidents.", evidence: "Preview rule state only. No claim about current resource health." },
    pending: { label: "Not evaluated", description: "The preference exists only in this preview. A current observation receipt would be needed to confirm application.", evidence: "No evaluation or collection was requested. No live evidence is available." }
  };
  const rules = [
    { id: "post-change", name: "Post-change observation", reason: "Watch service stability after a planned configuration change.", targets: [{ id: "mock:ontology-2d:group:example-runtime" }], strength: "strong", signals: ["Availability", "Configuration changes"], duration: "24h", state: "applied" },
    { id: "data-continuity", name: "Data continuity", reason: "Give the primary data service additional performance attention.", targets: [{ id: "mock:ontology-2d:example-data:state-db" }], strength: "strong", signals: ["Availability", "Performance"], duration: "ongoing", state: "limited" },
    { id: "cluster-behavior", name: "Runtime behavior", reason: "Observe the runtime environment during a workload transition.", targets: [{ id: "mock:ontology-2d:example-runtime:runtime-environment" }], strength: "preferred", signals: ["Performance"], duration: "7d", state: "unavailable" },
    { id: "api-rollout", name: "API rollout follow-up", reason: "Additional observation is paused after the review window.", targets: [{ id: "mock:ontology-2d:example-runtime:checkout-api" }], strength: "preferred", signals: ["Availability"], duration: "24h", state: "paused" }
  ];
  const seedRules = [...rules];
  const dialog = byId("rule-editor");
  const form = byId("rule-form");
  const picker = createOntologyPicker();
  let selectedId = rules[0].id;
  let nextId = 1;

  function setText(id, value) { byId(id).textContent = value; }
  function setStatus(element, state) {
    element.textContent = states[state].label;
    element.dataset.state = state;
  }
  function selectedRule() { return rules.find((rule) => rule.id === selectedId); }

  function renderDetail() {
    const rule = selectedRule();
    byId("rule-detail").hidden = !rule;
    byId("no-selection").hidden = Boolean(rule);
    if (!rule) return;
    setText("detail-title", rule.name);
    setText("detail-reason", rule.reason);
    byId("detail-targets").replaceChildren(...rule.targets.map((target) => {
      const item = document.createElement("li");
      const name = document.createElement("strong");
      const description = document.createElement("span");
      name.textContent = target.name ?? "Recorded target details unavailable";
      description.textContent = target.description ?? "Synthetic snapshot not loaded. No name-based substitution.";
      const identity = document.createElement("code");
      identity.textContent = target.id;
      const source = document.createElement("span");
      source.textContent = target.generation
        ? `${target.sourceId} / ${target.generation} / recorded ${target.recordedAt}`
        : "No validated source generation available.";
      item.dataset.instanceId = target.id;
      item.append(name, description, identity, source);
      return item;
    }));
    setText("target-membership", rule.targets.some((target) => target.objectType === "ResourceGroup")
      ? "Group membership is the recorded mock snapshot only, not a live or future membership guarantee."
      : "Matches these exact recorded identities only; no extra read or execution authority.");
    setText("detail-strength", strengths[rule.strength]);
    document.querySelector(".oa-preference-scale").dataset.strength = rule.strength;
    setText("detail-signals", rule.signals.join(", "));
    setText("detail-duration", durations[rule.duration] + (rule.duration === "ongoing" ? " / until paused or removed" : " from activation / illustrative, no live timer"));
    setStatus(byId("detail-status"), rule.state);
    setText("detail-application", states[rule.state].description);
    setText("detail-evidence", states[rule.state].evidence);
    setText("toggle-rule", rule.state === "paused" ? "Resume in preview" : "Pause in preview");
  }

  function visibleRules() {
    const query = byId("rule-search").value.trim().toLowerCase();
    const filter = byId("rule-filter").value;
    return rules.filter((rule) => {
      const matchesState = filter === "all" || (filter === "paused" ? rule.state === "paused" : rule.state !== "paused");
      const names = rule.targets.map((target) => `${target.name ?? ""} ${target.id}`).join(" ");
      return matchesState && `${rule.name} ${names}`.toLowerCase().includes(query);
    });
  }

  function render() {
    const visible = visibleRules();
    if (!visible.some((rule) => rule.id === selectedId)) selectedId = visible[0]?.id;
    byId("rule-list").replaceChildren(...visible.map((rule) => {
      const button = byId("rule-template").content.firstElementChild.cloneNode(true);
      button.dataset.ruleId = rule.id;
      button.setAttribute("aria-pressed", String(rule.id === selectedId));
      button.setAttribute("aria-controls", "rule-detail");
      button.setAttribute("aria-label", `Inspect ${rule.name}`);
      button.querySelector(".oa-rule-title").textContent = rule.name;
      button.querySelector(".oa-rule-target").textContent = rule.targets.map((target) => target.name ?? target.id).join(", ");
      button.querySelector(".oa-rule-strength").textContent = strengths[rule.strength];
      button.querySelector(".oa-rule-duration").textContent = durations[rule.duration];
      setStatus(button.querySelector(".oa-status"), rule.state);
      return button;
    }));
    setText("rule-count", `${visible.length} of ${rules.length} rules`);
    byId("empty-rules").hidden = visible.length !== 0;
    renderDetail();
  }

  function resetFilters() {
    byId("rule-search").value = "";
    byId("rule-filter").value = "all";
  }
  function clearErrors() {
    byId("form-error").hidden = true;
    form.querySelectorAll('[aria-invalid="true"]').forEach((input) => {
      input.removeAttribute("aria-invalid");
      input.removeAttribute("aria-describedby");
    });
  }
  function showError(message, input) {
    setText("form-error", message);
    byId("form-error").hidden = false;
    input.setAttribute("aria-invalid", "true");
    input.setAttribute("aria-describedby", "form-error");
    input.focus();
  }

  byId("rule-list").addEventListener("click", (event) => {
    const button = event.target.closest("[data-rule-id]");
    if (!button) return;
    selectedId = button.dataset.ruleId;
    byId("rule-list").querySelectorAll("[data-rule-id]").forEach((item) => {
      item.setAttribute("aria-pressed", String(item.dataset.ruleId === selectedId));
    });
    renderDetail();
    byId("detail-title").focus();
  });
  byId("rule-search").addEventListener("input", render);
  byId("rule-filter").addEventListener("change", render);
  byId("clear-filters").addEventListener("click", () => {
    resetFilters();
    render();
    byId("rule-search").focus();
  });
  byId("toggle-rule").addEventListener("click", () => {
    const rule = selectedRule();
    rule.state = rule.state === "paused" ? "pending" : "paused";
    setText("preview-feedback", `${rule.name}: ${states[rule.state].label} in this preview only. Baseline monitoring is unchanged.`);
    render();
    if (selectedRule()) byId("toggle-rule").focus();
    else byId("rule-filter").focus();
  });
  byId("add-rule").addEventListener("click", () => {
    form.reset();
    clearErrors();
    picker.open();
    dialog.showModal();
    byId("rule-name").focus();
  });
  byId("cancel-rule").addEventListener("click", () => dialog.close());
  dialog.addEventListener("close", () => {
    picker.close();
    byId("add-rule").focus();
  });
  // Keep keyboard focus inside the editor even when the mock lives in an iframe.
  dialog.addEventListener("keydown", (event) => {
    if (event.key !== "Tab") return;
    const controls = [...form.querySelectorAll("button:not(:disabled), input:not(:disabled), select:not(:disabled), summary")]
      .filter((control) => control.getClientRects().length > 0);
    const first = controls[0];
    const last = controls[controls.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  });
  form.addEventListener("input", clearErrors);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    clearErrors();
    const name = byId("rule-name").value.trim();
    const reason = byId("rule-reason").value.trim();
    const selectedTargets = picker.selection();
    const signals = [...form.querySelectorAll('[name="signal"]:checked')].map((input) => input.value);
    if (!selectedTargets) return showError("A complete, validated ontology snapshot is required. Reload the mock source.", byId("target-options"));
    if (!name) return showError("Enter a name for this affinity rule.", byId("rule-name"));
    if (rules.some((rule) => rule.name.toLowerCase() === name.toLowerCase())) return showError("A rule with this name already exists. Choose a different name.", byId("rule-name"));
    if (!selectedTargets.length) return showError("Select at least one observation target.", byId("target-options"));
    if (!signals.length) return showError("Select at least one observation signal.", form.querySelector('[name="signal"]'));
    if (!reason) return showError("Enter a reason for the additional observation.", byId("rule-reason"));
    const rule = {
      id: `preview-${nextId++}`, name, reason, targets: selectedTargets,
      strength: byId("rule-strength").value, duration: byId("rule-duration").value,
      signals, state: "pending"
    };
    rules.unshift(rule);
    selectedId = rule.id;
    resetFilters();
    render();
    dialog.close();
    setText("preview-feedback", `Created ${rule.name} in this preview only. Application is not evaluated. Reloading resets preview changes.`);
  });
  render();
  readOntologySnapshot().then((snapshot) => {
    if (snapshot.completeness !== "complete") return;
    seedRules.forEach((rule) => {
      rule.targets = rule.targets.map((target) => snapshot.instances.find((item) => item.id === target.id) ?? target);
    });
    render();
  }).catch(() => {
    setText("preview-feedback", "Synthetic ontology snapshot unavailable. Seed rules retain identities only; target details cannot be confirmed.");
  }).finally(() => { root.dataset.affinityReady = "true"; });
})();
