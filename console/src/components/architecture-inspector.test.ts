import { describe, expect, it } from "vitest";
import {
  architectureParentBoundary,
  architectureRelationshipLabel,
  architectureStatusLabel,
} from "./architecture-inspector";

describe("architecture inspector labels", () => {
  it("expresses relationship direction from the selected resource", () => {
    const link = { source: "app", target: "db", type: "depends_on" as const };
    expect(architectureRelationshipLabel(link, "app")).toBe("Depends on");
    expect(architectureRelationshipLabel(link, "db")).toBe("Required by");
  });

  it("preserves symmetric network peering semantics", () => {
    const link = { source: "vnet-a", target: "vnet-b", type: "peered_with" as const };
    expect(architectureRelationshipLabel(link, "vnet-a")).toBe("Peers with");
    expect(architectureRelationshipLabel(link, "vnet-b")).toBe("Peers with");
  });

  it("preserves runtime-call direction semantics", () => {
    const link = { source: "app-a", target: "app-b", type: "runtime_calls" as const };
    expect(architectureRelationshipLabel(link, "app-a")).toBe("Calls");
    expect(architectureRelationshipLabel(link, "app-b")).toBe("Called by");
  });

  it("does not present unknown status as a reported state", () => {
    expect(architectureStatusLabel("unknown")).toBe("Status unavailable");
    expect(architectureStatusLabel("vm_deallocated")).toBe("Vm deallocated");
  });

  it("uses the most specific reported containment as the parent boundary", () => {
    const graph = {
      resources: [
        { id: "group", type: "resource-group", name: "Group", status: "unknown" },
        { id: "vnet", type: "network.vnet", name: "Network", status: "healthy", parent_id: "group" },
        { id: "subnet", type: "network.subnet", name: "Subnet", status: "healthy", parent_id: "group" },
      ],
      links: [{ source: "vnet", target: "subnet", type: "contains" as const }],
    };

    expect(architectureParentBoundary(graph, "subnet")?.id).toBe("vnet");
  });
});
