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
 * - Read-only for questions; for an explicit operator command it submits a
 *   PROPOSAL to the typed pipeline (POST /chat/action) - it never executes.
 *   Nothing changes until Forseti judges the proposal and an approver signs
 *   off a high-risk one (execution is shadow-first, RBAC server-enforced).
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "preact/hooks";
import { t } from "../i18n";
import {
  askBackendStream,
  probeBackend,
  renderActionResult,
  submitAction,
  type BackendHealth,
  type BackendTurn,
  type RouterSnapshot,
} from "./backend";
import { detectActionIntent } from "./action-intent";
import {
  conversationTitle,
  GENERAL_CONVERSATION_KEY,
  parseConversationIndex,
  serializeConversationIndex,
  upsertConversation,
  type ConversationSummary,
  CONVERSATION_INDEX_KEY,
} from "./conversation-sessions";
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
import { DECK_OPEN_EVENT, type DeckOpenDetail } from "./open-deck";
import { isNearBottom } from "./scroll-stick";
import { parseTurns, serializeTurns, transcriptKeyFor } from "./transcript-store";

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
  /** Agent name when this turn speaks as a specific agent (renders its icon + name). */
  readonly agent?: string;
  readonly at: string;
}

interface ActiveRequest {
  readonly id: string;
  readonly sessionKey: string;
  readonly controller: AbortController;
  readonly kind: "stream" | "action";
}

function shortTime(): string {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}

function newId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function sessionIdFor(
  sessions: Map<string, string>,
  sessionKey: string,
  create: () => string = newId,
): string {
  const existing = sessions.get(sessionKey);
  if (existing) return existing;
  const created = create();
  sessions.set(sessionKey, created);
  return created;
}

