import { afterEach, describe, expect, it, vi } from "vitest";
import { isInitialCatalog, requestCatalog, type Action, type Catalog } from "./api";
import { isConfirmationDisabled } from "./app";

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
