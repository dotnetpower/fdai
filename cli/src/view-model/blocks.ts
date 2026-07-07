/**
 * Presentation-neutral BLOCK IR.
 *
 * This is the single "same content" layer. The briefing is compiled once into
 * an array of semantic `Block`s (see `build-briefing.ts`); every surface -
 * terminal (Ink), Slack (Block Kit), Teams (Adaptive Card), plain text - is a
 * pure function `Block[] -> <that surface's format>`. A block carries *meaning*
 * and *data*, never colors, ANSI codes, or layout - each renderer decides how a
 * block looks on its surface.
 *
 * Rule of thumb: if a field describes what the thing IS or the data it holds, it
 * belongs here. If it describes how it LOOKS (hex, emoji, column widths), it
 * belongs in a renderer.
 */

/** Semantic tone. Renderers map this to their own palette / affordance. */
export type Tone =
  | "neutral"
  | "dim"
  | "t0"
  | "t1"
  | "t2"
  | "low"
  | "medium"
  | "high"
  | "good"
  | "warn"
  | "danger"
  | "accent";

/**
 * Side-effect class of a console action (architecture.instructions.md -
 * Action Ontology and Console Vocabulary). Renderers may badge these.
 */
export type SideEffectClass =
  | "read"
  | "simulate"
  | "approve"
  | "execute"
  | "breakglass";

export type RiskLevel = "LOW" | "MEDIUM" | "HIGH";

/** Product wordmark + run context (env / clock / read-only). */
export interface HeaderBlock {
  type: "header";
  title: string;
  version: string;
  context: string;
}

/** One narrator line. The narrator is a translator, never a judge. */
export interface NarrationBlock {
  type: "narration";
  text: string;
  tone?: Tone;
}

/** Throughput over the window. Carries data only; each renderer picks a form. */
export interface BarChartBlock {
  type: "barChart";
  title: string;
  series: readonly number[];
  unit: string;
  caption: string;
  /** Sparse x-axis labels: text placed at column index `at`. */
  axisLabels: ReadonlyArray<{ at: number; text: string }>;
  tone: Tone;
}

/** Horizontal stat bars (e.g. trust-tier shares). */
export interface StatBarsBlock {
  type: "statBars";
  title: string;
  rows: ReadonlyArray<{ label: string; sub?: string; pct: number; tone: Tone }>;
}

/** A compact key/value stat strip. */
export interface SummaryBlock {
  type: "summary";
  items: ReadonlyArray<{ label: string; value: string; tone?: Tone }>;
}

/** A bulleted or numbered list (e.g. suggested questions). */
export interface ListBlock {
  type: "list";
  items: readonly string[];
  ordered?: boolean;
  tone?: Tone;
}

/** One HIL decision the operator must resolve. */
export interface DecisionCardBlock {
  type: "decisionCard";
  index: number;
  total: number;
  title: string;
  actionType: string;
  risk: RiskLevel;
  chip: string;
  chipSideEffect: SideEffectClass;
  fields: ReadonlyArray<{ label: string; value: string }>;
  actions: ReadonlyArray<{
    key: string;
    label: string;
    sideEffect: SideEffectClass;
  }>;
  reference: string;
  irreversible: boolean;
}

/** The input line at the end of the briefing. */
export interface PromptBlock {
  type: "prompt";
  text: string;
  hint?: string;
}

/** A visual separator. */
export interface DividerBlock {
  type: "divider";
}

export type Block =
  | HeaderBlock
  | NarrationBlock
  | BarChartBlock
  | StatBarsBlock
  | SummaryBlock
  | ListBlock
  | DecisionCardBlock
  | PromptBlock
  | DividerBlock;

/** A fully compiled briefing: an ordered list of surface-neutral blocks. */
export type Briefing = readonly Block[];
