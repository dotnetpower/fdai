import type {
  AnswerVerification,
  PresentationArtifact,
  PresentationAssembly,
  PresentationAssemblyInputKind,
  PresentationBlock,
  PresentationChartItem,
  PresentationColumn,
  PresentationEmphasis,
  PresentationTableData,
  PresentationSummaryItem,
  PresentationLayout,
  PresentationTone,
} from "./backend-types";

const MAX_BLOCKS = 8;
const MAX_REFS = 8;
const MAX_REF_CHARS = 1024;
const MAX_TEXT_CHARS = 512;
const MAX_COLUMNS = 6;
const MAX_ROWS = 40;
const MAX_ITEMS = 16;
const SLOT_ID = /^[a-z][a-z0-9_]{0,63}$/;
const COLUMN_KEY = /^[a-z][a-z0-9_]{0,63}$/;
const EMPHASES = new Set<PresentationEmphasis>(["primary", "secondary", "supporting"]);
const TONES = new Set<PresentationTone>(["neutral", "positive", "attention", "warning"]);
const COMPARISON_ROLES = new Set(["baseline", "current", "target", "before", "after"]);
const LAYOUTS = new Set<PresentationLayout>([
  "stack",
  "operational_brief",
  "markdown_document",
]);
const ASSEMBLY_INPUT_KINDS: readonly PresentationAssemblyInputKind[] = [
  "verified_semantic_result",
  "presentation_context",
  "incident_projection",
  "operator_locale",
];
const ASSEMBLY_DIGEST = /^sha256:[0-9a-f]{64}$/;
const RFC3339 = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/;
const SLOT_KINDS: Readonly<Record<string, ReadonlySet<PresentationBlock["kind"]>>> = {
  overview: new Set(["summary"]),
  root_cause: new Set(["summary"]),
  impact: new Set(["table"]),
  citations: new Set(["table"]),
  limitations: new Set(["callout"]),
  findings: new Set(["table", "list"]),
  coverage: new Set(["coverage", "table"]),
  metrics: new Set(["threshold_table", "table"]),
  evidence: new Set(["evidence"]),
  records: new Set(["table", "list"]),
  distribution: new Set(["bar", "table"]),
  trend: new Set(["time_series", "table"]),
  comparison: new Set(["comparison", "table"]),
  timeline: new Set(["timeline", "table", "list"]),
  correlation: new Set(["scatter", "table"]),
  matrix: new Set(["heatmap", "table"]),
};
const V1_KINDS = new Set<PresentationBlock["kind"]>([
  "summary", "callout", "table", "threshold_table", "list", "coverage", "bar", "evidence",
]);

export function parsePresentationArtifact(
  raw: unknown,
  verification: AnswerVerification | undefined,
): PresentationArtifact | undefined {
  if (!verification || !isRecord(raw)) return undefined;
  const schemaVersion = raw.schema_version;
  if (
    (schemaVersion !== 1 && schemaVersion !== 2 && schemaVersion !== 3) ||
    !hasExactKeys(
      raw,
      schemaVersion === 3
        ? ["schema_version", "layout", "blocks", "evidence_refs", "assembly"]
        : ["schema_version", "layout", "blocks", "evidence_refs"],
    ) ||
    typeof raw.layout !== "string" ||
    !LAYOUTS.has(raw.layout as PresentationLayout) ||
    (schemaVersion !== 3 && raw.layout !== "stack") ||
      !Array.isArray(raw.blocks) || raw.blocks.length === 0 || raw.blocks.length > MAX_BLOCKS) {
    return undefined;
  }
  const layout = raw.layout as PresentationLayout;
  const assembly = schemaVersion === 3
    ? parseAssembly(raw.assembly, raw.blocks.length)
    : undefined;
  if (schemaVersion === 3 && !assembly) return undefined;
  const verificationRefs = new Set(verification.evidence_refs);
  const evidenceRefs = parseRefs(raw.evidence_refs, verificationRefs);
  if (!evidenceRefs) return undefined;
  const slots = new Set<string>();
  const blocks: PresentationBlock[] = [];
  for (const rawBlock of raw.blocks) {
    const block = parseBlock(rawBlock, new Set(evidenceRefs), schemaVersion);
    if (!block || slots.has(block.slotId)) return undefined;
    slots.add(block.slotId);
    blocks.push(block);
  }
  return {
    schemaVersion,
    layout,
    blocks,
    evidenceRefs,
    ...(assembly ? { assembly } : {}),
  };
}

