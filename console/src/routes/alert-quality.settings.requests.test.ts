import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OperatorApiError } from "../api";
import type { AuthContext } from "../auth";
import type { ConsoleDataMode } from "../console-data-mode";
import backendFixture from "./alert-quality.backend.fixture.json";
import { createAlertQualitySession } from "./alert-quality.requests";
import { alertQualityPrincipal } from "./alert-quality.scopes";
import fixture from "./alert-quality.settings.fixture.json";
import {
  createAlertQualitySettingsMemory, createAlertQualitySettingsSession,
  type AlertQualitySettingsClient, type AlertQualitySettingsState,
} from "./alert-quality.settings.requests";
import type { IamOverview, IamRole } from "./settings-iam.model";

// Synthetic transport and principal only. No test needs a browser, backend, Entra or live store.
const scope = fixture.scope_ref;
const subject = "example-account";
const recorded = (enabled: boolean, revision: number) => ({
  ...fixture, enabled, revision, preference_state: "recorded", recorded_at: "2026-09-14T10:30:00Z",
});
const reply = (value: unknown, status = 200) => new Response(JSON.stringify(value), { status, headers: { "content-type": "application/json" } });
const owners: Array<{ dispose: () => void }> = [];
let network: ReturnType<typeof vi.fn<typeof fetch>>;

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((yes) => { resolve = yes; });
  return { promise, resolve };
}

function overview(roles: readonly IamRole[] = ["Owner"], oid = subject): IamOverview {
  return {
    principal: { oid, roles, capabilities: ["manage-runtime-settings"] }, roles: [],
    assignmentBoundary: "identity-provider-group",
    authority: { source: "server-verified", isOwner: roles.includes("Owner"), canManageGroupMembership: false },
    directory: { source: "not-configured", availability: "unavailable", observedAt: null, detail: null },
    workflow: { accessRequestAuthority: "proposal_only", assignmentAuthority: "observation_only", providerMutation: "promotion_required" },
  };
}

function setup(memory = createAlertQualitySettingsMemory()) {
  const read = vi.fn<(path: string, params?: Record<string, string>) => Promise<unknown>>().mockResolvedValue(fixture);
  const authorization = vi.fn<() => Promise<string | null>>().mockResolvedValue("Bearer test-only");
  const iam = vi.fn<() => Promise<IamOverview>>().mockResolvedValue(overview());
  const onState = vi.fn<(state: AlertQualitySettingsState) => void>();
  const auth: AuthContext = {
    devMode: false, account: { homeAccountId: subject, localAccountId: subject, username: "user@example.com",
      idTokenClaims: { roles: ["Owner"] } }, // Must not substitute for the API principal.
    getAuthorizationHeader: authorization, signIn: async () => {}, signOut: async () => {},
  };
  const client: AlertQualitySettingsClient = {
    operatorApiBaseUrl: "https://operator.example", authorizationHeader: authorization, iamOverview: iam,
    async panel<T>(path: string, params?: Record<string, string>): Promise<T> { return await read(path, params) as T; },
  };
  const context: { auth: AuthContext; client: AlertQualitySettingsClient; mode: ConsoleDataMode; scope: string; allowed: boolean } = {
    auth, client, mode: "live", scope, allowed: true,
  };
  const principal = alertQualityPrincipal(auth, "live");
  const current = () => context.auth === auth && context.client === client && context.scope === scope && context.allowed
    && principal !== null && alertQualityPrincipal(context.auth, context.mode) === principal;
  const owner = createAlertQualitySettingsSession(client, auth, scope, subject, current, onState, memory);
  owners.push(owner);
  return { owner, read, authorization, iam, onState, context, current, client, memory,
    state: () => onState.mock.calls.at(-1)![0] };
}

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date("2026-09-14T10:30:00Z"));
  network = vi.fn<typeof fetch>().mockImplementation(async (_url, options) => {
    const body = JSON.parse(String(options?.body)) as { enabled: boolean; expected_revision: number };
    return reply(recorded(body.enabled, body.expected_revision + 1));
  });
  vi.stubGlobal("fetch", network);
});

