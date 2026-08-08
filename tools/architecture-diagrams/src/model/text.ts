import type {
  DiagramEdge,
  DiagramNode,
  Locale,
  LocalizedText,
} from "./types.js";

export const GROUP_FONT_SIZE = 17;
export const NODE_FONT_SIZE = 17;
export const NODE_LINE_HEIGHT = 22;
export const NODE_BODY_FONT_SIZE = 14;
export const NODE_BODY_LINE_HEIGHT = 20;
export const NODE_ICON_SIZE = 42;
export const NODE_ICON_TOP = 12;
export const NODE_LABEL_GAP = 10;
export const NODE_BOTTOM_PADDING = 12;
export const REFERENCE_NODE_ICON_SIZE = 50;
export const EDGE_FONT_SIZE = 14;
export const EDGE_LINE_HEIGHT = 19;
export const REFERENCE_GROUP_FONT_SIZE = 14;
export const REFERENCE_NODE_FONT_SIZE = 13;
export const REFERENCE_NODE_LINE_HEIGHT = 17;
export const REFERENCE_NODE_BODY_FONT_SIZE = 11;
export const REFERENCE_NODE_BODY_LINE_HEIGHT = 15;
export const REFERENCE_EDGE_FONT_SIZE = 12;
export const REFERENCE_EDGE_LINE_HEIGHT = 16;

function glyphUnits(character: string): number {
  if (/\s/u.test(character)) return 0.35;
  if (/\p{Script=Hangul}|\p{Script=Han}|\p{Script=Hiragana}|\p{Script=Katakana}/u.test(character)) {
    return 1;
  }
  if (/\p{Lu}/u.test(character)) return 0.7;
  if (/\p{Ll}|\p{N}/u.test(character)) return 0.58;
  return 0.48;
}

export function visualUnits(value: string): number {
  return [...value].reduce((total, character) => total + glyphUnits(character), 0);
}

function splitToken(token: string, maxUnits: number): string[] {
  const chunks: string[] = [];
  let current = "";
  for (const character of token) {
    if (current && visualUnits(current + character) > maxUnits) {
      chunks.push(current);
      current = character;
    } else {
      current += character;
    }
  }
  if (current) chunks.push(current);
  return chunks;
}

export function wrapText(value: string, maxUnits: number): string[] {
  const lines: string[] = [];
  let current = "";
  for (const word of value.trim().split(/\s+/u)) {
    const pieces = visualUnits(word) > maxUnits ? splitToken(word, maxUnits) : [word];
    for (const piece of pieces) {
      const candidate = current ? `${current} ${piece}` : piece;
      if (current && visualUnits(candidate) > maxUnits) {
        lines.push(current);
        current = piece;
      } else {
        current = candidate;
      }
    }
  }
  if (current) lines.push(current);
  return lines.length ? lines : [""];
}

export function estimatedTextWidth(value: string, fontSize: number): number {
  return Math.ceil(visualUnits(value) * fontSize);
}

function maxLocaleLineCount(
  label: LocalizedText,
  maxUnits: number,
): number {
  return Math.max(
    ...(["en", "ko"] satisfies Locale[]).map(
      (locale) => wrapText(label[locale], maxUnits).length,
    ),
  );
}

export function nodeBodyLines(
  node: DiagramNode,
  locale: Locale,
  maxUnits: number,
): string[] {
  return (node.content ?? []).flatMap((item) => {
    const lines = wrapText(item[locale], Math.max(4, maxUnits - 2));
    return lines.map((line, index) => `${index === 0 ? "- " : "  "}${line}`);
  });
}

export interface NodeGeometry {
  width: number;
  height: number;
  hasIcon: boolean;
  iconSize: number;
  iconTop: number;
  labelTop: number;
  bodyTop: number;
  maxLabelUnits: number;
  maxBodyUnits: number;
}

