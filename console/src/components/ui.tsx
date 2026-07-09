/**
 * Shared UI primitives for panel routes.
 *
 * Each component here has ONE responsibility so panel modules can stay
 * focused on data-fetching + composition. The primitives are read-only:
 * they never issue privileged calls, matching the console contract in
 * app-shape.instructions.md § Operator console.
 */

import type { ComponentChildren, JSX } from "preact";
import { useState } from "preact/hooks";

// ---------------------------------------------------------------------------
// PageHeader - page identity (title + optional subtitle + optional actions)
// ---------------------------------------------------------------------------

export interface PageHeaderProps {
  readonly title: string;
  readonly subtitle?: ComponentChildren;
  readonly actions?: ComponentChildren;
}

export function PageHeader({ title, subtitle, actions }: PageHeaderProps) {
  return (
    <header class="page-header">
      <div class="page-header-text">
        <h2 class="page-header-title">{title}</h2>
        {subtitle ? <p class="page-header-subtitle muted">{subtitle}</p> : null}
      </div>
      {actions ? <div class="page-header-actions">{actions}</div> : null}
    </header>
  );
}

// ---------------------------------------------------------------------------
// AsyncBoundary - render loading / error / ready in a single primitive
// ---------------------------------------------------------------------------

export type AsyncState<T> =
  | { readonly status: "idle" }
  | { readonly status: "loading" }
  | { readonly status: "ready"; readonly data: T }
  | { readonly status: "unavailable"; readonly message: string }
  | { readonly status: "error"; readonly message: string };

export interface AsyncBoundaryProps<T> {
  readonly state: AsyncState<T>;
  /** Label describing what is loading, e.g. "audit log". */
  readonly resourceLabel: string;
  /** Optional custom idle view; defaults to the ready renderer being skipped. */
  readonly idle?: ComponentChildren;
  readonly children: (data: T) => JSX.Element;
}

export function AsyncBoundary<T>({
  state,
  resourceLabel,
  idle,
  children,
}: AsyncBoundaryProps<T>) {
  if (state.status === "idle") {
    return <>{idle ?? null}</>;
  }
  if (state.status === "loading") {
    return <LoadingState label={`Loading ${resourceLabel}...`} />;
  }
  if (state.status === "unavailable") {
    return <UnavailableState message={state.message} />;
  }
  if (state.status === "error") {
    return (
      <ErrorState
        message={`Failed to load ${resourceLabel}: ${state.message}`}
      />
    );
  }
  return children(state.data);
}

// ---------------------------------------------------------------------------
// LoadingState / ErrorState / EmptyState / UnavailableState
// ---------------------------------------------------------------------------

