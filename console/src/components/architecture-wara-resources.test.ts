import { describe, expect, test } from "vitest";
import { WARA_ARCHITECTURE_RESOURCE_VISUALS } from "./architecture-wara-resources";
import { hasExplicitVisualMapping, layerOf, resourceColorOf } from "./architecture-map.model";
import { architectureResourceAbbreviation } from "./architecture-resource-abbreviations";

describe("WARA canonical resource visual bindings", () => {
  test("wires every added source type and exact parent into every visual surface", () => {
    expect(Object.keys(WARA_ARCHITECTURE_RESOURCE_VISUALS)).toHaveLength(42);
    for (const [type, visual] of Object.entries(WARA_ARCHITECTURE_RESOURCE_VISUALS)) {
      expect(hasExplicitVisualMapping(type), type).toBe(true);
      expect(layerOf({ id: type, type, name: type, status: "unknown" })).toBe(visual.layer);
      expect(resourceColorOf({ id: type, type, name: type, status: "unknown" })).toMatch(/^#[0-9A-F]{6}$/);
      expect(architectureResourceAbbreviation(type)).toBe(visual.abbreviation);
    }
  });

  test.each([
    ["directory.managed-domain", "security", "aadds"],
    ["compute.desktop-host-pool", "runtime", "vdpool"],
    ["ml-model-registry", "data", "mlr"],
    ["event-topic", "messaging", "egt"],
    ["network.cdn-origin-group", "network", "cdnog"],
    ["observability.network-flow-log", "observability", "nwfl"],
    ["database.vm-cluster", "data", "dbcl"],
  ])("keeps the canonical meaning of %s", (type, layer, abbreviation) => {
    expect(layerOf({ id: type, type, name: type, status: "unknown" })).toBe(layer);
    expect(architectureResourceAbbreviation(type)).toBe(abbreviation);
  });
});
