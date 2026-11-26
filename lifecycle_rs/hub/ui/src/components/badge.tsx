import type { JSX } from "preact";
import type { Health, Outcome } from "../api";
import { tr, useHubLocale } from "../locale";

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

const OUTCOME_LABELS: Record<Outcome, { label: string; labelKo: string; variant: Variant }> = {
  issued: { label: "Plan issued", labelKo: "계획 발급됨", variant: "info" },
  unchanged: { label: "Plan unchanged", labelKo: "계획 변경 없음", variant: "info" },
  waiting: { label: "Waiting", labelKo: "대기 중", variant: "warn" },
  "up-to-date": { label: "Up to date", labelKo: "최신 상태", variant: "ok" },
  "no-eligible-release": { label: "No eligible release", labelKo: "적격 릴리스 없음", variant: "warn" },
  "no-managed-entity": { label: "No managed Entity", labelKo: "관리 대상 엔티티 없음", variant: "mute" },
};

export function OutcomeBadge({ outcome }: { outcome: Outcome | null }) {
  const [locale] = useHubLocale();
  if (outcome === null) return <Badge variant="mute">{tr(locale, "Not yet evaluated", "미평가")}</Badge>;
  const { label, labelKo, variant } = OUTCOME_LABELS[outcome];
  return <Badge variant={variant}>{tr(locale, label, labelKo)}</Badge>;
}

const HEALTH_LABELS: Record<Health, { label: string; labelKo: string; variant: Variant }> = {
  healthy: { label: "Healthy", labelKo: "정상", variant: "ok" },
  degraded: { label: "Degraded", labelKo: "저하됨", variant: "warn" },
  unhealthy: { label: "Unhealthy", labelKo: "비정상", variant: "fail" },
  unknown: { label: "Unknown", labelKo: "알 수 없음", variant: "mute" },
};

export function HealthBadge({ health }: { health: Health | null }) {
  const [locale] = useHubLocale();
  if (health === null) return <Badge variant="mute">{tr(locale, "No managed Entity", "관리 대상 엔티티 없음")}</Badge>;
  const { label, labelKo, variant } = HEALTH_LABELS[health];
  return <Badge variant={variant}>{tr(locale, label, labelKo)}</Badge>;
}
