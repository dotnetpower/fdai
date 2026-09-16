import { isValidElement, toChildArray, type ComponentChildren, type VNode } from "preact";
import { afterEach, describe, expect, it, vi } from "vitest";
import { supportsSampleData } from "../console-data-mode";
import { getLocale, setLocale } from "../i18n";
import { panelSourceClassification } from "../panel-sources";
import { panelForId, panelsInGroup } from "../panels";
import { parseConsoleRoute, routeHref } from "../router";
import {
  AlertQualityEvidence, AlertQualityFindingTable, AlertQualityPlans, AlertQualityProvenance,
  CommandFeedback, alertQualityCount, alertQualityReason,
} from "./alert-quality";
import { decodeAlertQuality } from "./alert-quality.model";
import backendFixture from "./alert-quality.backend.fixture.json";
import { alertQualityText } from "./i18n/alert-quality";
import en from "./i18n/alert-quality.en.json";
import ko from "./i18n/alert-quality.ko.json";

// Pure component-tree inspection, not a browser, visual or keyboard-runtime pass.
type ElementNode = VNode<Record<string, unknown>>;
function inspect(tree: ComponentChildren) {
  const elements: ElementNode[] = [];
  const parts: string[] = [];
  const visit = (child: ComponentChildren): void => {
    for (const node of toChildArray(child)) {
      if (typeof node === "string" || typeof node === "number" || typeof node === "bigint") {
        parts.push(String(node));
      } else if (isValidElement(node)) {
        const element = node as ElementNode;
        if (typeof element.type === "function") {
          // These view exports contain only function components without hooks.
          visit((element.type as (props: Record<string, unknown>) => ComponentChildren)(element.props));
        } else {
          elements.push(element);
          visit(element.props.children as ComponentChildren);
        }
      }
    }
  };
  visit(tree);
  return { elements, content: parts.join(" ").replace(/\s+/g, " ").trim() };
}

const digest = `sha256:${"a".repeat(64)}`;
const scope = "scope:example_team-1";
const now = Date.parse("2026-09-14T10:30:00Z");
const finding = {
  rule_ref: "rule:example_rule-1", service_ref: "service:example", reason: "overlap", guidance: "review-routing",
  source_episodes: 0, observed_deliveries: null, potential_recipients_lower: null, potential_recipients_upper: 10,
  duplicate_paths: 0, protected: false,
};
const report = {
  schema_version: "1.0.0", source: "alert-noise-evidence", evidence_digest: digest, policy_digest: digest,
  tenant_ref: "tenant:example", scope_ref: scope, observed_at: "2026-09-14T10:00:00Z", valid_until: "2026-09-14T11:00:00Z",
  coverage: "complete", reasons: [], source_episodes: 0, notification_attempts: null, confirmed_deliveries: 0,
  acknowledgements: null, findings: [finding], execution_authority: false,
};
const plan = {
  schema_version: "1.0.0", action_type: "ops.update-alert-routing", tenant_ref: "tenant:example", scope_ref: scope,
  requester_ref: "principal:example", evidence_digest: digest, policy_digest: digest, target_revision: digest,
  treatment: { kind: "routing", target_ref: finding.rule_ref, remove_group_ref: "group:source", replacement_group_ref: "group:replacement" },
  service_refs: ["service:example"], lock_refs: ["lock:example"], created_at: "2026-09-14T10:01:00Z", expires_at: "2026-09-14T10:59:00Z",
  max_execution_seconds: 60, max_observation_seconds: 300, max_recovery_seconds: 300, rollback_ref: digest,
  execution_path: "pr_manual", default_mode: "shadow", quorum_required: 2, execution_authority: false,
};
const payload = (assessment: unknown = report, plans: readonly unknown[] = [plan]) => decodeAlertQuality({
  source: "alert-noise-governance", available: true, enabled: true, authority: "shadow", unavailable_reason: null, assessment, plans,
}, scope);
const initialLocale = getLocale();
afterEach(() => setLocale(initialLocale));

