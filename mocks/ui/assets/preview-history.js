/* Per-entry presentation and explicit page-owned state only. Never discover or read form values.
   Stable control IDs take precedence; versioned index records remain backward-compatible. */
(function () {
  "use strict";

  var key = "fdaiMockView";
  var controls = "a[href],button,summary";
  var focusControls = controls + ",input[id],select[id]";
  var idPattern = /^[a-zA-Z][a-zA-Z0-9_-]{0,127}$/;
  var payloadLimit = 2048;

  function boundedPayload(value) {
    if (!value || typeof value !== "object" || Array.isArray(value)) return false;
    try {
      var serialized = JSON.stringify(value);
      return typeof serialized === "string" && new TextEncoder().encode(serialized).length <= payloadLimit;
    } catch (error) {
      if (!(error instanceof TypeError)) throw error;
      return false;
    }
  }

  window.createMockViewHistory = function (frame, navigate) {
    var binding = null;
    var timer = null;
    var restoring = false;

    function stateFor(page, section) {
      var state = history.state;
      var result = state && typeof state === "object" && !Array.isArray(state) ? { ...state } : {};
      var saved = result[key];
      if (saved && (saved.page !== page || saved.section !== section)) delete result[key];
      return result;
    }

    function active() {
      return binding && !restoring && frame.contentDocument === binding.doc &&
        location.hash === "#" + binding.page + (binding.section ? "::" + binding.section : "");
    }

    function capture() {
      clearTimeout(timer);
      timer = null;
      if (!active() || !binding.root) return;
      var doc = binding.doc;
      var root = binding.root;
      var focused = doc.activeElement;
      var focus = null;
      if (root.contains(focused) && focused.matches(focusControls)) {
        if (idPattern.test(focused.id)) focus = { id: focused.id, tag: focused.tagName };
        else {
          var focusedIndex = Array.from(root.querySelectorAll(controls)).indexOf(focused);
          if (focusedIndex >= 0 && focusedIndex < 256) focus = { index: focusedIndex, tag: focused.tagName };
        }
      }
      var disclosures = Array.from(root.querySelectorAll("details[id][data-preview-persist]"));
      if (disclosures.length > 64) {
        console.warn("Preview history disclosure limit exceeded.");
        return;
      }
      var state = stateFor(binding.page, binding.section);
      state[key] = {
        version: 1,
        view: root.dataset.previewView,
        page: binding.page,
        section: binding.section,
        x: doc.defaultView.scrollX,
        y: doc.defaultView.scrollY,
        disclosures: disclosures.map(node => ({ id: node.id, open: node.open })),
        focus,
      };
      if (root.fdaiPreviewState) {
        var payload = root.fdaiPreviewState.capture();
        if (!boundedPayload(payload)) {
          console.warn("Ignoring incompatible preview page state.");
          return;
        }
        state[key].pageState = payload;
      }
      history.replaceState(state, "", location.href);
    }

    function schedule() {
      if (binding && binding.root && !timer) timer = setTimeout(capture, 500);
    }

    function onClick(event) {
      capture();
      if (event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey ||
        event.shiftKey || event.altKey) return;
      var anchor = event.target.closest("a[href]");
      if (!anchor || anchor.hasAttribute("download") || (anchor.target && anchor.target !== "_self")) return;
      var url = new URL(anchor.href, binding.doc.location.href);
      if (url.origin !== location.origin) return;
      url.searchParams.delete("preview");
      url.searchParams.delete("shell");
      if (url.pathname.slice(1) + url.search === binding.page) return;
      if (navigate(url)) event.preventDefault();
    }

    function detach() {
      clearTimeout(timer);
      timer = null;
      if (!binding) return;
      binding.doc.removeEventListener("click", onClick, true);
      binding.doc.removeEventListener("toggle", capture, true);
      binding.doc.removeEventListener("scroll", schedule, true);
      binding.doc.removeEventListener("focusin", schedule, true);
      if (binding.root) binding.root.removeEventListener("fdai-preview-state-change", capture);
      binding = null;
      restoring = false;
    }

    function valid(saved, root) {
      return saved && saved.version === 1 && saved.view === root.dataset.previewView &&
        [saved.x, saved.y].every(value => Number.isFinite(value) && value >= 0 && value <= 10000000) &&
        Array.isArray(saved.disclosures) && saved.disclosures.length <= 64 &&
        saved.disclosures.every(item => item && idPattern.test(item.id) && typeof item.open === "boolean") &&
        (saved.pageState === undefined || boundedPayload(saved.pageState)) &&
        (saved.focus === null || (saved.focus && (
          (typeof saved.focus.id === "string" && idPattern.test(saved.focus.id) &&
            ["A", "BUTTON", "SUMMARY", "INPUT", "SELECT"].includes(saved.focus.tag)) ||
          (saved.focus.id === undefined && Number.isInteger(saved.focus.index) &&
            saved.focus.index >= 0 && saved.focus.index < 256 &&
            ["A", "BUTTON", "SUMMARY"].includes(saved.focus.tag)))));
    }

    function bind(page, section, restoreFocus = false) {
      var doc = frame.contentDocument;
      if (binding && binding.doc === doc && binding.page === page && binding.section === section) return;
      detach();
      var root = doc.querySelector("[data-preview-view]");
      binding = { doc, root, page, section };
      doc.addEventListener("click", onClick, true);
      if (!root) return;
      var saved = stateFor(page, section)[key];
      if (saved && !valid(saved, root)) {
        console.warn("Ignoring incompatible preview presentation state.");
        saved = null;
      }
      doc.addEventListener("toggle", capture, true);
      doc.addEventListener("scroll", schedule, true);
      doc.addEventListener("focusin", schedule, true);
      root.addEventListener("fdai-preview-state-change", capture);
      if (!saved) { capture(); return; }
      restoring = true;
      if (saved.pageState !== undefined) {
        if (!root.fdaiPreviewState || typeof root.fdaiPreviewState.restore !== "function") {
          console.warn("Ignoring incompatible preview page state.");
          restoring = false;
          capture();
          return;
        }
        var accepted;
        try {
          accepted = root.fdaiPreviewState.restore(saved.pageState);
        } finally {
          restoring = false;
        }
        if (accepted === false) {
          capture();
          return;
        }
        restoring = true;
      }
      saved.disclosures.forEach(item => {
        var node = doc.getElementById(item.id);
        if (node && root.contains(node) && node.matches("details[data-preview-persist]")) node.open = item.open;
      });
      var currentBinding = binding;
      doc.defaultView.requestAnimationFrame(function () {
        if (binding !== currentBinding) return;
        var target = restoreFocus && saved.focus
          ? saved.focus.id ? doc.getElementById(saved.focus.id) : root.querySelectorAll(controls)[saved.focus.index]
          : null;
        if (target && root.contains(target) && target.matches(focusControls) &&
          target.tagName === saved.focus.tag && !target.matches(":disabled") &&
          !target.closest("[hidden],[inert]") && target.getClientRects().length) target.focus({ preventScroll: true });
        doc.defaultView.scrollTo({ left: saved.x, top: saved.y, behavior: "instant" });
        restoring = false;
      });
    }

    return { capture, detach, stateFor, bind };
  };
})();
