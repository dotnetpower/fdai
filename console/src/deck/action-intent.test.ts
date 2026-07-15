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

  test("routes bilingual incident creation and confirmation", () => {
    expect(detectActionIntent("prod-api-01 대상으로 SEV2 장애 케이스 열어줘")).toBe(true);
    expect(detectActionIntent("Create a SEV2 incident for target prod-api-01")).toBe(true);
    expect(detectActionIntent("확인")).toBe(true);
    expect(detectActionIntent("confirm")).toBe(true);
    expect(detectActionIntent("장애 원인이 뭐야?")).toBe(false);
    expect(detectActionIntent("transition incident 00000000-0000-0000-0000-000000000001 to triaging")).toBe(true);
    expect(detectActionIntent("incident 00000000-0000-0000-0000-000000000001 상태 triaging으로 변경")).toBe(true);
    expect(detectActionIntent("assign incident 00000000-0000-0000-0000-000000000001 to user-1")).toBe(true);
  });

  // Parity with the server `_AMBIGUOUS_ACTION_VERBS` / `_QUESTION_MARKERS`
  // guard (fdai.agents._framework.introspection.is_action_intent). Without
  // this, the deck would misroute a question that leads with an ambiguous verb
  // to POST /chat/action instead of the read-only narrator.
  describe("ambiguous verbs are commands only when phrased imperatively", () => {
    test("imperative ambiguous verb IS a command", () => {
      expect(detectActionIntent("run the remediation")).toBe(true);
      expect(detectActionIntent("start the service")).toBe(true);
      expect(detectActionIntent("stop svc-1")).toBe(true);
      expect(detectActionIntent("update the tls policy")).toBe(true);
    });

    test("ambiguous verb + question mark is NOT a command", () => {
      expect(detectActionIntent("run status?")).toBe(false);
      expect(detectActionIntent("start count?")).toBe(false);
      expect(detectActionIntent("update history?")).toBe(false);
      expect(detectActionIntent("set of rules?")).toBe(false);
    });

    test("ambiguous verb + interrogative marker (no '?') is NOT a command", () => {
      expect(detectActionIntent("run status list")).toBe(false);
      expect(detectActionIntent("start count show")).toBe(false);
      expect(detectActionIntent("set which rules are active")).toBe(false);
    });

    test("non-ambiguous command verb ignores question markers", () => {
      // `delete` is unambiguous: a trailing marker does not soften it.
      expect(detectActionIntent("delete rg-x status")).toBe(true);
    });
  });
});

describe("leadingVerb", () => {
  test("returns the first non-filler token", () => {
    expect(leadingVerb("please restart vm-1")).toBe("restart");
    expect(leadingVerb("What is this")).toBe("what");
    expect(leadingVerb("")).toBe(null);
  });
});