/**
 * An artifact that only restates an overview carries less than the answer text it
 * would replace, so the reply keeps the markdown instead.
 */
export function presentationArtifactSupersedesText(artifact: PresentationArtifact): boolean {
  return artifact.blocks.some((block) => block.slotId !== "overview");
}

export function presentationArtifactToWire(artifact: PresentationArtifact): Record<string, unknown> {  return {
    schema_version: artifact.schemaVersion,
    layout: artifact.layout,
    evidence_refs: [...artifact.evidenceRefs],
    blocks: artifact.blocks.map((block) => ({
      slot_id: block.slotId,
      kind: block.kind,
      title: block.title,
      emphasis: block.emphasis,
      collapsed: block.collapsed,
      evidence_refs: [...block.evidenceRefs],
      data: blockDataToWire(block),
    })),
    ...(artifact.assembly ? {
      assembly: {
        mode: artifact.assembly.mode,
        label: artifact.assembly.label,
        section_count: artifact.assembly.sectionCount,
        input_kinds: [...artifact.assembly.inputKinds],
        digest: artifact.assembly.digest,
      },
    } : {}),
  };
}

export function parsePersistedPresentationArtifact(
  raw: unknown,
  verification: AnswerVerification | undefined,
): PresentationArtifact | undefined {
  if (!isRecord(raw)) return undefined;
  if ("schema_version" in raw) return parsePresentationArtifact(raw, verification);
  if (!Array.isArray(raw.blocks) || !Array.isArray(raw.evidenceRefs)) return undefined;
  const blocks: Record<string, unknown>[] = [];
  for (const rawBlock of raw.blocks) {
    if (!isRecord(rawBlock) || !isRecord(rawBlock.data)) return undefined;
    const data = persistedDataToWire(rawBlock.kind, rawBlock.data);
    if (!data) return undefined;
    blocks.push({
      slot_id: rawBlock.slotId,
      kind: rawBlock.kind,
      title: rawBlock.title,
      emphasis: rawBlock.emphasis,
      collapsed: rawBlock.collapsed,
      evidence_refs: rawBlock.evidenceRefs,
      data,
    });
  }
  return parsePresentationArtifact({
    schema_version: raw.schemaVersion,
    layout: raw.layout,
    blocks,
    evidence_refs: raw.evidenceRefs,
    ...(raw.assembly && isRecord(raw.assembly) ? {
      assembly: {
        mode: raw.assembly.mode,
        label: raw.assembly.label,
        section_count: raw.assembly.sectionCount,
        input_kinds: raw.assembly.inputKinds,
        digest: raw.assembly.digest,
      },
    } : {}),
  }, verification);
}

