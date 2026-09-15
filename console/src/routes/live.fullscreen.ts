import { useLayoutEffect, useRef, useState } from "preact/hooks";

type WorkspaceMode = "normal" | "native" | "expanded";

/** Expand only the Live workspace, retaining keyboard access and an explicit API fallback. */
export function useLiveFullscreen() {
  const workspaceRef = useRef<HTMLElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const [mode, setMode] = useState<WorkspaceMode>("normal");
  const [error, setError] = useState(false);
  const modeRef = useRef(mode);
  modeRef.current = mode;
  const restoreFocus = () => window.requestAnimationFrame(
    () => triggerRef.current?.focus({ preventScroll: true }),
  );
  const exit = () => {
    const finish = () => {
      setMode("normal");
      restoreFocus();
    };
    if (document.fullscreenElement !== workspaceRef.current) {
      finish();
      return;
    }
    void document.exitFullscreen().then(finish, (reason: unknown) => {
      if (document.fullscreenElement !== workspaceRef.current) finish();
      else {
        setError(true);
        console.warn("live_fullscreen_exit_failed", reason instanceof Error ? reason.name : "unknown");
      }
    });
  };

  useLayoutEffect(() => {
    const sync = () => {
      if (document.fullscreenElement === workspaceRef.current) {
        setMode("native");
      } else if (modeRef.current === "native") {
        setMode("normal");
        restoreFocus();
      }
    };
    const keydown = (event: KeyboardEvent) => {
      if (
        (modeRef.current === "normal" && document.fullscreenElement !== workspaceRef.current) ||
        document.querySelector(".live-detail-panel")
      ) return;
      if (event.key === "Escape") {
        event.preventDefault();
        exit();
        return;
      }
      if (event.key !== "Tab") return;
      const focusable = [...(workspaceRef.current?.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), summary, [tabindex="0"]',
      ) ?? [])].filter(element => element.getClientRects().length > 0);
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
    document.addEventListener("fullscreenchange", sync);
    document.addEventListener("keydown", keydown);
    return () => {
      document.removeEventListener("fullscreenchange", sync);
      document.removeEventListener("keydown", keydown);
    };
  }, []);

  useLayoutEffect(() => {
    document.body.classList.toggle("live-fullscreen-active", mode !== "normal");
    if (mode !== "normal") triggerRef.current?.focus();
    return () => document.body.classList.remove("live-fullscreen-active");
  }, [mode]);

  const toggle = async () => {
    setError(false);
    if (mode !== "normal") {
      exit();
      return;
    }
    const workspace = workspaceRef.current;
    if (workspace === null) {
      setError(true);
      return;
    }
    if (!document.fullscreenEnabled || typeof workspace.requestFullscreen !== "function") {
      setMode("expanded");
      return;
    }
    const operation = workspace.requestFullscreen({ navigationUI: "hide" });
    await operation.then(
      () => {
        setMode("native");
        restoreFocus();
      },
      (reason: unknown) => {
        if (reason instanceof TypeError || reason instanceof DOMException) {
          setMode("expanded");
        } else {
          setError(true);
        }
        console.warn("live_fullscreen_unavailable", reason instanceof Error ? reason.name : "unknown");
      },
    );
  };
  return { workspaceRef, triggerRef, toggle, mode, error, active: mode !== "normal" };
}
