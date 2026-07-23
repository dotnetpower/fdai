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
import { useTransientFlag } from "../hooks/use-transient-flag";
import { t } from "../i18n";
import { useNavigationDomain } from "./navigation-title";
import { Tooltip } from "./tooltip";

// ---------------------------------------------------------------------------
// PageHeader - page identity (title + optional subtitle + optional actions)
// ---------------------------------------------------------------------------

export interface PageHeaderProps {
  readonly title: string;
  readonly subtitle?: ComponentChildren;
  readonly actions?: ComponentChildren;
}

export function PageHeader({ title, subtitle, actions }: PageHeaderProps) {
  const domain = useNavigationDomain();
  return (
    <header class="page-header">
      <div class="page-header-text">
        <h2 class="page-header-title">
          {domain ? (
            <>
              <span class="page-header-domain">{domain}</span>
              <span class="page-header-separator" aria-hidden="true">/</span>
            </>
          ) : null}
          <span>{title}</span>
        </h2>
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
  /** Optional route-owned skeleton that preserves the final layout shape. */
  readonly loading?: ComponentChildren;
  /** Optional custom idle view; defaults to the ready renderer being skipped. */
  readonly idle?: ComponentChildren;
  readonly children: (data: T) => JSX.Element;
}

export function AsyncBoundary<T>({
  state,
  resourceLabel,
  loading,
  idle,
  children,
}: AsyncBoundaryProps<T>) {
  if (state.status === "idle") {
    return <>{idle ?? null}</>;
  }
  if (state.status === "loading") {
    return <>{loading ?? <LoadingState label={t("shared.loadingResource", { resource: resourceLabel })} />}</>;
  }
  if (state.status === "unavailable") {
    return <UnavailableState message={state.message} />;
  }
  if (state.status === "error") {
    return (
      <ErrorState
        message={t("shared.loadFailed", { resource: resourceLabel, message: state.message })}
      />
    );
  }
  return children(state.data);
}

// ---------------------------------------------------------------------------
// LoadingState / ErrorState / EmptyState / UnavailableState
// ---------------------------------------------------------------------------

export function LoadingState({ label = t("shared.loading") }: { readonly label?: string }) {
  return (
    <div class="loading-skeleton" role="status" aria-live="polite" aria-busy="true">
      <span class="sr-only">{label}</span>
      <div class="loading-skeleton-layout" aria-hidden="true">
        <span class="skeleton-shimmer loading-skeleton-heading" />
        <span class="skeleton-shimmer loading-skeleton-line" />
        <div class="loading-skeleton-cards">
          <span class="skeleton-shimmer" />
          <span class="skeleton-shimmer" />
          <span class="skeleton-shimmer" />
        </div>
        <span class="skeleton-shimmer loading-skeleton-panel" />
      </div>
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
      <span class="state-icon" aria-hidden="true">-</span>
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
  readonly href: string;
  readonly label: string;
  readonly value: ComponentChildren;
  readonly hint?: ComponentChildren;
  readonly tone?: "default" | "positive" | "warning" | "danger";
}

export function KpiCard({ href, label, value, hint, tone = "default" }: KpiCardProps) {
  return (
    <a class={`card kpi-card kpi-tone-${tone}`} href={href}>
      <span class="kpi-card-label">{label}</span>
      <span class="kpi-card-value">{value}</span>
      {hint ? <span class="kpi-card-hint muted">{hint}</span> : null}
    </a>
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
  /** Plain-text label shown beside a cell in responsive row layouts. */
  readonly mobileLabel?: string;
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
  /** Accessible label for an explicit first-cell selection button. */
  readonly rowActionLabel?: (row: Row, index: number) => string;
  /** Element controlled by the selection button. */
  readonly rowActionControls?: string;
}

export function mobileColumnLabel<Row>(column: Column<Row>): string {
  if (column.mobileLabel?.trim()) return column.mobileLabel;
  if (typeof column.header === "string" && column.header.trim()) return column.header;
  return column.key;
}

export function DataTable<Row>({
  columns,
  rows,
  keyOf,
  empty,
  caption,
  onRowClick,
  isRowActive,
  rowActionLabel,
  rowActionControls,
}: DataTableProps<Row>) {
  if (rows.length === 0) {
    return (
      <div class="data-table-empty muted" role="status" aria-live="polite">
        {empty ?? t("shared.noRows")}
      </div>
    );
  }
  const clickable = onRowClick !== undefined;
  const explicitAction = clickable && rowActionLabel !== undefined;
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
                aria-selected={explicitAction ? active : undefined}
                tabIndex={clickable && !explicitAction ? 0 : undefined}
                role={clickable && !explicitAction ? "button" : undefined}
                onClick={clickable && !explicitAction ? () => onRowClick?.(row, index) : undefined}
                onKeyDown={
                  clickable && !explicitAction
                    ? (e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          onRowClick?.(row, index);
                        }
                      }
                    : undefined
                }
              >
                {columns.map((c, columnIndex) => (
                  <td key={c.key} class={c.cellClass} data-label={mobileColumnLabel(c)}>
                    {explicitAction && columnIndex === 0 ? (
                      <button
                        type="button"
                        class="data-table-row-action"
                        aria-pressed={active}
                        aria-controls={rowActionControls}
                        onClick={() => onRowClick?.(row, index)}
                      >
                        <span>{c.render(row)}</span>
                        <span class="sr-only">{rowActionLabel(row, index)}</span>
                      </button>
                    ) : c.render(row)}
                  </td>
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
    <Tooltip content={title}>
      <span class={`status-pill status-pill-${kind}`}>{label}</span>
    </Tooltip>
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
 * Reject anything that is not an absolute http(s) URL. ``href`` values on
 * this component often originate on the read-API wire (rule provenance
 * ``source_url``, generated PR links, etc.); a ``javascript:``, ``data:``,
 * or ``vbscript:`` URI would execute on click (DOM-based XSS, OWASP A03).
 * Same guarantee as :func:`safeHttpUrl` in the provision route. Exported
 * for unit-testing the trust boundary.
 */
export function safeExternalHref(href: string): string | null {
  if (!href) return null;
  try {
    const parsed = new URL(href);
    return parsed.protocol === "http:" || parsed.protocol === "https:"
      ? parsed.href
      : null;
  } catch {
    return null;
  }
}

/**
 * Anchor that always opens in a new tab. Carries ``rel="noopener
 * noreferrer"`` (no tab-nabbing, no referrer leak), a visible
 * open-in-new glyph, and a screen-reader-only "(opens in a new tab)"
 * suffix so the behaviour is announced, not just implied. An unsafe
 * ``href`` (any non-http(s) scheme) degrades to plain text so a bad
 * value cannot execute on click.
 */
export function ExternalLink({ href, children }: ExternalLinkProps) {
  const safe = safeExternalHref(href);
  if (safe === null) {
    return <span class="ext-link ext-link--unsafe">{children}</span>;
  }
  return (
    <Tooltip content={t("tooltip.opensNewTab")}>
      <a
        class="ext-link"
        href={safe}
        target="_blank"
        rel="noopener noreferrer"
      >
        <span class="ext-link-text">{children}</span>
        <ExternalGlyph />
        <span class="sr-only"> ({t("tooltip.opensNewTab")})</span>
      </a>
    </Tooltip>
  );
}

// ---------------------------------------------------------------------------
// CopyButton - copy text to clipboard with transient feedback
// ---------------------------------------------------------------------------

export interface CopyButtonProps {
  readonly text: string;
  readonly label?: string;
}

export function CopyButton({ text, label = t("shared.copy") }: CopyButtonProps) {
  const [copied, showCopied] = useTransientFlag(1500);
  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(text);
      showCopied();
    } catch {
      /* clipboard unavailable (insecure context) - stay silent */
    }
  }
  return (
    <button
      type="button"
      class="btn btn-small copy-btn"
      onClick={copy}
      aria-label={copied ? t("shared.copied") : label}
    >
      {copied ? t("shared.copied") : label}
    </button>
  );
}
