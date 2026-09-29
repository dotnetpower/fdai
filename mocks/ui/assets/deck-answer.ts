import { parseAnswer, parseInline } from "../../../console/src/deck/rich-parse";
import { parsePresentationArtifact } from "../../../console/src/deck/presentation-artifact";
import type { AnswerVerification, PresentationBlock, PresentationTableData } from "../../../console/src/deck/backend-types";

interface AnswerInput {
  readonly format: "markdown" | "json";
  readonly content: unknown;
  readonly verification?: AnswerVerification;
}

interface AnswerOptions {
  readonly citation?: (reference: string) => Node | undefined;
}

function element<K extends keyof HTMLElementTagNameMap>(tag: K, text?: string): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  return node;
}

function inline(host: HTMLElement, text: string, options: AnswerOptions): void {
  for (const run of parseInline(text)) {
    if (run.t === "link") {
      let url: URL;
      try {
        url = new URL(run.href, document.baseURI);
      } catch {
        host.append(document.createTextNode(run.s));
        continue;
      }
      if (url.protocol !== "https:" && url.protocol !== "http:") {
        host.append(document.createTextNode(run.s));
        continue;
      }
      const link = element("a", run.s);
      link.href = run.href;
      host.append(link);
    } else if (run.t === "cite") {
      host.append(options.citation?.(String(run.n)) || element("span", "[" + run.n + "]"));
    } else {
      const parent = run.t === "code" ? element("code") : run.t === "strong" ? element("strong") : run.t === "emphasis" ? element("em") : run.t === "strike" ? element("del") : element("span");
      for (const part of run.s.split(/(\{[a-zA-Z]+\})/g)) {
        const reference = part.startsWith("{") && part.endsWith("}") ? part.slice(1, -1) : "";
        parent.append(reference && options.citation?.(reference) || document.createTextNode(part));
      }
      host.append(parent);
    }
  }
}

function table(headers: readonly string[], rows: readonly (readonly string[])[], title: string | undefined, options: AnswerOptions): HTMLElement {
  const wrapper = element("div");
  wrapper.className = "ds-answer-table";
  const grid = element("table");
  if (title) grid.append(element("caption", title));
  const head = element("tr");
  for (const label of headers) {
    const cell = element("th");
    cell.scope = "col";
    inline(cell, label, options);
    head.append(cell);
  }
  const thead = element("thead");
  thead.append(head);
  grid.append(thead);
  const body = element("tbody");
  for (const row of rows) {
    const line = element("tr");
    for (const value of row) {
      const cell = element("td");
      inline(cell, value, options);
      line.append(cell);
    }
    body.append(line);
  }
  grid.append(body);
  wrapper.append(grid);
  return wrapper;
}

function code(text: string, language = "text"): HTMLElement {
  const figure = element("figure");
  figure.className = "ds-answer-code";
  figure.append(element("figcaption", language));
  const pre = element("pre");
  pre.append(element("code", text));
  figure.append(pre);
  return figure;
}

function originalInput(host: HTMLElement, input: AnswerInput): void {
  const original = element("details");
  original.className = "ds-answer-original";
  original.append(element("summary", "Original " + (input.format === "markdown" ? "Markdown" : "JSON")), code(typeof input.content === "string" ? input.content : JSON.stringify(input.content, null, 2) ?? String(input.content), input.format));
  host.append(original);
}

function markdown(host: HTMLElement, text: string, options: AnswerOptions): void {
  for (const segment of parseAnswer(text)) {
    if (segment.kind === "text" || segment.kind === "heading" || segment.kind === "quote") {
      const node = segment.kind === "heading" ? element(segment.level === 1 ? "h3" : segment.level === 2 ? "h4" : "h5") : element(segment.kind === "quote" ? "blockquote" : "p");
      inline(node, segment.text, options);
      host.append(node);
    } else if (segment.kind === "list") {
      const list = element(segment.ordered ? "ol" : "ul");
      for (const item of segment.items) {
        const entry = element("li");
        if (item.checked !== undefined) entry.append(document.createTextNode(item.checked ? "[x] " : "[ ] "));
        inline(entry, item.text, options);
        list.append(entry);
      }
      host.append(list);
    } else if (segment.kind === "table") {
      host.append(table(segment.headers, segment.rows, undefined, options));
    } else if (segment.kind === "code") {
      host.append(code(segment.code, segment.lang));
    } else if (segment.kind === "divider") {
      host.append(element("hr"));
    } else if (segment.kind === "chart") {
      host.append(table(["Label", segment.spec.unit || "Value"], segment.spec.data.map(item => [item.label, String(item.value)]), segment.spec.title, options));
    } else {
      host.append(code(JSON.stringify(segment, null, 2), "json"));
    }
  }
}

