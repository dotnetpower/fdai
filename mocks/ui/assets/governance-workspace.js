// Presentation-only adaptation for authored Governance mocks, not a runtime projection.
(function () {
  "use strict";

  function mount() {
    document.body.classList.add("cs-operator-neutral", "cs-governance-neutral");
    const root = document.querySelector("main");
    if (!root) {
      console.error("Governance preview cannot initialize: main landmark is missing.");
      return;
    }
    if (!root.querySelector(".oa-preview")) {
      const note = document.createElement("p");
      note.className = "gw-preview-note";
      const label = document.createElement("strong");
      label.textContent = "Synthetic preview";
      const detail = document.createElement("span");
      detail.textContent = "Illustrative records. No live reads or changes.";
      note.append(label, detail);
      const header = root.querySelector(":scope > header, :scope > .cs-page-header");
      if (header) header.after(note);
      else root.prepend(note);
    }
    root.querySelectorAll(".fg-metric strong").forEach((value) => {
      if (!/^[\d\s.,/%+-]+$/.test(value.textContent.trim())) value.classList.add("op-value-label");
    });
    root.querySelectorAll("label select").forEach((select, index) => {
      if (select.hasAttribute("aria-labelledby")) return;
      const text = select.parentElement.querySelector(":scope > span");
      if (!text) return;
      if (!text.id) text.id = `gw-select-label-${index}`;
      select.setAttribute("aria-labelledby", text.id);
    });
    root.querySelectorAll("table").forEach((table, index) => {
      const wrapper = document.createElement("div");
      wrapper.className = "gw-table-scroll";
      wrapper.tabIndex = 0;
      wrapper.setAttribute("role", "region");
      const caption = table.querySelector("caption");
      wrapper.setAttribute("aria-label", caption?.textContent.trim() || `Governance records ${index + 1}`);
      table.before(wrapper);
      wrapper.append(table);
      const hint = document.createElement("p");
      hint.className = "gw-table-hint";
      hint.textContent = "Scroll horizontally to review all columns.";
      wrapper.after(hint);
      const update = () => {
        const overflowing = wrapper.scrollWidth > wrapper.clientWidth + 1;
        wrapper.tabIndex = overflowing ? 0 : -1;
        hint.hidden = !overflowing;
      };
      new ResizeObserver(update).observe(wrapper);
      update();
    });
    root.dataset.governanceReady = "true";
  }
  document.addEventListener("DOMContentLoaded", mount);
})();
