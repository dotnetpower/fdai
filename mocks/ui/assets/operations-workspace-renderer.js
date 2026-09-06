/* Local-only rendering and selection for the source-aligned Operations fixtures. */
(function () {
  "use strict";
  function ui() { return window.FDAI_CONSOLE_PARITY_UI; }
  function recordBody(record) {
    var html = "<h3>" + ui().escape(record.label) + '</h3><div class="cp-workspace-body"><p>' + ui().escape(record.summary) + "</p>";
    html += ui().facts(record.facts || []);
    html += (record.sections || []).map(function (section) {
      return '<details class="op-record-section"><summary>' + ui().escape(section.title) + '</summary><div>' + ui().section(section) + "</div></details>";
    }).join("");
    return html + "</div>";
  }
  function workspace(section) {
    var requested = new URL(location.href).searchParams.get("record");
    var record = requested ? section.records.find(function (item) { return item.id === requested; }) : section.records[0];
    return '<div class="cp-workspace" data-op-workspace="' + ui().escape(section.id) + '"><aside class="cp-workspace-list"><h3>' +
      ui().escape(section.listTitle) + '</h3><ul>' + section.records.map(function (item) {
        return '<li><button type="button" data-op-record="' + ui().escape(item.id) + '" aria-pressed="' + String(item === record) + '"><strong>' +
          ui().escape(item.label) + "</strong><small>" + ui().escape(item.summary) + "</small></button></li>";
      }).join("") + '</ul></aside><article class="cp-workspace-detail" data-op-record-detail>' +
      (record ? recordBody(record) : '<p class="op-empty" role="status">The requested record is not in this collection. Select a listed example; no substitute record is inferred.</p>') + "</article></div>";
  }
  function views(page) {
    var used = page.views.flatMap(function (view) { return view.sections; });
    if (used.length !== page.sections.length || new Set(used).size !== used.length ||
        page.sections.some(function (section) { return !used.includes(section.id); })) {
      throw new Error("Every Operations section must belong to one view.");
    }
    var html = '<div class="op-tabs" role="tablist" aria-label="' + ui().escape(page.title) + ' views">';
    html += page.views.map(function (view, index) {
      return '<button class="cp-tab" type="button" role="tab" id="op-tab-' + ui().escape(view.id) + '" data-op-tab="' + ui().escape(view.id) +
        '" aria-controls="op-panel-' + ui().escape(view.id) + '" aria-selected="' + String(index === 0) + '" tabindex="' + (index === 0 ? "0" : "-1") + '">' + ui().escape(view.label) + "</button>";
    }).join("") + '</div><div role="alert" data-op-tab-error hidden><strong>Preview view unavailable</strong><p>Choose a registered view.</p></div>';
    html += page.views.map(function (view, index) {
      return '<div role="tabpanel" id="op-panel-' + ui().escape(view.id) + '" aria-labelledby="op-tab-' + ui().escape(view.id) +
        '" data-op-panel="' + ui().escape(view.id) + '"' + (index ? " hidden" : "") + ">" +
        view.sections.map(function (id) { return ui().section(page.sections.find(function (section) { return section.id === id; })); }).join("") + "</div>";
    }).join("");
    return html;
  }
  function findSection(sections, id) {
    for (var section of sections) {
      if (section.id === id) return section;
      for (var record of section.records || []) {
        var nested = findSection(record.sections || [], id);
        if (nested) return nested;
      }
    }
    return null;
  }
  function revealAnchor(root) {
    var id = location.hash.slice(1);
    if (!id) return;
    var target = document.getElementById(id);
    if (!target || !root.contains(target)) return;
    var parent = target.parentElement;
    while (parent && parent !== root) {
      if (parent.tagName === "DETAILS") parent.open = true;
      parent = parent.parentElement;
    }
  }
  function previewStates(root) {
    var header = root.querySelector(".cp-header");
    var label = document.createElement("label");
    label.className = "op-preview-state";
    label.textContent = "Preview state";
    var select = document.createElement("select");
    select.className = "cs-control-select";
    ["Sample data", "Loading", "Unavailable", "Error", "Empty"].forEach(function (name) {
      select.add(new Option(name, name.toLowerCase().replace(" ", "-")));
    });
    label.append(select);
    var tabs = root.querySelector(":scope > .op-tabs");
    var tools = document.createElement("div");
    tools.className = "op-workspace-tools";
    if (!tabs) throw new Error("Operations preview requires a registered view navigation.");
    tools.append(tabs, label);
    header.after(tools);
    var content = document.createElement("div");
    content.dataset.opContent = "";
    [...root.children].filter(function (child) { return child !== header && child !== tools; }).forEach(function (child) { content.append(child); });
    var state = document.createElement("div");
    state.className = "op-state";
    state.hidden = true;
    root.append(content, state);
    select.addEventListener("change", function () {
      var mode = select.value;
      content.hidden = mode !== "sample-data";
      state.hidden = mode === "sample-data";
      if (mode === "sample-data") return;
      var messages = {
        loading: ["Loading projection", "A paused loading specimen, not a live request."],
        unavailable: ["Projection unavailable", "No authoritative source is connected in this example. Missing evidence is not zero activity."],
        error: ["Projection could not be read", "Example failure. No successful result or operational effect is established."],
        empty: ["No matching records", "This is a sourced empty example, not proof of absence outside the requested scope."]
      };
      var message = messages[mode];
      if (!message) throw new Error("Unknown Operations preview state.");
      state.setAttribute("role", mode === "error" ? "alert" : "status");
      state.setAttribute("aria-busy", String(mode === "loading"));
      state.innerHTML = "<h2>" + message[0] + "</h2><p>" + message[1] + "</p>" +
        (mode === "loading" ? '<div class="cs-state-loading-lines" aria-hidden="true"><span></span><span></span><span></span></div>' : "");
    });
  }
  async function bind(root, page, pageId) {
    root.addEventListener("click", function (event) {
      var button = event.target.closest("[data-op-record]");
      if (!button) return;
      var container = button.closest("[data-op-workspace]");
      var section = findSection(page.sections, container.dataset.opWorkspace);
      var record = section.records.find(function (item) { return item.id === button.dataset.opRecord; });
      if (!record) throw new Error("Unregistered Operations preview record.");
      container.querySelector("[data-op-record-detail]").innerHTML = recordBody(record);
      container.querySelectorAll(":scope > .cp-workspace-list [data-op-record]").forEach(function (item) {
        item.setAttribute("aria-pressed", String(item === button));
      });
      var url = new URL(location.href);
      url.searchParams.set("record", record.id);
      history.replaceState(null, "", url);
      if (window.fdaiPublishMockRoute) window.fdaiPublishMockRoute();
    });
    root.addEventListener("submit", function (event) {
      var form = event.target.closest("[data-cp-form]");
      if (!form) return;
      event.preventDefault();
      if (pageId !== "scheduler-runs" || form.closest("section").id !== "scheduler-query") return;
      var task = form.querySelector("input").value.trim();
      var status = form.querySelector("select").value;
      var shown = 0;
      var matchesTask = task === "example-scheduled-readiness";
      root.querySelectorAll("#scheduler-dispatch-history tbody tr").forEach(function (row) {
        var state = row.querySelector('[data-label="Status"]');
        row.hidden = !matchesTask || (status !== "All statuses" && state.textContent.trim().toLowerCase() !== status.toLowerCase());
        if (!row.hidden) shown++;
      });
      var notice = form.querySelector("[data-op-query-result]");
      if (!notice) {
        notice = document.createElement("p");
        notice.dataset.opQueryResult = "";
        notice.className = "op-source-note";
        notice.setAttribute("role", "status");
        form.append(notice);
      }
      notice.textContent = !task ? "Enter an exact task ID. No ledger request was made." : shown + " sample attempts shown. No ledger request was made.";
      root.querySelector(".cp-kpis").hidden = !matchesTask || status !== "All statuses";
    });
    if (page.views) {
      var module = await import("./settings-workspace-tabs.js?v=1");
      var aliases = {};
      function addAliases(section, viewId) {
        aliases[section.id] = viewId;
        (section.records || []).forEach(function (record) { (record.sections || []).forEach(function (nested) { addAliases(nested, viewId); }); });
      }
      page.views.forEach(function (view) { view.sections.forEach(function (id) {
        addAliases(page.sections.find(function (section) { return section.id === id; }), view.id);
      }); });
      module.bindWorkspaceTabs(root, {
        tabAttribute: "data-op-tab", panelAttribute: "data-op-panel", openAttribute: "data-open-op",
        errorSelector: "[data-op-tab-error]", defaultTab: page.views[0].id, aliases: aliases
      });
    }
    var task = new URL(location.href).searchParams.get("task_id");
    if (pageId === "scheduler-runs" && task) {
      var input = root.querySelector("#scheduler-query input");
      input.value = task;
      input.closest("form").requestSubmit();
    }
    revealAnchor(root);
    previewStates(root);
    root.dataset.operatorReady = "true";
  }
  window.FDAI_OPERATIONS_RENDERER = { workspace: workspace, views: views, bind: bind };
})();
