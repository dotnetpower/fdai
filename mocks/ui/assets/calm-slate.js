// Calm Slate - minimal interactions for the UI kit demo.
// The production console is read-only; this script performs no privileged action.
(function () {
  "use strict";

  var navigationGroups = [
    ["Console", [
      ["live.html", "Live", ""],
      ["dashboard.html", "Overview", "is-sage"],
      ["incidents.html", "Incidents", "is-terracotta"],
      ["hil.html", "HIL queue", "is-terracotta"],
      ["promotion.html", "Promotion", "is-teal"],
      ["rules.html", "Rules", ""],
      ["actions.html", "Actions (ontology)", "is-plum"],
      ["audit.html", "Audit", "is-terracotta"],
      ["rca.html", "RCA", "is-teal"]
    ]],
    ["Fleet & safety", [
      ["agents.html", "Fleet roster", "is-sage"],
      ["agents-constellation.html", "Constellation", ""],
      ["pantheon.html", "Pantheon", "is-plum"],
      ["agent-activity.html", "Agent activity", ""],
      ["blast-radius.html", "Blast radius", "is-terracotta"],
      ["provision.html", "Provisioning", ""],
      ["onboarding.html", "Onboarding", "is-dusty-red"],
      ["llm-cost.html", "LLM cost", "is-teal"]
    ]],
    ["Knowledge", [
      ["ontology.html", "Ontology", "is-plum"],
      ["rule-trace.html", "Rule trace", "is-teal"],
      ["workflow-builder.html", "Workflow builder", ""]
    ]],
    ["Chat", [
      ["deck.html", "Command deck", "is-plum"],
      ["deck-sources.html", "Deck sources", ""]
    ]],
    ["Report & kit", [
      ["report.html", "Weekly report", "is-terracotta"],
      ["rca-report.html", "RCA report", "is-teal"],
      ["settings.html", "Settings", "is-steel"],
      ["components.html", "Components", ""]
    ]],
    ["Explorations", [
      ["agent-icons.html", "Agent icons", "is-plum"],
      ["hcard-variants.html", "HIL card variants", "is-teal"]
    ]]
  ];

  function createNavigation() {
    if (window.self !== window.top) {
      document.body.classList.add("cs-embedded");
      return;
    }

    var currentPage = window.location.pathname.split("/").pop() || "dashboard.html";
    var sidebar = document.createElement("aside");
    sidebar.className = "cs-app-sidebar";
    sidebar.setAttribute("aria-label", "Mock navigation");

    var html = '<a class="cs-sidebar-brand" href="dashboard.html"><span class="cs-brand-mark">AW</span> FDAI</a>';
    navigationGroups.forEach(function (group) {
      html += '<section class="cs-sidebar-group"><h2>' + group[0] + '</h2><ul>';
      group[1].forEach(function (item) {
        var active = item[0] === currentPage;
        html += '<li><a href="' + item[0] + '"' + (active ? ' class="cs-active" aria-current="page"' : '') + '>' +
          '<span class="cs-sidebar-dot ' + item[2] + '"></span>' + item[1] + '</a></li>';
      });
      html += "</ul></section>";
    });
    sidebar.innerHTML = html;

    var menuButton = document.createElement("button");
    menuButton.className = "cs-sidebar-menu";
    menuButton.type = "button";
    menuButton.setAttribute("aria-label", "Toggle navigation");
    menuButton.setAttribute("aria-expanded", "false");

    function setNavigationOpen(open) {
      document.body.classList.toggle("cs-sidebar-open", open);
      menuButton.setAttribute("aria-expanded", String(open));
    }

    menuButton.addEventListener("click", function () {
      setNavigationOpen(!document.body.classList.contains("cs-sidebar-open"));
    });

    var backdrop = document.createElement("button");
    backdrop.className = "cs-sidebar-backdrop";
    backdrop.type = "button";
    backdrop.setAttribute("aria-label", "Close navigation");
    backdrop.addEventListener("click", function () { setNavigationOpen(false); });
    document.addEventListener("keydown", function (event) {
      if (event.key === "Escape") setNavigationOpen(false);
    });

    document.body.prepend(sidebar);
    document.body.prepend(backdrop);
    document.body.prepend(menuButton);
    document.body.classList.add("cs-has-sidebar");
  }

  document.addEventListener("DOMContentLoaded", createNavigation);

  // ---- Tabs (unchanged) -----------------------------------------------------
  document.addEventListener("click", function (event) {
    var tab = event.target.closest("[data-cs-tab]");
    if (!tab) return;
    var group = tab.closest("[data-cs-tabs]");
    if (!group) return;

    var targetId = tab.getAttribute("data-cs-tab");
    group.querySelectorAll("[data-cs-tab]").forEach(function (t) {
      t.classList.toggle("cs-active", t === tab);
    });

    var container = group.parentElement;
    container.querySelectorAll(".cs-tabpanel").forEach(function (panel) {
      panel.classList.toggle("cs-active", panel.id === targetId);
    });
  });

  // ---- Chart -> data modal --------------------------------------------------
  // Any element with class="js-chartable" becomes clickable. Data attributes:
  //   data-chart-title     : modal title
  //   data-chart-sub       : optional subtitle under the title
  //   data-chart-columns   : JSON array of column labels, e.g. ["Tier","Share"]
  //   data-chart-rows      : JSON array of row arrays
  //   data-chart-num-cols  : optional JSON array of 0-based column indices to
  //                          right-align (tabular numerals)
  //   data-chart-source    : optional footer text (source / window)

  var modalEl = null;
  var lastTrigger = null;

  function ensureModal() {
    if (modalEl) return modalEl;
    modalEl = document.createElement("div");
    modalEl.className = "cs-modal";
    modalEl.setAttribute("role", "dialog");
    modalEl.setAttribute("aria-modal", "true");
    modalEl.setAttribute("aria-labelledby", "cs-modal-title");
    modalEl.hidden = true;
    modalEl.innerHTML = [
      '<div class="cs-modal-panel">',
      '  <div class="cs-modal-head">',
      '    <div>',
      '      <h3 id="cs-modal-title" class="cs-modal-title"></h3>',
      '      <p class="cs-modal-sub" hidden></p>',
      '    </div>',
      '    <button type="button" class="cs-modal-close" aria-label="Close">&times;</button>',
      '  </div>',
      '  <div class="cs-modal-body"></div>',
      '  <div class="cs-modal-foot" hidden></div>',
      '</div>'
    ].join("");
    document.body.appendChild(modalEl);

    modalEl.addEventListener("click", function (e) {
      if (e.target === modalEl) closeModal();
    });
    modalEl.querySelector(".cs-modal-close").addEventListener("click", closeModal);

    return modalEl;
  }

  function parseJSONAttr(el, name) {
    var raw = el.getAttribute(name);
    if (!raw) return null;
    try { return JSON.parse(raw); }
    catch (e) { console.warn("chart modal: bad JSON on", name, raw); return null; }
  }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
    });
  }

  function renderTable(columns, rows, numCols) {
    var numSet = {};
    (numCols || []).forEach(function (i) { numSet[i] = true; });

    var thead = "<thead><tr>" + columns.map(function (c, i) {
      var cls = numSet[i] ? ' class="cs-num"' : "";
      return "<th" + cls + ">" + escapeHtml(c) + "</th>";
    }).join("") + "</tr></thead>";

    var tbody = "<tbody>" + rows.map(function (row) {
      return "<tr>" + row.map(function (cell, i) {
        var cls = numSet[i] ? ' class="cs-num"' : "";
        return "<td" + cls + ">" + escapeHtml(cell) + "</td>";
      }).join("") + "</tr>";
    }).join("") + "</tbody>";

    return '<div class="cs-table-wrap"><table class="cs-table">' + thead + tbody + "</table></div>";
  }

  function openModal(trigger) {
    var title   = trigger.getAttribute("data-chart-title") || "Details";
    var sub     = trigger.getAttribute("data-chart-sub") || "";
    var source  = trigger.getAttribute("data-chart-source") || "";
    var columns = parseJSONAttr(trigger, "data-chart-columns");
    var rows    = parseJSONAttr(trigger, "data-chart-rows");
    var numCols = parseJSONAttr(trigger, "data-chart-num-cols") || [];

    // Fallback: if the trigger doesn't declare explicit rows, derive them from
    // any descendant carrying data-label + data-value (a common annotation on
    // chart marks). Columns default to ["Point", "Value"].
    if (!rows || !rows.length) {
      var marks = trigger.querySelectorAll("[data-label][data-value]");
      if (marks.length) {
        rows = Array.prototype.map.call(marks, function (m) {
          return [m.getAttribute("data-label"), m.getAttribute("data-value")];
        });
        if (!columns || !columns.length) columns = ["Point", "Value"];
      }
    }
    columns = columns || [];
    rows = rows || [];

    var m = ensureModal();
    m.querySelector(".cs-modal-title").textContent = title;
    var subEl = m.querySelector(".cs-modal-sub");
    if (sub) { subEl.textContent = sub; subEl.hidden = false; }
    else { subEl.hidden = true; }

    m.querySelector(".cs-modal-body").innerHTML = columns.length && rows.length
      ? renderTable(columns, rows, numCols)
      : '<p class="cs-muted">No data provided.</p>';

    var footEl = m.querySelector(".cs-modal-foot");
    if (source) { footEl.textContent = source; footEl.hidden = false; }
    else { footEl.hidden = true; }

    lastTrigger = trigger;
    m.hidden = false;
    document.body.classList.add("cs-modal-open");
    m.querySelector(".cs-modal-close").focus();
  }

  function closeModal() {
    if (!modalEl || modalEl.hidden) return;
    modalEl.hidden = true;
    document.body.classList.remove("cs-modal-open");
    if (lastTrigger && typeof lastTrigger.focus === "function") lastTrigger.focus();
  }

  document.addEventListener("click", function (event) {
    var trigger = event.target.closest(".js-chartable");
    if (!trigger) return;
    if (event.target.closest("a, button, [role=button]") && event.target.closest("a, button, [role=button]") !== trigger) return;
    event.preventDefault();
    openModal(trigger);
  });

  document.addEventListener("keydown", function (event) {
    if (!modalEl || modalEl.hidden) return;
    if (event.key === "Escape") { event.preventDefault(); closeModal(); }
  });

  // Make chartables keyboard-activatable.
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".js-chartable").forEach(function (el) {
      if (!el.hasAttribute("tabindex")) el.setAttribute("tabindex", "0");
      if (!el.hasAttribute("role")) el.setAttribute("role", "button");
      el.addEventListener("keydown", function (e) {
        if (e.key === "Enter" || e.key === " ") { e.preventDefault(); openModal(el); }
      });
    });
  });
})();
