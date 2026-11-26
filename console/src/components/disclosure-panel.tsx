import type { ComponentChildren } from "preact";

export interface DisclosurePanelProps {
  readonly title: ComponentChildren;
  readonly summaryMeta?: ComponentChildren;
  readonly badge?: ComponentChildren;
  readonly open?: boolean;
  readonly defaultOpen?: boolean;
  readonly onToggle?: (open: boolean) => void;
  readonly tone?: "default" | "subtle";
  readonly className?: string;
  readonly children: ComponentChildren;
}

export function DisclosurePanel({
  title,
  summaryMeta,
  badge,
  open,
  defaultOpen,
  onToggle,
  tone = "default",
  className,
  children,
}: DisclosurePanelProps) {
  const classes = [
    "cs-disclosure",
    tone === "subtle" ? "cs-disclosure--subtle" : "",
    className ?? "",
  ].filter(Boolean).join(" ");

  return (
    <details
      class={classes}
      open={open ?? defaultOpen}
      onToggle={(event) => {
        if (onToggle) {
          onToggle((event.currentTarget as HTMLDetailsElement).open);
        }
      }}
    >
      <summary class="cs-disclosure-summary">
        <svg
          class="cs-disclosure-chevron"
          viewBox="0 0 12 12"
          fill="none"
          stroke="currentColor"
          stroke-width="1.6"
          stroke-linecap="round"
          stroke-linejoin="round"
          aria-hidden="true"
        >
          <path d="M4.2 2.5L7.8 6L4.2 9.5" />
        </svg>
        <span>{title}</span>
        {(summaryMeta || badge) ? (
          <span class="cs-disclosure-meta">
            {summaryMeta}
            {badge}
          </span>
        ) : null}
      </summary>
      <div class="cs-disclosure-body">{children}</div>
    </details>
  );
}
