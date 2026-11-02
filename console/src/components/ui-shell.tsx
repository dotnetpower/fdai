import type { ComponentChildren } from "preact";
import { useNavigationDomain, useNavigationExplorer } from "./navigation-title";

export interface PageHeaderProps {
  readonly title: string;
  readonly subtitle?: ComponentChildren;
  readonly actions?: ComponentChildren;
}

export function PageHeader({ title, subtitle, actions }: PageHeaderProps) {
  const domain = useNavigationDomain();
  const { explorerOpen, openExplorer } = useNavigationExplorer();
  const explorerTrigger = (label: string, className: string) => (
    <button
      type="button"
      class={className}
      aria-expanded={explorerOpen}
      aria-controls="navigation-explorer"
      onClick={openExplorer ?? undefined}
    >
      <span>{label}</span>
    </button>
  );
  return (
    <header class="page-header">
      <div class="page-header-text">
        <h2 class="page-header-title">
          {domain ? (
            <>
              {explorerTrigger(domain, "page-header-domain page-header-domain-trigger")}
              <span class="page-header-separator" aria-hidden="true">/</span>
            </>
          ) : null}
          {domain === null && openExplorer !== null
            ? explorerTrigger(title, "page-header-current page-header-domain-trigger")
            : <span>{title}</span>}
        </h2>
        {subtitle ? <p class="page-header-subtitle muted">{subtitle}</p> : null}
      </div>
      {actions ? <div class="page-header-actions">{actions}</div> : null}
    </header>
  );
}

export function ErrorState({
  message,
  onRetry,
  retryLabel,
}: {
  readonly message: string;
  readonly onRetry?: () => void;
  readonly retryLabel?: string;
}) {
  return (
    <div class="state-block state-error" role="alert">
      <span class="state-icon" aria-hidden="true">!</span>
      <span>{message}</span>
      {onRetry ? (
        <button type="button" class="btn" onClick={onRetry}>
          {retryLabel}
        </button>
      ) : null}
    </div>
  );
}
