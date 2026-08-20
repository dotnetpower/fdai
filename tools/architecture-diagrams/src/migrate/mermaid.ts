import type {
  DiagramEdge,
  DiagramGroup,
  DiagramKind,
  DiagramNode,
  DiagramSpec,
  Direction,
  EdgeKind,
} from "../model/types.js";
import { validateDiagram } from "../model/validate.js";

export interface MermaidBlock {
  heading: string;
  source: string;
}

interface ParsedEndpoint {
  id: string;
  label: string;
  kind: DiagramNode["kind"];
  shape?: DiagramNode["shape"];
}

interface ParsedFlow {
  direction: Direction;
  groups: Array<{ id: string; label: string; parent?: string }>;
  nodes: Array<ParsedEndpoint & { parent?: string }>;
  edges: Array<{ from: string; to: string; label: string; dotted: boolean }>;
}

interface ParsedSequenceStep {
  from: string;
  to: string;
  label: string;
  context: string[];
}

interface ParsedSequence {
  participants: Map<string, string>;
  steps: ParsedSequenceStep[];
}

interface ParsedTimeline {
  title: string;
  entries: Array<{ id: string; details: string[] }>;
}

interface ParsedGantt {
  title: string;
  sections: Array<{ id: string; label: string }>;
  tasks: Array<{ id: string; label: string; schedule: string; section: string }>;
}

const IGNORED_FLOW_LINE = /^(?:%%|direction\b|classDef\b|class\b|style\b|linkStyle\b)/;

