import { afterEach, describe, expect, it } from "vitest";
import { setLocale, t as mainT } from "../i18n";
import { t } from "./i18n/conversation-layer";
import en from "./i18n/conversation-layer.en.json";
import ko from "./i18n/conversation-layer.ko.json";

function leaves(value: unknown, prefix: string): [string, string][] {
  if (typeof value === "string") return [[prefix, value]];
  return Object.entries(value as Record<string, unknown>).flatMap(([key, child]) =>
    leaves(child, `${prefix}.${key}`),
  );
}

describe("conversation-layer translator", () => {
  afterEach(() => setLocale("en"));

  it("renders every deck-only layer label in the active locale", () => {
    const english = leaves(en, "deck");
    const korean = new Map(leaves(ko, "deck"));
    expect(english.length).toBeGreaterThan(0);
    for (const [key, text] of english) expect(t(key)).toBe(text);
    setLocale("ko");
    for (const [key] of english) expect(t(key)).toBe(korean.get(key));
    expect(t("deck.leave.stay")).toBe("여기에 머무르기");
  });

  it("keeps deck-only layer labels out of the entry catalog", () => {
    for (const [key] of leaves(en, "deck")) expect(mainT(key)).toBe(key);
  });

  it("falls back to the main catalog outside the deck-only keys", () => {
    expect(t("deck.tooltip.copied")).toBe(mainT("deck.tooltip.copied"));
    setLocale("ko");
    expect(t("deck.tooltip.copied")).toBe(mainT("deck.tooltip.copied"));
  });

  it("substitutes placeholders like the main catalog and keeps unmatched ones", () => {
    expect(t("deck.rich.copyCode", { language: "Python" })).toBe("Copy Python");
    expect(t("deck.leave.title")).toBe("Open {screen}?");
  });
});
