(function () {
  "use strict";

  function normalise(value) {
    return String(value || "").trim().toLowerCase();
  }

  function activate(group, value) {
    var activeControl = null;
    document.querySelectorAll('[data-fg-select="' + group + '"]').forEach(function (button) {
      var active = button.getAttribute("data-fg-value") === value;
      button.setAttribute("aria-pressed", String(active));
      button.classList.toggle("is-selected", active);
      if (active) activeControl = button;
    });
    document.querySelectorAll('[data-fg-panel="' + group + '"]').forEach(function (panel) {
      var active = panel.getAttribute("data-fg-value") === value;
      var panelId = panel.id || "fg-panel-" + group + "-" + value;
      if (active) panel.id = panelId;
      panel.hidden = !active;
      if (activeControl && active) {
        activeControl.setAttribute("aria-controls", panelId);
        panel.setAttribute("aria-labelledby", activeControl.id || "");
      }
    });
    document.querySelectorAll('[data-fg-row-group="' + group + '"]').forEach(function (row) {
      row.classList.toggle("is-selected", row.getAttribute("data-fg-row-value") === value);
    });
    var status = document.querySelector('[data-fg-selection-status="' + group + '"]');
    if (status && activeControl) {
      status.textContent = (activeControl.textContent || "").trim().replace(/\s+/g, " ") + " selected.";
    }
  }

  function bindSelectors() {
    document.querySelectorAll("[data-fg-select]").forEach(function (control, index) {
      if (!control.id) control.id = "fg-select-" + index;
      var group = control.getAttribute("data-fg-select");
      var value = control.getAttribute("data-fg-value");
      var panel = document.querySelector('[data-fg-panel="' + group + '"][data-fg-value="' + value + '"]');
      if (panel) {
        if (!panel.id) panel.id = "fg-panel-" + group + "-" + value;
        control.setAttribute("aria-controls", panel.id);
        panel.setAttribute("role", "region");
        panel.setAttribute("aria-labelledby", control.id);
      }
    });
    document.addEventListener("click", function (event) {
      var control = event.target.closest("[data-fg-select]");
      if (!control) return;
      var group = control.getAttribute("data-fg-select");
      var value = control.getAttribute("data-fg-value");
      if (!group || !value) return;
      activate(group, value);
    });
  }

  function bindSelectionInputs() {
    document.querySelectorAll("[data-fg-select-input]").forEach(function (select) {
      select.addEventListener("change", function () {
        var group = select.getAttribute("data-fg-select-input");
        if (group && select.value) activate(group, select.value);
      });
    });
  }

  function filterItems(form) {
    var group = form.getAttribute("data-fg-filter-form");
    if (!group) return;
    var controls = Array.from(form.querySelectorAll("[data-fg-filter-key]"));
    var items = Array.from(document.querySelectorAll('[data-fg-filter-item="' + group + '"]'));
    items.forEach(function (item) {
      var searchable = normalise([
        item.textContent,
        ...Array.from(item.attributes)
          .filter(function (attribute) { return attribute.name.startsWith("data-"); })
          .map(function (attribute) { return attribute.value; })
      ].join(" "));
      item.hidden = !controls.every(function (control) {
        var value = normalise(control.value);
        if (!value || value === "all") return true;
        var key = control.getAttribute("data-fg-filter-key");
        if (key === "search") return searchable.includes(value);
        var itemValue = normalise(item.getAttribute("data-fg-filter-" + key));
        return itemValue.split(/\s+/).includes(value);
      });
    });

    document.querySelectorAll('[data-fg-filter-section="' + group + '"]').forEach(function (section) {
      section.hidden = !section.querySelector('[data-fg-filter-item="' + group + '"]:not([hidden])');
    });

    var visibleItems = items.filter(function (item) { return !item.hidden; });
    var count = document.querySelector('[data-fg-filter-count="' + group + '"]');
    if (count) count.textContent = visibleItems.length + " of " + items.length + " shown";
    var empty = document.querySelector('[data-fg-filter-empty="' + group + '"]');
    if (empty) empty.hidden = visibleItems.length !== 0;
    var detailSelector = form.getAttribute("data-fg-filter-detail");
    if (detailSelector) {
      var detail = document.querySelector(detailSelector);
      if (detail) detail.hidden = visibleItems.length === 0;
    }

    var selectedItem = visibleItems.find(function (item) {
      var control = item.matches('[aria-pressed="true"]') ? item : item.querySelector('[aria-pressed="true"]');
      return Boolean(control);
    });
    if (!selectedItem && visibleItems.length) {
      var firstControl = visibleItems[0].matches("[data-fg-select], [data-oversight-agent]")
        ? visibleItems[0]
        : visibleItems[0].querySelector("[data-fg-select], [data-oversight-agent]");
      if (firstControl) firstControl.click();
    }

    var status = document.querySelector('[data-fg-filter-status="' + group + '"]');
    if (status) {
      status.textContent = visibleItems.length
        ? visibleItems.length + " of " + items.length + " records shown."
        : "No records match the current filters.";
    }
  }

  function bindFilterForms() {
    document.querySelectorAll("[data-fg-filter-form]").forEach(function (form) {
      var apply = function () { filterItems(form); };
      form.addEventListener("input", function (event) {
        if (event.target.matches("[data-fg-filter-key]")) apply();
      });
      form.addEventListener("change", function (event) {
        if (event.target.matches("[data-fg-filter-key]")) apply();
      });
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        apply();
      });
      form.addEventListener("reset", function () {
        requestAnimationFrame(apply);
      });
      apply();
    });
  }

  function bindCopyButtons() {
    document.querySelectorAll("[data-fg-copy]").forEach(function (button) {
      button.addEventListener("click", async function () {
        var source = document.querySelector(button.getAttribute("data-fg-copy"));
        if (!source) return;
        var text = "value" in source ? source.value : source.textContent;
        var result = button.nextElementSibling;
        if (!result || !result.classList.contains("fg-copy-result")) {
          result = document.createElement("span");
          result.className = "fg-copy-result";
          result.setAttribute("role", "status");
          button.after(result);
        }
        if (!navigator.clipboard || !text) {
          result.textContent = "Copy unavailable. Select the visible value to copy it manually.";
          return;
        }
        button.disabled = true;
        button.setAttribute("aria-busy", "true");
        try {
          await navigator.clipboard.writeText(text);
          result.textContent = "Copied to clipboard.";
        } catch (error) {
          result.textContent = "Copy unavailable. Select the visible value to copy it manually.";
        } finally {
          button.disabled = false;
          button.setAttribute("aria-busy", "false");
        }
      });
    });
  }

  function bindRows() {
    document.querySelectorAll("[data-fg-row-value]").forEach(function (row) {
      row.addEventListener("click", function (event) {
        if (event.target.closest("a, button")) return;
        activate(row.getAttribute("data-fg-row-group"), row.getAttribute("data-fg-row-value"));
      });
    });
  }

  function bindStaticForms() {
    document.querySelectorAll("[data-fg-static-form]").forEach(function (form) {
      form.addEventListener("submit", function (event) {
        event.preventDefault();
        var result = form.querySelector(".fg-form-result");
        if (!result) {
          result = document.createElement("p");
          result.className = "fg-form-result";
          result.setAttribute("role", "status");
          form.appendChild(result);
        }
        result.textContent = form.getAttribute("data-fg-static-message") ||
          "Preview only. No request was sent. The displayed sample record is unchanged.";
      });
    });
  }

  /** Decorative chart heights are not recorded measurements or quantitative evidence. */
  function explainIllustrativeCharts() {
    document.querySelectorAll(".forecast-calibration, .report-mini-bars").forEach(function (chart) {
      if (chart.hasAttribute("data-fg-measured-chart")) return;
      chart.setAttribute("role", "img");
      chart.setAttribute("aria-label", "Illustrative shape only; recorded measurements are unavailable.");
      var note = document.createElement("p");
      note.className = "chart-source-limit";
      note.textContent = "Illustrative shape only. Source values and units were not recorded; do not read bar height as a measurement.";
      chart.after(note);
    });
  }

  function bindOversight() {
    var detail = document.querySelector("[data-oversight-detail]");
    if (detail) {
      if (!detail.id) detail.id = "oversight-agent-detail";
      detail.setAttribute("aria-live", "polite");
    }
    document.querySelectorAll("[data-oversight-agent]").forEach(function (button) {
      if (detail) button.setAttribute("aria-controls", detail.id);
      button.addEventListener("click", function () {
        document.querySelectorAll("[data-oversight-agent]").forEach(function (candidate) {
          candidate.setAttribute("aria-pressed", String(candidate === button));
        });
        ["name", "role", "summary", "coverage", "steward", "knowledge", "approval"].forEach(function (key) {
          var target = document.querySelector("[data-oversight-" + key + "]");
          if (target) target.textContent = button.getAttribute("data-" + key) || "-";
        });
        var status = document.querySelector("[data-oversight-status]");
        if (status) {
          status.textContent = button.getAttribute("data-status") || "Review";
          status.className = "fg-badge " + (button.getAttribute("data-tone") || "");
        }
      });
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    bindSelectors();
    bindSelectionInputs();
    bindFilterForms();
    bindCopyButtons();
    bindRows();
    bindStaticForms();
    bindOversight();
    explainIllustrativeCharts();
  });
})();
