/**
 * Live cockpit - the operator surface for Forward Deployed AI.
 *
 * A single alternate-screen view fed by the read API's `/live/stream` (SSE),
 * where every frame is a REAL StageEvent from an actual ControlLoop run (real
 * rule catalog, T0 engine, Rego). The design goal is trust: the screen reads
 * like an assistant that operates your cloud on your behalf, not a debug log -
 * events are narrated in plain language with their tier and outcome, the safety
 * posture (read-only, PR-native, shadow-first, audited) is always visible, and
 * answers stream in.
 *
 * Input is edited in raw mode with the real terminal cursor at the caret so
 * IME/Korean composition works; only the affected regions are repainted, never
 * the whole screen, so typing is never disturbed. Read-only throughout.
 */

import { createNarrator } from "./narrator/index.js";
import type { NarratorContext } from "./narrator/types.js";
import { t, type Locale } from "./i18n/index.js";

const BRAND = "\x1b[38;2;99;166;156m"; // teal
const BRIGHT = "\x1b[38;2;122;214;196m"; // bright teal accent
const STEEL = "\x1b[38;2;110;155;203m";
const PLUM = "\x1b[38;2;168;150;206m";
const SAGE = "\x1b[38;2;127;176;119m";
const TERRA = "\x1b[38;2;214;146;95m";
const DIM = "\x1b[38;2;124;132;139m";
const TEXT = "\x1b[38;2;199;205;210m";
const BOLD = "\x1b[1m";
const NOBOLD = "\x1b[22m";
const RESET = "\x1b[0m";
const ESC = "\x1b";
// Panel backgrounds - we tint bands (header, section rules, input), never force
// the whole screen, so the operator's terminal theme still shows through.
const BG_HEADER = "\x1b[48;2;18;40;44m"; // deep teal header bar
const BG_BAR = "\x1b[48;2;15;22;26m"; // charcoal section band
const BG_INPUT = "\x1b[48;2;20;28;33m"; // input row band
const ON_HEADER = "\x1b[38;2;150;225;208m"; // text on the header bar
const ON_BAR = "\x1b[38;2;150;160;170m"; // text on a charcoal band

