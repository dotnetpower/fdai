import { describe, expect, it } from "vitest";
import { connectionChange, hasCatalogTrustSource, releaseHubConfirmation } from "./routes/release-connection";

describe("Release Hub connection approval", () => {
  it("binds the exact endpoint and revision", () => {
    expect(connectionChange("http://localhost:8091/", 3, "Reviewed source")).toEqual({
      endpoint: "http://localhost:8091",
      revision: 3,
      reason: "Reviewed source",
      confirmation: "connect release hub http://localhost:8091 3",
    });
    expect(releaseHubConfirmation("http://localhost:8099", 3))
      .not.toBe(releaseHubConfirmation("http://localhost:8091", 3));
    expect(releaseHubConfirmation("http://localhost:8091", 2))
      .not.toBe(releaseHubConfirmation("http://localhost:8091", 3));
  });

  it("resets explicitly instead of substituting an endpoint on failure", () => {
    expect(connectionChange(null, 4, "Restore local default")).toEqual({
      endpoint: null, revision: 4, reason: "Restore local default",
      confirmation: "connect release hub local-default 4",
    });
  });

  it("does not turn a saved or default endpoint into catalog trust", () => {
    const connection = {
      endpoint: "http://127.0.0.1:8091", configured_endpoint: null, revision: 0,
      source: "local-default" as const, editable: true, requires_migration: false,
    };
    expect(hasCatalogTrustSource(connection)).toBe(false);
    expect(hasCatalogTrustSource({ ...connection, source: "saved" })).toBe(false);
    expect(hasCatalogTrustSource({ ...connection, source: "environment" })).toBe(false);
    expect(hasCatalogTrustSource({ ...connection, source: "deployment" })).toBe(true);
  });

  it.each([
    "https://user:password@example.com", "https://example.com/catalog",
    "https://example.com?token=value", "https://example.com#fragment", "not a URL",
  ])("does not silently remove unsafe endpoint input: %s", (endpoint) => {
    expect(() => connectionChange(endpoint, 0, "Reviewed source")).toThrow();
  });
});
