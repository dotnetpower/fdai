import { readFileSync } from "node:fs";
import { describe, expect, test } from "vitest";
import { OperatorApiError } from "../api";
import { getLocale, setLocale } from "../i18n";
import { capabilityColumns, loadCapabilitiesState } from "./capabilities";
import {
  capabilityDestination,
  capabilityRequestPath,
  capabilityRoleMatch,
  capabilityRouteStateFromSearch,
  decodeCapabilities,
  isMutatingCapability,
  sortCapabilities,
} from "./capabilities.model";

const routeSource = readFileSync(new URL("./capabilities.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../styles.css", import.meta.url), "utf8");

describe("capability catalog provenance", () => {
  test("renders an unavailable state when the optional catalog is not served", async () => {
    const client = {
      panel: async () => { throw new OperatorApiError(404, "not found"); },
    };

    await expect(loadCapabilitiesState(client)).resolves.toEqual({
      status: "unavailable",
      message: expect.any(String),
    });
  });

  test("keeps a stable accessible name for the capability search control", () => {
    expect("Filter capabilities").toMatch(/filter capabilities/i);
  });

  test("counts only execute and breakglass declarations as mutating", () => {
    expect((["read", "simulate", "approve", "execute", "breakglass"] as const)
      .filter(isMutatingCapability)).toEqual(["execute", "breakglass"]);
  });

  test("maps declarations to non-authoritative operator request paths", () => {
    expect(capabilityRequestPath("read")).toEqual({ key: "directRead", tone: "info" });
    expect(capabilityRequestPath("simulate")).toEqual({ key: "governedRequest", tone: "shadow" });
    expect(capabilityRequestPath("approve")).toEqual({ key: "humanApproval", tone: "hil" });
    expect(capabilityRequestPath("execute")).toEqual({ key: "humanApproval", tone: "hil" });
    expect(capabilityRequestPath("breakglass")).toEqual({ key: "ownerBreakGlass", tone: "danger" });
  });

  test("decodes inert catalog metadata without implying execution eligibility", () => {
    const decoded = decodeCapabilities({
      source: "static-catalog",
      execution_eligibility: false,
      count: 1,
      capabilities: [{
        capability_id: "incident.inspect",
        name: "Inspect incident",
        category: "incident",
        summary: "Inspect bounded incident evidence.",
        side_effect_class: "read",
        default_mode: "shadow",
        required_role: "reader",
        slide_ref: null,
        tags: [],
        parity: "native",
        official_source: null,
        evidence_refs: [],
      }],
    });

    expect(decoded.source).toBe("static-catalog");
    expect(decoded.execution_eligibility).toBe(false);
    expect(decoded.capabilities[0]?.slide_ref).toBeNull();
    expect(decoded.capabilities[0]?.parity).toBe("native");
  });

  test("restores filters and selection from a canonical route", () => {
    expect(capabilityRouteStateFromSearch(new URLSearchParams(
      "q=restart&category=incident&effect=execute&role=owner&sort=role&page=3&capability=incident.restart",
    ))).toEqual({
      query: "restart",
      category: "incident",
      effect: "execute",
      role: "owner",
      sort: "role",
      page: 3,
      selectedId: "incident.restart",
    });
  });

  test("sorts declarations and maps exact owning surfaces", () => {
    const decoded = decodeCapabilities({
      source: "static-catalog",
      execution_eligibility: false,
      count: 2,
      capabilities: [
        capabilityItem({ capability_id: "devops.github", name: "GitHub", category: "knowledge" }),
        capabilityItem({ capability_id: "observability.topology", name: "Topology", category: "investigation" }),
      ],
    });

    expect(sortCapabilities(decoded.capabilities, "name").map((item) => item.name))
      .toEqual(["GitHub", "Topology"]);
    expect(capabilityDestination(decoded.capabilities[0]!))
      .toEqual({ routeId: "github", labelKey: "github" });
    expect(capabilityDestination(decoded.capabilities[1]!))
      .toEqual({ routeId: "architecture", labelKey: "architecture" });
  });

  test("compares server-verified ordinary roles without elevating BreakGlass", () => {
    expect(capabilityRoleMatch("reader", ["Reader"])).toBe("meets");
    expect(capabilityRoleMatch("contributor", ["Approver"])).toBe("meets");
    expect(capabilityRoleMatch("approver", ["Contributor"])).toBe("does-not-meet");
    expect(capabilityRoleMatch("reader", ["BreakGlass"])).toBe("does-not-meet");
    expect(capabilityRoleMatch("reader", null)).toBe("unavailable");
  });

  test("localizes capability table headers dynamically when locale changes", () => {
    const previous = getLocale();
    try {
      setLocale("en");
      const enHeader = capabilityColumns()[1]?.header;
      setLocale("ko");
      const koHeader = capabilityColumns()[1]?.header;
      expect(enHeader).toBeTruthy();
      expect(koHeader).toBeTruthy();
      expect(koHeader).not.toBe(enHeader);
    } finally {
      setLocale(previous);
    }
  });

  test("places selected capability details beside the directory on desktop", () => {
    expect(routeSource).toContain(
      'class={`capabilities-workspace${selectedId ? " has-selection" : ""}`}',
    );
    expect(routeSource).toContain('class="capability-detail-pane"');
    expect(routeSource).toContain(
      'scrollRegionLabel={t("governance.capabilities.tableAria")}',
    );
    expect(styles).toMatch(
      /\.capabilities-workspace\.has-selection\s*\{[^}]*display:\s*grid;[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)\s+minmax\(340px,\s*380px\);/s,
    );
    expect(styles).toMatch(
      /@media \(max-width:\s*1080px\)\s*\{[^}]*\.capabilities-workspace\.has-selection\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\);/s,
    );
  });

  test("rejects contradictory or ambiguous catalog evidence", () => {
    const item = {
      capability_id: "incident.restart",
      name: "Restart",
      category: "incident",
      summary: "Restart an incident target.",
      side_effect_class: "execute",
      default_mode: "shadow",
      required_role: "owner",
      slide_ref: "workflow-builder",
      tags: [],
      parity: "native",
      official_source: null,
      evidence_refs: [],
    };
    const root = {
      source: "static-catalog",
      execution_eligibility: false,
      count: 1,
      capabilities: [item],
    };
    expect(() => decodeCapabilities({ ...root, count: 2 })).toThrow(/count MUST match/);
    expect(() => decodeCapabilities({ ...root, capabilities: [item, item], count: 2 }))
      .toThrow(/ids MUST be unique/);
    expect(() => decodeCapabilities({ ...root, capabilities: [{ ...item, capability_id: " " }] }))
      .toThrow(/MUST NOT be empty/);
    expect(() => decodeCapabilities({ ...root, capabilities: [{ ...item, slide_ref: 8 }] }))
      .toThrow(/slide_ref MUST be a string/);
    expect(() => decodeCapabilities({
      ...root,
      capabilities: [{ ...item, side_effect_class: "unknown" }],
    })).toThrow(/side_effect_class is invalid/);
    expect(() => decodeCapabilities({
      ...root,
      capabilities: [{ ...item, default_mode: "observe" }],
    })).toThrow(/default_mode is invalid/);
    expect(() => decodeCapabilities({
      ...root,
      capabilities: [{ ...item, parity: "partial" }],
    })).toThrow(/capability.parity is invalid/);
    expect(() => decodeCapabilities({ ...root, execution_eligibility: true }))
      .toThrow(/MUST NOT grant execution/);
  });
});

function capabilityItem(overrides: Readonly<Record<string, unknown>> = {}) {
  return {
    capability_id: "incident.inspect",
    name: "Inspect incident",
    category: "incident",
    summary: "Inspect bounded incident evidence.",
    side_effect_class: "read",
    default_mode: "shadow",
    required_role: "reader",
    slide_ref: null,
    tags: [],
    parity: "native",
    official_source: null,
    evidence_refs: [],
    ...overrides,
  };
}