afterEach(() => {
  for (const owner of owners.splice(0)) owner.dispose();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("scope-local independent preference and IAM reads", () => {
  it("reads exactly one scoped settings projection and the existing IAM client without polling", async () => {
    const test = setup();
    await test.owner.load();
    expect(test.read).toHaveBeenCalledExactlyOnceWith("/alert-quality/settings", { scope_ref: scope });
    expect(test.iam).toHaveBeenCalledTimes(1);
    expect(test.state()).toMatchObject({ read: { status: "ready", data: fixture }, authority: "owner", editable: true });
    expect(test.owner.requestsAllowed()).toBe(true);
    await vi.advanceTimersByTimeAsync(120_000);
    expect(test.read).toHaveBeenCalledTimes(1);
    expect(test.iam).toHaveBeenCalledTimes(1);
    expect(network).not.toHaveBeenCalled();
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not let IAM failure hide the readable preference or make manual requests Owner-only", async () => {
    const test = setup();
    test.iam.mockRejectedValueOnce(new OperatorApiError(503, "private identity detail"));
    await test.owner.load();
    expect(test.state()).toMatchObject({ read: { status: "ready" }, authority: "unavailable", editable: false });
    expect(test.owner.requestsAllowed()).toBe(true);
    await test.owner.save(false, 0);
    expect(network).not.toHaveBeenCalled();
    test.iam.mockResolvedValue(overview(["Contributor"]));
    await test.owner.load();
    expect(test.state().authority).toBe("read-only");
    expect(test.owner.requestsAllowed()).toBe(true);
  });

  it("ignores browser Owner claims, other principals and every non-Owner server role", async () => {
    for (const roles of [[], ["Reader"], ["Contributor"], ["Approver"], ["BreakGlass"]] as const) {
      const test = setup();
      test.iam.mockResolvedValue(overview(roles));
      await test.owner.load();
      await test.owner.save(false, 0);
      expect(test.state().editable).toBe(false);
    }
    const other = setup();
    other.iam.mockResolvedValue(overview(["Owner"], "other-example-account"));
    await other.owner.load();
    await other.owner.save(false, 0);
    expect(network).not.toHaveBeenCalled();
  });

  it("does not read or acquire credentials for inactive auth, Sample or revoked scope", async () => {
    for (const change of ["auth", "sample", "scope"] as const) {
      const test = setup();
      if (change === "auth") test.context.auth = { ...test.context.auth, account: null };
      if (change === "sample") test.context.mode = "sample";
      if (change === "scope") test.context.allowed = false;
      await test.owner.load();
      await test.owner.save(false, 0);
      expect(test.authorization).not.toHaveBeenCalled();
      expect(test.read).not.toHaveBeenCalled();
      expect(test.iam).not.toHaveBeenCalled();
    }
    expect(network).not.toHaveBeenCalled();
  });

  it("retains optional-unavailable versus error distinctions without exposing dependency text", async () => {
    const test = setup();
    for (const [error, expected] of [[new OperatorApiError(404, "private"), "unavailable"],
      [new OperatorApiError(503, "private"), "error"], [new Error("private"), "error"]] as const) {
      test.read.mockRejectedValueOnce(error);
      await test.owner.load();
      expect(test.state().read.status).toBe(expected);
      expect(JSON.stringify(test.state())).not.toContain("private");
      expect(test.owner.requestsAllowed()).toBe(false);
    }
    test.read.mockResolvedValueOnce({ ...fixture, mode: "enforce" });
    await test.owner.load();
    expect(test.state().read.status).toBe("error");
    expect(test.state().editable).toBe(false);
  });
});

describe("exact JSON preference update and revision concurrency", () => {
  it("sends one PUT without query, If-Match, actor, mode or idempotency fields and accepts only its revision", async () => {
    const test = setup();
    await test.owner.load();
    const first = test.owner.save(false, 0);
    expect(test.owner.requestsAllowed()).toBe(false);
    await Promise.all([first, test.owner.save(false, 0)]);
    expect(network).toHaveBeenCalledTimes(1);
    expect(String(network.mock.calls[0]?.[0])).toBe("https://operator.example/alert-quality/settings");
    const options = network.mock.calls[0]![1]!;
    expect(options).toMatchObject({ method: "PUT", credentials: "omit", body: JSON.stringify({ scope_ref: scope, enabled: false, expected_revision: 0 }) });
    const headers = new Headers(options.headers);
    expect(headers.get("content-type")).toBe("application/json");
    expect(headers.get("if-match")).toBeNull();
    expect(headers.get("idempotency-key")).toBeNull();
    expect(test.iam).toHaveBeenCalledTimes(2);
    expect(test.state()).toMatchObject({ command: "saved", read: { status: "ready", data: recorded(false, 1) } });
    expect(test.owner.requestsAllowed()).toBe(false);
    await test.owner.save(true, 1);
    expect(test.state()).toMatchObject({ command: "saved", read: { status: "ready", data: recorded(true, 2) } });
    expect(test.read).toHaveBeenCalledTimes(1); // No result-driven refresh loop.
  });

  it("allows a preference change with readable storage even when the producer is not ready", async () => {
    const test = setup();
    const offline = { ...fixture, available: false, unavailable_reason: "producer_not_ready",
      prerequisites: { ...fixture.prerequisites, producer_ready: false } };
    test.read.mockResolvedValue(offline);
    network.mockResolvedValueOnce(reply({ ...offline, ...recorded(false, 1), available: false,
      unavailable_reason: "producer_not_ready", prerequisites: offline.prerequisites }));
    await test.owner.load();
    expect(test.state().editable).toBe(true);
    await test.owner.save(false, 0);
    expect(test.state()).toMatchObject({ command: "saved", read: { data: { available: false, enabled: false, mode: "shadow" } } });
    expect(test.owner.requestsAllowed()).toBe(false);
  });

  it("keeps a 409 conflict locked until an explicit fresh read and a newly chosen revision", async () => {
    const test = setup();
    await test.owner.load();
    network.mockResolvedValueOnce(reply({ error: { status: 409, code: "revision_conflict" } }, 409));
    await test.owner.save(false, 0);
    expect(test.state()).toMatchObject({ command: "conflict", editable: false });
    expect(test.owner.requestsAllowed()).toBe(false);
    await test.owner.save(false, 0);
    expect(network).toHaveBeenCalledTimes(1);
    test.read.mockResolvedValue(recorded(false, 1));
    await test.owner.load();
    await test.owner.save(true, 0);
    expect(network).toHaveBeenCalledTimes(1);
    await test.owner.save(true, 1);
    expect(network).toHaveBeenCalledTimes(2);
    expect(test.state().command).toBe("saved");
  });

  it("keeps a server 403 locked after refresh and remount even when IAM still returns Owner", async () => {
    const test = setup();
    await test.owner.load();
    network.mockResolvedValueOnce(reply({ error: { status: 403, code: "forbidden" } }, 403));
    await test.owner.save(false, 0);
    expect(test.state()).toMatchObject({ command: "denied", authority: "denied", editable: false });
    await test.owner.load();
    await test.owner.save(false, 0);
    test.owner.dispose();
    const revisited = setup(test.memory);
    await revisited.owner.load();
    await revisited.owner.save(false, 0);
    expect(revisited.state()).toMatchObject({ command: "denied", authority: "denied", editable: false });
    expect(network).toHaveBeenCalledTimes(1);
  });

  it.each([{ ...recorded(false, 1), revision: 2 }, recorded(true, 1), fixture,
    { ...recorded(false, 1), scope_ref: "scope:other" }, { ...recorded(false, 1), mode: "enforce" }])
  ("holds a malformed or mismatched successful receipt as unknown, without retry", async (value) => {
    const test = setup();
    await test.owner.load();
    network.mockResolvedValueOnce(reply(value));
    await test.owner.save(false, 0);
    expect(test.state()).toMatchObject({ command: "unknown", editable: false });
    await test.owner.load();
    await test.owner.save(false, 0);
    expect(test.owner.requestsAllowed()).toBe(false);
    expect(network).toHaveBeenCalledTimes(1);
  });
});

describe("late responses, changed principals and request separation", () => {
  it("ignores an older read after a newer revision was displayed", async () => {
    const test = setup();
    const older = deferred<unknown>();
    const started = deferred<void>();
    test.read.mockImplementationOnce(() => { started.resolve(); return older.promise; });
    const first = test.owner.load();
    await started.promise;
    test.read.mockResolvedValueOnce(recorded(false, 3));
    await test.owner.load();
    const events = test.onState.mock.calls.length;
    older.resolve(fixture);
    await first;
    expect(test.onState.mock.calls).toHaveLength(events);
    expect(test.state()).toMatchObject({ read: { status: "ready", data: recorded(false, 3) } });
  });

  it.each(["auth", "scope", "client", "sample", "unmount"] as const)("never sends a PUT after %s changes during token acquisition", async (change) => {
    const test = setup();
    await test.owner.load();
    const header = deferred<string | null>();
    const started = deferred<void>();
    test.authorization.mockImplementationOnce(() => { started.resolve(); return header.promise; });
    const work = test.owner.save(false, 0);
    await started.promise;
    if (change === "auth") test.context.auth = { ...test.context.auth, account: null };
    if (change === "scope") test.context.scope = "scope:other";
    if (change === "client") test.context.client = { ...test.client };
    if (change === "sample") test.context.mode = "sample";
    if (change === "unmount") test.owner.dispose();
    test.onState.mockClear();
    header.resolve("Bearer test-only");
    await work;
    expect(network).not.toHaveBeenCalled();
    expect(test.onState).not.toHaveBeenCalled();
  });

  it("rechecks the API role before saving and refuses a revoked Owner or unavailable token", async () => {
    const test = setup();
    await test.owner.load();
    test.iam.mockResolvedValueOnce(overview(["Contributor"]));
    await test.owner.save(false, 0);
    expect(test.state()).toMatchObject({ command: "blocked", authority: "read-only", editable: false });
    await test.owner.load();
    test.authorization.mockResolvedValueOnce(null);
    await test.owner.save(false, 0);
    expect(test.state().command).toBe("blocked");
    expect(network).not.toHaveBeenCalled();
  });

  it("bounds delayed authentication and never starts a PUT after its deadline", async () => {
    const test = setup();
    await test.owner.load();
    const header = deferred<string | null>();
    test.authorization.mockImplementationOnce(() => header.promise);
    const work = test.owner.save(false, 0);
    await vi.advanceTimersByTimeAsync(15_000);
    await work;
    expect(test.state()).toMatchObject({ command: "blocked", editable: false });
    header.resolve("Bearer test-only");
    await vi.advanceTimersByTimeAsync(1);
    expect(network).not.toHaveBeenCalled();
  });

  it("bounds both settings read credentials and an incomplete successful write body", async () => {
    const readTest = setup();
    const header = deferred<string | null>();
    readTest.authorization.mockImplementation(() => header.promise);
    const read = readTest.owner.load();
    await vi.advanceTimersByTimeAsync(15_000);
    await read;
    header.resolve("Bearer test-only");
    await vi.advanceTimersByTimeAsync(1);
    expect(readTest.read).not.toHaveBeenCalled();
    expect(readTest.iam).not.toHaveBeenCalled();
    expect(readTest.state().read.status).toBe("error");

    const writeTest = setup();
    await writeTest.owner.load();
    const body = deferred<unknown>();
    const response = reply(recorded(false, 1));
    vi.spyOn(response, "json").mockImplementation(() => body.promise);
    network.mockResolvedValueOnce(response);
    const write = writeTest.owner.save(false, 0);
    await vi.advanceTimersByTimeAsync(15_000);
    await write;
    expect(writeTest.state()).toMatchObject({ command: "unknown", editable: false });
    body.resolve(recorded(false, 1));
    await vi.advanceTimersByTimeAsync(1);
    expect(writeTest.state().command).toBe("unknown");
    expect(network).toHaveBeenCalledTimes(1);
  });

  it("discards a late save response after disposal and keeps that scope's outcome unknown", async () => {
    const test = setup();
    await test.owner.load();
    const response = deferred<Response>();
    const started = deferred<void>();
    network.mockImplementationOnce(() => { started.resolve(); return response.promise; });
    const work = test.owner.save(false, 0);
    await started.promise;
    test.owner.dispose();
    test.onState.mockClear();
    response.resolve(reply(recorded(false, 1)));
    await work;
    expect(test.onState).not.toHaveBeenCalled();
    const revisited = setup(test.memory);
    await revisited.owner.load();
    await revisited.owner.save(false, 0);
    expect(revisited.state()).toMatchObject({ command: "unknown", editable: false });
    expect(network).toHaveBeenCalledTimes(1);
  });

  it("uses settings only as a veto, never as a replacement for the report's requestability", async () => {
    const test = setup();
    let projection: unknown = backendFixture;
    test.read.mockImplementation(async (path) => path === "/alert-quality/settings" ? fixture : projection);
    await test.owner.load();
    const request = vi.fn();
    const report = createAlertQualitySession(test.client, scope, vi.fn(), request, test.current, undefined, test.owner.requestsAllowed);
    owners.push(report);
    await report.load();
    await test.owner.save(false, 0);
    await report.assess();
    expect(network).toHaveBeenCalledTimes(1); // PUT only; stale enabled report cannot submit.
    projection = { ...backendFixture, requestable: false };
    await report.load();
    await test.owner.save(true, 1);
    await report.assess();
    expect(network).toHaveBeenCalledTimes(2); // Two deliberate PUTs, never a POST.
    expect(request).toHaveBeenLastCalledWith("blocked");
    expect(network.mock.calls.every((call) => call[1]?.method === "PUT")).toBe(true);
  });
});
