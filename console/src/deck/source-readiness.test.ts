import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, test } from "vitest";
import type { ReadDataSourcesPayload } from "../api-data-sources";
import {
  deckSourceReadiness,
  hasVerifiedSourceReadiness,
  latestSourceObservation,
} from "./source-readiness";

const payload: ReadDataSourcesPayload = {
  surface: "read-data-sources",
  sources: [
    {
      key: "inventory-source",
      source: "provider-inventory",
      routes: ["/inventory/graph"],
      availability: "available",
      configured: true,
      reachable: true,
      authoritative: true,
      durable: false,
      synthetic: false,
      reason: null,
      last_observed_at: "2026-08-04T10:00:00Z",
    },
    {
      key: "incident-source",
      source: "incident-ledger",
      routes: ["/incidents"],
      availability: "unavailable",
      configured: true,
      reachable: false,
      authoritative: true,
      durable: true,
      synthetic: false,
      reason: "Incident projection is unavailable.",
      last_observed_at: "2026-08-04T09:00:00Z",
    },
    {
      key: "audit-source",
      source: "audit-cache",
      routes: ["/audit"],
      availability: "available",
      configured: true,
      reachable: true,
      authoritative: false,
      durable: true,
      synthetic: false,
      reason: "The cache is not authoritative.",
      last_observed_at: "2026-08-04T11:00:00Z",
    },
  ],
};

describe("Command Deck source readiness", () => {
  test("projects fixed FDAI evidence slots without inferring missing sources", () => {
    const sources = deckSourceReadiness(payload);

    expect(sources.map((source) => [source.key, source.availability])).toEqual([
      ["inventory", "available"],
      ["incidents", "unavailable"],
      ["audit", "unknown"],
      ["knowledge", "unknown"],
      ["automation", "unknown"],
    ]);
  });

  test("reports the newest valid source observation", () => {
    expect(latestSourceObservation(deckSourceReadiness(payload))).toBe("2026-08-04T11:00:00Z");
  });

  test("distinguishes actionable readiness from an all-unknown manifest", () => {
    const sources = deckSourceReadiness(payload);
    expect(hasVerifiedSourceReadiness(sources)).toBe(true);
    expect(hasVerifiedSourceReadiness(sources.map((source) => ({
      ...source,
      availability: "unknown",
    })))).toBe(false);
  });

  test("renders the strip from the authoritative manifest client", () => {
    const source = readFileSync(
      fileURLToPath(new URL("./source-readiness-view.tsx", import.meta.url)),
      "utf8",
    );

    expect(source).toContain("client.dataSources()");
    expect(source).toContain("if (!hasVerifiedSourceReadiness(state.sources)) return null;");
    expect(source).toContain('class={`deck-source-status is-${item.availability}`}');
    expect(source).toContain('aria-label={`${t(`deck.sourceReadiness.source.${item.key}`)}: ${t(`deck.sourceReadiness.status.${item.availability}`)}`}');
    expect(source).not.toContain('<span class="sr-only">: {t(`deck.sourceReadiness.status.${item.availability}`)}</span>');
    expect(source).toContain("panelPath(SOURCE_PANELS[item.key])");
    expect(source).not.toContain("item.source?.source");
    expect(source).not.toContain("item.source?.reason");
  });
});
