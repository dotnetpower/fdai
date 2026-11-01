import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";
import {
  EMPTY_MSRC_CSAF_FILTERS,
  PINNED_MSRC_CSAF_CATALOG,
  PINNED_MSRC_CSAF_RAW,
  buildMsrcCsafFacets,
  decodeMsrcCsafCatalog,
  filterMsrcCsafRows,
  msrcCsafHref,
  msrcCsafStateFromSearch,
} from "./msrc-csaf-controls.model";

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
});
