import type { ComponentChildren } from "preact";
import { StatusBadge, type BadgeTone } from "./status-badge";
import { CopyButton } from "./ui";
import "./capability-detail-drawer.css";

export interface CapabilityDrawerStateItem {
  readonly label: string;
  readonly tone: BadgeTone;
  readonly value: string;
}

export interface CapabilityDrawerFact {
  readonly label: string;
  readonly value: ComponentChildren;
}

export interface CapabilityDrawerLink {
  readonly href: string;
  readonly label: string;
}

export interface CapabilityDetailDrawerProps {
  readonly id?: string;
  readonly heading: string;
  readonly kicker?: string;
  readonly identifier?: string;
  readonly copyIdentifierLabel?: string;
  readonly summary?: string;
  readonly statusTone?: BadgeTone;
  readonly statusLabel?: string;
  readonly ariaLabel?: string;
  readonly onClose?: () => void;
  readonly closeLabel?: string;
  readonly stateGridLabel?: string;
  readonly stateBadges?: readonly CapabilityDrawerStateItem[];
  readonly facts: readonly CapabilityDrawerFact[];
  readonly links?: readonly CapabilityDrawerLink[];
  readonly provenance?: ComponentChildren;
  readonly className?: string;
}

export function CapabilityDetailDrawer({
  id,
  heading,
  kicker,
  identifier,
  copyIdentifierLabel,
  summary,
  statusTone,
  statusLabel,
  ariaLabel,
  onClose,
  closeLabel = "Close",
  stateGridLabel,
  stateBadges,
  facts,
  links,
  provenance,
  className,
}: CapabilityDetailDrawerProps) {
  return (
    <aside
      id={id}
      class={className ? `cs-cap-drawer ${className}` : "cs-cap-drawer"}
      aria-label={ariaLabel ?? heading}
    >
      <header class="cs-cap-drawer-head">
        <div class="cs-cap-drawer-heading">
          {kicker ? <span class="cs-cap-drawer-kicker">{kicker}</span> : null}
          <h3 class="cs-cap-drawer-title">{heading}</h3>
          {identifier ? <code class="cs-cap-drawer-id">{identifier}</code> : null}
        </div>
        <div class="cs-cap-drawer-actions">
          {statusLabel && statusTone ? (
            <StatusBadge tone={statusTone} label={statusLabel} />
          ) : null}
          {identifier ? (
            copyIdentifierLabel !== undefined ? (
              <CopyButton text={identifier} label={copyIdentifierLabel} />
            ) : (
              <CopyButton text={identifier} />
            )
          ) : null}
          {onClose ? (
            <button
              type="button"
              class="cs-control-button"
              onClick={onClose}
            >
              {closeLabel}
            </button>
          ) : null}
        </div>
      </header>

      {summary ? <p class="cs-cap-drawer-summary">{summary}</p> : null}

      {stateBadges && stateBadges.length > 0 ? (
        <div class="cs-cap-drawer-states" aria-label={stateGridLabel}>
          {stateBadges.map((item) => (
            <div key={item.label} class="cs-cap-drawer-state-row">
              <span class="cs-cap-drawer-state-label">{item.label}</span>
              <StatusBadge tone={item.tone} label={item.value} />
            </div>
          ))}
        </div>
      ) : null}

      <dl class="cs-cap-drawer-facts">
        {facts.map((fact) => (
          <div key={fact.label}>
            <dt>{fact.label}</dt>
            <dd>{fact.value}</dd>
          </div>
        ))}
      </dl>

      {links && links.length > 0 ? (
        <div class="cs-cap-drawer-links">
          {links.map((link) => (
            <a key={`${link.href}:${link.label}`} href={link.href}>
              {link.label}
            </a>
          ))}
        </div>
      ) : null}

      {provenance ? (
        <div class="cs-cap-drawer-provenance">{provenance}</div>
      ) : null}
    </aside>
  );
}