export function LoadingState({ label = "Loading..." }: { readonly label?: string }) {
  return (
    <div class="state-block state-loading" role="status" aria-live="polite">
      <span class="state-spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}

export function ErrorState({ message }: { readonly message: string }) {
  return (
    <div class="state-block state-error" role="alert">
      <span class="state-icon" aria-hidden="true">!</span>
      <span>{message}</span>
    </div>
  );
}

export interface EmptyStateProps {
  readonly title: string;
  readonly body?: ComponentChildren;
}

export function EmptyState({ title, body }: EmptyStateProps) {
  return (
    <div class="state-block state-empty">
      <span class="state-icon" aria-hidden="true">–</span>
      <div>
        <div class="state-empty-title">{title}</div>
        {body ? <div class="state-empty-body muted">{body}</div> : null}
      </div>
    </div>
  );
}

export function UnavailableState({ message }: { readonly message: string }) {
  return (
    <div class="state-block state-unavailable">
      <span class="state-icon" aria-hidden="true">?</span>
      <span>{message}</span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// KpiCard / KpiGrid - single-metric display, horizontal layout
// ---------------------------------------------------------------------------

export interface KpiCardProps {
  readonly label: string;
  readonly value: ComponentChildren;
  readonly hint?: ComponentChildren;
  readonly tone?: "default" | "positive" | "warning" | "danger";
}

export function KpiCard({ label, value, hint, tone = "default" }: KpiCardProps) {
  return (
    <div class={`card kpi-card kpi-tone-${tone}`}>
      <span class="kpi-card-label">{label}</span>
      <span class="kpi-card-value">{value}</span>
      {hint ? <span class="kpi-card-hint muted">{hint}</span> : null}
    </div>
  );
}

export function KpiGrid({ children }: { readonly children: ComponentChildren }) {
  return <section class="kpi-grid">{children}</section>;
}

// ---------------------------------------------------------------------------
// DataTable - tabular render + key management
// ---------------------------------------------------------------------------

export interface Column<Row> {
  readonly key: string;
  readonly header: ComponentChildren;
  readonly render: (row: Row) => ComponentChildren;
  /** CSS class applied to the cell, e.g. `"mono"`, `"num"`. */
  readonly cellClass?: string;
  /** CSS class applied to the header cell. */
  readonly headerClass?: string;
}

export interface DataTableProps<Row> {
  readonly columns: readonly Column<Row>[];
  readonly rows: readonly Row[];
  readonly keyOf: (row: Row, index: number) => string | number;
  readonly empty?: ComponentChildren;
  readonly caption?: ComponentChildren;
  /** When set, rows become clickable (button semantics + keyboard). */
  readonly onRowClick?: (row: Row, index: number) => void;
  /** Highlight the row matching this predicate as selected. */
  readonly isRowActive?: (row: Row, index: number) => boolean;
}

export function DataTable<Row>({
  columns,
  rows,
  keyOf,
  empty,
  caption,
  onRowClick,
  isRowActive,
}: DataTableProps<Row>) {
  if (rows.length === 0) {
    return (
      <div class="data-table-empty muted">{empty ?? "No rows to display."}</div>
    );
  }
  const clickable = onRowClick !== undefined;
  return (
    <div class="data-table-wrap">
      <table class={`data-table${clickable ? " data-table-clickable" : ""}`}>
        {caption ? <caption>{caption}</caption> : null}
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} class={c.headerClass}>{c.header}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const active = isRowActive?.(row, index) ?? false;
            return (
              <tr
                key={keyOf(row, index)}
                class={active ? "row-active" : undefined}
                tabIndex={clickable ? 0 : undefined}
                role={clickable ? "button" : undefined}
                onClick={clickable ? () => onRowClick?.(row, index) : undefined}
                onKeyDown={
                  clickable
                    ? (e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          onRowClick?.(row, index);
                        }
                      }
                    : undefined
                }
              >
                {columns.map((c) => (
                  <td key={c.key} class={c.cellClass}>{c.render(row)}</td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------
// StatusPill - colored status chip
// ---------------------------------------------------------------------------

export type PillKind =
  | "neutral"
  | "info"
  | "success"
  | "warning"
  | "danger"
  | "shadow"
  | "enforce"
  | "hil"
  | "auto";

export interface StatusPillProps {
  readonly kind: PillKind;
  readonly label: ComponentChildren;
  readonly title?: string;
}

export function StatusPill({ kind, label, title }: StatusPillProps) {
  return (
    <span class={`status-pill status-pill-${kind}`} title={title}>
      {label}
    </span>
  );
}

// ---------------------------------------------------------------------------
// ExternalLink - opens in a new tab, with an explicit affordance
// ---------------------------------------------------------------------------

/** Box-with-arrow glyph signalling "opens in a new tab". */
function ExternalGlyph() {
  return (
    <svg
      class="ext-icon"
      width="12"
      height="12"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <path d="M14 3h7v7" />
      <path d="M21 3l-9 9" />
      <path d="M19 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h6" />
    </svg>
  );
}

export interface ExternalLinkProps {
  readonly href: string;
  readonly children: ComponentChildren;
}

/**
 * Anchor that always opens in a new tab. Carries ``rel="noopener
 * noreferrer"`` (no tab-nabbing, no referrer leak), a visible
 * open-in-new glyph, and a screen-reader-only "(opens in a new tab)"
 * suffix so the behaviour is announced, not just implied.
 */
export function ExternalLink({ href, children }: ExternalLinkProps) {
  return (
    <a
      class="ext-link"
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      title="Opens in a new tab"
    >
      <span class="ext-link-text">{children}</span>
      <ExternalGlyph />
      <span class="sr-only"> (opens in a new tab)</span>
    </a>
  );
}

// ---------------------------------------------------------------------------
// CopyButton - copy text to clipboard with transient feedback
// ---------------------------------------------------------------------------

export interface CopyButtonProps {
  readonly text: string;
  readonly label?: string;
}

export function CopyButton({ text, label = "Copy" }: CopyButtonProps) {
  const [copied, setCopied] = useState(false);
  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1500);
    } catch {
      /* clipboard unavailable (insecure context) - stay silent */
    }
  }
  return (
    <button
      type="button"
      class="btn btn-small copy-btn"
      onClick={copy}
      aria-label={copied ? "Copied" : label}
    >
      {copied ? "Copied" : label}
    </button>
  );
}
