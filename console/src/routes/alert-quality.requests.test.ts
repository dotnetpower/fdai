import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OperatorApiError, type OperatorApiClient } from "../api";
import type { AsyncState } from "../components/ui";
import type { AlertQualityPayload } from "./alert-quality.model";
import { createAlertQualitySession, type AlertQualityCommandState, type AlertQualitySession } from "./alert-quality";
import { createAlertQualityRequestMemory } from "./alert-quality.requests";

// Synthetic source-only transport fixtures; tests never need an Operator server.
const scope = "scope:example";
const digest = `sha256:${"a".repeat(64)}`;
const report = {
  schema_version: "1.0.0", source: "alert-noise-evidence", evidence_digest: digest, policy_digest: digest,
  tenant_ref: "tenant:example", scope_ref: scope, observed_at: "2026-09-14T10:00:00Z", valid_until: "2026-09-14T11:00:00Z",
  coverage: "complete", reasons: [], source_episodes: 1, notification_attempts: 0, confirmed_deliveries: null,
  acknowledgements: null, execution_authority: false,
  findings: [{ rule_ref: "rule:example", service_ref: "service:example", reason: "overlap", guidance: "review-routing",
    source_episodes: 1, observed_deliveries: null, potential_recipients_lower: 5, potential_recipients_upper: 10,
    duplicate_paths: 1, protected: false }],
};
const payload = () => ({ source: "alert-noise-governance", available: true, enabled: true, authority: "shadow", unavailable_reason: null, assessment: report, plans: [] });
const response = () => new Response(JSON.stringify({
  ...payload(), available: false, assessment: null, unavailable_reason: "assessment_pending",
}), { status: 202, headers: { "content-type": "application/json" } });
const owners: AlertQualitySession[] = [];
let network: ReturnType<typeof vi.fn<typeof fetch>>;

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function setup(selectedScope = scope, memory = createAlertQualityRequestMemory(), canRequest: () => boolean = () => true) {
  const read = vi.fn<(path: string, params?: Record<string, string>) => Promise<unknown>>().mockResolvedValue(payload());
  const authorization = vi.fn<() => Promise<string | null>>().mockResolvedValue("Bearer test-only");
  const onRead = vi.fn<(state: AsyncState<AlertQualityPayload>) => void>();
  const onCommand = vi.fn<(state: AlertQualityCommandState) => void>();
  const client: Pick<OperatorApiClient, "panel" | "authorizationHeader" | "operatorApiBaseUrl"> = {
    operatorApiBaseUrl: "https://operator.example",
    authorizationHeader: authorization,
    async panel<T>(path: string, params?: Record<string, string>): Promise<T> { return await read(path, params) as T; },
  };
  const authorizationContext = { current: true };
  const owner = createAlertQualitySession(client, selectedScope, onRead, onCommand,
    () => authorizationContext.current, memory, canRequest);
  owners.push(owner);
  return { owner, read, authorization, onRead, onCommand, authorizationContext, memory };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-14T10:30:00Z"));
  let sequence = 0;
  vi.stubGlobal("crypto", { randomUUID: vi.fn(() => `source-only-request-${++sequence}`) });
  network = vi.fn<typeof fetch>().mockImplementation(async () => response());
  vi.stubGlobal("fetch", network);
});