function parseBlock(
  raw: unknown,
  artifactRefs: ReadonlySet<string>,
  schemaVersion: 1 | 2 | 3,
): PresentationBlock | null {
  if (!isRecord(raw) || !hasExactKeys(
    raw,
    ["slot_id", "kind", "title", "emphasis", "collapsed", "evidence_refs", "data"],
  )) return null;
  const slotId = text(raw.slot_id, 64);
  const title = text(raw.title);
  const emphasis = raw.emphasis;
  const collapsed = raw.collapsed;
  const evidenceRefs = parseRefs(raw.evidence_refs, artifactRefs);
  if (!slotId || !SLOT_ID.test(slotId) || !title ||
      !EMPHASES.has(emphasis as PresentationEmphasis) || typeof collapsed !== "boolean" ||
      !evidenceRefs || !isRecord(raw.data)) return null;
  const allowedKinds = SLOT_KINDS[slotId];
  if (!allowedKinds || typeof raw.kind !== "string" ||
      !allowedKinds.has(raw.kind as PresentationBlock["kind"])) return null;
  if (schemaVersion === 1 && !V1_KINDS.has(raw.kind as PresentationBlock["kind"])) return null;
  const base = {
    slotId,
    title,
    emphasis: emphasis as PresentationEmphasis,
    collapsed,
    evidenceRefs,
  };
  if (raw.kind === "summary") {
    const items = parseSummaryItems(raw.data);
    return items ? { ...base, kind: "summary", data: { items } } : null;
  }
  if (raw.kind === "callout") {
    const tone = raw.data.tone;
    const lines = parseTextArray(raw.data.lines);
    return TONES.has(tone as PresentationTone) && lines
      ? { ...base, kind: "callout", data: { tone: tone as PresentationTone, lines } }
      : null;
  }
  if (raw.kind === "table" || raw.kind === "threshold_table" || raw.kind === "list") {
    const table = parseTable(raw.data);
    return table ? { ...base, kind: raw.kind, data: table } : null;
  }
  if (raw.kind === "coverage" || raw.kind === "bar") {
    if (schemaVersion === 1) {
      const items = parseChartItems(raw.data, true);
      if (!items) return null;
      return raw.kind === "bar"
        ? { ...base, kind: "bar", data: { items } }
        : { ...base, kind: "coverage", data: { items } };
    }
    if (raw.kind === "bar") {
      const data = parseAccessibleBar(raw.data);
      return data ? { ...base, kind: "bar", data } : null;
    }
    const data = parseAccessibleCoverage(raw.data);
    return data ? { ...base, kind: "coverage", data } : null;
  }
  if (raw.kind === "time_series") {
    const data = schemaVersion >= 2 ? parseTimeSeries(raw.data) : null;
    return data ? { ...base, kind: "time_series", data } : null;
  }
  if (raw.kind === "comparison") {
    const data = schemaVersion >= 2 ? parseComparison(raw.data) : null;
    return data ? { ...base, kind: "comparison", data } : null;
  }
  if (raw.kind === "timeline") {
    const data = schemaVersion >= 2 ? parseTimeline(raw.data) : null;
    return data ? { ...base, kind: "timeline", data } : null;
  }
  if (raw.kind === "scatter") {
    const data = schemaVersion >= 2 ? parseScatter(raw.data) : null;
    return data ? { ...base, kind: "scatter", data } : null;
  }
  if (raw.kind === "heatmap") {
    const data = schemaVersion >= 2 ? parseHeatmap(raw.data) : null;
    return data ? { ...base, kind: "heatmap", data } : null;
  }
  if (raw.kind === "evidence") {
    const items = parseLabelValues(raw.data);
    return items ? { ...base, kind: "evidence", data: { items } } : null;
  }
  return null;
}

function parseAssembly(raw: unknown, blockCount: number): PresentationAssembly | null {
  if (!isRecord(raw) || !hasExactKeys(
    raw,
    ["mode", "label", "section_count", "input_kinds", "digest"],
  )) return null;
  const label = text(raw.label, 128);
  const digest = typeof raw.digest === "string" && ASSEMBLY_DIGEST.test(raw.digest)
    ? raw.digest
    : null;
  if (
    raw.mode !== "dynamic" ||
    !label ||
    raw.section_count !== blockCount ||
    !Array.isArray(raw.input_kinds) ||
    raw.input_kinds.length === 0 ||
    raw.input_kinds.length > ASSEMBLY_INPUT_KINDS.length ||
    !digest
  ) return null;
  const inputKinds: PresentationAssemblyInputKind[] = [];
  let previousPosition = -1;
  for (const value of raw.input_kinds) {
    const position = typeof value === "string"
      ? ASSEMBLY_INPUT_KINDS.indexOf(value as PresentationAssemblyInputKind)
      : -1;
    if (
      position <= previousPosition ||
      inputKinds.includes(value as PresentationAssemblyInputKind)
    ) return null;
    inputKinds.push(value as PresentationAssemblyInputKind);
    previousPosition = position;
  }
  return {
    mode: "dynamic",
    label,
    sectionCount: blockCount,
    inputKinds,
    digest,
  };
}