describe("Operations navigation and bilingual catalogs", () => {
  it("registers one lazy Operations route with its authoritative source and no Sample fallback", () => {
    expect(panelsInGroup("operations").filter((item) => item.id === "alert-quality")).toHaveLength(1);
    expect(panelForId("alert-quality").group).toBe("operations");
    expect(panelSourceClassification("alert-quality")).toBe("operator-api");
    expect(supportsSampleData("alert-quality")).toBe(false);
    const href = routeHref("alert-quality", { params: { scope_ref: scope, rule_ref: finding.rule_ref } });
    const url = new URL(href, "https://console.example");
    const route = parseConsoleRoute(url.pathname, url.search);
    expect(route.panelId).toBe("alert-quality");
    expect(route.canonicalPathname).toBe("/alert-quality");
    expect(route.search.get("scope_ref")).toBe(scope);
    expect(route.search.get("rule_ref")).toBe(finding.rule_ref);
  });

  it("has identical English/Korean keys and placeholders and localized navigation", () => {
    expect(Object.keys(ko).sort()).toEqual(Object.keys(en).sort());
    for (const key of Object.keys(en) as Array<keyof typeof en>) {
      expect(en[key].trim()).not.toBe("");
      expect(ko[key].trim()).not.toBe("");
      expect((ko[key].match(/\{\w+\}/g) ?? []).sort()).toEqual((en[key].match(/\{\w+\}/g) ?? []).sort());
      expect(/[\u2010-\u2015\u2018-\u201d\u2026\u00a0]/.test(en[key] + ko[key])).toBe(false);
    }
    for (const locale of ["en", "ko"] as const) {
      setLocale(locale);
      expect(panelForId("alert-quality").label).toBe(alertQualityText("title"));
      expect(panelForId("alert-quality").subtitle).toBe(alertQualityText("subtitle"));
      expect(alertQualityText("planDetails", { number: 1, target: finding.rule_ref })).toContain(finding.rule_ref);
    }
  });

  it("uses mandatory English fallback for an empty Korean translation", () => {
    const original = ko.title;
    try {
      setLocale("ko");
      ko.title = "";
      expect(alertQualityText("title")).toBe(en.title);
    } finally { ko.title = original; }
  });
});

