/* Architecture lenses change presentation only; they never change the stored synthetic topology. */
(function () {
  "use strict";
  function mount() {
  var root = document.querySelector("[data-console-parity-page]");
  if (!root) return;
  var sections = Array.from(root.querySelectorAll(".cp-section[id^='architecture-']"));
  if (!sections.length) return;
  var labels = {
    runtime: "Runtime topology",
    authority: "Authority boundary",
    effect: "Effect verification"
  };
  var tabs = document.createElement("div");
  tabs.className = "flow-mode-tabs";
  tabs.setAttribute("role", "tablist");
  tabs.setAttribute("aria-label", "Architecture lenses");
  Object.keys(labels).forEach(function (lens) {
    var button = document.createElement("button");
    button.id = "architecture-tab-" + lens;
    button.type = "button";
    button.dataset.architectureLens = lens;
    button.setAttribute("role", "tab");
    button.setAttribute("aria-controls", "architecture-panel-" + lens);
    button.textContent = labels[lens];
    tabs.appendChild(button);
  });
  var boundary = root.querySelector(".cs-readonly-banner");
  boundary.after(tabs);
  var panels = {};
  Object.keys(labels).forEach(function (lens) {
    var panel = document.createElement("div");
    panel.id = "architecture-panel-" + lens;
    panel.className = "architecture-lens-panel";
    panel.setAttribute("role", "tabpanel");
    panel.setAttribute("aria-labelledby", "architecture-tab-" + lens);
    sections.filter(function (section) {
      return section.id.startsWith("architecture-" + lens);
    }).forEach(function (section) {
      panel.appendChild(section);
    });
    root.appendChild(panel);
    panels[lens] = panel;
  });

  function select(lens, persist) {
    var selected = labels[lens] ? lens : "runtime";
    tabs.querySelectorAll("button").forEach(function (button) {
      button.setAttribute("aria-selected", String(button.dataset.architectureLens === selected));
    });
    Object.keys(panels).forEach(function (lens) {
      panels[lens].hidden = lens !== selected;
    });
    if (persist) {
      var url = new URL(window.location.href);
      url.searchParams.set("lens", selected);
      window.history.replaceState(null, "", url);
      if (window.fdaiPublishMockRoute) window.fdaiPublishMockRoute();
    }
  }

  tabs.addEventListener("click", function (event) {
    var button = event.target.closest("[data-architecture-lens]");
    if (button) select(button.dataset.architectureLens, true);
  });
  tabs.addEventListener("keydown", function (event) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    var controls = Array.from(tabs.querySelectorAll("[data-architecture-lens]"));
    var current = controls.indexOf(event.target);
    if (current < 0) return;
    event.preventDefault();
    var next = event.key === "Home"
      ? 0
      : event.key === "End"
        ? controls.length - 1
        : (current + (event.key === "ArrowRight" ? 1 : -1) + controls.length) % controls.length;
    controls[next].focus();
    controls[next].click();
  });
  select(new URLSearchParams(window.location.search).get("lens"), false);
  }
  document.addEventListener("DOMContentLoaded", mount);
}());
