import { t } from "../i18n";
import type { BackendHealth, RouterCandidate, RouterSnapshot } from "./backend-types";

type MeasurementStatus = "measured" | "unmeasured" | "failed" | "stale" | "unknown";

interface BackendTooltipCandidateView {
  readonly deployment: string;
  readonly p50: string;
  readonly p95: string;
  readonly samples: number;
  readonly selected: boolean;
  readonly status: string;
}

/** Sanitized health display; absent freshness never becomes measured speed. */
export interface BackendTooltipView {
  readonly mode: string;
  readonly model: string | null;
  readonly endpoint: string | null;
  readonly router: {
    readonly deployment: string;
    readonly reason: string;
    readonly updatedAt?: string;
    readonly expiresAt?: string;
    readonly intervalSeconds?: number;
    readonly candidates: readonly BackendTooltipCandidateView[];
  } | null;
  readonly visionRouter?: {
    readonly deployment: string;
    readonly candidates: readonly BackendTooltipCandidateView[];
  };
}

/** Preserves legacy/configured identity, but never claims an expired next-turn selection. */
export function backendModel(health: BackendHealth, now = Date.now()): string | null {
  if (!health.available) return null;
  const router = health.router;
  const expires = Date.parse(router?.expires_at ?? "");
  if (Number.isFinite(expires) && expires <= now) return null;
  const updated = Date.parse(router?.updated_at ?? "");
  if (router?.reason === "latency" && Number.isFinite(updated) &&
    Number.isFinite(expires) && expires > updated) {
    const selected = router.candidates.find((candidate) => candidate.deployment === router.chose);
    const measured = Date.parse(selected?.measured_at ?? "");
    if (selected?.status === "stale" ||
      (Number.isFinite(measured) && measured + expires - updated <= now)) return null;
  }
  return router?.chose.trim() || health.model?.trim() || null;
}

/** Preserves probing/unavailable labels and never invents a model for older health payloads. */
export function backendBadgeLabel(health: BackendHealth | null, now = Date.now()): string {
  if (!health) return t("deck.backend.probing");
  if (!health.available) return t("deck.backend.deterministic");
  const model = backendModel(health, now);
  return model ? t("deck.backend.t1Model", { model }) : t("deck.backend.connected");
}

function measurementStatus(
  candidate: RouterCandidate,
  router: RouterSnapshot,
  now: number,
): MeasurementStatus {
  if (candidate.status === "failed") return "failed";
  if (candidate.status === "stale" || router.reason === "stale") return "stale";
  if (candidate.status === "unmeasured" || candidate.samples <= 0 ||
    candidate.p50_ms === null || candidate.p95_ms === null) return "unmeasured";
  if (router.reason === "unmeasured" || router.reason === "unavailable" ||
    router.reason === "disabled") return "unmeasured";
  const updatedAt = Date.parse(router.updated_at ?? "");
  const expiresAt = Date.parse(router.expires_at ?? "");
  if (!Number.isFinite(updatedAt) || !Number.isFinite(expiresAt) ||
    updatedAt > now || expiresAt <= updatedAt) return "unknown";
  if (expiresAt <= now) return "stale";
  if (candidate.measured_at !== undefined) {
    const measuredAt = Date.parse(candidate.measured_at);
    if (!Number.isFinite(measuredAt) || measuredAt > now) return "unknown";
    if (now - measuredAt >= expiresAt - updatedAt) return "stale";
  }
  return "measured";
}

function candidateView(
  candidate: RouterCandidate,
  router: RouterSnapshot,
  chose: string,
  now: number,
  requireObservation = false,
): BackendTooltipCandidateView {
  const status = requireObservation && candidate.measured_at === undefined &&
    (candidate.status === undefined || candidate.status === "measured") && candidate.samples > 0
    ? "unknown" : measurementStatus(candidate, router, now);
  return {
    deployment: candidate.deployment,
    p50: status === "measured" ? `${Math.round(candidate.p50_ms!)}ms` : "-",
    p95: status === "measured" ? `${Math.round(candidate.p95_ms!)}ms` : "-",
    samples: candidate.samples,
    selected: candidate.deployment === chose,
    status: t(`deck.backend.measurement.${status}`),
  };
}

