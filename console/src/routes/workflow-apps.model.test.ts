import { describe, expect, it } from "vitest";
import { decodeWorkflowApps, workflowAppHref } from "./workflow-apps.model";

const APP = {
  id: "architecture-review",
  workflow_ref: "architecture-review",
  view_ref: "architecture-review",
  lifecycle: "published",
  audience: "reader",
  label: { en: "Architecture review", ko: "Architecture review" },
  description: { en: "Review evidence", ko: "Review evidence" },
  route: "/workflow-apps/architecture-review",
  group: "operations",
  order: 100,
};

describe("workflow app manifest decoder", () => {
  it("accepts a bounded published app and builds its clean route", () => {
    expect(decodeWorkflowApps({ items: [APP], count: 1 }).items[0]?.id).toBe(
      "architecture-review",
    );
    expect(workflowAppHref("architecture-review")).toBe("/workflow-apps/architecture-review");
  });

  it("rejects route spoofing and duplicate workflow exposure", () => {
    expect(() => decodeWorkflowApps({
      items: [{ ...APP, route: "/workflow-apps/other" }],
      count: 1,
    })).toThrow(/route MUST match/);
    expect(() => decodeWorkflowApps({
      items: [APP, { ...APP, id: "second", route: "/workflow-apps/second" }],
      count: 2,
    })).toThrow(/workflow refs MUST be unique/);
  });

  it("rejects non-published or privileged-looking manifests", () => {
    expect(() => decodeWorkflowApps({ items: [{ ...APP, lifecycle: "shadow" }], count: 1 }))
      .toThrow(/lifecycle MUST be published/);
    expect(() => decodeWorkflowApps({ items: [{ ...APP, audience: "owner" }], count: 1 }))
      .toThrow(/audience MUST be reader/);
  });
});