export function extractMermaidBlocks(markdown: string): MermaidBlock[] {
  const blocks: MermaidBlock[] = [];
  const expression = /```mermaid\s*\n([\s\S]*?)```/g;
  for (const match of markdown.matchAll(expression)) {
    const prefix = markdown.slice(0, match.index ?? 0);
    const headings = [...prefix.matchAll(/^#{1,6}\s+(.+)$/gm)];
    blocks.push({
      heading: headings.at(-1)?.[1]?.trim() ?? "Diagram",
      source: match[1]?.trim() ?? "",
    });
  }
  return blocks;
}

export function replaceMermaidBlocks(
  markdown: string,
  replacements: string[],
): string {
  let index = 0;
  const updated = markdown.replace(/```mermaid\s*\n[\s\S]*?```/g, () => {
    const replacement = replacements[index];
    index += 1;
    if (replacement === undefined) {
      throw new Error(`Missing Mermaid replacement ${index}`);
    }
    return replacement;
  });
  if (index !== replacements.length) {
    throw new Error(`Expected ${index} Mermaid replacements, received ${replacements.length}`);
  }
  return updated;
}

function cleanText(value: string): string {
  return value
    .trim()
    .replace(/^(["'])([\s\S]*)\1$/, "$2")
    .replace(/<br\s*\/?\s*>/giu, " / ")
    .replace(/<[^>]+>/gu, "")
    .replace(/\s+/gu, " ")
    .trim();
}

function parseEndpoint(value: string): ParsedEndpoint {
  const match = /^([A-Za-z0-9_.-]+)\s*([\s\S]*)$/.exec(value.trim().replace(/;$/, ""));
  if (!match) throw new Error(`Unsupported Mermaid endpoint: ${value}`);
  const id = match[1]!;
  const wrapper = match[2]?.trim() ?? "";
  if (!wrapper) return { id, label: id, kind: "process" };

  const shapes: Array<{
    expression: RegExp;
    kind: DiagramNode["kind"];
    shape?: DiagramNode["shape"];
  }> = [
    { expression: /^\[\(([\s\S]*)\)\]$/, kind: "store", shape: "database" },
    { expression: /^\(\(([\s\S]*)\)\)$/, kind: "process", shape: "circle" },
    { expression: /^\{([\s\S]*)\}$/, kind: "decision", shape: "diamond" },
    { expression: /^\[([\s\S]*)\]$/, kind: "process", shape: "card" },
    { expression: /^\(([\s\S]*)\)$/, kind: "process", shape: "terminator" },
  ];
  for (const candidate of shapes) {
    const shapeMatch = candidate.expression.exec(wrapper);
    if (!shapeMatch) continue;
    return {
      id,
      label: cleanText(shapeMatch[1] ?? id),
      kind: candidate.kind,
      ...(candidate.shape ? { shape: candidate.shape } : {}),
    };
  }
  throw new Error(`Unsupported Mermaid node shape: ${value}`);
}

function splitFlowEdge(line: string): {
  left: string;
  right: string;
  label: string;
  dotted: boolean;
} | null {
  const patterns: Array<{ expression: RegExp; dotted: boolean }> = [
    { expression: /^(.+?)\s*-->\|([^|]*)\|\s*(.+)$/, dotted: false },
    { expression: /^(.+?)\s*-\.\s*(.*?)\s*\.->\s*(.+)$/, dotted: true },
    { expression: /^(.+?)\s*-\.->\s*(.+)$/, dotted: true },
    { expression: /^(.+?)\s*--\s+(.+?)\s+-->\s*(.+)$/, dotted: false },
    { expression: /^(.+?)\s*(?:-->|==>)\s*(.+)$/, dotted: false },
  ];
  for (const candidate of patterns) {
    const match = candidate.expression.exec(line);
    if (!match) continue;
    const hasMiddle = match.length === 4;
    return {
      left: match[1]!.trim(),
      right: match[hasMiddle ? 3 : 2]!.trim(),
      label: cleanText(hasMiddle ? match[2] ?? "" : ""),
      dotted: candidate.dotted,
    };
  }
  return null;
}

function parseSubgraph(line: string): { id: string; label: string } | null {
  const match = /^subgraph\s+([A-Za-z0-9_.-]+)(?:\s*\[([\s\S]*)\]|\s+([\s\S]+))?$/i.exec(line);
  if (!match) return null;
  return { id: match[1]!, label: cleanText(match[2] ?? match[3] ?? match[1]!) };
}

export function parseFlowchart(source: string): ParsedFlow {
  const lines = source.split(/\r?\n/u).map((line) => line.trim()).filter(Boolean);
  const declaration = /^(?:flowchart|graph)\s+(LR|RL|TB|TD|BT)$/i.exec(lines.shift() ?? "");
  if (!declaration) throw new Error("Mermaid flow must start with flowchart or graph direction");
  const direction: Direction = ["LR", "RL"].includes(declaration[1]!.toUpperCase())
    ? "RIGHT"
    : "DOWN";
  const groups: ParsedFlow["groups"] = [];
  const nodes = new Map<string, ParsedEndpoint & { parent?: string }>();
  const edges: ParsedFlow["edges"] = [];
  const groupStack: string[] = [];

  const registerEndpoint = (endpoint: ParsedEndpoint): void => {
    if (groups.some((group) => group.id === endpoint.id)) return;
    const previous = nodes.get(endpoint.id);
    const parent = previous?.parent ?? groupStack.at(-1);
    nodes.set(endpoint.id, {
      ...(previous ?? endpoint),
      ...(endpoint.label !== endpoint.id ? endpoint : {}),
      ...(parent ? { parent } : {}),
    });
  };

  for (const line of lines) {
    if (IGNORED_FLOW_LINE.test(line)) continue;
    const subgraph = parseSubgraph(line);
    if (subgraph) {
      const parent = groupStack.at(-1);
      groups.push({ ...subgraph, ...(parent ? { parent } : {}) });
      groupStack.push(subgraph.id);
      continue;
    }
    if (/^end$/i.test(line)) {
      groupStack.pop();
      continue;
    }
    const chain = line.split(/\s*-->\s*/u);
    if (chain.length > 2 && !line.includes("|")) {
      const endpoints = chain.map(parseEndpoint);
      endpoints.forEach(registerEndpoint);
      for (let index = 1; index < endpoints.length; index += 1) {
        edges.push({
          from: endpoints[index - 1]!.id,
          to: endpoints[index]!.id,
          label: "",
          dotted: false,
        });
      }
      continue;
    }
    const bidirectional = /^(.+?)\s*<-->\s*(.+)$/u.exec(line);
    if (bidirectional) {
      const from = parseEndpoint(bidirectional[1]!);
      const to = parseEndpoint(bidirectional[2]!);
      registerEndpoint(from);
      registerEndpoint(to);
      edges.push(
        { from: from.id, to: to.id, label: "", dotted: false },
        { from: to.id, to: from.id, label: "", dotted: false },
      );
      continue;
    }
    const edge = splitFlowEdge(line);
    if (edge) {
      const from = parseEndpoint(edge.left);
      const to = parseEndpoint(edge.right);
      registerEndpoint(from);
      registerEndpoint(to);
      edges.push({ from: from.id, to: to.id, label: edge.label, dotted: edge.dotted });
      continue;
    }
    const standalone = parseEndpoint(line);
    if (standalone.label === standalone.id) {
      throw new Error(`Unsupported Mermaid flow line: ${line}`);
    }
    const parent = groupStack.at(-1);
    nodes.set(standalone.id, {
      ...standalone,
      ...(parent ? { parent } : {}),
    });
  }
  if (groupStack.length) throw new Error(`Unclosed Mermaid subgraph: ${groupStack.at(-1)}`);
  return { direction, groups, nodes: [...nodes.values()], edges };
}

export function parseSequence(source: string): ParsedSequence {
  const lines = source.split(/\r?\n/u).map((line) => line.trim()).filter(Boolean);
  if (lines.shift() !== "sequenceDiagram") {
    throw new Error("Mermaid sequence must start with sequenceDiagram");
  }
  const participants = new Map<string, string>();
  const steps: ParsedSequenceStep[] = [];
  const context: string[] = [];
  for (const line of lines) {
    if (line.startsWith("%%")) continue;
    const participant = /^(?:participant|actor)\s+([A-Za-z0-9_.-]+)(?:\s+as\s+(.+))?$/i.exec(line);
    if (participant) {
      participants.set(participant[1]!, cleanText(participant[2] ?? participant[1]!));
      continue;
    }
    const note = /^Note\s+(?:over|left of|right of)\s+[^:]+:\s*(.+)$/i.exec(line);
    if (note) {
      context.push(`Note: ${cleanText(note[1]!)}`);
      continue;
    }
    const control = /^(alt|opt|loop|par|critical|break|rect)\s*(.*)$/i.exec(line);
    if (control) {
      context.push(`${control[1]!.toLowerCase()}: ${cleanText(control[2] ?? "")}`.trim());
      continue;
    }
    const alternate = /^else\s*(.*)$/i.exec(line);
    if (alternate) {
      if (context.length) context.pop();
      context.push(`else: ${cleanText(alternate[1] ?? "")}`.trim());
      continue;
    }
    if (/^end$/i.test(line)) {
      context.pop();
      continue;
    }
    const message = /^([A-Za-z0-9_.-]+?)\s*-{1,2}(?:>>|>|x|\))\s*([A-Za-z0-9_.-]+)\s*:\s*(.+)$/u.exec(line);
    if (!message) throw new Error(`Unsupported Mermaid sequence line: ${line}`);
    participants.set(message[1]!, participants.get(message[1]!) ?? message[1]!);
    participants.set(message[2]!, participants.get(message[2]!) ?? message[2]!);
    steps.push({
      from: message[1]!,
      to: message[2]!,
      label: cleanText(message[3]!),
      context: [...context],
    });
  }
  if (!steps.length) throw new Error("Mermaid sequence requires at least one message");
  return { participants, steps };
}

export function parseTimeline(source: string): ParsedTimeline {
  const lines = source.split(/\r?\n/u).map((line) => line.trim()).filter(Boolean);
  if (lines.shift() !== "timeline") {
    throw new Error("Mermaid timeline must start with timeline");
  }
  let title = "Timeline";
  const entries: ParsedTimeline["entries"] = [];
  for (const line of lines) {
    if (line.startsWith("%%")) continue;
    const titleMatch = /^title\s+(.+)$/iu.exec(line);
    if (titleMatch) {
      title = cleanText(titleMatch[1]!);
      continue;
    }
    const [rawId, ...rawDetails] = line.split(":");
    const id = cleanText(rawId ?? "");
    const details = rawDetails.map(cleanText).filter(Boolean);
    if (!id || !details.length) throw new Error(`Unsupported Mermaid timeline line: ${line}`);
    entries.push({ id, details });
  }
  if (entries.length < 2) throw new Error("Mermaid timeline requires at least two entries");
  return { title, entries };
}

export function parseGantt(source: string): ParsedGantt {
  const lines = source.split(/\r?\n/u).map((line) => line.trim()).filter(Boolean);
  if (lines.shift() !== "gantt") throw new Error("Mermaid Gantt must start with gantt");
  let title = "Delivery timeline";
  const sections: ParsedGantt["sections"] = [];
  const tasks: ParsedGantt["tasks"] = [];
  let section = "delivery";
  for (const line of lines) {
    if (line.startsWith("%%") || /^(?:dateFormat|axisFormat|tickInterval)\b/iu.test(line)) continue;
    const titleMatch = /^title\s+(.+)$/iu.exec(line);
    if (titleMatch) {
      title = cleanText(titleMatch[1]!);
      continue;
    }
    const sectionMatch = /^section\s+(.+)$/iu.exec(line);
    if (sectionMatch) {
      const label = cleanText(sectionMatch[1]!);
      section = `section-${String(sections.length + 1).padStart(2, "0")}`;
      sections.push({ id: section, label });
      continue;
    }
    const taskMatch = /^(.+?)\s*:\s*([^,]+),\s*(.+)$/u.exec(line);
    if (!taskMatch) throw new Error(`Unsupported Mermaid Gantt line: ${line}`);
    tasks.push({
      id: cleanText(taskMatch[2]!),
      label: cleanText(taskMatch[1]!),
      schedule: cleanText(taskMatch[3]!),
      section,
    });
  }
  if (!tasks.length) throw new Error("Mermaid Gantt requires at least one task");
  return { title, sections, tasks };
}

function edgeKind(label: string, dotted: boolean): EdgeKind {
  if (dotted) return "dependency";
  const normalized = label.toLowerCase();
  if (normalized.includes("approval") || normalized.includes("approve")) return "approval";
  if (normalized.includes("audit")) return "audit";
  if (normalized.includes("rollback")) return "rollback";
  if (normalized.includes("event") || normalized.includes("signal")) return "event";
  if (normalized.includes("write") || normalized.includes("persist")) return "write";
  if (normalized.includes("read") || normalized.includes("query")) return "read";
  return "request";
}

function localizedAlt(title: string, labels: string[], locale: "en" | "ko"): string {
  const unique = [...new Set(labels)].slice(0, 12).join(", ");
  return locale === "ko"
    ? `${title}. 주요 단계는 ${unique}입니다.`
    : `${title}. The main stages are ${unique}.`;
}

function assertSameIds(kind: string, left: string[], right: string[]): void {
  if (left.join("\0") !== right.join("\0")) {
    throw new Error(`English and Korean ${kind} structure differs`);
  }
}

function normalizedIdMap(ids: string[]): Map<string, string> {
  const result = new Map<string, string>();
  const used = new Set<string>();
  for (const id of ids) {
    const normalized = id
      .toLowerCase()
      .replace(/[^a-z0-9]+/gu, "-")
      .replace(/^-+|-+$/gu, "") || "element";
    if (used.has(normalized)) {
      throw new Error(`Mermaid ids collide after normalization: ${id} -> ${normalized}`);
    }
    used.add(normalized);
    result.set(id, normalized);
  }
  return result;
}

function flowSpec(id: string, en: MermaidBlock, ko: MermaidBlock): DiagramSpec {
  const enFlow = parseFlowchart(en.source);
  const koFlow = parseFlowchart(ko.source);
  assertSameIds("group", enFlow.groups.map((group) => group.id), koFlow.groups.map((group) => group.id));
  assertSameIds("node", enFlow.nodes.map((node) => node.id), koFlow.nodes.map((node) => node.id));
  assertSameIds(
    "edge",
    enFlow.edges.map((edge) => `${edge.from}->${edge.to}`),
    koFlow.edges.map((edge) => `${edge.from}->${edge.to}`),
  );
  const normalizedIds = normalizedIdMap([
    ...enFlow.groups.map((group) => group.id),
    ...enFlow.nodes.map((node) => node.id),
  ]);
  const koGroups = new Map(koFlow.groups.map((group) => [group.id, group]));
  const koNodes = new Map(koFlow.nodes.map((node) => [node.id, node]));
  const labeledOutgoing = new Map<string, number>();
  for (const edge of enFlow.edges) {
    if (edge.label) labeledOutgoing.set(edge.from, (labeledOutgoing.get(edge.from) ?? 0) + 1);
  }
  const suppressEdgeLabels = enFlow.edges.filter((edge) => edge.label).length > 1;
  const targetConditions = new Map<string, { en: string[]; ko: string[] }>();
  enFlow.edges.forEach((edge, index) => {
    if (!edge.label || (!suppressEdgeLabels && (labeledOutgoing.get(edge.from) ?? 0) < 3)) return;
    const conditions = targetConditions.get(edge.to) ?? { en: [], ko: [] };
    conditions.en.push(`When: ${edge.label}`);
    conditions.ko.push(`조건: ${koFlow.edges[index]!.label || edge.label}`);
    targetConditions.set(edge.to, conditions);
  });
  const groups: DiagramGroup[] = enFlow.groups.map((group) => ({
    id: normalizedIds.get(group.id)!,
    ...(group.parent ? { parent: normalizedIds.get(group.parent)! } : {}),
    kind: "layer",
    presentation: "lane",
    label: { en: group.label, ko: koGroups.get(group.id)!.label },
    direction: enFlow.direction,
  }));
  const nodes: DiagramNode[] = enFlow.nodes.map((node) => ({
    id: normalizedIds.get(node.id)!,
    ...(node.parent ? { parent: normalizedIds.get(node.parent)! } : {}),
    kind: node.kind,
    ...(node.shape ? { shape: node.shape } : {}),
    label: { en: node.label, ko: koNodes.get(node.id)!.label },
    ...(targetConditions.has(node.id)
      ? {
          description: {
            en: targetConditions.get(node.id)!.en.join(" / "),
            ko: targetConditions.get(node.id)!.ko.join(" / "),
          },
        }
      : {}),
  }));
  const labelCounts = new Map<string, number>();
  for (const edge of enFlow.edges) {
    if (edge.label) labelCounts.set(edge.label, (labelCounts.get(edge.label) ?? 0) + 1);
  }
  const emittedLabels = new Set<string>();
  const edges: DiagramEdge[] = enFlow.edges.map((edge, index) => {
    const repeated = edge.label && (labelCounts.get(edge.label) ?? 0) > 1;
    const denseFanOut = (labeledOutgoing.get(edge.from) ?? 0) >= 3;
    const includeLabel = edge.label && !suppressEdgeLabels && !denseFanOut && (!repeated || !emittedLabels.has(edge.label));
    if (includeLabel) emittedLabels.add(edge.label);
    return {
      id: `flow-${String(index + 1).padStart(2, "0")}`,
      from: normalizedIds.get(edge.from)!,
      to: normalizedIds.get(edge.to)!,
      kind: edgeKind(edge.label, edge.dotted),
      ...(includeLabel
        ? { label: { en: edge.label, ko: koFlow.edges[index]!.label || "계속" } }
        : {}),
    };
  });
  return validateDiagram({
    id,
    version: 1,
    kind: "flowchart" satisfies DiagramKind,
    updated: "2026-08-20",
    formats: ["svg"],
    locales: {
      en: {
        title: en.heading,
        description: `FDAI flow for ${en.heading}.`,
        alt: localizedAlt(en.heading, enFlow.nodes.map((node) => node.label), "en"),
      },
      ko: {
        title: ko.heading,
        description: `${ko.heading}에 대한 FDAI 흐름입니다.`,
        alt: localizedAlt(ko.heading, koFlow.nodes.map((node) => node.label), "ko"),
      },
    },
    canvas: {
      width: Math.min(1600, Math.max(900, enFlow.nodes.length * 150)),
      height: Math.min(1200, Math.max(520, enFlow.nodes.length * 90)),
      direction: enFlow.direction,
    },
    groups,
    nodes,
    edges,
  });
}

function sequenceSpec(id: string, en: MermaidBlock, ko: MermaidBlock): DiagramSpec {
  const enSequence = parseSequence(en.source);
  const koSequence = parseSequence(ko.source);
  assertSameIds("participant", [...enSequence.participants.keys()], [...koSequence.participants.keys()]);
  assertSameIds(
    "sequence message",
    enSequence.steps.map((step) => `${step.from}->${step.to}`),
    koSequence.steps.map((step) => `${step.from}->${step.to}`),
  );
  const nodes: DiagramNode[] = enSequence.steps.map((step, index) => {
    const koStep = koSequence.steps[index]!;
    const enFrom = enSequence.participants.get(step.from) ?? step.from;
    const enTo = enSequence.participants.get(step.to) ?? step.to;
    const koFrom = koSequence.participants.get(koStep.from) ?? koStep.from;
    const koTo = koSequence.participants.get(koStep.to) ?? koStep.to;
    return {
      id: `step-${String(index + 1).padStart(2, "0")}`,
      kind: "process",
      badge: index + 1,
      label: { en: `${enFrom} -> ${enTo}`, ko: `${koFrom} -> ${koTo}` },
      description: {
        en: [...step.context, step.label].filter(Boolean).join(" / "),
        ko: [...koStep.context, koStep.label].filter(Boolean).join(" / "),
      },
    };
  });
  const edges: DiagramEdge[] = nodes.slice(1).map((node, index) => ({
    id: `sequence-${String(index + 1).padStart(2, "0")}`,
    from: nodes[index]!.id,
    to: node.id,
    kind: "sequence",
  }));
  return validateDiagram({
    id,
    version: 1,
    kind: "sequence" satisfies DiagramKind,
    updated: "2026-08-20",
    formats: ["svg"],
    locales: {
      en: {
        title: en.heading,
        description: `Ordered FDAI interactions for ${en.heading}.`,
        alt: localizedAlt(en.heading, enSequence.steps.map((step) => step.label), "en"),
      },
      ko: {
        title: ko.heading,
        description: `${ko.heading}에 대한 순서가 있는 FDAI 상호 작용입니다.`,
        alt: localizedAlt(ko.heading, koSequence.steps.map((step) => step.label), "ko"),
      },
    },
    canvas: {
      width: 1100,
      height: Math.min(1200, Math.max(520, nodes.length * 110)),
      direction: "DOWN",
    },
    groups: [],
    nodes,
    edges,
  });
}

function timelineSpec(id: string, en: MermaidBlock, ko: MermaidBlock): DiagramSpec {
  const enTimeline = parseTimeline(en.source);
  const koTimeline = parseTimeline(ko.source);
  assertSameIds(
    "timeline entry",
    enTimeline.entries.map((entry) => entry.id),
    koTimeline.entries.map((entry) => entry.id),
  );
  const ids = normalizedIdMap(enTimeline.entries.map((entry) => entry.id));
  const nodes: DiagramNode[] = enTimeline.entries.map((entry, index) => ({
    id: ids.get(entry.id)!,
    kind: "process",
    label: { en: entry.id, ko: koTimeline.entries[index]!.id },
    description: {
      en: entry.details.join(" / "),
      ko: koTimeline.entries[index]!.details.join(" / "),
    },
  }));
  const edges: DiagramEdge[] = nodes.slice(1).map((node, index) => ({
    id: `timeline-${String(index + 1).padStart(2, "0")}`,
    from: nodes[index]!.id,
    to: node.id,
    kind: "timeline",
  }));
  return validateDiagram({
    id,
    version: 1,
    kind: "timeline" satisfies DiagramKind,
    updated: "2026-08-20",
    formats: ["svg"],
    locales: {
      en: {
        title: enTimeline.title,
        description: `Ordered FDAI delivery waves for ${en.heading}.`,
        alt: localizedAlt(en.heading, enTimeline.entries.map((entry) => `${entry.id}: ${entry.details.join(", ")}`), "en"),
      },
      ko: {
        title: koTimeline.title,
        description: `${ko.heading}에 대한 순서가 있는 FDAI delivery wave입니다.`,
        alt: localizedAlt(ko.heading, koTimeline.entries.map((entry) => `${entry.id}: ${entry.details.join(", ")}`), "ko"),
      },
    },
    canvas: {
      width: 1600,
      height: 640,
      direction: "RIGHT",
    },
    groups: [],
    nodes,
    edges,
  });
}

function ganttSpec(id: string, en: MermaidBlock, ko: MermaidBlock): DiagramSpec {
  const enGantt = parseGantt(en.source);
  const koGantt = parseGantt(ko.source);
  assertSameIds("Gantt section", enGantt.sections.map((section) => section.id), koGantt.sections.map((section) => section.id));
  assertSameIds("Gantt task", enGantt.tasks.map((task) => task.id), koGantt.tasks.map((task) => task.id));
  const normalizedIds = normalizedIdMap(enGantt.tasks.map((task) => task.id));
  const groups: DiagramGroup[] = enGantt.sections.map((section, index) => ({
    id: section.id,
    kind: "layer",
    presentation: "lane",
    label: { en: section.label, ko: koGantt.sections[index]!.label },
    direction: "RIGHT",
  }));
  const nodes: DiagramNode[] = enGantt.tasks.map((task, index) => ({
    id: normalizedIds.get(task.id)!,
    parent: task.section,
    kind: "process",
    badge: index + 1,
    label: { en: task.label, ko: koGantt.tasks[index]!.label },
    description: {
      en: task.schedule,
      ko: koGantt.tasks[index]!.schedule,
    },
  }));
  const edges: DiagramEdge[] = nodes.slice(1).map((node, index) => ({
    id: `gantt-${String(index + 1).padStart(2, "0")}`,
    from: nodes[index]!.id,
    to: node.id,
    kind: "timeline",
  }));
  return validateDiagram({
    id,
    version: 1,
    kind: "timeline" satisfies DiagramKind,
    updated: "2026-08-20",
    formats: ["svg"],
    locales: {
      en: {
        title: enGantt.title,
        description: `Sequenced FDAI delivery tasks for ${en.heading}.`,
        alt: localizedAlt(en.heading, enGantt.tasks.map((task) => task.label), "en"),
      },
      ko: {
        title: koGantt.title,
        description: `${ko.heading}에 대한 순차 FDAI delivery task입니다.`,
        alt: localizedAlt(ko.heading, koGantt.tasks.map((task) => task.label), "ko"),
      },
    },
    canvas: {
      width: 1600,
      height: Math.min(1400, Math.max(720, enGantt.sections.length * 250)),
      direction: "RIGHT",
    },
    groups,
    nodes,
    edges,
  });
}

export function convertMermaidPair(
  id: string,
  en: MermaidBlock,
  ko: MermaidBlock,
): DiagramSpec {
  const firstLine = en.source.split(/\r?\n/u, 1)[0] ?? "";
  const koFirstLine = ko.source.split(/\r?\n/u, 1)[0] ?? "";
  if (firstLine !== koFirstLine) throw new Error(`English and Korean diagram kinds differ for ${id}`);
  if (/^(?:flowchart|graph)\b/u.test(firstLine)) return flowSpec(id, en, ko);
  if (firstLine === "sequenceDiagram") return sequenceSpec(id, en, ko);
  if (firstLine === "timeline") return timelineSpec(id, en, ko);
  if (firstLine === "gantt") return ganttSpec(id, en, ko);
  throw new Error(`Unsupported Mermaid diagram kind for ${id}: ${firstLine}`);
}