/** Return indexes of turns containing a case-insensitive search query. */
export function matchingTurnIndexes(
  turns: readonly { readonly text: string }[],
  rawQuery: string,
): number[] {
  const query = rawQuery.trim().toLowerCase();
  if (!query) return [];
  return turns.flatMap((turn, index) =>
    turn.text.toLowerCase().includes(query) ? [index] : [],
  );
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

/** The general (screen-scoped) conversation session id. */
const GENERAL_SESSION = GENERAL_CONVERSATION_KEY;

/**
 * The current route token from the location hash, normalized the same way the
 * app router does (decode `%2F`, strip the leading `#/` and any query). Used to
 * tell a real navigation from in-place hash re-encoding (`#/agents` <->
 * `#%2Fagents`) so the deck only dismisses on an actual route change.
 */
function normalizedRoute(): string {
  if (typeof window === "undefined") return "";
  let hash = window.location.hash;
  try {
    hash = decodeURIComponent(hash);
  } catch {
    /* keep raw hash if it is not a valid URI component */
  }
  return hash.replace(/^#\/?/, "").replace(/\?.*$/, "");
}

/** Typewriter cadence (ms per chunk) for the injected agent-context turn. */
const CONTEXT_TYPE_MS = 14;

/** CSS `mask-image` url for an agent's line icon (see agents route). Base-path
 *  aware so a subpath-mounted console still resolves the public asset. */
function agentIconUrl(name: string): string {
  const base = typeof import.meta.env.BASE_URL === "string" ? import.meta.env.BASE_URL : "/";
  return `url("${base}agent-icons/${name.toLowerCase()}.svg")`;
}

/** Split text into small whitespace-preserving chunks so an injected turn types
 *  in word-by-word, matching the LLM stream cadence. */
function contextChunks(text: string): string[] {
  const out: string[] = [];
  const re = /\s*\S{1,4}|\s+$/g;
  for (const m of text.matchAll(re)) out.push(m[0]);
  return out.length > 0 ? out : [text];
}

export function CommandDeck() {
  const snapshot = useViewContext();
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [activeSearchMatch, setActiveSearchMatch] = useState(0);
  // Active conversation session. The general screen deck is "screen"; a chat
  // scoped to one agent uses e.g. "agent:Forseti" and keeps a separate
  // transcript so threads never bleed into each other.
  const [sessionKey, setSessionKey] = useState<string>(GENERAL_SESSION);
  const [sessionLabel, setSessionLabel] = useState<string | null>(null);
  const sessionKeyRef = useRef<string>(GENERAL_SESSION);
  const [turns, setTurns] = useState<readonly Turn[]>(() => {
    const store = sessionStore();
    return store ? parseTurns(store.getItem(transcriptKeyFor(GENERAL_SESSION))) : [];
  });
  const [conversations, setConversations] = useState<readonly ConversationSummary[]>(() => {
    const store = sessionStore();
    const restored = store
      ? parseConversationIndex(store.getItem(CONVERSATION_INDEX_KEY))
      : [];
    const previous = restored.find((item) => item.key === GENERAL_SESSION);
    return upsertConversation(restored, {
      key: GENERAL_SESSION,
      label: t("deck.general"),
      kind: "general",
      updatedAt: previous?.updatedAt ?? new Date().toISOString(),
    });
  });
  const turnsRef = useRef<readonly Turn[]>(turns);
  const [pending, setPending] = useState(false);
  const [health, setHealth] = useState<BackendHealth | null>(null);
  const [srStatus, setSrStatus] = useState("");
  const [inFlight, setInFlight] = useState(false);
  const [stuck, setStuck] = useState(true);
  const abortRef = useRef<AbortController | null>(null);
  const activeRequestRef = useRef<ActiveRequest | null>(null);
  const inFlightRef = useRef(false);
  const historyRef = useRef(EMPTY_HISTORY);
  // One stable backend correlation id per transcript session.
  const sessionIdsRef = useRef(new Map<string, string>());
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const overlayRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);
  const scrollerRef = useRef<HTMLDivElement | null>(null);

  const updateConversationIndex = useCallback(
    (summary: ConversationSummary) => {
      setConversations((current) => {
        const next = upsertConversation(current, summary);
        const retained = new Set(next.map((item) => item.key));
        try {
          const store = sessionStore();
          store?.setItem(CONVERSATION_INDEX_KEY, serializeConversationIndex(next));
          for (const evicted of current) {
            if (!retained.has(evicted.key)) store?.removeItem(transcriptKeyFor(evicted.key));
          }
        } catch {
          /* best-effort */
        }
        return next;
      });
    },
    [],
  );

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

  // Re-probe whenever the deck opens so a backend that came online (or dropped)
  // since the last check is reflected in the badge before the first question.
  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    void probeBackend().then((h) => {
      if (!cancelled) setHealth(h);
    });
    return () => {
      cancelled = true;
    };
  }, [open]);

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

  const cancelActiveRequest = useCallback((): ActiveRequest["kind"] | null => {
    const active = activeRequestRef.current;
    activeRequestRef.current = null;
    abortRef.current = null;
    active?.controller.abort();
    inFlightRef.current = false;
    const completed = turnsRef.current.map((turn) =>
      turn.streaming ? { ...turn, streaming: false } : turn,
    );
    turnsRef.current = completed;
    setTurns(completed);
    setPending(false);
    setInFlight(false);
    return active?.kind ?? null;
  }, []);

  const closeDeck = useCallback(() => {
    cancelActiveRequest();
    setOpen(false);
    // Return focus to the element that opened the deck (a11y: modal contract).
    const target = restoreFocusRef.current;
    if (target && typeof target.focus === "function") {
      requestAnimationFrame(() => target.focus());
    }
  }, [cancelActiveRequest]);

  // Append an opening context turn that speaks AS the given agent (its icon +
  // name in the header) and types its text in like a live reply, instead of
  // dumping the whole note at once. `agent` null falls back to a plain deck
  // turn. Pure client-side typewriter over an already-known string.
  const streamContextTurn = useCallback((agent: string | null, fullText: string) => {
    const turnId = newId();
    const shouldAnimate =
      document.visibilityState !== "hidden" &&
      (typeof document.hasFocus !== "function" || document.hasFocus());
    const seed: Turn = {
      id: turnId,
      role: "deck",
      text: shouldAnimate ? "" : fullText,
      source: "context",
      streaming: shouldAnimate,
      at: shortTime(),
      ...(agent ? { agent } : {}),
    };
    setTurns((prev) => [...prev, seed]);
    turnsRef.current = [...turnsRef.current, seed];
    if (!shouldAnimate) return;
    const chunks = contextChunks(fullText);
    let i = 0;
    const step = (): void => {
      if (i >= chunks.length) {
        setTurns((prev) => prev.map((t) => (t.id === turnId ? { ...t, streaming: false } : t)));
        return;
      }
      const piece = chunks[i]!;
      i += 1;
      setTurns((prev) =>
        prev.map((t) => (t.id === turnId ? { ...t, text: t.text + piece } : t)),
      );
      window.setTimeout(step, CONTEXT_TYPE_MS);
    };
    window.setTimeout(step, CONTEXT_TYPE_MS);
  }, []);

  // Switch the visible conversation to `key`, persisting the outgoing session
  // first so returning to it restores the thread. A brand-new session is
  // optionally seeded with `contextNote` (e.g. an agent's recent work), streamed
  // in as the agent; an existing session is resumed as-is so its prior turns
  // are preserved.
  const switchSession = useCallback(
    (
      key: string,
      agent: string | null,
      contextNote?: string,
      conversationLabel?: string,
      kind: ConversationSummary["kind"] = agent ? "agent" : "general",
    ) => {
      if (key !== sessionKeyRef.current) cancelActiveRequest();
      const store = sessionStore();
      if (store && key !== sessionKeyRef.current) {
        try {
          store.setItem(
            transcriptKeyFor(sessionKeyRef.current),
            serializeTurns(turnsRef.current),
          );
        } catch {
          /* best-effort */
        }
      }
      const next: Turn[] = store ? (parseTurns(store.getItem(transcriptKeyFor(key))) as Turn[]) : [];
      sessionKeyRef.current = key;
      turnsRef.current = next;
      setSessionKey(key);
      setSessionLabel(agent);
      setTurns(next);
      setSearchQuery("");
      setActiveSearchMatch(0);
      historyRef.current = EMPTY_HISTORY;
      updateConversationIndex({
        key,
        label:
          conversationLabel ??
          agent ??
          (key === GENERAL_SESSION ? t("deck.general") : t("deck.newConversation")),
        kind,
        ...(agent ? { agent } : {}),
        updatedAt: new Date().toISOString(),
      });
      const note = contextNote?.trim();
      if (next.length === 0 && note) {
        streamContextTurn(agent, note);
      }
    },
    [cancelActiveRequest, streamContextTurn, updateConversationIndex],
  );

  const startNewConversation = useCallback(() => {
    const key = `conversation:${newId()}`;
    switchSession(key, null, undefined, t("deck.newConversation"));
    setDraft("");
    focusInput();
  }, [focusInput, switchSession]);

  // Open the deck on the general (screen) session - used by the launcher, the
  // Cmd/Ctrl+K toggle, and the `/` shortcut, so those never drop the operator
  // into a lingering agent session.
  const openGeneralDeck = useCallback(() => {
    if (sessionKeyRef.current !== GENERAL_SESSION) switchSession(GENERAL_SESSION, null);
    openDeck();
  }, [openDeck, switchSession]);

  const removeCachedConversation = useCallback(
    (conversation: ConversationSummary) => {
      if (conversation.key === GENERAL_SESSION) return;
      const removingActive = sessionKeyRef.current === conversation.key;
      if (removingActive) cancelActiveRequest();
      const remaining = conversations.filter((item) => item.key !== conversation.key);
      try {
        const store = sessionStore();
        store?.removeItem(transcriptKeyFor(conversation.key));
        store?.setItem(CONVERSATION_INDEX_KEY, serializeConversationIndex(remaining));
      } catch {
        /* best-effort */
      }
      sessionIdsRef.current.delete(conversation.key);
      setConversations(remaining);
      if (removingActive) {
        const fallback = remaining.find((item) => item.key === GENERAL_SESSION) ?? remaining[0];
        if (fallback) {
          switchSession(
            fallback.key,
            fallback.agent ?? null,
            undefined,
            fallback.label,
            fallback.kind,
          );
        } else {
          switchSession(GENERAL_SESSION, null, undefined, t("deck.general"));
        }
      }
      focusInput();
    },
    [cancelActiveRequest, conversations, focusInput, switchSession],
  );

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
        if (open) {
          searchRef.current?.focus();
          searchRef.current?.select();
        } else openGeneralDeck();
        return;
      }
      if (!inField && e.key === "/" && !open) {
        e.preventDefault();
        openGeneralDeck();
        return;
      }
      if (e.key === "Escape" && open) {
        e.preventDefault();
        if (document.activeElement === searchRef.current) {
          setSearchQuery("");
          focusInput();
          return;
        }
        // Progressive: while a reply is generating, Escape stops it first; a
        // second Escape (now idle) closes the deck.
        if (inFlightRef.current) {
          const kind = cancelActiveRequest();
          setSrStatus(kind === "action"
            ? "Response dismissed; submission outcome may be unknown."
            : "Stopped.");
          return;
        }
        closeDeck();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [open, openGeneralDeck, closeDeck, cancelActiveRequest]);

  // Cross-screen open: any read-only surface (e.g. the Now>Agents incident
  // thread) can dispatch `fdai:deck:open` to raise the deck, optionally seeding
  // the draft with a grounded question. This is a decoupled seam - the sender
  // holds no reference to the deck and cannot execute anything; it only opens a
  // question box the operator still has to send.
  useEffect(() => {
    const onOpenDeck = (e: Event) => {
      const detail = (e as CustomEvent<DeckOpenDetail>).detail;
      const note = typeof detail?.contextNote === "string" ? detail.contextNote.trim() : "";
      const key =
        typeof detail?.sessionKey === "string" && detail.sessionKey
          ? detail.sessionKey
          : GENERAL_SESSION;
      const label = typeof detail?.sessionLabel === "string" ? detail.sessionLabel : null;
      if (key !== sessionKeyRef.current) {
        // Move to the target session (its own transcript). A context note only
        // seeds a brand-new session, so re-opening an agent chat resumes the
        // existing thread instead of stacking duplicate context.
        switchSession(
          key,
          label,
          note,
          label ?? undefined,
          key.startsWith("agent:") ? "agent" : "general",
        );
      } else if (note && turnsRef.current.length === 0) {
        // Same, still-empty session: stream in the grounding context turn as
        // the agent.
        streamContextTurn(label, note);
      }
      const seed = typeof detail?.prompt === "string" ? detail.prompt : "";
      if (seed) {
        setDraft(seed);
        historyRef.current = recordHistory(historyRef.current, seed);
      }
      openDeck();
    };
    window.addEventListener(DECK_OPEN_EVENT, onOpenDeck);
    return () => window.removeEventListener(DECK_OPEN_EVENT, onOpenDeck);
  }, [openDeck, switchSession, streamContextTurn]);

  // Navigation dismisses the deck. While the deck is open the left rail is
  // lifted above the overlay (body.deck-open) so its navigation popover is
  // clickable; selecting an item changes the hash, and closing the deck here
  // surfaces the freshly navigated panel.
  useEffect(() => {
    if (!open) return;
    // Only a REAL navigation (route token change) should dismiss the deck.
    // This environment (and any hash-router host) can re-encode the hash in
    // place - e.g. `#/agents` <-> `#%2Fagents` - which fires `hashchange`
    // with no actual route change; closing on that made the deck appear to
    // auto-close. Compare the normalized route and ignore same-route churn.
    const routeAtOpen = normalizedRoute();
    const onHashChange = () => {
      if (normalizedRoute() !== routeAtOpen) closeDeck();
    };
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, [open, closeDeck]);

  useEffect(() => () => cancelActiveRequest(), [cancelActiveRequest]);

  // Focus guard: while the deck is open, a live route behind it re-renders on
  // every stream frame. Those background re-renders can steal focus out of the
  // input onto a topbar/background control, which silently swallows the
  // operator's keystrokes (a stray Space then scrolls the page or toggles a
  // background button - e.g. closing the deck). Pull focus back to the input
  // whenever it escapes to anything that is neither inside the overlay nor the
  // still-interactive left rail. A genuine click on a background control still
  // fires (click precedes focus); only the stuck-focus is corrected.
  useEffect(() => {
    if (!open) return;
    const onFocusIn = (e: FocusEvent) => {
      const target = e.target as HTMLElement | null;
      if (!target) return;
      const overlay = overlayRef.current;
      if (overlay && overlay.contains(target)) return;
      if (target.closest(".left-rail")) return;
      requestAnimationFrame(() => inputRef.current?.focus());
    };
    document.addEventListener("focusin", onFocusIn);
    return () => document.removeEventListener("focusin", onFocusIn);
  }, [open]);

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
  // not lose the conversation. Keyed by the active session so each agent chat
  // and the general deck persist independently. Skips a still-streaming turn.
  // `turnsRef` mirrors the latest turns so a session switch can flush the
  // outgoing session synchronously without a stale closure.
  useEffect(() => {
    turnsRef.current = turns;
    const store = sessionStore();
    if (!store) return;
    if (turns.some((t) => t.streaming === true)) return;
    try {
      store.setItem(transcriptKeyFor(sessionKey), serializeTurns(turns));
    } catch {
      /* storage full or blocked - persistence is best-effort */
    }
  }, [turns, sessionKey]);

  const jumpToLatest = useCallback(() => {
    const el = scrollerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    setStuck(true);
  }, []);

  const searchMatches = useMemo(() => {
    return matchingTurnIndexes(turns, searchQuery);
  }, [searchQuery, turns]);

  useEffect(() => {
    setActiveSearchMatch((current) =>
      searchMatches.length === 0 ? 0 : Math.min(current, searchMatches.length - 1),
    );
  }, [searchMatches.length]);

  const moveSearch = useCallback(
    (direction: -1 | 1) => {
      if (searchMatches.length === 0) return;
      const next =
        (activeSearchMatch + direction + searchMatches.length) % searchMatches.length;
      setActiveSearchMatch(next);
      const turn = turns[searchMatches[next]!];
      if (turn) {
        document.getElementById(`deck-turn-${turn.id}`)?.scrollIntoView({
          behavior: "smooth",
          block: "center",
        });
      }
    },
    [activeSearchMatch, searchMatches, turns],
  );

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
    if (text.length === 0 || pending || inFlightRef.current) return;
    const originSessionKey = sessionKeyRef.current;
    const controller = new AbortController();
    const action = detectActionIntent(text);
    const request: ActiveRequest = {
      id: newId(),
      sessionKey: originSessionKey,
      controller,
      kind: action ? "action" : "stream",
    };
    activeRequestRef.current = request;
    abortRef.current = controller;
    inFlightRef.current = true;
    const isCurrent = () =>
      activeRequestRef.current?.id === request.id &&
      sessionKeyRef.current === originSessionKey;
    const opTurn: Turn = { id: newId(), role: "operator", text, at: shortTime() };
    const activeSummary = conversations.find((item) => item.key === originSessionKey);
    const hasOperatorTurn = turnsRef.current.some((turn) => turn.role === "operator");
    updateConversationIndex({
      key: originSessionKey,
      label:
        activeSummary?.agent ??
        (originSessionKey.startsWith("conversation:") && !hasOperatorTurn
          ? conversationTitle(text)
          : (activeSummary?.label ?? t("deck.general"))),
      kind: activeSummary?.kind ?? "general",
      ...(activeSummary?.agent ? { agent: activeSummary.agent } : {}),
      updatedAt: new Date().toISOString(),
    });
    setTurns((prev) => [...prev, opTurn]);
    turnsRef.current = [...turnsRef.current, opTurn];
    setDraft("");
    historyRef.current = recordHistory(historyRef.current, text);
    setPending(true);
    setSrStatus("Retrieving answer...");
    setInFlight(true);

    // Action command ("restart vm-1") -> submit a proposal to the typed
    // pipeline instead of asking the narrator. This publishes a signal for
    // Forseti to judge; it never executes here (execution is the pantheon's,
    // after judge + approval, shadow-first).
    if (action) {
      try {
        const result = await submitAction(
          text,
          sessionIdFor(sessionIdsRef.current, originSessionKey),
          controller.signal,
        );
        if (isCurrent()) {
          setPending(false);
          setTurns((prev) => [
            ...prev,
            { id: newId(), role: "deck", text: renderActionResult(result), at: shortTime() },
          ]);
        }
      } finally {
        if (isCurrent()) {
          activeRequestRef.current = null;
          abortRef.current = null;
          inFlightRef.current = false;
          setPending(false);
          setSrStatus(controller.signal.aborted ? "Response dismissed; submission outcome may be unknown." : "Answer ready.");
          setInFlight(false);
          focusInput();
        }
      }
      return;
    }

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
        if (started || !isCurrent()) return;
        started = true;
        setPending(false);
        setSrStatus("Assistant is answering...");
        setTurns((prev) => {
          const next: readonly Turn[] = [
            ...prev,
            { id: deckId, role: "deck", text: "", streaming: true, at: shortTime() },
          ];
          turnsRef.current = next;
          return next;
        });
      };
      const reply = await askBackendStream(text, snapshot, history, {
        onToken: (delta) => {
          if (!isCurrent()) return;
          acc += delta;
          ensureTurn();
          setTurns((prev) => {
            const next = prev.map((t) => (t.id === deckId ? { ...t, text: acc } : t));
            turnsRef.current = next;
            return next;
          });
        },
        signal: controller.signal,
      });
      ensureTurn();
      if (isCurrent()) {
        setTurns((prev) => {
          const next = prev.map((t) =>
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
            );
            turnsRef.current = next;
            return next;
          });
      }
    } finally {
      if (isCurrent()) {
        activeRequestRef.current = null;
        abortRef.current = null;
        inFlightRef.current = false;
        setPending(false);
        setSrStatus(controller.signal.aborted ? "Stopped." : "Answer ready.");
        setInFlight(false);
        focusInput();
      }
    }
  }, [snapshot, focusInput, pending, turns, conversations, updateConversationIndex]);

  const clearTurns = useCallback(() => {
    cancelActiveRequest();
    setTurns([]);
    turnsRef.current = [];
    const store = sessionStore();
    try {
      store?.removeItem(transcriptKeyFor(sessionKeyRef.current));
    } catch {
      /* best-effort */
    }
  }, [cancelActiveRequest]);

  // Cancel an in-flight reply, keeping whatever streamed so far.
  const stopStream = useCallback(() => {
    const kind = cancelActiveRequest();
    setSrStatus(kind === "action"
      ? "Response dismissed; submission outcome may be unknown."
      : "Stopped.");
  }, [cancelActiveRequest]);

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
  const routeLabel = snapshot?.routeLabel ?? t("deck.label");

  return (
    <>
      <button
        type="button"
        class={`deck-invoke ${open ? "deck-invoke-open" : ""}`}
        onClick={open ? closeDeck : openGeneralDeck}
        aria-label={open ? t("deck.close") : t("deck.open")}
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
        <span class="deck-invoke-label">{t("deck.invoke")}</span>
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
          aria-label={t("deck.label")}
          ref={overlayRef}
          onKeyDown={onOverlayKeyDown}
        >
          <div class="deck-header">
            <div class="deck-header-title">
              <span class="deck-header-glyph" aria-hidden="true">◆</span>
              <span>Command deck</span>
              <span class="deck-header-sep muted">·</span>
              <span class="deck-header-route">{routeLabel}</span>
              {sessionLabel && (
                <>
                  <span class="deck-session-chip" title={`Chatting with ${sessionLabel}`}>
                    {sessionLabel}
                  </span>
                  <button
                    type="button"
                    class="deck-session-exit"
                    onClick={openGeneralDeck}
                    title="Back to the general screen deck"
                  >
                    General
                  </button>
                </>
              )}
              <BackendBadge health={health} placement="header" />
            </div>
            <div class="deck-header-center">
              <div class="deck-header-headline muted">{headline}</div>
              <div class="deck-search" role="search">
                <span class="deck-search-icon" aria-hidden="true">⌕</span>
                <input
                  ref={searchRef}
                  type="search"
                  value={searchQuery}
                  placeholder={t("deck.searchPlaceholder")}
                  aria-label={t("deck.searchConversation")}
                  onInput={(event) => {
                    setSearchQuery((event.target as HTMLInputElement).value);
                    setActiveSearchMatch(0);
                  }}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      event.preventDefault();
                      moveSearch(event.shiftKey ? -1 : 1);
                    }
                  }}
                />
                <span class="deck-search-count" aria-live="polite">
                  {searchQuery.trim()
                    ? `${searchMatches.length === 0 ? 0 : activeSearchMatch + 1}/${searchMatches.length}`
                    : ""}
                </span>
                <button
                  type="button"
                  onClick={() => moveSearch(-1)}
                  disabled={searchMatches.length === 0}
                  aria-label={t("deck.previousMatch")}
                >
                  ↑
                </button>
                <button
                  type="button"
                  onClick={() => moveSearch(1)}
                  disabled={searchMatches.length === 0}
                  aria-label={t("deck.nextMatch")}
                >
                  ↓
                </button>
                <kbd>{navigator.platform.toLowerCase().includes("mac") ? "⌘K" : "Ctrl K"}</kbd>
              </div>
            </div>
            <button type="button" class="deck-close" onClick={closeDeck} aria-label="Close">
              ×
            </button>
          </div>

          <div class="sr-only" role="status" aria-live="polite">
            {srStatus}
          </div>

          <div class="deck-body">
            <ConversationSidebar
              conversations={conversations}
              activeKey={sessionKey}
              onNew={startNewConversation}
              onRemove={removeCachedConversation}
              onSelect={(conversation) => {
                switchSession(
                  conversation.key,
                  conversation.agent ?? null,
                  undefined,
                  conversation.label,
                  conversation.kind,
                );
                focusInput();
              }}
            />
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
                  searchMatch={searchMatches.includes(i)}
                  activeSearchMatch={searchMatches[activeSearchMatch] === i}
                  onPickFollowUp={submit}
                  {...(t.role === "deck" &&
                    !t.streaming &&
                    !inFlight &&
                    turns.slice(0, i).some((previous) => previous.role === "operator")
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
                title={t("deck.clearCachedConversationHint")}
              >
                {t("deck.clearCachedConversation")}
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

function ConversationSidebar({
  conversations,
  activeKey,
  onNew,
  onSelect,
  onRemove,
}: {
  readonly conversations: readonly ConversationSummary[];
  readonly activeKey: string;
  readonly onNew: () => void;
  readonly onSelect: (conversation: ConversationSummary) => void;
  readonly onRemove: (conversation: ConversationSummary) => void;
}) {
  return (
    <aside class="deck-conversations" aria-label={t("deck.conversations")}>
      <div class="deck-conversations-head">
        <span>{t("deck.conversations")}</span>
        <span class="deck-conversations-count">{conversations.length}</span>
      </div>
      <button type="button" class="deck-conversation-new" onClick={onNew}>
        <span aria-hidden="true">+</span>
        {t("deck.newConversation")}
      </button>
      <div class="deck-conversation-list">
        {conversations.length === 0 ? (
          <p class="deck-conversation-empty">{t("deck.noConversations")}</p>
        ) : (
          conversations.map((conversation) => (
            <div
              key={conversation.key}
              class={`deck-conversation ${conversation.key === activeKey ? "is-active" : ""}`}
            >
              <button
                type="button"
                class="deck-conversation-select"
                aria-current={conversation.key === activeKey ? "true" : undefined}
                onClick={() => onSelect(conversation)}
              >
                <span class="deck-conversation-avatar" aria-hidden="true">
                  {(conversation.agent ?? "Br").slice(0, 2)}
                </span>
                <span class="deck-conversation-copy">
                  <strong>{conversation.label}</strong>
                  <small>{new Date(conversation.updatedAt).toLocaleString()}</small>
                </span>
              </button>
              {conversation.key !== GENERAL_SESSION ? (
                <button
                  type="button"
                  class="deck-conversation-remove"
                  onClick={() => onRemove(conversation)}
                  aria-label={`${t("deck.removeCachedConversation")}: ${conversation.label}`}
                  title={t("deck.removeCachedConversationHint")}
                >
                  ×
                </button>
              ) : null}
            </div>
          ))
        )}
      </div>
    </aside>
  );
}

function TurnBubble({
  turn,
  onPickFollowUp,
  onRegenerate,
  searchMatch,
  activeSearchMatch,
}: {
  readonly turn: Turn;
  readonly onPickFollowUp: (t: string) => void;
  readonly onRegenerate?: () => void;
  readonly searchMatch: boolean;
  readonly activeSearchMatch: boolean;
}) {
  const isDeck = turn.role === "deck";
  return (
    <article
      id={`deck-turn-${turn.id}`}
      class={`deck-turn deck-turn-${turn.role}${searchMatch ? " is-search-match" : ""}${activeSearchMatch ? " is-active-search-match" : ""}`}
    >
      <header class="deck-turn-head">
        {turn.agent ? (
          <span class="deck-turn-role deck-turn-agent">
            <span
              class="deck-turn-agent-icon"
              aria-hidden="true"
              style={{
                WebkitMaskImage: agentIconUrl(turn.agent),
                maskImage: agentIconUrl(turn.agent),
              }}
            />
            {turn.agent}
          </span>
        ) : (
          <span class="deck-turn-role">{turn.role === "operator" ? "you" : "deck"}</span>
        )}
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
