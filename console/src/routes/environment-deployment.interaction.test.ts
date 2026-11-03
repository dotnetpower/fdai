import { beforeEach, describe, expect, it, vi } from "vitest";
import type { VNode } from "preact";
import type { OperatorApiClient } from "../api";

const state = vi.hoisted(() => ({
  segment: undefined as string | undefined, search: new URLSearchParams(), transient: false,
  slots: [] as unknown[], index: 0,
}));
vi.mock("preact/hooks", () => ({
  useEffect: () => undefined,
  useState: <T,>(initial: T) => {
    const position = state.index++;
    if (!(position in state.slots)) state.slots[position] = initial;
    return [state.slots[position], (next: T | ((current: T) => T)) => {
      state.slots[position] = typeof next === "function" ? (next as (current: T) => T)(state.slots[position] as T) : next;
    }];
  },
}));
vi.mock("../router", async (original) => {
  const location = (href: string) => {
    const url = new URL(href, "http://localhost");
    state.segment = url.pathname.split("/")[3];
    state.search = url.searchParams;
  };
  return {
    ...await original<object>(),
    currentRoute: () => ({ segments: state.segment === undefined ? [] : [state.segment], search: state.search }),
    navigate: vi.fn((href: string) => { location(href); state.slots = []; }),
    replaceRouteState: vi.fn(location),
    hasTransientRoute: () => state.transient,
  };
});
import { navigate, replaceRouteState } from "../router";
import { EnvironmentDeploymentRoute } from "./environment-deployment";
import { ProvisionRoute } from "./provision";
import type { ProvisionViewId } from "./provision-view";
interface Props {
  readonly children?: unknown;
  readonly role?: string;
  readonly href?: string;
  readonly id?: string;
  readonly onKeyDown?: (event: { key: string; preventDefault: () => void }) => void;
  readonly onClick?: () => void;
  readonly evidenceView?: ProvisionViewId;
  readonly onEvidenceViewChange?: (view: ProvisionViewId) => void;
  readonly "aria-describedby"?: string;
}
type Node = VNode<Props>;
function flatten(value: unknown): Node[] {
  if (Array.isArray(value)) return value.flatMap(flatten);
  if (value === null || typeof value !== "object" || !("props" in value)) return [];
  const node = value as Node;
  return [node, ...flatten(node.props.children)];
}
const render = (sample = false) => {
  state.index = 0;
  return flatten(EnvironmentDeploymentRoute({ client: {} as OperatorApiClient, dataMode: sample ? "sample" : "live" }));
};

describe("environment wrapper events without DOM rendering", () => {
  beforeEach(() => {
    state.segment = undefined;
    state.search = new URLSearchParams();
    state.transient = false;
    state.slots = [];
    vi.clearAllMocks();
    vi.stubGlobal("document", { getElementById: vi.fn(() => ({ focus: vi.fn() })) });
  });
  it("moves keyboard focus without navigating or activating a network-backed tab", () => {
    const tablist = render().find((node) => node.props.role === "tablist")!;
    const preventDefault = vi.fn();
    tablist.props.onKeyDown?.({ key: "ArrowRight", preventDefault });
    expect(preventDefault).toHaveBeenCalledOnce();
    expect(document.getElementById).toHaveBeenCalledWith("environment-deployment-tab-deployment");
    expect(navigate).not.toHaveBeenCalled();
    const deployment = render().filter((node) => node.props.role === "tab")[1]!;
    deployment.props.onClick?.();
    expect(navigate).toHaveBeenCalledWith("/settings/environment-and-deployment/deployment");
  });
  it("offers a canonical recovery link without treating an invalid tab as ready", () => {
    state.segment = "invalid";
    const links = render(true).filter((node) => node.type === "a");
    expect(links.some((node) => node.props.href === "/settings/environment-and-deployment?data=sample")).toBe(true);
  });
  it("restores the deployment subview after URL-keyed wrapper remounts without keeping hidden content", () => {
    state.segment = "deployment";
    state.search = new URLSearchParams("locale=ko");
    let deployment = render().find((node) => node.type === ProvisionRoute)!;
    expect(deployment.props.evidenceView).toBe("stages");
    deployment.props.onEvidenceViewChange?.("resources");
    expect(replaceRouteState).toHaveBeenCalledWith("/settings/environment-and-deployment/deployment?locale=ko&deployment-view=resources");
    for (const segment of ["readiness", "observers"]) {
      render().find((node) => node.props.id === `environment-deployment-tab-${segment}`)!.props.onClick?.();
      expect(state.slots).toEqual([]);
      expect(render().some((node) => node.type === ProvisionRoute)).toBe(false);
      expect(state.search.get("deployment-view")).toBe("resources");
      expect(state.search.get("locale")).toBe("ko");
    }
    render().find((node) => node.props.id === "environment-deployment-tab-deployment")!.props.onClick?.();
    deployment = render().find((node) => node.type === ProvisionRoute)!;
    expect(deployment.props.evidenceView).toBe("resources");
  });
  it("updates a transient Settings route without rewriting its background workspace URL", () => {
    state.segment = "deployment";
    state.search = new URLSearchParams("locale=en");
    state.transient = true;
    render().find((node) => node.type === ProvisionRoute)!.props.onEvidenceViewChange?.("resources");
    expect(navigate).toHaveBeenCalledWith("/settings/environment-and-deployment/deployment?locale=en&deployment-view=resources", true);
    expect(replaceRouteState).not.toHaveBeenCalled();
    expect(render().find((node) => node.type === ProvisionRoute)!.props.evidenceView).toBe("resources");
  });
  it("retains the selected evidence subview through an explicit read-only source reload", () => {
    state.segment = "deployment";
    let contents = render();
    contents.find((node) => node.type === ProvisionRoute)!.props.onEvidenceViewChange?.("readiness");
    contents = render();
    const previousKey = contents.find((node) => node.type === ProvisionRoute)!.key;
    contents.find((node) => node.props["aria-describedby"] === "deployment-reload-hint")!.props.onClick?.();
    const deployment = render().find((node) => node.type === ProvisionRoute)!;
    expect(deployment.key).not.toBe(previousKey);
    expect(deployment.props.evidenceView).toBe("readiness");
  });
});