// A block's table is named by its block title, which the block heading already shows.
function structuredTable(data: PresentationTableData, label: string, options: AnswerOptions): HTMLElement {
  const wrapper = table(data.columns.map(column => column.label), data.rows.map(row => data.columns.map(column => row[column.key] ?? "")), undefined, options);
  wrapper.querySelector("table")?.setAttribute("aria-label", label);
  return wrapper;
}

function blockBody(block: PresentationBlock, options: AnswerOptions): HTMLElement {
  const body = element("div");
  body.className = "ds-answer-block-body";
  if (block.kind === "summary") {
    const facts = element("dl");
    for (const item of block.data.items) {
      const row = element("div");
      row.append(element("dt", item.label));
      const value = element("dd");
      inline(value, item.value, options);
      value.dataset.tone = item.tone;
      row.append(value);
      facts.append(row);
    }
    body.append(facts);
  } else if (block.kind === "callout") {
    body.dataset.tone = block.data.tone;
    for (const line of block.data.lines) {
      const paragraph = element("p");
      inline(paragraph, line, options);
      body.append(paragraph);
    }
  } else if (block.kind === "table" || block.kind === "threshold_table" || block.kind === "list") {
    body.append(structuredTable(block.data, block.title, options));
  } else if (block.kind === "evidence") {
    const facts = element("dl");
    for (const item of block.data.items) {
      const row = element("div");
      row.append(element("dt", item.label), element("dd", item.value));
      facts.append(row);
    }
    body.append(facts);
  } else if ("exactTable" in block.data) {
    body.append(structuredTable(block.data.exactTable, block.title, options));
  } else {
    body.append(code(JSON.stringify(block.data, null, 2), "json"));
  }
  const references = element("div");
  references.className = "ds-answer-refs";
  for (const reference of block.evidenceRefs) references.append(options.citation?.(reference) || element("code", reference));
  body.append(references);
  return body;
}

export function renderAnswer(host: HTMLElement, input: AnswerInput, options: AnswerOptions = {}): void {
  host.replaceChildren();
  host.classList.add("ds-common-answer");
  if (input.format === "markdown" && typeof input.content === "string") {
    markdown(host, input.content, options);
    originalInput(host, input);
    return;
  }
  let raw = input.content;
  try {
    if (typeof raw === "string") raw = JSON.parse(raw);
  } catch {
    host.append(element("p", "Invalid JSON. Original input retained."), code(String(input.content), "json"));
    return;
  }
  const verification = input.verification && Array.isArray(input.verification.evidence_refs) && input.verification.evidence_refs.every(reference => typeof reference === "string")
    ? input.verification : undefined;
  const artifact = parsePresentationArtifact(raw, verification);
  if (!artifact) {
    host.append(element("p", "Unrecognized or unsupported structured input. Original JSON retained."), code(typeof input.content === "string" ? input.content : JSON.stringify(input.content, null, 2) ?? String(input.content), "json"));
    return;
  }
  for (const block of artifact.blocks) {
    const critical = block.kind === "callout" && (block.data.tone === "attention" || block.data.tone === "warning");
    const section = block.collapsed && !critical && block.slotId !== "limitations" ? element("details") : element("section");
    section.className = "ds-answer-block";
    section.dataset.emphasis = block.emphasis;
    section.dataset.kind = block.kind;
    section.dataset.slot = block.slotId;
    section.append(element(section.tagName === "DETAILS" ? "summary" : "h3", block.title), blockBody(block, options));
    host.append(section);
  }
  originalInput(host, input);
}

Object.assign(window, { FDAIDeckAnswer: { render: renderAnswer } });
