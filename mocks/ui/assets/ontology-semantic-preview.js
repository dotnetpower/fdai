(function () {
  "use strict";

  var nodes = {
    BusinessCapability: [4, "A stable business outcome that operating services are expected to realize."],
    BusinessService: [7, "An operator-recognizable service boundary connected to workloads, objectives, ownership, and outcomes."],
    Workload: [6, "A deployable or schedulable unit that realizes part of a BusinessService."],
    Resource: [9, "A provider-observed infrastructure, platform, or application instance."],
    Environment: [4, "The deployment and operating context in which a target is observed."],
    ServiceObjective: [6, "A measurable reliability objective attached to one operating subject."],
    RecoveryObjective: [5, "A bounded recovery-time or recovery-point objective."],
    CostObjective: [4, "A governed cost target with scope and measurement window."],
    ArchitectureConstraint: [5, "A reviewed structural constraint that limits acceptable change."],
    Ownership: [6, "An effective-time accountability relationship; it does not grant authority."],
    ChangeWindow: [5, "A reviewed interval in which a class of change may be considered."],
    Signal: [7, "An admitted observation that may support detection but does not establish cause."],
    Finding: [8, "A versioned detector conclusion grounded in admitted evidence."],
    Incident: [8, "A bounded operational disruption with effective time, evidence, and accountable response."],
    Observation: [7, "A source-attributed statement about recorded operating reality."],
    Change: [7, "A recorded configuration or deployment transition."],
    Forecast: [6, "A time-bounded prediction that must later close against an observed outcome."],
    Experiment: [6, "A governed test with explicit stop conditions and expected evidence."],
    DecisionCase: [8, "A reviewable decision context containing evidence, constraints, and alternatives."],
    ActionOption: [7, "A typed candidate action that remains subject to risk and approval gates."],
    ExpectedEffect: [6, "The independently observable effect required to claim operational success."],
    ActionRun: [10, "A two-phase audited attempt to dispatch, verify, or roll back an eligible action."],
    ObservedOutcome: [7, "An authoritative post-action observation compared with the expected effect."],
    Pattern: [6, "A reviewed reusable result; similarity alone never grants execution authority."]
  };

  var relations = [
    ["BusinessCapability", "realized_by", "BusinessService"],
    ["BusinessService", "implemented_by", "Workload"],
    ["BusinessService", "governed_by", "ServiceObjective"],
    ["BusinessService", "accountable_through", "Ownership"],
    ["Workload", "contains", "Resource"],
    ["Resource", "deployed_in", "Environment"],
    ["Resource", "emits", "Signal"],
    ["ServiceObjective", "constrained_by", "ArchitectureConstraint"],
    ["ServiceObjective", "recovered_under", "RecoveryObjective"],
    ["ServiceObjective", "balanced_with", "CostObjective"],
    ["Change", "scheduled_within", "ChangeWindow"],
    ["Change", "affects", "Resource", "temporal"],
    ["Observation", "supports", "Signal"],
    ["Signal", "indicates", "Finding"],
    ["Finding", "escalates_to", "Incident"],
    ["Forecast", "predicts", "Signal", "temporal"],
    ["Experiment", "observes", "Resource"],
    ["Incident", "opens", "DecisionCase", "temporal"],
    ["DecisionCase", "considers", "ActionOption"],
    ["ActionOption", "expects", "ExpectedEffect"],
    ["ActionRun", "realizes", "ActionOption"],
    ["ActionRun", "produces", "ObservedOutcome", "causal / temporal"],
    ["ObservedOutcome", "compared_with", "ExpectedEffect"],
    ["ObservedOutcome", "supports", "Pattern"]
  ];

  var bands = [
    ["operating-scope", "Operating scope", "What is operated and why it matters", ["BusinessCapability", "BusinessService", "Workload", "Resource", "Environment"]],
    ["operating-intent", "Operating intent", "Objectives and constraints to preserve", ["ServiceObjective", "RecoveryObjective", "CostObjective", "ArchitectureConstraint", "Ownership", "ChangeWindow"]],
    ["operating-reality", "Operating reality", "Observed, detected, and predicted conditions", ["Signal", "Finding", "Incident", "Observation", "Change", "Forecast", "Experiment"]],
    ["decision-learning", "Decision and learning", "Alternatives, execution, outcomes, and reviewed reuse", ["DecisionCase", "ActionOption", "ExpectedEffect", "ActionRun", "ObservedOutcome", "Pattern"]]
  ];

  var selectedName = "BusinessService";
  var selectedLens = "relationship";

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, function (character) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[character];
    });
  }

  function related(name) {
    return relations.filter(function (relation) { return relation[0] === name || relation[2] === name; });
  }

  function renderBands() {
    var root = document.querySelector("[data-ontology-bands]");
    if (!root) return;
    root.innerHTML = bands.map(function (band) {
      return '<section class="ontology-semantic-band is-' + band[0] + '"><header><div><span>' +
        escapeHtml(band[1]) + "</span><small>" + escapeHtml(band[2]) + "</small></div><strong>" + band[3].length +
        '</strong></header><div class="ontology-semantic-nodes">' + band[3].map(function (name) {
          return '<button type="button" data-ontology-node="' + escapeHtml(name) + '" aria-pressed="' +
            String(name === selectedName) + '" class="' + (name === selectedName ? "is-selected" : "") + '"><code>' +
            escapeHtml(name) + "</code><span>" + related(name).length + " relationships</span></button>";
        }).join("") + "</div></section>";
    }).join("");
  }

  function relationMarkup(relation, compact) {
    var flags = relation[3] ? '<small class="ontology-relation-flags">' + escapeHtml(relation[3]) + "</small>" : "";
    if (compact) {
      return "<li><code>" + escapeHtml(relation[0]) + '</code><span class="ontology-relation-arrow">--' +
        escapeHtml(relation[1]) + "--&gt;</span><code>" + escapeHtml(relation[2]) + "</code>" + flags + "</li>";
    }
    return "<li><code>" + escapeHtml(relation[0]) + '</code><span class="ontology-relation-arrow">--' +
      escapeHtml(relation[1]) + "--&gt;</span><code>" + escapeHtml(relation[2]) + "</code>" + flags + "</li>";
  }

  function renderLensPanel() {
    var panel = document.querySelector("[data-ontology-lens-panel]");
    if (!panel) return;
    var selectedRelations = related(selectedName);
    if (selectedLens === "relationship") {
      panel.innerHTML = '<section class="ontology-semantic-relations" aria-label="Directed relationships"><header><strong>Directed relationships</strong><span>' +
        selectedRelations.length + "</span></header>" + (selectedRelations.length ? "<ul>" + selectedRelations.map(function (relation) {
          return relationMarkup(relation, false);
        }).join("") + "</ul>" : "<p>No reviewed relationship connects this selection within the semantic model.</p>") + "</section>";
      return;
    }
    if (selectedLens === "state") {
      panel.innerHTML = '<section class="ontology-semantic-state" aria-label="Authority-separated state lanes">' +
        [["Observed", "Provider or telemetry evidence"], ["Derived operational", "Versioned function output with evidence"], ["Desired", "Approved objectives, policy, or configuration"], ["Execution", "Planned, dispatched, verified, or rolled back"]].map(function (item) {
          return "<div><strong>" + item[0] + "</strong><span>" + item[1] + "</span></div>";
        }).join("") + "</section>";
      return;
    }
    if (selectedLens === "context") {
      panel.innerHTML = '<section class="ontology-semantic-context" aria-label="Context snapshot status"><span class="cs-tag">Secured receipt required</span><dl>' +
        '<div><dt>Ontology release</dt><dd><code>sha256:illustrative-release</code></dd></div>' +
        '<div><dt>Projection revision</dt><dd><code>semantic-model-v1</code></dd></div>' +
        '<div><dt>Runtime evidence</dt><dd>No purpose-scoped Context snapshot selected</dd></div>' +
        '<div><dt>Mutation authority</dt><dd>No</dd></div></dl></section>';
      return;
    }
    if (selectedLens === "action") {
      var actionRelations = relations.filter(function (relation) {
        return ["DecisionCase", "ActionOption", "ExpectedEffect", "ActionRun", "ObservedOutcome", "Pattern"].indexOf(relation[0]) !== -1 ||
          ["DecisionCase", "ActionOption", "ExpectedEffect", "ActionRun", "ObservedOutcome", "Pattern"].indexOf(relation[2]) !== -1;
      });
      panel.innerHTML = '<section class="ontology-semantic-relations" aria-label="Action closure relationships"><header><strong>Action closure relationships</strong><span>' +
        actionRelations.length + "</span></header><ul>" + actionRelations.map(function (relation) { return relationMarkup(relation, false); }).join("") + "</ul></section>";
      return;
    }
    panel.innerHTML = '<section class="ontology-semantic-context" aria-label="Selected object"><span class="cs-tag">Object declaration</span><dl>' +
      '<div><dt>Selected ObjectType</dt><dd><code>' + escapeHtml(selectedName) + "</code></dd></div>" +
      '<div><dt>Declared properties</dt><dd>' + nodes[selectedName][0] + "</dd></div>" +
      '<div><dt>Reviewed relationships</dt><dd>' + selectedRelations.length + "</dd></div>" +
      '<div><dt>Authority</dt><dd>Read only</dd></div></dl></section>';
  }

  function renderInspector() {
    var root = document.querySelector("[data-ontology-inspector]");
    if (!root) return;
    var outgoing = relations.filter(function (relation) { return relation[0] === selectedName; });
    var incoming = relations.filter(function (relation) { return relation[2] === selectedName; });
    function direction(title, values) {
      return "<section><h4>" + title + "</h4>" + (values.length ? "<ul>" + values.map(function (relation) {
        return relationMarkup(relation, true);
      }).join("") + "</ul>" : "<p class=\"cs-muted\">None</p>") + "</section>";
    }
    root.innerHTML = '<span class="cs-tag">' + escapeHtml(selectedLens.charAt(0).toUpperCase() + selectedLens.slice(1)) +
      '</span><h3><code>' + escapeHtml(selectedName) + "</code></h3><p>" + escapeHtml(nodes[selectedName][1]) +
      "</p><dl><div><dt>Declared properties</dt><dd>" + nodes[selectedName][0] +
      "</dd></div><div><dt>Outgoing</dt><dd>" + outgoing.length + "</dd></div><div><dt>Incoming</dt><dd>" + incoming.length +
      "</dd></div></dl>" + direction("Outgoing", outgoing) + direction("Incoming", incoming);
  }

  function renderSelection() {
    document.querySelectorAll("[data-ontology-node]").forEach(function (button) {
      var active = button.getAttribute("data-ontology-node") === selectedName;
      button.classList.toggle("is-selected", active);
      button.setAttribute("aria-pressed", String(active));
    });
    document.querySelectorAll("[data-ontology-lens]").forEach(function (button) {
      button.setAttribute("aria-pressed", String(button.getAttribute("data-ontology-lens") === selectedLens));
    });
    renderLensPanel();
    renderInspector();
  }

  function switchView(view) {
    document.body.classList.toggle("is-instance-view", view === "instances");
    document.querySelectorAll("[data-ontology-view]").forEach(function (panel) {
      panel.hidden = panel.getAttribute("data-ontology-view") !== view;
    });
    document.querySelectorAll("[data-ontology-tab]").forEach(function (tab) {
      var active = tab.getAttribute("data-ontology-tab") === view;
      tab.classList.toggle("is-active", active);
      if (active) tab.setAttribute("aria-current", "page");
      else tab.removeAttribute("aria-current");
    });
  }

  function mount() {
    if (!document.querySelector("[data-ontology-preview]")) return;
    renderBands();
    renderSelection();

    document.addEventListener("click", function (event) {
      var node = event.target.closest("[data-ontology-node]");
      if (node) {
        selectedName = node.getAttribute("data-ontology-node");
        renderSelection();
        return;
      }
      var lens = event.target.closest("[data-ontology-lens]");
      if (lens) {
        selectedLens = lens.getAttribute("data-ontology-lens");
        renderSelection();
        return;
      }
      var tab = event.target.closest("[data-ontology-tab]");
      if (tab) {
        event.preventDefault();
        var view = tab.getAttribute("data-ontology-tab");
        switchView(view);
        history.replaceState(null, "", view === "map" ? "ontology.html" : "ontology.html?view=" + encodeURIComponent(view));
        if (window.fdaiPublishMockRoute) window.fdaiPublishMockRoute();
      }
    });

    var requested = new URLSearchParams(location.search).get("view");
    switchView(["map", "objects", "links", "actions", "instances", "topology"].indexOf(requested) === -1 ? "map" : requested);
  }

  document.addEventListener("DOMContentLoaded", mount);
})();