function parseSummaryItems(data: Record<string, unknown>): PresentationSummaryItem[] | null {
  if (!hasExactKeys(data, ["items"]) || !Array.isArray(data.items) ||
      data.items.length === 0 || data.items.length > MAX_ITEMS) return null;
  const items: PresentationSummaryItem[] = [];
  const labels = new Set<string>();
  for (const rawItem of data.items) {
    if (!isRecord(rawItem) || !hasExactKeys(rawItem, ["label", "value", "tone"])) return null;
    const label = text(rawItem.label);
    const value = text(rawItem.value);
    const tone = rawItem.tone;
    if (!label || !value || labels.has(label) || !TONES.has(tone as PresentationTone)) return null;
    labels.add(label);
    items.push({ label, value, tone: tone as PresentationTone });
  }
  return items;
}

function parseChartItems(
  data: Record<string, unknown>,
  integersOnly: boolean,
): PresentationChartItem[] | null {
  if (!hasExactKeys(data, ["items"]) || !Array.isArray(data.items) ||
      data.items.length === 0 || data.items.length > MAX_ITEMS) return null;
  const items: PresentationChartItem[] = [];
  const labels = new Set<string>();
  for (const rawItem of data.items) {
    if (!isRecord(rawItem) || !hasExactKeys(rawItem, ["label", "value", "tone"])) return null;
    const label = text(rawItem.label);
    const value = rawItem.value;
    const tone = rawItem.tone;
    if (!label || labels.has(label) || !finiteNumber(value) || (value as number) < 0 ||
      (integersOnly && !Number.isSafeInteger(value)) ||
        !TONES.has(tone as PresentationTone)) return null;
    labels.add(label);
    items.push({ label, value: value as number, tone: tone as PresentationTone });
  }
  return items;
}

function parseAccessibleBar(data: Record<string, unknown>) {
  if (!hasLegacyOrVisualizedKeys(data, ["description", "unit", "items", "exact_table"])) return null;
  const description = text(data.description);
  const unit = text(data.unit, 64);
  const items = parseChartItems({ items: data.items }, false);
  const exactTable = isRecord(data.exact_table) ? parseTable(data.exact_table) : null;
  const visualization = chartVisualization(data.visualization, ["bar", "bar_list", "donut"]);
  return description && unit && items && exactTable && visualization !== null
    ? { description, unit, items, exactTable, ...(visualization ? { visualization } : {}) }
    : null;
}

function parseAccessibleCoverage(data: Record<string, unknown>) {
  if (!hasLegacyOrVisualizedKeys(data, ["description", "unit", "items", "exact_table"]) ||
      !Array.isArray(data.items) || data.items.length === 0 || data.items.length > MAX_ITEMS) {
    return null;
  }
  const description = text(data.description);
  const unit = text(data.unit, 64);
  const exactTable = isRecord(data.exact_table) ? parseTable(data.exact_table) : null;
  const items: { label: string; value: number; total: number; tone: PresentationTone }[] = [];
  const labels = new Set<string>();
  for (const rawItem of data.items) {
    if (!isRecord(rawItem) || !hasExactKeys(rawItem, ["label", "value", "total", "tone"])) {
      return null;
    }
    const label = text(rawItem.label);
    if (!label || labels.has(label) || !finiteNumber(rawItem.value) ||
        !finiteNumber(rawItem.total) || (rawItem.total as number) <= 0 ||
        (rawItem.value as number) < 0 || (rawItem.value as number) > (rawItem.total as number) ||
        !TONES.has(rawItem.tone as PresentationTone)) return null;
    labels.add(label);
    items.push({
      label,
      value: rawItem.value as number,
      total: rawItem.total as number,
      tone: rawItem.tone as PresentationTone,
    });
  }
  const visualization = chartVisualization(data.visualization, ["category_bar"]);
  return description && unit && exactTable && visualization !== null
    ? { description, unit, items, exactTable, ...(visualization ? { visualization } : {}) }
    : null;
}

