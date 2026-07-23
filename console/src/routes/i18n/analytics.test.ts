import { afterEach, describe, expect, it } from "vitest";
import { setLocale } from "../../i18n";
import en from "./analytics.en.json";
import ko from "./analytics.ko.json";
import { t } from "./analytics";

afterEach(() => setLocale("en"));

function leafPaths(value: unknown, prefix = ""): string[] {
  if (typeof value === "string") return [prefix];
  if (typeof value !== "object" || value === null) return [];
  return Object.entries(value).flatMap(([key, child]) =>
    leafPaths(child, prefix === "" ? key : `${prefix}.${key}`),
  );
}

describe("analytics route localization", () => {
  it("renders the English source and interpolates values", () => {
    expect(t("analytics.outcomes.trend", { metric: "MTTR" })).toBe("MTTR trend");
  });

  it("provides complete Korean leaf-key coverage", () => {
    expect(leafPaths(ko).sort()).toEqual(leafPaths(en).sort());
  });

  it("resolves every route-local leaf in both locales", () => {
    const paths = leafPaths(en);
    for (const path of paths) expect(t(`analytics.${path}`)).not.toBe(`analytics.${path}`);
    setLocale("ko");
    for (const path of paths) expect(t(`analytics.${path}`)).not.toBe(`analytics.${path}`);
  });

  it("falls back to English for a missing Korean route value", () => {
    const mutableKo = ko as { outcomes: { costNoticeTitle?: string } };
    const original = mutableKo.outcomes.costNoticeTitle;
    if (original === undefined) throw new Error("Korean cost notice title is required");
    delete mutableKo.outcomes.costNoticeTitle;
    try {
      setLocale("ko");
      expect(t("analytics.outcomes.costNoticeTitle")).toBe("Standard-price estimate");
    } finally {
      mutableKo.outcomes.costNoticeTitle = original;
    }
  });
});
