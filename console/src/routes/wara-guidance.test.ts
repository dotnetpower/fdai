import { isValidElement, toChildArray, type ComponentChildren, type VNode } from "preact";
import { afterEach, describe, expect, test } from "vitest";
import { setLocale } from "../i18n";
import { WaraGuidanceContent } from "./wara-guidance";
import { guidanceColumns, guidanceEdgePath, guidanceNodePresentation, WaraGuidanceDiagram } from "./wara-guidance-diagram";
import { fixtureControl, fixtureGuidance } from "./wara-guidance.fixture";
import { guidanceText } from "./wara-guidance.model";

// Component-tree evidence only. Browser geometry and keyboard behavior belong to the focused E2E.
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
  return { content: content.join(" "), elements };
}

afterEach(() => setLocale("en"));

describe("WARA illustrated reading view", () => {
  test.each(["en", "ko"] as const)("renders ordered technical sections and explicit reference/evidence boundaries in %s", (locale) => {
    setLocale(locale);
    const control = fixtureControl();
    const guidance = fixtureGuidance(control);
    const view = inspect(WaraGuidanceContent({ control: { ...control, guidance }, expanded: false, onExpand: () => undefined }));
    expect(view.content).toContain(locale === "ko" ? "핵심 설명" : "Key explanation");
    expect(view.content).toContain(locale === "ko" ? "실제 환경을 관측한 결과가 아닌 구성 예시" : "not an observation of your environment");
    expect(view.content).toContain(locale === "ko" ? "검증 방법" : "Verification");
    expect(view.elements.filter((element) => element.type === "table")).toHaveLength(1);
    expect(view.elements.filter((element) => element.type === "ol")).toHaveLength(2);
    expect(view.elements.some((element) => element.type === WaraGuidanceDiagram)).toBe(true);
    expect(view.content).toContain(guidanceText(guidance.rationale, locale));
    expect(view.elements.findIndex((element) => element.props["name"] === "rationale"))
      .toBeGreaterThan(view.elements.findIndex((element) => element.type === WaraGuidanceDiagram));
    expect(view.elements.some((element) => "dangerouslySetInnerHTML" in element.props)).toBe(false);
    expect(view.elements.filter((element) => element.type === "a").map((element) => element.props["href"])).toContain(control.source_url);
  });

  test("renders an honest missing-guide state with base explanation and pinned source", () => {
    const control = fixtureControl();
    const view = inspect(WaraGuidanceContent({ control, expanded: false, onExpand: () => undefined }));
    expect(view.content).toContain("not yet available");
    expect(view.content).toContain(control.description);
    expect(view.content).toContain(control.source_version);
    expect(view.elements.some((element) => element.type === WaraGuidanceDiagram)).toBe(false);
    expect(view.elements.some((element) => element.type === "table")).toBe(false);
  });

  test.each(["en", "ko"] as const)("labels disabled catalog history without reactivating assessment in %s", (locale) => {
    setLocale(locale);
    const control = { ...fixtureControl(), lifecycle: "disabled" as const };
    const view = inspect(WaraGuidanceContent({ control: { ...control, guidance: fixtureGuidance(control) }, expanded: false, onExpand: () => undefined }));
    expect(view.content).toContain(locale === "ko" ? "카탈로그 이력" : "catalog history only");
    expect(view.elements.some((element) => element.props["role"] === "note")).toBe(true);
    expect(control.satisfaction).toBe("unknown");
  });

  test("keeps typed content as text and preserves every diagram node", () => {
    const control = fixtureControl();
    const guidance = fixtureGuidance(control);
    const view = inspect(WaraGuidanceContent({ control: { ...control, guidance: { ...guidance, title: { en: "<script>not executable</script>" } } }, expanded: false, onExpand: () => undefined }));
    expect(view.content).toContain("<script>not executable</script>");
    expect(guidanceColumns(guidance.diagram).flat()).toHaveLength(guidance.diagram.nodes.length);
    expect(guidanceEdgePath({ x: 40, y: 0, width: 200, height: 100 }, { x: 288, y: 100, width: 200, height: 100 }, 0, false)).toMatch(/^M 240 50 H /);
    expect(guidanceEdgePath({ x: 40, y: 0, width: 200, height: 100 }, { x: 40, y: 150, width: 200, height: 100 }, 0, true)).toContain("V 200");
  });

  test("uses a typed relationship label for long node copy while retaining the complete explanation", () => {
    const guidance = fixtureGuidance();
    const original = guidance.diagram.nodes[1]!;
    const detail = "A complete qualified explanation with all prerequisites. ".repeat(12);
    const node = { ...original, detail: { en: detail } };
    const presented = guidanceNodePresentation(guidance.diagram, node, "en");
    expect(presented.fullExplanation).toBe(true);
    expect(presented.primaryDetail).toBe(guidance.diagram.edges[0]!.label.en);
    expect(presented.detail).toBe(detail);
    expect(guidanceNodePresentation(guidance.diagram, original, "en").primaryDetail).toBe(original.detail.en);
  });
});
