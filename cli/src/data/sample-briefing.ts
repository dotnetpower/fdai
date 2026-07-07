/**
 * Synthetic briefing payload - customer-agnostic, all values fabricated.
 *
 * Mirrors the mock at `mocks/ui-cli/app.js`. `mode` selects the two world
 * states the console can open on: `needs-me` (HIL decisions pending) and
 * `all-clear` (nothing to sign off).
 */

import type { BriefingPayload, HilItem } from "../view-model/contract.js";

export type BriefingMode = "needs-me" | "all-clear";

const HIL: readonly HilItem[] = [
  {
    risk: "MEDIUM",
    chip: "needs your approval",
    chipSideEffect: "approve",
    title: "Give payments-api more memory",
    actionType: "scale-memory - payments-api",
    change: "Raise the memory limit from 512 MB to 1 GB",
    why: "It ran out of memory twice in the last hour (incident #1204).",
    basis: "Looks 91% like incident #0847, which we already fixed this way.",
    basisTech: "T1 - similarity 0.91",
    safety: "Affects 1 pod - auto-stops if CPU goes over 80% - fully reversible.",
    how: "Opens a pull request for review. Nothing changes until it is merged.",
    who: "Needs 1 approver who is not the requester - that is you.",
    check: "Dry run passed - no rules broken.",
    reference: "#5521",
    irreversible: false,
  },
  {
    risk: "HIGH",
    chip: "high-risk - needs two approvers",
    chipSideEffect: "breakglass",
    title: "Rotate the production signing key",
    actionType: "rotate-key - kv-prod",
    change: "Replace the signing key with a fresh one",
    why: "The key is more than 90 days old (security policy kv-014).",
    basis: "A fixed security rule flagged it.",
    basisTech: "T0 - policy match",
    safety:
      "Affects 1 key - apps reload it automatically - stops if errors go over 1%. Cannot be undone, only rolled forward.",
    how: "Opens a pull request for review.",
    who: "High-risk, so it needs 2 approvers, none of them the requester.",
    check: "Dry run passed - apps support hot reload.",
    reference: "#7781",
    irreversible: true,
  },
  {
    risk: "LOW",
    chip: "your review",
    chipSideEffect: "read",
    title: "Turn on the 'idle disk cleanup' rule for real",
    actionType: "promote-rule - disk-idle-30d",
    change: "Move the rule from trial to live",
    why: "Trialed for 30 days: 41 of 41 correct, nothing slipped through.",
    basis: "A fixed cost rule, proven over the trial.",
    basisTech: "T0 - trial to live",
    safety:
      "Only ever proposes cleanups as pull requests - switches back to trial if anything slips.",
    how: "Opens a pull request for review.",
    who: "Needs 1 reviewer.",
    check: "Replayed the 30-day trial - same results.",
    reference: "#9002",
    irreversible: false,
  },
];

const THROUGHPUT: readonly number[] = [
  120, 140, 135, 160, 210, 260, 240, 300, 520, 610, 700, 900, 1180, 1240, 980,
  760, 540, 430, 360, 300, 280, 240, 200, 170,
];

export function sampleBriefing(mode: BriefingMode): BriefingPayload {
  return {
    env: "staging",
    operator: "Alice",
    clock: "09:41 UTC",
    windowLabel: "the past 24 hours",
    events: 1204,
    autoResolved: 1201,
    rollbacks: 0,
    shadowCandidates: 6,
    overridesActive: 2,
    tiers: [
      { tier: "T0", name: "Handled by fixed rules", pct: 74 },
      { tier: "T1", name: "Matched a past case", pct: 18 },
      { tier: "T2", name: "Needed AI reasoning", pct: 8 },
    ],
    throughput: THROUGHPUT,
    peakHourLabel: "13:00 UTC",
    hil: mode === "needs-me" ? HIL : [],
    suggestions: [
      "why did payments-api restart?",
      "how's spending trending this week?",
      "what new rules are being trialed?",
    ],
  };
}
