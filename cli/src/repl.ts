/**
 * Interactive REPL with a bottom-fixed input, like a coding CLI.
 *
 * The terminal is split with a DEC scroll region: the top area scrolls the
 * conversation, and the bottom two lines are a fixed input box (a hint line + a
 * prompt line). Input is read in raw mode and edited in place, and the REAL
 * terminal cursor is positioned at the caret - so IME composition (Korean and
 * any language) renders exactly at the cursor, and the input never drifts.
 *
 * There is no full-screen React repaint here (that is what fought the input
 * cursor); we only rewrite the two-line input box. Read-only: answers come from
 * the narrator seam, which only calls read-only console tools.
 */

import { randomUUID } from "node:crypto";

import { withChannelLocale, type CliChannelContext } from "./channel-context.js";
import { askChat, type ChatHistoryTurn } from "./data/operator-api.js";

const TEAL = "\x1b[38;2;99;166;156m";
const DIM = "\x1b[38;2;124;132;139m";
const RESET = "\x1b[0m";

const ESC = "\x1b";
const out = process.stdout;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

// East-Asian wide (2-cell) codepoints - Hangul, CJK, fullwidth, etc.
function charWidth(cp: number): number {
  if (
    (cp >= 0x1100 && cp <= 0x115f) ||
    (cp >= 0x2e80 && cp <= 0xa4cf) ||
    (cp >= 0xac00 && cp <= 0xd7a3) ||
    (cp >= 0xf900 && cp <= 0xfaff) ||
    (cp >= 0xfe30 && cp <= 0xfe4f) ||
    (cp >= 0xff00 && cp <= 0xff60) ||
    (cp >= 0xffe0 && cp <= 0xffe6) ||
    (cp >= 0x20000 && cp <= 0x3fffd)
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

export async function startRepl(ctx: CliChannelContext): Promise<void> {
  const stdin = process.stdin;
  // Sample mode is a renderer fixture only. Interactive turns always go
  // through the shared Operator API coordinator.
  if (!ctx.apiUrl || !stdin.isTTY || typeof stdin.setRawMode !== "function") return;
  const apiUrl = ctx.apiUrl;

  const chatHistory: ChatHistoryTurn[] = [];
  const sessionId = randomUUID();
  const promptStr = `${TEAL}\u203a ${RESET}`;
  const promptW = 2; // "> " display width
  const hintText = "narrator: shared-api - ask a question or /exit - Up/Down history, Ctrl+W word";

  let buf: string[] = [];
  let cur = 0;
  const history: string[] = [];
  let histIdx: number | null = null;
  let busy = false;

  const rows = () => out.rows ?? 24;

  const write = (s: string): void => {
    out.write(s);
  };
  const cursorTo = (row: number, col: number): void => write(`${ESC}[${row};${col}H`);

  // Split the screen: scroll region = top .. (rows-2); fixed box = last 2 rows.
  const setLayout = (): void => {
    const r = rows();
    write(`${ESC}[1;${Math.max(1, r - 2)}r`);
    write(`${ESC}8`); // restore the saved conversation cursor
  };

  const renderInput = (): void => {
    const r = rows();
    write(`${ESC}[?25l`); // hide cursor while drawing
    cursorTo(r - 1, 1);
    write(`${ESC}[2K${DIM}  ${hintText}${RESET}`);
    cursorTo(r, 1);
    write(`${ESC}[2K${promptStr}${buf.join("")}`);
    const caretCol = 1 + promptW + strWidth(buf.slice(0, cur).join(""));
    cursorTo(r, caretCol);
    write(`${ESC}[?25h`); // show cursor at the caret (IME composes here)
  };

  const appendConv = (s: string): void => {
    write(`${ESC}8`); // restore conversation cursor
    write(s);
    write(`${ESC}7`); // save conversation cursor
    renderInput();
  };

  const streamAnswer = async (text: string): Promise<void> => {
    write(`${ESC}8`);
    write(`${TEAL}\u203a${RESET} `);
    const chars = [...text];
    const step = Math.max(1, Math.round(chars.length / 60));
    for (let i = 0; i < chars.length; i += step) {
      write(chars.slice(i, i + step).join(""));
      await sleep(8);
    }
    write("\n");
    write(`${ESC}7`);
    renderInput();
  };

  const cleanup = (): void => {
    write(`${ESC}[r`); // reset scroll region
    write(`${ESC}[?25h`);
    cursorTo(rows(), 1);
    write("\n");
    if (typeof stdin.setRawMode === "function") stdin.setRawMode(false);
    stdin.pause();
    stdin.unref?.(); // let the process exit once the REPL is done
  };

  let done!: () => void;
  const finished = new Promise<void>((resolve) => {
    done = resolve;
  });
  const finish = (): void => {
    cleanup();
    stdin.removeListener("data", onData);
    out.removeListener("resize", onResize);
    done();
  };

  const submit = (): void => {
    const q = buf.join("").trim();
    appendConv(`${TEAL}\u203a${RESET} ${buf.join("")}\n`);
    buf = [];
    cur = 0;
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
    busy = true;
    renderInput();
    const answer = askChat(apiUrl, q, {
      viewContext: withChannelLocale(ctx.locale ?? "en", {
        routeId: "cli-briefing",
        routeLabel: "Operator briefing",
        records: ctx.payload ?? {},
      }),
      history: chatHistory,
      sessionId,
    }).then((reply) => reply.answer);
    void answer
      .then(async (a) => {
        await streamAnswer(a);
        chatHistory.push(
          { role: "user", content: q },
          { role: "assistant", content: a },
        );
        while (chatHistory.length > 12) chatHistory.shift();
      })
      .catch((err: unknown) => appendConv(`(error) ${(err as Error).message}\n`))
      .finally(() => {
        busy = false;
        renderInput();
      });
  };

  const onResize = (): void => {
    setLayout();
    renderInput();
  };

  const onData = (chunk: string): void => {
    const d = chunk;
    if (d === "\x03") {
      finish();
      return;
    } // Ctrl+C
    if (busy) return; // ignore input while an answer streams
    if (d === "\r" || d === "\n") {
      submit();
      return;
    }
    if (d === "\x7f" || d === "\b") {
      if (cur > 0) {
        buf.splice(cur - 1, 1);
        cur--;
        renderInput();
      }
      return;
    }
    if (d === `${ESC}[D`) {
      if (cur > 0) cur--;
      renderInput();
      return;
    }
    if (d === `${ESC}[C`) {
      if (cur < buf.length) cur++;
      renderInput();
      return;
    }
    if (d === `${ESC}[A`) {
      if (history.length === 0) return;
      histIdx = histIdx === null ? history.length - 1 : Math.max(0, histIdx - 1);
      buf = [...history[histIdx]!];
      cur = buf.length;
      renderInput();
      return;
    }
    if (d === `${ESC}[B`) {
      if (histIdx === null) return;
      histIdx += 1;
      if (histIdx >= history.length) {
        histIdx = null;
        buf = [];
      } else {
        buf = [...history[histIdx]!];
      }
      cur = buf.length;
      renderInput();
      return;
    }
    if (d === "\x01" || d === `${ESC}[H`) {
      cur = 0;
      renderInput();
      return;
    }
    if (d === "\x05" || d === `${ESC}[F`) {
      cur = buf.length;
      renderInput();
      return;
    }
    if (d === "\x17") {
      let i = cur;
      while (i > 0 && buf[i - 1] === " ") i--;
      while (i > 0 && buf[i - 1] !== " ") i--;
      buf.splice(i, cur - i);
      cur = i;
      renderInput();
      return;
    }
    if (d === "\x15") {
      buf = [];
      cur = 0;
      renderInput();
      return;
    }
    if (d === "\x04") {
      if (buf.length === 0) finish();
      return;
    }
    if (d.startsWith(ESC)) return; // ignore other escape sequences
    const nl = d.search(/[\r\n]/);
    const printable = (nl >= 0 ? d.slice(0, nl) : d).replace(/[\u0000-\u001f]/g, "");
    if (printable) {
      const insert = [...printable];
      buf.splice(cur, 0, ...insert);
      cur += insert.length;
    }
    if (nl >= 0) {
      submit();
      return;
    }
    renderInput();
  };

  // Boot: raw mode, save the conversation cursor (just below the briefing), set
  // the split, and draw the input box.
  stdin.setRawMode(true);
  stdin.setEncoding("utf8");
  stdin.resume();
  write(`${ESC}7`);
  setLayout();
  renderInput();
  stdin.on("data", onData);
  out.on("resize", onResize);

  return finished;
}
