import { beforeEach, describe, expect, it, vi } from "vitest";
import type { VNode } from "preact";
import type { OperatorApiClient } from "../api";

const hooks = vi.hoisted(() => ({ slots: [] as unknown[], index: 0 }));
vi.mock("preact/hooks", () => ({
  useState: <T,>(initial: T) => {
    const position = hooks.index++;
    if (!(position in hooks.slots)) hooks.slots[position] = initial;
    return [hooks.slots[position], (next: T) => { hooks.slots[position] = next; }];
  },
  useReducer: (_reducer: unknown, initial: unknown) => [initial, vi.fn()],
  useMemo: (factory: () => unknown) => factory(),
  useEffect: () => undefined,
}));
vi.mock("../deck/context", () => ({ usePublishViewContext: () => undefined }));
vi.mock("../config", () => ({ loadConfig: () => ({ operatorApiBaseUrl: "http://localhost:8010" }) }));
vi.mock("../hooks/use-provision-stream", () => ({
  useProvisionStream: vi.fn(() => ({ status: "closed", lastError: null })),
}));
import { ProvisionView, type ProvisionViewId } from "./provision-view";
import { INITIAL, ProvisionRoute } from "./provision";
import { useProvisionStream } from "../hooks/use-provision-stream";

interface NodeProps {
  readonly children?: unknown;
  readonly role?: string;
  readonly "aria-selected"?: boolean;
  readonly evidenceView?: ProvisionViewId;
  readonly onEvidenceViewChange?: (view: ProvisionViewId) => void;
  readonly onClick?: () => void;
  readonly onKeyDown?: (event: { key: string; preventDefault: () => void }) => void;
}
type Node = VNode<NodeProps>;
function flatten(value: unknown): Node[] {
  if (Array.isArray(value)) return value.flatMap(flatten);
  if (value === null || typeof value !== "object" || !("props" in value)) return [];
  const node = value as Node;
  return [node, ...flatten(node.props.children)];
}
const render = (control: {
  readonly evidenceView?: ProvisionViewId;
  readonly onEvidenceViewChange?: (view: ProvisionViewId) => void;
} = {}) => {
  hooks.index = 0;
  return flatten(ProvisionView({
    consoleUrl: null, dataMode: "live", lastError: null, percent: 0,
    source: { status: "ready", reason: null }, state: { ...INITIAL, runId: "run-example" },
    status: "closed", ...control,
  }));
};
const tabs = (nodes: readonly Node[]) => nodes.filter((node) => node.props.role === "tab");

describe("controlled deployment subview (mocked hooks, no DOM or stream)", () => {
  beforeEach(() => {
    hooks.slots = [];
    hooks.index = 0;
    vi.clearAllMocks();
    vi.stubGlobal("document", { getElementById: vi.fn(() => ({ focus: vi.fn() })) });
    vi.stubGlobal("requestAnimationFrame", (callback: (time: number) => void) => { callback(0); return 1; });
  });
  it("keeps the compatibility default and local state without control props", () => {
    expect(tabs(render())[0]!.props["aria-selected"]).toBe(true);
    tabs(render())[2]!.props.onClick?.();
    expect(tabs(render())[2]!.props["aria-selected"]).toBe(true);
  });
  it("notifies the parent without replacing its controlled selection", () => {
    const onEvidenceViewChange = vi.fn();
    const control = { evidenceView: "resources" as const, onEvidenceViewChange };
    expect(tabs(render(control))[2]!.props["aria-selected"]).toBe(true);
    tabs(render(control))[1]!.props.onClick?.();
    expect(onEvidenceViewChange).toHaveBeenCalledWith("readiness");
    expect(tabs(render(control))[2]!.props["aria-selected"]).toBe(true);
    expect(tabs(render({ evidenceView: "readiness", onEvidenceViewChange }))[1]!.props["aria-selected"]).toBe(true);
  });
  it("routes keyboard changes through the same controlled callback", () => {
    const onEvidenceViewChange = vi.fn();
    const tablist = render({ evidenceView: "resources", onEvidenceViewChange })
      .find((node) => node.props.role === "tablist")!;
    const preventDefault = vi.fn();
    tablist.props.onKeyDown?.({ key: "Home", preventDefault });
    expect(onEvidenceViewChange).toHaveBeenCalledWith("stages");
    expect(preventDefault).toHaveBeenCalledOnce();
    expect(document.getElementById).toHaveBeenCalledWith("provision-tab-stages");
  });
  it("threads control props through the route/session without enabling an unready stream", () => {
    const onEvidenceViewChange = vi.fn();
    const session = ProvisionRoute({
      client: {} as OperatorApiClient, dataMode: "live", embedded: true,
      evidenceView: "resources", onEvidenceViewChange,
    });
    expect(session.props).toMatchObject({ evidenceView: "resources", onEvidenceViewChange });
    const Session = session.type as (props: typeof session.props) => Node;
    const view = Session(session.props);
    expect(view.type).toBe(ProvisionView);
    expect(view.props).toMatchObject({ evidenceView: "resources", onEvidenceViewChange });
    expect(useProvisionStream).toHaveBeenCalledWith(expect.objectContaining({ enabled: false }));
  });
});
