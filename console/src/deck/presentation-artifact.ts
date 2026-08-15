import type {
  AnswerVerification,
  PresentationArtifact,
  PresentationBlock,
  PresentationChartItem,
  PresentationColumn,
  PresentationEmphasis,
  PresentationSummaryItem,
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
const SLOT_KINDS: Readonly<Record<string, ReadonlySet<PresentationBlock["kind"]>>> = {
  overview: new Set(["summary"]),
  limitations: new Set(["callout"]),
  findings: new Set(["table", "list"]),
  coverage: new Set(["coverage", "table"]),
  metrics: new Set(["threshold_table", "table"]),
  evidence: new Set(["evidence"]),
  records: new Set(["table", "list"]),
  distribution: new Set(["bar", "table"]),
};

export function parsePresentationArtifact(
  raw: unknown,
  verification: AnswerVerification | undefined,
): PresentationArtifact | undefined {
  if (!verification || !isRecord(raw) || !hasExactKeys(
    raw,
    ["schema_version", "layout", "blocks", "evidence_refs"],
  )) return undefined;
  if (raw.schema_version !== 1 || raw.layout !== "stack" ||
      !Array.isArray(raw.blocks) || raw.blocks.length === 0 || raw.blocks.length > MAX_BLOCKS) {
    return undefined;
  }
  const verificationRefs = new Set(verification.evidence_refs);
  const evidenceRefs = parseRefs(raw.evidence_refs, verificationRefs);
  if (!evidenceRefs) return undefined;
  const slots = new Set<string>();
  const blocks: PresentationBlock[] = [];
  for (const rawBlock of raw.blocks) {
    const block = parseBlock(rawBlock, new Set(evidenceRefs));
    if (!block || slots.has(block.slotId)) return undefined;
    slots.add(block.slotId);
    blocks.push(block);
  }
  return { schemaVersion: 1, layout: "stack", blocks, evidenceRefs };
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
      data: block.kind === "table" || block.kind === "threshold_table" || block.kind === "list"
        ? {
            columns: block.data.columns.map((column) => ({ ...column })),
            rows: block.data.rows.map((row) => ({ ...row })),
            status_key: block.data.statusKey,
          }
        : block.kind === "callout"
        ? { tone: block.data.tone, lines: [...block.data.lines] }
        : { items: block.data.items.map((item) => ({ ...item })) },
    })),
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
    let data: Record<string, unknown>;
    if (rawBlock.kind === "table" || rawBlock.kind === "threshold_table" ||
        rawBlock.kind === "list") {
      data = {
        columns: rawBlock.data.columns,
        rows: rawBlock.data.rows,
        status_key: rawBlock.data.statusKey,
      };
    } else {
      data = { ...rawBlock.data };
    }
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
  }, verification);
}

function parseBlock(raw: unknown, artifactRefs: ReadonlySet<string>): PresentationBlock | null {
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
    const items = parseChartItems(raw.data);
    return items ? { ...base, kind: raw.kind, data: { items } } : null;
  }
  if (raw.kind === "evidence") {
    const items = parseLabelValues(raw.data);
    return items ? { ...base, kind: "evidence", data: { items } } : null;
  }
  return null;
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

function parseChartItems(data: Record<string, unknown>): PresentationChartItem[] | null {
  if (!hasExactKeys(data, ["items"]) || !Array.isArray(data.items) ||
      data.items.length === 0 || data.items.length > MAX_ITEMS) return null;
  const items: PresentationChartItem[] = [];
  const labels = new Set<string>();
  for (const rawItem of data.items) {
    if (!isRecord(rawItem) || !hasExactKeys(rawItem, ["label", "value", "tone"])) return null;
    const label = text(rawItem.label);
    const value = rawItem.value;
    const tone = rawItem.tone;
    if (!label || labels.has(label) || !Number.isSafeInteger(value) || (value as number) < 0 ||
        !TONES.has(tone as PresentationTone)) return null;
    labels.add(label);
    items.push({ label, value: value as number, tone: tone as PresentationTone });
  }
  return items;
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

function isRecord(raw: unknown): raw is Record<string, unknown> {
  return typeof raw === "object" && raw !== null && !Array.isArray(raw);
}

function hasExactKeys(record: Record<string, unknown>, expected: readonly string[]): boolean {
  const keys = Object.keys(record);
  return keys.length === expected.length && expected.every((key) => key in record);
}
