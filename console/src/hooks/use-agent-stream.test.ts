import { describe, expect, test } from "vitest";
import {
  agentReconnectDelay,
  agentStreamHeaders,
  consumeAgentActivitySse,
  decodeAgentActivityMessage,
  isPermanentAgentStreamFailure,
  shouldResumeAgentStream,
  type AgentActivityMessage,
} from "./use-agent-stream";

describe("agent activity stream boundary", () => {
  test("adds the bearer header without putting credentials in the URL", () => {
    const headers = agentStreamHeaders("Bearer token");
    expect(headers.get("authorization")).toBe("Bearer token");
    expect(headers.get("accept")).toBe("text/event-stream");
  });

  test("decodes the sensing heartbeat", () => {
    const event = decodeAgentActivityMessage(JSON.stringify({
      type: "agent.state",
      agent: "Heimdall",
      state: "watching",
      ts: "2026-07-16T06:00:00Z",
      correlation_id: null,
      detail: null,
    }));
    expect(event?.type).toBe("agent.state");
    expect(event && "state" in event ? event.state : null).toBe("watching");
    expect(event?.source).toBe("unknown");
    expect(decodeAgentActivityMessage(JSON.stringify({
      type: "agent.state",
      agent: "Heimdall",
      state: "watching",
      source: "synthetic-dev",
      ts: "2026-07-16T06:00:00Z",
      correlation_id: null,
      detail: null,
    }))?.source).toBe("synthetic-dev");
  });

  test("rejects malformed and unknown semantic frames", () => {
    expect(decodeAgentActivityMessage("not json")).toBeNull();
    expect(decodeAgentActivityMessage(JSON.stringify({ type: "agent.state", agent: "Huginn" })))
      .toBeNull();
    expect(decodeAgentActivityMessage(JSON.stringify({ type: "unknown" }))).toBeNull();
  });

  test("decodes data frames and ignores hello and keepalive frames", async () => {
    const payload = JSON.stringify({
      type: "agent.state",
      agent: "Huginn",
      state: "collecting",
      ts: "2026-07-16T06:00:00Z",
      correlation_id: "incident-1",
      detail: "Collecting event",
    });
    const response = new Response(
      `event: hello\ndata: {"status":"ok"}\n\n: keepalive\n\ndata: ${payload}\n\n`,
      { status: 200, headers: { "content-type": "text/event-stream" } },
    );
    const events: AgentActivityMessage[] = [];
    await consumeAgentActivitySse(response, (event) => events.push(event));
    expect(events).toHaveLength(1);
    expect(events[0]?.type).toBe("agent.state");
  });

  test("classifies auth failures and caps reconnect backoff", () => {
    expect(isPermanentAgentStreamFailure(401)).toBe(true);
    expect(isPermanentAgentStreamFailure(403)).toBe(false);
    expect(isPermanentAgentStreamFailure(503)).toBe(false);
    expect(agentReconnectDelay(0)).toBe(1000);
    expect(agentReconnectDelay(20)).toBe(30000);
  });

  test("does not resume a permanently failed stream on tab visibility", () => {
    expect(shouldResumeAgentStream(true, false)).toBe(false);
    expect(shouldResumeAgentStream(false, true)).toBe(false);
    expect(shouldResumeAgentStream(false, false)).toBe(true);
  });

  test("rejects successful responses that are not SSE", async () => {
    await expect(consumeAgentActivitySse(
      new Response("<html></html>", {
        status: 200,
        headers: { "content-type": "text/html" },
      }),
      () => undefined,
    )).rejects.toThrow(/content type/);
  });
});
