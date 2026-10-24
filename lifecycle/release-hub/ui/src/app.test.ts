import { afterEach, describe, expect, it, vi } from "vitest";
import { requestCatalog, type Action, type Catalog } from "./api";
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

describe("confirmation retry state", () => {
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
