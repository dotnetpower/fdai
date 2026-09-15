import { describe, expect, test } from "vitest";

import {
  coverageResourceHref,
  filterCoverageResources,
  parseCoverageResourceControls,
} from "./detection-coverage-state";
import { decodeAnalyzerCoverage } from "./detection-readiness.analyzer-run";
import { sampleDetectionReadiness } from "./operations.sample-readiness";

const coverage = decodeAnalyzerCoverage(
  sampleDetectionReadiness().analyzer_coverage,
);
if (coverage.status !== "available") throw new Error("Sample coverage must be available");
const resources = coverage.resources;

describe("Detection coverage resource state", () => {
  test("parses only supported URL controls", () => {
    expect(parseCoverageResourceControls(new URLSearchParams(
      "q=mysql&type=mysql-server&state=evaluation_error&sort=name&resource=db-1",
    ))).toEqual({
      query: "mysql",
      resourceType: "mysql-server",
      evaluation: "evaluation_error",
      sort: "name",
      selectedRef: "db-1",
    });
    expect(parseCoverageResourceControls(new URLSearchParams(
      "state=healthy&sort=random",
    ))).toMatchObject({ evaluation: "all", sort: "attention" });
  });

  test("preserves locale and Sample mode in shareable resource URLs", () => {
    const href = coverageResourceHref(
      "/detection-coverage",
      new URLSearchParams("data=sample&locale=ko"),
      {
        query: "mysql",
        resourceType: "mysql-server",
        evaluation: "evaluation_error",
        sort: "name",
        selectedRef: "example-mysql-server",
      },
    );

    expect(href).toBe(
      "/detection-coverage?data=sample&locale=ko&q=mysql&type=mysql-server"
      + "&state=evaluation_error&sort=name&resource=example-mysql-server"
      + "#detection-resources",
    );
  });

  test("filters and prioritizes attention without inventing health", () => {
    const filtered = filterCoverageResources(resources, {
      query: "",
      resourceType: "all",
      evaluation: "all",
      sort: "attention",
      selectedRef: null,
    });

    expect(filtered.map((resource) => resource.evaluation_state)).toEqual([
      "evaluation_error",
      "finding",
      "evaluated_no_finding",
      "evaluated_no_finding",
      "evaluated_no_finding",
    ]);
    expect(filterCoverageResources(resources, {
      query: "timeout",
      resourceType: "all",
      evaluation: "all",
      sort: "attention",
      selectedRef: null,
    }).map((resource) => resource.resource_ref)).toEqual([
      "example-mysql-server",
    ]);
  });
});
