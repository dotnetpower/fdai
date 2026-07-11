import { describe, expect, test } from "vitest";
import type { ProvisionEvent } from "../hooks/use-provision-stream";
import { INITIAL, reducer, safeHttpUrl } from "./provision";

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
});

function ev(partial: Partial<ProvisionEvent> & { phase: ProvisionEvent["phase"] }): ProvisionEvent {
  return { type: `provision.${partial.phase}`, ...partial } as ProvisionEvent;
}

describe("reducer", () => {
  test("progress fraction never regresses", () => {
    let state = reducer(INITIAL, ev({ phase: "progress", fraction: 0.6 }));
    state = reducer(state, ev({ phase: "progress", fraction: 0.3 }));
    expect(state.fraction).toBe(0.6);
  });

  test("done clears a prior transient failure", () => {
    let state = reducer(INITIAL, ev({ phase: "failed", node: "x", reason: "boom" }));
    expect(state.failed).toBe("x");
    state = reducer(state, ev({ phase: "done", fraction: 1, console_url: "https://c.example" }));
    expect(state.done).toBe(true);
    expect(state.failed).toBeNull();
    expect(state.fraction).toBe(1);
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
