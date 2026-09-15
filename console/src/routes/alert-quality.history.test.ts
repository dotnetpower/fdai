/** Pure contracts and request orchestration; browser assertions live in the route E2E test. */
import { isValidElement, toChildArray, type ComponentChildren, type VNode } from "preact";
import { afterEach, expect, it, vi } from "vitest";
import { setLocale } from "../i18n";
import { RequestView } from "./alert-quality.history";
import { decodeAlertRequestHistory } from "./alert-quality.history.model";
import { createAlertHistorySession } from "./alert-quality.history.requests";
import { createAlertQualityRequestMemory, type AlertClient } from "./alert-quality.requests";
import fixture from "./alert-quality.history.fixture.json";
import en from "./i18n/alert-quality.en.json";
import ko from "./i18n/alert-quality.ko.json";

const scope = fixture.scope_ref;
afterEach(() => { vi.useRealTimers(); setLocale("en"); });

it("decodes the exact backend-validated no-authority detail", () => {
  const data = decodeAlertRequestHistory(fixture, scope);
  expect(data.requests[0]!.detail!.baseline.rule.ref).toBe(fixture.requests[0]!.plan.treatment.target_ref);
  expect(data.requests[0]!.detail!.process!.status).toBe("waiting");
});

it.each([
  { scope_ref: "scope:other" }, { execution_authority: true }, { truncated: 1 },
  { read_at: "2026-09-14T09:00:00Z" }, { requests: Array(26).fill(fixture.requests[0]) },
  { read_at: "2026-02-31T10:00:00Z" }, { extra: "not allowed" },
])("rejects unsafe history envelope %s", (change) => {
  expect(() => decodeAlertRequestHistory({ ...fixture, ...change }, scope)).toThrow();
});

it.each([
  { execution_authority: true }, { request_key: "key\n" }, { status: "applied" },
  { result_recorded_at: null }, { plan: null }, { reason: "private message with spaces" },
  { accepted_at: "2026-09-14T09:00:00Z" }, { accepted_at: "2026-09-14T10:06:00Z" },
  { detail: { ...fixture.requests[0]!.detail, recorded_at: "2026-09-14T10:04:00Z" } },
])("rejects unsafe request row %s", (change) => {
  expect(() => decodeAlertRequestHistory({ ...fixture, requests: [{ ...fixture.requests[0], ...change }] }, scope)).toThrow();
});

it("keeps pending and unconfirmed distinct from recorded terminal state", () => {
  for (const status of ["pending", "unconfirmed"]) {
    const data = decodeAlertRequestHistory({ ...fixture, requests: [{ ...fixture.requests[0], status, plan: null, detail: null, result_recorded_at: null }] }, scope);
    expect(data.requests[0]!.status).toBe(status);
  }
});

it.each(["en", "ko"] as const)("renders native Process link and observed baseline in %s", (locale) => {
  setLocale(locale);
  const strings: string[] = [], links: string[] = [];
  function walk(children: ComponentChildren): void {
    for (const child of toChildArray(children)) {
      if (typeof child === "string" || typeof child === "number") strings.push(String(child));
      else if (isValidElement(child)) {
        const item = child as VNode<Record<string, unknown>>;
        if (typeof item.type === "function") walk((item.type as (p: Record<string, unknown>) => ComponentChildren)(item.props));
        else { if (item.type === "a") links.push(String(item.props.href)); walk(item.props.children as ComponentChildren); }
      }
    }
  }
  walk(RequestView({ entry: decodeAlertRequestHistory(fixture, scope).requests[0]! }));
  expect(links).toContain("/processes/example-alert-process");
  expect(strings.join(" ")).toContain((locale === "en" ? en : ko)["history.baselineGroups"]);
  expect(strings.join(" ")).not.toContain((locale === "en" ? en : ko).beforeMissing);
});

it("reconciles only an explicit exact original-key terminal without resending", async () => {
  const memory = createAlertQualityRequestMemory();
  memory.remember(scope, "test-history"); memory.markUnknown(scope);
  const client = { panel: vi.fn(async () => fixture), authorizationHeader: vi.fn(async () => "Bearer test-only"), operatorApiBaseUrl: "http://test.invalid" } as unknown as AlertClient;
  const reconciled = vi.fn(), reads = vi.fn();
  const session = createAlertHistorySession(client, scope, memory, () => true, reads, reconciled);
  await session.load();
  expect(memory.isUnknown(scope)).toBe(true);
  await session.load(true);
  expect(client.panel).toHaveBeenLastCalledWith("/alert-quality/requests", { scope_ref: scope, request_key: "test-history" });
  expect(memory.isUnknown(scope)).toBe(false);
  expect(reconciled).toHaveBeenCalledTimes(1);
  session.dispose();
});

it.each(["unconfirmed", "mismatch", "unavailable"])("never clears an uncertain write from %s", async (kind) => {
  const memory = createAlertQualityRequestMemory();
  memory.remember(scope, "test-history"); memory.markUnknown(scope);
  const raw = kind === "unconfirmed" ? { ...fixture, requests: [{ ...fixture.requests[0], status: "unconfirmed", result_recorded_at: null, plan: null, detail: null }] }
    : { ...fixture, requests: [{ ...fixture.requests[0], request_key: "different" }] };
  const client = { panel: vi.fn(async () => { if (kind === "unavailable") throw new Error("unavailable"); return raw; }),
    authorizationHeader: async () => "Bearer test-only", operatorApiBaseUrl: "http://test.invalid" } as unknown as AlertClient;
  const reconciled = vi.fn();
  await createAlertHistorySession(client, scope, memory, () => true, vi.fn(), reconciled).load(true);
  expect(memory.isUnknown(scope)).toBe(true);
  expect(reconciled).not.toHaveBeenCalled();
});

it("withdraws access before delayed authentication can start a read", async () => {
  let resolve!: (value: string) => void;
  const client = { panel: vi.fn(async () => fixture), authorizationHeader: () => new Promise<string>((done) => { resolve = done; }), operatorApiBaseUrl: "http://test.invalid" } as unknown as AlertClient;
  const memory = createAlertQualityRequestMemory(), reads = vi.fn();
  const session = createAlertHistorySession(client, scope, memory, () => true, reads, vi.fn());
  const pending = session.load(); session.dispose(); resolve("Bearer test-only"); await pending;
  expect(client.panel).not.toHaveBeenCalled();
  expect(reads).toHaveBeenCalledTimes(1);
});
