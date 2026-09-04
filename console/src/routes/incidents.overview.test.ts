import { describe, expect, it } from "vitest";
import type { AuditItem, IncidentSummary } from "../types";
import {
  incidentAgentStatus,
  incidentOperationalOverview,
} from "./incidents.overview";

function incident(overrides: Partial<IncidentSummary> = {}): IncidentSummary {
  return {
    correlation_id: "correlation-1",
    incident_id: "incident-1",
    incident_number: null,
    ticket_id: null,
    title: "Resource inventory change",
    title_source: "recorded_title",
    source: null,
    response_plan: null,
    severity: "medium",
    status: "open",
    status_source: "incident_lifecycle",
    lifecycle_state: "open",
    target_ref: "sha256:target",
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
    expect(incidentAgentStatus("approval_delivery_unavailable")).toBe("blocked");
    expect(incidentAgentStatus("response_failed")).toBe("blocked");
    expect(incidentAgentStatus("approval_required")).toBe("pending_user_input");
    expect(incidentAgentStatus("response_in_progress")).toBe("in_progress");
    expect(incidentAgentStatus("monitoring")).toBe("monitoring");
  });

  it("keeps human approval required when external approval delivery is unavailable", () => {
    const unavailable = incidentOperationalOverview(
      incident({ verdict: "hil", disposition: "awaiting_hil" }),
      [audit("hil.requested", 1), audit("hil.request.dispatch_unavailable", 2)],
    );
    const monitoring = incidentOperationalOverview(incident(), [audit("incident.open")]);

    expect(unavailable.userInputRequired).toBe(true);
    expect(monitoring.userInputRequired).toBe(false);
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
      notificationDeliveryFailed: true,
      notificationEvidence: {
        targetChannelIds: [],
        excludedChannels: [],
        deliveries: [],
        observedDeliveredChannelIds: [],
      },
      approvalDeliveryUnavailable: false,
      userInputRequired: false,
      decisionRecorded: false,
      rcaAvailable: false,
      reportAvailable: false,
      traceAvailable: true,
      auditAvailable: true,
      activityCount: 4,
      blockingReason: null,
    });
  });

  it("surfaces only recorded A2 target, exclusion, and per-channel delivery evidence", () => {
    const overview = incidentOperationalOverview(incident(), [
      audit("notification.route", 1, {
        outcome: "partially_delivered",
        trust_tier: "a2_operational_alert",
        target_channel_ids: ["teams-ops", "email-oncall"],
        excluded_channels: { "slack-ops": "channel_disabled" },
        deliveries: [
          { channel_id: "teams-ops", state: "accepted" },
          { channel_id: "email-oncall", state: "delivered" },
        ],
      }),
    ]);

    expect(overview.notificationEvidence).toEqual({
      targetChannelIds: ["teams-ops", "email-oncall"],
      excludedChannels: [{ channelId: "slack-ops", reason: "channel_disabled" }],
      deliveries: [
        { channelId: "teams-ops", state: "accepted" },
        { channelId: "email-oncall", state: "delivered" },
      ],
      observedDeliveredChannelIds: [],
    });
  });

  it("ignores an A4 digest route failure when deciding incident attention", () => {
    const overview = incidentOperationalOverview(incident(), [
      audit("notification.route", 1, {
        outcome: "failed",
        trust_tier: "a4_digest",
      }),
    ]);

    expect(overview.notificationDeliveryFailed).toBe(false);
    expect(overview.phase).toBe("monitoring");
  });

  it("keeps attention while an accepted channel has no independent observation", () => {
    const overview = incidentOperationalOverview(incident(), [
      audit("notification.route", 1, {
        audit_id: "incident-alert-1",
        outcome: "failed",
        trust_tier: "a2_operational_alert",
        target_channel_ids: ["teams-ops"],
        deliveries: [{ channel_id: "teams-ops", state: "accepted" }],
      }),
      audit("notification.delivery.observed", 2, {
        audit_id: "incident-alert-1",
        phase: "prepared",
        channel_id: "teams-ops",
        publication_result: "published",
      }),
    ]);

    // A prepared phase and a provider 2xx are not authoritative evidence.
    expect(overview.notificationDeliveryFailed).toBe(true);
    expect(overview.notificationEvidence.observedDeliveredChannelIds).toEqual([]);
  });

  it("clears attention only when the observation records a delivered transition", () => {
    const history = [
      audit("notification.route", 1, {
        audit_id: "incident-alert-1",
        outcome: "failed",
        trust_tier: "a2_operational_alert",
        target_channel_ids: ["teams-ops"],
        deliveries: [{ channel_id: "teams-ops", state: "accepted" }],
      }),
      audit("notification.delivery.observed", 2, {
        audit_id: "incident-alert-1",
        phase: "completed",
        channel_id: "teams-ops",
        publication_result: "failed",
        delivery_state: "retryable_failed",
      }),
    ];

    expect(incidentOperationalOverview(incident(), history).notificationDeliveryFailed).toBe(true);

    const recovered = incidentOperationalOverview(incident(), [
      ...history,
      audit("notification.delivery.observed", 3, {
        audit_id: "incident-alert-1",
        phase: "completed",
        channel_id: "teams-ops",
        publication_result: "published",
        delivery_state: "delivered",
      }),
    ]);

    expect(recovered.notificationDeliveryFailed).toBe(false);
    expect(recovered.phase).toBe("monitoring");
    expect(recovered.notificationEvidence.observedDeliveredChannelIds).toEqual(["teams-ops"]);
  });

  it("does not clear attention when only one of several open channels recovers", () => {
    const overview = incidentOperationalOverview(incident(), [
      audit("notification.route", 1, {
        audit_id: "incident-alert-1",
        outcome: "failed",
        trust_tier: "a2_operational_alert",
        target_channel_ids: ["teams-ops", "email-oncall"],
        deliveries: [
          { channel_id: "teams-ops", state: "accepted" },
          { channel_id: "email-oncall", state: "retryable_failed" },
        ],
      }),
      audit("notification.delivery.observed", 2, {
        audit_id: "incident-alert-1",
        phase: "completed",
        channel_id: "teams-ops",
        publication_result: "published",
        delivery_state: "delivered",
      }),
    ]);

    expect(overview.notificationDeliveryFailed).toBe(true);
  });

  it("does not use an earlier route observation to clear a newer failure", () => {
    const overview = incidentOperationalOverview(incident(), [
      audit("notification.route", 1, {
        audit_id: "incident-alert-1",
        outcome: "failed",
        trust_tier: "a2_operational_alert",
        deliveries: [{ channel_id: "teams-ops", state: "accepted" }],
      }),
      audit("notification.delivery.observed", 2, {
        audit_id: "incident-alert-1",
        phase: "completed",
        channel_id: "teams-ops",
        publication_result: "published",
        delivery_state: "delivered",
      }),
      audit("notification.route", 3, {
        audit_id: "incident-alert-2",
        outcome: "failed",
        trust_tier: "a2_operational_alert",
        deliveries: [{ channel_id: "teams-ops", state: "accepted" }],
      }),
    ]);

    expect(overview.notificationDeliveryFailed).toBe(true);
    expect(overview.notificationEvidence.observedDeliveredChannelIds).toEqual([]);
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

  it("keeps approval delivery failure separate from operational notifications", () => {
    const overview = incidentOperationalOverview(
      incident({ verdict: "hil", disposition: "awaiting_hil" }),
      [
        audit("notification.route", 1, { outcome: "delivered" }),
        audit("hil.requested", 2),
        audit("hil.request.dispatch_unavailable", 3),
      ],
    );

    expect(overview.phase).toBe("approval_delivery_unavailable");
  });

  it("does not hide a failed response behind an earlier approval requirement", () => {
    const overview = incidentOperationalOverview(
      incident({ verdict: "hil", disposition: "failed" }),
      [
        audit("hil.requested", 1),
        audit("hil.request.dispatch_unavailable", 2),
        audit("executor.failed", 3, { outcome: "failed" }),
      ],
    );

    expect(overview.phase).toBe("response_failed");
  });

  it("clears approval delivery attention after a later successful dispatch", () => {
    const overview = incidentOperationalOverview(
      incident({ verdict: "hil", disposition: "awaiting_hil" }),
      [
        audit("hil.requested", 1),
        audit("hil.request.dispatch_unavailable", 2),
        audit("hil.load.initial_sent", 3),
      ],
    );

    expect(overview.phase).toBe("approval_required");
  });

  it("clears approval delivery attention after a terminal human decision", () => {
    const overview = incidentOperationalOverview(
      incident({ status: "in_progress", verdict: "hil", disposition: "action_delivered" }),
      [
        audit("hil.requested", 1),
        audit("hil.request.dispatch_failed", 2),
        audit("hil.approved.executed", 3),
      ],
    );

    expect(overview.phase).toBe("response_in_progress");
    expect(overview.userInputRequired).toBe(false);
  });

  it("reports response progress as soon as approved execution is claimed", () => {
    const overview = incidentOperationalOverview(
      incident({ status: "open", verdict: "hil", disposition: "unknown" }),
      [audit("hil.requested", 1), audit("hil.approved.claimed", 2)],
    );

    expect(overview.phase).toBe("response_in_progress");
    expect(overview.userInputRequired).toBe(false);
  });

  it.each([
    "hil.rejected",
    "hil.timeout",
    "hil.resolve.integrity_failed",
    "hil.escalation.exhausted",
  ])(
    "does not request more human input after %s",
    (terminalKind) => {
      const overview = incidentOperationalOverview(
        incident({ verdict: "hil", disposition: "pending" }),
        [audit("hil.requested", 1), audit(terminalKind, 2)],
      );

      expect(overview.phase).toBe("monitoring");
      expect(overview.userInputRequired).toBe(false);
    },
  );

  it("surfaces execution failure after approval as response failure", () => {
    const overview = incidentOperationalOverview(
      incident({ status: "in_progress", verdict: "hil", disposition: "action_delivered" }),
      [audit("hil.requested", 1), audit("hil.approved.execute_failed", 2)],
    );

    expect(overview.phase).toBe("response_failed");
    expect(overview.userInputRequired).toBe(false);
  });

  it("does not revive approval from a historical verdict without current lifecycle evidence", () => {
    const overview = incidentOperationalOverview(
      incident({ verdict: "hil", disposition: "unknown" }),
      [audit("incident.activity", 101)],
    );

    expect(overview.phase).toBe("monitoring");
    expect(overview.userInputRequired).toBe(false);
  });

  it("preserves approval recovery when A1 and A2 delivery fail together", () => {
    const overview = incidentOperationalOverview(
      incident({ verdict: "hil", disposition: "awaiting_hil" }),
      [
        audit("hil.requested", 1),
        audit("hil.request.dispatch_unavailable", 2),
        audit("notification.route", 3, { outcome: "failed" }),
      ],
    );

    expect(overview.phase).toBe("notification_failed");
    expect(overview.notificationDeliveryFailed).toBe(true);
    expect(overview.approvalDeliveryUnavailable).toBe(true);
    expect(overview.userInputRequired).toBe(true);
  });

  it("reports the newest recorded reason a governed response stopped", () => {
    const overview = incidentOperationalOverview(incident(), [
      audit("control_loop.abstain", 1, { reason: "first_abstention" }),
      audit("control_loop.abstain", 2, { reason: "no_rule_matches_resource_and_signal_type" }),
      audit("control_loop.t1_evaluate", 3, { t1_outcome: "abstain" }),
    ]);

    expect(overview.blockingReason).toBe("no_rule_matches_resource_and_signal_type");
  });

  it("does not report a completed compliant evaluation as a blocker", () => {
    const overview = incidentOperationalOverview(incident(), [
      audit("control_loop.abstain", 1, { reason: "no_rule_matches_resource_type" }),
      audit("control_loop.abstain", 2, { reason: "no_rule_denied" }),
    ]);

    expect(overview.blockingReason).toBe("no_rule_matches_resource_type");
  });

  it("does not invent a blocker when no abstention recorded a reason", () => {
    const overview = incidentOperationalOverview(incident(), [
      audit("incident.open", 1, { reason: "operator opened the incident" }),
      audit("control_loop.abstain", 2, {}),
    ]);

    expect(overview.blockingReason).toBeNull();
  });
});
