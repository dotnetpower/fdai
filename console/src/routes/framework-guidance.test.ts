import { isValidElement, toChildArray, type ComponentChildren, type VNode } from "preact";
import { afterEach, describe, expect, test } from "vitest";
import { setLocale } from "../i18n";
import { FrameworkGuidanceContent } from "./framework-guidance";
import { fixtureFrameworkGuidance } from "./framework-guidance.fixture";
import { ControlEnablementSection } from "./control-enablement";
import { WaraGuidanceDiagram } from "./wara-guidance-diagram";
import { guidanceText } from "./wara-guidance.model";
import { ControlRemediationSection } from "./control-remediation";

function inspect(tree: ComponentChildren) {
  const content: string[] = [];
  const elements: VNode<Record<string, unknown>>[] = [];
  const visit = (child: ComponentChildren): void => {
    for (const node of toChildArray(child)) {
      if (typeof node === "string" || typeof node === "number") content.push(String(node));
      else if (isValidElement(node)) {
        const element = node as VNode<Record<string, unknown>>;
        elements.push(element);
        if (typeof element.type === "function" && element.type !== WaraGuidanceDiagram) {
          visit((element.type as (props: Record<string, unknown>) => ComponentChildren)(element.props));
        } else visit(element.props.children as ComponentChildren);
      }
    }
  };
  visit(tree);
  return { text: content.join(" "), elements };
}

afterEach(() => setLocale("en"));

describe("shared framework reading view", () => {
  test.each(["en", "ko"] as const)("reuses all WARA-quality technical sections and diagram in %s without WARA identity", (locale) => {
    setLocale(locale);
    for (const framework of ["azure-waf", "azure-mcsb", "azure-caf"] as const) {
      const guide = fixtureFrameworkGuidance(framework);
      const view = inspect(FrameworkGuidanceContent({
        guidance: guide, controlId: guide.control_id, title: "Source title", expanded: false, onExpand: () => undefined,
      }));
      expect(view.text).toContain(guidanceText(guide.summary, locale));
      expect(view.text).toContain(guidanceText(guide.benefits, locale));
      expect(view.text).toContain(guidanceText(guide.rationale, locale));
      expect(view.text).toContain(locale === "ko" ? "실제 환경을 관측한 결과가 아닌 구성 예시" : "not an observation of your environment");
      expect(view.elements.filter((element) => element.type === "ol")).toHaveLength(2);
      expect(view.elements.some((element) => element.type === WaraGuidanceDiagram)).toBe(true);
      expect(view.elements.filter((element) => element.type === "a").map((element) => element.props["href"]))
        .toEqual(expect.arrayContaining(["#framework-configuration", "#framework-implementation", "#framework-verification", "#framework-runtime", guide.sources[0]!.url]));
      expect(view.elements.some((element) => element.props["data-recommendation-id"] !== undefined)).toBe(false);
      expect(view.elements.some((element) => "dangerouslySetInnerHTML" in element.props)).toBe(false);
    }
  });

  test.each(["en", "ko"] as const)("shows guide absence without hiding base context or inventing evidence in %s", (locale) => {
    setLocale(locale);
    const view = inspect(FrameworkGuidanceContent({
      guidance: null, controlId: "strategy", title: "Strategy", description: "Source explanation",
      expanded: false, onExpand: () => undefined, unavailableReason: "source_pin_unavailable",
    }));
    expect(view.text).toContain("Source explanation");
    expect(view.text).toContain(locale === "ko" ? "그림 안내가 없습니다" : "guidance is not available");
    expect(view.text).toContain("source_pin_unavailable");
    expect(view.elements.some((element) => element.type === WaraGuidanceDiagram)).toBe(false);
    expect(view.elements.some((element) => element.props["role"] === "status")).toBe(true);
  });

  test.each(["en", "ko"] as const)("distinguishes server default, override, readiness and no authority in %s", (locale) => {
    setLocale(locale);
    const view = inspect(ControlEnablementSection({
      value: { severity: "low", default_enabled: false, enabled: true, source: "profile_override", mode: "shadow", execution_authority: false, available: false, unavailable_reason: "missing_evidence" },
      severitySource: "fdai_default",
    }));
    for (const text of locale === "ko"
      ? ["FDAI 기본값", "재정의", "활성화됨", "비활성화됨", "사용 불가", "실행 권한은 없습니다", "검토된 배포 프로필"]
      : ["FDAI default", "profile override", "Enabled", "Disabled", "Unavailable", "Execution authority: none", "reviewed deployment profile"]) expect(view.text).toContain(text);
    expect(view.text).toContain("shadow");
    expect(view.text).toContain("missing_evidence");
    expect(view.elements.some((element) => ["button", "input", "select"].includes(String(element.type)))).toBe(false);
  });

  test("does not infer a preference or readiness when the server omits it", () => {
    const view = inspect(ControlEnablementSection({ value: null, severitySource: undefined }));
    expect(view.text).toContain("No default is inferred");
  });

  test.each(["en", "ko"] as const)("renders inert governed Rule references and the authority boundary in %s", (locale) => {
    setLocale(locale);
    const view = inspect(ControlRemediationSection({
      value: {
        status: "governed_candidates", candidates: [{ rule_id: "storage.https-only", action_type_ref: "storage.enable-https" }],
        limitations: ["promotion_required"], execution_authority: false,
      },
    }));
    expect(view.text).toContain("storage.enable-https");
    expect(view.text).toContain("promotion_required");
    expect(view.text).toContain(locale === "ko" ? "실행 권한을 부여하지 않습니다" : "grant no execution authority");
    const link = view.elements.find((element) => element.type === "a");
    const params = new URL(String(link?.props["href"]), "http://localhost").searchParams;
    expect(params.get("rule")).toBe("storage.https-only");
    expect(view.elements.some((element) => element.type === "button")).toBe(false);
    for (const status of ["manual_guidance", "unavailable"] as const) {
      const state = inspect(ControlRemediationSection({ value: { status, candidates: [], limitations: [], execution_authority: false } }));
      expect(state.elements.some((element) => element.type === "a")).toBe(false);
    }
  });
});
