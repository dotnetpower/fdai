// Same-snapshot hover/focus information. Selection and authority remain with the controller.
(function () {
  "use strict";
  const { statusKey, typeNames } = window.FdaiDashboardData;
  const { element, badge } = window.FdaiDashboardViews;
  function create(getSnapshot) {
    const map = document.getElementById("resource-honeycomb");
    const tip = document.getElementById("resource-hover-preview");
    let anchor = null;
    let dismissTimer;
    let positionFrame;
    function hide() {
      clearTimeout(dismissTimer);
      cancelAnimationFrame(positionFrame);
      if (anchor) anchor.removeAttribute("aria-describedby");
      anchor = null;
      tip.hidden = true;
    }
    function position(cell) {
      const rect = cell.getBoundingClientRect();
      const width = tip.offsetWidth;
      const height = tip.offsetHeight;
      const left = Math.max(8, Math.min(rect.left, innerWidth - width - 8));
      const top = rect.bottom + height + 8 <= innerHeight ? rect.bottom + 8 : Math.max(8, rect.top - height - 8);
      tip.style.left = left + "px";
      tip.style.top = top + "px";
    }
    function deferHide() {
      clearTimeout(dismissTimer);
      dismissTimer = setTimeout(hide, 150);
    }
    function show(cell) {
      hide();
      const snapshot = getSnapshot();
      const resource = snapshot.byId.get(cell.dataset.resourceId);
      if (!resource) throw new Error("Preview resource is outside the active example snapshot");
      anchor = cell;
      tip.dataset.resourceId = resource.id;
      tip.dataset.snapshotId = snapshot.id;
      tip.replaceChildren(
        element("strong", "dr-hover-name", resource.name),
        element("p", "dr-hover-scope", `${typeNames[resource.type]} / ${resource.subscriptionName} / ${resource.groupName}`),
      );
      const facts = element("dl", "dr-hover-facts");
      for (const [lens, label] of [["operation", "Operating state"], ["availability", "Availability"], ["observation", "Observation"]]) {
        const row = element("div");
        const value = element("dd");
        value.appendChild(badge(lens, statusKey(resource, lens, snapshot)));
        row.append(element("dt", "", label), value);
        facts.appendChild(row);
      }
      tip.append(facts, element("p", "dr-hover-time", resource.time
        ? `Observed 05 Sep 2026, ${resource.time} KST` : "State observation time not recorded"),
      element("p", "dr-hover-time", `Synthetic provider observation / ${snapshot.complete ? "Complete" : "Partial"} inventory`),
      element("p", "dr-hover-help", "Click or press Enter to pin details. Escape dismisses this preview."));
      tip.hidden = false;
      cell.setAttribute("aria-describedby", tip.id);
      position(cell);
    }
    map.addEventListener("pointerover", (event) => {
      const cell = event.target.closest(".dr-cell");
      if (cell && event.pointerType !== "touch" && cell !== anchor) show(cell);
    });
    map.addEventListener("pointerout", (event) => {
      if (event.target.closest(".dr-cell") && !tip.contains(event.relatedTarget)) deferHide();
    });
    map.addEventListener("focusin", (event) => {
      if (event.target.matches(".dr-cell")) show(event.target);
    });
    map.addEventListener("focusout", hide);
    tip.addEventListener("pointerenter", () => clearTimeout(dismissTimer));
    tip.addEventListener("pointerleave", deferHide);
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape" && !tip.hidden) { event.preventDefault(); hide(); }
    });
    document.addEventListener("scroll", (event) => {
      if (tip.contains(event.target)) return;
      if (anchor && document.activeElement === anchor) {
        const cell = anchor;
        cancelAnimationFrame(positionFrame);
        positionFrame = requestAnimationFrame(() => {
          if (anchor !== cell) return;
          const rect = cell.getBoundingClientRect();
          if (rect.bottom > 0 && rect.top < innerHeight) position(cell);
          else hide();
        });
      } else hide();
    }, true);
    window.addEventListener("resize", hide);
    return { hide };
  }
  window.FdaiDashboardPreview = Object.freeze({ create });
})();