function parseTimeSeries(data: Record<string, unknown>) {
  if (!hasLegacyOrVisualizedKeys(data, ["description", "metric", "unit", "points", "exact_table"]) ||
      !Array.isArray(data.points) || data.points.length < 3 || data.points.length > MAX_ROWS) {
    return null;
  }
  const description = text(data.description);
  const metric = text(data.metric);
  const unit = text(data.unit, 64);
  const exactTable = isRecord(data.exact_table) ? parseTable(data.exact_table) : null;
  const points: { timestamp: string; value: number }[] = [];
  for (const rawPoint of data.points) {
    if (!isRecord(rawPoint) || !hasExactKeys(rawPoint, ["timestamp", "value"])) return null;
    const timestamp = rfc3339(rawPoint.timestamp);
    if (!timestamp || !finiteNumber(rawPoint.value)) return null;
    points.push({ timestamp, value: rawPoint.value as number });
  }
  if (!timestampsStrictlyIncrease(points.map((point) => point.timestamp))) return null;
  const visualization = chartVisualization(data.visualization, ["area", "line"]);
  return description && metric && unit && exactTable && visualization !== null
    ? { description, metric, unit, points, exactTable, ...(visualization ? { visualization } : {}) }
    : null;
}

function parseComparison(data: Record<string, unknown>) {
  if (!hasLegacyOrVisualizedKeys(data, ["description", "metric", "unit", "items", "exact_table"]) ||
      !Array.isArray(data.items) || data.items.length < 2 || data.items.length > 5) return null;
  const description = text(data.description);
  const metric = text(data.metric);
  const unit = text(data.unit, 64);
  const exactTable = isRecord(data.exact_table) ? parseTable(data.exact_table) : null;
  const roles = new Set<string>();
  const items: { role: "baseline" | "current" | "target" | "before" | "after"; label: string; value: number }[] = [];
  for (const rawItem of data.items) {
    if (!isRecord(rawItem) || !hasExactKeys(rawItem, ["role", "label", "value"]) ||
        typeof rawItem.role !== "string" || !COMPARISON_ROLES.has(rawItem.role) ||
        roles.has(rawItem.role) || !finiteNumber(rawItem.value)) return null;
    const label = text(rawItem.label);
    if (!label) return null;
    roles.add(rawItem.role);
    items.push({ role: rawItem.role as typeof items[number]["role"], label, value: rawItem.value as number });
  }
  const visualization = chartVisualization(data.visualization, ["comparison_bar"]);
  return description && metric && unit && exactTable && visualization !== null
    ? { description, metric, unit, items, exactTable, ...(visualization ? { visualization } : {}) }
    : null;
}

function parseTimeline(data: Record<string, unknown>) {
  if (!hasLegacyOrVisualizedKeys(data, ["description", "items", "exact_table"]) ||
      !Array.isArray(data.items) || data.items.length < 2 || data.items.length > MAX_ROWS) return null;
  const description = text(data.description);
  const exactTable = isRecord(data.exact_table) ? parseTable(data.exact_table) : null;
  const items: { timestamp: string; label: string }[] = [];
  for (const rawItem of data.items) {
    if (!isRecord(rawItem) || !hasExactKeys(rawItem, ["timestamp", "label"])) return null;
    const timestamp = rfc3339(rawItem.timestamp);
    const label = text(rawItem.label);
    if (!timestamp || !label) return null;
    items.push({ timestamp, label });
  }
  if (!timestampsStrictlyIncrease(items.map((item) => item.timestamp))) return null;
  const visualization = chartVisualization(data.visualization, ["tracker"]);
  return description && exactTable && visualization !== null
    ? { description, items, exactTable, ...(visualization ? { visualization } : {}) }
    : null;
}

