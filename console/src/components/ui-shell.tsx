import type { ComponentChildren } from "preact";
import { t } from "../i18n";
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

const TRANSPORT_FAILURE_TAIL =
  /^(.*?)(?::\s*)?(failed to fetch|networkerror when attempting to fetch resource\.?|load failed|network request failed)\s*$/i;

/** Split a composed "<what failed>: <browser transport error>" message into title and detail. */
export function describeLoadFailure(message: string): {
  readonly title: string;
  readonly detail?: string;
} {
  const match = TRANSPORT_FAILURE_TAIL.exec(message.trim());
  if (!match) return { title: message };
  const title = (match[1] ?? "").trim();
  return {
    title: title === "" ? t("shared.sourceUnreachableTitle") : title,
    detail: t("shared.sourceUnreachable"),
  };
}

export function ErrorState({
  message,
  detail,
  onRetry,
  retryLabel,
}: {
  readonly message: string;
  readonly detail?: string;
  readonly onRetry?: () => void;
  readonly retryLabel?: string;
}) {
  const described = detail === undefined ? describeLoadFailure(message) : { title: message, detail };
  return (
    <div class="state-block state-error" role="alert">
      <span class="state-icon" aria-hidden="true">!</span>
      <div class="state-body">
        <span class="state-title">{described.title}</span>
        {described.detail ? <span class="state-detail">{described.detail}</span> : null}
      </div>
      {onRetry ? (
        <button type="button" class="btn" onClick={onRetry}>
          {retryLabel ?? t("shared.retry")}
        </button>
      ) : null}
    </div>
  );
}
