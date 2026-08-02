import type {
  DiagramEdge,
  DiagramNode,
  Locale,
  LocalizedText,
} from "./types.js";

export const NODE_FONT_SIZE = 13;
export const NODE_LINE_HEIGHT = 17;
export const NODE_ICON_SIZE = 42;
export const NODE_ICON_TOP = 12;
export const NODE_LABEL_GAP = 10;
export const NODE_BOTTOM_PADDING = 12;
export const REFERENCE_NODE_ICON_SIZE = 50;
export const EDGE_FONT_SIZE = 12;
export const EDGE_LINE_HEIGHT = 16;

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

export interface NodeGeometry {
  width: number;
  height: number;
  hasIcon: boolean;
  iconSize: number;
  iconTop: number;
  labelTop: number;
  maxLabelUnits: number;
}

export function nodeGeometry(node: DiagramNode): NodeGeometry {
  const iconPresentation = node.presentation === "icon";
  const width = Math.max(iconPresentation ? 116 : 148, node.width ?? 0);
  const maxLabelUnits = (width - (iconPresentation ? 12 : 20)) / NODE_FONT_SIZE;
  const lineCount = maxLocaleLineCount(node.label, maxLabelUnits);
  const hasIcon = Boolean(node.icon) || node.kind === "agent";
  const textHeight = lineCount * NODE_LINE_HEIGHT;
  const iconSize = iconPresentation ? REFERENCE_NODE_ICON_SIZE : NODE_ICON_SIZE;
  const iconTop = iconPresentation ? 8 : NODE_ICON_TOP;
  const labelGap = iconPresentation ? 6 : NODE_LABEL_GAP;
  const bottomPadding = iconPresentation ? 8 : NODE_BOTTOM_PADDING;
  const iconLabelTop = iconTop + iconSize + labelGap;
  const requiredHeight = iconLabelTop + textHeight + bottomPadding;
  const height = Math.max(requiredHeight, node.height ?? 0);
  return {
    width,
    height,
    hasIcon,
    iconSize: hasIcon ? iconSize : 0,
    iconTop: hasIcon ? iconTop : 0,
    labelTop: hasIcon ? iconLabelTop : (height - textHeight) / 2,
    maxLabelUnits,
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
): EdgeLabelGeometry | undefined {
  if (!edge.label) return undefined;
  const maxLabelUnits = 14;
  const localeLines = (["en", "ko"] satisfies Locale[]).map((locale) =>
    wrapText(edge.label![locale], maxLabelUnits),
  );
  const lines = localeLines.flat();
  const width = Math.max(
    64,
    ...lines.map((line) => estimatedTextWidth(line, EDGE_FONT_SIZE) + 18),
  );
  const lineCount = Math.max(...localeLines.map((value) => value.length));
  return {
    width,
    height: lineCount * EDGE_LINE_HEIGHT + 8,
    maxLabelUnits,
    lineCount,
  };
}