describe("neutral evidence, native detail links and loading semantics", () => {
  it("renders the real serialized observation window separately from cutoff and validity in both locales", () => {
    const report = decodeAlertQuality(JSON.parse(JSON.stringify(backendFixture)), backendFixture.assessment.scope_ref).assessment!;
    for (const locale of ["en", "ko"] as const) {
      setLocale(locale);
      const view = inspect(AlertQualityProvenance({ report, now }));
      expect(view.elements.filter((item) => item.type === "time").map((item) => item.props.dateTime))
        .toEqual([report.observed_at, report.valid_until, report.window_start, report.window_end]);
      expect(view.content).toContain(alertQualityText("periodHelp"));
      expect(view.content).not.toContain(alertQualityText("periodMissing"));
      const missing = inspect(AlertQualityProvenance({ report: { ...report, window_start: null, window_end: null }, now }));
      expect(missing.content).toContain(alertQualityText("periodMissing"));
      expect(missing.elements.filter((item) => item.type === "time")).toHaveLength(2);
    }
  });

  it("keeps zero, null, incomplete and unavailable measurements distinct in both locales", () => {
    for (const locale of ["en", "ko"] as const) {
      setLocale(locale);
      const view = inspect(AlertQualityEvidence({ report: payload().assessment!, now }));
      const values = view.elements.filter((item) => item.props.class === "alert-quality-metric-value").map((item) => item.props.children);
      expect(values).toEqual(["0", alertQualityText("notMeasured"), "0", alertQualityText("notMeasured")]);
      const provenance = inspect(AlertQualityProvenance({ report: payload().assessment!, now }));
      expect(provenance.content).toContain(alertQualityText("periodMissing"));
      expect(provenance.content).toContain(report.evidence_digest);
      expect(provenance.elements.filter((item) => item.type === "time").map((item) => item.props.dateTime)).toEqual([report.observed_at, report.valid_until]);
      expect(inspect(AlertQualityEvidence({ report: payload({ ...report, coverage: "partial", reasons: ["missing:history"] }).assessment!, now })).content).toContain(alertQualityText("partialCounts"));
      const missing = inspect(AlertQualityEvidence({ report: payload({ ...report, coverage: "unavailable", reasons: ["missing:history"] }).assessment!, now }));
      expect(missing.elements.filter((item) => item.props.class === "alert-quality-metric-value")
        .every((item) => item.props.children === alertQualityText("notMeasured"))).toBe(true);
      expect(alertQualityCount(null)).not.toBe(alertQualityCount(0));
    }
  });

  it("keeps rule references in exact native links and exposes keyboard-scrollable table semantics", () => {
    setLocale("en");
    const data = payload();
    const view = inspect(AlertQualityFindingTable({ rows: data.assessment!.findings, scope, coverage: "complete" }));
    const link = view.elements.find((item) => item.type === "a")!;
    const url = new URL(String(link.props.href), "https://console.example");
    expect(url.pathname).toBe("/alert-quality");
    expect(url.searchParams.get("scope_ref")).toBe(scope);
    expect(url.searchParams.get("rule_ref")).toBe(finding.rule_ref);
    expect(view.elements.filter((item) => item.type === "th").every((item) => item.props.scope === "col")).toBe(true);
    expect(view.elements.find((item) => item.props.role === "region")?.props.tabIndex).toBe(0);
    expect(view.elements.find((item) => item.type === "table")?.props.class).toBe("data-table");
    expect(view.elements.filter((item) => item.type === "th")).toHaveLength(4);
    expect(view.elements.some((item) => item.type === "tr" && item.props.role === "button")).toBe(false);
    expect(view.content).toContain("Unknown / 10");
    expect(view.content).toContain("Not marked protected; not permission to change");
  });

  it("renders null source episodes as unknown rather than zero at report and row level", () => {
    const data = payload({ ...report, source_episodes: null, findings: [{ ...finding, source_episodes: null }] });
    for (const locale of ["en", "ko"] as const) {
      setLocale(locale);
      const evidence = inspect(AlertQualityEvidence({ report: data.assessment!, now }));
      expect(evidence.elements.find((item) => item.props.class === "alert-quality-metric-value")?.props.children).toBe(alertQualityText("unknown"));
      for (const coverage of ["complete", "partial", "unavailable"] as const) {
        const table = inspect(AlertQualityFindingTable({ rows: data.assessment!.findings, scope, coverage }));
        expect(table.content).toMatch(new RegExp(`${alertQualityText("sourceEpisodes")}\\s*:\\s*${alertQualityText("unknown")}`));
      }
    }
  });

  it("never promotes unavailable per-rule counts to measured zero", () => {
    const data = payload();
    const view = inspect(AlertQualityFindingTable({ rows: data.assessment!.findings, scope, coverage: "unavailable" }));
    expect(view.content).toContain(alertQualityText("notMeasured"));
    expect(view.content).toContain(`${alertQualityText("unknown")} / ${alertQualityText("unknown")}`);
    expect(view.content).not.toMatch(new RegExp(`${alertQualityText("sourceEpisodes")}\\s*:\\s*0(?:\\s|$)`));
  });

  it("uses a single accessible skeleton and a native Stop waiting control", () => {
    const stop = vi.fn();
    const view = inspect(CommandFeedback({ command: "pending", onStop: stop }));
    const statuses = view.elements.filter((item) => item.props.role === "status");
    expect(statuses).toHaveLength(1);
    expect(statuses[0]?.props["aria-busy"]).toBe("true");
    expect(view.elements.some((item) => item.props["aria-hidden"] === "true")).toBe(true);
    const button = view.elements.find((item) => item.type === "button")!;
    expect(button.props.type).toBe("button");
    expect(button.props["aria-describedby"]).toBe("alert-quality-stop-help");
    (button.props.onClick as () => void)();
    expect(stop).toHaveBeenCalledTimes(1);
    expect(view.content).toContain(alertQualityText("stopHelp"));
  });
});

