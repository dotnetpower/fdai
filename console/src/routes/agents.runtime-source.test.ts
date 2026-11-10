import { describe, expect, test } from "vitest";
import {
  agentActivitySnapshotSource,
  agentEvidenceAvailable,
  agentObservationSource,
} from "./agents.runtime-source";

describe("agent runtime source fallback", () => {
  test("uses the durable activity projection when the live stream is unavailable", () => {
    expect(agentActivitySnapshotSource("durable-operational-projection")).toBe(
      "runtime-observed",
    );
    expect(agentEvidenceAvailable("closed", true)).toBe(true);
    expect(agentObservationSource("closed", "unknown", "runtime-observed")).toBe(
      "runtime-observed",
    );
  });

  test("keeps an open stream authoritative over retained activity", () => {
    expect(agentEvidenceAvailable("open", false)).toBe(true);
    expect(agentObservationSource("open", "runtime-observed", "replay")).toBe(
      "runtime-observed",
    );
  });
});
