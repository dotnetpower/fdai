// Plain-language mapping for the Updates page. Pure functions only: every backend code is turned
// into a sentence here, and an unknown code is shown verbatim instead of being hidden.
import type {
  IntegrityResult, IntegrityState, UpdateChange, UpdateCheckRecord, UpdateOutcome, UpdateStatus,
} from "./api";

export type BadgeVariant = "ok" | "warn" | "fail" | "info" | "mute";

const REASONS: Record<string, string> = {
  adoption_mode_review: "Automatic adoption is off, so every new catalog needs your review.",
  standing_authorization_missing:
    "Automatic adoption has no standing authorization on record, so your review is needed.",
  standing_authorization_expired:
    "The standing authorization for automatic adoption has expired, so your review is needed.",
  signature_not_verified: "The catalog signature could not be verified.",
  release_removed: "The new catalog removes a release that the accepted catalog contains.",
  release_replaced: "The new catalog changes the content of a release that already exists.",
  new_channel: "The new catalog introduces a channel that did not exist before.",
  channel_membership_removed: "The new catalog removes a release from a channel.",
  recall_lifted: "The new catalog lifts a recall that was in force.",
  recall_dropped: "The new catalog no longer lists a recall that was in force.",
  schema_range_widened: "The new catalog widens the tolerated schema range.",
  too_many_new_releases: "The new catalog adds more releases than automatic adoption allows.",
  integrity_not_verified:
    "The vendor's signed catalog roles could not be verified, so your review is needed.",
  timestamp_expired:
    "The vendor's signed timestamp has expired, so only recall changes can be adopted until fresh metadata arrives.",
  root_rotation_requires_review:
    "The vendor changed its offline root keys. A root rotation always needs your review.",
  policy_engine_unavailable: "The adoption policy engine is unavailable, so no automatic decision was made.",
  policy_evaluation_failed: "The adoption policy could not be evaluated, so no automatic decision was made.",
  policy_result_invalid: "The adoption policy returned an unusable result, so no automatic decision was made.",
};

const FAILURES: Record<string, string> = {
  source_unavailable: "The vendor catalog source could not be reached. Try again later.",
  signature_missing: "The vendor catalog has no signature, so it was not accepted.",
  signature_invalid: "The vendor catalog signature is invalid, so it was not accepted.",
  candidate_invalid: "The vendor catalog is malformed or not newer than the accepted one, so it was not accepted.",
  adoption_rejected: "The Hub refused to adopt the catalog. Nothing was changed.",
  integrity_not_verified:
    "The vendor's signed catalog roles could not be verified, so the catalog was not accepted.",
};

const INTEGRITY_REASONS: Record<string, string> = {
  catalog_version_rollback: "A signed record carries an older version than this Hub already verified.",
  catalog_root_signature_invalid: "The root record lacks enough valid offline-key signatures.",
  catalog_root_pin_mismatch: "The first root record does not match the root keys pinned in this Hub.",
  catalog_root_rotation_unsigned_by_previous:
    "A new root record was not signed by enough keys of the previous root.",
  catalog_root_chain_invalid: "The root record chain is incomplete or out of order.",
  catalog_root_expired: "The root record has expired.",
  catalog_root_export_key_missing: "The root record names no key for the catalog export.",
  catalog_root_equivocation: "The vendor served two different root records for one version.",
  catalog_snapshot_equivocation: "The vendor served two different snapshots for one version.",
  catalog_timestamp_equivocation: "The vendor served two different timestamps for one version.",
  catalog_snapshot_signature_invalid: "The snapshot signature is not valid for an authorized key.",
  catalog_timestamp_signature_invalid: "The timestamp signature is not valid for an authorized key.",
  timestamp_snapshot_mismatch: "The timestamp does not name the snapshot that was served.",
  recall_sequence_gap: "The recall sequence has a gap or went backwards, so a recall may be withheld.",
  export_digest_mismatch: "The catalog export does not match the digest the snapshot names.",
  snapshot_export_mismatch: "The snapshot does not describe the catalog that was served.",
  catalog_timestamp_expired: "The signed timestamp has expired.",
  allowed: "All signed records verified.",
};

