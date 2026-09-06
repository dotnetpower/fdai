import { afterEach, describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { setLocale } from "../i18n";
import { parseRouter } from "./backend-normalizers";
import {
  backendBadgeLabel,
  backendMeasurementExpiry,
  backendModel,
  backendTooltip,
  backendTooltipView,
  routerTooltip,
} from "./backend-health-presentation";
import type { BackendHealth, RouterCandidate, RouterSnapshot } from "./backend-types";

const now = Date.parse("2026-09-06T10:00:30Z");
const candidate: RouterCandidate = {
  deployment: "narrator-mini",
  p50_ms: 120.4,
  p95_ms: 200.2,
  samples: 2,
  history_ms: [120.4, 200.2],
  status: "measured",
  measured_at: "2026-09-06T10:00:00Z",
};
const router: RouterSnapshot = {
  chose: candidate.deployment,
  reason: "latency",
  candidates: [candidate],
  updated_at: "2026-09-06T10:00:00Z",
  expires_at: "2026-09-06T10:05:00Z",
  interval_seconds: 300,
};
const legacyHealth: BackendHealth = {
  available: true,
  mode: "semantic-core",
  model: "configured-mini",
  endpoint: null,
};
const health: BackendHealth = { ...legacyHealth, router };

afterEach(() => setLocale("en"));

describe("T1 backend model badge", () => {
  it("shows the selected deployment, or the configured model on older payloads", () => {
    expect(backendBadgeLabel(health, now)).toBe("T1 narrator-mini");
    expect(backendBadgeLabel(legacyHealth)).toBe("T1 configured-mini");
    expect(backendBadgeLabel({ ...health, model: null }, now)).toBe("T1 narrator-mini");
    expect(backendBadgeLabel({ ...legacyHealth, model: null })).toBe("Chat connected");
    expect(backendBadgeLabel({ ...legacyHealth, model: "  " })).toBe("Chat connected");
  });

  it("preserves probing and unavailable states instead of presenting a cached model as ready", () => {
    expect(backendBadgeLabel(null)).toBe("probing");
    expect(backendBadgeLabel({ ...health, available: false })).toBe("deterministic");
  });

  it("keeps the model label visible in the actual header stylesheet", () => {
    const css = readFileSync(new URL("../styles.css", import.meta.url), "utf8");
    expect(css).toContain(".deck-backend-header.deck-backend-ready .deck-backend-label { display: block; }");
    expect(css).not.toContain(".deck-backend-header.deck-backend-ready .deck-backend-label { display: none; }");
    const desktop = css.match(
      /@media \(min-width: 641px\) \{\s*(\.deck-backend-header\.deck-backend-ready \{[\s\S]*?)\n\}/,
    )?.[1];
    expect(desktop).toContain("max-width: min(40ch, 40vw)");
    expect(desktop).toContain("white-space: nowrap");
    expect(desktop).toContain("text-overflow: ellipsis");
    expect(desktop).toContain("overflow: hidden");
  });

  it("owns the local expiry timer on the badge even when its tooltip is closed", () => {
    const component = readFileSync(new URL("./command-deck-presenters.tsx", import.meta.url), "utf8");
    const badge = component.slice(component.indexOf("export function BackendBadge("));
    expect(badge).toContain("backendMeasurementExpiry(health?.router, now)");
    expect(badge).toContain("window.setTimeout(() => setClock((value) => value + 1)");
    expect(badge).toContain("return () => window.clearTimeout(timer)");
  });

  it("drops an expired projection locally without falling back to the old configured model", () => {
    const expires = Date.parse(router.expires_at!);
    expect(backendModel(health, expires - 1)).toBe("narrator-mini");
    expect(backendModel(health, expires)).toBeNull();
    expect(backendBadgeLabel(health, expires)).toBe("Chat connected");
    expect(backendTooltipView(health, expires).model).toBeNull();
    expect(health.model).toBe("configured-mini");
  });

  it("drops latency-selected identity when its sample expires before the projection", () => {
    const current = {
      ...health,
      router: { ...router, candidates: [{ ...candidate, measured_at: "2026-09-06T09:56:00Z" }] },
    };
    const sampleExpires = Date.parse("2026-09-06T10:01:00Z");
    expect(backendMeasurementExpiry(current.router, now)).toBe(sampleExpires);
    expect(backendBadgeLabel(current, sampleExpires - 1)).toBe("T1 narrator-mini");
    expect(backendBadgeLabel(current, sampleExpires)).toBe("Chat connected");
    expect(backendTooltipView(current, sampleExpires).model).toBeNull();
  });

  it.each(["stale", "configured-order"])("keeps a fresh %s configured selection despite old samples", (reason) => {
    const current = {
      ...health,
      router: {
        ...router,
        reason,
        candidates: [{ ...candidate, status: "stale" as const, measured_at: "2026-09-06T09:50:00Z" }],
      },
    };
    expect(backendBadgeLabel(current, now)).toBe("T1 narrator-mini");
    const view = backendTooltipView(current, now);
    expect(view.router?.reason).not.toBe("Measured latency");
    expect(view.router?.candidates[0]?.p50).toBe("-");
    expect(backendBadgeLabel(current, Date.parse(router.expires_at!))).toBe("Chat connected");
  });

  it("preserves legacy configured/selected models without inventing an expiry", () => {
    const legacyRouter = { chose: router.chose, reason: "latency", candidates: [candidate] };
    const later = Date.parse("2026-09-07T10:00:00Z");
    expect(backendBadgeLabel(legacyHealth, later)).toBe("T1 configured-mini");
    expect(backendBadgeLabel({ ...health, router: legacyRouter }, later)).toBe("T1 narrator-mini");
    expect(backendMeasurementExpiry(legacyRouter, later)).toBeNull();
  });

  it("honors an explicit projection expiry even when the optional update timestamp is absent", () => {
    const { updated_at: _updated, ...snapshot } = router;
    const current = { ...health, router: snapshot };
    expect(backendMeasurementExpiry(snapshot, now)).toBe(Date.parse(router.expires_at!));
    expect(backendBadgeLabel(current, now)).toBe("T1 narrator-mini");
    expect(backendBadgeLabel(current, Date.parse(router.expires_at!))).toBe("Chat connected");
  });

  it.each(["en", "ko"] as const)("explains independent review and T2 scope in %s", (locale) => {
    setLocale(locale);
    const text = backendTooltip(health, now);
    expect(text).toContain("T1 narrator-mini");
    expect(text).toContain("T2");
    expect(text).toContain(locale === "en" ? "Independent review" : "독립 검토");
    expect(text).toContain(locale === "en" ? "Next narration/general response" : "다음 설명/일반 응답");
    expect(text).toContain(locale === "en" ? "separate models" : "별도 모델");
    expect(text).not.toMatch(/\{(?:model|deployment|reason|candidates)\}/);
  });
});

describe("trustworthy measurement disclosure", () => {
  it("shows fresh measured p50/p95 and the server refresh metadata", () => {
    const view = backendTooltipView(health, now);
    expect(view.router).toMatchObject({
      reason: "Probe latency",
      updatedAt: router.updated_at,
      expiresAt: router.expires_at,
      intervalSeconds: 300,
      candidates: [{ deployment: "narrator-mini", p50: "120ms", p95: "200ms", status: "Measured" }],
    });
    expect(backendMeasurementExpiry(router, now)).toBe(Date.parse(router.expires_at!));
  });

  it.each(["failed", "unmeasured", "stale"] as const)("does not show %s candidates as measured speed", (status) => {
    const snapshot = { ...router, candidates: [{ ...candidate, status }] };
    const view = backendTooltipView({ ...health, router: snapshot }, now);
    expect(view.router?.candidates[0]).toMatchObject({ p50: "-", p95: "-", selected: true });
    expect(view.router?.reason).not.toBe("Measured latency");
    expect(routerTooltip(snapshot, now)).not.toMatch(/120ms|200ms|fastest/i);
  });

  it.each(["stale", "unmeasured", "unavailable", "disabled"])("suppresses measured speed for router reason %s", (reason) => {
    const view = backendTooltipView({ ...health, router: { ...router, reason } }, now);
    expect(view.router?.candidates[0]?.p50).toBe("-");
    expect(view.router?.reason).not.toBe("Measured latency");
  });

  it("keeps legacy model identity but hides speed when freshness is unknown", () => {
    const legacy = { chose: router.chose, reason: "latency", candidates: [candidate] };
    const view = backendTooltipView({ ...health, router: legacy }, now);
    expect(view.model).toBe("narrator-mini");
    expect(view.router?.candidates[0]).toMatchObject({ status: "Freshness unknown", p50: "-", p95: "-" });
    expect(view.router?.reason).not.toBe("Measured latency");
    expect(backendMeasurementExpiry(legacy, now)).toBeNull();
  });

  it("expires exactly at the deadline even when the last health response is cached", () => {
    const expiredAt = Date.parse(router.expires_at!);
    const view = backendTooltipView(health, expiredAt);
    expect(view.router?.candidates[0]).toMatchObject({ status: "Stale", p50: "-", p95: "-" });
    expect(view.router?.reason).toBe("Stale");
    expect(backendMeasurementExpiry(router, expiredAt)).toBeNull();
  });

  it("does not turn an older candidate measurement fresh when the snapshot is republished", () => {
    const snapshot = {
      ...router,
      candidates: [{ ...candidate, measured_at: "2026-09-06T09:56:00Z" }],
    };
    expect(backendMeasurementExpiry(snapshot, now)).toBe(Date.parse("2026-09-06T10:01:00Z"));
    const expired = backendTooltipView({ ...health, router: snapshot }, Date.parse("2026-09-06T10:01:00Z"));
    expect(expired.router?.candidates[0]?.status).toBe("Stale");
  });

  it.each([
    { updated_at: undefined },
    { expires_at: undefined },
    { updated_at: "invalid" },
    { updated_at: "2026-09-06T11:00:00Z" },
    { expires_at: "2026-09-06T09:00:00Z" },
  ])("rejects missing, invalid, future, or reversed windows: %j", (changes) => {
    const view = backendTooltipView({ ...health, router: parseRouter({ ...router, ...changes })! }, now);
    expect(view.router?.candidates[0]?.p50).toBe("-");
    expect(view.router?.reason).not.toBe("Measured latency");
  });

  it("does not infer speed from a zero-sample candidate or a future observation", () => {
    for (const changes of [{ samples: 0 }, { measured_at: "2026-09-06T11:00:00Z" }]) {
      const view = backendTooltipView({
        ...health,
        router: { ...router, candidates: [{ ...candidate, ...changes }] },
      }, now);
      expect(view.router?.candidates[0]?.p50).toBe("-");
    }
  });

  it("does not reuse fresh text metadata as proof of an undated vision measurement", () => {
    const { measured_at: _measuredAt, ...undated } = candidate;
    const snapshot = {
      ...router,
      vision: { available: true, chose: "vision-mini", candidates: [{ ...undated, deployment: "vision-mini" }] },
    };
    const view = backendTooltipView({ ...health, router: snapshot }, now);
    expect(view.router?.candidates[0]?.p50).toBe("120ms");
    expect(view.visionRouter?.candidates[0]).toMatchObject({ p50: "-", status: "Freshness unknown" });
  });
});
