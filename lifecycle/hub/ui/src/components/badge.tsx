import type { JSX } from "preact";
import type { Health, Outcome } from "../api";

type Variant = "ok" | "warn" | "fail" | "info" | "mute";

function Badge({ variant, children }: { variant: Variant; children: JSX.Element | string }) {
  return <span class={`badge ${variant}`}>{children}</span>;
}

const OUTCOME_LABELS: Record<Outcome, { label: string; variant: Variant }> = {
  issued: { label: "Plan open", variant: "info" },
  unchanged: { label: "Plan open", variant: "info" },
  waiting: { label: "Waiting", variant: "warn" },
  "up-to-date": { label: "Up to date", variant: "ok" },
  "no-eligible-release": { label: "No eligible release", variant: "mute" },
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

export function EnrollmentBadge({ status }: { status: string }) {
  if (status === "enrolled") return <Badge variant="ok">Enrolled</Badge>;
  if (status === "rejected") return <Badge variant="fail">Rejected</Badge>;
  return <Badge variant="warn">Pending</Badge>;
}
