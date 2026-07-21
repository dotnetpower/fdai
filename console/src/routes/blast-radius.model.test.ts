import { describe, expect, test } from "vitest";
import { ReadApiError } from "../api";
import { blastRadiusFailure } from "./blast-radius";
import {
  blastRadiusHref,
  blastRadiusQueryFromSearch,
  blastRadiusRequestIsCurrent,
} from "./blast-radius.model";

describe("blast-radius route query", () => {
  test("rejects a simulation response superseded by a draft edit", () => {
    expect(blastRadiusRequestIsCurrent(4, 3)).toBe(false);
    expect(blastRadiusRequestIsCurrent(4, 4)).toBe(true);
  });

  test("decodes a shareable simulation query", () => {
    expect(blastRadiusQueryFromSearch(
      "?target=web-api&depth=4&links=contains,attached_to&view=production",
    )).toEqual({
      target: "web-api",
      depth: 4,
      links: ["contains", "attached_to"],
      architectureView: "production",
    });
  });

  test("bounds depth and removes unsupported links", () => {
    expect(blastRadiusQueryFromSearch("?depth=99&links=unknown")).toEqual({
      target: null,
      depth: 2,
      links: ["contains", "depends_on"],
      architectureView: null,
    });
  });

  test("builds a clean URL that round-trips", () => {
    const href = blastRadiusHref({
      target: "database-primary",
      depth: 3,
      links: ["depends_on"],
      architectureView: null,
    });
    expect(href).toBe("/blast-radius?target=database-primary&depth=3&links=depends_on");
    expect(blastRadiusQueryFromSearch(new URL(href, "http://localhost").search).target)
      .toBe("database-primary");
  });

  test("preserves draft tabs and an explicitly empty link selection", () => {
    const href = blastRadiusHref({
      target: "database-primary",
      depth: 2,
      links: [],
      architectureView: "production",
    }, "map");

    expect(href).toBe(
      "/blast-radius?target=database-primary&depth=2&links=none&view=production&result=map",
    );
    expect(blastRadiusQueryFromSearch(new URL(href, "http://localhost").search).links)
      .toEqual([]);
  });

  test("distinguishes an unwired simulator from operational failures", () => {
    expect(blastRadiusFailure(new ReadApiError(404, "Not Found")).status).toBe("unavailable");
    expect(blastRadiusFailure(new ReadApiError(501, "Not Implemented")).status).toBe("unavailable");
    expect(blastRadiusFailure(new ReadApiError(400, "invalid target"))).toEqual({
      status: "error",
      message: "invalid target",
    });
    expect(blastRadiusFailure(new ReadApiError(503, "inventory unavailable")).status)
      .toBe("unavailable");
    expect(blastRadiusFailure(new ReadApiError(500, "inventory failed"))).toEqual({
      status: "error",
      message: "inventory failed",
    });
  });
});
