import type { ComponentChildren } from "preact";
import { Tooltip } from "./tooltip";
import { CopyButton } from "./ui";
import { StatusBadge, type BadgeTone } from "./status-badge";

export interface ProposalFact {
  readonly label: string;
  readonly value: ComponentChildren;
}

export interface ActionProposalCardProps {
  readonly title: string;
  readonly statusTone: BadgeTone;
  readonly statusLabel: string;
  readonly authorityLabel?: string;
  readonly authorityTone?: BadgeTone;
  readonly evidenceFacts: readonly ProposalFact[];
  readonly authorityNotice?: string;
  readonly technicalDetails?: ComponentChildren;
  readonly proposalSlot?: ComponentChildren;
  readonly className?: string;
}

export function ActionProposalCard({
  title,
  statusTone,
  statusLabel,
  authorityLabel,
  authorityTone = "neutral",
  evidenceFacts,
  authorityNotice,
  technicalDetails,
  proposalSlot,
  className,
}: ActionProposalCardProps) {
  return (
    <article class={className ? `cs-proposal-panel ${className}` : "cs-proposal-panel"}>
      <div class="cs-proposal-readonly">
        <div class="cs-proposal-head">
          <h3 class="cs-proposal-title">{title}</h3>
          <div class="cs-proposal-badges">
            <StatusBadge tone={statusTone} label={statusLabel} />
            {authorityLabel ? (
              <StatusBadge tone={authorityTone} label={authorityLabel} />
            ) : null}
          </div>
        </div>
        <dl class="cs-proposal-facts">
          {evidenceFacts.map((fact) => (
            <div key={fact.label}>
              <dt>{fact.label}</dt>
              <dd>{fact.value}</dd>
            </div>
          ))}
        </dl>
        {technicalDetails}
      </div>
      {(authorityNotice || proposalSlot) ? (
        <div class="cs-proposal-boundary">
          {authorityNotice ? <p class="cs-proposal-authority-note">{authorityNotice}</p> : null}
          {proposalSlot}
        </div>
      ) : null}
    </article>
  );
}

export type HashChainStatus = "verified" | "gap" | "unverified" | "unavailable";

const HASH_TONE: Record<HashChainStatus, BadgeTone> = {
  verified: "live",
  gap: "sec",
  unverified: "sre",
  unavailable: "neutral",
};

const HASH_DEFAULT_LABEL: Record<HashChainStatus, string> = {
  verified: "Verified",
  gap: "Gap detected",
  unverified: "Unverified",
  unavailable: "Unavailable",
};

export interface HashChainBadgeProps {
  readonly status: HashChainStatus;
  readonly label?: string;
  readonly entryHash?: string;
  readonly copyLabel?: string;
}

export function HashChainBadge({
  status,
  label,
  entryHash,
  copyLabel,
}: HashChainBadgeProps) {
  const shortHash = entryHash && entryHash.length > 16
    ? `${entryHash.slice(0, 12)}...${entryHash.slice(-4)}`
    : entryHash;

  return (
    <span class="cs-hash-badge-group">
      <StatusBadge tone={HASH_TONE[status]} label={label ?? HASH_DEFAULT_LABEL[status]} />
      {entryHash ? (
        <>
          <Tooltip content={entryHash}>
            <code class="cs-hash-digest">{shortHash}</code>
          </Tooltip>
          {copyLabel !== undefined ? (
            <CopyButton text={entryHash} label={copyLabel} />
          ) : (
            <CopyButton text={entryHash} />
          )}
        </>
      ) : null}
    </span>
  );
}

export interface CorrelationStepItem {
  readonly id: string;
  readonly title: string;
  readonly stateLabel: string;
  readonly tone: BadgeTone;
  readonly timestamp?: string;
  readonly detail?: ComponentChildren;
  readonly current?: boolean;
}

export interface CorrelationTimelineProps {
  readonly variant?: "lifecycle" | "causal" | "phases";
  readonly ariaLabel: string;
  readonly items: readonly CorrelationStepItem[];
}

