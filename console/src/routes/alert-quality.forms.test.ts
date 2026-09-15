import { isValidElement, toChildArray, type ComponentChildren, type VNode } from "preact";
import { afterEach, describe, expect, it, vi } from "vitest";
import { getLocale, setLocale } from "../i18n";
import { AlertQualityScopePicker } from "./alert-quality";
import { alertQualityReadPresentation } from "./alert-quality.controller";
import { AlertQualityProposalEditor } from "./alert-quality.forms";
import { decodeAlertQuality } from "./alert-quality.model";
import { AlertQualityRequestControls } from "./alert-quality.presentation";
import { initialAlertProposal, type AlertProposalDraft } from "./alert-quality.proposal";
import { decodeAlertQualityScopes } from "./alert-quality.scopes";
import { alertQualityText as text } from "./i18n/alert-quality";

// Pure component-tree assertions, not executed browser, keyboard, geometry or provider evidence.
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

const scope = "scope:example_team.alpha-1";
const digest = `sha256:${"a".repeat(64)}`;
const now = Date.parse("2026-09-14T10:30:00Z");
const report = {
  schema_version: "1.0.0", source: "alert-noise-evidence", evidence_digest: digest, policy_digest: digest,
  tenant_ref: "tenant:example", scope_ref: scope, observed_at: "2026-09-14T10:00:00Z", valid_until: "2026-09-14T11:00:00Z",
  coverage: "complete", reasons: [], source_episodes: null, notification_attempts: null, confirmed_deliveries: 0,
  acknowledgements: null, execution_authority: false,
  findings: ["rule:routing", "rule:evaluation"].map((rule_ref, index) => ({
    rule_ref, service_ref: "service:example", reason: index === 0 ? "overlap" : "flapping",
    guidance: index === 0 ? "review-routing" : "review-evaluation", protected: false, source_episodes: null,
    observed_deliveries: null, potential_recipients_lower: null, potential_recipients_upper: null, duplicate_paths: 0,
  })),
};
const data = decodeAlertQuality({ source: "alert-noise-governance", available: true, enabled: true,
  authority: "shadow", unavailable_reason: null, assessment: report, plans: [] }, scope);
const routing: AlertProposalDraft = { kind: "routing", target_ref: "rule:routing", remove_group_ref: "group:source", replacement_group_ref: "group:replacement" };
const suppression: Extract<AlertProposalDraft, { kind: "suppression" }> = {
  kind: "suppression", target_ref: "rule:routing", processing_rule_ref: "processing:example", preprovisioned: true,
  starts_at: "2026-09-14T11:00:00Z", ends_at: "2026-09-14T12:00:00Z",
};
const evaluation: Extract<AlertProposalDraft, { kind: "evaluation" }> = {
  kind: "evaluation", target_ref: "rule:evaluation", parameter: "threshold", proposed_value: "1e-9",
  baseline: { metric_ref: "metric:example", operator: "above", threshold: "0", window_seconds: "300", frequency_seconds: "60", aggregation: "maximum" },
};
const locale = getLocale();
afterEach(() => setLocale(locale));

function editor(draft: AlertProposalDraft, held = false) {
  const onDraft = vi.fn<(draft: AlertProposalDraft) => void>();
  const onSubmit = vi.fn<(draft: AlertProposalDraft) => void>();
  const view = inspect(AlertQualityProposalEditor({ data, scope, now, held, draft, onDraft, onSubmit }));
  const field = (name: string) => view.elements.find((item) => item.props.name === name)!;
  const submit = () => (view.elements.find((item) => item.type === "form")!.props.onSubmit as (event: unknown) => void)({ preventDefault: vi.fn() });
  return { ...view, field, submit, onDraft, onSubmit };
}

