const MIN_SCALE = 0.2;
const MAX_SCALE = 8;
const PAN_THRESHOLD_PX = 4;

export function clampZoom(scale) {
  return Math.min(MAX_SCALE, Math.max(MIN_SCALE, scale));
}

export function scaledSvgWidth(baseWidth, scale) {
  return Math.max(1, Math.round(baseWidth * clampZoom(scale)));
}

export function shouldCloseBackdrop(targetIsBackdrop, suppressClick) {
  return targetIsBackdrop && !suppressClick;
}

export function zoomLabels(language = "en") {
  if (language.toLowerCase().startsWith("ko")) {
    return {
      dialog: "확대된 다이어그램",
      open: "다이어그램 확대",
      zoomIn: "확대",
      zoomOut: "축소",
      reset: "보기 초기화",
      close: "닫기",
      zoomLevel: "확대 비율",
    };
  }
  return {
    dialog: "Expanded diagram",
    open: "Expand diagram",
    zoomIn: "Zoom in",
    zoomOut: "Zoom out",
    reset: "Reset view",
    close: "Close",
    zoomLevel: "Zoom level",
  };
}

export function createPanGesture(threshold = PAN_THRESHOLD_PX) {
  let active = false;
  let moved = false;
  let startX = 0;
  let startY = 0;
  let startTx = 0;
  let startTy = 0;

  return {
    start(pointerX, pointerY, tx, ty) {
      active = true;
      moved = false;
      startX = pointerX;
      startY = pointerY;
      startTx = tx;
      startTy = ty;
    },
    move(pointerX, pointerY) {
      if (!active) return null;
      const dx = pointerX - startX;
      const dy = pointerY - startY;
      moved ||= Math.hypot(dx, dy) >= threshold;
      return {
        tx: startTx + dx,
        ty: startTy + dy,
        moved,
      };
    },
    end() {
      const suppressClick = active && moved;
      active = false;
      moved = false;
      return suppressClick;
    },
    cancel() {
      active = false;
      moved = false;
    },
  };
}

