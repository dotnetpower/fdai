import { afterEach, describe, expect, it } from "vitest";
import { setLocale } from "../i18n";
import type { AuditItem } from "../types";
import {
  incidentCommandSummary,
  incidentDisplayTitle,
  incidentHandoffSteps,
  incidentPageMatchesSnapshot,
  incidentDisplayIdentifier,
  incidentRosterStage,
  incidentVerticalDisplayLabel,
  mergeOlderAuditItems,
  mergeIncidentItems,
  normalizeIncidentSearch,
  parseIncidentSeverity,
  parseIncidentVertical,
  resolveIncidentSelection,
} from "./incidents";
import { incidentTimelinePresentation } from "./incidents.timeline";

const incidents = [
  { correlation_id: "correlation-1" },
  { correlation_id: "correlation-2" },
];

afterEach(() => setLocale("en"));

describe("incident deep-link selection", () => {
  it("uses the first incident only when no correlation was requested", () => {
    expect(resolveIncidentSelection(incidents, null)).toBe("correlation-1");
    expect(resolveIncidentSelection([], null)).toBeNull();
  });

  it("preserves an explicit correlation that is not in the loaded page", () => {
    expect(resolveIncidentSelection(incidents, "missing-correlation"))
      .toBe("missing-correlation");
  });
});

describe("incident route filters", () => {
  it("normalizes a bounded server search without accepting an oversized deep link", () => {
    expect(normalizeIncidentSearch("  Compute   VM  ")).toBe("Compute VM");
    expect(normalizeIncidentSearch("x".repeat(201))).toBe("");
    expect(normalizeIncidentSearch(null)).toBe("");
  });

  it("normalizes the four server-supported vertical values", () => {
    expect(parseIncidentVertical("change-safety")).toBe("change_safety");
    expect(parseIncidentVertical("COST_GOVERNANCE")).toBe("cost_governance");
    expect(parseIncidentVertical("resilience")).toBe("resilience");
    expect(parseIncidentVertical("unknown")).toBe("unknown");
  });

  it("drops unsupported or empty vertical values", () => {
    expect(parseIncidentVertical("../../other")).toBeNull();
    expect(parseIncidentVertical("")).toBeNull();
    expect(parseIncidentVertical(null)).toBeNull();
  });

  it("localizes the active vertical summary", () => {
    setLocale("ko");
    expect(incidentVerticalDisplayLabel("change_safety")).toBe("변경 안전");
  });

  it("normalizes the five server-supported severity values", () => {
    expect(parseIncidentSeverity("CRITICAL")).toBe("critical");
    expect(parseIncidentSeverity(" low ")).toBe("low");
    expect(parseIncidentSeverity("unknown")).toBe("unknown");
  });

  it("drops an unsupported or empty severity so the roster cannot filter client-side", () => {
    expect(parseIncidentSeverity("sev2")).toBeNull();
    expect(parseIncidentSeverity("")).toBeNull();
    expect(parseIncidentSeverity(null)).toBeNull();
  });
});

describe("incident pagination", () => {
  it("keeps roster order and removes duplicate correlation ids", () => {
    const current = [{ correlation_id: "a" }, { correlation_id: "b" }];
    const incoming = [{ correlation_id: "b" }, { correlation_id: "c" }];
    expect(mergeIncidentItems(current as never, incoming as never).map((item) => item.correlation_id))
      .toEqual(["a", "b", "c"]);
  });

  it("can prepend one exact deep-link result without duplicating the roster", () => {
    const current = [{ correlation_id: "a" }, { correlation_id: "b" }];
    const exact = [{ correlation_id: "b" }];
    expect(mergeIncidentItems(exact as never, current as never).map((item) => item.correlation_id))
      .toEqual(["b", "a"]);
  });

  it("rejects a page from a different analytical snapshot", () => {
    expect(incidentPageMatchesSnapshot({ snapshot_seq: 42 }, { snapshot_seq: 42 })).toBe(true);
    expect(incidentPageMatchesSnapshot({ snapshot_seq: 42 }, { snapshot_seq: 43 })).toBe(false);
  });

  it("prepends older audit pages in chronological order without duplicate rows", () => {
    const current = [
      { ...auditItem("incident.transition", "Saga", {}), seq: 3 },
      { ...auditItem("incident.transition", "Saga", {}), seq: 4 },
    ];
    const incomingNewestFirst = [
      { ...auditItem("incident.transition", "Saga", {}), seq: 3 },
      { ...auditItem("incident.open", "Huginn", {}), seq: 2 },
      { ...auditItem("incident.open", "Huginn", {}), seq: 1 },
    ];

    expect(mergeOlderAuditItems(current, incomingNewestFirst).map((item) => item.seq))
      .toEqual([1, 2, 3, 4]);
  });
});

