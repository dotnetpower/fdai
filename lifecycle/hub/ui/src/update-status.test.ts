import { describe, expect, test } from "vitest";
import type { UpdateChange, UpdateCheckRecord } from "./api";
import {
  canApply, describeActionError, describeDetail, describePlanOutcome, describeReason,
  describeSchedule, hasUrgentRecall, outcomeBadge, shortDigest, summarizeChange,
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
    "adoption_rejected"])("failed %s is mapped", (code) => {
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
