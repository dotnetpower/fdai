import type { ComponentChildren } from "preact";
import { useId, useLayoutEffect, useRef } from "preact/hooks";

export interface DetailDrawerProps {
  readonly open: boolean;
  readonly title: string;
  readonly subtitle?: string;
  readonly onClose: () => void;
  readonly closeLabel?: string;
  readonly width?: "md" | "lg";
  readonly footer?: ComponentChildren;
  readonly children: ComponentChildren;
}

export function DetailDrawer({
  open,
  title,
  subtitle,
  onClose,
  closeLabel = "Close detail drawer",
  width = "md",
  footer,
  children,
}: DetailDrawerProps) {
  const titleId = useId();
  const closeButtonRef = useRef<HTMLButtonElement>(null);
  const previousFocusRef = useRef<HTMLElement | null>(null);
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  useLayoutEffect(() => {
    if (!open) return;
    previousFocusRef.current = document.activeElement as HTMLElement | null;
    closeButtonRef.current?.focus();

    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape") {
        event.preventDefault();
        onCloseRef.current();
      }
    }

    document.addEventListener("keydown", handleKeyDown);
    return () => {
      document.removeEventListener("keydown", handleKeyDown);
      previousFocusRef.current?.focus?.();
    };
  }, [open]);

  if (!open) return null;

  return (
    <div
      class="cs-drawer-backdrop"
      onClick={(event) => {
        if (event.target === event.currentTarget) {
          onClose();
        }
      }}
    >
      <div
        class={width === "lg" ? "cs-drawer-panel cs-drawer-panel--lg" : "cs-drawer-panel"}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            onClose();
          }
        }}
      >
        <div class="cs-drawer-head">
          <div>
            <h2 id={titleId} class="cs-drawer-title">{title}</h2>
            {subtitle ? <p class="cs-drawer-subtitle">{subtitle}</p> : null}
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            class="cs-drawer-close"
            aria-label={closeLabel}
            onClick={onClose}
          >
            <svg
              width="14"
              height="14"
              viewBox="0 0 14 14"
              fill="none"
              stroke="currentColor"
              stroke-width="1.6"
              stroke-linecap="round"
              aria-hidden="true"
            >
              <path d="M3 3L11 11M11 3L3 11" />
            </svg>
          </button>
        </div>
        <div class="cs-drawer-body">{children}</div>
        {footer ? <div class="cs-drawer-footer">{footer}</div> : null}
      </div>
    </div>
  );
}
