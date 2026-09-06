// Uses the mock combobox presentation with an explicit committed value, IME handling and scope counts.
(function () {
  "use strict";
  const { element } = window.FdaiDashboardViews;
  const catalog = [{ key: "all", label: "All types", nativeType: "", aliases: ["모든 유형"] }, ...window.FdaiDashboardData.typeCatalog];
  const byKey = new Map(catalog.map((type) => [type.key, type]));
  function create(onSelect) {
    const root = document.getElementById("resource-type-picker");
    const input = document.getElementById("resource-type");
    const popup = document.getElementById("resource-type-popup");
    const list = document.getElementById("resource-type-options");
    const message = document.getElementById("resource-type-results");
    const clear = document.getElementById("resource-type-clear");
    let value = "all";
    let draft = "";
    let counts = new Map();
    let complete = true;
    let active = -1;
    let matches = [];
    let composing = false;
    let compositionCancelled = false;
    let positionFrame;
    function close() {
      if (composing) compositionCancelled = true;
      cancelAnimationFrame(positionFrame);
      popup.hidden = true;
      input.setAttribute("aria-expanded", "false");
      input.removeAttribute("aria-activedescendant");
      input.value = byKey.get(value).label;
      draft = "";
      active = -1;
    }
    function position() {
      if (popup.hidden) return;
      const rect = input.getBoundingClientRect();
      const viewport = window.visualViewport;
      const topEdge = (viewport?.offsetTop || 0) + 8;
      const bottomEdge = (viewport?.offsetTop || 0) + (viewport?.height || innerHeight) - 8;
      if (rect.bottom < topEdge || rect.top > bottomEdge) { popup.style.visibility = "hidden"; return; }
      popup.style.visibility = "visible";
      const below = bottomEdge - rect.bottom - 6;
      const above = rect.top - topEdge - 6;
      const down = below >= 300 || below >= above;
      const space = Math.max(0, down ? below : above);
      const width = Math.min(Math.max(root.clientWidth, 360), innerWidth - 16);
      popup.style.width = width + "px";
      popup.style.maxHeight = space + "px";
      // Fractional scrollport heights can clip the final option at maximum scroll.
      list.style.maxHeight = Math.floor(Math.max(40, Math.min(300, space - 100))) + "px";
      popup.style.left = Math.max(8, Math.min(rect.left, innerWidth - width - 8)) + "px";
      popup.style.top = down ? rect.bottom + 6 + "px" : "auto";
      popup.style.bottom = down ? "auto" : innerHeight - rect.top + 6 + "px";
    }
    function highlight(index) {
      active = index;
      [...list.children].forEach((option, at) => option.classList.toggle("is-active", at === active));
      if (active < 0) input.removeAttribute("aria-activedescendant");
      else {
        const option = list.children[active];
        input.setAttribute("aria-activedescendant", option.id);
        const top = option.offsetTop;
        if (top < list.scrollTop) list.scrollTop = top;
        else if (top + option.offsetHeight > list.scrollTop + list.clientHeight) list.scrollTop = top + option.offsetHeight - list.clientHeight;
      }
    }
    function count(type) {
      return type.key === "all" ? [...counts.values()].reduce((sum, total) => sum + total, 0) : counts.get(type.key) || 0;
    }
    function render() {
      const query = draft.trim().toLowerCase();
      const terms = query.split(/\s+/).filter(Boolean);
      function rank(type) {
        if ([type.label, type.nativeType, ...type.aliases].some((text) => text.toLowerCase() === query)) return 0;
        return type.label.toLowerCase().startsWith(query) ? 1 : 2;
      }
      const allMatches = catalog.filter((type) => {
        const text = `${type.label} ${type.nativeType} ${type.aliases.join(" ")}`.toLowerCase();
        return terms.every((term) => text.includes(term));
      }).sort((a, b) => {
        if (query) return rank(a) - rank(b) || a.label.localeCompare(b.label, "en");
        return Number(b.key === "all") - Number(a.key === "all")
          || Number(b.key === value) - Number(a.key === value)
          || count(b) - count(a) || a.label.localeCompare(b.label, "en");
      });
      matches = allMatches.slice(0, 12);
      list.replaceChildren();
      for (const type of matches) {
        const option = element("div", "cs-combobox-option dr-type-option");
        option.id = "resource-type-option-" + type.key;
        option.role = "option";
        option.tabIndex = -1;
        option.dataset.value = type.key;
        option.setAttribute("aria-selected", String(type.key === value));
        const text = element("span");
        text.append(element("strong", "", type.label), element("small", "", type.nativeType || "Remove the type filter"));
        option.append(text, element("span", "dr-type-count", count(type).toLocaleString("en-US") + " observed"));
        list.appendChild(option);
      }
      message.textContent = matches.length
        ? `${matches.length} of ${allMatches.length} matching types${allMatches.length > 12 ? ". Keep typing to narrow." : "."}`
        : "No matching types. Try a name, abbreviation, or Azure type.";
      document.getElementById("resource-type-help").textContent = `Applied: ${byKey.get(value).label}. Select to change. Counts are before type/state filters, from ${complete ? "received scope" : "partial inventory; full coverage is unknown"}.`;
      popup.hidden = false;
      input.setAttribute("aria-expanded", "true");
      position();
      cancelAnimationFrame(positionFrame);
      positionFrame = requestAnimationFrame(position);
      highlight(-1);
    }
    function open() {
      if (!popup.hidden) return;
      draft = "";
      input.value = "";
      render();
    }
    function select(key) {
      if (!byKey.has(key)) throw new Error("Unknown example resource type");
      value = key;
      close();
      input.focus({ preventScroll: true });
      onSelect(key);
    }
    input.addEventListener("click", open);
    input.addEventListener("input", (event) => {
      if (composing || document.activeElement !== input) return;
      if (compositionCancelled && ["insertCompositionText", "insertFromComposition"].includes(event.inputType)) return;
      draft = input.value;
      render();
    });
    input.addEventListener("compositionstart", () => { composing = true; compositionCancelled = false; });
    input.addEventListener("compositionend", () => {
      composing = false;
      if (compositionCancelled || document.activeElement !== input) { close(); return; }
      draft = input.value;
      render();
    });
    input.addEventListener("keydown", (event) => {
      if (composing || event.isComposing) return;
      if (event.key === "Tab") { close(); return; }
      if (event.key === "Escape" && !popup.hidden) { event.preventDefault(); event.stopPropagation(); close(); return; }
      if (["ArrowDown", "ArrowUp"].includes(event.key)) {
        event.preventDefault();
        open();
        if (matches.length) highlight(active < 0 ? (event.key === "ArrowDown" ? 0 : matches.length - 1)
          : (active + (event.key === "ArrowDown" ? 1 : -1) + matches.length) % matches.length);
      }
      if (event.key === "Enter" && !popup.hidden) {
        event.preventDefault();
        if (active >= 0) select(matches[active].key);
        else message.textContent = "Use Arrow keys then Enter, or choose a result. The applied filter has not changed.";
      }
    });
    list.addEventListener("mousedown", (event) => event.preventDefault());
    list.addEventListener("click", (event) => {
      const option = event.target.closest("[data-value]");
      if (option) select(option.dataset.value);
    });
    clear.addEventListener("click", () => select("all"));
    root.addEventListener("focusout", (event) => { if (!root.contains(event.relatedTarget)) close(); });
    function dismissOutside(event) {
      if (!root.contains(event.target)) close();
    }
    document.addEventListener("pointerdown", dismissOutside);
    document.addEventListener("click", dismissOutside);
    window.addEventListener("blur", close);
    document.addEventListener("scroll", (event) => { if (!popup.contains(event.target)) position(); }, true);
    window.addEventListener("resize", position);
    window.visualViewport?.addEventListener("resize", position);
    return {
      sync(next, nextCounts, inventoryComplete) {
        const changed = value !== next;
        value = next;
        counts = nextCounts;
        complete = inventoryComplete;
        input.dataset.value = value;
        clear.hidden = value === "all";
        if (changed || popup.hidden) close();
        else render();
      },
      close,
    };
  }
  window.FdaiDashboardTypePicker = Object.freeze({ create });
})();