describe("single-axis native form presentation", () => {
  it("offers all three treatments and clears foreign-axis state when selection changes", () => {
    const view = editor(routing);
    const selector = view.field("treatment_kind");
    const choices = toChildArray(selector.props.children as ComponentChildren).filter(isValidElement);
    expect(choices.map((node) => (node as ElementNode).props.value)).toEqual(["routing", "suppression", "evaluation"]);
    (selector.props.onChange as (event: unknown) => void)({ currentTarget: { value: "suppression" } });
    expect(view.onDraft).toHaveBeenCalledExactlyOnceWith(initialAlertProposal("suppression"));
    expect(view.onDraft.mock.calls[0]?.[0]).not.toHaveProperty("remove_group_ref");
    expect(view.onDraft.mock.calls[0]?.[0]).not.toHaveProperty("baseline");
  });

  it("submits only a valid deliberate draft and provides no approve or execute button", () => {
    for (const draft of [routing, suppression, evaluation]) {
      const view = editor(draft);
      const buttons = view.elements.filter((item) => item.type === "button");
      expect(buttons).toHaveLength(1);
      expect(buttons[0]?.props).toMatchObject({ type: "submit", disabled: false });
      view.submit();
      expect(view.onSubmit).toHaveBeenCalledExactlyOnceWith(draft);
      const held = editor(draft, true);
      held.submit();
      expect(held.onSubmit).not.toHaveBeenCalled();
      expect(held.elements.some((item) => item.type === "fieldset" && item.props.disabled === true)).toBe(true);
    }
    const incomplete = editor(initialAlertProposal());
    incomplete.submit();
    expect(incomplete.onSubmit).not.toHaveBeenCalled();
  });

  it("shows only the selected axis and requires the pre-provisioned rule acknowledgement", () => {
    const view = editor({ ...suppression, preprovisioned: false });
    expect(view.field("starts_at").props.type).toBe("text");
    expect(view.field("ends_at").props.type).toBe("text");
    expect(view.field("preprovisioned").props).toMatchObject({ type: "checkbox", checked: false, required: true });
    expect(view.field("remove_group_ref")).toBeUndefined();
    expect(view.field("baseline.metric_ref")).toBeUndefined();
    view.submit();
    expect(view.onSubmit).not.toHaveBeenCalled();
    expect(view.content).toContain(text("suppressionPrerequisite"));
    expect(view.content).toContain(text("propagationHelp"));
    expect(view.content).toContain(text("suppressionHelp"));
  });

  it("keeps baseline context explicit and clears a proposed value when the parameter changes", () => {
    const view = editor(evaluation);
    expect(view.content).toContain(text("baselineHelp"));
    expect(view.content).toContain(text("draftPreviewHelp"));
    expect(view.content).toContain(text("draftBefore"));
    expect(view.field("processing_rule_ref")).toBeUndefined();
    const selector = view.field("parameter");
    (selector.props.onChange as (event: unknown) => void)({ currentTarget: { value: "window_seconds" } });
    expect(view.onDraft).toHaveBeenCalledExactlyOnceWith({ ...evaluation, parameter: "window_seconds", proposed_value: "" });
  });

  it("connects invalid numeric input to bilingual correction text without erasing it", () => {
    for (const locale of ["en", "ko"] as const) {
      setLocale(locale);
      const view = editor({ ...evaluation, proposed_value: "0x10" });
      const input = view.field("proposed_value");
      expect(input.props.value).toBe("0x10");
      expect(input.props["aria-invalid"]).toBe(true);
      expect(view.elements.some((item) => item.props.id === input.props["aria-describedby"])).toBe(true);
      expect(view.content).toContain(text("validation.number"));
      view.submit();
      expect(view.onSubmit).not.toHaveBeenCalled();
    }
  });

  it("authors 44px native controls, labels and bounded layout rather than custom decorative CSS", () => {
    for (const draft of [routing, suppression, evaluation]) {
      const view = editor(draft);
      const controls = view.elements.filter((item) => item.type === "button" || item.type === "select"
        || (item.type === "input" && item.props.type !== "checkbox"));
      expect(controls.every((item) => (item.props.style as { minHeight?: number }).minHeight === 44)).toBe(true);
      expect(view.elements.filter((item) => item.type === "input" && item.props.type !== "checkbox")
        .every((item) => view.elements.some((label) => label.type === "label" && label.props.htmlFor === item.props.id))).toBe(true);
      expect(view.elements.some((item) => item.type === "style")).toBe(false);
    }
  });
});

