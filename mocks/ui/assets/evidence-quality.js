(function () {
  "use strict";

  function evidenceStatus() {
    var status = document.querySelector("[data-evidence-status]");
    if (status) return status;
    status = document.createElement("p");
    status.className = "cs-sr-only";
    status.dataset.evidenceStatus = "";
    status.setAttribute("role", "status");
    status.setAttribute("aria-live", "polite");
    document.querySelector("main")?.appendChild(status);
    return status;
  }

  function announce(message) {
    evidenceStatus().textContent = message;
  }

  function showFormResult(form, message) {
    var result = form.querySelector(".fg-form-result");
    if (!result) {
      result = document.createElement("p");
      result.className = "fg-form-result";
      result.setAttribute("role", "status");
      form.appendChild(result);
    }
    result.textContent = message;
  }

  function enhanceSelectors() {
    document.querySelectorAll("[data-fg-select]").forEach(function (control) {
      if (control.tagName === "BUTTON" && !control.hasAttribute("type")) {
        control.type = "button";
      }
      var group = control.getAttribute("data-fg-select");
      var value = control.getAttribute("data-fg-value");
      if (!group || !value) return;
      var panel = document.querySelector(
        '[data-fg-panel="' + CSS.escape(group) + '"][data-fg-value="' + CSS.escape(value) + '"]',
      );
      if (panel) {
        panel.id = panel.id || "evidence-" + group + "-" + value;
        panel.setAttribute("role", "region");
        control.setAttribute("aria-controls", panel.id);
        var heading = panel.querySelector("h2, h3");
        if (heading) {
          heading.id = heading.id || panel.id + "-title";
          panel.setAttribute("aria-labelledby", heading.id);
        }
      }
      control.addEventListener("click", function () {
        window.requestAnimationFrame(function () {
          var selected = panel?.querySelector("h2, h3")?.textContent?.trim() ||
            control.textContent?.trim().replace(/\s+/g, " ");
          announce(selected + " selected.");
        });
      });
    });
  }

  function bindAssuranceTwin() {
    if (document.body.dataset.consolePage !== "assurance-twin") return;
    var list = document.querySelector(".cp-workspace-list ul");
    var detail = document.querySelector(".cp-workspace-detail");
    if (!list || !detail) {
      console.error("Assurance Twin review workspace is unavailable.");
      return;
    }

    var records = [
      {
        title: "example/repository#42",
        summary: "Blocked - 2 findings",
        detail: "Two high-severity scope expansions are grounded in the selected change and keep the change blocked.",
        facts: [
          ["Mode", "Enforce"],
          ["Verdict", { text: "Blocked", tone: "danger" }],
          ["Findings", "2 high-severity"],
          ["Evidence freshness", { text: "Fresh", tone: "success" }],
          ["Action effect", "Change remains blocked"],
          ["Audit", { text: "Review evidence", href: "audit.html?kind=assurance-twin&review=42" }],
        ],
      },
      {
        title: "example/repository#41",
        summary: "Clear - no findings",
        detail: "The reviewed change stayed within its declared scope and every required evidence reference resolved.",
        facts: [
          ["Mode", "Shadow"],
          ["Verdict", { text: "Clear", tone: "success" }],
          ["Findings", "0"],
          ["Evidence freshness", { text: "Fresh", tone: "success" }],
          ["Action effect", "No operational effect"],
          ["Audit", { text: "Review evidence", href: "audit.html?kind=assurance-twin&review=41" }],
        ],
      },
      {
        title: "example/repository#39",
        summary: "Needs review - stale evidence",
        detail: "The source revision is known, but its verification receipt exceeded the freshness budget, so no clear verdict is available.",
        facts: [
          ["Mode", "Shadow"],
          ["Verdict", { text: "Needs review", tone: "warning" }],
          ["Findings", "1 evidence gap"],
          ["Evidence freshness", { text: "Stale", tone: "warning" }],
          ["Action effect", "No operational effect"],
          ["Audit", { text: "Review evidence", href: "audit.html?kind=assurance-twin&review=39" }],
        ],
      },
    ];

    var items = Array.from(list.querySelectorAll("li"));
    items.forEach(function (item, index) {
      var record = records[index];
      if (!record) return;
      item.replaceChildren();
      var button = document.createElement("button");
      button.type = "button";
      button.className = "evidence-review-option";
      button.dataset.assuranceReview = String(index);
      button.setAttribute("aria-pressed", String(index === 0));
      var title = document.createElement("strong");
      title.textContent = record.title;
      var summary = document.createElement("small");
      summary.textContent = record.summary;
      button.append(title, summary);
      item.appendChild(button);
    });

    var detailTitle = detail.querySelector("h3");
    var detailCopy = detail.querySelector(".cp-workspace-body > p");
    var facts = Array.from(detail.querySelectorAll(".cp-facts > div"));
    detail.id = "assurance-review-detail";
    detail.setAttribute("role", "region");
    detail.setAttribute("aria-live", "polite");

    function renderValue(container, value) {
      container.replaceChildren();
      if (typeof value === "string") {
        container.textContent = value;
        return;
      }
      if (value.href) {
        var link = document.createElement("a");
        link.href = value.href;
        link.textContent = value.text;
        container.appendChild(link);
        return;
      }
      var status = document.createElement("span");
      status.className = "cp-status is-" + value.tone;
      status.textContent = value.text;
      container.appendChild(status);
    }

    function selectRecord(index, shouldAnnounce) {
      var record = records[index];
      if (!record) {
        console.error("Assurance Twin review selection is invalid.");
        return;
      }
      items.forEach(function (item, itemIndex) {
        var selected = itemIndex === index;
        item.classList.toggle("is-selected", selected);
        item.querySelector("button")?.setAttribute("aria-pressed", String(selected));
      });
      detailTitle.textContent = record.title;
      detailCopy.textContent = record.detail;
      facts.forEach(function (fact, factIndex) {
        var entry = record.facts[factIndex];
        if (!entry) return;
        fact.querySelector("dt").textContent = entry[0];
        renderValue(fact.querySelector("dd"), entry[1]);
      });
      if (shouldAnnounce) {
        announce(record.title + " review selected: " + record.summary + ".");
      }
    }

    list.querySelectorAll("[data-assurance-review]").forEach(function (button) {
      button.setAttribute("aria-controls", detail.id);
      button.addEventListener("click", function () {
        selectRecord(Number(button.dataset.assuranceReview), true);
      });
    });
    selectRecord(0, false);
  }

  function bindConversationSearch() {
    if (document.body.dataset.evidencePage !== "conversation-search") return;
    var form = document.querySelector("[data-evidence-search]");
    var list = document.querySelector(".search-result-list");
    var empty = document.querySelector("[data-evidence-search-empty]");
    var workbench = document.querySelector(".search-workbench");
    var detail = document.querySelector(".search-workbench .fg-detail");
    var count = document.querySelector("[data-evidence-search-count]");
    if (!form || !list || !empty || !workbench || !detail || !count) {
      console.error("Conversation search preview controls are unavailable.");
      return;
    }
    var query = form.querySelector('input[type="search"]');
    var role = form.querySelector("[data-evidence-search-role]");
    var items = Array.from(list.querySelectorAll("li"));

    function applySearch(reportResult) {
      var tokens = query.value.trim().toLowerCase().split(/\s+/).filter(function (token) {
        return token.length > 2 && token !== "evidence";
      });
      var roleValue = role.value;
      var visible = items.filter(function (item) {
        var button = item.querySelector(".search-result");
        var haystack = (button.dataset.searchTerms + " " + button.textContent).toLowerCase();
        var queryMatches = tokens.length === 0 || tokens.every(function (token) {
          return haystack.includes(token);
        });
        var roleMatches = roleValue === "all" || button.dataset.searchRole === roleValue;
        item.hidden = !(queryMatches && roleMatches);
        return !item.hidden;
      });
      count.textContent = visible.length + " of " + items.length + " samples";
      empty.hidden = visible.length !== 0;
      workbench.classList.toggle("is-empty", visible.length === 0);
      detail.hidden = visible.length === 0;
      if (visible.length) {
        var selected = visible.find(function (item) {
          return item.querySelector(".search-result").getAttribute("aria-pressed") === "true";
        }) || visible[0];
        var selectedButton = selected.querySelector(".search-result");
        if (selectedButton.getAttribute("aria-pressed") !== "true") selectedButton.click();
      }
      if (reportResult) {
        showFormResult(
          form,
          visible.length
            ? visible.length + " authorized synthetic sample" + (visible.length === 1 ? "" : "s") + " shown. No request was sent."
            : "No authorized synthetic sample matches. No request was sent.",
        );
      }
    }

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      applySearch(true);
    });
    empty.querySelector("[data-evidence-clear-search]").addEventListener("click", function () {
      query.value = "";
      role.value = "all";
      applySearch(true);
      query.focus();
    });
    applySearch(false);
  }

  function bindReportForm() {
    if (document.body.dataset.evidencePage !== "reports") return;
    var form = document.querySelector("[data-evidence-report-form]");
    if (!form) {
      console.error("Report preview form is unavailable.");
      return;
    }
    var template = form.querySelector("[data-evidence-report-template]");
    document.querySelectorAll('[data-fg-select="report"]').forEach(function (selection) {
      selection.addEventListener("click", function () {
        template.value = selection.getAttribute("data-fg-value");
      });
    });
    form.addEventListener("submit", function () {
      var value = template.value;
      var selection = document.querySelector(
        '[data-fg-select="report"][data-fg-value="' + CSS.escape(value) + '"]',
      );
      if (!selection) {
        console.error("Selected report preview is unavailable.");
        return;
      }
      selection.click();
    });
  }

  function bindAuditPagination() {
    if (document.body.dataset.evidencePage !== "audit") return;
    var button = document.querySelector("[data-evidence-append]");
    var records = Array.from(document.querySelectorAll("[data-evidence-next-record]"));
    var count = document.querySelector("[data-evidence-audit-count]");
    var summary = document.querySelector("[data-evidence-append-summary]");
    if (!button || !records.length || !count || !summary) {
      console.error("Audit cursor preview is unavailable.");
      return;
    }
    button.addEventListener("click", function () {
      records.forEach(function (record) {
        record.hidden = false;
      });
      count.textContent = "8 samples";
      summary.textContent = "Showing 8 representative records across two cursor pages; 1,834 records are omitted from this synthetic preview.";
      button.disabled = true;
      button.textContent = "Next-page samples shown";
      announce("Two next-page audit samples appended. Existing order was preserved.");
    });
  }

  function enhanceRcaStates() {
    if (document.body.dataset.evidencePage !== "rca") return;
    document.querySelectorAll("[data-rca-view]").forEach(function (button) {
      var value = button.dataset.rcaView;
      var panel = document.querySelector('[data-rca-panel="' + CSS.escape(value) + '"]');
      if (!panel) {
        console.error("RCA state panel is unavailable.");
        return;
      }
      panel.id = "rca-" + value + "-panel";
      button.setAttribute("aria-controls", panel.id);
      button.addEventListener("click", function () {
        announce(button.textContent.trim() + " selected.");
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    enhanceSelectors();
    bindAssuranceTwin();
    bindConversationSearch();
    bindReportForm();
    bindAuditPagination();
    enhanceRcaStates();
  });
})();
