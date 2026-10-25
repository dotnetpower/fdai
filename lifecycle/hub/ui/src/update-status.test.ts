import { describe, expect, test } from "vitest";
import type { IntegrityResult, IntegrityState, UpdateChange, UpdateCheckRecord } from "./api";
import {
  canApply, describeActionError, describeDetail, describeIntegrity, describeIntegrityReason,
  describePlanOutcome, describeReason, describeSchedule, describeVersions, hasUrgentRecall,
  isTimestampExpired, outcomeBadge, shortDigest, summarizeChange,
} from "./update-status";

const emptyChange: UpdateChange = {
  added_releases: [], removed_releases: [], changed_releases: [], channel_additions: [],
  channel_removals: [], new_channels: [], new_recalls: [], lifted_recalls: [], schema_widened: false,
};

function record(overrides: Partial<UpdateCheckRecord> & { verified?: boolean } = {}): UpdateCheckRecord {
  const { verified = true, ...rest } = overrides;
  return {
    checked_at: "2026-10-25T00:00:00Z", outcome: "review_required", detail: "adoption_mode_review",
    candidate: {
      revision: 7, sha256: "a".repeat(64), expires_at: "2026-11-25T00:00:00Z",
      signature_verified: verified, key_id: null, accepted_revision: 6,
      decision: { allow: false, reasons: ["adoption_mode_review"] }, change: emptyChange,
    },
    plans: [], ...rest,
  };
}

describe("describeReason", () => {
  test.each([
    "adoption_mode_review", "standing_authorization_missing", "standing_authorization_expired",
    "signature_not_verified", "release_removed", "release_replaced", "new_channel",
    "channel_membership_removed", "recall_lifted", "recall_dropped", "schema_range_widened", "too_many_new_releases",
    "policy_engine_unavailable", "policy_evaluation_failed", "policy_result_invalid",
    "integrity_not_verified", "timestamp_expired", "root_rotation_requires_review",
  ])("%s maps to a sentence without the raw code", (code) => {
    const text = describeReason(code);
    expect(text).not.toContain(code);
    expect(text.endsWith(".")).toBe(true);
  });

  test("channel_not_allowed names the channel", () => {
    expect(describeReason("channel_not_allowed:PROD")).toContain("PROD");
  });

  test("an unknown code is shown verbatim", () => {
    expect(describeReason("brand_new_code")).toContain("brand_new_code");
  });
});

describe("describeDetail", () => {
  test.each(["source_unavailable", "signature_missing", "signature_invalid", "candidate_invalid",
    "adoption_rejected", "integrity_not_verified"])("failed %s is mapped", (code) => {
    const [text] = describeDetail("failed", code);
    expect(text).not.toContain(code);
  });

  test.each(["source_reports_current", "digest_already_accepted"])("unchanged %s is mapped", (code) => {
    expect(describeDetail("unchanged", code)[0]).not.toContain(code);
  });

  test("review_required splits the comma-joined reasons", () => {
    const lines = describeDetail("review_required", "adoption_mode_review, channel_not_allowed:PROD");
    expect(lines).toHaveLength(2);
    expect(lines[1]).toContain("PROD");
  });

  test("an empty review detail still explains the state", () => {
    expect(describeDetail("review_required", "")).toHaveLength(1);
  });

  test("unknown failure and unchanged codes fall back to the raw code", () => {
    expect(describeDetail("failed", "mystery")[0]).toContain("mystery");
    expect(describeDetail("unchanged", "mystery")[0]).toContain("mystery");
  });

  test("adopted has a fixed sentence", () => {
    expect(describeDetail("adopted", "anything")).toEqual(["The new catalog was adopted."]);
  });
});

describe("outcomeBadge", () => {
  test("known outcomes carry distinct variants", () => {
    expect(outcomeBadge("failed").variant).toBe("fail");
    expect(outcomeBadge("review_required").variant).toBe("warn");
    expect(outcomeBadge("adopted").variant).toBe("ok");
    expect(outcomeBadge("unchanged").variant).toBe("ok");
  });

  test("an unknown outcome is muted and shows the raw value", () => {
    expect(outcomeBadge("weird")).toEqual({ label: "weird", variant: "mute" });
  });
});

