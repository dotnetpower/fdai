import { describe, expect, it } from "vitest";
import { nextReleaseStep, recordedStage } from "./release-workspace";
import { CatalogRequestError, catalogChangeObserved, catalogRecovery, type Catalog, type Release } from "./api";

const release: Release = {
  id: "1.0.0", label: "", manifest: "{}", digest: "a".repeat(64),
  signed_payload_sha256: "b".repeat(64), signature: "development-signature",
  signature_status: "development-key-verified", state: "published",
  channels: ["DEV"], published_at: "2026-10-26T00:00:00Z", recalled_at: null,
};
const catalog: Catalog = {
  revision: 3, updated_at: "2026-10-26T00:00:00Z", expires_at: "2026-10-27T00:00:00Z",
  expired: false, key_id: "development", mode: "local-development",
  releases: [release], channels: { DEV: ["1.0.0"] }, events: [],
};

describe("release workspace decisions", () => {
  it("chooses exactly one next step without inventing promotion authority", () => {
    expect(nextReleaseStep({ ...release, state: "draft" }, catalog)).toBe("publish");
    expect(nextReleaseStep(release, catalog)).toBe("review");
    expect(nextReleaseStep(release, { ...catalog, expired: true })).toBe("renew");
    expect(nextReleaseStep({ ...release, state: "recalled" }, { ...catalog, expired: true })).toBe("recall");
  });
  it("publishes an expired draft without a separate catalog renewal", () => {
    expect(nextReleaseStep({ ...release, state: "draft" }, { ...catalog, expired: true })).toBe("publish");
  });
  it("reports only recorded built-in membership, independent of channel order", () => {
    expect(recordedStage(release)).toBe("DEV");
    expect(recordedStage({ ...release, channels: ["RELEASE_CANDIDATE", "DEV"] })).toBe("RELEASE_CANDIDATE");
    expect(recordedStage({ ...release, channels: ["RELEASE", "DEV", "RELEASE_CANDIDATE"] })).toBe("RELEASE");
    expect(recordedStage({ ...release, channels: ["custom-pilot"] })).toBeNull();
    expect(recordedStage({ ...release, channels: [] })).toBeNull();
    expect(recordedStage({ ...release, state: "recalled" })).toBe("DEV");
  });
  it("distinguishes recovery paths without rendering arbitrary server diagnostics", () => {
    const unsafe = "private diagnostic must not be rendered";
    expect(catalogRecovery(new CatalogRequestError(unsafe, 401))).toContain("Session expired");
    expect(catalogRecovery(new CatalogRequestError(unsafe, 403))).toContain("access denied");
    expect(catalogRecovery(new CatalogRequestError(unsafe, 409))).toContain("server guard");
    expect(catalogRecovery(new CatalogRequestError(unsafe, 503))).toContain("readiness");
    expect(catalogRecovery(new CatalogRequestError(unsafe, 422))).toContain("(422)");
    expect(catalogRecovery(new DOMException(unsafe, "TimeoutError"))).toContain("timed out");
    expect(catalogRecovery(new TypeError(unsafe))).toContain("unavailable or invalid");
    const expired = new Error(unsafe);
    expired.name = "InteractionRequiredAuthError";
    expect(catalogRecovery(expired)).toContain("sign-in");
    for (const status of [401, 403, 409, 422, 503]) {
      expect(catalogRecovery(new CatalogRequestError(unsafe, status))).not.toContain(unsafe);
    }
  });
  it("requires the exact attributed event on readback instead of an API success or unrelated revision", () => {
    const change = { revision: 3, confirmation: release.id, reason: " reviewed ", channel: "RELEASE_CANDIDATE" };
    const event = { revision: 4, action: "contribute", release_id: release.id,
      reason: "reviewed", channel: "RELEASE_CANDIDATE", occurred_at: "2026-10-27T00:00:00Z" };
    const current = { ...catalog, revision: 4, events: [event] };
    expect(catalogChangeObserved(current, "contribute", release.id, change)).toBe(true);
    expect(catalogChangeObserved({ ...current, revision: 5 }, "contribute", release.id, change)).toBe(true);
    expect(catalogChangeObserved(catalog, "contribute", release.id, change)).toBe(false);
    for (const mismatch of [{ revision: 5 }, { action: "recall" }, { release_id: "2.0.0" },
      { channel: "RELEASE" }, { reason: "another operator request" }]) {
      expect(catalogChangeObserved({ ...current, events: [{ ...event, ...mismatch }] }, "contribute", release.id, change)).toBe(false);
    }
    expect(catalogChangeObserved({ ...current, events: [{ ...event, action: "renew", release_id: "catalog", channel: null }] },
      "renew", "", change)).toBe(true);
    for (const action of ["register", "publish", "recall"] as const) {
      expect(catalogChangeObserved({ ...current, events: [{ ...event, action, channel: null }] },
        action, release.id, change)).toBe(true);
    }
  });
});
