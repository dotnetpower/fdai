import type { ComponentChildren } from "preact";
import { useEffect, useLayoutEffect, useRef, useState } from "preact/hooks";
import { t } from "../i18n";
import { panelsInGroup } from "../panels";
import { panelPath } from "../router";
import { SettingsDirtyContext, type SettingsDirtyRegistration } from "./settings-dirty-state";

interface SettingsOverlayProps {
  readonly activePanelId: string;
  readonly onClose: () => void;
  readonly onPrefetchPanel?: (panelId: string) => void;
  readonly children: ComponentChildren;
}

const FOCUSABLE_SELECTOR = [
  "a[href]",
  "button:not([disabled])",
  "input:not([disabled])",
  "select:not([disabled])",
  "textarea:not([disabled])",
  "[tabindex]:not([tabindex='-1'])",
].join(",");

export function SettingsOverlay({
  activePanelId,
  onClose,
  onPrefetchPanel,
  children,
}: SettingsOverlayProps) {
  const dialogRef = useRef<HTMLElement | null>(null);
  const navigationRef = useRef<HTMLElement | null>(null);
  const closeRef = useRef<HTMLButtonElement | null>(null);
  const [dirtySources, setDirtySources] = useState<ReadonlySet<string>>(() => new Set());
  const [registerDirtySource] = useState<SettingsDirtyRegistration>(() => (
    source: string,
    dirty: boolean,
  ) => {
    setDirtySources((current) => {
      if (current.has(source) === dirty) return current;
      const next = new Set(current);
      if (dirty) next.add(source);
      else next.delete(source);
      return next;
    });
  });
  const hasUnsavedChanges = dirtySources.size > 0;
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const requestCloseRef = useRef(() => undefined);
  requestCloseRef.current = () => {
    if (hasUnsavedChanges && !window.confirm(t("settings.unsavedConfirm"))) return;
    onCloseRef.current();
  };

  useLayoutEffect(() => {
    const returnFocus = document.activeElement instanceof HTMLElement
      ? document.activeElement
      : null;
    const bodyWasLocked = document.body.classList.contains("scroll-locked");
    document.body.classList.add("scroll-locked");
    closeRef.current?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        requestCloseRef.current();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = [...(dialogRef.current?.querySelectorAll<HTMLElement>(
        FOCUSABLE_SELECTOR,
      ) ?? [])].filter((element) => !element.hasAttribute("disabled"));
      if (focusable.length === 0) {
        event.preventDefault();
        closeRef.current?.focus();
        return;
      }
      const first = focusable[0]!;
      const last = focusable[focusable.length - 1]!;
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    window.addEventListener("keydown", handleKeyDown, true);
    return () => {
      window.removeEventListener("keydown", handleKeyDown, true);
      if (!bodyWasLocked) document.body.classList.remove("scroll-locked");
      returnFocus?.focus();
    };
  }, []);

  useEffect(() => {
    if (!hasUnsavedChanges) return;
    const handleBeforeUnload = (event: BeforeUnloadEvent) => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", handleBeforeUnload);
    return () => window.removeEventListener("beforeunload", handleBeforeUnload);
  }, [hasUnsavedChanges]);

  useLayoutEffect(() => {
    navigationRef.current
      ?.querySelector<HTMLElement>('[aria-current="page"]')
      ?.scrollIntoView({ block: "nearest", inline: "nearest" });
  }, [activePanelId]);

  return (
    <div
      class="settings-overlay-scrim"
      onPointerDown={(event) => {
        if (event.target === event.currentTarget) requestCloseRef.current();
      }}
    >
      <section
        ref={dialogRef}
        id="settings-overlay"
        class="settings-overlay"
        role="dialog"
        aria-modal="true"
        aria-labelledby="settings-overlay-title"
      >
        <header class="settings-overlay-header">
          <div>
            <h2 id="settings-overlay-title">{t("nav.group.settings")}</h2>
            <p>{t("nav.groupHint.settings")}</p>
          </div>
          <button
            ref={closeRef}
            type="button"
            class="settings-overlay-close"
            aria-label={t("settings.close")}
            onClick={() => requestCloseRef.current()}
          >
            <svg
              aria-hidden="true"
              width="20"
              height="20"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="1.8"
              stroke-linecap="round"
            >
              <path d="M6 6 18 18M18 6 6 18" />
            </svg>
          </button>
        </header>
        <div class="settings-overlay-workspace">
          <nav
            ref={navigationRef}
            class="settings-overlay-navigation"
            aria-label={t("settings.menuLabel")}
          >
            <ul>
              {panelsInGroup("settings").map((panel) => (
                <li key={panel.id}>
                  <a
                    href={panelPath(panel.id)}
                    class={panel.id === activePanelId ? "active" : ""}
                    aria-current={panel.id === activePanelId ? "page" : undefined}
                    onClick={(event) => {
                      if (
                        panel.id !== activePanelId
                        && hasUnsavedChanges
                        && !window.confirm(t("settings.unsavedConfirm"))
                      ) event.preventDefault();
                    }}
                    onPointerEnter={() => onPrefetchPanel?.(panel.id)}
                    onFocus={() => onPrefetchPanel?.(panel.id)}
                  >
                    <strong>{panel.label}</strong>
                    {panel.subtitle ? <small>{panel.subtitle}</small> : null}
                  </a>
                </li>
              ))}
            </ul>
          </nav>
          <div class="settings-overlay-content">
            <SettingsDirtyContext.Provider value={registerDirtySource}>
              {children}
            </SettingsDirtyContext.Provider>
          </div>
        </div>
      </section>
    </div>
  );
}
