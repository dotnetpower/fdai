import { describe, expect, it } from "vitest";
import { OperatorApiError } from "../api";
import {
  ruleCatalogHref,
  ruleDetailFailure,
  ruleListStateFromSearch,
  ruleLifecycleStatusFromSearch,
  ruleSelectionFromSearch,
} from "./rule-catalog";

describe("rule detail citation failures", () => {
  it("keeps list origin filtering independent from detail provenance", () => {
    const filters = { origin: "custom", category: "", severity: "", source: "", q: "" };
    const href = ruleCatalogHref(filters, 0, { id: "rule-1", origin: "built_in" });
    expect(href).toBe("/rules?origin=custom&rule_origin=built_in&rule=rule-1");
    const search = new URL(href, "https://console.example").searchParams;
    expect(ruleListStateFromSearch(search).filters.origin).toBe("custom");
    expect(ruleSelectionFromSearch(search)).toEqual({ id: "rule-1", origin: "built_in" });
  });

  it("does not turn a legacy detail origin into a list filter", () => {
    const search = new URLSearchParams("rule=rule-1&origin=built_in");
    expect(ruleListStateFromSearch(search).filters.origin).toBe("");
    expect(ruleSelectionFromSearch(search)).toEqual({ id: "rule-1", origin: "built_in" });
  });

  it("maps only active lifecycle evidence to the authoritative catalog origin", () => {
    const active = new URLSearchParams("status=active");
    expect(ruleLifecycleStatusFromSearch(active)).toBe("active");
    expect(ruleListStateFromSearch(active).filters.origin).toBe("active");
    expect(ruleLifecycleStatusFromSearch(new URLSearchParams("status=promoted")))
      .toBe("promoted");
    expect(ruleLifecycleStatusFromSearch(new URLSearchParams("status=unknown")))
      .toBe("invalid");
  });

  it("preserves a missing historical rule id for recovery", () => {
    expect(ruleDetailFailure(new OperatorApiError(404, "unknown rule"), "retired.rule"))
      .toEqual({ status: "unavailable", ruleId: "retired.rule" });
  });

  it("keeps operational failures visible as errors", () => {
    expect(ruleDetailFailure(new OperatorApiError(503, "catalog unavailable"), "active.rule"))
      .toEqual({ status: "error", message: "catalog unavailable" });
  });
});
