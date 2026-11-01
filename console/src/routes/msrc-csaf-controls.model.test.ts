import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  EMPTY_MSRC_CSAF_FILTERS,
  PINNED_MSRC_CSAF_CATALOG,
  PINNED_MSRC_CSAF_RAW,
  buildMsrcCsafFacets,
  decodeMsrcCsafCatalog,
  filterMsrcCsafRows,
  mergeMsrcCsafProjection,
  msrcCsafHref,
  msrcCsafStateFromSearch,
} from "./msrc-csaf-controls.model";
import { msrcCsafDisplayTitle, parseCvssVector } from "./msrc-csaf-guidance";

describe("msrc-csaf-controls model", () => {
  it("stays synchronized with the repository-pinned MSRC CSAF crosswalk catalog", () => {
    const manifest = JSON.parse(
      readFileSync(
        new URL("../../../rule-catalog/collected/msrc-csaf/crosswalk.json", import.meta.url),
        "utf8",
      ),
    ) as {
      readonly schema_version: string;
      readonly source_id: string;
      readonly source_revision: string;
      readonly advisories_digest: string;
      readonly crosswalk_digest: string;
      readonly product_mappings: readonly unknown[];
      readonly shards: ReadonlyArray<{ readonly path: string }>;
    };
    const advisories = manifest.shards.flatMap((shard) => {
      const parsed = JSON.parse(
        readFileSync(
          new URL(`../../../rule-catalog/collected/msrc-csaf/${shard.path}`, import.meta.url),
          "utf8",
        ),
      ) as { readonly advisories: readonly unknown[] };
      return parsed.advisories;
    });
    expect(PINNED_MSRC_CSAF_CATALOG.crosswalk_digest).toBe(manifest.crosswalk_digest);
    expect(advisories).toHaveLength(9057);
    expect(PINNED_MSRC_CSAF_CATALOG.rows).toHaveLength(9058);
    expect(PINNED_MSRC_CSAF_CATALOG.rows.every((row) => row.execution_authority === false)).toBe(true);
  });

  it("filters rows by year, severity, exploit_status, disposition, resource_type, and search query", () => {
    const rows = PINNED_MSRC_CSAF_CATALOG.rows;
    expect(
      filterMsrcCsafRows(rows, { ...EMPTY_MSRC_CSAF_FILTERS, exploit_status: "exploited" }).map(
        (r) => r.cve_id,
      ),
    ).toContain("CVE-2026-20001");
    expect(
      filterMsrcCsafRows(rows, { ...EMPTY_MSRC_CSAF_FILTERS, year: "2019" }),
    ).toHaveLength(1);
    expect(
      filterMsrcCsafRows(rows, { ...EMPTY_MSRC_CSAF_FILTERS, severity: "critical" }).map(
        (r) => r.cve_id,
      ),
    ).toContain("CVE-2026-20002");
    expect(
      filterMsrcCsafRows(rows, { ...EMPTY_MSRC_CSAF_FILTERS, q: "CVE-2026-20002" }).map(
        (r) => r.cve_id,
      ),
    ).toEqual(["CVE-2026-20002"]);
  });

  it("builds facet counts and round-trips route search state", () => {
    const facets = buildMsrcCsafFacets(PINNED_MSRC_CSAF_CATALOG.rows);
    expect(facets["by_exploit_status"]?.["exploited"]).toBeGreaterThanOrEqual(1);
    expect(facets["by_year"]?.["2026"]).toBe(4439);
    expect(facets["by_year"]?.["2025"]).toBeGreaterThanOrEqual(1246);
    expect(
      Object.values(facets["by_year"] ?? {}).reduce((sum, count) => sum + count, 0),
    ).toBe(9058);
    const href = msrcCsafHref(
      { ...EMPTY_MSRC_CSAF_FILTERS, year: "2025", exploit_status: "exploited", q: "aks" },
      "CVE-2026-20001",
      50,
    );
    const search = new URL(href, "http://localhost:5273").searchParams;
    expect(msrcCsafStateFromSearch(search)).toEqual({
      filters: {
        ...EMPTY_MSRC_CSAF_FILTERS,
        year: "2025",
        exploit_status: "exploited",
        q: "aks",
      },
      selected: "CVE-2026-20001",
      offset: 50,
    });
  });

  it("fails closed when an advisory signature is not verified", () => {
    const raw = PINNED_MSRC_CSAF_RAW as {
      readonly schema_version: string;
      readonly source_id: string;
      readonly source_revision: string;
      readonly advisories_digest: string;
      readonly crosswalk_digest: string;
      readonly product_mappings: readonly unknown[];
      readonly advisories: ReadonlyArray<Record<string, unknown>>;
      readonly vulnerability_mappings: readonly unknown[];
    };
    const minimal = {
      ...raw,
      advisories: [{ ...raw.advisories[0], signature_verified: false }],
      vulnerability_mappings: raw.vulnerability_mappings.slice(0, 1),
    };
    expect(() => decodeMsrcCsafCatalog(minimal)).toThrow(/signature is not verified/);
  });

  it("overlays Operator projection evaluations and rejects execution_authority or digest drift", () => {
    const merged = mergeMsrcCsafProjection(PINNED_MSRC_CSAF_CATALOG, {
      schema_version: "1.0.0",
      source_id: "msrc_csaf",
      source_revision: PINNED_MSRC_CSAF_CATALOG.source_revision,
      advisories_digest: PINNED_MSRC_CSAF_CATALOG.advisories_digest,
      crosswalk_digest: PINNED_MSRC_CSAF_CATALOG.crosswalk_digest,
      controls: [
        {
          cve_id: "CVE-2026-20001",
          evaluation_status: "evaluated",
          exposure: "affected",
          execution_authority: false,
        },
      ],
    });
    const row = merged.rows.find((r) => r.cve_id === "CVE-2026-20001");
    expect(row?.evaluation_status).toBe("evaluated");
    expect(row?.exposure).toBe("affected");

    expect(() =>
      mergeMsrcCsafProjection(PINNED_MSRC_CSAF_CATALOG, {
        schema_version: "1.0.0",
        source_id: "msrc_csaf",
        source_revision: PINNED_MSRC_CSAF_CATALOG.source_revision,
        advisories_digest: PINNED_MSRC_CSAF_CATALOG.advisories_digest,
        crosswalk_digest: PINNED_MSRC_CSAF_CATALOG.crosswalk_digest,
        controls: [
          {
            cve_id: "CVE-2026-20001",
            evaluation_status: "evaluated",
            exposure: "affected",
            execution_authority: true,
          },
        ],
      }),
    ).toThrow(/MUST NOT carry execution_authority/);

    // C34: Reject unknown or duplicate cve_id in Operator projection
    expect(() =>
      mergeMsrcCsafProjection(PINNED_MSRC_CSAF_CATALOG, {
        schema_version: "1.0.0",
        source_id: "msrc_csaf",
        source_revision: PINNED_MSRC_CSAF_CATALOG.source_revision,
        advisories_digest: PINNED_MSRC_CSAF_CATALOG.advisories_digest,
        crosswalk_digest: PINNED_MSRC_CSAF_CATALOG.crosswalk_digest,
        controls: [
          {
            cve_id: "CVE-1999-99999",
            evaluation_status: "evaluated",
            exposure: "affected",
            execution_authority: false,
          },
        ],
      }),
    ).toThrow(/unknown or duplicated/);
  });

  it("supports exposure filtering, product/rule search, Korean title suffixes, and temporal CVSS dimensions (C31-C36)", () => {
    const facets = buildMsrcCsafFacets(PINNED_MSRC_CSAF_CATALOG.rows);
    expect(facets["by_exposure"]?.["unknown"]).toBe(9058);
    expect(
      filterMsrcCsafRows(PINNED_MSRC_CSAF_CATALOG.rows, {
        ...EMPTY_MSRC_CSAF_FILTERS,
        q: "secret-store.soft-delete.enable",
      }).length,
    ).toBeGreaterThanOrEqual(1);
    expect(
      msrcCsafDisplayTitle({ title: "Azure Service Memory Corruption Vulnerability" }, "ko"),
    ).toContain("메모리 손상 취약점");
    const dims = parseCvssVector("CVSS:3.1/AV:N/AC:L/PR:N/UI:N/S:C/C:H/I:H/A:H/E:F/RL:O/RC:C");
    expect(dims.map((d) => d.code)).toContain("E:F");
    expect(dims.map((d) => d.code)).toContain("RL:O");
    expect(dims.map((d) => d.code)).toContain("RC:C");
  });
});
