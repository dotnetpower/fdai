(function () {
  "use strict";

  var titles = {
    "RE:01": "Focus workload design on simplicity and efficiency",
    "RE:02": "Identify and rate user and system flows",
    "RE:03": "Perform failure mode analysis",
    "RE:04": "Define reliability and recovery targets",
    "RE:05": "Add redundancy for critical flows",
    "RE:06": "Implement timely and reliable scaling",
    "RE:07": "Implement self-preservation and self-healing",
    "RE:08": "Test resiliency and availability scenarios",
    "RE:09": "Implement tested disaster recovery plans",
    "RE:10": "Continuously measure and track system health",
    "OE:01": "Define standard workload development and operating practices",
    "OE:02": "Standardize routine, ad-hoc, and emergency operations",
    "OE:03": "Formalize practices across the software development lifecycle",
    "OE:04": "Standardize development tools and quality processes",
    "OE:05": "Use a standardized infrastructure-as-code approach",
    "OE:06": "Build a predictable workload supply chain",
    "OE:07": "Design a workload monitoring stack",
    "OE:08": "Establish a structured incident management process",
    "OE:09": "Adopt testing practices aligned with business objectives",
    "OE:10": "Design reliable, secure, and maintainable automation",
    "OE:11": "Define safe deployment practices"
  };
  var statusCycle = [
    "satisfied", "satisfied", "unknown", "satisfied", "failed", "satisfied", "stale",
    "unknown", "failed", "satisfied", "unknown", "satisfied", "stale", "unknown",
    "satisfied", "failed", "unknown", "satisfied", "unknown", "satisfied", "unknown"
  ];
  var critical = ["RE:09", "OE:06", "OE:08", "OE:11"];
  var controls = Object.keys(titles).map(function (id, index) {
    var reliability = id.indexOf("RE:") === 0;
    return {
      id: id,
      title: titles[id],
      pillar: reliability ? "reliability" : "operational-excellence",
      severity: critical.indexOf(id) >= 0 ? "critical" : id === "RE:01" ? "medium" : "high",
      requirements: 2 + index % 3,
      owner: reliability ? "resilience-owner" : "operations-owner",
      status: statusCycle[index]
    };
  });
  var filters = { pillar: "", status: "", search: "" };
  var statusClass = { satisfied: "ok", failed: "err", stale: "wait", unknown: "idle" };

  function label(value) {
    return value.replace(/-/g, " ").replace(/^./, function (letter) { return letter.toUpperCase(); });
  }

  function statusNode(status) {
    var node = document.createElement("span");
    node.className = "cs-status " + statusClass[status];
    node.textContent = label(status);
    return node;
  }

  function renderRow(control) {
    var row = document.createElement("tr");
    var identityCell = document.createElement("td");
    var button = document.createElement("button");
    button.type = "button";
    button.className = "control-table-button";
    button.setAttribute("data-control-id", control.id);
    button.setAttribute("data-cs-drawer-open", "rules-control-drawer");
    var id = document.createElement("code");
    id.textContent = control.id;
    var title = document.createElement("span");
    title.textContent = control.title;
    button.append(id, title);
    identityCell.appendChild(button);
    row.appendChild(identityCell);

    [label(control.pillar), control.severity, String(control.requirements), control.owner].forEach(
      function (value, index) {
        var cell = document.createElement("td");
        cell.className = index === 3 ? "control-col-owner" : "control-col-secondary";
        if (index === 1) {
          var severity = document.createElement("span");
          severity.className = "cs-sev " + control.severity;
          severity.textContent = value;
          cell.appendChild(severity);
        } else if (index === 3) {
          var owner = document.createElement("code");
          owner.textContent = value;
          cell.appendChild(owner);
        } else {
          cell.textContent = value;
        }
        row.appendChild(cell);
      }
    );
    var statusCell = document.createElement("td");
    statusCell.appendChild(statusNode(control.status));
    row.appendChild(statusCell);
    var chevron = document.createElement("td");
    chevron.setAttribute("aria-hidden", "true");
    chevron.textContent = ">";
    row.appendChild(chevron);
    return row;
  }

  function render() {
    var tableBody = document.getElementById("control-table-body");
    var resultCount = document.getElementById("control-result-count");
    if (!tableBody || !resultCount) return;
    var needle = filters.search.toLowerCase();
    var visible = controls.filter(function (control) {
      return (!filters.pillar || control.pillar === filters.pillar)
        && (!filters.status || control.status === filters.status)
        && (!needle || (control.id + " " + control.title).toLowerCase().indexOf(needle) >= 0);
    });
    tableBody.replaceChildren.apply(tableBody, visible.map(renderRow));
    resultCount.textContent = "Showing " + visible.length + " of " + controls.length + " controls.";
  }

  function populateDrawer(control) {
    document.getElementById("control-drawer-title").textContent = control.id;
    document.getElementById("control-drawer-heading").textContent = control.title;
    document.getElementById("control-drawer-rationale").textContent =
      "This control combines deterministic checks with current artifacts, drills, metrics, and accountable approval evidence.";
    var pills = document.getElementById("control-drawer-pills");
    var severity = document.createElement("span");
    severity.className = "cs-sev " + control.severity;
    severity.textContent = control.severity;
    var pillar = document.createElement("span");
    pillar.className = "cs-tag";
    pillar.textContent = label(control.pillar);
    pills.replaceChildren(statusNode(control.status), severity, pillar);
    var requirements = document.getElementById("control-drawer-requirements");
    var items = Array.from({ length: control.requirements }, function (_, index) {
      var row = document.createElement("div");
      row.className = "control-requirement";
      var identity = document.createElement("span");
      var kind = document.createElement("small");
      kind.className = "cs-muted";
      kind.textContent = index % 2 ? "artifact" : "rule";
      var ref = document.createElement("code");
      ref.textContent = control.id.toLowerCase().replace(":", "-") + "-evidence-" + (index + 1);
      identity.append(kind, ref);
      row.append(identity, statusNode(control.status));
      return row;
    });
    requirements.replaceChildren.apply(requirements, items);
  }

  document.addEventListener("click", function (event) {
    var filter = event.target.closest("[data-control-filter] .cs-chip");
    if (filter) {
      var group = filter.closest("[data-control-filter]");
      group.querySelectorAll(".cs-chip").forEach(function (chip) {
        chip.classList.toggle("cs-active", chip === filter);
      });
      filters[group.getAttribute("data-control-filter")] = filter.getAttribute("data-value");
      render();
      return;
    }
    var trigger = event.target.closest("[data-control-id]");
    if (trigger) {
      populateDrawer(controls.find(function (control) {
        return control.id === trigger.getAttribute("data-control-id");
      }));
    }
  });

  document.addEventListener("DOMContentLoaded", function () {
    var search = document.getElementById("control-search");
    search.addEventListener("input", function (event) {
      filters.search = event.target.value.trim();
      render();
    });
    render();
  });
}());