const stripAnsi = (s: string): string =>
  // eslint-disable-next-line no-control-regex
  s.replace(/\x1b\[[0-9;]*m/g, "");

const out = process.stdout;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

interface StageFrame {
  event_id: string;
  correlation_id: string;
  stage: string;
  phase: string;
  ts: string;
  detail?: Record<string, unknown>;
  error?: string;
}

interface Activity {
  marker: string; // colored glyph
  resource: string;
  text: string;
  tier: string;
}

/** Which component fills the main panel. Driven by natural-language commands. */
type ViewMode = "stream" | "overview" | "focus";
interface View {
  mode: ViewMode;
  focus?: string; // resource-type substring when mode === "focus"
  paused: boolean; // freeze the stream (events still counted)
}

function charWidth(cp: number): number {
  if (
    (cp >= 0x1100 && cp <= 0x115f) ||
    (cp >= 0x2e80 && cp <= 0xa4cf) ||
    (cp >= 0xac00 && cp <= 0xd7a3) ||
    (cp >= 0xf900 && cp <= 0xfaff) ||
    (cp >= 0xfe30 && cp <= 0xfe4f) ||
    (cp >= 0xff00 && cp <= 0xff60) ||
    (cp >= 0xffe0 && cp <= 0xffe6)
  ) {
    return 2;
  }
  return 1;
}
function strWidth(s: string): number {
  let w = 0;
  for (const ch of s) w += charWidth(ch.codePointAt(0)!);
  return w;
}
function clip(s: string, width: number): string {
  let w = 0;
  let o = "";
  for (const ch of s) {
    const cw = charWidth(ch.codePointAt(0)!);
    if (w + cw > width) break;
    o += ch;
    w += cw;
  }
  return o;
}
function wrap(s: string, width: number, maxLines: number): string[] {
  const words = s.split(/\s+/);
  const lines: string[] = [];
  let cur = "";
  for (const w of words) {
    const cand = cur ? `${cur} ${w}` : w;
    if (strWidth(cand) > width && cur) {
      lines.push(cur);
      cur = w;
      if (lines.length >= maxLines) break;
    } else {
      cur = cand;
    }
  }
  if (cur && lines.length < maxLines) lines.push(cur);
  return lines.slice(0, maxLines);
}

const tierColor = (t: string): string =>
  t === "t0" ? BRAND : t === "t1" ? STEEL : t === "t2" ? PLUM : DIM;
export function tierLabel(tier: string, locale: Locale): string {
  const key =
    tier === "t0"
      ? "cockpit.tier.t0"
      : tier === "t1"
        ? "cockpit.tier.t1"
        : tier === "t2"
          ? "cockpit.tier.t2"
          : "cockpit.tier.unrouted";
  return t(key, locale);
}

// ---- compact visualizations (overview dashboard) ---------------------------
const TRACK = "\x1b[38;2;46;54;62m"; // unfilled bar track
const SPARK_CHARS = ["\u2581", "\u2582", "\u2583", "\u2584", "\u2585", "\u2586", "\u2587", "\u2588"];

/** A horizontal proportion bar: filled block in `color`, remainder as a track.
 * Uses distinct glyphs (full vs light shade) so the ratio reads even without
 * color. */
function hbar(frac: number, width: number, color: string): string {
  const f = Math.round(Math.max(0, Math.min(1, frac)) * width);
  return `${color}${"\u2588".repeat(f)}${TRACK}${"\u2591".repeat(Math.max(0, width - f))}${RESET}`;
}

/** A unicode sparkline over the last `width` samples. */
function sparkline(data: number[], width: number): string {
  const d = data.slice(-width);
  if (d.length === 0) return `${TRACK}${"\u2581".repeat(width)}${RESET}`;
  const max = Math.max(1, ...d);
  return d.map((v) => SPARK_CHARS[Math.min(7, Math.floor((v / max) * 7.999))]).join("");
}

/** Map a natural-language token to a resource-type focus substring. */
const RESOURCE_KEYWORDS: Array<[RegExp, string]> = [
  [/network|nsg|load.?balancer|public.?ip|\ub124\ud2b8\uc6cc\ud06c/, "network"],
  [/compute|vm|scale.?set|\uac00\uc0c1\uba38\uc2e0|\ucef4\ud4e8\ud2b8/, "compute"],
  [/disk|\ub514\uc2a4\ud06c/, "disk"],
  [/postgres|postgre/, "postgres"],
  [/\bsql\b|database|\ub370\uc774\ud130\ubca0\uc774\uc2a4/, "sql"],
  [/storage|object|\uc2a4\ud1a0\ub9ac\uc9c0|\uc624\ube0c\uc81d\ud2b8/, "object-storage"],
  [/kubernetes|k8s|aks|node.?pool|\ucfe0\ubc84\ub124\ud2f0\uc2a4/, "kubernetes"],
  [/cache|redis|\uce90\uc2dc/, "cache"],
  [/secret|key.?vault|\ube44\ubc00|\uc2dc\ud06c\ub9bf/, "secret"],
  [/log.?workspace|\ub85c\uadf8/, "log-workspace"],
  [/resource.?group|\ub9ac\uc18c\uc2a4\s?\uadf8\ub8f9/, "resource-group"],
];

/** The active-view badge, localized. Pure over the view + locale. */
export function viewBadge(view: View, locale: Locale): string {
  if (view.paused) return t("cockpit.badge.paused", locale);
  if (view.mode === "overview") return t("cockpit.badge.overview", locale);
  if (view.mode === "focus")
    return t("cockpit.badge.focus", locale, { focus: (view.focus ?? "").toUpperCase() });
  return t("cockpit.badge.stream", locale);
}

/** Parse a natural-language screen command (KO/EN) into a view patch + reply.
 * Pure over the query and locale; the cockpit routes views locally with zero
 * LLM dependency. Returns null when nothing matches. */
export function parseScreenCommand(
  q: string,
  locale: Locale,
): { patch: Partial<View>; reply: string } | null {
  const norm = q.toLowerCase().trim();
  if (/\b(pause|freeze|hold)\b|\uba48\ucdb0|\uc815\uc9c0|\uc911\uc9c0|\uc77c\uc2dc\uc815\uc9c0/.test(norm)) {
    return { patch: { paused: true }, reply: t("cockpit.cmd.paused", locale) };
  }
  if (/\b(resume|continue|unpause|play|live)\b|\uc7ac\uac1c|\uacc4\uc18d|\ub2e4\uc2dc\s?\uc2dc\uc791|\uc774\uc5b4/.test(norm)) {
    return { patch: { paused: false, mode: "stream" }, reply: t("cockpit.cmd.resumed", locale) };
  }
  if (/\b(overview|dashboard|summary)\b|\ub300\uc2dc\ubcf4\ub4dc|\uc9d1\uacc4|\ud55c\ub208|\uc694\uc57d\s?(\ud654\uba74|\ubcf4\uae30|\ubdf0)/.test(norm)) {
    return { patch: { mode: "overview", paused: false }, reply: t("cockpit.cmd.overview", locale) };
  }
  if (/\b(stream|feed|logs?)\b|\uc2a4\ud2b8\ub9bc|\ud53c\ub4dc|\ub85c\uadf8|\ud759\ub984|\uc2e4\uc2dc\uac04/.test(norm)) {
    return {
      patch: { mode: "stream", focus: undefined, paused: false },
      reply: t("cockpit.cmd.streaming", locale),
    };
  }
  if (/\b(clear|reset|all|everything)\b|\uc804\uccb4|\ucd08\uae30\ud654|\ud574\uc81c/.test(norm)) {
    return {
      patch: { mode: "stream", focus: undefined, paused: false },
      reply: t("cockpit.cmd.cleared", locale),
    };
  }
  const wantsFocus = /focus|only|\ud544\ud130|\uc9d1\uc911|\ub9cc\s?(\ubcf4\uc5ec|\ubd10|\ubcf4\uae30)/.test(norm);
  if (wantsFocus) {
    for (const [re, key] of RESOURCE_KEYWORDS) {
      if (re.test(norm)) {
        return {
          patch: { mode: "focus", focus: key, paused: false },
          reply: t("cockpit.cmd.focusing", locale, { focus: key }),
        };
      }
    }
    return {
      patch: { mode: "stream", focus: undefined, paused: false },
      reply: t("cockpit.cmd.whichResource", locale),
    };
  }
  return null;
}

/** Live counters the cockpit's local answerer reads. Passed as a snapshot so
 * `localAnswer` stays pure and testable. */
export interface CockpitStats {
  readonly handled: number;
  readonly byTier: Record<string, number>;
  readonly awaitingYou: number;
  readonly autoApplied: number;
  readonly undone: number;
  readonly activity: readonly { readonly resource: string; readonly text: string }[];
}

/** Answer a state/trust question from the LIVE cockpit counters (never a mock
 * seed), so what I say matches what is on screen. Returns null to let the
 * narrator handle anything outside live state. Pure over the query, the stats
 * snapshot, and the locale. */
export function localAnswer(q: string, stats: CockpitStats, locale: Locale): string | null {
  const norm = q.toLowerCase().trim();
  const { handled, byTier, awaitingYou, autoApplied, undone, activity } = stats;
  if (/(awaiting|approval|hil|queue|decision|need you|escalat)/.test(norm)) {
    return awaitingYou > 0
      ? t("cockpit.answer.awaitingSome", locale, { count: awaitingYou })
      : t("cockpit.answer.awaitingNone", locale);
  }
  if (/(abstain|stepped|skip|no rule|why not)/.test(norm)) {
    return t("cockpit.answer.abstain", locale, { count: byTier.abstain ?? 0 });
  }
  if (/(safe|trust|read.?only|audit|rollback|how do you|guarantee)/.test(norm)) {
    return t("cockpit.answer.trust", locale);
  }
  if (/(recent|activity|last|what did you|history)/.test(norm)) {
    const last = activity
      .slice(-3)
      .map((a) => `${a.resource} ${a.text.split(" - ")[0]}`)
      .join("; ");
    return t("cockpit.answer.recent", locale, {
      last: last || t("cockpit.answer.nothingYet", locale),
    });
  }
  if (/(kpi|status|summary|how many|handl|doing|happening|now|minute|overview|health)/.test(norm)) {
    return t("cockpit.answer.kpi", locale, {
      handled,
      t0: byTier.t0 ?? 0,
      t1: byTier.t1 ?? 0,
      t2: byTier.t2 ?? 0,
      abstain: byTier.abstain ?? 0,
      auto: autoApplied,
      awaiting: awaitingYou,
      undone,
    });
  }
  return null;
}

async function consumeSse(
  url: string,
  onFrame: (f: StageFrame) => void,
  onStatus: (s: string) => void,
  signal: AbortSignal,
): Promise<void> {
  try {
    const res = await fetch(url, { signal, headers: { accept: "text/event-stream" } });
    if (!res.ok || !res.body) {
      onStatus(`stream ${res.status}`);
      return;
    }
    onStatus("live");
    const reader = res.body.getReader();
    const dec = new TextDecoder();
    let buf = "";
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buf += dec.decode(value, { stream: true });
      let idx: number;
      while ((idx = buf.indexOf("\n\n")) >= 0) {
        const block = buf.slice(0, idx);
        buf = buf.slice(idx + 2);
        let ev = "message";
        let data = "";
        for (const line of block.split("\n")) {
          if (line.startsWith("event:")) ev = line.slice(6).trim();
          else if (line.startsWith("data:")) data += line.slice(5).trim();
        }
        if (ev === "stage" && data) {
          try {
            onFrame(JSON.parse(data) as StageFrame);
          } catch {
            /* ignore */
          }
        }
      }
    }
  } catch (err) {
    if (!signal.aborted) onStatus(`stream error: ${(err as Error).message}`);
  }
}

