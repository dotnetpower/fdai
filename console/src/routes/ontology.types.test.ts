import { describe, expect, it } from "vitest";
import { compactRecord, formatUnknown, ontologyView, recordValue } from "./ontology.types";

describe("ontology view model", () => {
  it("normalizes unsupported views to the Semantic model", () => {
    expect(ontologyView(null)).toBe("map");
    expect(ontologyView("unknown")).toBe("map");
    expect(ontologyView("links")).toBe("links");
    expect(ontologyView("actions")).toBe("actions");
    expect(ontologyView("map")).toBe("map");
    expect(ontologyView("topology")).toBe("topology");
  });

  it("formats nested safety contract records without inventing fields", () => {
    expect(compactRecord({ kind: "provider_api_error_streak", count: 3 })).toBe(
      "kind: provider_api_error_streak | count: 3",
    );
    expect(formatUnknown({ max_autonomy: "enforce_hil", min_role: "approver" })).toBe(
      "max_autonomy=enforce_hil, min_role=approver",
    );
    expect(recordValue({ kind: "both" }, "kind")).toBe("both");
    expect(recordValue(undefined, "kind")).toBeNull();
  });
});