afterEach(() => {
  for (const owner of owners.splice(0)) owner.dispose();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("latest read and unmount isolation", () => {
  it("loads only the exact opaque scope through the existing panel client", async () => {
    const fixture = setup();
    await fixture.owner.load();
    expect(fixture.read).toHaveBeenCalledExactlyOnceWith("/alert-quality", { scope_ref: scope });
    expect(fixture.onRead.mock.calls[0]?.[0]).toEqual({ status: "loading" });
    expect(fixture.onRead).toHaveBeenLastCalledWith(expect.objectContaining({ status: "ready" }));
    expect(network).not.toHaveBeenCalled();
    expect(fixture.authorization).not.toHaveBeenCalled();
  });

  it("discards an older response and ignores a response after disposal", async () => {
    const fixture = setup();
    const earlier = deferred<unknown>();
    fixture.read.mockImplementationOnce(() => earlier.promise);
    const first = fixture.owner.load();
    await fixture.owner.load();
    const events = fixture.onRead.mock.calls.length;
    earlier.resolve({ ...payload(), available: false, unavailable_reason: "old-source" });
    await first;
    expect(fixture.onRead.mock.calls).toHaveLength(events);
    const late = deferred<unknown>();
    fixture.read.mockImplementationOnce(() => late.promise);
    const pending = fixture.owner.load();
    fixture.owner.dispose();
    fixture.onRead.mockClear();
    late.resolve(payload());
    await pending;
    expect(fixture.onRead).not.toHaveBeenCalled();
  });

  it("keeps optional unavailability separate from transport, auth and decoder errors", async () => {
    const fixture = setup();
    for (const [error, status] of [
      [new OperatorApiError(404, "not served"), "unavailable"],
      [new OperatorApiError(503, "source missing", "projection-unavailable"), "unavailable"],
      [new OperatorApiError(503, "failed"), "error"],
      [new OperatorApiError(403, "denied"), "error"],
    ] as const) {
      fixture.read.mockRejectedValueOnce(error);
      await fixture.owner.load();
      expect(fixture.onRead).toHaveBeenLastCalledWith(expect.objectContaining({ status }));
    }
    fixture.read.mockResolvedValueOnce({ ...payload(), authority: "enforce" });
    await fixture.owner.load();
    expect(fixture.onRead).toHaveBeenLastCalledWith(expect.objectContaining({ status: "error" }));
    await fixture.owner.assess();
    expect(network).not.toHaveBeenCalled();
  });

  it("bounds a hanging read and never repaints from its late result", async () => {
    const fixture = setup();
    const pending = deferred<unknown>();
    fixture.read.mockImplementationOnce(() => pending.promise);
    const work = fixture.owner.load();
    await vi.advanceTimersByTimeAsync(15_000);
    await work;
    expect(fixture.onRead).toHaveBeenLastCalledWith(expect.objectContaining({ status: "error" }));
    fixture.onRead.mockClear();
    pending.resolve(payload());
    await vi.advanceTimersByTimeAsync(1);
    expect(fixture.onRead).not.toHaveBeenCalled();
  });
});

describe("deliberate idempotency and no blind retries", () => {
  it("coalesces overlapping clicks but gives a later deliberate request a new key", async () => {
    const fixture = setup();
    await fixture.owner.load();
    await Promise.all([fixture.owner.assess(), fixture.owner.assess()]);
    expect(network).toHaveBeenCalledTimes(1);
    await fixture.owner.assess();
    expect(network).toHaveBeenCalledTimes(2);
    const first = network.mock.calls[0]!;
    const second = network.mock.calls[1]!;
    expect(String(first[0])).toBe("https://operator.example/alert-quality/assess");
    expect(first[1]).toMatchObject({ method: "POST", credentials: "omit", body: JSON.stringify({ scope_ref: scope }) });
    expect(new Headers(first[1]?.headers).get("idempotency-key")).not.toBe(new Headers(second[1]?.headers).get("idempotency-key"));
    expect(fixture.onCommand).toHaveBeenLastCalledWith("submitted");
    expect(fixture.read).toHaveBeenCalledTimes(3);
  });

  it("submits only the selected routing axis and the exact report evidence digest", async () => {
    const fixture = setup();
    await fixture.owner.load();
    await fixture.owner.proposeRouting("rule:example", "group:source", "group:replacement");
    expect(network).toHaveBeenCalledTimes(1);
    expect(String(network.mock.calls[0]?.[0])).toBe("https://operator.example/alert-quality/proposals");
    expect(JSON.parse(String(network.mock.calls[0]?.[1]?.body))).toEqual({
      scope_ref: scope, evidence_digest: digest,
      treatment: { kind: "routing", target_ref: "rule:example", remove_group_ref: "group:source", replacement_group_ref: "group:replacement" },
    });
  });

  it("can request a new assessment with no report or an expired retained report", async () => {
    for (const assessment of [null, { ...report, valid_until: "2026-09-14T10:01:00Z" }]) {
      const fixture = setup();
      fixture.read.mockResolvedValueOnce({ ...payload(), assessment, unavailable_reason: "assessment_expired" });
      await fixture.owner.load();
      await fixture.owner.assess();
      expect(fixture.onCommand).toHaveBeenLastCalledWith("submitted");
    }
    expect(network).toHaveBeenCalledTimes(2);
  });

  it("sends finite suppression without provisioning, acknowledgement or authority fields", async () => {
    const fixture = setup();
    await fixture.owner.load();
    await fixture.owner.propose({ kind: "suppression", target_ref: "rule:example", processing_rule_ref: "processing:example",
      starts_at: "2026-09-14T20:00:00+09:00", ends_at: "2026-09-14T21:00:00+09:00", preprovisioned: true });
    expect(network).toHaveBeenCalledTimes(1);
    expect(JSON.parse(String(network.mock.calls[0]?.[1]?.body))).toEqual({ scope_ref: scope, evidence_digest: digest,
      treatment: { kind: "suppression", target_ref: "rule:example", processing_rule_ref: "processing:example",
        starts_at: "2026-09-14T20:00:00+09:00", ends_at: "2026-09-14T21:00:00+09:00" } });
  });

  it("sends only the after evaluation while the server owns the baseline and validation", async () => {
    const fixture = setup();
    fixture.read.mockResolvedValueOnce({ ...payload(), assessment: { ...report,
      findings: [{ ...report.findings[0], guidance: "review-evaluation", reason: "flapping" }] } });
    await fixture.owner.load();
    await fixture.owner.propose({ kind: "evaluation", target_ref: "rule:example", parameter: "threshold", proposed_value: "80.5",
      baseline: { metric_ref: "metric:example", operator: "above", threshold: "75", window_seconds: "300", frequency_seconds: "60", aggregation: "average" } });
    expect(network).toHaveBeenCalledTimes(1);
    expect(JSON.parse(String(network.mock.calls[0]?.[1]?.body))).toEqual({ scope_ref: scope, evidence_digest: digest,
      treatment: { kind: "evaluation", target_ref: "rule:example", evaluation: { metric_ref: "metric:example", operator: "above",
        threshold: 80.5, window_seconds: 300, frequency_seconds: 60, aggregation: "average" } } });
  });

  it("honors an optional explicit server veto without requiring that field from older servers", async () => {
    const fixture = setup();
    fixture.read.mockResolvedValueOnce({ ...payload(), requestable: false });
    await fixture.owner.load();
    await fixture.owner.assess();
    expect(network).not.toHaveBeenCalled();
    await fixture.owner.load();
    await fixture.owner.assess();
    expect(network).toHaveBeenCalledTimes(1);
  });

  it("never requests without safe scope, loaded availability, enablement or valid inputs", async () => {
    const unsafe = setup("/subscriptions/example");
    await unsafe.owner.load();
    await unsafe.owner.assess();
    expect(unsafe.read).not.toHaveBeenCalled();
    const fixture = setup();
    await fixture.owner.assess();
    fixture.read.mockResolvedValueOnce({ ...payload(), enabled: false });
    await fixture.owner.load();
    await fixture.owner.assess();
    fixture.read.mockResolvedValueOnce({ ...payload(), assessment: null, available: false, unavailable_reason: "source_unavailable" });
    await fixture.owner.load();
    await fixture.owner.assess();
    await fixture.owner.load();
    await fixture.owner.proposeRouting("rule:other", "group:source", "group:replacement");
    expect(network).not.toHaveBeenCalled();
    expect(fixture.authorization).not.toHaveBeenCalled();
  });

  it("does not retry unknown outcomes, even after an explicit read refresh", async () => {
    const fixture = setup();
    await fixture.owner.load();
    network.mockRejectedValueOnce(new TypeError("Network unavailable"));
    await fixture.owner.assess();
    expect(fixture.onCommand).toHaveBeenLastCalledWith("unknown");
    await fixture.owner.load();
    await fixture.owner.assess();
    await fixture.owner.proposeRouting("rule:example", "group:source", "group:replacement");
    expect(network).toHaveBeenCalledTimes(1);
    expect(fixture.onCommand).toHaveBeenLastCalledWith("unknown");
  });

  it("retains the unknown hold when the same principal returns to a scope", async () => {
    const fixture = setup();
    await fixture.owner.load();
    network.mockRejectedValueOnce(new TypeError("Network unavailable"));
    await fixture.owner.assess();
    fixture.owner.dispose();
    const revisited = setup(scope, fixture.memory);
    await revisited.owner.load();
    await revisited.owner.assess();
    expect(revisited.onCommand).toHaveBeenLastCalledWith("unknown");
    expect(network).toHaveBeenCalledTimes(1);
  });

  it("requires a fresh read before another deliberate request after a conflict", async () => {
    const fixture = setup();
    await fixture.owner.load();
    network.mockResolvedValueOnce(new Response('{"detail":"revision conflict"}', { status: 409 }));
    await fixture.owner.assess();
    expect(fixture.onCommand).toHaveBeenLastCalledWith("rejected");
    await fixture.owner.assess();
    expect(network).toHaveBeenCalledTimes(1);
    await fixture.owner.load();
    await fixture.owner.assess();
    expect(network).toHaveBeenCalledTimes(2);
  });

  it("treats an invalid successful response as unknown and does not retry it", async () => {
    const fixture = setup();
    await fixture.owner.load();
    network.mockResolvedValueOnce(new Response('{"authority":"enforce"}', { status: 202 }));
    await fixture.owner.assess();
    expect(fixture.onCommand).toHaveBeenLastCalledWith("unknown");
    await fixture.owner.assess();
    expect(network).toHaveBeenCalledTimes(1);
    expect(fixture.read).toHaveBeenCalledTimes(1);
  });
});

describe("cancellation, delayed credentials and total deadlines", () => {
  it("rechecks a disabled or refreshing settings preference after delayed request authentication", async () => {
    let enabled = true;
    const fixture = setup(scope, createAlertQualityRequestMemory(), () => enabled);
    const header = deferred<string | null>();
    fixture.authorization.mockImplementationOnce(() => header.promise);
    await fixture.owner.load();
    const request = fixture.owner.assess();
    enabled = false;
    header.resolve("Bearer test-only");
    await request;
    expect(network).not.toHaveBeenCalled();
    expect(fixture.onCommand).toHaveBeenLastCalledWith("blocked");
  });

  it("cannot turn a server requestability veto into permission by enabling settings", async () => {
    let enabled = false;
    const fixture = setup(scope, createAlertQualityRequestMemory(), () => enabled);
    fixture.read.mockResolvedValue({ ...payload(), requestable: false });
    await fixture.owner.load();
    enabled = true;
    await fixture.owner.assess();
    expect(network).not.toHaveBeenCalled();
    expect(fixture.onCommand).toHaveBeenLastCalledWith("blocked");
  });

  it("stops before sending if unmounted during authentication", async () => {
    const fixture = setup();
    const header = deferred<string | null>();
    fixture.authorization.mockImplementationOnce(() => header.promise);
    await fixture.owner.load();
    const request = fixture.owner.assess();
    fixture.owner.dispose();
    fixture.onRead.mockClear();
    fixture.onCommand.mockClear();
    header.resolve("Bearer test-only");
    await request;
    expect(network).not.toHaveBeenCalled();
    expect(fixture.onRead).not.toHaveBeenCalled();
    expect(fixture.onCommand).not.toHaveBeenCalled();
  });

  it("rechecks report expiry after authentication, immediately before transport", async () => {
    const fixture = setup();
    const header = deferred<string | null>();
    fixture.authorization.mockImplementationOnce(() => header.promise);
    await fixture.owner.load();
    const request = fixture.owner.proposeRouting("rule:example", "group:source", "group:replacement");
    vi.setSystemTime(new Date(report.valid_until));
    header.resolve("Bearer test-only");
    await request;
    expect(network).not.toHaveBeenCalled();
    expect(fixture.onCommand).toHaveBeenLastCalledWith("blocked");
  });

  it("does not send or repaint after the principal, client or authorized selection fence changes", async () => {
    const fixture = setup();
    const header = deferred<string | null>();
    fixture.authorization.mockImplementationOnce(() => header.promise);
    await fixture.owner.load();
    const request = fixture.owner.assess();
    fixture.authorizationContext.current = false;
    fixture.onRead.mockClear();
    fixture.onCommand.mockClear();
    header.resolve("Bearer test-only");
    await request;
    expect(network).not.toHaveBeenCalled();
    expect(fixture.onRead).not.toHaveBeenCalled();
    expect(fixture.onCommand).not.toHaveBeenCalled();
    await fixture.owner.load();
    expect(fixture.read).toHaveBeenCalledTimes(1);
  });

  it("does not send a request after authentication exceeds the deadline", async () => {
    const fixture = setup();
    const header = deferred<string | null>();
    fixture.authorization.mockImplementationOnce(() => header.promise);
    await fixture.owner.load();
    const request = fixture.owner.assess();
    await vi.advanceTimersByTimeAsync(15_000);
    await request;
    expect(fixture.onCommand).toHaveBeenLastCalledWith("blocked");
    header.resolve("Bearer test-only");
    await vi.advanceTimersByTimeAsync(1);
    expect(network).not.toHaveBeenCalled();
  });

  it("ignores late completion after Stop waiting and never calls a cancellation endpoint", async () => {
    const fixture = setup();
    const sent = deferred<void>();
    const reply = deferred<Response>();
    network.mockImplementationOnce(async () => { sent.resolve(); return reply.promise; });
    await fixture.owner.load();
    const request = fixture.owner.assess();
    await sent.promise;
    fixture.owner.stopWaiting();
    expect(fixture.onCommand).toHaveBeenLastCalledWith("unknown");
    const events = fixture.onCommand.mock.calls.length;
    reply.resolve(response());
    await request;
    expect(fixture.onCommand.mock.calls).toHaveLength(events);
    await fixture.owner.load();
    await fixture.owner.assess();
    expect(network).toHaveBeenCalledTimes(1);
  });

  it("bounds a response body that never finishes and does not claim submission", async () => {
    const fixture = setup();
    const body = deferred<unknown>();
    const reply = response();
    vi.spyOn(reply, "json").mockImplementation(() => body.promise);
    network.mockResolvedValueOnce(reply);
    await fixture.owner.load();
    const request = fixture.owner.assess();
    await vi.advanceTimersByTimeAsync(15_000);
    await request;
    expect(fixture.onCommand).toHaveBeenLastCalledWith("unknown");
    body.resolve({});
    await vi.advanceTimersByTimeAsync(1);
    expect(fixture.onCommand).toHaveBeenLastCalledWith("unknown");
    expect(network).toHaveBeenCalledTimes(1);
  });

  it("reports a missing authorization header as unsent", async () => {
    const fixture = setup();
    fixture.authorization.mockResolvedValueOnce(null);
    await fixture.owner.load();
    await fixture.owner.assess();
    expect(network).not.toHaveBeenCalled();
    expect(fixture.onCommand).toHaveBeenLastCalledWith("blocked");
  });
});
