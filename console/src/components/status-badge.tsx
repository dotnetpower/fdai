import type { ComponentChildren } from "preact";
import { Tooltip } from "./tooltip";

export type BadgeTone =
  | "live"
  | "sre"
  | "sec"
  | "human"
  | "neutral"
  | "info"
  | "success"
  | "warning"
  | "danger";

export interface StatusBadgeProps {
  readonly tone: BadgeTone;
  readonly label: ComponentChildren;
  readonly title?: string;
  readonly noDot?: boolean;
  readonly className?: string;
}

export function StatusBadge({
  tone,
  label,
  title,
  noDot = false,
  className,
}: StatusBadgeProps) {
  const classes = [
    "cs-status-badge",
    `cs-status-badge--${tone}`,
    className ?? "",
  ].filter(Boolean).join(" ");

  return (
    <Tooltip content={title}>
      <span class={classes}>
        {noDot ? null : <span class="cs-status-dot" aria-hidden="true" />}
        <span>{label}</span>
      </span>
    </Tooltip>
  );
}

export type PromotionStage =
  | "shadow"
  | "ready"
  | "blocked"
  | "enforce"
  | "override"
  | "recall";

const PROMOTION_TONE: Record<PromotionStage, BadgeTone> = {
  shadow: "neutral",
  ready: "info",
  blocked: "sec",
  enforce: "live",
  override: "human",
  recall: "sre",
};

const PROMOTION_DEFAULT_LABEL: Record<PromotionStage, string> = {
  shadow: "Shadow",
  ready: "Ready",
  blocked: "Blocked",
  enforce: "Enforce",
  override: "Operator Override",
  recall: "Capability Recall",
};

export interface PromotionReadinessBadgeProps {
  readonly stage: PromotionStage;
  readonly label?: string;
  readonly title?: string;
}

export function PromotionReadinessBadge({
  stage,
  label,
  title,
}: PromotionReadinessBadgeProps) {
  return (
    <StatusBadge
      tone={PROMOTION_TONE[stage]}
      label={label ?? PROMOTION_DEFAULT_LABEL[stage]}
      {...(title !== undefined ? { title } : {})}
    />
  );
}
