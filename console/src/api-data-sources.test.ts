import { describe, expect, test } from "vitest";

import {
  decodeReadDataSources,
  sourceForRoute,
  unavailableSourceReason,
} from "./api-data-sources";

const payload = {
  surface: "read-data-sources",
  sources: [
    {
      key: "operational-state",
      source: "empty-local-memory",
      routes: ["/audit", "/kpi"],
      availability: "unavailable",
      configured: true,
      reachable: true,
      authoritative: false,
      durable: false,
      synthetic: false,
      reason: "Authoritative operational state is not connected.",
      last_observed_at: null,
    },
  ],
};

describe("read data sources", () => {
  test("decodes provenance and finds the owner of a route", () => {
    const decoded = decodeReadDataSources(payload);
    expect(sourceForRoute(decoded, "/kpi")?.source).toBe("empty-local-memory");
    expect(unavailableSourceReason(decoded, "/audit"))
      .toBe("Authoritative operational state is not connected.");
    expect(unavailableSourceReason(decoded, "/models/settings")).toBeNull();
  });

  test("rejects malformed and duplicate source contracts", () => {
    expect(() => decodeReadDataSources({ ...payload, surface: "other" })).toThrow();
    expect(() => decodeReadDataSources({
      ...payload,
      sources: [...payload.sources, payload.sources[0]],
    })).toThrow(/unique/);
    expect(() => decodeReadDataSources({
      ...payload,
      sources: [{ ...payload.sources[0], routes: ["audit"] }],
    })).toThrow(/absolute paths/);
    expect(() => decodeReadDataSources({
      ...payload,
      sources: [
        payload.sources[0],
        { ...payload.sources[0], key: "other", routes: ["/audit"] },
      ],
    })).toThrow(/unique owners/);
  });

  test("distinguishes a non-authoritative source from an unavailable source", () => {
    const decoded = decodeReadDataSources({
      ...payload,
      sources: [{
        ...payload.sources[0],
        source: "local-process-metering",
        availability: "available",
        reachable: true,
        reason: null,
      }],
    });

    expect(unavailableSourceReason(decoded, "/kpi"))
      .toBe("Source operational-state is not authoritative.");
  });

  test("resolves query and descendant routes without crossing path segment boundaries", () => {
    const decoded = decodeReadDataSources({
      ...payload,
      sources: [
        { ...payload.sources[0], key: "processes", routes: ["/views/process"] },
        { ...payload.sources[0], key: "events", routes: ["/views/process/special"] },
      ],
    });

    expect(sourceForRoute(decoded, "/views/process?status=running")?.key).toBe("processes");
    expect(sourceForRoute(decoded, "/views/process/run-1/events")?.key).toBe("processes");
    expect(sourceForRoute(decoded, "/views/process/special/events")?.key).toBe("events");
    expect(sourceForRoute(decoded, "/views/processes")).toBeNull();
  });
});
