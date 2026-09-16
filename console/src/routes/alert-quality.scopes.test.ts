import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { OperatorApiError } from "../api";
import type { AuthContext } from "../auth";
import type { AsyncState } from "../components/ui";
import type { ConsoleDataMode } from "../console-data-mode";
import { createAlertQualityScopesSession, createAlertQualitySession, type AlertClient, type AlertQualityScopesSession } from "./alert-quality.requests";
import { ALERT_MAX_SCOPES, alertQualityPrincipal, decodeAlertQualityScopes, selectAlertQualityScope, type AlertQualityScopes } from "./alert-quality.scopes";

// Synthetic identity and transport only. These tests do not contact an identity provider or API.
const scope = "scope:example_team.alpha-1";
const payload = (scope_refs: readonly string[] = [scope]) => ({
  source: "alert-noise-governance", scope_refs, execution_authority: false,
});
const auth = (id = "example-account"): AuthContext => ({
  devMode: false, account: { homeAccountId: id, localAccountId: id, username: "user@example.com" },
  getAuthorizationHeader: async () => "Bearer test-only",
  signIn: async () => {}, signOut: async () => {},
});
const owners: AlertQualityScopesSession[] = [];

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function setup(options: { auth?: AuthContext; mode?: ConsoleDataMode } = {}) {
  const read = vi.fn<(path: string, params?: Record<string, string>) => Promise<unknown>>().mockResolvedValue(payload());
  const authorization = vi.fn<() => Promise<string | null>>().mockResolvedValue("Bearer test-only");
  const onRead = vi.fn<(state: AsyncState<AlertQualityScopes>) => void>();
  const client: AlertClient = {
    operatorApiBaseUrl: "https://operator.example", authorizationHeader: authorization,
    async panel<T>(path: string, params?: Record<string, string>): Promise<T> {
      return await (params === undefined ? read(path) : read(path, params)) as T;
    },
  };
  const context: { client: AlertClient; auth: AuthContext; mode: ConsoleDataMode } = {
    client, auth: options.auth ?? auth(), mode: options.mode ?? "live",
  };
  const principal = alertQualityPrincipal(context.auth, context.mode);
  const current = () => principal !== null && context.client === client
    && alertQualityPrincipal(context.auth, context.mode) === principal;
  const owner = createAlertQualityScopesSession(client, current, onRead);
  owners.push(owner);
  return { owner, read, authorization, onRead, context, current, client };
}

beforeEach(() => { vi.useFakeTimers(); });
afterEach(() => { for (const owner of owners.splice(0)) owner.dispose(); vi.useRealTimers(); });

describe("exact bounded authorized-scope contract", () => {
  it("accepts an empty list and the exact 64-reference limit without inventing a scope", () => {
    const empty = decodeAlertQualityScopes(payload([]));
    expect(empty.scope_refs).toEqual([]);
    expect(selectAlertQualityScope(new URLSearchParams(), empty)).toEqual({ status: "missing" });
    const maximum = Array.from({ length: ALERT_MAX_SCOPES }, (_, index) => `scope:example-${String(index).padStart(2, "0")}`);
    expect(decodeAlertQualityScopes(payload(maximum)).scope_refs).toEqual(maximum);
    expect(selectAlertQualityScope(new URLSearchParams(), decodeAlertQualityScopes(payload(maximum)))).toEqual({ status: "missing" });
    expect(Object.isFrozen(decodeAlertQualityScopes(payload()).scope_refs)).toBe(true);
  });

  it.each([
    null, [], {}, { ...payload(), source: "sample" }, { ...payload(), execution_authority: true },
    { ...payload(), execution_authority: "false" }, { ...payload(), scope_ref: scope },
    { ...payload(), scope_refs: null }, { ...payload(), scope_refs: [scope, scope] },
    payload(["scope:z", "scope:a"]), payload(["Scope:example"]), payload([`${scope}\n`]),
    payload(["scope:*"]), payload(["/subscriptions/example"]), payload(["user@example.com"]),
    payload(Array.from({ length: 65 }, (_, index) => `scope:example-${index}`)),
  ])("rejects malformed or broadened discovery atomically", (value) => {
    expect(() => decodeAlertQualityScopes(value)).toThrow();
  });

  it("opens one unambiguous discovered scope and admits explicit URL scope only by exact membership", () => {
    const scopes = decodeAlertQualityScopes(payload());
    expect(selectAlertQualityScope(new URLSearchParams(), scopes)).toEqual({ status: "selected", scope });
    expect(selectAlertQualityScope(new URLSearchParams({ scope_ref: scope }), scopes)).toEqual({ status: "selected", scope });
    expect(selectAlertQualityScope(new URLSearchParams("scope_ref=scope:other"), scopes)).toEqual({ status: "unauthorized" });
    for (const query of [`scope_ref=${scope}&scope_ref=${scope}`, "scope_ref=", "scope_ref=%20scope:example", "scope_ref=%2Fprovider%2Fpath"]) {
      expect(selectAlertQualityScope(new URLSearchParams(query), scopes)).toEqual({ status: "invalid" });
    }
    expect(selectAlertQualityScope(new URLSearchParams(), decodeAlertQualityScopes(payload([scope, "scope:other"]))))
      .toEqual({ status: "missing" });
  });
});

