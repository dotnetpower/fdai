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
    const onDisk = JSON.parse(
      readFileSync(
        new URL("../../../rule-catalog/collected/msrc-csaf/crosswalk.json", import.meta.url),
        "utf8",
      ),
    ) as unknown;
    expect(PINNED_MSRC_CSAF_RAW).toEqual(onDisk);
    expect(PINNED_MSRC_CSAF_CATALOG.rows).toHaveLength(3);
    expect(PINNED_MSRC_CSAF_CATALOG.rows.every((row) => row.execution_authority === false)).toBe(true);
  });

  it("filters rows by severity, exploit_status, disposition, resource_type, and search query", () => {
    const rows = PINNED_MSRC_CSAF_CATALOG.rows;
    expect(
      filterMsrcCsafRows(rows, { ...EMPTY_MSRC_CSAF_FILTERS, exploit_status: "exploited" }).map(
        (r) => r.cve_id,
      ),
    ).toEqual(["CVE-2026-20001"]);
    expect(
      filterMsrcCsafRows(rows, { ...EMPTY_MSRC_CSAF_FILTERS, severity: "critical" }).map(
        (r) => r.cve_id,
      ),
    ).toEqual(["CVE-2026-20002"]);
    expect(
      filterMsrcCsafRows(rows, { ...EMPTY_MSRC_CSAF_FILTERS, q: "storage" }).map((r) => r.cve_id),
    ).toEqual(["CVE-2026-20002"]);
  });

  it("builds facet counts and round-trips route search state", () => {
    const facets = buildMsrcCsafFacets(PINNED_MSRC_CSAF_CATALOG.rows);
    expect(facets["by_exploit_status"]).toEqual({
      exploited: 1,
      exploitation_more_likely: 1,
      unproven: 1,
    });
    const href = msrcCsafHref(
      { ...EMPTY_MSRC_CSAF_FILTERS, exploit_status: "exploited", q: "aks" },
      "CVE-2026-20001",
    );
    const search = new URL(href, "http://localhost:5273").searchParams;
    expect(msrcCsafStateFromSearch(search)).toEqual({
      filters: {
        ...EMPTY_MSRC_CSAF_FILTERS,
        exploit_status: "exploited",
        q: "aks",
      },
      selected: "CVE-2026-20001",
    });
  });

  it("fails closed when an advisory signature is not verified", () => {
    const cloned = JSON.parse(JSON.stringify(PINNED_MSRC_CSAF_RAW)) as {
      advisories: Array<{ signature_verified: boolean }>;
    };
    cloned.advisories[0]!.signature_verified = false;
    expect(() => decodeMsrcCsafCatalog(cloned)).toThrow(/signature is not verified/);
  });
});
