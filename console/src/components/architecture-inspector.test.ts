import { describe, expect, it } from "vitest";
import { architectureRelationshipLabel, architectureStatusLabel } from "./architecture-inspector";

describe("architecture inspector labels", () => {
  it("expresses relationship direction from the selected resource", () => {
    const link = { source: "app", target: "db", type: "depends_on" as const };
    expect(architectureRelationshipLabel(link, "app")).toBe("Depends on");
    expect(architectureRelationshipLabel(link, "db")).toBe("Required by");
  });

  it("does not present unknown status as a reported state", () => {
    expect(architectureStatusLabel("unknown")).toBe("Status unavailable");
    expect(architectureStatusLabel("vm_deallocated")).toBe("Vm deallocated");
  });
});