describe("authorized picker and producer/read separation", () => {
  it("re-localizes retained errors without a request or raw dependency message", () => {
    for (const locale of ["en", "ko"] as const) {
      setLocale(locale);
      expect(alertQualityReadPresentation({ status: "error", message: "private dependency text" }, "scopes"))
        .toEqual({ status: "error", message: text("scopesFailed") });
      expect(alertQualityReadPresentation({ status: "unavailable", message: "private dependency text" }, "report"))
        .toEqual({ status: "unavailable", message: text("loadUnavailable") });
    }
  });

  it("offers exact server choices, ignores injected references and leaves an empty list unavailable", () => {
    const scopes = decodeAlertQualityScopes({ source: "alert-noise-governance", scope_refs: [scope], execution_authority: false });
    const onSelect = vi.fn();
    const view = inspect(AlertQualityScopePicker({ scopes, selected: null, onSelect }));
    expect(view.elements.some((item) => item.type === "input")).toBe(false);
    const select = view.elements.find((item) => item.type === "select")!;
    const change = select.props.onChange as (event: unknown) => void;
    change({ currentTarget: { value: "scope:unauthorized" } });
    expect(onSelect).not.toHaveBeenCalled();
    change({ currentTarget: { value: scope } });
    expect(onSelect).toHaveBeenCalledExactlyOnceWith(scope);
    const empty = inspect(AlertQualityScopePicker({ scopes: { ...scopes, scope_refs: [] }, selected: null, onSelect }));
    expect(empty.elements.find((item) => item.type === "select")?.props.disabled).toBe(true);
  });

  it("keeps assessment enabled when ready even with no report or an expired report", () => {
    for (const assessment of [null, { ...data.assessment!, valid_until: "2026-09-14T10:01:00Z" }]) {
      const onAssess = vi.fn();
      const view = inspect(AlertQualityRequestControls({ state: { status: "ready", data: { ...data,
        assessment, unavailable_reason: "assessment_expired" } }, command: "idle", onAssess, onRefresh: vi.fn(), onStop: vi.fn(),
        periodSeconds: 86400, onPeriodChange: vi.fn() }));
      const button = view.elements.find((item) => item.props["aria-describedby"] === "alert-quality-assess-help")!;
      expect(button.props.disabled).toBe(false);
      (button.props.onClick as () => void)();
      expect(onAssess).toHaveBeenCalledExactlyOnceWith(86400);
    }
  });

  it("retains uncertainty and the optional server veto independently of retained data", () => {
    for (const [command, requestable] of [["unknown", true], ["idle", false]] as const) {
      const onAssess = vi.fn();
      const view = inspect(AlertQualityRequestControls({ state: { status: "ready", data: { ...data, requestable } },
        command, onAssess, onRefresh: vi.fn(), onStop: vi.fn(), periodSeconds: 86400, onPeriodChange: vi.fn() }));
      const button = view.elements.find((item) => item.props["aria-describedby"] === "alert-quality-assess-help")!;
      expect(button.props.disabled).toBe(true);
      (button.props.onClick as () => void)();
      expect(onAssess).not.toHaveBeenCalled();
    }
  });

  it("keeps manual requests disabled for a settings veto even when the report is still enabled", () => {
    const onAssess = vi.fn();
    const view = inspect(AlertQualityRequestControls({ state: { status: "ready", data: { ...data, requestable: true } },
      command: "idle", preferenceHeld: true, onAssess, onRefresh: vi.fn(), onStop: vi.fn(),
      periodSeconds: 86400, onPeriodChange: vi.fn() }));
    const button = view.elements.find((item) => item.props["aria-describedby"] === "alert-quality-assess-help")!;
    expect(button.props.disabled).toBe(true);
    (button.props.onClick as () => void)();
    expect(onAssess).not.toHaveBeenCalled();
    expect(view.content).toContain(text("settings.requestHold"));
  });
});
