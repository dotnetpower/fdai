import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";
import type { VNode } from "preact";
import type { OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";
import type { IamAccessRequest, IamOverview, IdentityRosterItem } from "./settings-iam.model";
import type { TeamsWorkflowBindingView } from "./settings-teams-workflow.model";

const hooks = vi.hoisted(() => {
  type Cell = { value?: unknown; deps?: readonly unknown[] | undefined; cleanup?: (() => void) | undefined };
  let cells: Cell[] = [];
  let cursor = 0;
  let effects: (() => void)[] = [];
  return {
    begin: () => { cursor = 0; },
    effects: () => { const pending = effects; effects = []; pending.forEach((effect) => effect()); },
    reset: () => { cells.forEach((cell) => cell.cleanup?.()); cells = []; effects = []; cursor = 0; },
    useState: <T,>(initial: T | (() => T)) => {
      const index = cursor++;
      const cell = cells[index] ??= { value: typeof initial === "function" ? (initial as () => T)() : initial };
      return [cell.value as T, (next: T | ((previous: T) => T)) => {
        cell.value = typeof next === "function" ? (next as (value: T) => T)(cell.value as T) : next;
      }] as const;
    },
    useRef: <T,>(initial: T) => {
      const cell = cells[cursor++] ??= { value: { current: initial } };
      return cell.value as { current: T };
    },
    useEffect: (effect: () => void | (() => void), deps?: readonly unknown[]) => {
      const cell = cells[cursor++] ??= {};
      if (!deps || !cell.deps || deps.some((value, index) => !Object.is(value, cell.deps?.[index]))) {
        cell.deps = deps;
        effects.push(() => { cell.cleanup?.(); cell.cleanup = effect() || undefined; });
      }
    },
  };
});
const routeState = vi.hoisted(() => ({ segments: [] as string[] }));

vi.mock("preact/hooks", async (original) => ({ ...await original<object>(), ...hooks }));
vi.mock("../deck/context", () => ({ usePublishViewContext: vi.fn() }));
vi.mock("../router", async (original) => ({
  ...await original<object>(),
  currentRoute: () => ({ segments: routeState.segments, search: new URLSearchParams() }),
}));
vi.mock("./settings-teams-workflow.command", () => ({
  loadTeamsWorkflowBinding: vi.fn(), revealTeamsWorkflowBinding: vi.fn(),
  testTeamsWorkflowWebhook: vi.fn(),
}));
vi.mock("./settings-models.model", () => ({ decodeModelSettings: (value: unknown) => value }));

import { useAdministrationRead } from "./settings-administration-read";
import { SettingsIamRoute } from "./settings-iam";
import { DirectoryUserSearch } from "./settings-iam-users";
import { AccessRequestsView } from "./settings-iam-requests";
import { IamCapabilityDisclosure } from "./settings-iam-capabilities";
import { SettingsDiagnosticsRoute } from "./settings-diagnostics";
import { TeamsWorkflowTestPanel, EmailTemplatePreviewPanel } from "./settings-system";
import { DocumentOcrSettingsPanel } from "./document-ocr-settings";
import { TeamsA1OnboardingGuide } from "./settings-teams-a1-onboarding";
import { loadTeamsWorkflowBinding, testTeamsWorkflowWebhook } from "./settings-teams-workflow.command";

const auth: AuthContext = {
  devMode: true, account: null, getAuthorizationHeader: async () => null,
  signIn: async () => undefined, signOut: async () => undefined,
};
const overview: IamOverview = {
  principal: { oid: "current-1", roles: ["Owner"], capabilities: [] },
  roles: [], assignmentBoundary: "identity-provider-group",
  authority: { source: "server-verified", isOwner: true, canManageGroupMembership: true },
  directory: { source: "synthetic", availability: "available", observedAt: null, detail: null },
  workflow: { accessRequestAuthority: "proposal_only", assignmentAuthority: "observation_only", providerMutation: "promotion_required" },
};
const roster: IdentityRosterItem[] = [
  { provider: "entra", subjectId: "person-a", displayName: "Example A", username: "a@example.com", active: true, roles: ["Reader"], principalType: "person" },
  { provider: "entra", subjectId: "person-b", displayName: "Example B", username: "b@example.com", active: true, roles: ["Reader"], principalType: "person" },
];
const accessRequest: IamAccessRequest = {
  requestId: "request-1", idempotencyKey: "intent-1", requesterOid: "another-owner",
  identityProvider: "entra", targetSubjectId: "person-a", targetUsername: "a@example.com",
  operation: "grant", role: "Reader", justification: "The applicant's synthetic request rationale.",
  requestedAt: "2026-01-01T00:00:00Z", status: "pending",
  reviewedBy: null, reviewedAt: null, reviewJustification: null,
};
const binding: TeamsWorkflowBindingView = {
  visible: true, configured: true, bindingVersion: "version-1", endpointIdentifier: "synthetic-binding",
  observedAt: "2026-01-01T00:00:00Z", savedAt: null,
  deliveryTargets: ["teams-a2-operational-alert", "email"], emailRecipientMode: "login", customEmail: "",
  channels: [{ channelId: "channel-1", label: "Example channel", bindingVersion: "version-1", endpointIdentifier: "synthetic-channel", enabled: true, savedAt: null }],
};
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
async function settle() { for (let i = 0; i < 12; i += 1) await Promise.resolve(); }
function render<T>(component: () => T): T { hooks.begin(); const tree = component(); hooks.effects(); return tree; }
function all(tree: unknown): VNode<Record<string, unknown>>[] {
  if (Array.isArray(tree)) return tree.flatMap(all);
  if (!tree || typeof tree !== "object" || !("props" in tree)) return [];
  const node = tree as VNode<Record<string, unknown>>;
  return [node, ...all(node.props.children)];
}
function content(tree: unknown): string {
  if (Array.isArray(tree)) return tree.map(content).join("");
  if (typeof tree === "string" || typeof tree === "number") return String(tree);
  return tree && typeof tree === "object" && "props" in tree
    ? content((tree as VNode).props.children) : "";
}
function button(tree: unknown, label: string) {
  const node = all(tree).find((node) => node.type === "button" && content(node.props.children) === label);
  expect(node, label).toBeDefined();
  return node!;
}
function click(node: VNode<Record<string, unknown>>) {
  expect(node.props.disabled).not.toBe(true);
  (node.props.onClick as () => void)();
}
function input(node: VNode<Record<string, unknown>>, value: string) {
  const handler = node.props.onInput ?? node.props.oninput;
  expect(typeof handler, Object.keys(node.props).join(", ")).toBe("function");
  (handler as (event: unknown) => void)({ currentTarget: { value } });
}

beforeEach(() => {
  hooks.reset();
  routeState.segments = [];
  vi.clearAllMocks();
  vi.stubGlobal("window", { addEventListener: vi.fn(), removeEventListener: vi.fn(), setTimeout, clearTimeout });
  vi.stubGlobal("document", { getElementById: () => null });
  vi.stubGlobal("requestAnimationFrame", (callback: () => void) => { callback(); return 1; });
  vi.mocked(loadTeamsWorkflowBinding).mockResolvedValue(binding);
});
afterEach(() => { hooks.reset(); vi.unstubAllGlobals(); });

describe("read-only projection recovery", () => {
  test("N01 N02 recovery preserves verified data, marks refresh failure and retries only the read", async () => {
    const owner = {};
    const read = vi.fn<() => Promise<string>>().mockResolvedValueOnce("verified").mockRejectedValueOnce(new Error("private")).mockResolvedValueOnce("updated");
    const run = () => useAdministrationRead(owner, read);
    expect(render(run).state.status).toBe("loading");
    await settle();
    let view = render(run);
    expect(view.state).toEqual({ status: "ready", data: "verified" });
    const observed = view.observedAt;
    view.refresh(); view.refresh();
    render(run);
    await settle();
    view = render(run);
    expect(read).toHaveBeenCalledTimes(2);
    expect(view.state).toEqual({ status: "ready", data: "verified" });
    expect(view.error).toBe("read-unavailable");
    expect(view.observedAt).toBe(observed);
    view.refresh(); render(run); await settle();
    expect(render(run).state).toEqual({ status: "ready", data: "updated" });
  });
  test("N01 initial read failure is unavailable rather than an empty success", async () => {
    const owner = {};
    const run = () => useAdministrationRead(owner, async () => { throw new Error("private"); });
    render(run); await settle();
    expect(render(run)).toMatchObject({ state: { status: "unavailable" }, refreshing: false });
  });
  test("a changed client never exposes the previous client's data", async () => {
    let owner = {};
    const pending = deferred<string>();
    let read = () => pending.promise;
    const run = () => useAdministrationRead(owner, read);
    render(run);
    owner = {}; read = async () => "new client";
    expect(render(run).state.status).toBe("loading");
    pending.resolve("old client"); await settle();
    expect(render(run).state).toEqual({ status: "ready", data: "new client" });
  });
});

describe("IAM management and draft boundaries", () => {
  test("I12 capability disclosure starts collapsed and retains every canonical ID", () => {
    const tree = IamCapabilityDisclosure({ capabilities: ["view-console", "registered-synthetic-capability"] });
    expect(tree.type).toBe("details");
    expect(tree.props.open).not.toBe(true);
    expect(content(tree)).toContain("Inspect all 2 capabilities");
    expect(content(tree)).toContain("view-console");
    expect(content(tree)).toContain("registered-synthetic-capability");
  });
  test("I01 I02 authority, not capability spelling, gates independent supplemental reads", async () => {
    const requests = deferred<{ items: []; total: number; nextCursor: null }>();
    const client = {
      iamOverview: vi.fn().mockResolvedValue(overview),
      listIamAccessRequests: vi.fn().mockReturnValue(requests.promise),
      iamRoster: vi.fn().mockResolvedValue(roster),
    };
    const run = () => SettingsIamRoute({ client: client as unknown as OperatorApiClient, auth });
    render(run); await settle();
    expect(client.iamRoster).toHaveBeenCalledOnce();
    expect(client.listIamAccessRequests).toHaveBeenCalledOnce();
    routeState.segments = ["users"]; render(run);
    const userPanel = all(render(run)).find((node) => typeof node.type === "function" && node.type.name === "UsersView");
    expect(userPanel?.props.roster).toEqual(roster);
    expect(content(render(run))).not.toContain("Access requests are unavailable");
    hooks.reset();
    const restricted = { ...overview, authority: { ...overview.authority, canManageGroupMembership: false }, principal: { ...overview.principal, capabilities: ["manage-group-membership"] } };
    client.iamOverview.mockResolvedValue(restricted);
    render(run); await settle();
    expect(client.iamRoster).toHaveBeenCalledOnce();
    expect(client.listIamAccessRequests).toHaveBeenCalledOnce();
    requests.resolve({ items: [], total: 0, nextCursor: null });
    await settle();
  });
  test("I02 request records become usable while the roster is still pending", async () => {
    routeState.segments = ["requests"];
    const pendingRoster = deferred<readonly IdentityRosterItem[]>();
    const client = {
      iamOverview: vi.fn().mockResolvedValue(overview),
      listIamAccessRequests: vi.fn().mockResolvedValue({ items: [accessRequest], total: 1, nextCursor: null }),
      iamRoster: vi.fn().mockReturnValue(pendingRoster.promise),
    };
    const run = () => SettingsIamRoute({ client: client as unknown as OperatorApiClient, auth });
    render(run); await settle();
    const panel = all(render(run)).find((node) => node.type === AccessRequestsView);
    expect(panel?.props.requests).toEqual([accessRequest]);
    pendingRoster.resolve(roster); await settle();
  });
  test("I10 refreshing requests preserves the loaded window and active tab", async () => {
    routeState.segments = ["requests"];
    const page = Array.from({ length: 100 }, (_, index) => ({ ...accessRequest, requestId: `request-${index}` }));
    const client = {
      iamOverview: vi.fn().mockResolvedValue(overview), iamRoster: vi.fn().mockResolvedValue(roster),
      listIamAccessRequests: vi.fn().mockImplementation((_limit: number, cursor = 0) =>
        Promise.resolve({ items: page.slice(cursor, cursor + 50), total: 100, nextCursor: cursor === 0 ? 50 : null })),
    };
    const run = () => SettingsIamRoute({ client: client as unknown as OperatorApiClient, auth });
    render(run); await settle();
    let panel = all(render(run)).find((node) => node.type === AccessRequestsView)!;
    await (panel.props.loadMore as () => Promise<void>)(); await settle();
    panel = all(render(run)).find((node) => node.type === AccessRequestsView)!;
    expect((panel.props.requests as unknown[])).toHaveLength(100);
    const refreshing = (panel.props.reload as () => Promise<void>)();
    expect(all(render(run)).some((node) => node.type === AccessRequestsView)).toBe(true);
    await refreshing; await settle();
    panel = all(render(run)).find((node) => node.type === AccessRequestsView)!;
    expect((panel.props.requests as unknown[])).toHaveLength(100);
    expect(client.listIamAccessRequests).toHaveBeenCalledTimes(4);
  });
  test("I10 short pages cannot turn an initial read into an unbounded page scan", async () => {
    const client = {
      iamOverview: vi.fn().mockResolvedValue(overview), iamRoster: vi.fn().mockResolvedValue(roster),
      listIamAccessRequests: vi.fn().mockImplementation((_limit: number, cursor = 0) =>
        Promise.resolve({ items: [accessRequest], total: 1000, nextCursor: cursor + 50 })),
    };
    const run = () => SettingsIamRoute({ client: client as unknown as OperatorApiClient, auth });
    render(run); await settle();
    expect(client.listIamAccessRequests).toHaveBeenCalledOnce();
  });
  test("I11 a failed initial request read is unavailable, not an empty list, and retry is scoped", async () => {
    routeState.segments = ["requests"];
    const client = {
      iamOverview: vi.fn().mockResolvedValue(overview), iamRoster: vi.fn().mockResolvedValue(roster),
      listIamAccessRequests: vi.fn().mockRejectedValueOnce(new Error("synthetic read failed"))
        .mockResolvedValueOnce({ items: [accessRequest], total: 1, nextCursor: null }),
    };
    const run = () => SettingsIamRoute({ client: client as unknown as OperatorApiClient, auth });
    render(run); await settle();
    let tree = render(run);
    expect(content(tree)).toContain("This is not an empty request list");
    expect(all(tree).some((node) => node.type === AccessRequestsView)).toBe(false);
    click(button(tree, "Retry")); render(run); await settle();
    tree = render(run);
    expect(all(tree).some((node) => node.type === AccessRequestsView)).toBe(true);
    expect(client.iamOverview).toHaveBeenCalledOnce();
    expect(client.iamRoster).toHaveBeenCalledOnce();
  });
  test("I11 failed reads remain unavailable across a tab-route remount until scoped recovery", async () => {
    const pending = deferred<void>();
    let available = false;
    routeState.segments = ["users"];
    const client = {
      iamOverview: vi.fn().mockResolvedValue(overview),
      iamRoster: vi.fn().mockResolvedValue(roster),
      listIamAccessRequests: vi.fn().mockImplementation(async () => {
        await pending.promise;
        if (!available) throw new Error("Synthetic projection unavailable.");
        return { items: [accessRequest], total: 1, nextCursor: null };
      }),
    };
    const run = () => SettingsIamRoute({ client: client as unknown as OperatorApiClient, auth });
    render(run); await settle();
    expect(all(render(run)).some((node) =>
      typeof node.type === "function" && node.type.name === "UsersView")).toBe(true);
    hooks.reset();
    routeState.segments = ["requests"];
    render(run); await settle();
    pending.resolve(); await settle();
    let tree = render(run);
    expect(client.listIamAccessRequests).toHaveBeenCalledTimes(2);
    expect(content(tree)).toContain("This is not an empty request list");
    expect(all(tree).some((node) => node.type === AccessRequestsView)).toBe(false);
    const overviewReads = client.iamOverview.mock.calls.length;
    const rosterReads = client.iamRoster.mock.calls.length;
    available = true;
    click(button(tree, "Retry")); render(run); await settle();
    tree = render(run);
    const panel = all(tree).find((node) => node.type === AccessRequestsView);
    expect(panel?.props.requests).toEqual([accessRequest]);
    expect(client.listIamAccessRequests).toHaveBeenCalledTimes(3);
    expect(client.iamOverview).toHaveBeenCalledTimes(overviewReads);
    expect(client.iamRoster).toHaveBeenCalledTimes(rosterReads);
  });
  test("I04 I05 request disclosure retains rationale and approved status without claiming assignment", () => {
    const tree = render(() => AccessRequestsView({
      requests: [{ ...accessRequest, status: "approved", reviewedAt: "2026-01-02T00:00:00Z", reviewJustification: "An independent review." }],
      total: 1, hasMore: false, loadMore: async () => undefined, roster,
      canManage: true, reviewerOid: "current-1", auth, client: {} as OperatorApiClient, reload: async () => undefined,
    }));
    const table = all(tree).find((node) => Array.isArray(node.props.columns))!;
    const columns = table.props.columns as { key: string; render: (item: IamAccessRequest) => VNode }[];
    const item = (table.props.rows as IamAccessRequest[])[0]!;
    const details = columns.find((column) => column.key === "target")!.render(item);
    expect(content(details)).toContain(accessRequest.justification);
    expect(content(details)).toContain("An independent review.");
    expect(all(details).some((node) => node.type === "summary")).toBe(true);
    const status = columns.find((column) => column.key === "status")!.render(item);
    expect((status.props as unknown as { label: string }).label).toBe("Approved - effect not verified");
  });
  test("I08 I09 a new target clears the reason and the reason is accessibly labeled", () => {
    const onAssign = vi.fn().mockResolvedValue(undefined);
    const run = () => DirectoryUserSearch({
      client: {} as OperatorApiClient, canManage: true, roster, rosterAvailable: true,
      rosterError: null, referencedUsers: [], onAssign, retryRoster: vi.fn(), rosterLoading: false,
    });
    let tree = render(run);
    const table = all(tree).find((node) => Array.isArray(node.props.columns))!;
    const column = (table.props.columns as { key: string; render: (item: IdentityRosterItem) => VNode }[]).find((column) => column.key === "change")!;
    let dropdown = column.render(roster[0]!);
    (dropdown.props as unknown as { onSelect: (role: string) => void }).onSelect("Contributor");
    tree = render(run);
    let textarea = all(tree).find((node) => node.type === "textarea")!;
    expect(textarea.props.id).toBe("iam-role-justification");
    expect(all(tree).some((node) => node.type === "label" && node.props.for === textarea.props.id)).toBe(true);
    input(textarea, "Reason specifically for person A.");
    tree = render(run);
    dropdown = column.render(roster[1]!);
    (dropdown.props as unknown as { onSelect: (role: string) => void }).onSelect("Owner");
    tree = render(run);
    textarea = all(tree).find((node) => node.type === "textarea")!;
    expect(textarea.props.value).toBe("");
    expect(onAssign).not.toHaveBeenCalled();
  });
});

describe("integration-owned bounded tools", () => {
  test("N03 N04 failed binding reads differ from unconfigured and can retry", async () => {
    vi.mocked(loadTeamsWorkflowBinding).mockRejectedValueOnce(new Error("private"));
    const run = () => TeamsWorkflowTestPanel({ auth, operatorApiBaseUrl: "", canManage: true });
    let tree = render(run);
    tree = render(run);
    expect(all(tree).some((node) => node.type instanceof Function && node.type.name === "LoadingState")).toBe(true);
    await settle(); tree = render(run);
    expect(content(tree)).toContain("Saved binding metadata is unavailable");
    expect(all(tree).some((node) => node.type === "form")).toBe(false);
    click(button(tree, "Retry"));
    render(run); await settle();
    expect(all(render(run)).some((node) => node.type === "form")).toBe(true);
  });
  test("N05 N06 failed preference writes roll back, and overlapping writes are suppressed", async () => {
    const write = deferred<never>();
    vi.mocked(testTeamsWorkflowWebhook).mockReturnValue(write.promise);
    const run = () => TeamsWorkflowTestPanel({ auth, operatorApiBaseUrl: "", canManage: true });
    render(run); await settle();
    let tree = render(run);
    const checkboxes = all(tree).filter((node) => node.type === "input" && node.props.type === "checkbox");
    (checkboxes[0]!.props.onChange as () => void)();
    (checkboxes[1]!.props.onChange as () => void)();
    expect(testTeamsWorkflowWebhook).toHaveBeenCalledOnce();
    tree = render(run);
    expect(all(tree).filter((node) => node.type === "input" && node.props.type === "checkbox").every((node) => node.props.disabled)).toBe(true);
    write.reject(new Error("private")); await settle(); tree = render(run);
    expect(content(tree)).toContain("last confirmed selection has been restored");
    const restored = all(tree).filter((node) => node.type === "input" && node.props.type === "checkbox");
    expect(restored[0]!.props.checked).toBe(true);
    expect(restored[3]!.props.checked).toBe(true);
  });
  test("N07 first save includes recipient fields and standalone recipient Save is disabled", async () => {
    vi.mocked(loadTeamsWorkflowBinding).mockResolvedValueOnce({ visible: true, configured: false });
    const write = deferred<never>();
    vi.mocked(testTeamsWorkflowWebhook).mockReturnValue(write.promise);
    const run = () => TeamsWorkflowTestPanel({ auth, operatorApiBaseUrl: "", canManage: true });
    render(run); await settle();
    let tree = render(run);
    let radios = all(tree).filter((node) => node.type === "input" && node.props.type === "radio");
    (radios[1]!.props.onChange as () => void)();
    tree = render(run);
    const email = all(tree).find((node) => node.type === "input" && node.props.type === "email" && node.props["aria-label"])!;
    input(email, "recipient@example.com");
    const recipientRow = all(tree).find((node) => node.props.class === "settings-teams-workflow-email-custom-row")!;
    expect(all(recipientRow).find((node) => node.type === "button")?.props.disabled).toBe(true);
    const secretInput = all(tree).find((node) => node.type === "input" && node.props.inputMode === "url")!;
    input(secretInput, "https://example.com/synthetic");
    tree = render(run);
    const form = all(tree).find((node) => node.type === "form")!;
    (form.props.onSubmit as (event: unknown) => void)({ preventDefault: vi.fn() });
    expect(testTeamsWorkflowWebhook).toHaveBeenCalledWith(
      auth, "", "https://example.com/synthetic", expect.any(String),
      expect.objectContaining({ emailRecipientMode: "custom", customEmail: "recipient@example.com" }),
    );
    write.reject(new Error("synthetic")); await settle();
  });
  test("N08 the last selected target and channel expose a minimum selection rule", async () => {
    vi.mocked(loadTeamsWorkflowBinding).mockResolvedValue({ ...binding, deliveryTargets: ["email"] } as TeamsWorkflowBindingView);
    const run = () => TeamsWorkflowTestPanel({ auth, operatorApiBaseUrl: "", canManage: true });
    render(run); await settle();
    const tree = render(run);
    const selected = all(tree).filter((node) => node.type === "input" && node.props.type === "checkbox" && node.props.checked);
    expect(selected).toHaveLength(2);
    expect(selected.every((node) => node.props.disabled && node.props["aria-describedby"] === "teams-minimum-selection")).toBe(true);
  });
  test("N09 failed draft copying reports an error without echoing the draft", async () => {
    const copy = vi.fn().mockRejectedValue(new Error("clipboard unavailable"));
    vi.stubGlobal("navigator", { clipboard: { writeText: copy } });
    const run = () => TeamsWorkflowTestPanel({ auth, operatorApiBaseUrl: "", canManage: true });
    render(run); await settle();
    let tree = render(run);
    input(all(tree).find((node) => node.type === "input" && node.props.inputMode === "url")!, "https://example.com/synthetic-draft");
    tree = render(run);
    const copyButton = all(tree).find((node) => node.type === "button" && node.props["aria-label"] === "Copy saved URL")!;
    click(copyButton); await settle();
    expect(content(render(run))).toContain("The URL was not copied");
    expect(content(render(run))).not.toContain("https://example.com/synthetic-draft");
    expect(copy).toHaveBeenCalledWith("https://example.com/synthetic-draft");
  });
  test("N10 plain-text selection preserves the synthetic subject and sandbox on return", () => {
    const run = () => EmailTemplatePreviewPanel({ template: { key: "incident-opened", subject: "Synthetic subject", plainText: "Synthetic plain text", html: "<p>Example</p>" } });
    let tree = render(run);
    expect(all(tree).find((node) => node.type === "iframe")?.props.sandbox).toBe("");
    click(button(tree, "Plain-text preview"));
    tree = render(run);
    expect(content(tree)).toContain("Synthetic plain text");
    expect(content(tree)).toContain("Synthetic subject");
    expect(all(tree).some((node) => node.type === "iframe")).toBe(false);
    click(button(tree, "HTML preview"));
    expect(all(render(run)).find((node) => node.type === "iframe")?.props.referrerPolicy).toBe("no-referrer");
  });
  test("N11 authoritative A1 state changes update the request button", () => {
    let state: "not-configured" | "plan-requested" = "not-configured";
    const run = () => TeamsA1OnboardingGuide({
      auth, operatorApiBaseUrl: "",
      onboarding: { revision: 1, state, environment: "dev", canManage: true, executionAuthority: false },
    });
    render(run);
    expect(button(render(run), "Prepare Teams connection").props.disabled).toBe(false);
    state = "plan-requested"; render(run);
    expect(button(render(run), "Protected plan requested").props.disabled).toBe(true);
  });
  test("N12 OCR failure stops loading and offers a read-only retry", async () => {
    const client = { modelSettings: vi.fn().mockRejectedValueOnce(new Error("private")).mockResolvedValueOnce({
      documentOcr: { desiredProvider: "local_python", azureResourceState: "absent", effectiveProvider: "local_python", requestState: "idle", canManage: false, koreanEnabled: true },
    }) };
    const run = () => DocumentOcrSettingsPanel({ client: client as unknown as OperatorApiClient, auth });
    render(run); await settle();
    let tree = render(run);
    expect(content(tree)).toContain("OCR status could not be read");
    click(button(tree, "Retry OCR status read"));
    render(run); await settle(); tree = render(run);
    expect(client.modelSettings).toHaveBeenCalledTimes(2);
    expect(client.modelSettings).toHaveBeenNthCalledWith(1, { includeCatalog: false, force: false });
    expect(client.modelSettings).toHaveBeenNthCalledWith(2, { includeCatalog: false, force: true });
    expect(content(tree)).not.toContain("OCR status could not be read");
    expect(testTeamsWorkflowWebhook).not.toHaveBeenCalled();
  });
});

describe("diagnostic recovery controls", () => {
  test("D01 D02 D12 probe retries are independent and policy reads have separate recovery", async () => {
    const metrics = deferred<unknown>();
    const client = {
      panel: vi.fn().mockImplementation((path: string) => path === "/healthz" ? Promise.resolve({ status: "ok" }) : Promise.reject(new Error("policy unavailable"))),
      dashboardMetrics: vi.fn().mockReturnValueOnce(metrics.promise).mockResolvedValue({}),
    };
    const run = () => SettingsDiagnosticsRoute({ client: client as unknown as OperatorApiClient, auth });
    render(run); await settle();
    let tree = render(run);
    expect(content(tree)).toContain("1 available / 0 unavailable / 1 checking");
    expect(button(tree, "Recheck API liveness").props.disabled).toBe(false);
    expect(button(tree, "Recheck KPI read access").props.disabled).toBe(true);
    expect(content(tree)).toContain("Policy facts are unavailable");
    click(button(tree, "Refresh policy facts")); render(run); await settle();
    expect(client.dashboardMetrics).toHaveBeenCalledOnce();
    metrics.resolve({}); await settle(); tree = render(run);
    click(button(tree, "Recheck KPI read access")); render(run); await settle();
    expect(client.panel.mock.calls.filter(([path]) => path === "/healthz")).toHaveLength(1);
    expect(client.dashboardMetrics).toHaveBeenCalledTimes(2);
  });
  test("D04 D08 D09 D10 initial skeletons, safe copy and identity guidance remain separate", async () => {
    const pending = deferred<unknown>();
    const copied = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText: copied } });
    const client = { panel: vi.fn().mockReturnValue(pending.promise), dashboardMetrics: vi.fn().mockReturnValue(pending.promise) };
    const run = () => SettingsDiagnosticsRoute({ client: client as unknown as OperatorApiClient, auth });
    const tree = render(run);
    const regions = all(tree).filter((node) => node.props.class === "settings-diagnostic-result");
    expect(regions).toHaveLength(2);
    expect(regions.every((node) => node.props["aria-busy"])).toBe(true);
    expect(all(tree).filter((node) => typeof node.type === "function" && node.type.name === "LoadingState")).toHaveLength(2);
    expect(all(tree).some((node) => node.props.hint === "This local session uses the development authorization ceiling. Display identity does not grant capabilities; review server-verified access in IAM.")).toBe(true);
    expect(all(tree).filter((node) => node.type === "a").map((node) => node.props.href)).toContain("/settings/iam");
    click(button(tree, "Copy safe diagnostic summary")); await settle();
    const output = JSON.parse(copied.mock.calls[0]![0] as string);
    expect(output.operator_api_liveness).toBeNull();
    expect(output.kpi_read_path).toBeNull();
    expect(content(render(run))).toContain("Diagnostic summary copied");
    pending.resolve({ status: "ok" }); await settle();
  });
});
