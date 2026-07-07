/**
 * Interactive terminal shell (Ink) - the Copilot-style REPL.
 *
 * The briefing is printed once via <Static> (it scrolls up like a log), then a
 * live input line stays at the bottom so the operator can ask questions or pick
 * a decision card - the console does not exit after the briefing. This
 * interaction loop is terminal-specific; Slack/Teams carry their own button
 * interactions, so it lives in the Ink renderer, not the shared view-model.
 *
 * This is a design mock: there is no live backend, so replies are synthesized
 * (and honestly marked) from the same synthetic payload. Read-only by default.
 */

import { Box, Static, Text, useApp, useInput, useStdin } from "ink";
import type { ReactNode } from "react";
import { useCallback, useEffect, useRef, useState } from "react";

import type { Block, Tone } from "../../view-model/blocks.js";
import type { BriefingPayload } from "../../view-model/contract.js";
import { fetchAuditItems, fetchHilItems, fetchKpi } from "../../data/read-api.js";
import { BlockView } from "./Briefing.js";
import { toneHex } from "./theme.js";

const CARD_WIDTH = 78;

interface LogItem {
  id: string;
  node: ReactNode;
}

interface Pending {
  id: number;
  answer: string;
  loading: boolean;
}

/** Answer a query from the live read API (narrator as a deterministic router). */
async function liveAnswer(q: string, apiUrl: string): Promise<string> {
  const t = q.toLowerCase().trim();
  try {
    if (/(kpi|status|metric|dashboard|health|summary|how many)/.test(t)) {
      const kpi = await fetchKpi(apiUrl);
      return (
        `Live KPI: ${kpi.event_count} events, ${Math.round(kpi.shadow_share * 100)}% shadow, ` +
        `${Math.round(kpi.enforce_share * 100)}% enforce, ${kpi.hil_pending} awaiting you. ` +
        `Last recorded ${kpi.last_recorded_at ?? "-"}.`
      );
    }
    if (/(hil|queue|decision|approv|pending|awaiting)/.test(t)) {
      const items = await fetchHilItems(apiUrl);
      if (items.length === 0) return "The HIL queue is empty - nothing awaiting your decision.";
      return (
        `HIL queue (${items.length}): ` +
        items.map((h) => `${h.action_kind} - ${h.reason}`).join("; ")
      );
    }
    if (/(audit|log|history|recent|activity|happened)/.test(t)) {
      const items = await fetchAuditItems(apiUrl, 5);
      if (items.length === 0) return "No audit entries yet.";
      return (
        "Recent audit: " +
        items.map((a) => `#${a.seq} ${a.action_kind}/${a.mode}`).join(", ")
      );
    }
    const kpi = await fetchKpi(apiUrl);
    return (
      `I match keywords like kpi / hil queue / recent audit, or a card number. ` +
      `Right now: ${kpi.event_count} events, ${Math.round(kpi.shadow_share * 100)}% shadow, ` +
      `${kpi.hil_pending} awaiting you. Free-form natural language (including Korean) ` +
      `is answered by the LLM narrator - a fork drop-in.`
    );
  } catch (err) {
    return `(error) could not reach the read API: ${(err as Error).message}`;
  }
}

