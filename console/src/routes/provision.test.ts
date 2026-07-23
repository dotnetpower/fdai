import { describe, expect, test } from "vitest";
import type { ReadDataSourcesPayload } from "../api";
import type { ProvisionEvent } from "../hooks/use-provision-stream";
import { INITIAL, provisionSourceState, reducer, safeHttpUrl } from "./provision";

/**
 * Provision route hardening regressions.
 *
 * - `safeHttpUrl` is a security boundary: `console_url` arrives over the SSE
 *   wire and is rendered into an anchor `href`, so a `javascript:` / `data:`
 *   URI must never survive (DOM-based XSS, OWASP A03).
 * - The progress meter must never regress and must not render "up" and
 *   "failed" at the same time.
 */

describe("safeHttpUrl", () => {
  test("passes absolute http(s) URLs through", () => {
    expect(safeHttpUrl("https://console.example.com/")).toBe("https://console.example.com/");
    expect(safeHttpUrl("http://localhost:8080/x")).toBe("http://localhost:8080/x");
  });

  test("rejects javascript: and data: URIs", () => {
    expect(safeHttpUrl("javascript:alert(1)")).toBeNull();
    expect(safeHttpUrl("JavaScript:alert(1)")).toBeNull();
    expect(safeHttpUrl("data:text/html,<script>alert(1)</script>")).toBeNull();
  });

  test("rejects non-absolute / unparseable / empty values", () => {
    expect(safeHttpUrl("not a url")).toBeNull();
    expect(safeHttpUrl("/relative/path")).toBeNull();
    expect(safeHttpUrl("")).toBeNull();
    expect(safeHttpUrl(null)).toBeNull();
  });

  test("rejects URLs that embed credentials", () => {
    expect(safeHttpUrl("https://user:password@example.com/console")).toBeNull();
  });
});

describe("provision source gating", () => {
  const payload = (availability: "available" | "unavailable" | "unknown"): ReadDataSourcesPayload => ({
    surface: "read-data-sources",
    sources: [{
      key: "provisioning-stream",
      source: availability === "unavailable" ? "not-configured" : "event-stream",
      routes: ["/provision/stream"],
      availability,
      configured: availability !== "unavailable",
      reachable: availability === "available" ? true : null,
      authoritative: availability !== "unavailable",
      durable: false,
      synthetic: false,
      reason: availability === "unavailable" ? "relay not configured" : null,
      last_observed_at: null,
    }],
  });

  test("connects only to declared authoritative stream sources", () => {
    expect(provisionSourceState(payload("available")).status).toBe("ready");
    expect(provisionSourceState(payload("unknown")).status).toBe("ready");
  });

  test("holds unavailable before fetch when the relay is absent or unowned", () => {
    expect(provisionSourceState(payload("unavailable"))).toEqual({
      status: "unavailable",
      reason: "relay not configured",
    });
    expect(provisionSourceState({ surface: "read-data-sources", sources: [] }).status)
      .toBe("unavailable");
  });
});

function ev(partial: Partial<ProvisionEvent> & { phase: ProvisionEvent["phase"] }): ProvisionEvent {
  return { type: `provision.${partial.phase}`, ...partial } as ProvisionEvent;
}

describe("reducer", () => {
  test("does not claim progress before the first observed provision event", () => {
    expect(INITIAL.observed).toBe(false);
    expect(reducer(INITIAL, ev({ phase: "progress", fraction: 0 })).observed).toBe(true);
  });

  test("progress fraction never regresses", () => {
    let state = reducer(INITIAL, ev({ phase: "progress", fraction: 0.6 }));
    state = reducer(state, ev({ phase: "progress", fraction: 0.3 }));
    expect(state.fraction).toBe(0.6);
  });

  test("progress clamps invalid wire fractions to the valid range", () => {
    expect(reducer(INITIAL, ev({ phase: "progress", fraction: 2 })).fraction).toBe(1);
    expect(reducer(INITIAL, ev({ phase: "progress", fraction: -1 })).fraction).toBe(0);
    expect(reducer(INITIAL, ev({ phase: "progress", fraction: Number.NaN })).fraction).toBe(0);
  });

  test("done clears a prior transient failure", () => {
    let state = reducer(INITIAL, ev({ phase: "failed", node: "x", reason: "boom" }));
    expect(state.failed).toBe("x");
    state = reducer(state, ev({ phase: "done", fraction: 1, console_url: "https://c.example" }));
    expect(state.done).toBe(true);
    expect(state.failed).toBeNull();
    expect(state.fraction).toBe(1);
  });

  test("done is terminal when the wire has no new-run identity", () => {
    const done = reducer(INITIAL, ev({ phase: "done", fraction: 1 }));
    expect(reducer(done, ev({ phase: "progress", fraction: 0.2, node: "late" }))).toBe(done);
    expect(reducer(done, ev({ phase: "failed", node: "late", reason: "replay" }))).toBe(done);
    expect(reducer(done, ev({ phase: "waiting", node: "late" }))).toBe(done);
    expect(reducer(done, ev({ phase: "done", console_url: "https://other.example" }))).toBe(done);
  });

  test("waiting then resumed clears the hold", () => {
    let state = reducer(INITIAL, ev({ phase: "waiting", node: "db", reason: "slow" }));
    expect(state.waiting).toBe("db");
    state = reducer(state, ev({ phase: "resumed", node: "db" }));
    expect(state.waiting).toBeNull();
  });

  test("resumed for a different node keeps the current waiter visible", () => {
    // A waits, then B waits (overwriting the single display slot). When A
    // eventually resumes, the banner must still show B - we must not falsely
    // clear the hold for a resource that is still waiting.
    let state = reducer(INITIAL, ev({ phase: "waiting", node: "a", reason: "slow-a" }));
    state = reducer(state, ev({ phase: "waiting", node: "b", reason: "slow-b" }));
    expect(state.waiting).toBe("b");
    state = reducer(state, ev({ phase: "resumed", node: "a" }));
    expect(state.waiting).toBe("b");
    expect(state.waitingReason).toBe("slow-b");
    state = reducer(state, ev({ phase: "resumed", node: "b" }));
    expect(state.waiting).toBeNull();
  });

  test("unrelated progress does not clear the waiting banner", () => {
    let state = reducer(INITIAL, ev({ phase: "waiting", node: "db", reason: "slow" }));
    state = reducer(state, ev({ phase: "progress", fraction: 0.5, node: "other" }));
    expect(state.waiting).toBe("db"); // still waiting on db
    expect(state.fraction).toBe(0.5);
  });

  test("failure clears the waiting hold", () => {
    let state = reducer(INITIAL, ev({ phase: "waiting", node: "db", reason: "slow" }));
    state = reducer(state, ev({ phase: "failed", node: "db", reason: "timeout" }));
    expect(state.waiting).toBeNull();
    expect(state.failed).toBe("db");
  });

  test("recent list stays unique (no duplicate keys) and newest-first", () => {
    let state = reducer(INITIAL, ev({ phase: "progress", fraction: 0.3, node: "a" }));
    state = reducer(state, ev({ phase: "progress", fraction: 0.6, node: "b" }));
    state = reducer(state, ev({ phase: "progress", fraction: 0.9, node: "a" })); // repeat
    expect(state.recent).toEqual(["a", "b"]);
    expect(new Set(state.recent).size).toBe(state.recent.length);
  });
});
