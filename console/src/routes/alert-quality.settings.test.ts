import { isValidElement, toChildArray, type ComponentChildren, type VNode } from "preact";
import { afterEach, describe, expect, it, vi } from "vitest";
import { getLocale, setLocale } from "../i18n";
import { AlertQualitySettingsEditor } from "./alert-quality.settings";
import { decodeAlertQualitySettings } from "./alert-quality.settings.model";
import type { AlertQualitySettingsState } from "./alert-quality.settings.requests";
import fixture from "./alert-quality.settings.fixture.json";
import { alertQualityText as text } from "./i18n/alert-quality";

// Component-tree contracts only, not a browser, keyboard, layout or visual pass.
type ElementNode = VNode<Record<string, unknown>>;
function inspect(tree: ComponentChildren) {
  const elements: ElementNode[] = [];
  const parts: string[] = [];
  const visit = (child: ComponentChildren): void => {
    for (const node of toChildArray(child)) {
      if (typeof node === "string" || typeof node === "number" || typeof node === "bigint") parts.push(String(node));
      else if (isValidElement(node)) {
        const element = node as ElementNode;
        if (typeof element.type === "function") visit((element.type as (props: Record<string, unknown>) => ComponentChildren)(element.props));
        else { elements.push(element); visit(element.props.children as ComponentChildren); }
      }
    }
  };
  visit(tree);
  return { elements, content: parts.join(" ").replace(/\s+/g, " ").trim() };
}

const settings = decodeAlertQualitySettings(fixture, fixture.scope_ref);
const ready: AlertQualitySettingsState = { read: { status: "ready", data: settings }, authority: "owner", command: "idle", editable: true };
const originalLocale = getLocale();
afterEach(() => setLocale(originalLocale));

function editor(state: AlertQualitySettingsState = ready, value: boolean | null = false) {
  const context = { current: true };
  const onSave = vi.fn<(enabled: boolean, revision: number) => void>();
  const onValue = vi.fn<(enabled: boolean) => void>();
  const onRefresh = vi.fn();
  const view = inspect(AlertQualitySettingsEditor({ state, value, onSave, onValue, onRefresh, isCurrent: () => context.current }));
  const select = view.elements.find((item) => item.type === "select")!;
  const save = view.elements.find((item) => item.type === "button" && item.props.type === "submit")!;
  const submit = () => (view.elements.find((item) => item.type === "form")!.props.onSubmit as (event: unknown) => void)({ preventDefault: vi.fn() });
  return { ...view, select, save, submit, context, onSave, onValue, onRefresh };
}