describe("authenticated Live-only discovery with no polling", () => {
  it("calls only the scopes panel with no query arguments and never loops on its result", async () => {
    const fixture = setup();
    await fixture.owner.load();
    expect(fixture.read).toHaveBeenCalledExactlyOnceWith("/alert-quality/scopes");
    expect(fixture.onRead.mock.calls[0]?.[0]).toEqual({ status: "loading" });
    expect(fixture.onRead).toHaveBeenLastCalledWith({ status: "ready", data: decodeAlertQualityScopes(payload()) });
    await vi.advanceTimersByTimeAsync(120_000);
    expect(fixture.read).toHaveBeenCalledTimes(1);
    expect(vi.getTimerCount()).toBe(0);
  });

  it("does not acquire credentials or read scopes in Sample, anonymous or synthetic dev mode", async () => {
    for (const options of [
      { mode: "sample" as const },
      { auth: { ...auth(), account: null } },
      { auth: { ...auth(), devMode: true } },
    ]) {
      const fixture = setup(options);
      await fixture.owner.load();
      expect(fixture.read).not.toHaveBeenCalled();
      expect(fixture.authorization).not.toHaveBeenCalled();
    }
    const cli = { ...auth(), devMode: true, localAzureCli: true };
    expect(alertQualityPrincipal(cli, "live")).not.toBeNull();
  });

  it("does not start assessment reads for an unauthorized, missing or ambiguous scope", async () => {
    const fixture = setup();
    await fixture.owner.load();
    const scopes = decodeAlertQualityScopes(payload());
    for (const [query, available] of [
      ["scope_ref=scope:other", scopes],
      ["", decodeAlertQualityScopes(payload([scope, "scope:other"]))],
      [`scope_ref=${scope}&scope_ref=${scope}`, scopes],
    ] as const) {
      const selection = selectAlertQualityScope(new URLSearchParams(query), available);
      const report = createAlertQualitySession(fixture.client, "scope:other", vi.fn(), vi.fn(),
        () => fixture.current() && selection.status === "selected");
      await report.load();
      await report.assess();
      report.dispose();
    }
    expect(fixture.read).toHaveBeenCalledExactlyOnceWith("/alert-quality/scopes");
  });

  it("keeps unsupported discovery unavailable and auth, malformed or transport failures as errors", async () => {
    const fixture = setup();
    for (const [error, status] of [
      [new OperatorApiError(404, "not served"), "unavailable"],
      [new OperatorApiError(503, "missing", "projection-unavailable"), "unavailable"],
      [new OperatorApiError(403, "denied"), "error"],
      [new OperatorApiError(503, "transport failure"), "error"],
    ] as const) {
      fixture.read.mockRejectedValueOnce(error);
      await fixture.owner.load();
      expect(fixture.onRead).toHaveBeenLastCalledWith(expect.objectContaining({ status }));
    }
    fixture.read.mockResolvedValueOnce(payload([scope, scope]));
    await fixture.owner.load();
    expect(fixture.onRead).toHaveBeenLastCalledWith(expect.objectContaining({ status: "error" }));
    fixture.authorization.mockResolvedValueOnce(null);
    const count = fixture.read.mock.calls.length;
    await fixture.owner.load();
    expect(fixture.read).toHaveBeenCalledTimes(count);
    expect(fixture.onRead).toHaveBeenLastCalledWith(expect.objectContaining({ status: "error" }));
  });
});

describe("scope request generation and identity races", () => {
  it.each(["principal", "client", "sample", "unmount"] as const)("fences delayed authentication after %s changes", async (change) => {
    const fixture = setup();
    const header = deferred<string | null>();
    fixture.authorization.mockImplementationOnce(() => header.promise);
    const request = fixture.owner.load();
    if (change === "principal") fixture.context.auth = auth("other-example-account");
    if (change === "client") fixture.context.client = { ...fixture.client };
    if (change === "sample") fixture.context.mode = "sample";
    if (change === "unmount") fixture.owner.dispose();
    fixture.onRead.mockClear();
    header.resolve("Bearer test-only");
    await request;
    expect(fixture.read).not.toHaveBeenCalled();
    expect(fixture.onRead).not.toHaveBeenCalled();
  });

  it.each(["principal", "client", "unmount"] as const)("discards a late scopes response after %s changes", async (change) => {
    const fixture = setup();
    const result = deferred<unknown>();
    const sent = deferred<void>();
    fixture.read.mockImplementationOnce(() => { sent.resolve(); return result.promise; });
    const request = fixture.owner.load();
    await sent.promise;
    if (change === "principal") fixture.context.auth = auth("other-example-account");
    if (change === "client") fixture.context.client = { ...fixture.client };
    if (change === "unmount") fixture.owner.dispose();
    fixture.onRead.mockClear();
    result.resolve(payload());
    await request;
    expect(fixture.onRead).not.toHaveBeenCalled();
  });

  it("never overwrites a newer allowlist with an older response", async () => {
    const fixture = setup();
    const result = deferred<unknown>();
    const sent = deferred<void>();
    fixture.read.mockImplementationOnce(() => { sent.resolve(); return result.promise; });
    const older = fixture.owner.load();
    await sent.promise;
    fixture.read.mockResolvedValueOnce(payload([]));
    await fixture.owner.load();
    const count = fixture.onRead.mock.calls.length;
    result.resolve(payload());
    await older;
    expect(fixture.onRead.mock.calls).toHaveLength(count);
    expect(fixture.onRead).toHaveBeenLastCalledWith({ status: "ready", data: decodeAlertQualityScopes(payload([])) });
  });

  it("bounds delayed authentication and prevents a GET after the total deadline", async () => {
    const fixture = setup();
    const header = deferred<string | null>();
    fixture.authorization.mockImplementationOnce(() => header.promise);
    const request = fixture.owner.load();
    await vi.advanceTimersByTimeAsync(15_000);
    await request;
    expect(fixture.onRead).toHaveBeenLastCalledWith(expect.objectContaining({ status: "error" }));
    header.resolve("Bearer test-only");
    await vi.advanceTimersByTimeAsync(0);
    expect(fixture.read).not.toHaveBeenCalled();
  });
});
