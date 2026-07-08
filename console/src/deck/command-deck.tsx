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
  askBackend,
  probeBackend,
  type BackendHealth,
  type BackendTurn,
  type RouterSnapshot,
} from "./backend";
import { useViewContext } from "./context";

interface Turn {
  readonly id: string;
  readonly role: "operator" | "deck";
  readonly text: string;
  readonly citations?: readonly { readonly label: string; readonly value?: string }[];
  readonly followUps?: readonly string[];
  readonly source?: string;
  readonly router?: RouterSnapshot;
  readonly at: string;
}

function shortTime(): string {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}

function newId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
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
    const marker = c.deployment === router.chose ? "* " : "  ";
    return `${marker}${c.deployment} · p50 ${p50} · n=${c.samples}`;
  });
  return `auto-router (${router.reason}) chose ${router.chose}\n${lines.join("\n")}`;
}

export function CommandDeck() {
  const snapshot = useViewContext();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [turns, setTurns] = useState<readonly Turn[]>([]);
  const [pending, setPending] = useState(false);
  const [health, setHealth] = useState<BackendHealth | null>(null);
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

  const openDeck = useCallback(() => {
    setOpen(true);
    focusInput();
  }, [focusInput]);

  const closeDeck = useCallback(() => {
    setOpen(false);
  }, []);

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
        closeDeck();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, openDeck, closeDeck]);

  // Autoscroll transcript on new turn.
  useEffect(() => {
    if (!scrollerRef.current) return;
    scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight;
  }, [turns.length]);

  const submit = useCallback(async (raw: string) => {
    const text = raw.trim();
    if (text.length === 0 || pending) return;
    const opTurn: Turn = { id: newId(), role: "operator", text, at: shortTime() };
    setTurns((prev) => [...prev, opTurn]);
    setDraft("");
    setPending(true);
    // Build the history the backend sees (excluding this turn).
    const history: BackendTurn[] = turns.map((t) => ({
      role: t.role === "operator" ? "user" : "assistant",
      content: t.text,
    }));
    try {
      const reply = await askBackend(text, snapshot, history);
      const deckTurnBase: Turn = {
        id: newId(),
        role: "deck",
        text: reply.text,
        citations: reply.citations,
        followUps: reply.followUps,
        source: reply.source,
        at: shortTime(),
      };
      const deckTurn: Turn = reply.router
        ? { ...deckTurnBase, router: reply.router }
        : deckTurnBase;
      setTurns((prev) => [...prev, deckTurn]);
    } finally {
      setPending(false);
      focusInput();
    }
  }, [snapshot, focusInput, pending, turns]);

  const clearTurns = useCallback(() => setTurns([]), []);

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
      </button>

      {open ? (
        <div class="deck-overlay" role="dialog" aria-label="Command deck">
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

          <div class="deck-body">
            <section class="deck-transcript" ref={scrollerRef} aria-label="conversation">
              {turns.length === 0 ? (
                <IntroPanel snapshotPresent={snapshot !== null} onPick={submit} />
              ) : null}
              {turns.map((t) => (
                <TurnBubble key={t.id} turn={t} onPickFollowUp={submit} />
              ))}
              {pending ? <PendingBubble /> : null}
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
              placeholder="Ask about tiles, verticals, HIL, audit, promotion... (Enter to send, Shift+Enter for newline, Esc to close)"
              value={draft}
              rows={2}
              onInput={(e) => setDraft((e.target as HTMLTextAreaElement).value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  submit(draft);
                }
              }}
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
              <button
                type="submit"
                class="deck-btn deck-btn-primary"
                disabled={draft.trim().length === 0 || pending}
              >
                {pending ? "Thinking..." : "Send"}
              </button>
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
}: {
  readonly turn: Turn;
  readonly onPickFollowUp: (t: string) => void;
}) {
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
      <div class="deck-turn-body">
        {turn.text.split("\n").map((line, i) => (
          <p key={i} class="deck-turn-line">{line}</p>
        ))}
      </div>
      {turn.citations && turn.citations.length > 0 ? (
        <ul class="deck-turn-citations" aria-label="citations">
          {turn.citations.map((c, i) => (
            <li key={i} class="deck-citation">
              <span class="deck-citation-label">{c.label}</span>
              {c.value !== undefined ? (
                <span class="deck-citation-value">{c.value}</span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}
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

function PendingBubble() {
  return (
    <article class="deck-turn deck-turn-deck deck-turn-pending" aria-live="polite">
      <header class="deck-turn-head">
        <span class="deck-turn-role">deck</span>
        <span class="deck-turn-time muted">thinking</span>
      </header>
      <div class="deck-turn-body">
        <span class="deck-typing" aria-hidden="true">
          <span class="deck-typing-dot" />
          <span class="deck-typing-dot" />
          <span class="deck-typing-dot" />
        </span>
      </div>
    </article>
  );
}

function IntroPanel({
  snapshotPresent,
  onPick,
}: {
  readonly snapshotPresent: boolean;
  readonly onPick: (s: string) => void;
}) {
  const suggestions = snapshotPresent
    ? [
        "what do you see on this screen?",
        "how many items need attention?",
        "which tiles are failed?",
        "what is the tier mix right now?",
      ]
    : ["what routes are available?"];
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
            {facts.map((f) => (
              <div key={f.key} class="deck-digest-row">
                <dt>{f.key}</dt>
                <dd>{f.value === null ? "-" : String(f.value)}</dd>
              </div>
            ))}
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