describe("incident command presentation", () => {
  it("summarizes only loaded and bounded server-owned evidence", () => {
    const summary = incidentCommandSummary([
      { disposition: "awaiting_hil", verdict: "hil" },
      { disposition: "action_delivered", verdict: "auto" },
      { disposition: "unknown", verdict: "hil" },
    ] as never, {
      cohorts: {
        agent_mitigated: 3,
        agent_assisted: 2,
        human_mitigated: 1,
        pending: 8,
        integrity_excluded: 4,
      },
    });

    expect(summary).toEqual({
      loaded: 3,
      needsApproval: 1,
      verifiedOutcomes: 6,
      pendingOutcomes: 8,
    });
  });

  it("maps roster state onto the four visible response stages", () => {
    expect(incidentRosterStage({ status: "open", disposition: "pending" }))
      .toEqual({ key: "investigate", step: 1 });
    expect(incidentRosterStage({ status: "open", disposition: "awaiting_hil" }))
      .toEqual({ key: "approval", step: 2 });
    expect(incidentRosterStage({ status: "open", disposition: "unknown" }))
      .toEqual({ key: "investigate", step: 1 });
    expect(incidentRosterStage({ status: "in_progress", disposition: "action_delivered" }))
      .toEqual({ key: "respond", step: 3 });
    expect(incidentRosterStage({ status: "resolved", disposition: "resolved" }))
      .toEqual({ key: "verify", step: 4 });
  });

  it("keeps the latest contribution per owner in chronological order", () => {
    const items = [
      { ...auditItem("incident.open", "Huginn", {}), seq: 1 },
      { ...auditItem("rca.hypothesis", "Forseti", { rca_outcome: "recorded" }), seq: 2 },
      { ...auditItem("incident.members", "Huginn", { member_event_ids: ["event-2"] }), seq: 3 },
    ];

    expect(incidentHandoffSteps(items)).toMatchObject([
      { seq: 2, owner: "Forseti" },
      { seq: 3, owner: "Huginn" },
    ]);
  });
});

describe("incident title presentation", () => {
  it("keeps an evidence-backed title", () => {
    expect(incidentDisplayTitle(
      { title: "Checkout latency increased", title_source: "recorded_summary" },
      "Title unavailable",
    )).toBe("Checkout latency increased");
  });

  it("does not present an identifier fallback as the incident subject", () => {
    expect(incidentDisplayTitle(
      { title: "Incident corr-1", title_source: "identifier_fallback" },
      "Title unavailable",
    )).toBe("Title unavailable");
  });

  it("falls back to the correlation id for a legacy incident", () => {
    const summary = {
      correlation_id: "live-proof-correlation",
      incident_id: "00000000-0000-0000-0000-000000000000",
      incident_number: null,
    };
    expect(incidentDisplayIdentifier(summary)).toBe("live-proof-correlation");
  });

  it("shows the operator-facing incident number when one was assigned", () => {
    expect(incidentDisplayIdentifier({
      correlation_id: "live-proof-correlation",
      incident_number: "INC-202608-0000",
    })).toBe("INC-202608-0000");
  });
});

function auditItem(
  actionKind: string,
  actor: string,
  entry: Record<string, unknown>,
): AuditItem {
  return {
    seq: 1,
    event_id: "event-1",
    correlation_id: "correlation-1",
    actor,
    action_kind: actionKind,
    mode: "shadow",
    entry,
    entry_hash: "hash-1",
    previous_hash: "hash-0",
    recorded_at: "2026-07-28T06:43:55Z",
  };
}

