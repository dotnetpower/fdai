import { afterEach, describe, expect, it } from "vitest";
import { setLocale } from "../i18n";
import type { AuditItem } from "../types";
import {
  incidentDisplayTitle,
  incidentPageMatchesSnapshot,
  incidentRosterIdentifier,
  incidentVerticalDisplayLabel,
  mergeIncidentItems,
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

  it("shows the correlation id that Audit, Trace, RCA, and the dossier resolve", () => {
    const summary = {
      correlation_id: "live-proof-correlation",
      incident_id: "00000000-0000-0000-0000-000000000000",
    };
    expect(incidentRosterIdentifier(summary)).toBe("live-proof-correlation");
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
});
