import { useCallback, useEffect, useMemo, useRef, useState } from "preact/hooks";
import {
  clampDockWidth,
  parseDeckLayoutMode,
  type DeckLayoutMode,
} from "./command-deck-session";

const DECK_LAYOUT_KEY = "fdai.deck.layout.v1";
const DECK_DOCK_WIDTH_KEY = "fdai.deck.dock-width.v1";

function sessionStore(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.sessionStorage : null;
  } catch {
    return null;
  }
}

function initialDockWidth(): number {
  if (typeof window === "undefined") return 440;
  const stored = Number.parseInt(sessionStore()?.getItem(DECK_DOCK_WIDTH_KEY) ?? "", 10);
  return clampDockWidth(Number.isFinite(stored) ? stored : 440, window.innerWidth);
}

function initialFloatingPosition(): { readonly x: number; readonly y: number } {
  if (typeof window === "undefined") return { x: 720, y: 84 };
  return {
    x: Math.max(68, window.innerWidth - 476),
    y: 76,
  };
}

export function commandDeckLayoutStyle(
  mode: DeckLayoutMode,
  floatingPosition: { readonly x: number; readonly y: number },
  dockWidth: number,
): Record<string, string> | undefined {
  if (mode === "floating") {
    return {
      left: `${floatingPosition.x}px`,
      top: `${floatingPosition.y}px`,
    };
  }
  if (mode === "dock") return { "--deck-dock-width": `${dockWidth}px` };
  return undefined;
}

export function useCommandDeckLayout(open: boolean) {
  const [layoutMode, setLayoutMode] = useState<DeckLayoutMode>(() =>
    parseDeckLayoutMode(sessionStore()?.getItem(DECK_LAYOUT_KEY) ?? null));
  const [floatingPosition, setFloatingPosition] = useState(initialFloatingPosition);
  const [dockWidth, setDockWidth] = useState(initialDockWidth);
  const [dockResizing, setDockResizing] = useState(false);
  const [dragging, setDragging] = useState(false);
  const overlayRef = useRef<HTMLDivElement | null>(null);

  const selectLayoutMode = useCallback((mode: DeckLayoutMode) => {
    setLayoutMode(mode);
    try {
      sessionStore()?.setItem(DECK_LAYOUT_KEY, mode);
    } catch {
      /* best-effort preference */
    }
  }, []);

  const deckStyle = useMemo(() => {
    return commandDeckLayoutStyle(layoutMode, floatingPosition, dockWidth);
  }, [dockWidth, floatingPosition, layoutMode]);

  const startFloatingDrag = (event: MouseEvent) => {
    if (layoutMode !== "floating" || event.button !== 0) return;
    const target = event.target as HTMLElement | null;
    if (target?.closest("button, a, input, textarea")) return;
    event.preventDefault();
    const overlay = overlayRef.current;
    if (!overlay) return;
    const rect = overlay.getBoundingClientRect();
    const offsetX = event.clientX - rect.left;
    const offsetY = event.clientY - rect.top;
    setDragging(true);

    const onMove = (moveEvent: MouseEvent) => {
      setFloatingPosition({
        x: Math.max(12, moveEvent.clientX - offsetX),
        y: Math.max(12, moveEvent.clientY - offsetY),
      });
    };
    const onEnd = () => {
      setDragging(false);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onEnd);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onEnd);
  };

  const updateDockWidth = (value: number) => {
    const next = clampDockWidth(value, window.innerWidth);
    setDockWidth(next);
    return next;
  };

  const saveDockWidth = (value: number) => {
    try {
      sessionStore()?.setItem(DECK_DOCK_WIDTH_KEY, String(value));
    } catch {
      /* best-effort preference */
    }
  };

  const startDockResize = (event: MouseEvent) => {
    if (layoutMode !== "dock" || event.button !== 0) return;
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = dockWidth;
    let latest = dockWidth;
    setDockResizing(true);

    const onMove = (moveEvent: MouseEvent) => {
      latest = updateDockWidth(startWidth + startX - moveEvent.clientX);
    };
    const onEnd = () => {
      setDockResizing(false);
      saveDockWidth(latest);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onEnd);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onEnd);
  };

  const onDockResizeKeyDown = (event: KeyboardEvent) => {
    if (layoutMode !== "dock" || (event.key !== "ArrowLeft" && event.key !== "ArrowRight")) {
      return;
    }
    event.preventDefault();
    const delta = event.key === "ArrowLeft" ? 20 : -20;
    const next = updateDockWidth(dockWidth + delta);
    saveDockWidth(next);
  };

  const onOverlayKeyDown = useCallback((event: KeyboardEvent) => {
    if (layoutMode !== "workspace" || event.key !== "Tab") return;
    const root = overlayRef.current;
    if (!root) return;
    const focusable = Array.from(
      root.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    ).filter((element) =>
      element.offsetParent !== null || element === document.activeElement,
    );
    if (focusable.length === 0) return;
    const first = focusable[0]!;
    const last = focusable[focusable.length - 1]!;
    const active = document.activeElement as HTMLElement | null;
    if (event.shiftKey && active === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && active === last) {
      event.preventDefault();
      first.focus();
    }
  }, [layoutMode]);

  useEffect(() => {
    const workspaceClass = "deck-open";
    const dockClass = "deck-dock-right";
    const resizingClass = "deck-dock-resizing";
    document.body.classList.toggle(workspaceClass, open && layoutMode === "workspace");
    document.body.classList.toggle(dockClass, open && layoutMode === "dock");
    document.body.classList.toggle(resizingClass, open && layoutMode === "dock" && dockResizing);
    if (open && layoutMode === "dock") {
      document.body.style.setProperty("--deck-dock-width", `${dockWidth}px`);
    } else {
      document.body.style.removeProperty("--deck-dock-width");
    }
    return () => {
      document.body.classList.remove(workspaceClass, dockClass, resizingClass);
      document.body.style.removeProperty("--deck-dock-width");
    };
  }, [dockResizing, dockWidth, layoutMode, open]);

  return {
    deckStyle,
    dockWidth,
    dragging,
    layoutMode,
    onDockResizeKeyDown,
    onOverlayKeyDown,
    overlayRef,
    selectLayoutMode,
    startDockResize,
    startFloatingDrag,
  };
}
