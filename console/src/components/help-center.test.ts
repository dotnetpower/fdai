import { describe, expect, test } from "vitest";
import {
  manualAssetUrl,
  manualOpenUrl,
  parseManualCatalog,
  resolveManualStudioUrl,
} from "./help-center";

const baseUrl = "https://manuals.example.com/fdai";
const validCatalog = {
  schemaVersion: 2,
  generatedAt: "2026-09-01T05:00:00Z",
  minimumSlidesByLevel: {
    L100: 5,
    L200: 10,
    L300: 20,
    L400: 30,
  },
  journey: {
    id: "fdai-value-to-scale",
    title: "FDAI Value-to-Scale Journey",
    stages: [
      stage(1, "understand-align"),
      stage(2, "envision-prioritize"),
      stage(3, "architect-validate", true),
      stage(4, "activate-realize"),
      stage(5, "scale-evolve"),
    ],
  },
  manuals: [{
    id: "fdai-overview",
    stageId: "understand-align",
    kind: "core",
    level: "L100",
    status: "complete",
    title: "FDAI overview",
    eyebrow: "PLATFORM OVERVIEW",
    description: "Introduction to the operating model.",
    createdAt: "2026-09-01",
    duration: "8 minutes",
    slideCount: 5,
    coverImage: "assets/platform-overview.jpeg",
    coverLabel: "CONTROL PLANE",
    featured: true,
  }],
};

function stage(number: number, id: string, differentiator = false) {
  return {
    id,
    number,
    title: `Stage ${number}`,
    question: `Question ${number}`,
    differentiator,
  };
}

describe("Manual Studio catalog boundary", () => {
  test("accepts the versioned catalog and resolves same-site links", () => {
    const parsed = parseManualCatalog(validCatalog, baseUrl);
    expect(parsed.manuals[0]?.id).toBe("fdai-overview");
    expect(parsed.manuals[0]?.level).toBe("L100");
    expect(manualAssetUrl(baseUrl, "assets/platform-overview.jpeg"))
      .toBe("https://manuals.example.com/fdai/assets/platform-overview.jpeg");
    expect(manualOpenUrl(baseUrl, "fdai-overview"))
      .toBe("https://manuals.example.com/fdai/library.html?manual=fdai-overview");
  });

  test.each([
    "https://tracker.example.com/pixel.gif",
    "//tracker.example.com/pixel.gif",
    "../pixel.gif",
    "/pixel.gif",
  ])("rejects an image path outside the configured Manual Studio base: %s", (coverImage) => {
    expect(() => parseManualCatalog({
      ...validCatalog,
      manuals: [{ ...validCatalog.manuals[0], coverImage }],
    }, baseUrl)).toThrow("unsafe coverImage path");
  });

  test("rejects malformed catalog metadata", () => {
    expect(() => parseManualCatalog({
      ...validCatalog,
      generatedAt: "today",
    }, baseUrl)).toThrow("generatedAt");
  });

  test("requires exactly five valid journey stages", () => {
    expect(() => parseManualCatalog({
      ...validCatalog,
      journey: { ...validCatalog.journey, stages: validCatalog.journey.stages.slice(0, 4) },
    }, baseUrl)).toThrow("five unique stages");
  });

  test("rejects unsupported manual levels", () => {
    expect(() => parseManualCatalog({
      ...validCatalog,
      manuals: [{ ...validCatalog.manuals[0], level: "L500" }],
    }, baseUrl)).toThrow("invalid level");
  });

  test("rejects obsolete catalog versions and incomplete published manuals", () => {
    expect(() => parseManualCatalog({
      ...validCatalog,
      schemaVersion: 1,
    }, baseUrl)).toThrow("schemaVersion 2");
    expect(() => parseManualCatalog({
      ...validCatalog,
      minimumSlidesByLevel: { ...validCatalog.minimumSlidesByLevel, L100: 6 },
    }, baseUrl)).toThrow("slide minimum");
  });

  test("validates deployed and development Manual Studio URLs", () => {
    expect(resolveManualStudioUrl("https://manuals.example.com/fdai/", false))
      .toBe("https://manuals.example.com/fdai");
    expect(resolveManualStudioUrl(undefined, true)).toBe("http://127.0.0.1:5474");
    expect(resolveManualStudioUrl(undefined, false)).toBeNull();
    expect(() => resolveManualStudioUrl("http://manuals.example.com", false))
      .toThrow("must be HTTPS");
    expect(() => resolveManualStudioUrl("https://manuals.example.com?tenant=example", false))
      .toThrow("must be HTTPS");
  });
});
