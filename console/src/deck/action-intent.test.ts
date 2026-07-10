import { describe, expect, test } from "vitest";
import { detectActionIntent, leadingVerb } from "./action-intent";

describe("detectActionIntent", () => {
  test("recognises leading command verbs", () => {
    expect(detectActionIntent("restart vm-1")).toBe(true);
    expect(detectActionIntent("failover prod-pg-01")).toBe(true);
    expect(detectActionIntent("delete the storage account")).toBe(true);
    expect(detectActionIntent("encrypt disk-2")).toBe(true);
  });

  test("strips polite filler before the verb", () => {
    expect(detectActionIntent("please restart vm-1")).toBe(true);
    expect(detectActionIntent("can you delete rg-x")).toBe(true);
  });

  test("treats questions as non-actions", () => {
    expect(detectActionIntent("what is the action status")).toBe(false);
    expect(detectActionIntent("why did corr-j start")).toBe(false);
    expect(detectActionIntent("show me the failed tiles")).toBe(false);
    expect(detectActionIntent("how many rules are active")).toBe(false);
  });

  test("empty / punctuation-only is not an action", () => {
    expect(detectActionIntent("")).toBe(false);
    expect(detectActionIntent("   ")).toBe(false);
    expect(detectActionIntent("???")).toBe(false);
  });
});

describe("leadingVerb", () => {
  test("returns the first non-filler token", () => {
    expect(leadingVerb("please restart vm-1")).toBe("restart");
    expect(leadingVerb("What is this")).toBe("what");
    expect(leadingVerb("")).toBe(null);
  });
});