function parseScatter(data: Record<string, unknown>) {
  if (!hasExactKeys(data, ["description", "x_label", "y_label", "points", "exact_table"]) ||
      !Array.isArray(data.points) || data.points.length < 2 || data.points.length > MAX_ROWS) return null;
  const description = text(data.description);
  const xLabel = text(data.x_label);
  const yLabel = text(data.y_label);
  const exactTable = isRecord(data.exact_table) ? parseTable(data.exact_table) : null;
  const points: { label: string; x: number; y: number }[] = [];
  for (const rawPoint of data.points) {
    if (!isRecord(rawPoint) || !hasExactKeys(rawPoint, ["label", "x", "y"]) ||
        !finiteNumber(rawPoint.x) || !finiteNumber(rawPoint.y)) return null;
    const label = text(rawPoint.label);
    if (!label) return null;
    points.push({ label, x: rawPoint.x as number, y: rawPoint.y as number });
  }
  return description && xLabel && yLabel && exactTable
    ? { description, xLabel, yLabel, points, exactTable }
    : null;
}

function parseHeatmap(data: Record<string, unknown>) {
  if (!hasExactKeys(data, ["description", "row_label", "column_label", "cells", "exact_table"]) ||
      !Array.isArray(data.cells) || data.cells.length < 2 || data.cells.length > MAX_ROWS) return null;
  const description = text(data.description);
  const rowLabel = text(data.row_label);
  const columnLabel = text(data.column_label);
  const exactTable = isRecord(data.exact_table) ? parseTable(data.exact_table) : null;
  const cells: { row: string; column: string; value: number }[] = [];
  const coordinates = new Set<string>();
  for (const rawCell of data.cells) {
    if (!isRecord(rawCell) || !hasExactKeys(rawCell, ["row", "column", "value"]) ||
        !finiteNumber(rawCell.value)) return null;
    const row = text(rawCell.row);
    const column = text(rawCell.column);
    if (!row || !column || coordinates.has(`${row}\u0000${column}`)) return null;
    coordinates.add(`${row}\u0000${column}`);
    cells.push({ row, column, value: rawCell.value as number });
  }
  return description && rowLabel && columnLabel && exactTable
    ? { description, rowLabel, columnLabel, cells, exactTable }
    : null;
}

function parseTable(data: Record<string, unknown>): {
  readonly columns: readonly PresentationColumn[];
  readonly rows: readonly Readonly<Record<string, string>>[];
  readonly statusKey: string | null;
} | null {
  if (!hasExactKeys(data, ["columns", "rows", "status_key"]) ||
      !Array.isArray(data.columns) || data.columns.length === 0 ||
      data.columns.length > MAX_COLUMNS || !Array.isArray(data.rows) ||
      data.rows.length === 0 || data.rows.length > MAX_ROWS) return null;
  const columns: PresentationColumn[] = [];
  const keys = new Set<string>();
  for (const rawColumn of data.columns) {
    if (!isRecord(rawColumn) || !hasExactKeys(rawColumn, ["key", "label"])) return null;
    const key = text(rawColumn.key, 64);
    const label = text(rawColumn.label);
    if (!key || !COLUMN_KEY.test(key) || !label || keys.has(key)) return null;
    keys.add(key);
    columns.push({ key, label });
  }
  const statusKey = data.status_key === null ? null : text(data.status_key, 64);
  if (data.status_key !== null && (!statusKey || !keys.has(statusKey))) return null;
  const rows: Readonly<Record<string, string>>[] = [];
  for (const rawRow of data.rows) {
    if (!isRecord(rawRow) || Object.keys(rawRow).length !== keys.size ||
        Object.keys(rawRow).some((key) => !keys.has(key))) return null;
    const row: Record<string, string> = {};
    for (const key of keys) {
      const value = text(rawRow[key]);
      if (value === null) return null;
      row[key] = value;
    }
    rows.push(row);
  }
  return { columns, rows, statusKey };
}

