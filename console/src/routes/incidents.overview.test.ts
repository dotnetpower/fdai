import { describe, expect, it } from "vitest";
import type { AuditItem, IncidentSummary } from "../types";
import { incidentAgentStatus, incidentOperationalOverview } from "./incidents.overview";

function incident(overrides: Partial<IncidentSummary> = {}): IncidentSummary {
  return {
    correlation_id: "correlation-1",
    incident_id: "incident-1",
    ticket_id: null,
    title: "Resource inventory change",
    title_source: "recorded_title",
    source: null,
    response_plan: null,
    severity: "medium",
    status: "open",
    status_source: "incident_lifecycle",
    disposition: "pending",
    verdict: "unknown",
    vertical: "unknown",
    opened_at: "2026-07-28T06:43:55Z",
    last_updated_at: "2026-07-28T07:11:38Z",
    latest_mode: "shadow",
    history_count: 7,
    involved_agents: ["Heimdall"],
    ...overrides,
  };
}

function audit(
  actionKind: string,
  seq = 1,
  entry: Record<string, unknown> = {},
): AuditItem {
  return {
    seq,
    event_id: "event-1",
    correlation_id: "correlation-1",
    actor: "Heimdall",
    action_kind: actionKind,
    mode: "shadow",
    entry,
    entry_hash: "hash-1",
    previous_hash: "hash-0",
    recorded_at: "2026-07-28T06:43:55Z",
  };
}

describe("incident operational overview", () => {
  it("keeps alert lifecycle separate from agent work state", () => {
    expect(incidentAgentStatus("resolved")).toBe("completed");
    expect(incidentAgentStatus("notification_failed")).toBe("blocked");
    expect(incidentAgentStatus("response_failed")).toBe("blocked");
    expect(incidentAgentStatus("approval_required")).toBe("pending_user_input");
    expect(incidentAgentStatus("response_in_progress")).toBe("in_progress");
    expect(incidentAgentStatus("monitoring")).toBe("monitoring");
  });

  it("surfaces notification failure and hides unrecorded RCA views", () => {
    const overview = incidentOperationalOverview(incident(), [
      audit("incident.open"),
      audit("notification.escalation", 2),
      audit("notification.route", 3, { outcome: "route_unresolved" }),
      audit("incident.members"),
    ]);

    expect(overview).toEqual({
      phase: "notification_failed",
      decisionRecorded: false,
      rcaAvailable: false,
      reportAvailable: false,
      traceAvailable: true,
      auditAvailable: true,
      activityCount: 4,
      blockingReason: null,
    });
  });

  it("enables RCA views only after an RCA record exists", () => {
    const overview = incidentOperationalOverview(
      incident({ status: "in_progress", verdict: "hil", disposition: "awaiting_hil" }),
      [audit("incident.open"), audit("rca.hypothesis"), audit("hil.requested")],
    );

    expect(overview.phase).toBe("approval_required");
    expect(overview.decisionRecorded).toBe(true);
    expect(overview.rcaAvailable).toBe(true);
    expect(overview.reportAvailable).toBe(true);
  });

  it("keeps resolved lifecycle state authoritative over earlier delivery failures", () => {
    const overview = incidentOperationalOverview(
      incident({ status: "resolved", disposition: "resolved" }),
      [audit("notification.escalation"), audit("incident.transition")],
    );

    expect(overview.phase).toBe("resolved");
  });

  it("clears notification attention after a later successful route", () => {
    const overview = incidentOperationalOverview(incident(), [
      audit("notification.escalation", 1),
      audit("notification.route", 2, { outcome: "delivered" }),
    ]);

    expect(overview.phase).toBe("monitoring");
  });

  it("reports the newest recorded reason a governed response stopped", () => {
    const overview = incidentOperationalOverview(incident(), [
      audit("control_loop.abstain", 1, { reason: "first_abstention" }),
      audit("control_loop.abstain", 2, { reason: "no_rule_matches_resource_and_signal_type" }),
      audit("control_loop.t1_evaluate", 3, { t1_outcome: "abstain" }),
    ]);

    expect(overview.blockingReason).toBe("no_rule_matches_resource_and_signal_type");
  });

  it("does not invent a blocker when no abstention recorded a reason", () => {
    const overview = incidentOperationalOverview(incident(), [
      audit("incident.open", 1, { reason: "operator opened the incident" }),
      audit("control_loop.abstain", 2, {}),
    ]);

    expect(overview.blockingReason).toBeNull();
  });
});
