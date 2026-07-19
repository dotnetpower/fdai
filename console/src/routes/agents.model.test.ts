import { describe, expect, it } from "vitest";
import type { AgentActivityMessage, AgentStatus } from "../hooks/use-agent-stream";
import {
  activeAgentCount,
  currentRuntimeCount,
  AGENT_RUNTIME_BINDING,
  AGENT_ROLE,
  agentChatContext,
  engagedGroups,
  incidentsForAgent,
  isEngaged,
  makeInitialState,
  ORG_CHART,
  PANTHEON,
  reducer,
  runtimeConsumerCount,
} from "./agents.model";

function stateMsg(
  agent: string,
  state: AgentStatus,
  correlation_id: string | null = null,
): AgentActivityMessage {
  return {
    type: "agent.state",
    agent,
    state,
    ts: "2026-07-12T00:00:00+00:00",
    correlation_id,
    detail: null,
    source: "unknown",
  };
}

function ticketMsg(
  correlation_id: string,
  status: "open" | "investigating" | "resolved",
  rca: string | null = null,
): AgentActivityMessage {
  return {
    type: "incident.ticket",
    ticket_id: "FDAI-1",
    correlation_id,
    status,
    title: "t",
    severity: "high",
    involved_agents: ["Heimdall", "Forseti"],
    rca,
    ts: "2026-07-12T00:00:00+00:00",
    source: "unknown",
  };
}

function turnMsg(correlation_id: string): AgentActivityMessage {
  return {
    type: "conversation.turn",
    correlation_id,
    from_agent: "Heimdall",
    to_agent: "Forseti",
    kind: "handoff",
    text: "anomaly 0.92",
    ts: "2026-07-12T00:00:00+00:00",
    source: "unknown",
  };
}

describe("agents.model", () => {
  it("seeds all 15 agents as unobserved", () => {
    const s = makeInitialState();
    expect(Object.keys(s.agents)).toHaveLength(15);
    expect(PANTHEON.every((a) => s.agents[a.name]?.state === "idle")).toBe(true);
    expect(PANTHEON.every((a) => s.agents[a.name]?.observed === false)).toBe(true);
  });

  it("applies an agent.state transition", () => {
    let s = makeInitialState();
    s = reducer(s, { kind: "message", msg: stateMsg("Heimdall", "collecting", "inc-1") });
    expect(s.agents.Heimdall?.state).toBe("collecting");
    expect(s.agents.Heimdall?.observed).toBe(true);
    expect(s.agents.Heimdall?.correlationId).toBe("inc-1");
  });

  it("ignores state frames outside the fixed pantheon", () => {
    const initial = makeInitialState();
    const next = reducer(initial, {
      kind: "message",
      msg: stateMsg("UnknownAgent", "collecting", "inc-1"),
    });

    expect(next).toBe(initial);
    expect(Object.keys(next.agents)).toHaveLength(15);
    expect(next.agents.UnknownAgent).toBeUndefined();
  });

  it("opens then resolves an incident, preserving the rca", () => {
    let s = makeInitialState();
    s = reducer(s, { kind: "message", msg: ticketMsg("inc-1", "open") });
    expect(s.incidentOrder).toEqual(["inc-1"]);
    expect(s.incidents["inc-1"]?.status).toBe("open");
    s = reducer(s, { kind: "message", msg: ticketMsg("inc-1", "investigating", "root cause X") });
    s = reducer(s, { kind: "message", msg: ticketMsg("inc-1", "resolved", "root cause X") });
    expect(s.incidents["inc-1"]?.status).toBe("resolved");
    expect(s.incidents["inc-1"]?.rca).toBe("root cause X");
    // Still a single incident (upsert, not duplicate).
    expect(s.incidentOrder).toEqual(["inc-1"]);
  });

  it("accumulates conversation turns on an incident", () => {
    let s = makeInitialState();
    s = reducer(s, { kind: "message", msg: ticketMsg("inc-1", "open") });
    s = reducer(s, { kind: "message", msg: turnMsg("inc-1") });
    s = reducer(s, { kind: "message", msg: turnMsg("inc-1") });
    expect(s.incidents["inc-1"]?.turns).toHaveLength(2);
  });

  it("seeds a stub incident when a turn arrives before its ticket", () => {
    let s = makeInitialState();
    s = reducer(s, { kind: "message", msg: turnMsg("inc-9") });
    expect(s.incidents["inc-9"]?.turns).toHaveLength(1);
    expect(s.incidents["inc-9"]?.involved).toEqual(["Heimdall", "Forseti"]);
    expect(incidentsForAgent(s, "Heimdall").map((incident) => incident.correlationId))
      .toEqual(["inc-9"]);
    expect(s.incidentOrder).toEqual(["inc-9"]);
  });

  it("adds known turn participants to an existing incident once", () => {
    let s = makeInitialState();
    s = reducer(s, { kind: "message", msg: ticketMsg("inc-1", "open") });
    s = reducer(s, { kind: "message", msg: turnMsg("inc-1") });
    s = reducer(s, { kind: "message", msg: turnMsg("inc-1") });

    expect(s.incidents["inc-1"]?.involved).toEqual(["Heimdall", "Forseti"]);
  });

  it("prunes turn-first incident stubs outside the retention window", () => {
    let s = makeInitialState();
    for (let index = 0; index < 31; index += 1) {
      s = reducer(s, { kind: "message", msg: turnMsg(`inc-${index}`) });
    }

    expect(s.incidentOrder).toHaveLength(30);
    expect(Object.keys(s.incidents)).toHaveLength(30);
    expect(s.incidents["inc-0"]).toBeUndefined();
    expect(s.incidentOrder[0]).toBe("inc-30");
  });

  it("counts engaged (non-idle, non-watching) agents", () => {
    let s = makeInitialState();
    s = reducer(s, { kind: "message", msg: stateMsg("Heimdall", "collecting") });
    s = reducer(s, { kind: "message", msg: stateMsg("Huginn", "watching") });
    s = reducer(s, { kind: "message", msg: stateMsg("Forseti", "analyzing") });
    expect(activeAgentCount(s)).toBe(2);
  });

  it("resets to the initial state", () => {
    let s = makeInitialState();
    s = reducer(s, { kind: "message", msg: ticketMsg("inc-1", "open") });
    s = reducer(s, { kind: "reset" });
    expect(s.incidentOrder).toHaveLength(0);
  });

  it("hydrates real incident history without overwriting a newer live frame", () => {
    let s = makeInitialState();
    s = reducer(s, { kind: "message", msg: ticketMsg("inc-live", "resolved") });
    s = reducer(s, {
      kind: "hydrate",
      incidents: [
        {
          correlation_id: "inc-history",
          incident_id: null,
          ticket_id: null,
          title: "Historical HIL",
          severity: "high",
          status: "in_progress",
          status_source: "audit_projection",
          disposition: "awaiting_hil",
          verdict: "hil",
          vertical: "change_safety",
          opened_at: "2026-07-11T00:00:00+00:00",
          last_updated_at: "2026-07-12T00:00:00+00:00",
          latest_mode: "shadow",
          history_count: 8,
          involved_agents: ["Heimdall", "Forseti", "Var"],
        },
      ],
    });
    expect(s.incidentOrder).toEqual(["inc-history", "inc-live"]);
    expect(s.incidents["inc-history"]?.status).toBe("investigating");
    expect(s.incidents["inc-history"]?.involved).toEqual(["Heimdall", "Forseti", "Var"]);
    expect(s.incidents["inc-live"]?.status).toBe("resolved");
    expect(s.agents.Var?.state).toBe("approving");
    expect(s.agents.Var?.observed).toBe(true);
    expect(s.agents.Var?.correlationId).toBe("inc-history");
  });
});