export function CorrelationTimeline({
  variant = "lifecycle",
  ariaLabel,
  items,
}: CorrelationTimelineProps) {
  const classes = variant === "phases"
    ? "cs-corr-timeline cs-corr-timeline--phases"
    : "cs-corr-timeline";

  return (
    <ol class={classes} aria-label={ariaLabel}>
      {items.map((item) => (
        <li
          key={item.id}
          class="cs-corr-step"
          aria-current={item.current ? "step" : undefined}
        >
          <div class="cs-corr-step-head">
            <span>{item.title}</span>
            <StatusBadge tone={item.tone} label={item.stateLabel} />
          </div>
          {item.timestamp ? <span class="cs-corr-step-meta">{item.timestamp}</span> : null}
          {item.detail ? <div class="cs-corr-step-meta">{item.detail}</div> : null}
        </li>
      ))}
    </ol>
  );
}

export interface KnowledgeSourceCardProps {
  readonly title: string;
  readonly statusTone: BadgeTone;
  readonly statusLabel: string;
  readonly freshness?: string;
  readonly sourceKind?: string;
  readonly summary?: ComponentChildren;
  readonly actions?: ComponentChildren;
}

export function KnowledgeSourceCard({
  title,
  statusTone,
  statusLabel,
  freshness,
  sourceKind,
  summary,
  actions,
}: KnowledgeSourceCardProps) {
  return (
    <article class="cs-knowledge-panel">
      <div class="cs-knowledge-head">
        <h3 class="cs-knowledge-title">{title}</h3>
        <StatusBadge tone={statusTone} label={statusLabel} />
      </div>
      {summary ? <div>{summary}</div> : null}
      {(freshness || sourceKind || actions) ? (
        <div class="cs-knowledge-meta">
          {sourceKind ? <span>{sourceKind}</span> : null}
          {freshness ? <span>{freshness}</span> : null}
          {actions}
        </div>
      ) : null}
    </article>
  );
}

export interface TimelineStepEntry {
  readonly id: string;
  readonly timestamp: string;
  readonly actor: string;
  readonly summary: string;
  readonly statusTone: BadgeTone;
  readonly statusLabel: string;
  readonly correlationId?: string;
}

export interface TimelineStepListProps {
  readonly ariaLabel: string;
  readonly entries: readonly TimelineStepEntry[];
}

export function TimelineStepList({ ariaLabel, entries }: TimelineStepListProps) {
  return (
    <ol class="cs-step-list" aria-label={ariaLabel}>
      {entries.map((entry) => (
        <li key={entry.id} class="cs-step-row">
          <span class="cs-step-time">{entry.timestamp}</span>
          <div class="cs-step-body">
            <span class="cs-step-actor">{entry.actor}</span>
            <p class="cs-step-summary">{entry.summary}</p>
            {entry.correlationId ? (
              <span class="cs-hash-badge-group">
                <code class="cs-hash-digest">{entry.correlationId}</code>
                <CopyButton text={entry.correlationId} />
              </span>
            ) : null}
          </div>
          <StatusBadge tone={entry.statusTone} label={entry.statusLabel} />
        </li>
      ))}
    </ol>
  );
}

export type ConversationRole = "operator" | "assistant" | "tool" | "system";

export interface ConversationTurnItemProps {
  readonly role: ConversationRole;
  readonly authorLabel: string;
  readonly timestamp?: string;
  readonly content: ComponentChildren;
  readonly footer?: ComponentChildren;
}

export function ConversationTurnItem({
  role,
  authorLabel,
  timestamp,
  content,
  footer,
}: ConversationTurnItemProps) {
  return (
    <div class={`cs-conv-turn cs-conv-turn--${role}`} data-turn-role={role}>
      <div class="cs-conv-meta">
        <strong>{authorLabel}</strong>
        {timestamp ? <span>{timestamp}</span> : null}
      </div>
      <div class="cs-conv-body">{content}</div>
      {footer}
    </div>
  );
}