export function nodeGeometry(node: DiagramNode, compact = false): NodeGeometry {
  const nodeFontSize = compact ? REFERENCE_NODE_FONT_SIZE : NODE_FONT_SIZE;
  const nodeLineHeight = compact ? REFERENCE_NODE_LINE_HEIGHT : NODE_LINE_HEIGHT;
  const bodyFontSize = compact ? REFERENCE_NODE_BODY_FONT_SIZE : NODE_BODY_FONT_SIZE;
  const bodyLineHeight = compact
    ? REFERENCE_NODE_BODY_LINE_HEIGHT
    : NODE_BODY_LINE_HEIGHT;
  const iconPresentation = node.presentation === "icon";
  const databaseShape = node.shape === "database";
  const naturalLabelWidth = Math.min(
    220,
    Math.max(
      156,
      ...(["en", "ko"] satisfies Locale[]).map(
        (locale) => estimatedTextWidth(node.label[locale], nodeFontSize) + 28,
      ),
    ),
  );
  const width = node.width ?? (
    iconPresentation
      ? 116
      : node.content?.length
        ? 220
        : compact
          ? 148
          : naturalLabelWidth
  );
  const maxLabelUnits = (width - (iconPresentation ? 12 : 20)) / nodeFontSize;
  const maxBodyUnits = (width - 24) / bodyFontSize;
  const lineCount = maxLocaleLineCount(node.label, maxLabelUnits);
  const bodyLineCount = Math.max(
    ...(["en", "ko"] satisfies Locale[]).map(
      (locale) => nodeBodyLines(node, locale, maxBodyUnits).length,
    ),
  );
  const hasIcon = Boolean(node.icon) || node.kind === "agent";
  const textHeight = lineCount * nodeLineHeight;
  const bodyHeight = bodyLineCount * bodyLineHeight;
  const iconSize = iconPresentation ? REFERENCE_NODE_ICON_SIZE : NODE_ICON_SIZE;
  const iconTop = iconPresentation ? 8 : NODE_ICON_TOP;
  const labelGap = iconPresentation ? 6 : NODE_LABEL_GAP;
  const bottomPadding = iconPresentation ? 8 : databaseShape ? 18 : NODE_BOTTOM_PADDING;
  const iconLabelTop = iconTop + iconSize + labelGap;
  const naturalLabelTop = hasIcon ? iconLabelTop : databaseShape ? 28 : 14;
  const bodyGap = bodyLineCount ? 8 : 0;
  const requiredHeight = bodyLineCount
    ? naturalLabelTop + textHeight + bodyGap + bodyHeight + bottomPadding
    : iconLabelTop + textHeight + bottomPadding;
  const height = Math.max(requiredHeight, databaseShape ? 88 : 0, node.height ?? 0);
  const labelTop = hasIcon
    ? iconLabelTop
    : bodyLineCount
      ? naturalLabelTop
      : (height - textHeight) / 2;
  return {
    width,
    height,
    hasIcon,
    iconSize: hasIcon ? iconSize : 0,
    iconTop: hasIcon ? iconTop : 0,
    labelTop,
    bodyTop: labelTop + textHeight + bodyGap,
    maxLabelUnits,
    maxBodyUnits,
  };
}

export interface EdgeLabelGeometry {
  width: number;
  height: number;
  maxLabelUnits: number;
  lineCount: number;
}

export function edgeLabelGeometry(
  edge: DiagramEdge,
  compact = false,
): EdgeLabelGeometry | undefined {
  if (!edge.label) return undefined;
  const fontSize = compact ? REFERENCE_EDGE_FONT_SIZE : EDGE_FONT_SIZE;
  const lineHeight = compact ? REFERENCE_EDGE_LINE_HEIGHT : EDGE_LINE_HEIGHT;
  const maxLabelUnits = 14;
  const localeLines = (["en", "ko"] satisfies Locale[]).map((locale) =>
    wrapText(edge.label![locale], maxLabelUnits),
  );
  const lines = localeLines.flat();
  const width = Math.max(
    64,
    ...lines.map((line) => estimatedTextWidth(line, fontSize) + 18),
  );
  const lineCount = Math.max(...localeLines.map((value) => value.length));
  return {
    width,
    height: lineCount * lineHeight + 8,
    maxLabelUnits,
    lineCount,
  };
}