function tableDataToWire(data: PresentationTableData): Record<string, unknown> {
  return {
    columns: data.columns.map((column) => ({ ...column })),
    rows: data.rows.map((row) => ({ ...row })),
    status_key: data.statusKey,
  };
}

function blockDataToWire(block: PresentationBlock): Record<string, unknown> {
  if (block.kind === "table" || block.kind === "threshold_table" || block.kind === "list") {
    return tableDataToWire(block.data);
  }
  if (block.kind === "callout") return { tone: block.data.tone, lines: [...block.data.lines] };
  if (block.kind === "time_series") return {
    description: block.data.description,
    metric: block.data.metric,
    unit: block.data.unit,
    ...(block.data.visualization ? { visualization: block.data.visualization } : {}),
    points: block.data.points.map((point) => ({ ...point })),
    exact_table: tableDataToWire(block.data.exactTable),
  };
  if (block.kind === "comparison") return {
    description: block.data.description,
    metric: block.data.metric,
    unit: block.data.unit,
    ...(block.data.visualization ? { visualization: block.data.visualization } : {}),
    items: block.data.items.map((item) => ({ ...item })),
    exact_table: tableDataToWire(block.data.exactTable),
  };
  if (block.kind === "timeline") return {
    description: block.data.description,
    ...(block.data.visualization ? { visualization: block.data.visualization } : {}),
    items: block.data.items.map((item) => ({ ...item })),
    exact_table: tableDataToWire(block.data.exactTable),
  };
  if (block.kind === "scatter") return {
    description: block.data.description,
    x_label: block.data.xLabel,
    y_label: block.data.yLabel,
    points: block.data.points.map((point) => ({ ...point })),
    exact_table: tableDataToWire(block.data.exactTable),
  };
  if (block.kind === "heatmap") return {
    description: block.data.description,
    row_label: block.data.rowLabel,
    column_label: block.data.columnLabel,
    cells: block.data.cells.map((cell) => ({ ...cell })),
    exact_table: tableDataToWire(block.data.exactTable),
  };
  if ((block.kind === "bar" || block.kind === "coverage") && "description" in block.data) {
    return {
      description: block.data.description,
      unit: block.data.unit,
      ...(block.data.visualization ? { visualization: block.data.visualization } : {}),
      items: block.data.items.map((item) => ({ ...item })),
      exact_table: tableDataToWire(block.data.exactTable),
    };
  }
  return { items: block.data.items.map((item) => ({ ...item })) };
}

function persistedDataToWire(kind: unknown, data: Record<string, unknown>): Record<string, unknown> | null {
  if (kind === "table" || kind === "threshold_table" || kind === "list") {
    return { columns: data.columns, rows: data.rows, status_key: data.statusKey };
  }
  if (kind === "time_series") return {
    description: data.description,
    metric: data.metric,
    unit: data.unit,
    ...("visualization" in data ? { visualization: data.visualization } : {}),
    points: data.points,
    exact_table: persistedTableToWire(data.exactTable),
  };
  if (kind === "comparison") return {
    description: data.description,
    metric: data.metric,
    unit: data.unit,
    ...("visualization" in data ? { visualization: data.visualization } : {}),
    items: data.items,
    exact_table: persistedTableToWire(data.exactTable),
  };
  if (kind === "timeline") return {
    description: data.description,
    ...("visualization" in data ? { visualization: data.visualization } : {}),
    items: data.items,
    exact_table: persistedTableToWire(data.exactTable),
  };
  if (kind === "scatter") return {
    description: data.description,
    x_label: data.xLabel,
    y_label: data.yLabel,
    points: data.points,
    exact_table: persistedTableToWire(data.exactTable),
  };
  if (kind === "heatmap") return {
    description: data.description,
    row_label: data.rowLabel,
    column_label: data.columnLabel,
    cells: data.cells,
    exact_table: persistedTableToWire(data.exactTable),
  };
  if ((kind === "bar" || kind === "coverage") && "description" in data) return {
    description: data.description,
    unit: data.unit,
    ...("visualization" in data ? { visualization: data.visualization } : {}),
    items: data.items,
    exact_table: persistedTableToWire(data.exactTable),
  };
  return { ...data };
}