/** Synthesize a read-only answer from the synthetic payload (clearly a mock). */
function respond(q: string, p: BriefingPayload | null): string {
  if (!p) {
    return "(mock) No sample briefing loaded. Restart with --source=api to query the live read API, or /exit.";
  }
  const t = q.toLowerCase().trim();
  const num = Number(t);

  if (p.hil.length > 0 && Number.isInteger(num) && num >= 1 && num <= p.hil.length) {
    const item = p.hil[num - 1]!;
    return (
      `${item.title} (${item.actionType}). ${item.why} ` +
      `Confidence: ${item.basis} (${item.basisTech}). Safety: ${item.safety} ` +
      `Approving opens a pull request - ${item.who}`
    );
  }
  if (t === "a" || t === "approve") {
    return "(mock) I would open a pull request for the selected card. Nothing changes until it is merged, and you cannot approve your own request.";
  }
  if (t === "r" || t === "decline") {
    return "(mock) Declined and logged. Nothing changes.";
  }
  if (t === "w" || t === "explain") {
    return `(mock) Pick a card number (1-${p.hil.length || 3}) and I will explain the reasoning behind it.`;
  }
  if (t.includes("payment") || t.includes("restart")) {
    return "payments-api restarted after two out-of-memory events in the last hour (incident #1204). There is a pending proposal to raise its memory 512 MB -> 1 GB (card 1), 91% similar to incident #0847.";
  }
  if (t.includes("spend") || t.includes("cost") || t.includes("budget")) {
    return "(mock) Spending is flat versus last week in this synthetic dataset. One cost rule ('idle disk cleanup') is finishing a 30-day trial with 41/41 correct (card 3).";
  }
  if (t.includes("rule") || t.includes("trial") || t.includes("shadow")) {
    return `${p.shadowCandidates} rules are in trial (shadow mode) - they watch and log but do not act yet. One is ready to promote to live (card 3).`;
  }
  if (
    t.includes("resource") ||
    t.includes("group") ||
    t.includes("inventory") ||
    t.includes("list") ||
    t.includes("show")
  ) {
    return "(mock) No live inventory here - the real console would list resource groups read-only from the inventory snapshot and cite the audit entry. Nothing is ever mutated from the console.";
  }
  if (
    t.includes("kpi") ||
    t.includes("dashboard") ||
    t.includes("metric") ||
    t.includes("status") ||
    t.includes("health")
  ) {
    return `(mock) ${p.autoResolved}/${p.events} events auto-resolved, ${p.rollbacks} rolled back, ${p.overridesActive} paused rules, ${p.shadowCandidates} rules in trial. The real console reads these KPIs read-only.`;
  }
  if (t.includes("audit") || t.includes("log") || t.includes("history")) {
    return "(mock) The audit log is append-only. The real console would page it read-only and let you trace any autonomous action end to end.";
  }
  if (t === "help" || t === "/help" || t === "?") {
    return "Ask about an incident, cost, or trials; type a card number (1-3) to dig in; a / r / w to act on a card. /exit to quit. This is a read-only design mock.";
  }
  if (/[^\x00-\x7f]/.test(q)) {
    return (
      `In this sample: ${p.autoResolved}/${p.events} events auto-resolved, ` +
      `${p.overridesActive} paused rules, ${p.shadowCandidates} in trial. ` +
      `Free-form natural language (including Korean) is answered by the LLM narrator - ` +
      `a fork drop-in. Try a card number (1-${p.hil.length || 3}) or /exit.`
    );
  }
  return '(mock) No live backend here, so I cannot fetch that - on the real console I would look it up read-only and cite the audit entry. Try "why did payments-api restart?", a card number, or /exit.';
}

/** Reveal text left-to-right so replies feel streamed, like a coding CLI. */
function UserLine({ text }: { text: string }) {
  return (
    <Box marginTop={1} width={CARD_WIDTH}>
      <Text>
        <Text color={toneHex("t0")}>{"\u203a"}</Text>
        {" "}
        <Text>{text}</Text>
      </Text>
    </Box>
  );
}

function AnswerLine({ text, tone }: { text: string; tone?: Tone }) {
  return (
    <Box width={CARD_WIDTH}>
      <Text>
        <Text color={toneHex("accent")}>{"\u25c7"}</Text>
        {" "}
        <Text color={toneHex(tone)}>{text}</Text>
      </Text>
    </Box>
  );
}

/** Reveal the answer left-to-right, then signal completion exactly once. */
function StreamingAnswer({ text, onDone }: { text: string; onDone: () => void }) {
  const [shown, setShown] = useState(0);
  const done = useRef(false);
  useEffect(() => {
    if (shown >= text.length) {
      if (!done.current) {
        done.current = true;
        onDone();
      }
      return;
    }
    const step = Math.max(2, Math.round(text.length / 40));
    const id = setTimeout(() => setShown((n) => Math.min(text.length, n + step)), 16);
    return () => clearTimeout(id);
  }, [shown, text, onDone]);
  return <AnswerLine text={text.slice(0, shown)} />;
}