describe("agents.model engagement helpers", () => {
  it("does not claim a current runtime count after the stream closes", () => {
    expect(currentRuntimeCount(true, 3)).toBe(3);
    expect(currentRuntimeCount(false, 3)).toBeNull();
  });

  it("distinguishes perpetual consumers from adapter and schedule driven agents", () => {
    expect(runtimeConsumerCount()).toBe(12);
    expect(AGENT_RUNTIME_BINDING.Huginn).toBe("raw ingress subscriber");
    expect(AGENT_RUNTIME_BINDING.Heimdall).toBe("event-bus subscriber");
    expect(AGENT_RUNTIME_BINDING.Njord).toBe("external adapter");
    expect(AGENT_RUNTIME_BINDING.Freyr).toBe("external adapter");
    expect(AGENT_RUNTIME_BINDING.Loki).toBe("scheduled trigger");
  });

  it("stores the streamed detail on the agent node", () => {
    let s = makeInitialState();
    s = reducer(s, {
      kind: "message",
      msg: {
        type: "agent.state",
        agent: "Forseti",
        state: "analyzing",
        ts: "2026-07-12T00:00:00+00:00",
        correlation_id: "inc-1",
        detail: "root-cause reasoning",
        source: "runtime-observed",
      },
    });
    expect(s.agents.Forseti?.detail).toBe("root-cause reasoning");
    expect(isEngaged(s.agents.Forseti!)).toBe(true);
    expect(isEngaged(s.agents.Odin!)).toBe(false);
  });

  it("groups engaged agents by the incident they work on", () => {
    let s = makeInitialState();
    s = reducer(s, { kind: "message", msg: ticketMsg("inc-1", "open") });
    s = reducer(s, { kind: "message", msg: stateMsg("Heimdall", "collecting", "inc-1") });
    s = reducer(s, { kind: "message", msg: stateMsg("Forseti", "analyzing", "inc-1") });
    // Watching / idle / correlation-less agents are excluded.
    s = reducer(s, { kind: "message", msg: stateMsg("Huginn", "watching", "inc-1") });
    s = reducer(s, { kind: "message", msg: stateMsg("Thor", "executing", null) });

    const groups = engagedGroups(s);
    expect(groups).toHaveLength(1);
    expect(groups[0]?.correlationId).toBe("inc-1");
    expect(groups[0]?.agents).toEqual(["Forseti", "Heimdall"]); // sorted
    expect(groups[0]?.incident?.ticketId).toBe("FDAI-1");
  });

  it("returns one group per concurrent incident, newest first", () => {
    let s = makeInitialState();
    s = reducer(s, { kind: "message", msg: ticketMsg("inc-old", "open") });
    s = reducer(s, { kind: "message", msg: ticketMsg("inc-new", "open") });
    s = reducer(s, { kind: "message", msg: stateMsg("Heimdall", "collecting", "inc-old") });
    s = reducer(s, { kind: "message", msg: stateMsg("Thor", "executing", "inc-new") });

    const groups = engagedGroups(s);
    expect(groups.map((g) => g.correlationId)).toEqual(["inc-new", "inc-old"]);
  });

  it("returns no groups when the pantheon is at rest", () => {
    const s = makeInitialState();
    expect(engagedGroups(s)).toEqual([]);
  });
});

