import { beforeEach, describe, expect, it, vi } from "vitest";
import type { VNode } from "preact";
import type { OperatorApiClient } from "../api";
import type { AuthContext } from "../auth";

const harness = vi.hoisted(() => {
  let slots: unknown[] = [];
  let index = 0;
  const effects: Array<() => unknown> = [];
  return {
    reset() { slots = []; index = 0; effects.length = 0; },
    render() { index = 0; },
    effects,
    useState<T>(initial: T | (() => T)): [T, (next: T | ((current: T) => T)) => void] {
      const position = index++;
      if (!(position in slots)) slots[position] = typeof initial === "function" ? (initial as () => T)() : initial;
      return [slots[position] as T, (next) => {
        slots[position] = typeof next === "function" ? (next as (current: T) => T)(slots[position] as T) : next;
      }];
    },
    useRef<T>(initial: T): { current: T } {
      const position = index++;
      if (!(position in slots)) slots[position] = { current: initial };
      return slots[position] as { current: T };
    },
    useEffect(effect: () => unknown, dependencies: unknown[]) {
      const position = index++;
      const previous = slots[position] as unknown[] | undefined;
      if (!previous || dependencies.some((value, i) => value !== previous[i])) effects.push(effect);
      slots[position] = dependencies;
    },
    CommandError: class extends Error {
      constructor(readonly status: number) { super(`HTTP ${status}`); }
    },
  };
});

vi.mock("preact/hooks", () => ({
  useState: harness.useState, useRef: harness.useRef, useEffect: harness.useEffect,
}));
vi.mock("../deck/context", () => ({ usePublishViewContext: () => undefined }));
vi.mock("../components/settings-dirty-state", () => ({ useSettingsDirtyState: () => undefined }));
vi.mock("../i18n", () => ({ getLocale: () => "en", t: (key: string) => key }));
vi.mock("./settings-runtime.command", () => ({
  RuntimeSettingsCommandError: harness.CommandError, saveRuntimeSettings: vi.fn(),
}));
import { saveRuntimeSettings } from "./settings-runtime.command";
import { SettingsRuntimeRoute } from "./settings-runtime";
import { decodeRuntimeSettings } from "./settings-runtime.model";

const payload = (revision = 1, effective = 30) => ({
  revision, can_manage: true, updated_at: null, updated_by: null, integrations: [],
  runtime: {
    environment: "dev", state_store_durable: true, autonomy_default: "shadow", pantheon_enabled: true,
    workflow_observation_enabled: true, primary_transport_configured: true,
    auxiliary_transport_configured: false, case_history_configured: false,
  },
  settings: [{
    key: "analyzer.budget_seconds", group: "investigation", value_type: "integer",
    environment_value: 30, effective_value: effective, override_value: effective === 30 ? null : effective,
    minimum: 10, maximum: 300, options: [], restart_required: false, available: true, unavailable_reason: null,
  }],
});

interface NodeProps {
  readonly children?: unknown;
  readonly setting?: { readonly key: string };
  readonly value?: unknown;
  readonly disabled?: boolean;
  readonly onChange?: (value: string) => void;
  readonly onClick?: () => unknown;
  readonly onRetry?: () => unknown;
}
type TestNode = VNode<NodeProps>;
function nodes(value: unknown): TestNode[] {
  if (Array.isArray(value)) return value.flatMap(nodes);
  if (value === null || typeof value !== "object" || !("props" in value)) return [];
  const node = value as TestNode;
  return [node, ...nodes(node.props.children)];
}

describe("runtime settings action recovery (mocked hooks, no DOM)", () => {
  let client: OperatorApiClient;
  let tree: TestNode;
  const render = () => {
    harness.render();
    tree = SettingsRuntimeRoute({ client, auth: {} as AuthContext }) as TestNode;
    return tree;
  };
  const find = (predicate: (node: TestNode) => boolean): TestNode => {
    const node = nodes(tree).find(predicate);
    if (!node) throw new Error("Expected test node not found");
    return node;
  };
  const row = () => find((node) => node.props.setting?.key === "analyzer.budget_seconds");
  const button = (text: string) => find((node) => node.type === "button" && node.props.children === text);
  const saveButton = () => button("settings.runtimePolicies.save");
  const flush = async () => {
    for (let i = 0; i < 6; i += 1) await Promise.resolve();
    render();
  };

  beforeEach(async () => {
    harness.reset();
    vi.clearAllMocks();
    client = { panel: vi.fn().mockResolvedValue(payload()), operatorApiBaseUrl: "http://localhost:8010" } as unknown as OperatorApiClient;
    render();
    for (const effect of harness.effects.splice(0)) effect();
    await flush();
  });

  it("retains invalid raw input and blocks the complete save batch", async () => {
    row().props.onChange?.("");
    render();
    expect(row().props.value).toBe("");
    expect(saveButton().props.disabled).toBe(true);
    await saveButton().props.onClick?.();
    expect(saveRuntimeSettings).not.toHaveBeenCalled();
    row().props.onChange?.("60");
    render();
    vi.mocked(saveRuntimeSettings).mockResolvedValue(decodeRuntimeSettings(payload(2, 60)));
    await saveButton().props.onClick?.();
    await flush();
    expect(saveRuntimeSettings).toHaveBeenCalledWith(expect.anything(), "http://localhost:8010",
      { "analyzer.budget_seconds": 60 }, 1);
  });

  it("preserves a failed-save draft and retries the save, not a destructive reload", async () => {
    row().props.onChange?.("90");
    render();
    vi.mocked(saveRuntimeSettings).mockRejectedValueOnce(new harness.CommandError(503));
    saveButton().props.onClick?.();
    await flush();
    expect(row().props.value).toBe("90");
    const error = find((node) => node.props.onRetry !== undefined);
    vi.mocked(saveRuntimeSettings).mockResolvedValue(decodeRuntimeSettings(payload(2, 90)));
    error.props.onRetry?.();
    await flush();
    expect(saveRuntimeSettings).toHaveBeenCalledTimes(2);
    expect(client.panel).toHaveBeenCalledOnce();
    expect(vi.mocked(saveRuntimeSettings).mock.calls[1]?.[2]).toEqual({ "analyzer.budget_seconds": 90 });
  });

  it("keeps conflicting proposed values until explicit review and a separate save", async () => {
    row().props.onChange?.("90");
    render();
    vi.mocked(saveRuntimeSettings).mockRejectedValueOnce(new harness.CommandError(409));
    vi.mocked(client.panel).mockResolvedValue(payload(2, 60));
    saveButton().props.onClick?.();
    await flush();
    expect(row().props.value).toBe("90");
    expect(saveButton().props.disabled).toBe(true);
    expect(saveRuntimeSettings).toHaveBeenCalledOnce();
    button("Use latest revision and keep this draft").props.onClick?.();
    render();
    expect(row().props.value).toBe("90");
    expect(saveRuntimeSettings).toHaveBeenCalledOnce();
    vi.mocked(saveRuntimeSettings).mockResolvedValue(decodeRuntimeSettings(payload(3, 90)));
    saveButton().props.onClick?.();
    await flush();
    expect(vi.mocked(saveRuntimeSettings).mock.calls[1]?.[3]).toBe(2);
  });

  it("discards a draft without resetting a persisted override or sending a command", () => {
    row().props.onChange?.("120");
    render();
    button("Discard changes").props.onClick?.();
    render();
    expect(row().props.value).toBe(30);
    expect(saveButton().props.disabled).toBe(true);
    expect(saveRuntimeSettings).not.toHaveBeenCalled();
  });
});