export function App({
  blocks,
  payload,
  apiUrl,
}: {
  blocks: readonly Block[];
  payload?: BriefingPayload | null;
  apiUrl?: string | null;
}) {
  const { exit } = useApp();
  const { isRawModeSupported } = useStdin();
  const [value, setValue] = useState("");
  const [pending, setPending] = useState<Pending | null>(null);
  const nextId = useRef(1);

  // The live input line replaces the static prompt block; briefing blocks are
  // the first permanent log items.
  const briefingItems: LogItem[] = blocks
    .filter((b) => b.type !== "prompt")
    .map((block, i) => ({ id: `b${i}`, node: <BlockView block={block} /> }));
  const [log, setLog] = useState<LogItem[]>([]);
  const items = [...briefingItems, ...log];

  // Without a TTY (piped/CI) there is no interactive input - print and leave.
  // Unref an inherited stdin pipe so it does not keep the process alive.
  useEffect(() => {
    if (!isRawModeSupported) {
      exit();
      process.stdin.unref?.();
    }
  }, [isRawModeSupported, exit]);

  const commit = useCallback((id: number, answer: string) => {
    setLog((prev) => [
      ...prev,
      { id: `a${id}`, node: <AnswerLine text={answer} /> },
    ]);
    setPending(null);
  }, []);

  const submit = (raw: string) => {
    const q = raw.trim();
    setValue("");
    if (q === "") return;
    if (q === "/exit" || q === "/quit" || q === "/q") {
      exit();
      return;
    }
    if (pending) return; // one exchange at a time
    const id = nextId.current++;
    setLog((prev) => [...prev, { id: `q${id}`, node: <UserLine text={q} /> }]);
    // Live read API -> deterministic tool router; otherwise the mock responder.
    if (apiUrl) {
      setPending({ id, answer: "", loading: true });
      void liveAnswer(q, apiUrl).then((a) =>
        setPending({ id, answer: a, loading: false }),
      );
    } else {
      setPending({ id, answer: respond(q, payload ?? null), loading: false });
    }
  };

  // Built-in line editor - compatible with the installed Ink; no extra deps.
  useInput(
    (input, key) => {
      if (key.return) {
        submit(value);
        return;
      }
      if (key.backspace || key.delete) {
        setValue((v) => v.slice(0, -1));
        return;
      }
      if (key.escape) {
        setValue("");
        return;
      }
      if (key.ctrl || key.meta) return;
      // Bulk input (paste, or a harness) may carry the Enter inline as \r/\n;
      // submit the completed line rather than swallowing the newline.
      if (input.includes("\r") || input.includes("\n")) {
        const line = (value + input).split(/\r|\n/)[0] ?? "";
        submit(line);
        return;
      }
      if (input) {
        setValue((v) => v + input);
      }
    },
    { isActive: isRawModeSupported },
  );

  return (
    <Box flexDirection="column">
      <Static items={items}>{(item) => <Box key={item.id}>{item.node}</Box>}</Static>

      {pending ? (
        pending.loading ? (
          <AnswerLine text="..." tone="dim" />
        ) : (
          <StreamingAnswer
            text={pending.answer}
            onDone={() => commit(pending.id, pending.answer)}
          />
        )
      ) : null}

      {isRawModeSupported ? (
        <Box flexDirection="column" marginTop={1}>
          <Box>
            <Text>
              <Text color={toneHex("t0")}>{"\u203a "}</Text>
              <Text>{value}</Text>
              <Text color={toneHex("t0")}>{"\u2588"}</Text>
            </Text>
          </Box>
          <Text color={toneHex("dim")}>
            {value === ""
              ? "  ask a question, a card number (1-3), or /exit"
              : "  read-only - I only look things up unless you ask me to act - /exit to quit"}
          </Text>
        </Box>
      ) : (
        <Text color={toneHex("dim")}>
          {"  (interactive input needs a TTY; run this in a real terminal)"}
        </Text>
      )}
    </Box>
  );
}