describe("describeSchedule", () => {
  test("minutes", () => {
    expect(describeSchedule({ mode: "review", check_interval_seconds: 900 }))
      .toBe("Checks the vendor catalog every 15 minutes; automatic adoption is off.");
  });

  test("hours", () => {
    expect(describeSchedule({ mode: "auto", check_interval_seconds: 7200 }))
      .toBe("Checks the vendor catalog every 2 hours; automatic adoption is on.");
    expect(describeSchedule({ mode: "auto", check_interval_seconds: 3600 })).toContain("every hour;");
  });

  test("non-whole hours stay in minutes and a minute is singular", () => {
    expect(describeSchedule({ mode: "review", check_interval_seconds: 5400 })).toContain("90 minutes");
    expect(describeSchedule({ mode: "review", check_interval_seconds: 60 })).toContain("every minute;");
  });

  test("a disabled interval says periodic checks are off", () => {
    expect(describeSchedule({ mode: "review", check_interval_seconds: 0 }))
      .toBe("Periodic checks are off; automatic adoption is off.");
  });
});

describe("summarizeChange", () => {
  test("an unchanged diff has no sections", () => {
    expect(summarizeChange(emptyChange)).toEqual([]);
  });

  test("every populated field becomes a labelled section", () => {
    const sections = summarizeChange({
      added_releases: [{ release_id: "2.0.0", channels: ["DEV", "STG"], schema_target: 16 },
        { release_id: "2.0.1", channels: [], schema_target: null }],
      removed_releases: ["1.0.0"], changed_releases: ["1.1.0"],
      channel_additions: [{ channel: "STG", release_id: "1.1.0" }],
      channel_removals: [{ channel: "PROD", release_id: "0.9.0" }],
      new_channels: ["CANARY"],
      new_recalls: [{ scope: "release", target: "1.0.0", sequence: 3 }],
      lifted_recalls: [{ scope: "capability", target: "x", sequence: 2 }],
      schema_widened: true,
    });
    expect(Object.fromEntries(sections.map(s => [s.label, s.items]))).toEqual({
      "Added releases": ["2.0.0 (DEV, STG)", "2.0.1 (no channel)"],
      "Removed releases": ["1.0.0"], "Changed releases": ["1.1.0"],
      "Added to channels": ["1.1.0 in STG"], "Removed from channels": ["0.9.0 from PROD"],
      "New channels": ["CANARY"], "New recalls": ["release 1.0.0 (sequence 3)"],
      "Lifted recalls": ["capability x (sequence 2)"],
      Schema: ["The tolerated schema range is widened."],
    });
  });
});

describe("hasUrgentRecall and canApply", () => {
  test("only new recalls are urgent", () => {
    expect(hasUrgentRecall(emptyChange)).toBe(false);
    expect(hasUrgentRecall({ ...emptyChange, lifted_recalls: [{ scope: "r", target: "t", sequence: 1 }] }))
      .toBe(false);
    expect(hasUrgentRecall({ ...emptyChange, new_recalls: [{ scope: "r", target: "t", sequence: 1 }] }))
      .toBe(true);
  });

  test("apply needs review_required, a candidate, and a verified signature", () => {
    expect(canApply(record())).toBe(true);
    expect(canApply(record({ verified: false }))).toBe(false);
    expect(canApply(record({ outcome: "failed" }))).toBe(false);
    expect(canApply(record({ candidate: null }))).toBe(false);
    expect(canApply(null)).toBe(false);
  });
});

describe("describeActionError", () => {
  test("409 candidate_changed is recognized", () => {
    const result = describeActionError({ status: 409, reasonCode: "candidate_changed" });
    expect(result.candidateChanged).toBe(true);
    expect(result.message).toContain("changed");
  });

  test("other failures include the reason code but are not candidate changes", () => {
    expect(describeActionError({ status: 503, reasonCode: "boom" }))
      .toEqual({ message: "The request failed (boom). Nothing was applied.", candidateChanged: false });
    expect(describeActionError({ status: 422, reasonCode: "x" }).message).toContain("invalid");
    expect(describeActionError(new Error("net")).candidateChanged).toBe(false);
    expect(describeActionError(null).message).toContain("Nothing was applied");
  });
});

describe("small helpers", () => {
  test("shortDigest and describePlanOutcome", () => {
    expect(shortDigest("a".repeat(64))).toHaveLength(12);
    expect(describePlanOutcome("issued")).toBe("Plan issued");
    expect(describePlanOutcome("odd")).toBe("odd");
  });
});

function integrity(overrides: Partial<IntegrityResult> = {}): IntegrityResult {
  return {
    mode: "tuf", verified: true, reason: "allowed",
    root: { version: 2, expires_at: "2027-10-25T00:00:00Z" },
    snapshot: { version: 5, expires_at: "2026-11-01T00:00:00Z" },
    timestamp: { version: 9, expires_at: "2026-10-26T00:00:00Z" },
    expired: false, root_rotation: false, previous_root_version: 2, max_recall_sequence: 3,
    allowed_plan_types: ["install", "upgrade", "recall-rolloff"],
    demote_operator_overrides_to_shadow: false, ...overrides,
  };
}

