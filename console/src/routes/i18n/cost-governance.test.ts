import { describe, expect, it } from "vitest";
import en from "./cost-governance.en.json";
import ko from "./cost-governance.ko.json";

function catalogKeys(value: unknown, prefix = ""): string[] {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return [prefix];
  return Object.entries(value).flatMap(([key, child]) =>
    catalogKeys(child, prefix ? `${prefix}.${key}` : key)
  );
}

describe("Cost Governance catalogs", () => {
  it("keeps English and Korean catalogs structurally aligned", () => {
    expect(catalogKeys(ko).sort()).toEqual(catalogKeys(en).sort());
  });
});
