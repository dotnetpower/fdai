import { afterEach, describe, expect, it, vi } from "vitest";
import { isInitialCatalog, requestCatalog, type Action, type Catalog } from "./api";
import { confirmedReturnRoute, currentPromotionTransition, isConfirmationDisabled, quickCreateReturnRoute, releaseNavGroup } from "./app";

const validConfirmation = {
  action: "renew" as Action,
  busy: false,
  channel: "",
  channelConfirmation: "",
  confirmation: "renew 3",
  customChannel: false,
  reason: "Reviewed current eligibility",
  target: "renew 3",
};

const catalog = (): Catalog => ({
  revision: 4,
  updated_at: "2026-10-24T10:00:00Z",
  expires_at: "2026-10-25T10:00:00Z",
  expired: false,
  key_id: "development",
  mode: "local-development",
  releases: [],
  channels: {},
  events: [],
});

describe("grouped navigation with retained legacy routes", () => {
  it("maps existing bookmarks and Edition detail routes to three navigation groups", () => {
    for (const route of ["/edition", "/edition/new", "/edition/releases/0.5.2", "/edition/selected/0.5.2", "/stencils", "/releases", "/releases/0.5.2"]) {
      expect(releaseNavGroup(route)).toBe("/edition");
    }
    expect(releaseNavGroup("/channels")).toBe("/channels");
    expect(releaseNavGroup("/deployment-requests")).toBe("/channels");
    expect(releaseNavGroup("/trust")).toBe("/trust");
    expect(releaseNavGroup("/activity")).toBe("/trust");
    expect(releaseNavGroup("/unknown")).toBeNull();
  });

  describe("one-click promotion freshness", () => {
    const release: Catalog["releases"][number] = {
      id: "1.0.0", label: "Candidate", manifest: "{}", digest: "a".repeat(64),
      signed_payload_sha256: "b".repeat(64), signature: "signed",
      signature_status: "development-key-verified", state: "published",
      channels: ["DEV"], published_at: "2026-10-24T10:00:00Z", recalled_at: null,
    };

    it("uses the current stage only when it matches the stage shown to the operator", () => {
      expect(currentPromotionTransition(release, { ...catalog(), releases: [release] })).toEqual({
        sourceChannel: "DEV", targetChannel: "RELEASE_CANDIDATE",
      });
    });

    it("rejects a changed, recalled, or missing release rather than promoting the next stage", () => {
      for (const releases of [
        [{ ...release, channels: ["DEV", "RELEASE_CANDIDATE"] }],
        [{ ...release, state: "recalled" as const }],
        [],
      ]) {
        expect(() => currentPromotionTransition(release, { ...catalog(), releases })).toThrow(/Release stage changed/);
      }
    });
  });

  it("returns successful create and confirmed changes to their originating workflow", () => {
    expect(quickCreateReturnRoute("/edition/new", "0.5.3")).toBe("/edition/selected/0.5.3");
    expect(quickCreateReturnRoute("/stencils", "0.5.3")).toBe("/releases");
    expect(confirmedReturnRoute("/edition/new", "0.5.3", "register")).toBe("/edition/releases/0.5.3");
    expect(confirmedReturnRoute("/edition/releases/0.5.2", "0.5.2", "promote")).toBe("/edition/releases/0.5.2");
    expect(confirmedReturnRoute("/releases/0.5.2", "0.5.2", "publish")).toBe("/releases/0.5.2");
    expect(confirmedReturnRoute("/trust", "", "renew")).toBe("/trust");
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe("initial catalog evidence", () => {
  const initial = (): Catalog => ({ ...catalog(), revision: 0, expired: true });

  it("distinguishes an untouched empty store without changing its expiry", () => {
    const data = initial();
    expect(isInitialCatalog(data)).toBe(true);
    expect(data.expired).toBe(true);
    expect(data.expires_at).toBe("2026-10-25T10:00:00Z");
  });

  it("never hides expiry after renewal, registration, publication, or recall", () => {
    expect(isInitialCatalog({ ...initial(), revision: 1 })).toBe(false);
    expect(isInitialCatalog({ ...initial(), events: [{
      revision: 1, release_id: "catalog", action: "renew", reason: "Reviewed",
      channel: null, occurred_at: "2026-10-24T11:00:00Z",
    }] })).toBe(false);
    expect(isInitialCatalog({ ...initial(), releases: [{
      id: "1.0.0", label: "Registered", manifest: "{}", digest: "a".repeat(64),
      signed_payload_sha256: "b".repeat(64), signature: null, signature_status: "unsigned",
      state: "draft", channels: [], published_at: null, recalled_at: null,
    }] })).toBe(false);
    expect(isInitialCatalog({ ...initial(), channels: { DEV: ["1.0.0"] } })).toBe(false);
  });
});

describe("confirmation retry state", () => {
  it("requires a fresh reason and confirmation for a retained registration target", () => {
    const state = { ...validConfirmation, action: "register" as Action, target: "2.0.0", reason: "", confirmation: "" };
    expect(isConfirmationDisabled(state)).toBe(true);
    expect(isConfirmationDisabled({ ...state, reason: "Reviewed after readback" })).toBe(true);
    expect(isConfirmationDisabled({ ...state, confirmation: "2.0.0" })).toBe(true);
    expect(isConfirmationDisabled({ ...state, reason: "Reviewed after readback", confirmation: "2.0.0" })).toBe(false);
  });

  it("keeps in-flight and validation failures disabled", () => {
    expect(isConfirmationDisabled({ ...validConfirmation, busy: true })).toBe(true);
    expect(isConfirmationDisabled({ ...validConfirmation, confirmation: "renew 2" })).toBe(true);
    expect(isConfirmationDisabled({ ...validConfirmation, target: "" })).toBe(true);
    expect(isConfirmationDisabled({ ...validConfirmation, reason: "  " })).toBe(true);
    expect(isConfirmationDisabled({
      ...validConfirmation,
      action: "contribute",
      channel: "custom-pilot",
      channelConfirmation: "custom-other",
      customChannel: true,
    })).toBe(true);
  });

  it("allows a failed request to be retried successfully", async () => {
    const fetch = vi.fn()
      .mockResolvedValueOnce({
        ok: false,
        status: 409,
        json: async () => ({ error: "Catalog changed." }),
      })
      .mockResolvedValueOnce({ ok: true, status: 200, json: async () => catalog() });
    vi.stubGlobal("fetch", fetch);

    let error = "";
    try {
      await requestCatalog("/v1/catalog/renew", {
        revision: 3,
        confirmation: "renew 3",
        reason: validConfirmation.reason,
      });
    } catch (failure) {
      error = failure instanceof Error ? failure.message : "Request failed.";
    }

    expect(error).toBe("Catalog changed.");
    expect(isConfirmationDisabled(validConfirmation)).toBe(false);
    await expect(requestCatalog("/v1/catalog/renew", {
      revision: 3,
      confirmation: "renew 3",
      reason: validConfirmation.reason,
    })).resolves.toEqual(catalog());
    expect(fetch).toHaveBeenCalledTimes(2);
  });
});
