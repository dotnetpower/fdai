import { describe, expect, it } from "vitest";
import { parseAnswer, parseInline, type Segment } from "./rich-parse";

function kinds(segs: Segment[]): string[] {
  return segs.map((s) => s.kind);
}

describe("parseAnswer - text", () => {
  it("returns a single text segment for plain prose", () => {
    const segs = parseAnswer("There are 61 active rules.");
    expect(kinds(segs)).toEqual(["text"]);
    expect(segs[0]).toMatchObject({ kind: "text", text: "There are 61 active rules." });
  });

  it("joins multi-line prose into one text segment", () => {
    const segs = parseAnswer("line one\nline two");
    expect(kinds(segs)).toEqual(["text"]);
    expect(segs[0]).toMatchObject({ text: "line one\nline two" });
  });

  it("returns no segments for empty or whitespace-only input", () => {
    expect(parseAnswer("")).toEqual([]);
    expect(parseAnswer("   \n  \n")).toEqual([]);
  });
});

describe("parseAnswer - tables", () => {
  it("parses a basic markdown table", () => {
    const md = "| id | sev |\n| --- | --- |\n| r1 | high |\n| r2 | low |";
    const segs = parseAnswer(md);
    expect(kinds(segs)).toEqual(["table"]);
    expect(segs[0]).toMatchObject({
      kind: "table",
      headers: ["id", "sev"],
      rows: [
        ["r1", "high"],
        ["r2", "low"],
      ],
    });
  });

  it("accepts alignment colons in the separator", () => {
    const md = "| a | b |\n|:---|---:|\n| 1 | 2 |";
    const segs = parseAnswer(md);
    expect(kinds(segs)).toEqual(["table"]);
    expect(segs[0]).toMatchObject({ headers: ["a", "b"], rows: [["1", "2"]] });
  });

  it("does NOT treat pipe rows without a separator as a table", () => {
    const md = "| a | b |\n| 1 | 2 |";
    const segs = parseAnswer(md);
    expect(kinds(segs)).toEqual(["text"]);
  });

  it("wraps text around a table into separate segments", () => {
    const md = "before\n| a | b |\n| --- | --- |\n| 1 | 2 |\nafter";
    const segs = parseAnswer(md);
    expect(kinds(segs)).toEqual(["text", "table", "text"]);
    expect(segs[0]).toMatchObject({ text: "before" });
    expect(segs[2]).toMatchObject({ text: "after" });
  });

  it("tolerates ragged rows (fewer cells than headers)", () => {
    const md = "| a | b | c |\n| --- | --- | --- |\n| 1 | 2 |";
    const segs = parseAnswer(md);
    expect(segs[0]).toMatchObject({ headers: ["a", "b", "c"], rows: [["1", "2"]] });
  });
});

describe("parseAnswer - code", () => {
  it("parses a fenced code block with a language", () => {
    const md = "```json\n{\"a\": 1}\n```";
    const segs = parseAnswer(md);
    expect(kinds(segs)).toEqual(["code"]);
    expect(segs[0]).toMatchObject({ kind: "code", lang: "json", code: '{"a": 1}' });
  });

  it("parses a fenced block with no language (lang is empty)", () => {
    const md = "```\nplain\n```";
    const segs = parseAnswer(md);
    expect(segs[0]).toMatchObject({ kind: "code", lang: "", code: "plain" });
  });

  it("preserves multi-line code content", () => {
    const md = "```yaml\na: 1\nb:\n  - x\n  - y\n```";
    const segs = parseAnswer(md);
    expect(segs[0]).toMatchObject({ kind: "code", lang: "yaml", code: "a: 1\nb:\n  - x\n  - y" });
  });

  it("lowercases the language tag", () => {
    const segs = parseAnswer("```JSON\n1\n```");
    expect(segs[0]).toMatchObject({ lang: "json" });
  });

  it("handles an unterminated fence to end of input", () => {
    const segs = parseAnswer("```bash\necho hi");
    expect(segs[0]).toMatchObject({ kind: "code", lang: "bash", code: "echo hi" });
  });
});

