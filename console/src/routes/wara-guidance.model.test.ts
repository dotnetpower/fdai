import { describe, expect, test } from "vitest";
import { decodeWaraDetail } from "./wara-controls.model";
import { fixtureControl, fixtureGuidance, signFixtureGuidance } from "./wara-guidance.fixture";
import { decodeWaraGuidance, guidanceMissingKoreanFields, guidanceText, verifyWaraGuidanceDigest } from "./wara-guidance.model";

describe("WARA illustrated detail boundary", () => {
  const image = {
    asset_id: `sha256-${"a".repeat(64)}`, digest: `sha256:${"a".repeat(64)}`,
    source_document_url: "https://learn.microsoft.com/en-us/azure/backup/backup-azure-vms-introduction",
    image_url: "https://learn.microsoft.com/en-us/azure/backup/media/backup-azure-vms-introduction/vmbackup-architecture.png",
    source_revision: "b".repeat(40), attribution: "Microsoft, CC BY 4.0, unmodified",
    license: "CC-BY-4.0" as const, license_url: "https://creativecommons.org/licenses/by/4.0/" as const,
    alt: { en: "VM snapshot transfer to a vault", ko: "VM 스냅샷을 자격 증명 모음으로 전송하는 구조" },
    caption: { en: "Reference architecture, not runtime evidence", ko: "실제 관측 정보가 아닌 참고 구조" },
    english_in_image_notice: { en: "Original English labels", ko: "그림 내부는 영어 원문입니다." },
  };

  test("preserves reviewed image provenance in the verified content without changing authority", async () => {
    const control = fixtureControl();
    const guidance = signFixtureGuidance({ ...fixtureGuidance(control), reference_image: image });
    const decoded = decodeWaraDetail({ ...control, guidance }, control.id);
    expect(decoded.guidance!.reference_image).toEqual(image);
    await expect(verifyWaraGuidanceDigest(decoded.guidance)).resolves.toBeUndefined();
    expect(decoded.execution_authority).toBe(false);
    expect(decoded.satisfaction).toBe("unknown");
  });

  test("normalizes an explicitly absent optional image without changing a legacy guide digest", async () => {
    const control = fixtureControl();
    const guidance = fixtureGuidance(control);
    const decoded = decodeWaraGuidance({ ...guidance, reference_image: null }, control);
    expect(decoded).toEqual(guidance);
    await expect(verifyWaraGuidanceDigest(decoded)).resolves.toBeUndefined();
  });

  test("counts missing reader translations without treating original citation titles as Korean defects", () => {
    const guide = fixtureGuidance();
    const missing = guidanceMissingKoreanFields(guide);
    expect(missing).toBeGreaterThan(0);
    expect(guidanceMissingKoreanFields({ ...guide, sources: [] })).toBe(missing);
    expect(guidanceMissingKoreanFields({ ...guide, title: { en: "Title" } })).toBe(missing + 1);
    expect(guidanceMissingKoreanFields({ ...guide, reference_image: image })).toBe(missing);
  });

  test.each([
    { asset_id: "../image" }, { digest: `sha256:${"b".repeat(64)}` },
    { source_revision: "main" }, { license: "unknown" },
    { source_document_url: "https://example.com/image" },
    { image_url: "https://learn.microsoft.com:443/en-us/image.png" },
    { image_url: "https://learn.microsoft.com/en-us/%2e%2e/image.png" },
    { image_url: "https://learn.microsoft.com/en-us/image.png?token=example" },
    { image_url: "javascript:alert(1)" }, { alt: { en: "<svg onload='x' />" } },
    { attribution: "x".repeat(513) },
  ])("rejects unreviewed image metadata %j", (change) => {
    const control = fixtureControl();
    expect(() => decodeWaraGuidance({
      ...fixtureGuidance(control), reference_image: { ...image, ...change },
    }, control)).toThrow(/WARA guidance/);
  });

  test("accepts a pinned, bilingual, content-addressed guide without changing assessment", async () => {
    const control = fixtureControl();
    const guidance = fixtureGuidance(control);
    const decoded = decodeWaraDetail({ ...control, guidance }, control.id);
    expect(decoded.description).toBe(control.description);
    expect(decoded.potential_benefits).toBe(control.potential_benefits);
    expect(decoded.guidance).toEqual(guidance);
    await expect(verifyWaraGuidanceDigest(decoded.guidance)).resolves.toBeUndefined();
    expect(decoded.satisfaction).toBe("unknown");
    expect(decoded.execution_authority).toBe(false);
  });

  test("distinguishes a missing old-snapshot guide from malformed content", () => {
    const control = fixtureControl();
    expect(decodeWaraDetail(control).guidance).toBeNull();
    expect(decodeWaraDetail({ ...control, guidance: null }).guidance).toBeNull();
    for (const guidance of [false, "", [], {}]) {
      expect(() => decodeWaraDetail({ ...control, guidance })).toThrow(/WARA guidance/);
    }
    expect(() => decodeWaraDetail(control, "different-selection")).toThrow(/selected recommendation/);
  });

  test.each(["recommendation_id", "source_revision", "source_digest", "lifecycle"] as const)("rejects mismatched %s", (key) => {
    const control = fixtureControl();
    expect(() => decodeWaraGuidance({ ...fixtureGuidance(control), [key]: "mismatch" }, control)).toThrow(/does not match/);
  });

  test("requires supported schema, English fallback, safe typed assets, and sufficient content", () => {
    const control = fixtureControl();
    const guidance = fixtureGuidance(control);
    const malformed = [
      { ...guidance, schema_version: "2.0.0" },
      { ...guidance, title: { ko: "영문 없음" } },
      { ...guidance, configuration: { ...guidance.configuration, after: [{ en: "One row" }] } },
      { ...guidance, verification_steps: [] },
      { ...guidance, diagram: { ...guidance.diagram, svg: "<svg onload='alert(1)'/>" } },
      { ...guidance, diagram: { ...guidance.diagram, id: "https://example.test/asset.svg" } },
      { ...guidance, diagram: { ...guidance.diagram, nodes: [...guidance.diagram.nodes, guidance.diagram.nodes[0]] } },
      { ...guidance, diagram: { ...guidance.diagram, edges: [...guidance.diagram.edges, guidance.diagram.edges[0]] } },
      { ...guidance, diagram: { ...guidance.diagram, edges: [{ ...guidance.diagram.edges[0], to: "unknown" }, guidance.diagram.edges[1]] } },
      { ...guidance, sources: [{ label: { en: "Unsafe source" }, kind: "aprl", url: "javascript:alert(1)" }] },
      { ...guidance, sources: [{ label: { en: "Unpinned source" }, kind: "aprl", url: "https://github.com/Azure/Azure-Proactive-Resiliency-Library-v2/blob/main/file.yaml" }] },
      { ...guidance, sources: [{ label: { en: "Wrong repository" }, kind: "aprl", url: `https://github.com/example/repo/blob/${control.source_revision}/file.yaml` }] },
    ];
    for (const value of malformed) expect(() => decodeWaraGuidance(value, control)).toThrow(/WARA guidance/);
  });

  test("rejects a validly shaped but tampered illustrated asset digest", async () => {
    const guidance = fixtureGuidance();
    await expect(verifyWaraGuidanceDigest({ ...guidance, title: { en: "Tampered material" } })).rejects.toThrow(/content_digest/);
  });

  test("accepts only the explicitly reviewed Citrix vendor source alongside pinned APRL provenance", async () => {
    const control = fixtureControl();
    const guidance = fixtureGuidance(control);
    const source = { kind: "vendor" as const, label: { en: "Citrix DaaS for Azure limits" }, url: "https://docs.citrix.com/us/en/citrix-daas-azure/limits.html" };
    const material = signFixtureGuidance({ ...guidance, sources: [...guidance.sources, source] });
    const decoded = decodeWaraGuidance(material, control);
    expect(decoded?.sources).toContainEqual(source);
    await expect(verifyWaraGuidanceDigest(decoded)).resolves.toBeUndefined();
    expect(() => decodeWaraGuidance({ ...material, sources: [source] }, control)).toThrow(/revision-pinned APRL source/);
  });

  test.each([
    "https://docs.citrix.com/us/en/citrix-daas-azure/overview.html",
    "https://docs.citrix.com/en-us/citrix-daas-azure/limits.html",
    "https://example.test/us/en/citrix-daas-azure/limits.html",
    "https://docs.citrix.com.example.test/us/en/citrix-daas-azure/limits.html",
    "https://learn.microsoft.com/us/en/citrix-daas-azure/limits.html",
    "http://docs.citrix.com/us/en/citrix-daas-azure/limits.html",
    "https://docs.citrix.com/us/en/citrix-daas-azure/limits.html?view=current",
    "https://docs.citrix.com/us/en/citrix-daas-azure/limits.html#limits",
    "https://docs.citrix.com:443/us/en/citrix-daas-azure/limits.html",
    "https://DOCS.CITRIX.COM/us/en/citrix-daas-azure/limits.html",
    "https://user@docs.citrix.com/us/en/citrix-daas-azure/limits.html",
    "https://docs.citrix.com/us/en/citrix-daas-azure/limit%73.html",
    "https://docs.citrix.com/us/en/citrix-daas-azure/../citrix-daas-azure/limits.html",
  ])("rejects every unapproved vendor URL, including normalized aliases: %s", (url) => {
    const control = fixtureControl();
    const guidance = fixtureGuidance(control);
    expect(() => decodeWaraGuidance({
      ...guidance, sources: [...guidance.sources, { kind: "vendor", label: { en: "Unapproved reference" }, url }],
    }, control)).toThrow(/approved source/);
  });

  test("uses mandatory English fallback without inventing translated content", () => {
    expect(guidanceText({ en: "English source" }, "ko")).toBe("English source");
    expect(guidanceText({ en: "English source", ko: "한국어 설명" }, "ko")).toBe("한국어 설명");
    expect(guidanceText({ en: "English source", ko: "한국어 설명" }, "en")).toBe("English source");
  });
});