describe("Owner preference controls and honest settings state", () => {
  it("offers a deliberate boolean preference change at the exact read revision in both locales", () => {
    for (const locale of ["en", "ko"] as const) {
      setLocale(locale);
      const view = editor();
      expect(view.select.props).toMatchObject({ name: "enabled", value: "false", disabled: false, required: true });
      expect(view.save.props.disabled).toBe(false);
      view.submit();
      expect(view.onSave).toHaveBeenCalledExactlyOnceWith(false, 0);
      const change = view.select.props.onChange as (event: unknown) => void;
      change({ currentTarget: { value: "false" } });
      change({ currentTarget: { value: "enforce" } });
      expect(view.onValue).toHaveBeenCalledExactlyOnceWith(false);
      expect(view.content).toContain(text("settings.help"));
      expect(view.content).toContain(text("settings.authority.owner"));
      expect(view.content).toContain(text("settings.unsaved"));
      expect(view.elements.filter((item) => item.type === "time")).toHaveLength(0);
    }
  });

  it("keeps availability, saved preference and authority separate instead of displaying the unsaved draft", () => {
    const unavailableProducer = decodeAlertQualitySettings({ ...fixture, available: false, unavailable_reason: "producer_not_ready",
      prerequisites: { ...fixture.prerequisites, producer_ready: false } }, fixture.scope_ref);
    const view = editor({ ...ready, read: { status: "ready", data: unavailableProducer } }, false);
    expect(view.content).toContain(text("enabled")); // Stored default is still true; draft is false.
    expect(view.content).toContain(text("unavailable"));
    expect(view.content).toContain(text("shadow"));
    expect(view.content).toContain(text("settings.reason.producer"));
    expect(view.content).not.toContain("producer_not_ready");
    expect(view.save.props.disabled).toBe(false); // Preference storage is independent of producer readiness.
  });

  it.each(["read-only", "unavailable", "denied", "loading"] as const)("does not enable edits for %s even with an inconsistent editable hint", (authority) => {
    const view = editor({ ...ready, authority });
    expect(view.select.props.disabled).toBe(true);
    expect(view.save.props.disabled).toBe(true);
    view.submit();
    expect(view.onSave).not.toHaveBeenCalled();
    (view.select.props.onChange as (event: unknown) => void)({ currentTarget: { value: "false" } });
    expect(view.onValue).not.toHaveBeenCalled();
  });

  it.each(["pending", "conflict", "denied", "rejected", "unknown"] as const)("keeps a %s update disabled and exposes localized recovery guidance", (command) => {
    const view = editor({ ...ready, command });
    expect(view.save.props.disabled).toBe(true);
    view.submit();
    expect(view.onSave).not.toHaveBeenCalled();
    expect(view.content).toContain(text(`settings.command.${command}`));
    if (command === "pending") {
      expect(view.elements.some((item) => item.props.role === "status" && item.props["aria-busy"] === "true")).toBe(true);
    }
  });

  it("rechecks the current auth/scope binding in captured form and selection handlers", () => {
    const view = editor();
    view.context.current = false;
    view.submit();
    (view.select.props.onChange as (event: unknown) => void)({ currentTarget: { value: "false" } });
    const refresh = view.elements.find((item) => item.type === "button" && item.props.type === "button")!;
    (refresh.props.onClick as () => void)();
    expect(view.onSave).not.toHaveBeenCalled();
    expect(view.onValue).not.toHaveBeenCalled();
    expect(view.onRefresh).not.toHaveBeenCalled();
  });

  it("does not invent an initial preference or recorded time for missing storage", () => {
    const absent = decodeAlertQualitySettings({ ...fixture, available: false, enabled: null, revision: null,
      preference_state: "unavailable", unavailable_reason: "preference_store_unavailable",
      prerequisites: { ...fixture.prerequisites, preference_store_available: false } }, fixture.scope_ref);
    const view = editor({ ...ready, read: { status: "ready", data: absent }, editable: false }, null);
    expect(view.select.props.value).toBe("");
    expect(view.select.props.disabled).toBe(true);
    expect(view.save.props.disabled).toBe(true);
    expect(view.content).toContain(text("settings.reason.store"));
    expect(view.content).toContain(text("unknown"));
    expect(view.elements.some((item) => item.type === "time")).toBe(false);
    expect(editor(ready, true).save.props.disabled).toBe(true); // No change means no new revision.
  });

  it("keeps errors content-free and loading accessible while using existing native controls", () => {
    const loading = editor({ read: { status: "loading" }, authority: "loading", command: "idle", editable: false }, null);
    expect(loading.elements.some((item) => item.props.role === "status" && item.props["aria-busy"] === "true")).toBe(true);
    expect(loading.save.props.disabled).toBe(true);
    for (const status of ["error", "unavailable"] as const) {
      const view = editor({ ...ready, read: { status, message: "private dependency detail" }, editable: false }, null);
      expect(view.content).not.toContain("private dependency detail");
      expect(view.content).toContain(text(status === "error" ? "settings.loadFailed" : "settings.loadUnavailable"));
    }
    const view = editor();
    for (const element of view.elements.filter((item) => item.type === "button" || item.type === "select")) {
      expect(element.props.style).toMatchObject({ minHeight: 44 });
    }
    expect(view.elements.some((item) => item.type === "label" && item.props.htmlFor === view.select.props.id)).toBe(true);
    expect(view.elements.some((item) => item.type === "style")).toBe(false);
  });
});
