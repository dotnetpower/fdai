import { describe, expect, it } from "vitest";
import { getLocale, setLocale } from "../i18n";
import { modelText } from "./settings-models.i18n";
import {
  filterCatalogModels,
  formatDisplayTimestamp,
  formatTpm,
  independentSecondaryCandidates,
  matchesModelQuery,
  modelReadinessState,
  nextModelWorkspaceView,
  presentModelStatus,
} from "./settings-models.presentation";
import type {
  GptModelCatalogEntryView,
  ModelSettingsView,
  T2ModelChoiceView,
} from "./settings-models.model";

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

  it("distinguishes a missing secondary model from a policy review", () => {
    expect(modelReadinessState(true, true)).toBe("ready");
    expect(modelReadinessState(false, false)).toBe("secondary-missing");
    expect(modelReadinessState(false, true)).toBe("review-required");
  });

  it.each([
    ["en", "T2 judgments stay unavailable until a secondary model from another publisher is reviewed and activated."],
    ["ko", "다른 공급자의 보조 모델을 검토하고 활성화할 때까지 T2 판단은 사용할 수 없습니다."],
  ] as const)("does not promise T1 availability when narration and the secondary are unavailable (%s)", (locale, expectedHint) => {
    const projection: Pick<ModelSettingsView, "narrator" | "t2ModelPolicy"> = {
      narrator: {
        revision: 0,
        requested: "auto",
        effective: "auto",
        fallbackReason: null,
        currentAutoPick: null,
        candidates: [],
      },
      t2ModelPolicy: {
        selectionScope: "governance-draft",
        invariant: "distinct-publisher",
        primaryCandidates: [],
        secondaryCandidates: [],
        activePrimary: null,
        activeSecondary: null,
        quorumReady: false,
      },
    };
    expect(projection.narrator.currentAutoPick).toBeNull();
    expect(projection.narrator.candidates).toHaveLength(0);
    expect(modelReadinessState(
      projection.t2ModelPolicy.quorumReady,
      projection.t2ModelPolicy.activeSecondary !== null,
    )).toBe("secondary-missing");

    const previousLocale = getLocale();
    try {
      setLocale(locale);
      expect(modelText("t2SecondaryMissingHint")).toBe(expectedHint);
    } finally {
      setLocale(previousLocale);
    }
  });

  it("moves predictably across model workspace views", () => {
    expect(nextModelWorkspaceView("overview", "ArrowLeft")).toBe("web-search");
    expect(nextModelWorkspaceView("catalog", "ArrowRight")).toBe("routing");
    expect(nextModelWorkspaceView("routing", "Home")).toBe("overview");
    expect(nextModelWorkspaceView("overview", "End")).toBe("web-search");
    expect(nextModelWorkspaceView("routing", "Enter")).toBe("routing");
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
