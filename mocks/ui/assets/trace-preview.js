/* Switches between read-investigation and decision traces without replaying either fixture. */
(function () {
  "use strict";
  var buttons = Array.from(document.querySelectorAll("[data-trace-mode]"));
  var surfaces = Array.from(document.querySelectorAll("[data-trace-surface]"));
  var meta = document.querySelector("[data-trace-meta]");
  if (!buttons.length || !surfaces.length) return;

  function select(mode, persist) {
    var selected = mode === "decision" ? "decision" : "read";
    buttons.forEach(function (button) {
      button.setAttribute("aria-selected", String(button.dataset.traceMode === selected));
    });
    surfaces.forEach(function (surface) {
      surface.hidden = surface.dataset.traceSurface !== selected;
    });
    if (meta) {
      meta.textContent = selected === "read"
        ? "6 observed stages / total 7.8 seconds"
        : "7 decision stages / 3.2 seconds";
    }
    if (persist) {
      var url = new URL(window.location.href);
      url.searchParams.set("mode", selected);
      window.history.replaceState(null, "", url);
      if (window.fdaiPublishMockRoute) window.fdaiPublishMockRoute();
    }
  }

  buttons.forEach(function (button) {
    button.addEventListener("click", function () {
      select(button.dataset.traceMode, true);
    });
    button.addEventListener("keydown", function (event) {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault();
      var current = buttons.indexOf(button);
      var next = event.key === "Home"
        ? 0
        : event.key === "End"
          ? buttons.length - 1
          : (current + (event.key === "ArrowRight" ? 1 : -1) + buttons.length) % buttons.length;
      buttons[next].focus();
      buttons[next].click();
    });
  });
  select(new URLSearchParams(window.location.search).get("mode"), false);
}());
