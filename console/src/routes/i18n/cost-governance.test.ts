import { describe, expect, it } from "vitest";
import { getLocale, setLocale } from "../../i18n";
import en from "./cost-governance.en.json";
import ko from "./cost-governance.ko.json";
import { t } from "./cost-governance";

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

  it("falls back to English when the active locale omits or empties a key", () => {
    const previous = getLocale();
    const mutableKo = ko as unknown as Record<string, unknown>;
    const originalTitle = mutableKo["title"];
    try {
      setLocale("ko");
      mutableKo["title"] = "";
      expect(t("costGovernance.title")).toBe(en.title);
      expect(t("costGovernance.nonexistent.key")).toBe("costGovernance.nonexistent.key");
    } finally {
      mutableKo["title"] = originalTitle;
      setLocale(previous);
    }
  });
});