function routingReason(router: RouterSnapshot, now: number): string {
  if (["stale", "unavailable", "disabled", "unmeasured"].includes(router.reason)) {
    return t(`deck.backend.routing.${router.reason}`);
  }
  if (router.reason !== "latency") return t("deck.backend.routing.unknown");
  const selected = router.candidates.find((candidate) => candidate.deployment === router.chose);
  const status = selected ? measurementStatus(selected, router, now) : "unknown";
  return status === "measured"
    ? t("deck.backend.routing.latency")
    : t(`deck.backend.measurement.${status}`);
}

/** Renders measured values only within the server-provided freshness window. */
export function backendTooltipView(health: BackendHealth, now = Date.now()): BackendTooltipView {
  const router = health.router;
  const vision = router?.vision;
  return {
    mode: health.mode,
    model: backendModel(health, now),
    endpoint: health.endpoint,
    router: router ? {
      deployment: router.chose,
      reason: routingReason(router, now),
      ...(router.updated_at ? { updatedAt: router.updated_at } : {}),
      ...(router.expires_at ? { expiresAt: router.expires_at } : {}),
      ...(router.interval_seconds ? { intervalSeconds: router.interval_seconds } : {}),
      candidates: router.candidates.map((candidate) => candidateView(candidate, router, router.chose, now)),
    } : null,
    ...(vision?.available && vision.chose ? {
      visionRouter: {
        deployment: vision.chose,
        candidates: vision.candidates.map((candidate) =>
          candidateView(candidate, { ...router!, reason: "" }, vision.chose!, now, true)),
      },
    } : {}),
  };
}

/** Returns the next measurement expiry for a display-only timer, without issuing any probe. */
export function backendMeasurementExpiry(router: RouterSnapshot | undefined, now = Date.now()): number | null {
  if (!router) return null;
  const updated = Date.parse(router.updated_at ?? "");
  const expires = Date.parse(router.expires_at ?? "");
  if (!Number.isFinite(expires) || expires <= now) return null;
  const deadlines = [
    expires,
    ...[...router.candidates, ...(router.vision?.candidates ?? [])].flatMap((candidate) => {
      const measured = Date.parse(candidate.measured_at ?? "");
      return Number.isFinite(updated) && expires > updated && Number.isFinite(measured)
        ? [measured + expires - updated] : [];
    }),
  ].filter((deadline) => deadline > now);
  return deadlines.length ? Math.min(...deadlines) : null;
}

/** Legacy reply-source text uses the same freshness checks as the connected-backend tooltip. */
export function routerTooltip(router: RouterSnapshot | undefined, now = Date.now()): string | undefined {
  if (!router) return undefined;
  const lines = router.candidates.map((candidate) => {
    const view = candidateView(candidate, router, router.chose, now);
    const marker = view.selected ? "* " : "  ";
    return `${marker}${view.deployment} · ${view.status} · p50 ${view.p50} · p95 ${view.p95} · n=${view.samples}`;
  });
  return t("deck.tooltip.routerChoice", {
    reason: routingReason(router, now),
    deployment: router.chose,
    candidates: lines.join("\n"),
  });
}

/** Plain-text disclosure preserves the configured/selected model and its narrow T1 scope. */
export function backendTooltip(health: BackendHealth, now = Date.now()): string {
  const model = backendModel(health, now);
  const lines = [
    model ? t("deck.backend.t1Model", { model }) : t("deck.backend.modelUnknown"),
    t("deck.backend.t1Scope"),
    t("deck.tooltip.chatMode", {
      mode: health.mode,
      endpoint: health.endpoint ? ` · ${health.endpoint}` : "",
    }),
    routerTooltip(health.router, now),
  ];
  return lines.filter(Boolean).join("\n");
}
