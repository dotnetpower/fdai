/**
 * Live cockpit session orchestration.
 *
 * The cockpit is a read-only alternate-screen view over real control-loop SSE
 * frames. Rendering and raw input remain incremental so the terminal cursor
 * stays at the edit caret and IME composition is not disturbed.
 */

import { randomUUID } from "node:crypto";

import { withChannelLocale, type CliChannelContext } from "./channel-context.js";
import { createInputController } from "./cockpit-input.js";
import { CockpitRenderer } from "./cockpit-renderer.js";
import { consumeSse } from "./cockpit-sse.js";
import {
  createCockpitState,
  liveOverviewText,
  reduceStageFrame,
} from "./cockpit-state.js";
import { parseScreenCommand, viewBadge } from "./cockpit-view.js";
import { askChat } from "./data/read-api.js";

export { parseScreenCommand, tierLabel, viewBadge } from "./cockpit-view.js";

const DIM = "\x1b[38;2;124;132;139m";
const RESET = "\x1b[0m";
const ESC = "\x1b";
const sleep = (milliseconds: number) =>
  new Promise((resolve) => setTimeout(resolve, milliseconds));

export async function startCockpit(context: CliChannelContext): Promise<void> {
  const input = process.stdin;
  const output = process.stdout;
  const apiUrl = context.apiUrl!;
  if (!input.isTTY || typeof input.setRawMode !== "function") {
    output.write(
      `${DIM}live cockpit needs a TTY; run in a real terminal (streaming ${apiUrl}/live/stream)${RESET}\n`,
    );
    return;
  }

  const locale = context.locale ?? "en";
  const sessionId = randomUUID();
  const state = createCockpitState();
  const renderer = new CockpitRenderer(state, locale, output);
  const abort = new AbortController();
  let resolveFinished!: () => void;
  const finished = new Promise<void>((resolve) => {
    resolveFinished = resolve;
  });
  let tick!: NodeJS.Timeout;
  let onData!: (data: string) => void;

  const onResize = (): void => {
    renderer.write(`${ESC}[2J`);
    renderer.renderAll();
  };

  const finish = (): void => {
    abort.abort();
    clearInterval(tick);
    input.removeListener("data", onData);
    output.removeListener("resize", onResize);
    renderer.write(`${ESC}[?25h${ESC}[?1049l`);
    if (typeof input.setRawMode === "function") input.setRawMode(false);
    input.pause();
    input.unref?.();
    resolveFinished();
  };

  const conversation: Array<{ role: "user" | "assistant"; content: string }> = [];
  const recordTurn = (question: string, answer: string): void => {
    conversation.push(
      { role: "user", content: question },
      { role: "assistant", content: answer },
    );
    while (conversation.length > 12) conversation.shift();
  };

  const streamReveal = async (): Promise<void> => {
    const total = [...state.answerTarget].length;
    const step = Math.max(1, Math.round(total / 80));
    while (state.answerShown < total) {
      state.answerShown = Math.min(total, state.answerShown + step);
      renderer.renderQA();
      renderer.placeCaret();
      // eslint-disable-next-line no-await-in-loop
      await sleep(14);
    }
  };

  const ask = (question: string): void => {
    state.busy = true;
    const screen = parseScreenCommand(question, locale);
    if (screen) {
      Object.assign(state.view, screen.patch);
      renderer.renderHeader();
      renderer.renderBody();
      state.thinking = false;
      state.answerTarget = screen.reply;
      state.answerShown = 0;
      recordTurn(question, screen.reply);
      void streamReveal().finally(() => {
        state.busy = false;
        renderer.renderInput();
      });
      return;
    }

    state.thinking = true;
    state.answerTarget = "";
    state.answerShown = 0;
    renderer.renderQA();
    void askChat(apiUrl, question, {
      viewContext: withChannelLocale(locale, {
        routeId: "cli-live",
        routeLabel: "Forward Deployed Agents",
        purpose: "Read-only live control-loop activity and routing outcomes.",
        facts: {
          handled: state.handled,
          by_tier: { ...state.byTier },
          awaiting_approval: state.awaitingYou,
          auto_applied: state.autoApplied,
          undone: state.undone,
          errors: state.errors,
          active_view: viewBadge(state.view, locale),
          overview: liveOverviewText(state),
        },
        records: {
          activity: state.activity.slice(-40).map((item) => ({
            resource_type: item.resource,
            summary: item.text,
            tier: item.tier,
          })),
        },
      }),
      history: conversation,
      sessionId,
    })
      .then((reply) => reply.answer)
      .then(async (answer) => {
        state.thinking = false;
        state.answerTarget = answer;
        state.answerShown = 0;
        recordTurn(question, answer);
        await streamReveal();
      })
      .catch((error: unknown) => {
        state.thinking = false;
        state.answerTarget = `I could not complete that: ${(error as Error).message}`;
        state.answerShown = state.answerTarget.length;
        renderer.renderQA();
      })
      .finally(() => {
        state.busy = false;
        renderer.renderInput();
      });
  };

  const submit = (): void => {
    const question = state.input.join("").trim();
    state.input = [];
    state.cursor = 0;
    state.historyIndex = null;
    if (question === "") {
      renderer.renderInput();
      return;
    }
    if (question === "/exit" || question === "/quit" || question === "/q") {
      finish();
      return;
    }
    if (state.history[state.history.length - 1] !== question) state.history.push(question);
    state.lastQ = question;
    renderer.renderQA();
    renderer.renderInput();
    ask(question);
  };

  onData = createInputController(state, renderer, submit, finish);
  renderer.write(`${ESC}[?1049h${ESC}[2J`);
  input.setRawMode(true);
  input.setEncoding("utf8");
  input.resume();
  renderer.renderAll();
  input.on("data", onData);
  output.on("resize", onResize);

  tick = setInterval(() => {
    const delta = state.handled - state.handledAtLastTick;
    state.handledAtLastTick = state.handled;
    state.spark.push(delta);
    if (state.spark.length > 60) state.spark.shift();
    renderer.renderOverviewTick();
  }, 1000);
  tick.unref?.();

  void consumeSse(
    `${apiUrl.replace(/\/$/, "")}/live/stream`,
    (frame) => {
      const activity = reduceStageFrame(state, frame, locale);
      if (activity) {
        renderer.onNewActivity(activity);
        renderer.scheduleHeader();
      }
    },
    (status) => {
      state.status = status;
      renderer.scheduleHeader();
    },
    abort.signal,
  );

  return finished;
}