/** One sentence for a catalog-role verification code. An unknown code is shown verbatim. */
export function describeIntegrityReason(code: string): string {
  return INTEGRITY_REASONS[code] ?? `Unrecognized integrity code: ${code}`;
}

export interface IntegrityView {
  badge: { label: string; variant: BadgeVariant };
  lines: string[];
}

/** The state to show for one verification: failed, expired, awaiting a rotation review, or fine. */
export function describeIntegrity(result: IntegrityResult): IntegrityView {
  if (!result.verified) {
    return { badge: { label: "Not verified", variant: "fail" }, lines: [describeIntegrityReason(result.reason)] };
  }
  if (result.root_rotation) {
    const next = result.root ? result.root.version : "a newer version";
    return {
      badge: { label: "Root rotation awaiting review", variant: "warn" },
      lines: [`The vendor rotated its offline root keys (root version ${result.previous_root_version} to ${next}). ` +
        "A rotation is never adopted automatically."],
    };
  }
  if (result.expired) {
    return {
      badge: { label: "Timestamp expired", variant: "warn" },
      lines: ["The signed timestamp has expired. Only recall roll-off Plans are issued until fresh metadata arrives.",
        ...(result.demote_operator_overrides_to_shadow
          ? ["Operator-override promotions return to shadow mode until then."] : [])],
    };
  }
  return { badge: { label: "Verified", variant: "ok" }, lines: [describeIntegrityReason(result.reason)] };
}

/** Whether the persisted timestamp has passed, judged now so an old check cannot look fresh. */
export function isTimestampExpired(state: IntegrityState, now: Date = new Date()): boolean {
  if (state.timestamp_expires_at === null) return true;
  const expiry = Date.parse(state.timestamp_expires_at);
  return Number.isNaN(expiry) || expiry <= now.getTime();
}

export function describeVersions(state: Pick<IntegrityState, "root_version" | "snapshot_version" | "timestamp_version">): string {
  return `Root v${state.root_version}, snapshot v${state.snapshot_version}, timestamp v${state.timestamp_version}`;
}

const UNCHANGED: Record<string, string> = {
  source_reports_current: "The vendor reports no newer catalog than the one already accepted.",
  digest_already_accepted: "The vendor catalog is identical to the one already accepted.",
};

export function describeReason(code: string): string {
  const known = REASONS[code];
  if (known) return known;
  const channel = /^channel_not_allowed:(.+)$/.exec(code);
  if (channel) {
    return `The new catalog publishes releases to channel ${channel[1]}, which automatic adoption does not allow.`;
  }
  return `Unrecognized reason code: ${code}`;
}

export function splitReasons(detail: string): string[] {
  return detail.split(",").map(part => part.trim()).filter(part => part.length > 0);
}

/** One human-readable sentence per code carried by a check record. */
export function describeDetail(outcome: UpdateOutcome, detail: string): string[] {
  switch (outcome) {
    case "unchanged":
      return [UNCHANGED[detail] ?? `Unrecognized status code: ${detail}`];
    case "failed":
      return [FAILURES[detail] ?? `Unrecognized failure code: ${detail}`];
    case "review_required": {
      const reasons = splitReasons(detail);
      return reasons.length === 0 ? ["A new catalog is waiting for your review."] : reasons.map(describeReason);
    }
    case "adopted":
      return ["The new catalog was adopted."];
    default:
      return [`Unrecognized status code: ${detail}`];
  }
}

const OUTCOMES: Record<UpdateOutcome, { label: string; variant: BadgeVariant }> = {
  unchanged: { label: "Up to date", variant: "ok" },
  adopted: { label: "Adopted", variant: "ok" },
  review_required: { label: "Review required", variant: "warn" },
  failed: { label: "Check failed", variant: "fail" },
};

export function outcomeBadge(outcome: string): { label: string; variant: BadgeVariant } {
  return OUTCOMES[outcome as UpdateOutcome] ?? { label: outcome, variant: "mute" };
}

export function shortDigest(sha256: string): string {
  return sha256.slice(0, 12);
}

