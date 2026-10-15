import { describe, expect, it } from "vitest";
import {
  filterCatalogModels,
  formatDisplayTimestamp,
  formatTpm,
  independentSecondaryCandidates,
  matchesModelQuery,
  presentModelStatus,
} from "./settings-models.presentation";
import type { GptModelCatalogEntryView, T2ModelChoiceView } from "./settings-models.model";

const catalogModels: readonly GptModelCatalogEntryView[] = [
  {
    publisher: "OpenAI",
    family: "gpt-5.4",
    version: "2026-03-05",
    lifecycle: "GenerallyAvailable",
    skus: [{ name: "GlobalStandard", availableTpm: 125500 }],
    availableTpm: 125500,
    deployments: ["reasoner-primary"],
    deployed: true,
    provisionable: true,
    selectable: true,
    status: "deployed",
  },
  {
    publisher: "OpenAI",
    family: "gpt-preview",
    version: "2026-02-01",
    lifecycle: "Preview",
    skus: [],
    availableTpm: 0,
    deployments: [],
    deployed: false,
    provisionable: false,
    selectable: false,
    status: "quota-unavailable",
  },
];

function choice(publisher: string, family: string): T2ModelChoiceView {
  return {
    publisher,
    family,
    version: null,
    catalogStatus: "registry-only",
    deployments: [],
    availableTpm: 0,
    capacityUnit: "tpm",
    capacityValue: 0,
  };
}

describe("settings models presentation", () => {
  it("keeps non-selectable catalog evidence visible and searchable", () => {
    expect(filterCatalogModels(catalogModels, "")).toHaveLength(2);
    expect(filterCatalogModels(catalogModels, "Preview")).toEqual([catalogModels[1]]);
    expect(filterCatalogModels(catalogModels, "reasoner-primary")).toEqual([catalogModels[0]]);
  });

  it("preserves exact TPM instead of rounding to thousands", () => {
    expect(formatTpm(125500)).toBe("125,500 TPM");
    expect(formatTpm(0)).toBe("0 TPM");
  });

  it("offers only an independent secondary publisher", () => {
    const primary = choice("OpenAI", "gpt-5.4");
    const candidates = [primary, choice("Anthropic", "claude-sonnet")];
    expect(independentSecondaryCandidates(primary, candidates)).toEqual([candidates[1]]);
  });

  it("does not paint an unknown or unavailable status as success", () => {
    expect(presentModelStatus("available").tone).toBe("success");
    expect(presentModelStatus("unhealthy").tone).toBe("warning");
    expect(presentModelStatus("provider-specific").tone).toBe("neutral");
  });

  it("matches inventory queries across readable and technical fields", () => {
    expect(matchesModelQuery("APIM", ["t2.reasoner", "apim-gateway", 30])).toBe(true);
    expect(matchesModelQuery("30", ["t2.reasoner", "apim-gateway", 30])).toBe(true);
    expect(matchesModelQuery("missing", ["t2.reasoner", "apim-gateway", 30])).toBe(false);
  });

  it("formats an explicit timezone without invalid option combinations", () => {
    expect(formatDisplayTimestamp("2026-08-24T00:00:00Z", "en", "UTC")).toContain("UTC");
  });
});