function integrityState(overrides: Partial<IntegrityState> = {}): IntegrityState {
  return {
    mode: "tuf", root_version: 2, snapshot_version: 5, snapshot_expires_at: "2026-11-01T00:00:00Z",
    timestamp_version: 9, timestamp_expires_at: "2026-10-26T00:00:00Z", max_recall_sequence: 3,
    observed_at: "2026-10-25T00:00:00Z", last: integrity(), ...overrides,
  };
}

describe("describeIntegrity", () => {
  test("a verified result is ok and says everything verified", () => {
    const view = describeIntegrity(integrity());
    expect(view.badge).toEqual({ label: "Verified", variant: "ok" });
    expect(view.lines).toEqual(["All signed records verified."]);
  });

  test("an unverified result fails and explains the reason without the raw code", () => {
    const view = describeIntegrity(integrity({ verified: false, reason: "catalog_version_rollback" }));
    expect(view.badge.variant).toBe("fail");
    expect(view.lines[0]).toContain("older version");
    expect(view.lines[0]).not.toContain("catalog_version_rollback");
  });

  test("an expired timestamp warns that only recall roll-off proceeds and names the shadow return", () => {
    const view = describeIntegrity(integrity({
      expired: true, demote_operator_overrides_to_shadow: true, allowed_plan_types: ["recall-rolloff"],
    }));
    expect(view.badge).toEqual({ label: "Timestamp expired", variant: "warn" });
    expect(view.lines[0]).toContain("Only recall roll-off");
    expect(view.lines[1]).toContain("shadow mode");
    expect(describeIntegrity(integrity({ expired: true })).lines).toHaveLength(1);
  });

  test("a root rotation waits for review and shows both versions", () => {
    const view = describeIntegrity(integrity({
      root_rotation: true, previous_root_version: 1, root: { version: 2, expires_at: "2027-10-25T00:00:00Z" },
    }));
    expect(view.badge.variant).toBe("warn");
    expect(view.badge.label).toContain("Root rotation");
    expect(view.lines[0]).toContain("root version 1 to 2");
    expect(view.lines[0]).toContain("never adopted automatically");
    expect(describeIntegrity(integrity({ root_rotation: true, root: null })).lines[0])
      .toContain("a newer version");
  });

  test("failure reasons cover every code and show an unknown one verbatim", () => {
    for (const code of [
      "catalog_version_rollback", "catalog_root_signature_invalid", "catalog_root_pin_mismatch",
      "catalog_root_rotation_unsigned_by_previous", "catalog_root_chain_invalid", "catalog_root_expired",
      "catalog_root_export_key_missing", "catalog_root_equivocation", "catalog_snapshot_equivocation",
      "catalog_timestamp_equivocation", "catalog_snapshot_signature_invalid",
      "catalog_timestamp_signature_invalid", "timestamp_snapshot_mismatch", "recall_sequence_gap",
      "export_digest_mismatch", "snapshot_export_mismatch", "catalog_timestamp_expired",
    ]) {
      const text = describeIntegrityReason(code);
      expect(text).not.toContain(code);
      expect(text.endsWith(".")).toBe(true);
    }
    expect(describeIntegrityReason("brand_new")).toContain("brand_new");
  });
});

describe("persisted integrity state", () => {
  test("a timestamp is judged against now, not against the last check", () => {
    const state = integrityState();
    expect(isTimestampExpired(state, new Date("2026-10-25T12:00:00Z"))).toBe(false);
    expect(isTimestampExpired(state, new Date("2026-10-26T00:00:00Z"))).toBe(true);
    expect(isTimestampExpired(integrityState({ timestamp_expires_at: null }))).toBe(true);
    expect(isTimestampExpired(integrityState({ timestamp_expires_at: "garbage" }))).toBe(true);
  });

  test("versions read as one sentence fragment", () => {
    expect(describeVersions(integrityState())).toBe("Root v2, snapshot v5, timestamp v9");
  });

  test("an expired-timestamp candidate cannot be applied, but other review candidates can", () => {
    const expired = record();
    expired.candidate!.decision = { allow: false, reasons: ["timestamp_expired"] };
    expect(canApply(expired)).toBe(false);
    const rotation = record();
    rotation.candidate!.decision = { allow: false, reasons: ["root_rotation_requires_review"] };
    expect(canApply(rotation)).toBe(true);
  });
});