function persistedTableToWire(raw: unknown): Record<string, unknown> | null {
  if (!isRecord(raw)) return null;
  return { columns: raw.columns, rows: raw.rows, status_key: raw.statusKey };
}

function parseLabelValues(data: Record<string, unknown>): { label: string; value: string }[] | null {
  if (!hasExactKeys(data, ["items"]) || !Array.isArray(data.items) ||
      data.items.length === 0 || data.items.length > MAX_ITEMS) return null;
  const items: { label: string; value: string }[] = [];
  const labels = new Set<string>();
  for (const rawItem of data.items) {
    if (!isRecord(rawItem) || !hasExactKeys(rawItem, ["label", "value"])) return null;
    const label = text(rawItem.label);
    const value = text(rawItem.value);
    if (!label || value === null || labels.has(label)) return null;
    labels.add(label);
    items.push({ label, value });
  }
  return items;
}

function parseTextArray(raw: unknown): string[] | null {
  if (!Array.isArray(raw) || raw.length === 0 || raw.length > MAX_ITEMS) return null;
  const values = raw.map((value) => text(value));
  if (!values.every((value): value is string => value !== null && value.length > 0)) return null;
  return new Set(values).size === values.length ? values : null;
}

function parseRefs(raw: unknown, allowed: ReadonlySet<string>): string[] | null {
  if (!Array.isArray(raw) || raw.length === 0 || raw.length > MAX_REFS) return null;
  const refs: string[] = [];
  for (const value of raw) {
    const ref = text(value, MAX_REF_CHARS);
    if (!ref || !allowed.has(ref) || refs.includes(ref)) return null;
    refs.push(ref);
  }
  return refs;
}

function text(raw: unknown, max = MAX_TEXT_CHARS): string | null {
  if (typeof raw !== "string" || raw.length === 0 || raw.length > max ||
      /[\u0000-\u001F\u007F]/.test(raw)) return null;
  return raw;
}

function finiteNumber(raw: unknown): raw is number {
  return typeof raw === "number" && Number.isFinite(raw);
}

function rfc3339(raw: unknown): string | null {
  const value = text(raw, 64);
  return value && RFC3339.test(value) && Number.isFinite(Date.parse(value)) ? value : null;
}

function timestampsStrictlyIncrease(values: readonly string[]): boolean {
  const times = values.map((value) => Date.parse(value));
  return times.every((value, index) => index === 0 || times[index - 1]! < value);
}

function isRecord(raw: unknown): raw is Record<string, unknown> {
  return typeof raw === "object" && raw !== null && !Array.isArray(raw);
}

function hasExactKeys(record: Record<string, unknown>, expected: readonly string[]): boolean {
  const keys = Object.keys(record);
  return keys.length === expected.length && expected.every((key) => key in record);
}

function hasLegacyOrVisualizedKeys(
  record: Record<string, unknown>,
  legacy: readonly string[],
): boolean {
  return hasExactKeys(record, legacy) || hasExactKeys(record, [...legacy, "visualization"]);
}

function chartVisualization<T extends string>(
  raw: unknown,
  allowed: readonly T[],
): T | undefined | null {
  if (raw === undefined) return undefined;
  return typeof raw === "string" && allowed.includes(raw as T) ? raw as T : null;
}