export function describeSchedule(
  status: Pick<UpdateStatus, "mode" | "check_interval_seconds">,
): string {
  const adoption = `automatic adoption is ${status.mode === "auto" ? "on" : "off"}`;
  const seconds = status.check_interval_seconds;
  if (!(seconds > 0)) return `Periodic checks are off; ${adoption}.`;
  let every: string;
  if (seconds < 60) {
    every = seconds === 1 ? "second" : `${seconds} seconds`;
  } else if (seconds % 3600 === 0) {
    const hours = seconds / 3600;
    every = hours === 1 ? "hour" : `${hours} hours`;
  } else {
    const minutes = Math.round(seconds / 60);
    every = minutes === 1 ? "minute" : `${minutes} minutes`;
  }
  return `Checks the vendor catalog every ${every}; ${adoption}.`;
}

export interface ChangeSection {
  label: string;
  items: string[];
}

export function summarizeChange(change: UpdateChange): ChangeSection[] {
  const sections: ChangeSection[] = [
    {
      label: "Added releases",
      items: change.added_releases.map(
        r => `${r.release_id} (${r.channels.length > 0 ? r.channels.join(", ") : "no channel"})`),
    },
    { label: "Removed releases", items: [...change.removed_releases] },
    { label: "Changed releases", items: [...change.changed_releases] },
    {
      label: "Added to channels",
      items: change.channel_additions.map(c => `${c.release_id} in ${c.channel}`),
    },
    {
      label: "Removed from channels",
      items: change.channel_removals.map(c => `${c.release_id} from ${c.channel}`),
    },
    { label: "New channels", items: [...change.new_channels] },
    {
      label: "New recalls",
      items: change.new_recalls.map(r => `${r.scope} ${r.target} (sequence ${r.sequence})`),
    },
    {
      label: "Lifted recalls",
      items: change.lifted_recalls.map(r => `${r.scope} ${r.target} (sequence ${r.sequence})`),
    },
    {
      label: "Dropped recalls",
      items: (change.removed_recalls ?? []).map(
        r => `${r.scope} ${r.target} (sequence ${r.sequence})`,
      ),
    },
  ];
  const filled = sections.filter(section => section.items.length > 0);
  if (change.schema_widened) {
    filled.push({ label: "Schema", items: ["The tolerated schema range is widened."] });
  }
  return filled;
}

export function hasUrgentRecall(change: UpdateChange): boolean {
  return change.new_recalls.length > 0;
}

/** Only a verified-signature candidate that still awaits review may be applied from this page. */
export function canApply(record: UpdateCheckRecord | null): boolean {
  return record !== null && record.outcome === "review_required" &&
    record.candidate !== null && record.candidate.signature_verified &&
    // The Hub refuses everything but recalls while the signed timestamp is expired.
    !record.candidate.decision.reasons.includes("timestamp_expired");
}

const PLAN_OUTCOMES: Record<string, string> = {
  issued: "Plan issued",
  unchanged: "Plan unchanged",
  waiting: "Waiting for a maintenance window",
  "no-eligible-release": "No eligible release",
  "up-to-date": "Up to date",
  "no-managed-entity": "No managed Entity",
};

export function describePlanOutcome(outcome: string): string {
  return PLAN_OUTCOMES[outcome] ?? outcome;
}

export const CANDIDATE_CHANGED_MESSAGE =
  "The vendor catalog changed after you reviewed it. Nothing was applied. The new candidate is shown below; review it before applying.";

export function describeActionError(error: unknown): { message: string; candidateChanged: boolean } {
  const e = error as { status?: unknown; reasonCode?: unknown } | null;
  if (e && e.status === 409 && e.reasonCode === "candidate_changed") {
    return { message: CANDIDATE_CHANGED_MESSAGE, candidateChanged: true };
  }
  if (e && e.status === 422) {
    return { message: "The Hub rejected the request as invalid. Nothing was applied.", candidateChanged: false };
  }
  const code = e && typeof e.reasonCode === "string" ? e.reasonCode : null;
  return {
    message: code ? `The request failed (${code}). Nothing was applied.`
      : "The request failed. Nothing was applied.",
    candidateChanged: false,
  };
}
