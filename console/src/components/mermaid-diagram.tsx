/**
 * MermaidDiagram - lazy-load mermaid.js and render one source string.
 *
 * Single responsibility: given a mermaid ``source``, produce the SVG in
 * place. The upstream console keeps mermaid out of the main bundle by
 * dynamic-importing it on first mount, so panels that never open the
 * diagram never pay the cost. The route module stays UI-only; error
 * and copy affordances live in the calling panel.
 *
 * Contract:
 * - Purely presentational (no data-fetch, no network calls beyond
 *   loading its own JS bundle).
 * - Re-renders when ``source`` changes; each render uses a fresh
 *   deterministic id so mermaid does not collide with a prior tree.
 * - Applies the console's current CSS-variable palette so the diagram
 *   inherits light / dark theme automatically.
 */

import { useEffect, useMemo, useRef, useState } from "preact/hooks";
import { t } from "../i18n";

interface Props {
  readonly source: string;
  /** Optional label announced to screen readers. */
  readonly ariaLabel?: string;
  /** Optional extra class on the wrapper. */
  readonly className?: string;
}

type LoadState =
  | { readonly kind: "loading" }
  | { readonly kind: "ready"; readonly svg: string }
  | { readonly kind: "error"; readonly message: string };

let mermaidPromise: Promise<{
  readonly render: (id: string, src: string) => Promise<{ readonly svg: string }>;
}> | null = null;

/** Idempotent dynamic import of the mermaid runtime + one-time init. */
function loadMermaid() {
  if (mermaidPromise !== null) return mermaidPromise;
  mermaidPromise = (async () => {
    const mod = await import("mermaid");
    const mermaid = mod.default;
    // Manual startOnLoad=false: we drive render() ourselves so a
    // Preact re-render never triggers the auto-scanner.
    mermaid.initialize({
      startOnLoad: false,
      securityLevel: "strict",
      theme: currentTheme(),
      fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
      themeVariables: themeVariables(),
    });
    return { render: mermaid.render.bind(mermaid) };
  })();
  return mermaidPromise;
}

function currentTheme(): "default" | "dark" {
  if (typeof document === "undefined") return "default";
  return document.documentElement.getAttribute("data-theme") === "dark"
    ? "dark"
    : "default";
}

function themeVariables(): Record<string, string> {
  // Neutral tokens that read cleanly on both themes. mermaid's own
  // `theme: "dark"` handles the palette; we override just the fonts.
  return {
    fontFamily: "system-ui, -apple-system, 'Segoe UI', Roboto, sans-serif",
  };
}

let idCounter = 0;

export function MermaidDiagram({ source, ariaLabel, className }: Props) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  const diagramId = useMemo(() => `mmd-${++idCounter}`, []);

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    (async () => {
      try {
        const mermaid = await loadMermaid();
        const { svg } = await mermaid.render(diagramId, source);
        if (!cancelled) setState({ kind: "ready", svg });
      } catch (err) {
        if (!cancelled) {
          setState({
            kind: "error",
            message: err instanceof Error ? err.message : String(err),
          });
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [source, diagramId]);

  if (state.kind === "loading") {
    return (
      <div class={`mermaid-diagram mermaid-diagram-loading ${className ?? ""}`}>
        <span class="state-spinner" aria-hidden="true" />
        <span class="muted">{t("ui.renderingDiagram")}</span>
      </div>
    );
  }
  if (state.kind === "error") {
    return (
      <div class={`mermaid-diagram mermaid-diagram-error ${className ?? ""}`} role="alert">
        <div class="mermaid-diagram-error-title">{t("ui.diagramRenderFailed")}</div>
        <div class="mermaid-diagram-error-body muted">{state.message}</div>
      </div>
    );
  }
  return (
    <div
      class={`mermaid-diagram ${className ?? ""}`}
      role="img"
      aria-label={ariaLabel ?? t("ui.mermaidDiagram")}
      ref={wrapperRef}
      // mermaid.render returns trusted, sanitized SVG string when
      // securityLevel: 'strict' is set at init (documented behaviour).
      // We render it via dangerouslySetInnerHTML so the outer container
      // is a plain div and the SVG's own viewport handles sizing.
      dangerouslySetInnerHTML={{ __html: state.svg }}
    />
  );
}
