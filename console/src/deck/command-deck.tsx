/**
 * CommandDeck - a screen-aware conversational surface.
 *
 * Design goals (deliberately NOT a corner bubble):
 * - Always visible as a slim bar pinned to the bottom of the viewport,
 *   inviting a question. Cmd+K / Ctrl+K / `/` focuses it.
 * - On focus it expands into a full-viewport overlay split into two
 *   columns: the transcript on the left, the "what I see" digest on
 *   the right. This is the "overwhelming" gesture - the deck is not a
 *   pop-up, it is the operator workspace momentarily.
 * - The right column shows the current ViewSnapshot, so the operator
 *   literally sees what the assistant grounds its answers on. Nothing
 *   hidden.
 * - Purely read-only: the deck can invoke the deterministic answerer
 *   and (future) an LLM narrator behind the same seam. It never issues
 *   privileged calls.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "preact/hooks";
import {
  askBackendStream,
  probeBackend,
  type BackendHealth,
  type BackendTurn,
  type RouterSnapshot,
} from "./backend";
import { useViewContext } from "./context";
import {
  EMPTY_HISTORY,
  record as recordHistory,
  recallNewer,
  recallOlder,
} from "./draft-history";
import { GroundedReply } from "./grounded-reply";
import { RetrievalTrace } from "./retrieval-trace";
import { introSuggestions } from "./intro-suggestions";
import { isNearBottom } from "./scroll-stick";
import { parseTurns, serializeTurns, TRANSCRIPT_KEY } from "./transcript-store";

interface Turn {
  readonly id: string;
  readonly role: "operator" | "deck";
  readonly text: string;
  readonly citations?: readonly { readonly label: string; readonly value?: string }[];
  readonly followUps?: readonly string[];
  readonly source?: string;
  readonly router?: RouterSnapshot;
  /** True while a deck reply is still streaming tokens in. */
  readonly streaming?: boolean;
  readonly at: string;
}

function shortTime(): string {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}

function newId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

/** Tab-scoped storage, guarded so a disabled/absent store never throws. */
function sessionStore(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.sessionStorage : null;
  } catch {
    return null;
  }
}

/**
 * Multi-line tooltip listing every routed candidate's rolling p50 latency
 * and sample count. ``undefined`` when no router is attached so callers
 * can fall back to a plain label.
 */
function routerTooltip(router: RouterSnapshot | undefined): string | undefined {
  if (!router) return undefined;
  const lines = router.candidates.map((c) => {
    const p50 = c.p50_ms === null ? "-" : `${Math.round(c.p50_ms)}ms`;
    const p95 = c.p95_ms === null ? "-" : `${Math.round(c.p95_ms)}ms`;
    const marker = c.deployment === router.chose ? "* " : "  ";
    return `${marker}${c.deployment} · p50 ${p50} · p95 ${p95} · n=${c.samples}`;
  });
  return `auto-router (${router.reason}) chose ${router.chose}\n${lines.join("\n")}`;
}