describe("agents.model org chart + agent events", () => {
  it("has a role card for every one of the 15 agents", () => {
    for (const { name } of PANTHEON) {
      expect(AGENT_ROLE[name], name).toBeDefined();
      expect(AGENT_ROLE[name]?.title.length).toBeGreaterThan(0);
    }
  });

  it("org chart places every agent exactly once, rooted at Odin", () => {
    const placed = [ORG_CHART.root, ...ORG_CHART.staff];
    for (const line of ORG_CHART.lines) placed.push(line.manager, ...line.reports);
    expect(placed).toHaveLength(15);
    expect(new Set(placed).size).toBe(15);
    expect(placed).toContain("Odin");
    // Every placed name is a real pantheon agent.
    const known = new Set(PANTHEON.map((a) => a.name));
    for (const n of placed) expect(known.has(n), n).toBe(true);
  });

  it("reportsTo lines match the org chart structure", () => {
    expect(AGENT_ROLE.Odin?.reportsTo).toBeNull();
    for (const line of ORG_CHART.lines) {
      expect(AGENT_ROLE[line.manager]?.reportsTo).toBe("Odin");
      for (const r of line.reports) {
        expect(AGENT_ROLE[r]?.reportsTo).toBe(line.manager);
      }
    }
    for (const s of ORG_CHART.staff) {
      expect(AGENT_ROLE[s]?.reportsTo).toBe("Odin");
      expect(AGENT_ROLE[s]?.staff).toBe(true);
    }
  });

  it("lists the incidents an agent participates in, newest first", () => {
    let s = makeInitialState();
    // Two incidents; Forseti is involved in both, Loki only in the second.
    s = reducer(s, {
      kind: "message",
      msg: {
        type: "incident.ticket",
        ticket_id: "FDAI-1",
        correlation_id: "inc-1",
        status: "open",
        title: "first",
        severity: "high",
        involved_agents: ["Heimdall", "Forseti"],
        rca: null,
        ts: "2026-07-12T00:00:00+00:00",
        source: "runtime-observed",
      },
    });
    s = reducer(s, {
      kind: "message",
      msg: {
        type: "incident.ticket",
        ticket_id: "FDAI-2",
        correlation_id: "inc-2",
        status: "open",
        title: "second",
        severity: "medium",
        involved_agents: ["Forseti", "Loki"],
        rca: null,
        ts: "2026-07-12T00:00:01+00:00",
        source: "runtime-observed",
      },
    });
    const forseti = incidentsForAgent(s, "Forseti").map((i) => i.correlationId);
    expect(forseti).toEqual(["inc-2", "inc-1"]); // newest first
    const loki = incidentsForAgent(s, "Loki").map((i) => i.correlationId);
    expect(loki).toEqual(["inc-2"]);
    expect(incidentsForAgent(s, "Bragi")).toEqual([]);
  });

  it("builds a grounded chat context for an agent from its recent work", () => {
    const node = {
      name: "Forseti",
      layer: "judge" as const,
      state: "analyzing" as const,
      observed: true,
      correlationId: "inc-1",
      since: "2026-07-12T00:00:00+00:00",
      detail: null,
    };
    const incidents = [
      {
        correlationId: "inc-1",
        ticketId: "FDAI-1",
        title: "AKS pod restart storm",
        severity: "high",
        status: "resolved" as const,
        involved: ["Forseti"],
        rca: "scheduled chaos experiment",
        turns: [],
        updatedAt: "2026-07-12T00:00:00+00:00",
      },
    ];
    const ctx = agentChatContext(node, incidents);
    expect(ctx).toContain("Forseti");
    expect(ctx).toContain("Judge"); // role title
    expect(ctx).toContain("FDAI-1");
    expect(ctx).toContain("scheduled chaos experiment"); // RCA injected
    expect(ctx).toContain("analyzing"); // live state
  });

  it("notes when an agent has no incidents in its chat context", () => {
    const node = {
      name: "Bragi",
      layer: "conversational" as const,
      state: "idle" as const,
      observed: false,
      correlationId: null,
      since: "",
      detail: null,
    };
    expect(agentChatContext(node, [])).toContain("has not participated in any incident");
  });
});
