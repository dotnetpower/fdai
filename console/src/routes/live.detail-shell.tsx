import type { ComponentChildren } from "preact";
import { useEffect, useRef } from "preact/hooks";

export function LiveDetailShell({
  panelId,
  titleId,
  title,
  closeLabel,
  onClose,
  children,
}: {
  readonly panelId: string;
  readonly titleId: string;
  readonly title: string;
  readonly closeLabel: string;
  readonly onClose: () => void;
  readonly children: ComponentChildren;
}) {
  const panelRef = useRef<HTMLElement>(null);

  useEffect(() => {
    const restoreTarget = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const panel = panelRef.current;
    document.body.classList.add("scroll-locked");
    panel?.querySelector<HTMLElement>("button")?.focus();
    const onKeyDown = (event: KeyboardEvent): void => {
      if (event.key === "Escape") {
        event.preventDefault();
        onClose();
        return;
      }
      if (event.key !== "Tab" || panel === null) return;
      const focusable = [...panel.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), [tabindex]:not([tabindex="-1"])',
      )];
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable.at(-1);
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.classList.remove("scroll-locked");
      window.requestAnimationFrame(() => restoreTarget?.focus());
    };
  }, [onClose]);

  return (
    <div
      class="live-detail-backdrop"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside
        ref={panelRef}
        id={panelId}
        class="live-detail-panel"
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
      >
        <header>
          <h2 id={titleId}>{title}</h2>
          <button
            type="button"
            class="live-detail-close"
            aria-label={closeLabel}
            onClick={onClose}
          >
            ×
          </button>
        </header>
        <div class="live-detail-body">{children}</div>
      </aside>
    </div>
  );
}
