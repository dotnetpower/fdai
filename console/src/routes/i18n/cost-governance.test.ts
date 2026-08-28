import { describe, expect, it } from "vitest";
import en from "./cost-governance.en.json";
import ko from "./cost-governance.ko.json";

describe("Cost Governance catalogs", () => {
  it("keeps English and Korean catalogs structurally aligned", () => {
    expect(Object.keys(ko).sort()).toEqual(Object.keys(en).sort());
    expect(Object.keys(ko.tabs).sort()).toEqual(Object.keys(en.tabs).sort());
    expect(Object.keys(ko.columns).sort()).toEqual(Object.keys(en.columns).sort());
  });
});
