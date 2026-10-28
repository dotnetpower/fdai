import type { JSX } from "preact";
import type { Health, Outcome } from "../api";

type Variant = "ok" | "warn" | "fail" | "info" | "mute";

// A leading glyph repeats the status in shape, not only in color, matching the ✓/✕/◷ vocabulary
// already used for constraint and report rows elsewhere in this app. "info" and "mute" carry no
// judgment (open/inactive, not good or bad), so they stay textual.
const VARIANT_GLYPH: Partial<Record<Variant, string>> = {
  ok: "✓",
  warn: "●",
  fail: "✕",
};

export function Badge({ variant, children }: { variant: Variant; children: JSX.Element | string }) {
  const glyph = VARIANT_GLYPH[variant];
  return (
    <span class={`badge ${variant}`}>
      {glyph && (
        <span class="badge-glyph" aria-hidden="true">
          {glyph}
        </span>
      )}
      {children}
    </span>
  );
}

const OUTCOME_LABELS: Record<Outcome, { label: string; variant: Variant }> = {
  issued: { label: "Plan issued", variant: "info" },
  unchanged: { label: "Plan unchanged", variant: "info" },
  waiting: { label: "Waiting", variant: "warn" },
  "up-to-date": { label: "Up to date", variant: "ok" },
  "no-eligible-release": { label: "No eligible release", variant: "warn" },
  "no-managed-entity": { label: "No managed Entity", variant: "mute" },
};

export function OutcomeBadge({ outcome }: { outcome: Outcome | null }) {
  if (outcome === null) return <Badge variant="mute">Not yet evaluated</Badge>;
  const { label, variant } = OUTCOME_LABELS[outcome];
  return <Badge variant={variant}>{label}</Badge>;
}

const HEALTH_LABELS: Record<Health, { label: string; variant: Variant }> = {
  healthy: { label: "Healthy", variant: "ok" },
  degraded: { label: "Degraded", variant: "warn" },
  unhealthy: { label: "Unhealthy", variant: "fail" },
  unknown: { label: "Unknown", variant: "mute" },
};

export function HealthBadge({ health }: { health: Health | null }) {
  if (health === null) return <Badge variant="mute">No managed Entity</Badge>;
  const { label, variant } = HEALTH_LABELS[health];
  return <Badge variant={variant}>{label}</Badge>;
}