describe("parseAnswer - charts", () => {
  it("parses a valid bar chart block", () => {
    const md = '```chart\n{"type":"bar","data":[{"label":"T0","value":78}]}\n```';
    const segs = parseAnswer(md);
    expect(kinds(segs)).toEqual(["chart"]);
    expect(segs[0]).toMatchObject({
      kind: "chart",
      spec: { type: "bar", data: [{ label: "T0", value: 78 }] },
    });
  });

  it("keeps title and unit when present", () => {
    const md =
      '```chart\n{"type":"bar","title":"Tiers","unit":"%","data":[{"label":"T0","value":78}]}\n```';
    const segs = parseAnswer(md);
    expect(segs[0]).toMatchObject({ spec: { title: "Tiers", unit: "%" } });
  });

  it("omits title/unit keys when absent", () => {
    const md = '```chart\n{"type":"bar","data":[{"label":"x","value":1}]}\n```';
    const seg = parseAnswer(md)[0]!;
    expect(seg.kind).toBe("chart");
    if (seg.kind === "chart") {
      expect("title" in seg.spec).toBe(false);
      expect("unit" in seg.spec).toBe(false);
    }
  });

  it("filters out non-numeric or malformed data points", () => {
    const md =
      '```chart\n{"type":"bar","data":[{"label":"ok","value":5},{"label":"bad","value":"x"},{"value":9}]}\n```';
    const seg = parseAnswer(md)[0]!;
    if (seg.kind === "chart") {
      expect(seg.spec.data).toEqual([{ label: "ok", value: 5 }]);
    } else {
      throw new Error("expected chart");
    }
  });

  it("falls back to text when the chart JSON is invalid", () => {
    const md = "```chart\nnot json\n```";
    const segs = parseAnswer(md);
    expect(kinds(segs)).toEqual(["text"]);
    expect(segs[0]).toMatchObject({ kind: "text" });
    if (segs[0]?.kind === "text") expect(segs[0].text).toContain("not json");
  });

  it("falls back to text when type is not bar", () => {
    const md = '```chart\n{"type":"pie","data":[{"label":"a","value":1}]}\n```';
    expect(kinds(parseAnswer(md))).toEqual(["text"]);
  });

  it("accepts a line chart and preserves the type", () => {
    const md =
      '```chart\n{"type":"line","unit":"eps","data":[{"label":"t0","value":1},{"label":"t1","value":4}]}\n```';
    const seg = parseAnswer(md)[0]!;
    expect(seg.kind).toBe("chart");
    if (seg.kind === "chart") {
      expect(seg.spec.type).toBe("line");
      expect(seg.spec.data).toHaveLength(2);
    }
  });

  it("falls back to text when data is empty", () => {
    const md = '```chart\n{"type":"bar","data":[]}\n```';
    expect(kinds(parseAnswer(md))).toEqual(["text"]);
  });

  it("renders a chart spec wrapped in a ```json fence as a chart", () => {
    const md = '```json\n{"type":"bar","data":[{"label":"a","value":1}]}\n```';
    expect(kinds(parseAnswer(md))).toEqual(["chart"]);
  });

  it("renders a chart spec in an unlabelled fence as a chart", () => {
    const md = '```\n{"type":"line","data":[{"label":"a","value":1}]}\n```';
    expect(kinds(parseAnswer(md))).toEqual(["chart"]);
  });

  it("keeps ordinary json (no chart shape) as a code block", () => {
    const md = '```json\n{"id":"r1","severity":"high"}\n```';
    const segs = parseAnswer(md);
    expect(kinds(segs)).toEqual(["code"]);
    expect(segs[0]).toMatchObject({ kind: "code", lang: "json" });
  });

  it("shows a chart-pending placeholder while a chart spec is still streaming", () => {
    const md = '```chart\n{"type":"bar","data":[{"label":"a"';
    expect(kinds(parseAnswer(md))).toEqual(["chart-pending"]);
  });

  it("shows chart-pending for a ```json-wrapped spec still streaming", () => {
    const md = '```json\n{"type":"line","data":[{"lab';
    expect(kinds(parseAnswer(md))).toEqual(["chart-pending"]);
  });

  it("does NOT show chart-pending for an unterminated non-chart code fence", () => {
    const md = "```yaml\na: 1\nb: 2";
    expect(kinds(parseAnswer(md))).toEqual(["code"]);
  });

  it("accepts a safe hex color and rejects an unsafe one", () => {
    const md =
      '```chart\n{"type":"bar","data":[{"label":"a","value":1,"color":"#e5484d"},{"label":"b","value":2,"color":"red; background:url(x)"}]}\n```';
    const seg = parseAnswer(md)[0]!;
    if (seg.kind === "chart") {
      expect(seg.spec.data[0]).toEqual({ label: "a", value: 1, color: "#e5484d" });
      expect(seg.spec.data[1]).toEqual({ label: "b", value: 2 });
      expect("color" in seg.spec.data[1]!).toBe(false);
    } else {
      throw new Error("expected chart");
    }
  });
});

describe("parseAnswer - mixed documents", () => {
  it("splits prose, table, code, and chart in order", () => {
    const md = [
      "Here is the breakdown:",
      "| k | v |",
      "| --- | --- |",
      "| a | 1 |",
      "And a chart:",
      "```chart",
      '{"type":"bar","data":[{"label":"a","value":1}]}',
      "```",
      "And config:",
      "```yaml",
      "a: 1",
      "```",
    ].join("\n");
    const segs = parseAnswer(md);
    expect(kinds(segs)).toEqual(["text", "table", "text", "chart", "text", "code"]);
  });

  it("keeps two consecutive code blocks separate", () => {
    const md = "```json\n1\n```\n```yaml\na: 1\n```";
    const segs = parseAnswer(md);
    expect(kinds(segs)).toEqual(["code", "code"]);
    expect(segs[0]).toMatchObject({ lang: "json" });
    expect(segs[1]).toMatchObject({ lang: "yaml" });
  });
});

describe("parseInline", () => {
  it("returns one text run for plain prose", () => {
    expect(parseInline("just words")).toEqual([{ t: "text", s: "just words" }]);
  });

  it("extracts an inline code span", () => {
    expect(parseInline("the `rule.id` value")).toEqual([
      { t: "text", s: "the " },
      { t: "code", s: "rule.id" },
      { t: "text", s: " value" },
    ]);
  });

  it("extracts a strong span", () => {
    expect(parseInline("this is **bold** here")).toEqual([
      { t: "text", s: "this is " },
      { t: "strong", s: "bold" },
      { t: "text", s: " here" },
    ]);
  });

  it("handles multiple and adjacent spans", () => {
    expect(parseInline("`a``b`")).toEqual([
      { t: "code", s: "a" },
      { t: "code", s: "b" },
    ]);
  });

  it("mixes code and strong in one line", () => {
    expect(parseInline("**T0** is `deterministic`")).toEqual([
      { t: "strong", s: "T0" },
      { t: "text", s: " is " },
      { t: "code", s: "deterministic" },
    ]);
  });

  it("never returns empty (blank line -> one text run)", () => {
    expect(parseInline("")).toEqual([{ t: "text", s: "" }]);
  });
});