export function CommandDeck() {
  const snapshot = useViewContext();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [turns, setTurns] = useState<readonly Turn[]>(() => {
    const store = sessionStore();
    return store ? parseTurns(store.getItem(TRANSCRIPT_KEY)) : [];
  });
  const [pending, setPending] = useState(false);
  const [health, setHealth] = useState<BackendHealth | null>(null);
  const [srStatus, setSrStatus] = useState("");
  const [inFlight, setInFlight] = useState(false);
  const [stuck, setStuck] = useState(true);
  const abortRef = useRef<AbortController | null>(null);
  const inFlightRef = useRef(false);
  const historyRef = useRef(EMPTY_HISTORY);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const overlayRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const scrollerRef = useRef<HTMLDivElement | null>(null);

  // Preflight probe: hit /chat/health once so the deck header can show
  // the operator whether the LLM is wired BEFORE they ask.
  useEffect(() => {
    let cancelled = false;
    void probeBackend().then((h) => {
      if (!cancelled) setHealth(h);
    });
    return () => {
      cancelled = true;
    };
  }, []);

  const focusInput = useCallback(() => {
    // requestAnimationFrame lets the overlay layout before the caret jumps in.
    requestAnimationFrame(() => inputRef.current?.focus());
  }, []);

  // Mirror in-flight state into a ref so the global key handler can read it
  // without re-binding its listener every turn.
  useEffect(() => {
    inFlightRef.current = inFlight;
  }, [inFlight]);

  const openDeck = useCallback(() => {
    // Remember what had focus so we can restore it when the modal closes.
    restoreFocusRef.current = (document.activeElement as HTMLElement | null) ?? null;
    setOpen(true);
    focusInput();
  }, [focusInput]);

  const closeDeck = useCallback(() => {
    setOpen(false);
    // Return focus to the element that opened the deck (a11y: modal contract).
    const target = restoreFocusRef.current;
    if (target && typeof target.focus === "function") {
      requestAnimationFrame(() => target.focus());
    }
  }, []);

  // Trap Tab within the open overlay so keyboard focus cannot escape the modal
  // to the read-only page behind it (aria-modal contract).
  const onOverlayKeyDown = useCallback((e: KeyboardEvent) => {
    if (e.key !== "Tab") return;
    const root = overlayRef.current;
    if (!root) return;
    const focusable = Array.from(
      root.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]), select:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ),
    ).filter((el) => el.offsetParent !== null || el === document.activeElement);
    if (focusable.length === 0) return;
    const first = focusable[0]!;
    const last = focusable[focusable.length - 1]!;
    const active = document.activeElement as HTMLElement | null;
    if (e.shiftKey && active === first) {
      e.preventDefault();
      last.focus();
    } else if (!e.shiftKey && active === last) {
      e.preventDefault();
      first.focus();
    }
  }, []);

  // While the deck overlay is open, mark the document so the persistent left
  // rail can stack above the overlay (see `body.deck-open .left-rail` in
  // styles.css). The rail's navigation popover opens into the overlay region;
  // because the rail is a lower stacking context, without this the popover
  // renders BEHIND the chat and cannot be clicked. Scoped to the open state so
  // the rule-detail drawer scrim (which should dim the rail) is unaffected.
  useEffect(() => {
    const cls = "deck-open";
    if (open) document.body.classList.add(cls);
    else document.body.classList.remove(cls);
    return () => document.body.classList.remove(cls);
  }, [open]);

  // Keyboard: Cmd/Ctrl+K, `/` opens; Escape closes.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      const target = e.target as HTMLElement | null;
      const inField = target?.tagName === "INPUT" ||
        target?.tagName === "TEXTAREA" ||
        target?.isContentEditable === true;
      if ((e.key === "k" || e.key === "K") && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        if (open) closeDeck();
        else openDeck();
        return;
      }
      if (!inField && e.key === "/" && !open) {
        e.preventDefault();
        openDeck();
        return;
      }
      if (e.key === "Escape" && open) {
        e.preventDefault();
        // Progressive: while a reply is generating, Escape stops it first; a
        // second Escape (now idle) closes the deck.
        if (inFlightRef.current) {
          abortRef.current?.abort();
          setSrStatus("Stopped.");
          return;
        }
        closeDeck();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, openDeck, closeDeck]);

  // Navigation dismisses the deck. While the deck is open the left rail is
  // lifted above the overlay (body.deck-open) so its navigation popover is
  // clickable; selecting an item changes the hash, and closing the deck here
  // surfaces the freshly navigated panel.
  useEffect(() => {
    if (!open) return;
    const onHashChange = () => closeDeck();
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, [open, closeDeck]);

  // Follow new content (including streaming token growth) only while the
  // operator is reading the latest turn. If they scrolled up to re-read an
  // earlier answer, an arriving reply must not yank them back down.
  const lastTurnLen = turns.length > 0 ? (turns[turns.length - 1]?.text.length ?? 0) : 0;
  useEffect(() => {
    if (!scrollerRef.current || !stuck) return;
    scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight;
  }, [turns.length, lastTurnLen, stuck]);

  const onTranscriptScroll = useCallback(() => {
    const el = scrollerRef.current;
    if (!el) return;
    setStuck(isNearBottom(el.scrollTop, el.scrollHeight, el.clientHeight));
  }, []);

  // Mirror completed turns into tab-scoped storage so an accidental reload does
  // not lose the conversation. Skips while a turn is still streaming.
  useEffect(() => {
    const store = sessionStore();
    if (!store) return;
    if (turns.some((t) => t.streaming === true)) return;
    try {
      store.setItem(TRANSCRIPT_KEY, serializeTurns(turns));
    } catch {
      /* storage full or blocked - persistence is best-effort */
    }
  }, [turns]);

  const jumpToLatest = useCallback(() => {
    const el = scrollerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    setStuck(true);
  }, []);

  // Auto-grow the input to fit its content (capped by the CSS max-height, past
  // which it scrolls). Runs whenever the draft changes or the overlay opens so
  // a recalled multi-line prompt is fully visible without manual resizing.
  useEffect(() => {
    const el = inputRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${el.scrollHeight}px`;
  }, [draft, open]);

  const submit = useCallback(async (raw: string) => {
    const text = raw.trim();
    if (text.length === 0 || pending) return;
    const opTurn: Turn = { id: newId(), role: "operator", text, at: shortTime() };
    setTurns((prev) => [...prev, opTurn]);
    setDraft("");
    historyRef.current = recordHistory(historyRef.current, text);
    setPending(true);
    setSrStatus("Retrieving answer...");
    setInFlight(true);
    const controller = new AbortController();
    abortRef.current = controller;
    // Build the history the backend sees (excluding this turn).
    const history: BackendTurn[] = turns.map((t) => ({
      role: t.role === "operator" ? "user" : "assistant",
      content: t.text,
    }));
    try {
      const deckId = newId();
      let started = false;
      let acc = "";
      // Reveal the streaming reply bubble on the first token (until then the
      // RetrievalTrace "preparing answer" surface stays up).
      const ensureTurn = () => {
        if (started) return;
        started = true;
        setPending(false);
        setSrStatus("Assistant is answering...");
        setTurns((prev) => [
          ...prev,
          { id: deckId, role: "deck", text: "", streaming: true, at: shortTime() },
        ]);
      };
      const reply = await askBackendStream(text, snapshot, history, {
        onToken: (delta) => {
          acc += delta;
          ensureTurn();
          setTurns((prev) =>
            prev.map((t) => (t.id === deckId ? { ...t, text: acc } : t)),
          );
        },
        signal: controller.signal,
      });
      ensureTurn();
      setTurns((prev) =>
        prev.map((t) =>
          t.id === deckId
            ? {
                ...t,
                text: reply.text,
                streaming: false,
                citations: reply.citations,
                followUps: reply.followUps,
                source: reply.source,
                ...(reply.router ? { router: reply.router } : {}),
              }
            : t,
        ),
      );
    } finally {
      setPending(false);
      setSrStatus("Answer ready.");
      setInFlight(false);
      abortRef.current = null;
      focusInput();
    }
  }, [snapshot, focusInput, pending, turns]);

  const clearTurns = useCallback(() => {
    setTurns([]);
    const store = sessionStore();
    try {
      store?.removeItem(TRANSCRIPT_KEY);
    } catch {
      /* best-effort */
    }
  }, []);

  // Cancel an in-flight reply, keeping whatever streamed so far.
  const stopStream = useCallback(() => {
    abortRef.current?.abort();
    setSrStatus("Stopped.");
  }, []);

  // Re-ask the operator question that produced the deck turn at `deckIndex`.
  const regenerateAt = useCallback(
    (deckIndex: number) => {
      for (let j = deckIndex - 1; j >= 0; j--) {
        const prev = turns[j];
        if (prev && prev.role === "operator") {
          void submit(prev.text);
          return;
        }
      }
    },
    [turns, submit],
  );

  // Shell-style history recall: Arrow-Up walks to older submitted prompts,
  // Arrow-Down walks back to the live draft. Only fires when the caret is on
  // the first line (Up) or last line (Down) so multi-line editing is
  // unaffected. Delegated to the pure `draft-history` reducer.
  const onInputKeyDown = useCallback(
    (e: KeyboardEvent) => {
      const el = e.target as HTMLTextAreaElement;
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        submit(el.value);
        return;
      }
      if (e.key === "ArrowUp") {
        const caretOnFirstLine = !el.value.slice(0, el.selectionStart ?? 0).includes("\n");
        if (!caretOnFirstLine) return;
        const r = recallOlder(historyRef.current, el.value);
        historyRef.current = r.history;
        if (r.draft !== null) {
          e.preventDefault();
          setDraft(r.draft);
        }
        return;
      }
      if (e.key === "ArrowDown") {
        const caretOnLastLine = !el.value.slice(el.selectionStart ?? 0).includes("\n");
        if (!caretOnLastLine) return;
        const r = recallNewer(historyRef.current);
        historyRef.current = r.history;
        if (r.draft !== null) {
          e.preventDefault();
          setDraft(r.draft);
        }
      }
    },
    [submit],
  );

  const headline = snapshot?.headline ?? "Idle. Open any route to publish a view snapshot.";
  const routeLabel = snapshot?.routeLabel ?? "Deck";

  return (
    <>
      <button
        type="button"
        class={`deck-invoke ${open ? "deck-invoke-open" : ""}`}
        onClick={open ? closeDeck : openDeck}
        aria-label={open ? "Close command deck" : "Open command deck"}
      >
        <span class="deck-invoke-glyph" aria-hidden="true">
          <svg viewBox="0 0 16 16" width="14" height="14">
            <path
              d="M2 3.5 L14 3.5 M2 8 L14 8 M2 12.5 L10 12.5"
              stroke="currentColor"
              stroke-width="1.6"
              stroke-linecap="round"
            />
          </svg>
        </span>
        <span class="deck-invoke-label">Ask anything about this screen</span>
        <span class="deck-invoke-context muted">{routeLabel}</span>
        <BackendBadge health={health} placement="invoke" />
        <kbd class="deck-invoke-kbd">
          {navigator.platform.toLowerCase().includes("mac") ? "⌘K" : "Ctrl K"}
        </kbd>
        <kbd class="deck-invoke-kbd">/</kbd>
      </button>

      {open ? (
        <div
          class="deck-overlay"
          role="dialog"
          aria-modal="true"
          aria-label="Command deck"
          ref={overlayRef}
          onKeyDown={onOverlayKeyDown}
        >
          <div class="deck-header">
            <div class="deck-header-title">
              <span class="deck-header-glyph" aria-hidden="true">◆</span>
              <span>Command deck</span>
              <span class="deck-header-sep muted">·</span>
              <span class="deck-header-route">{routeLabel}</span>
              <BackendBadge health={health} placement="header" />
            </div>
            <div class="deck-header-headline muted">{headline}</div>
            <button type="button" class="deck-close" onClick={closeDeck} aria-label="Close">
              ×
            </button>
          </div>

          <div class="sr-only" role="status" aria-live="polite">
            {srStatus}
          </div>

          <div class="deck-body">
            <section
              class="deck-transcript"
              ref={scrollerRef}
              aria-label="conversation"
              role="log"
              aria-live="polite"
              aria-relevant="additions"
              aria-busy={pending}
              onScroll={onTranscriptScroll}
            >
              {turns.length === 0 ? (
                <IntroPanel snapshot={snapshot} onPick={submit} />
              ) : null}
              {turns.map((t, i) => (
                <TurnBubble
                  key={t.id}
                  turn={t}
                  onPickFollowUp={submit}
                  {...(t.role === "deck" && !t.streaming && !inFlight
                    ? { onRegenerate: () => regenerateAt(i) }
                    : {})}
                />
              ))}
              {pending ? <RetrievalTrace snapshot={snapshot} health={health} /> : null}
              {!stuck && turns.length > 0 ? (
                <button
                  type="button"
                  class="deck-jump"
                  onClick={jumpToLatest}
                  aria-label="Jump to latest message"
                >
                  Jump to latest ↓
                </button>
              ) : null}
            </section>

            <aside class="deck-digest" aria-label="what the deck sees">
              <div class="deck-digest-header">
                <span class="deck-digest-title">What I see</span>
                <span class="deck-digest-meta muted">
                  {snapshot ? new Date(snapshot.capturedAt).toLocaleTimeString() : "-"}
                </span>
              </div>
              <DigestList snapshot={snapshot} />
            </aside>
          </div>

          <form
            class="deck-input-row"
            onSubmit={(e) => {
              e.preventDefault();
              submit(draft);
            }}
          >
            <textarea
              ref={inputRef}
              class="deck-input"
              placeholder="Ask anything (Enter to send, Shift+Enter for newline, Up for history, Esc to close)"
              value={draft}
              rows={1}
              onInput={(e) => setDraft((e.target as HTMLTextAreaElement).value)}
              onKeyDown={onInputKeyDown}
            />
            <div class="deck-input-actions">
              <button
                type="button"
                class="deck-btn deck-btn-secondary"
                onClick={clearTurns}
                disabled={turns.length === 0}
                title="Clear conversation"
              >
                Clear
              </button>
              {inFlight ? (
                <button
                  type="button"
                  class="deck-btn deck-btn-stop"
                  onClick={stopStream}
                  title="Stop generating"
                >
                  Stop
                </button>
              ) : (
                <button
                  type="submit"
                  class="deck-btn deck-btn-primary"
                  disabled={draft.trim().length === 0}
                >
                  Send
                </button>
              )}
            </div>
          </form>
        </div>
      ) : null}
    </>
  );
}

// ---------------------------------------------------------------------------
// Subcomponents (each with one job)
// ---------------------------------------------------------------------------

function TurnBubble({
  turn,
  onPickFollowUp,
  onRegenerate,
}: {
  readonly turn: Turn;
  readonly onPickFollowUp: (t: string) => void;
  readonly onRegenerate?: () => void;
}) {
  const isDeck = turn.role === "deck";
  return (
    <article class={`deck-turn deck-turn-${turn.role}`}>
      <header class="deck-turn-head">
        <span class="deck-turn-role">{turn.role === "operator" ? "you" : "deck"}</span>
        {turn.source ? (
          <span
            class="deck-turn-source"
            title={routerTooltip(turn.router) ?? "reply source"}
          >
            {turn.source}
          </span>
        ) : null}
        <span class="deck-turn-time muted">{turn.at}</span>
      </header>
      {isDeck ? (
        <GroundedReply
          turnId={turn.id}
          text={turn.text}
          citations={turn.citations}
          source={turn.source}
          streaming={turn.streaming === true}
          {...(onRegenerate ? { onRegenerate } : {})}
        />
      ) : (
        <div class="deck-turn-body">
          {turn.text.split("\n").map((line, i) => (
            <p key={i} class="deck-turn-line">{line}</p>
          ))}
        </div>
      )}
      {turn.followUps && turn.followUps.length > 0 ? (
        <ul class="deck-followups" aria-label="suggested follow-ups">
          {turn.followUps.map((f) => (
            <li key={f}>
              <button
                type="button"
                class="deck-followup"
                onClick={() => onPickFollowUp(f)}
              >
                {f}
              </button>
            </li>
          ))}
        </ul>
      ) : null}
    </article>
  );
}

function BackendBadge({
  health,
  placement,
}: {
  readonly health: BackendHealth | null;
  readonly placement: "invoke" | "header";
}) {
  if (health === null) {
    return (
      <span
        class={`deck-backend deck-backend-${placement} deck-backend-probing`}
        title="probing chat backend..."
      >
        <span class="deck-backend-dot" />
        <span class="deck-backend-label">probing</span>
      </span>
    );
  }
  if (health.available) {
    const routed = health.router;
    const label = routed
      ? `LLM · auto(${routed.candidates.length}) · ${routed.chose}`
      : health.model
        ? `LLM · ${health.model}`
        : "LLM ready";
    const base = `chat mode ${health.mode}${
      health.endpoint ? ` · ${health.endpoint}` : ""
    }`;
    const tooltip = routed ? `${base}\n${routerTooltip(routed) ?? ""}` : base;
    return (
      <span
        class={`deck-backend deck-backend-${placement} deck-backend-ready`}
        title={tooltip}
      >
        <span class="deck-backend-dot" />
        <span class="deck-backend-label">{label}</span>
      </span>
    );
  }
  return (
    <span
      class={`deck-backend deck-backend-${placement} deck-backend-fallback`}
      title={`LLM unavailable (${health.mode}) · falling back to deterministic answerer`}
    >
      <span class="deck-backend-dot" />
      <span class="deck-backend-label">deterministic</span>
    </span>
  );
}

function IntroPanel({
  snapshot,
  onPick,
}: {
  readonly snapshot: ReturnType<typeof useViewContext>;
  readonly onPick: (s: string) => void;
}) {
  const suggestions = introSuggestions(snapshot);
  return (
    <div class="deck-intro">
      <p class="deck-intro-lead">
        Ask about anything currently visible - tiles, KPIs, HIL items, audit rows,
        promotion status, blast radius, or ontology. I ground every answer in the
        snapshot on the right.
      </p>
      <ul class="deck-intro-suggest">
        {suggestions.map((s) => (
          <li key={s}>
            <button type="button" class="deck-suggest" onClick={() => onPick(s)}>
              {s}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/**
 * Short human descriptions for the "What I see" digest keys, shown as a fast
 * hover tooltip. Returns "" for keys we do not describe (no tooltip rendered).
 * English source strings (L2 product surface).
 */
const FACT_DESCRIPTIONS: Readonly<Record<string, string>> = {
  eps: "Events per second the control loop is processing (60s rolling).",
  "session.total": "Total events seen since this live session started.",
  "session.duration": "How long this live session has been running.",
  "tiles.active": "Tiles currently showing an in-flight action.",
  "tiles.empty": "Unused tiles in the cockpit grid.",
  "tiles.shadow": "Tiles running in shadow mode (judge-and-log, no execution).",
  "tier.t0": "Share routed to T0 - deterministic policy (target 70-80%).",
  "tier.t1": "Share routed to T1 - lightweight similarity / small model (15-20%).",
  "tier.t2": "Share routed to T2 - frontier-model reasoning, novel cases only (5-10%).",
  "gate.auto": "Actions the risk gate auto-executed (low risk).",
  "gate.hil": "Actions routed to human-in-the-loop approval (high risk).",
  "gate.abstain": "Cases the gate abstained on - no autonomous action taken.",
  "gate.deny": "Actions the gate denied outright.",
  "attention.total": "Items currently needing operator attention.",
  "attention.hil": "Items waiting on a human approval.",
  "attention.deny": "Denied actions flagged for review.",
  "attention.failed": "Actions that failed during execution.",
  "attention.stuck": "Actions stuck without progress past their budget.",
  "verticals.change": "Change Safety events (safe change, drift remediation).",
  "verticals.resilience": "Resilience events (disaster recovery, chaos testing).",
  "verticals.cost": "Cost Governance events (FinOps).",
  "verticals.unknown": "Events not yet classified into a vertical.",
};

function factDescription(key: string): string {
  return FACT_DESCRIPTIONS[key] ?? "";
}

function DigestList({ snapshot }: { readonly snapshot: ReturnType<typeof useViewContext> }) {
  const grouped = useMemo(() => {
    if (snapshot === null) return new Map<string, readonly { key: string; value: unknown }[]>();
    const out = new Map<string, { key: string; value: unknown }[]>();
    for (const f of snapshot.facts) {
      const g = f.group ?? "facts";
      const bucket = out.get(g) ?? [];
      bucket.push({ key: f.key, value: f.value });
      out.set(g, bucket);
    }
    return out;
  }, [snapshot]);

  if (snapshot === null) {
    return (
      <div class="deck-digest-empty muted">
        No route has published a view snapshot. Open Live, Dashboard, Audit,
        HIL, Trace, Blast Radius, Promotion, or Ontology.
      </div>
    );
  }

  const recordCount = snapshot.records
    ? Object.entries(snapshot.records).reduce((acc, [, v]) => acc + v.length, 0)
    : 0;

  return (
    <div class="deck-digest-body">
      {[...grouped.entries()].map(([group, facts]) => (
        <section key={group} class="deck-digest-group">
          <h4 class="deck-digest-group-title">{group}</h4>
          <dl class="deck-digest-list">
            {facts.map((f) => {
              const desc = factDescription(f.key);
              return (
                <div key={f.key} class="deck-digest-row">
                  <dt>{f.key}</dt>
                  <dd>{f.value === null ? "-" : String(f.value)}</dd>
                  {desc ? (
                    <span class="deck-digest-tip" role="tooltip">
                      {desc}
                    </span>
                  ) : null}
                </div>
              );
            })}
          </dl>
        </section>
      ))}
      {recordCount > 0 ? (
        <p class="deck-digest-records muted">
          + {recordCount} record(s) available for the answerer to search
          {snapshot.records
            ? " (" +
              Object.entries(snapshot.records)
                .map(([k, v]) => `${k}: ${v.length}`)
                .join(", ") +
              ")"
            : ""}
          .
        </p>
      ) : null}
    </div>
  );
}
