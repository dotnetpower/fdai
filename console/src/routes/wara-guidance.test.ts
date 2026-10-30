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
    expect(view.content).toContain(guidanceText(guidance.summary, locale));
    expect(view.content).toContain(locale === "ko" ? "실제 환경을 관측한 결과가 아닌 구성 예시" : "not an observation of your environment");
    expect(view.content).toContain(locale === "ko" ? "검증 방법" : "Verification");
    expect(view.elements.filter((element) => element.type === "table")).toHaveLength(0);
    expect(view.elements.filter((element) => element.type === "nav")).toHaveLength(1);
    expect(view.content).toContain(guidanceText(guidance.configuration.before[0]!, locale));
    expect(view.content).toContain(guidanceText(guidance.configuration.after[0]!, locale));
    expect(view.elements.filter((element) => element.type === "ol")).toHaveLength(2);
    expect(view.elements.some((element) => element.type === WaraGuidanceDiagram)).toBe(true);
    expect(view.content).toContain(guidanceText(guidance.rationale, locale));
    expect(view.elements.findIndex((element) => element.props["class"] === "wara-guidance-rationale"))
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

  test.each(["en", "ko"] as const)("makes retained translation gaps explicit only in the affected locale %s", (locale) => {
    setLocale(locale);
    const control = fixtureControl();
    const view = inspect(WaraGuidanceContent({ control: { ...control, guidance: fixtureGuidance(control) }, expanded: false, onExpand: () => undefined }));
    expect(view.elements.some((element) => element.props["class"] === "wara-guidance-translation-note")).toBe(locale === "ko");
    if (locale === "ko") expect(view.content).toContain("한국어 번역이 누락");
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

  test("gives wide Korean text the same compact-diagram budget without truncating its explanation", () => {
    const diagram = fixtureGuidance().diagram;
    const original = diagram.nodes[1]!;
    const ko = "복구 조건을 독립적으로 검증합니다. ".repeat(9);
    const presentation = guidanceNodePresentation(diagram, { ...original, detail: { en: "Short explanation", ko } }, "ko");
    expect(ko.length).toBeLessThan(220);
    expect(presentation.fullExplanation).toBe(true);
    expect(presentation.detail).toBe(ko);
  });

  test("keeps a conditional feedback link out of the primary reading order", () => {
    const diagram = fixtureGuidance().diagram;
    const nodes = diagram.nodes.slice(0, 3);
    const [first, second, third] = nodes;
    const columns = guidanceColumns({
      ...diagram, nodes,
      edges: [
        { from: first!.id, to: second!.id, label: { en: "Creates" }, style: "solid" },
        { from: second!.id, to: third!.id, label: { en: "Transfers" }, style: "solid" },
        { from: third!.id, to: first!.id, label: { en: "Verifies" }, style: "dashed" },
      ],
    });
    expect(columns.map((column) => column.map((node) => node.id))).toEqual(nodes.map((node) => [node.id]));
  });

  test("separates return routes by eight pixels and reserves top channels for skipped columns", () => {
    const from = { x: 120, y: 80, width: 200, height: 100 };
    const to = { x: 120, y: 240, width: 200, height: 100 };
    expect(guidanceEdgePath(from, to, 0, true)).toContain("H 12");
    expect(guidanceEdgePath(from, to, 1, true)).toContain("H 20");
    expect(guidanceEdgePath(from, { ...to, x: 700 }, 1, false)).toContain("V 20");
  });
});
