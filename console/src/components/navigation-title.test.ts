import { describe, expect, test } from "vitest";
import { navigationDomainForPanel } from "./navigation-title";

describe("navigation title", () => {
  test("omits duplicate domain roots and standalone utilities", () => {
    expect(navigationDomainForPanel("dashboard")).toBeNull();
    expect(navigationDomainForPanel("agents")).toBeNull();
    expect(navigationDomainForPanel("labs")).toBeNull();
    expect(navigationDomainForPanel("settings")).toBeNull();
  });

  test("returns the domain for detail panels", () => {
    expect(navigationDomainForPanel("llm-cost")).toBe("Overview");
    expect(navigationDomainForPanel("incidents")).toBe("Operations");
  });
});