export function installMermaidZoom(root = document) {
  if (root.documentElement.dataset.mermaidZoomBound === "true") return;
  root.documentElement.dataset.mermaidZoomBound = "true";

  const view = root.defaultView ?? window;
  const labels = zoomLabels(root.documentElement.lang);
  const gesture = createPanGesture();
  let overlay;
  let stage;
  let inner;
  let svgClone;
  let scale = 1;
  let baseWidth = 1;
  let tx = 0;
  let ty = 0;
  let activePointerId;
  let suppressBackdropClick = false;
  let opener;
  let closeButton;
  let zoomStatus;

  const apply = () => {
    if (!inner || !svgClone) return;
    inner.style.transform = `translate(${Math.round(tx)}px, ${Math.round(ty)}px)`;
    svgClone.style.width = `${scaledSvgWidth(baseWidth, scale)}px`;
    if (zoomStatus) zoomStatus.textContent = `${Math.round(scale * 100)}%`;
  };

  const zoomBy = (factor) => {
    scale = clampZoom(scale * factor);
    apply();
  };

  const close = () => {
    if (!overlay) return;
    overlay.classList.remove("open");
    root.documentElement.style.overflow = "";
    gesture.cancel();
    activePointerId = undefined;
    suppressBackdropClick = false;
    opener?.focus?.({ preventScroll: true });
    opener = undefined;
  };

  const finishPan = (event, cancelled = false) => {
    if (activePointerId !== event.pointerId) return;
    if (stage.hasPointerCapture?.(event.pointerId)) {
      stage.releasePointerCapture(event.pointerId);
    }
    stage.classList.remove("dragging");
    activePointerId = undefined;
    if (cancelled) {
      gesture.cancel();
      suppressBackdropClick = false;
      return;
    }
    suppressBackdropClick = gesture.end();
    view.setTimeout(() => {
      suppressBackdropClick = false;
    }, 0);
  };

  const build = () => {
    overlay = root.createElement("div");
    overlay.className = "mermaid-zoom-overlay";
    overlay.setAttribute("role", "dialog");
    overlay.setAttribute("aria-modal", "true");
    overlay.setAttribute("aria-label", labels.dialog);

    const bar = root.createElement("div");
    bar.className = "mermaid-zoom-toolbar";
    zoomStatus = root.createElement("output");
    zoomStatus.className = "mermaid-zoom-status";
    zoomStatus.setAttribute("aria-label", labels.zoomLevel);
    zoomStatus.setAttribute("aria-live", "polite");
    bar.appendChild(zoomStatus);
    const makeButton = (label, title, action) => {
      const button = root.createElement("button");
      button.type = "button";
      button.textContent = label;
      button.title = title;
      button.setAttribute("aria-label", title);
      button.addEventListener("click", (event) => {
        event.stopPropagation();
        action();
      });
      bar.appendChild(button);
    };
    makeButton("+", labels.zoomIn, () => zoomBy(1.2));
    makeButton("-", labels.zoomOut, () => zoomBy(1 / 1.2));
    makeButton("Reset", labels.reset, () => {
      scale = 1;
      tx = 0;
      ty = 0;
      apply();
    });
    makeButton("x", labels.close, close);
    closeButton = bar.lastElementChild;

    stage = root.createElement("div");
    stage.className = "mermaid-zoom-stage";
    inner = root.createElement("div");
    inner.className = "mermaid-zoom-inner";
    stage.appendChild(inner);
    overlay.appendChild(bar);
    overlay.appendChild(stage);
    root.body.appendChild(overlay);

    overlay.addEventListener("click", (event) => {
      const targetIsBackdrop = event.target === overlay || event.target === stage;
      const suppressClick = suppressBackdropClick;
      suppressBackdropClick = false;
      if (shouldCloseBackdrop(targetIsBackdrop, suppressClick)) close();
    });

    stage.addEventListener(
      "wheel",
      (event) => {
        event.preventDefault();
        zoomBy(event.deltaY < 0 ? 1.1 : 1 / 1.1);
      },
      { passive: false },
    );

    stage.addEventListener("pointerdown", (event) => {
      if (event.button !== 0 || activePointerId !== undefined) return;
      event.preventDefault();
      root.getSelection?.()?.removeAllRanges();
      activePointerId = event.pointerId;
      gesture.start(event.clientX, event.clientY, tx, ty);
      stage.classList.add("dragging");
      stage.setPointerCapture?.(event.pointerId);
    });

    stage.addEventListener("pointermove", (event) => {
      if (activePointerId !== event.pointerId) return;
      const next = gesture.move(event.clientX, event.clientY);
      if (!next) return;
      tx = next.tx;
      ty = next.ty;
      apply();
    });

    stage.addEventListener("pointerup", (event) => finishPan(event));
    stage.addEventListener("pointercancel", (event) => finishPan(event, true));

    root.addEventListener("keydown", (event) => {
      if (!overlay.classList.contains("open")) return;
      if (event.key === "Escape") {
        event.preventDefault();
        close();
        return;
      }
      if (event.key === "+" || event.key === "=") {
        event.preventDefault();
        zoomBy(1.2);
        return;
      }
      if (event.key === "-") {
        event.preventDefault();
        zoomBy(1 / 1.2);
        return;
      }
      if (event.key === "0") {
        event.preventDefault();
        scale = 1;
        tx = 0;
        ty = 0;
        apply();
        return;
      }
      const panStep = event.shiftKey ? 120 : 48;
      if (event.key === "ArrowLeft") tx += panStep;
      else if (event.key === "ArrowRight") tx -= panStep;
      else if (event.key === "ArrowUp") ty += panStep;
      else if (event.key === "ArrowDown") ty -= panStep;
      else if (event.key !== "Tab") return;
      if (event.key.startsWith("Arrow")) {
        event.preventDefault();
        apply();
        return;
      }
      if (event.key !== "Tab") return;
      const buttons = [...bar.querySelectorAll("button")];
      if (buttons.length === 0) return;
      const first = buttons[0];
      const last = buttons.at(-1);
      if (event.shiftKey && root.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && root.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    });
  };

  const open = (svg, trigger) => {
    if (!overlay) build();
    opener = trigger;
    inner.replaceChildren();
    svgClone = svg.cloneNode(true);
    svgClone.removeAttribute("width");
    svgClone.removeAttribute("height");
    svgClone.style.maxWidth = "none";
    svgClone.style.height = "auto";
    svgClone.setAttribute("preserveAspectRatio", "xMidYMid meet");
    inner.appendChild(svgClone);
    scale = 1;
    tx = 0;
    ty = 0;
    baseWidth = Math.min((stage.clientWidth || view.innerWidth) * 0.9, 1400);
    apply();
    overlay.classList.add("open");
    root.documentElement.style.overflow = "hidden";
    closeButton.focus({ preventScroll: true });
  };

  const prepareDiagrams = (scope = root) => {
    const diagrams = scope.querySelectorAll?.("pre.mermaid") ?? [];
    for (const pre of diagrams) {
      if (!pre.querySelector("svg")) continue;
      pre.setAttribute("role", "button");
      pre.setAttribute("tabindex", "0");
      pre.setAttribute("aria-label", labels.open);
    }
  };

  prepareDiagrams();
  new view.MutationObserver(() => prepareDiagrams()).observe(root.body, {
    childList: true,
    subtree: true,
  });

  root.addEventListener("click", (event) => {
    const pre = event.target.closest?.("pre.mermaid");
    if (!pre) return;
    const svg = pre.querySelector("svg");
    if (svg) open(svg, pre);
  });

  root.addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const pre = event.target.closest?.("pre.mermaid");
    if (!pre || event.target !== pre) return;
    const svg = pre.querySelector("svg");
    if (!svg) return;
    event.preventDefault();
    open(svg, pre);
  });
}

if (typeof document !== "undefined") {
  installMermaidZoom(document);
}