export async function startCockpit(ctx: NarratorContext): Promise<void> {
  const stdin = process.stdin;
  const apiUrl = ctx.apiUrl!;
  if (!stdin.isTTY || typeof stdin.setRawMode !== "function") {
    process.stdout.write(
      `${DIM}live cockpit needs a TTY; run in a real terminal (streaming ${apiUrl}/live/stream)${RESET}\n`,
    );
    return;
  }

  const narrator = createNarrator();
  const locale = ctx.locale ?? "en";

  // ---- live state ----------------------------------------------------------
  let handled = 0;
  const byTier: Record<string, number> = {};
  let autoApplied = 0;
  let awaitingYou = 0;
  let undone = 0;
  let errors = 0;
  const activity: Activity[] = [];
  const resourceCounts: Record<string, number> = {};
  const spark: number[] = []; // handled-per-tick, for the overview sparkline
  let handledAtLastTick = 0;
  const perEvent = new Map<string, { resource: string; tier: string; routed: string }>();
  const view: View = { mode: "stream", paused: false };
  let status = "connecting";
  let lastQ = "";
  let answerTarget = "";
  let answerShown = 0;
  let thinking = false;
  let busy = false;

  const onFrame = (f: StageFrame): void => {
    const d = f.detail ?? {};
    if (f.phase === "failed") errors++;
    if (f.stage === "route" && f.phase === "done") {
      const routed = String(d.routed_to ?? "abstain");
      perEvent.set(f.event_id, {
        resource: String(d.resource_type ?? "") || "resource",
        tier: routed,
        routed,
      });
      byTier[routed] = (byTier[routed] ?? 0) + 1;
    }
    if (f.stage === "verify" && f.phase === "done") {
      const rec = perEvent.get(f.event_id);
      if (rec && d.tier) rec.tier = String(d.tier);
    }
    if (f.stage === "audit" && f.phase === "done") {
      handled++;
      const rec = perEvent.get(f.event_id);
      const tier = rec?.tier ?? "t0";
      const resource = rec?.resource ?? "resource";
      const outcome = String(d.outcome ?? "");
      const decision = String(d.decision ?? "");
      let a: Activity;
      if (decision === "auto" || outcome === "executed") {
        autoApplied++;
        a = { marker: `${SAGE}\u2713${RESET}`, resource, text: t("cockpit.feed.autoApplied", locale), tier };
      } else if (outcome.includes("hil") || decision === "hil") {
        awaitingYou++;
        a = { marker: `${TERRA}\u2691${RESET}`, resource, text: t("cockpit.feed.awaiting", locale), tier };
      } else if (outcome.startsWith("abstained")) {
        const why = outcome.includes("routing")
          ? t("cockpit.feed.whyRouting", locale)
          : t("cockpit.feed.whyNoRule", locale);
        a = { marker: `${DIM}\u00b7${RESET}`, resource, text: t("cockpit.feed.steppedBack", locale, { why }), tier };
      } else {
        a = { marker: `${DIM}\u00b7${RESET}`, resource, text: outcome || t("cockpit.feed.handled", locale), tier };
      }
      activity.push(a);
      if (activity.length > 400) activity.shift();
      if (resource !== "resource") {
        resourceCounts[resource] = (resourceCounts[resource] ?? 0) + 1;
      }
      perEvent.delete(f.event_id);
      onNewActivity(a);
      scheduleHeader();
    }
  };

  // ---- geometry ------------------------------------------------------------
  const rows = () => (out.rows && out.rows > 0 ? out.rows : 24);
  const cols = () => (out.columns && out.columns > 0 ? out.columns : 80);
  // Batched, tear-free rendering. Every write goes into a frame buffer that is
  // flushed once, wrapped in DEC 2026 synchronized-update markers, so the
  // terminal applies a whole frame atomically instead of showing it being
  // painted row by row (the flicker Ink hides for us, done by hand here).
  // Terminals that do not implement mode 2026 silently ignore the markers.
  const BEGIN_SYNC = `${ESC}[?2026h`;
  const END_SYNC = `${ESC}[?2026l`;
  let buf: string | null = null;
  const write = (s: string): void => {
    if (buf !== null) buf += s;
    else out.write(s);
  };
  const frame = (fn: () => void): void => {
    if (buf !== null) {
      // Reentrant call (e.g. renderTop -> renderQA): stay in the outer frame.
      fn();
      return;
    }
    buf = "";
    fn();
    const payload = buf;
    buf = null;
    out.write(BEGIN_SYNC + payload + END_SYNC);
  };
  const cursorTo = (r: number, c: number): void => write(`${ESC}[${r};${c}H`);
  const clearRow = (r: number): void => {
    cursorTo(r, 1);
    write(`${ESC}[2K`);
  };

  // ---- input state ---------------------------------------------------------
  let ibuf: string[] = [];
  let icur = 0;
  const history: string[] = [];
  let histIdx: number | null = null;
  // The input row is drawn as " > <text>" (leading space, prompt glyph, space),
  // so the caret column base is 3. Must match renderInput's prompt width or a
  // wide CJK/IME char will land one column off and overwrite the caret.
  const promptW = 3;

  const placeCaret = (): void => {
    cursorTo(rows(), 1 + promptW + strWidth(ibuf.slice(0, icur).join("")));
  };

  // ---- render regions ------------------------------------------------------
  // Layout (R = rows):
  //   1 header
  //   2 narrated summary
  //   3 trust line
  //   4 separator
  //   5 .. R-7 curated activity feed  (a hardware scroll region; new ops rise)
  //   R-6 separator
  //   R-5 question echo
  //   R-4,R-3,R-2 streamed answer (3 lines)
  //   R-1 hint
  //   R   input
  //
  // The cursor stays visible at the input caret the whole time - it is never
  // hidden/shown per frame (that resets the terminal blink timer and looks
  // jittery). Synchronized update hides the intra-frame cursor moves instead,
  // so the caret blinks steadily while frames repaint underneath it.
  const feedTop = 5;
  const feedBottom = (): number => Math.max(feedTop, rows() - 7);

  // Fill a full-width background band with left-aligned content. Content may
  // carry foreground SGR but MUST NOT contain a RESET (that drops the bg). The
  // last column is left empty so the band never auto-wraps onto the next row.
  const band = (r: number, content: string, bg: string): void => {
    const C = cols();
    const pad = Math.max(0, C - 1 - strWidth(stripAnsi(content)));
    clearRow(r);
    write(`${bg}${content}${" ".repeat(pad)}${RESET}`);
  };

  const drawFeedLine = (a: Activity): string => {
    const C = cols();
    const res = clip(a.resource, 22).padEnd(22);
    const tierTag = `${tierColor(a.tier)}${tierLabel(a.tier, locale)}${RESET}`;
    return `  ${a.marker} ${TEXT}${res}${RESET} ${DIM}${clip(a.text, C - 40)}${RESET}  ${tierTag}`;
  };

  const renderHeader = (): void => {
    frame(() => {
      const C = cols();
      const sub = "\x1b[38;2;96;150;150m";
      // Row 1: deep-teal header bar (title + status + active view, all inline).
      band(
        1,
        ` ${BOLD}${ON_HEADER}Forward Deployed AI${NOBOLD}${sub} \u00b7 Cloud Ops` +
          `   ${sub}read-only \u00b7 ${status} \u00b7 ${ON_HEADER}${BOLD}${viewBadge(view, locale)}${NOBOLD}`,
        BG_HEADER,
      );

      // Row 2: narrated summary.
      const abstain = byTier.abstain ?? 0;
      const summary = t("cockpit.header.summary", locale, {
        handled,
        t0: byTier.t0 ?? 0,
        abstain,
        auto: autoApplied,
        awaiting: awaitingYou,
      });
      clearRow(2);
      write(` ${TEXT}${clip(summary, C - 2)}${RESET}`);

      // Row 3: standing trust line.
      clearRow(3);
      write(` ${DIM}${t("cockpit.header.trust", locale)}${RESET}`);

      // Row 4: view band with the natural-language commands.
      band(
        4,
        ` ${BRIGHT}${BOLD}${viewBadge(view, locale)}${NOBOLD}${ON_BAR}   ${t("cockpit.header.commands", locale)}`,
        BG_BAR,
      );
      placeCaret();
    });
  };

  const matchesFocus = (a: Activity): boolean =>
    view.mode !== "focus" || !view.focus || a.resource.includes(view.focus);

  const visibleActivity = (): Activity[] =>
    view.mode === "focus" && view.focus
      ? activity.filter((a) => a.resource.includes(view.focus!))
      : activity;

  // Full repaint of the feed area (startup / resize / view switch).
  const renderFeedFull = (): void => {
    frame(() => {
      const top = feedTop;
      const bottom = feedBottom();
      const feedRows = bottom - top + 1;
      const slice = visibleActivity().slice(-feedRows);
      for (let i = 0; i < feedRows; i++) {
        clearRow(top + i);
        const a = slice[i];
        if (a) write(drawFeedLine(a));
      }
      placeCaret();
    });
  };

  // Append one op by scrolling the feed region up a line (hardware scroll, so
  // records glide upward) and drawing only the new row.
  const pushFeed = (a: Activity): void => {
    frame(() => {
      const top = feedTop;
      const bottom = feedBottom();
      write(`${ESC}[${top};${bottom}r`);
      write(`${ESC}[S`);
      write(`${ESC}[r`);
      write(`${ESC}[${bottom};1H${ESC}[2K`);
      write(drawFeedLine(a));
      placeCaret();
    });
  };

  // A new op arrived: update the live view unless paused / filtered / on overview.
  const onNewActivity = (a: Activity): void => {
    if (view.paused) return;
    if (view.mode === "overview") return;
    if (!matchesFocus(a)) return;
    pushFeed(a);
  };

  // The calm, "hip" default: aggregates instead of a firehose.
  const renderOverview = (): void => {
    frame(() => {
      const top = feedTop;
      const bottom = feedBottom();
      for (let rr = top; rr <= bottom; rr++) clearRow(rr);
      const C = cols();
      const barW = Math.max(16, Math.min(38, C - 44));
      let r = top;
      const line = (s = ""): void => {
        if (r > bottom) return;
        cursorTo(r, 3);
        write(s);
        r++;
      };
      const total = Math.max(1, handled);
      line(`${BRIGHT}${BOLD}${t("cockpit.overview.routingMix", locale)}${RESET}`);
      const tiers: Array<[string, number, string]> = [
        [t("cockpit.overview.tierT0", locale), byTier.t0 ?? 0, BRAND],
        [t("cockpit.overview.tierT1", locale), byTier.t1 ?? 0, STEEL],
        [t("cockpit.overview.tierT2", locale), byTier.t2 ?? 0, PLUM],
        [t("cockpit.overview.tierAbstain", locale), byTier.abstain ?? 0, DIM],
      ];
      for (const [label, n, color] of tiers) {
        line(
          `${TEXT}${label.padEnd(16)}${RESET} ${hbar(n / total, barW, color)} ` +
            `${color}${String(n).padStart(4)}${RESET} ${DIM}${Math.round((n / total) * 100)}%${RESET}`,
        );
      }
      line();
      line(
        `${BRIGHT}${BOLD}${t("cockpit.overview.throughput", locale)}${RESET}  ${BRAND}${sparkline(spark, Math.min(50, C - 24))}${RESET}` +
          ` ${DIM}${t("cockpit.overview.eventsPerSec", locale)}${RESET}`,
      );
      line();
      line(`${BRIGHT}${BOLD}${t("cockpit.overview.outcomes", locale)}${RESET}`);
      line(
        `${SAGE}\u2713 ${autoApplied}${RESET} ${DIM}${t("cockpit.overview.autoApplied", locale)}${RESET}    ` +
          `${TERRA}\u2691 ${awaitingYou}${RESET} ${DIM}${t("cockpit.overview.awaitingYou", locale)}${RESET}    ` +
          `${DIM}\u21ba ${undone} ${t("cockpit.overview.undone", locale)}    \u26a0 ${errors} ${t("cockpit.overview.errors", locale)}${RESET}`,
      );
      line();
      line(`${BRIGHT}${BOLD}${t("cockpit.overview.topResources", locale)}${RESET}`);
      const tops = Object.entries(resourceCounts)
        .sort((a, b) => b[1] - a[1])
        .slice(0, Math.max(1, bottom - r - 1));
      const maxc = Math.max(1, ...tops.map((t) => t[1]));
      for (const [name, c] of tops) {
        line(
          `${TEXT}${clip(name, 22).padEnd(22)}${RESET} ${hbar(c / maxc, barW, BRAND)} ${DIM}${c}${RESET}`,
        );
      }
      placeCaret();
    });
  };

  const renderBody = (): void => {
    if (view.mode === "overview") renderOverview();
    else renderFeedFull();
  };

  const renderQA = (): void => {
    frame(() => {
      const R = rows();
      const C = cols();
      clearRow(R - 6);
      write(` ${DIM}${"\u2500".repeat(Math.min(C - 2, 98))}${RESET}`);
      clearRow(R - 5);
      if (lastQ) write(` ${DIM}${t("cockpit.qa.you", locale)}${RESET} ${BRAND}\u203a${RESET} ${TEXT}${clip(lastQ, C - 8)}${RESET}`);
      const shown = thinking ? t("cockpit.qa.thinking", locale) : answerTarget.slice(0, answerShown);
      const lines = wrap(shown, C - 4, 3);
      clearRow(R - 4);
      if (lines[0]) write(` ${thinking ? DIM : BRIGHT}${lines[0]}${RESET}`);
      clearRow(R - 3);
      if (lines[1]) write(` ${TEXT}${lines[1]}${RESET}`);
      clearRow(R - 2);
      if (lines[2]) write(` ${TEXT}${lines[2]}${RESET}`);
      placeCaret();
    });
  };

  const hint = t("cockpit.hint", locale, {
    kind: t(narrator.kind === "llm" ? "cockpit.hintNarratorAi" : "cockpit.hintNarratorRules", locale),
  });
  const renderInput = (): void => {
    frame(() => {
      const R = rows();
      clearRow(R - 1);
      write(` ${DIM}${hint}${RESET}`);
      // Input row: subtle band so the prompt reads as an input field.
      band(R, ` ${BRIGHT}${BOLD}\u203a${NOBOLD} ${TEXT}${ibuf.join("")}`, BG_INPUT);
      placeCaret();
    });
  };

  // Startup / resize / view switch: repaint every region once.
  const renderAll = (): void => {
    renderHeader();
    renderBody();
    renderQA();
    renderInput();
  };

  // ---- natural-language screen control -------------------------------------
  // `parseScreenCommand` is a module-level pure function (KO/EN -> view patch).

  let headerPending = false;
  const scheduleHeader = (): void => {
    if (headerPending) return;
    headerPending = true;
    setTimeout(() => {
      headerPending = false;
      renderHeader();
    }, 350);
  };

  // ---- narrator (streamed answer) -----------------------------------------
  /** The resource types seen on the live stream, most-frequent first. These are
   * event resource TYPES (e.g. compute.vm), not a named Azure resource-group
   * inventory - we say so, rather than pretend an inventory we do not have. */
  const topResourcesText = (n: number): string => {
    const tops = Object.entries(resourceCounts)
      .sort((a, b) => b[1] - a[1])
      .slice(0, n)
      .map(([name, c]) => `${name} x${c}`);
    return tops.length ? tops.join(", ") : "nothing yet";
  };

  /** A compact live-state overview the narrator (LLM) can request as a tool. */
  const liveOverviewText = (): string =>
    `Live so far - ${handled} events handled: T0=${byTier.t0 ?? 0} T1=${byTier.t1 ?? 0} ` +
    `T2=${byTier.t2 ?? 0} stepped-back=${byTier.abstain ?? 0}; ${autoApplied} auto-applied, ` +
    `${awaitingYou} awaiting you, ${undone} undone, ${errors} errors. ` +
    `By resource type: ${topResourcesText(10)}. ` +
    `These are live event types from the stream, not a named resource-group inventory.`;

  // ---- local answerer ------------------------------------------------------
  // `localAnswer` is a module-level pure function over a stats snapshot.

  const streamReveal = async (): Promise<void> => {
    const total = [...answerTarget].length;
    const step = Math.max(1, Math.round(total / 80));
    while (answerShown < total) {
      answerShown = Math.min(total, answerShown + step);
      renderQA();
      placeCaret();
      // eslint-disable-next-line no-await-in-loop
      await sleep(14);
    }
  };

  // The narrator gets a read-only screen handle so an LLM can also arrange the
  // view (show a chart, focus a resource, pause) from free-form phrasings the
  // local parser above does not cover. It only changes what is displayed.
  const convo: Array<{ role: "user" | "assistant"; content: string }> = [];
  const recordTurn = (q: string, a: string): void => {
    convo.push({ role: "user", content: q }, { role: "assistant", content: a });
    while (convo.length > 12) convo.shift();
  };
  const narratorCtx: NarratorContext = {
    ...ctx,
    live: { overview: liveOverviewText },
    history: convo,
    screen: {
      setView: (patch) => {
        if (patch.mode) view.mode = patch.mode;
        if (patch.focus !== undefined) view.focus = patch.focus;
        if (typeof patch.paused === "boolean") view.paused = patch.paused;
        renderHeader();
        renderBody();
        return t("cockpit.showing", locale, { badge: viewBadge(view, locale) });
      },
    },
  };

  const ask = (q: string): void => {
    busy = true;
    // 1. Screen control (view switch) - handled locally, instantly, no LLM.
    const screen = parseScreenCommand(q, locale);
    if (screen) {
      Object.assign(view, screen.patch);
      renderHeader();
      renderBody();
      thinking = false;
      answerTarget = screen.reply;
      answerShown = 0;
      recordTurn(q, screen.reply);
      void streamReveal().finally(() => {
        busy = false;
        renderInput();
      });
      return;
    }
    // 2. Grounded live-state answers.
    const local = localAnswer(q, { handled, byTier, awaitingYou, autoApplied, undone, activity }, locale);
    if (local !== null) {
      thinking = false;
      answerTarget = local;
      answerShown = 0;
      recordTurn(q, local);
      void streamReveal().finally(() => {
        busy = false;
        renderInput();
      });
      return;
    }
    thinking = true;
    answerTarget = "";
    answerShown = 0;
    renderQA();
    void narrator
      .answer(q, narratorCtx)
      .then(async (a) => {
        thinking = false;
        answerTarget = a;
        answerShown = 0;
        recordTurn(q, a);
        await streamReveal();
      })
      .catch((err: unknown) => {
        thinking = false;
        answerTarget = `I could not complete that: ${(err as Error).message}`;
        answerShown = answerTarget.length;
        renderQA();
      })
      .finally(() => {
        busy = false;
        renderInput();
      });
  };

  const submit = (): void => {
    const q = ibuf.join("").trim();
    ibuf = [];
    icur = 0;
    histIdx = null;
    if (q === "") {
      renderInput();
      return;
    }
    if (q === "/exit" || q === "/quit" || q === "/q") {
      finish();
      return;
    }
    if (history[history.length - 1] !== q) history.push(q);
    lastQ = q;
    renderQA();
    renderInput();
    ask(q);
  };

  // ---- input ---------------------------------------------------------------
  const onData = (d: string): void => {
    if (d === "\x03") {
      finish();
      return;
    }
    if (busy) return;
    if (d === "\r" || d === "\n") return submit();
    if (d === "\x7f" || d === "\b") {
      if (icur > 0) {
        ibuf.splice(icur - 1, 1);
        icur--;
        renderInput();
      }
      return;
    }
    if (d === `${ESC}[D`) {
      if (icur > 0) icur--;
      renderInput();
      return;
    }
    if (d === `${ESC}[C`) {
      if (icur < ibuf.length) icur++;
      renderInput();
      return;
    }
    if (d === `${ESC}[A`) {
      if (history.length === 0) return;
      histIdx = histIdx === null ? history.length - 1 : Math.max(0, histIdx - 1);
      ibuf = [...history[histIdx]!];
      icur = ibuf.length;
      renderInput();
      return;
    }
    if (d === `${ESC}[B`) {
      if (histIdx === null) return;
      histIdx += 1;
      if (histIdx >= history.length) {
        histIdx = null;
        ibuf = [];
      } else ibuf = [...history[histIdx]!];
      icur = ibuf.length;
      renderInput();
      return;
    }
    if (d === "\x01" || d === `${ESC}[H`) {
      icur = 0;
      renderInput();
      return;
    }
    if (d === "\x05" || d === `${ESC}[F`) {
      icur = ibuf.length;
      renderInput();
      return;
    }
    if (d === "\x17") {
      let i = icur;
      while (i > 0 && ibuf[i - 1] === " ") i--;
      while (i > 0 && ibuf[i - 1] !== " ") i--;
      ibuf.splice(i, icur - i);
      icur = i;
      renderInput();
      return;
    }
    if (d === "\x15") {
      ibuf = [];
      icur = 0;
      renderInput();
      return;
    }
    if (d === "\x04") {
      if (ibuf.length === 0) finish();
      return;
    }
    if (d.startsWith(ESC)) return;
    const nl = d.search(/[\r\n]/);
    const printable = (nl >= 0 ? d.slice(0, nl) : d).replace(/[\u0000-\u001f]/g, "");
    if (printable) {
      const ins = [...printable];
      ibuf.splice(icur, 0, ...ins);
      icur += ins.length;
    }
    if (nl >= 0) return submit();
    renderInput();
  };

  // ---- lifecycle -----------------------------------------------------------
  const abort = new AbortController();
  let done!: () => void;
  const finished = new Promise<void>((resolve) => {
    done = resolve;
  });
  const finish = (): void => {
    abort.abort();
    clearInterval(tick);
    stdin.removeListener("data", onData);
    out.removeListener("resize", onResize);
    write(`${ESC}[?25h${ESC}[?1049l`);
    if (typeof stdin.setRawMode === "function") stdin.setRawMode(false);
    stdin.pause();
    stdin.unref?.();
    done();
  };
  const onResize = (): void => {
    write(`${ESC}[2J`);
    renderAll();
  };

  write(`${ESC}[?1049h${ESC}[2J`);
  stdin.setRawMode(true);
  stdin.setEncoding("utf8");
  stdin.resume();
  renderAll();
  stdin.on("data", onData);
  out.on("resize", onResize);

  // One-second heartbeat: sample throughput for the sparkline and keep the
  // overview fresh. Unref'd so it never holds the process open on its own.
  const tick = setInterval(() => {
    const delta = handled - handledAtLastTick;
    handledAtLastTick = handled;
    spark.push(delta);
    if (spark.length > 60) spark.shift();
    if (view.mode === "overview") renderOverview();
  }, 1000);
  tick.unref?.();

  void consumeSse(
    `${apiUrl.replace(/\/$/, "")}/live/stream`,
    onFrame,
    (s) => {
      status = s;
      scheduleHeader();
    },
    abort.signal,
  );

  return finished;
}