describe("incident timeline presentation", () => {
  it("explains an incident opening and names the responsible agent", () => {
    const presentation = incidentTimelinePresentation(auditItem(
      "incident.open",
      "Heimdall",
      { severity: "sev3", state: "open", member_event_ids: ["event-1"] },
    ));

    expect(presentation.title).toBe("Incident opened");
    expect(presentation.description).toBe(
      "Opened a SEV3 incident and began correlating related signals.",
    );
    expect(presentation.owner).toBe("Heimdall");
    expect(presentation.ownerKind).toBe("agent");
    expect(presentation.facts).toContainEqual({ label: "Related signals", value: "1" });
  });

  it("uses a recorded reason and labels non-agent notification ownership honestly", () => {
    const presentation = incidentTimelinePresentation(auditItem(
      "notification.escalation",
      "fdai.notifications.hil_sink",
      { reason: "No configured channel accepted the alert.", severity: "warn" },
    ));

    expect(presentation.title).toBe("Notification escalation required");
    expect(presentation.description).toBe(
      "Notification delivery could not complete and requires operator attention. " +
      "Recorded reason: No configured channel accepted the alert.",
    );
    expect(presentation.owner).toBe("Notification delivery");
    expect(presentation.ownerKind).toBe("service");
  });

  it("prefers an audit summary and producer principal for a generic action", () => {
    const presentation = incidentTimelinePresentation(auditItem(
      "compute.restart",
      "fdai.runtime",
      {
        producer_principal: "Thor",
        summary: "Restarted the unhealthy compute instance after policy verification.",
        outcome: "applied",
      },
    ));

    expect(presentation.title).toBe("Compute restart");
    expect(presentation.description).toContain("Restarted the unhealthy compute instance");
    expect(presentation.owner).toBe("Thor");
    expect(presentation.facts).toContainEqual({ label: "Outcome", value: "Applied" });
  });

  it("uses singular wording for one correlated signal", () => {
    const presentation = incidentTimelinePresentation(auditItem(
      "incident.members",
      "Heimdall",
      { member_event_ids: ["event-1"] },
    ));

    expect(presentation.description).toBe("Attached one related signal to this incident.");
  });

  it("localizes known severity values in Korean timeline text", () => {
    setLocale("ko");

    const presentation = incidentTimelinePresentation(auditItem(
      "incident.open",
      "Heimdall",
      { severity: "high", state: "open" },
    ));

    expect(presentation.description).toContain("높음");
    expect(presentation.facts).toContainEqual({ label: "심각도", value: "높음" });
  });

  it("quotes a recorded RCA abstention instead of restating the action kind", () => {
    const presentation = incidentTimelinePresentation(auditItem(
      "rca.hypothesis",
      "fdai.core.rca",
      { rca_tier: "t2", rca_outcome: "abstained", rca_reason: "t2_reasoner_abstained" },
    ));

    expect(presentation.title).toBe("RCA hypothesis");
    expect(presentation.description).toBe(
      "Root-cause analysis recorded abstained: T2 reasoner abstained.",
    );
  });

  it("quotes a recorded T1 verdict and its reason", () => {
    const presentation = incidentTimelinePresentation(auditItem(
      "control_loop.t1_evaluate",
      "fdai.core.control_loop",
      { t1_outcome: "abstain", t1_reason: "no_neighbour_found" },
    ));

    expect(presentation.title).toBe("Control loop T1 evaluate");
    expect(presentation.description).toBe("T1 similarity recorded abstain: no neighbour found.");
  });

  it("prefers a recorded cause over the tier reason", () => {
    const presentation = incidentTimelinePresentation(auditItem(
      "rca.hypothesis",
      "fdai.core.rca",
      {
        rca_outcome: "grounded",
        rca_reason: "cited_rule_match",
        rca_cause: "Connection pool exhaustion",
      },
    ));

    expect(presentation.description).toBe(
      "Root-cause analysis recorded a cause: Connection pool exhaustion.",
    );
  });
});