describe("all plan kinds, no approval shortcuts and no invented baselines", () => {
  it("localizes current emitted coverage, planner and settings reasons, never raw server text", () => {
    for (const locale of ["en", "ko"] as const) {
      setLocale(locale);
      for (const reason of ["delivery_coverage_incomplete", "history_coverage_incomplete", "candidate_limit_reached",
        "evidence_reason_limit_reached", "routing_source_mismatch", "routing_replacement_missing",
        "routing_replacement_already_bound", "suppression_deadline_does_not_fit", "evaluation_validation_mismatch",
        "request_expired", "scope_denied", "evidence_not_retained", "synthetic_live_evidence",
        "preference_store_unavailable", "writer_unavailable", "producer_not_ready"]) {
        expect(alertQualityReason(reason)).not.toBe(reason);
        expect(alertQualityReason(reason)).not.toBe(alertQualityText("reason.held"));
      }
      expect(alertQualityReason("private provider detail")).toBe(alertQualityText("reason.held"));
    }
  });

  it("shows exact binding deltas and a receipt reference without fabricating a full baseline or metrics", () => {
    const stored = backendFixture.plans[0]!;
    const receipt = `sha256:${"e".repeat(64)}`;
    const raw = { ...backendFixture, plans: [stored, { ...stored, action_type: "ops.tune-alert-evaluation",
      evaluation_receipt_digest: receipt,
      treatment: { kind: "evaluation", target_ref: stored.treatment.target_ref, replacement_group_ref: null,
        remove_group_ref: null, processing_rule_ref: null, starts_at: null, ends_at: null,
        evaluation: { metric_ref: "metric:example", operator: "above", threshold: 75.25,
          window_seconds: 300, frequency_seconds: 60, aggregation: "maximum" } } }] };
    const plans = decodeAlertQuality(JSON.parse(JSON.stringify(raw)), backendFixture.assessment.scope_ref).plans;
    for (const locale of ["en", "ko"] as const) {
      setLocale(locale);
      const view = inspect(AlertQualityPlans({ plans, now }));
      for (const key of ["removedBinding", "addedBinding", "beforeMissing", "evaluationReceiptHelp", "benefitMissing"] as const) {
        expect(view.content).toContain(alertQualityText(key));
      }
      for (const value of [stored.treatment.remove_group_ref, stored.treatment.replacement_group_ref,
        stored.target_revision, stored.rollback_ref, receipt, "75.25"]) expect(view.content).toContain(value);
      expect(view.content).not.toContain("0%");
      expect(view.elements.some((item) => item.type === "button")).toBe(false);
    }
  });

  it("localizes pending states without disclosing arbitrary provider prose", () => {
    expect(alertQualityReason("assessment_pending")).toBe(alertQualityText("reason.assessment_pending"));
    expect(alertQualityReason("proposal_pending")).toBe(alertQualityText("reason.proposal_pending"));
    expect(alertQualityReason("assessment_expired")).toBe(alertQualityText("reason.assessment_expired"));
    expect(alertQualityReason("protected_alert")).toBe(alertQualityText("reason.protectedHeld"));
    expect(alertQualityReason("evaluation_validation_missing")).toBe(alertQualityText("reason.evaluationEvidenceHeld"));
    expect(alertQualityReason("private provider message")).toBe(alertQualityText("reason.held"));
    expect(alertQualityReason("__proto__")).toBe(alertQualityText("reason.held"));
  });

  it("renders routing, finite suppression and evaluation plans without apply or approve controls", () => {
    const data = payload(report, [plan, {
      ...plan, action_type: "ops.set-alert-notification-window",
      treatment: { kind: "suppression", target_ref: finding.rule_ref, processing_rule_ref: "processing:example", starts_at: "2026-09-14T11:00:00+00:00", ends_at: "2026-09-14T12:00:00+00:00" },
    }, {
      ...plan, action_type: "ops.tune-alert-evaluation",
      treatment: { kind: "evaluation", target_ref: finding.rule_ref, evaluation: { metric_ref: "metric:example", operator: "above", threshold: 1e-9, window_seconds: 300, frequency_seconds: 60, aggregation: "maximum" } },
    }]);
    for (const locale of ["en", "ko"] as const) {
      setLocale(locale);
      const view = inspect(AlertQualityPlans({ plans: data.plans, now }));
      expect(view.elements.filter((item) => item.type === "summary")).toHaveLength(3);
      expect(view.elements.filter((item) => item.type === "button")).toHaveLength(0);
      expect(view.elements.filter((item) => item.type === "a").map((item) => item.props.href)).toEqual(["/approvals"]);
      for (const key of ["shadow", "kind.routing", "kind.suppression", "kind.evaluation", "quorumHelp", "beforeMissing", "suppressionHelp", "evaluationHelp"] as const) {
        expect(view.content).toContain(alertQualityText(key));
      }
      expect(view.content).toContain("group:source");
      expect(view.content).toContain("group:replacement");
      expect(view.content).toContain("1e-9");
    }
  });

  it("labels plan expiry and distinguishes an empty projection from success", () => {
    setLocale("en");
    expect(inspect(AlertQualityPlans({ plans: payload().plans, now: Date.parse(plan.expires_at) })).content).toContain("Expired");
    expect(inspect(AlertQualityPlans({ plans: [], now })).content).toContain(en.noPlans);
    const unknown = inspect(CommandFeedback({ command: "unknown", onStop: vi.fn() }));
    expect(unknown.content).toContain(en["command.unknown"]);
    expect(unknown.elements.some((item) => item.type === "button")).toBe(false);
  });
});
