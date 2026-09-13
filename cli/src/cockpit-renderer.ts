import { clip, hbar, inputViewport, sparkline, strWidth, wrap } from "./cockpit-format.js";
import type { Activity, CockpitState } from "./cockpit-state.js";
import { tierLabel, viewBadge } from "./cockpit-view.js";
import { t, type Locale } from "./i18n/index.js";
import {
  MIN_TERMINAL_COLUMNS,
  MIN_TERMINAL_ROWS,
} from "./terminal-capabilities.js";

const BRAND = "\x1b[38;2;99;166;156m";
const BRIGHT = "\x1b[38;2;122;214;196m";
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
const BG_HEADER = "\x1b[48;2;18;40;44m";
const BG_BAR = "\x1b[48;2;15;22;26m";
const BG_INPUT = "\x1b[48;2;20;28;33m";
const ON_BAR = "\x1b[38;2;150;160;170m";

const stripAnsi = (text: string): string =>
  // eslint-disable-next-line no-control-regex
  text.replace(/\x1b\[[0-9;]*m/g, "");

const THINKING_FRAMES = [".", "..", "..."];

const tierColor = (tier: string): string =>
  tier === "t0" ? BRAND : tier === "t1" ? STEEL : tier === "t2" ? PLUM : DIM;

export class CockpitRenderer {
  private buffer: string | null = null;
  private readonly promptWidth = 3;
  private readonly feedTop = 5;
  private headerPending = false;
  private headerTimer: NodeJS.Timeout | null = null;
  private disposed = false;

  constructor(
    private readonly state: CockpitState,
    private readonly locale: Locale,
    private readonly output: NodeJS.WriteStream,
    private readonly color = true,
  ) {}

  write(text: string): void {
    if (this.disposed) return;
    const rendered = this.color ? text : stripAnsi(text);
    if (this.buffer !== null) this.buffer += rendered;
    else this.output.write(rendered);
  }

  private frame(render: () => void): void {
    if (this.disposed) return;
    if (this.buffer !== null) {
      render();
      return;
    }
    this.buffer = "";
    render();
    const payload = this.buffer;
    this.buffer = null;
    this.output.write(`${ESC}[?2026h${payload}${ESC}[?2026l`);
  }

  private rows(): number {
    return this.output.rows && this.output.rows > 0 ? this.output.rows : 24;
  }

  private columns(): number {
    return this.output.columns && this.output.columns > 0 ? this.output.columns : 80;
  }

  private cursorTo(row: number, column: number): void {
    this.write(`${ESC}[${row};${column}H`);
  }

  private clearRow(row: number): void {
    this.cursorTo(row, 1);
    this.write(`${ESC}[2K`);
  }

  placeCaret(): void {
    const viewport = inputViewport(
      this.state.input,
      this.state.cursor,
      Math.max(1, this.columns() - this.promptWidth - 1),
    );
    this.cursorTo(
      Math.max(1, this.rows()),
      Math.min(this.columns(), 1 + this.promptWidth + viewport.caretWidth),
    );
  }

  private hasMinimumLayout(): boolean {
    return this.columns() >= MIN_TERMINAL_COLUMNS && this.rows() >= MIN_TERMINAL_ROWS;
  }

  private renderTooSmall(): void {
    this.frame(() => {
      const message = t("cockpit.terminalTooSmall", this.locale, {
        columns: MIN_TERMINAL_COLUMNS,
        rows: MIN_TERMINAL_ROWS,
      });
      this.write(`${ESC}[2J${ESC}[1;1H${clip(message, Math.max(1, this.columns()))}`);
      this.cursorTo(Math.max(1, this.rows()), 1);
    });
  }

  private feedBottom(): number {
    return Math.max(this.feedTop, this.rows() - 7);
  }

  private band(row: number, content: string, background: string): void {
    const columns = this.columns();
    const padding = Math.max(0, columns - 1 - strWidth(stripAnsi(content)));
    this.clearRow(row);
    this.write(`${background}${content}${" ".repeat(padding)}${RESET}`);
  }

  private drawFeedLine(activity: Activity): string {
    const resource = clip(activity.resource, 22).padEnd(22);
    const tierTag = `${tierColor(activity.tier)}${tierLabel(activity.tier, this.locale)}${RESET}`;
    return `  ${activity.marker} ${TEXT}${resource}${RESET} ${DIM}${clip(activity.text, this.columns() - 40)}${RESET}  ${tierTag}`;
  }

  renderHeader(): void {
    if (!this.hasMinimumLayout()) return this.renderTooSmall();
    this.frame(() => {
      const columns = this.columns();
      const status = this.state.status === "live"
        ? t("cockpit.header.statusLive", this.locale)
        : this.state.status === "connecting"
          ? t("cockpit.header.statusConnecting", this.locale)
          : t("cockpit.header.statusDegraded", this.locale);
      const readOnly = t("cockpit.header.readOnly", this.locale).toUpperCase();
      const badge = viewBadge(this.state.view, this.locale);
      const header = ` \u2726 FDAI Console   ${status.toUpperCase()}   ${readOnly}   ${badge}`;
      this.band(
        1,
        `${BRIGHT}${BOLD}${clip(header, columns - 1)}${NOBOLD}`,
        BG_HEADER,
      );
      const summary = t("cockpit.header.summary", this.locale, {
        handled: this.state.handled,
        t0: this.state.byTier.t0 ?? 0,
        abstain: this.state.byTier.abstain ?? 0,
        auto: this.state.autoApplied,
        awaiting: this.state.awaitingYou,
      });
      this.clearRow(2);
      this.write(` ${TEXT}${clip(summary, columns - 2)}${RESET}`);
      this.clearRow(3);
      const auth = this.state.authMode === "local-azure-cli"
        ? t("cockpit.header.azureCli", this.locale)
        : t("cockpit.header.apiSession", this.locale);
      this.write(
        ` ${DIM}${clip(`${auth}  ${t("cockpit.header.trust", this.locale)}`, columns - 2)}${RESET}`,
      );
      this.band(
        4,
        ` ${BRIGHT}${BOLD}${badge}${NOBOLD}${ON_BAR}   ${clip(
          t("cockpit.header.commands", this.locale),
          Math.max(0, columns - strWidth(badge) - 6),
        )}`,
        BG_BAR,
      );
      this.placeCaret();
    });
  }

  scheduleHeader(): void {
    if (this.headerPending || this.disposed) return;
    this.headerPending = true;
    this.headerTimer = setTimeout(() => {
      this.headerPending = false;
      this.headerTimer = null;
      this.renderHeader();
    }, 350);
    this.headerTimer.unref?.();
  }

  dispose(): void {
    this.disposed = true;
    if (this.headerTimer !== null) clearTimeout(this.headerTimer);
    this.headerTimer = null;
    this.headerPending = false;
  }

  private visibleActivity(): Activity[] {
    return this.state.view.mode === "focus" && this.state.view.focus
      ? this.state.activity.filter((item) => item.resource.includes(this.state.view.focus!))
      : this.state.activity;
  }

  private renderFeedFull(): void {
    this.frame(() => {
      const bottom = this.feedBottom();
      const feedRows = bottom - this.feedTop + 1;
      const slice = this.visibleActivity().slice(-feedRows);
      for (let index = 0; index < feedRows; index++) {
        this.clearRow(this.feedTop + index);
        const activity = slice[index];
        if (activity) this.write(this.drawFeedLine(activity));
      }
      this.placeCaret();
    });
  }

  private pushFeed(activity: Activity): void {
    this.frame(() => {
      const bottom = this.feedBottom();
      this.write(`${ESC}[${this.feedTop};${bottom}r`);
      this.write(`${ESC}[S`);
      this.write(`${ESC}[r`);
      this.write(`${ESC}[${bottom};1H${ESC}[2K`);
      this.write(this.drawFeedLine(activity));
      this.placeCaret();
    });
  }

  onNewActivity(activity: Activity): void {
    if (!this.hasMinimumLayout()) return;
    if (this.state.view.paused || this.state.view.mode === "overview") return;
    if (
      this.state.view.mode === "focus" &&
      this.state.view.focus &&
      !activity.resource.includes(this.state.view.focus)
    ) {
      return;
    }
    this.pushFeed(activity);
  }

  private renderOverview(): void {
    this.frame(() => {
      const bottom = this.feedBottom();
      for (let row = this.feedTop; row <= bottom; row++) this.clearRow(row);
      const columns = this.columns();
      const barWidth = Math.max(16, Math.min(38, columns - 44));
      let row = this.feedTop;
      const line = (content = ""): void => {
        if (row > bottom) return;
        this.cursorTo(row, 3);
        this.write(content);
        row++;
      };
      const total = Math.max(1, this.state.handled);
      line(`${BRIGHT}${BOLD}${t("cockpit.overview.routingMix", this.locale)}${RESET}`);
      const tiers: Array<[string, number, string]> = [
        [t("cockpit.overview.tierT0", this.locale), this.state.byTier.t0 ?? 0, BRAND],
        [t("cockpit.overview.tierT1", this.locale), this.state.byTier.t1 ?? 0, STEEL],
        [t("cockpit.overview.tierT2", this.locale), this.state.byTier.t2 ?? 0, PLUM],
        [t("cockpit.overview.tierAbstain", this.locale), this.state.byTier.abstain ?? 0, DIM],
      ];
      for (const [label, count, color] of tiers) {
        line(
          `${TEXT}${label.padEnd(16)}${RESET} ${hbar(count / total, barWidth, color)} ` +
            `${color}${String(count).padStart(4)}${RESET} ${DIM}${Math.round((count / total) * 100)}%${RESET}`,
        );
      }
      line();
      line(
        `${BRIGHT}${BOLD}${t("cockpit.overview.throughput", this.locale)}${RESET}  ` +
          `${BRAND}${sparkline(this.state.spark, Math.min(50, columns - 24))}${RESET}` +
          ` ${DIM}${t("cockpit.overview.eventsPerSec", this.locale)}${RESET}`,
      );
      line();
      line(`${BRIGHT}${BOLD}${t("cockpit.overview.outcomes", this.locale)}${RESET}`);
      line(
        `${SAGE}\u2713 ${this.state.autoApplied}${RESET} ${DIM}${t("cockpit.overview.autoApplied", this.locale)}${RESET}    ` +
          `${TERRA}\u2691 ${this.state.awaitingYou}${RESET} ${DIM}${t("cockpit.overview.awaitingYou", this.locale)}${RESET}    ` +
          `${DIM}\u21ba ${this.state.undone} ${t("cockpit.overview.undone", this.locale)}    ` +
          `\u26a0 ${this.state.errors} ${t("cockpit.overview.errors", this.locale)}${RESET}`,
      );
      line();
      line(`${BRIGHT}${BOLD}${t("cockpit.overview.topResources", this.locale)}${RESET}`);
      const resources = Object.entries(this.state.resourceCounts)
        .sort((left, right) => right[1] - left[1])
        .slice(0, Math.max(1, bottom - row - 1));
      const maximum = Math.max(1, ...resources.map((entry) => entry[1]));
      for (const [name, count] of resources) {
        line(
          `${TEXT}${clip(name, 22).padEnd(22)}${RESET} ` +
            `${hbar(count / maximum, barWidth, BRAND)} ${DIM}${count}${RESET}`,
        );
      }
      this.placeCaret();
    });
  }

  renderBody(): void {
    if (!this.hasMinimumLayout()) return this.renderTooSmall();
    if (this.state.view.mode === "overview") this.renderOverview();
    else this.renderFeedFull();
  }

  renderQA(): void {
    if (!this.hasMinimumLayout()) return this.renderTooSmall();
    this.frame(() => {
      const rows = this.rows();
      const columns = this.columns();
      this.clearRow(rows - 6);
      this.write(` ${DIM}${"\u2500".repeat(Math.min(columns - 2, 98))}${RESET}`);
      this.clearRow(rows - 5);
      if (this.state.lastQ) {
        this.write(
          ` ${DIM}${t("cockpit.qa.you", this.locale)}${RESET} ${BRAND}\u203a${RESET} ` +
            `${TEXT}${clip(this.state.lastQ, columns - 8)}${RESET}`,
        );
      }
      this.clearRow(rows - 4);
      const elapsed = this.state.questionStartedAt === null
        ? null
        : Math.max(0, Date.now() - this.state.questionStartedAt);
      const thinkingSuffix = THINKING_FRAMES[
        this.state.thinkingFrame % THINKING_FRAMES.length
      ];
      const meta = this.state.thinking
        ? `${t("cockpit.qa.working", this.locale)}${thinkingSuffix}${
            elapsed === null ? "" : `  ${formatDuration(elapsed)}`
          }`
        : [
            safeModelLabel(this.state.answerModel),
            this.state.answerLatencyMs === null
              ? ""
              : formatDuration(this.state.answerLatencyMs),
          ]
            .filter(Boolean)
            .join("  ");
      const assistant = t("cockpit.qa.assistant", this.locale);
      this.write(
        ` ${BRIGHT}${BOLD}\u2726 ${assistant}${NOBOLD}${RESET}${
          meta ? ` ${DIM}${meta}${RESET}` : ""
        }`,
      );
      const shown = this.state.thinking
        ? t("cockpit.qa.waiting", this.locale)
        : this.state.answerTarget.slice(0, this.state.answerShown);
      const lines = wrap(shown, columns - 4, 2);
      this.clearRow(rows - 3);
      if (lines[0]) this.write(`   ${this.state.thinking ? DIM : TEXT}${lines[0]}${RESET}`);
      this.clearRow(rows - 2);
      if (lines[1]) this.write(`   ${TEXT}${lines[1]}${RESET}`);
      this.placeCaret();
    });
  }

  renderInput(): void {
    if (!this.hasMinimumLayout()) return this.renderTooSmall();
    this.frame(() => {
      const rows = this.rows();
      const hint = t("cockpit.hint", this.locale, {
        kind: t("cockpit.hintNarratorAi", this.locale),
      });
      const viewport = inputViewport(
        this.state.input,
        this.state.cursor,
        Math.max(1, this.columns() - this.promptWidth - 1),
      );
      this.clearRow(rows - 1);
      this.write(` ${DIM}${clip(hint, this.columns() - 2)}${RESET}`);
      this.band(
        rows,
        ` ${BRIGHT}${BOLD}\u203a${NOBOLD} ${TEXT}${viewport.text}`,
        BG_INPUT,
      );
      this.placeCaret();
    });
  }

  renderAll(): void {
    if (!this.hasMinimumLayout()) return this.renderTooSmall();
    this.renderHeader();
    this.renderBody();
    this.renderQA();
    this.renderInput();
  }

  renderOverviewTick(): void {
    if (this.state.view.mode === "overview") this.renderOverview();
  }
}

function formatDuration(milliseconds: number): string {
  if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`;
  return `${(milliseconds / 1000).toFixed(1)} s`;
}

function safeModelLabel(value: string): string {
  return clip(value.replace(/[\u0000-\u001f\u007f]/g, ""), 28);
}
