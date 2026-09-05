import { autoUpdate, computePosition, flip, offset, shift } from "@floating-ui/dom";
import type { ComponentChildren } from "preact";
import { createPortal } from "preact/compat";
import { useEffect, useLayoutEffect, useRef } from "preact/hooks";

/** One viewport-bound preview for the active resource, rather than one tooltip instance per cell. */
export function DashboardResourcePreview({ anchor, id, children, onClose }: {
  readonly anchor: HTMLElement;
  readonly id: string;
  readonly children: ComponentChildren;
  readonly onClose: () => void;
}) {
  const popup = useRef<HTMLSpanElement | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout>>();
  useLayoutEffect(() => {
    const target = popup.current;
    if (!target) return;
    let active = true;
    const update = () => {
      void computePosition(anchor, target, {
        strategy: "fixed", placement: "top", middleware: [offset(6), flip({ padding: 16 }), shift({ padding: 16 })],
      }).then((position) => {
        if (!active) return;
        target.style.left = `${position.x}px`;
        target.style.top = `${position.y}px`;
        target.style.visibility = "visible";
      });
    };
    const stop = autoUpdate(anchor, target, update);
    return () => { active = false; stop(); };
  }, [anchor]);
  useEffect(() => {
    const cancel = () => clearTimeout(timer.current);
    const closeSoon = () => { cancel(); timer.current = setTimeout(onClose, 150); };
    const outside = (event: Event) => {
      if (event.target instanceof Node && !anchor.contains(event.target) && !popup.current?.contains(event.target)) onClose();
    };
    const key = (event: KeyboardEvent) => { if (event.key === "Escape") onClose(); };
    anchor.addEventListener("pointerleave", closeSoon);
    popup.current?.addEventListener("pointerenter", cancel);
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", key);
    return () => {
      cancel();
      anchor.removeEventListener("pointerleave", closeSoon);
      popup.current?.removeEventListener("pointerenter", cancel);
      document.removeEventListener("pointerdown", outside);
      document.removeEventListener("keydown", key);
    };
  }, [anchor, onClose]);
  return createPortal(<span ref={popup} id={id} role="tooltip" class="app-tooltip" data-state="instant-open"
    style={{ pointerEvents: "auto", visibility: "hidden", maxHeight: "calc(100vh - 32px)", overflow: "auto" }}
    onPointerLeave={onClose}>{children}</span>, document.body);
}
