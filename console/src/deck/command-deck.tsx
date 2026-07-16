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
import { navigate } from "../router";
import {
  fetchConversationTurns,
  fetchOpeningBriefing,
  type ConversationTurnPayload,
} from "../user-context-client";
import {
  askBackendStream,
  probeBackend,
  renderActionResult,
  submitAction,
  type AnswerVerification,
  type AnswerPlanMetadata,
  type BackendHealth,
  type BackendTurn,
  type GroundedCodeArtifact,
  type ProgressiveAnswer,
  type RouterSnapshot,
  type VerificationProgress,
} from "./backend";
import { detectActionIntent } from "./action-intent";
import {
  conversationGroups,
  conversationIndexKeyFor,
  conversationLabelForPrompt,
  conversationPath,
  conversationUserScope,
  isScreenConversationKey,
  manualConversationSummary,
  parseConversationIndex,
  screenConversationSummary,
  screenConversationKey,
  serializeConversationIndex,
  upsertConversation,
  userConversationKey,
  type ConversationSummary,
} from "./conversation-sessions";
import { useViewContext } from "./context";
import { getDeckUser } from "./deck-user";
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
import { drainStreamPaint } from "./stream-paint";
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
  /** True only after a terminal canonical revision has arrived. */
  readonly terminal?: boolean;
  readonly revision?: number;
  readonly verification?: AnswerVerification;
  readonly verificationProgress?: VerificationProgress;
  readonly answerPlan?: AnswerPlanMetadata;
  readonly codeArtifacts?: readonly GroundedCodeArtifact[];
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

const MIN_PREPARING_VISIBLE_MS = 420;
const DECK_LAYOUT_KEY = "fdai.deck.layout.v1";
const DECK_DOCK_WIDTH_KEY = "fdai.deck.dock-width.v1";

export type DeckLayoutMode = "floating" | "dock" | "workspace";

export function parseDeckLayoutMode(value: string | null): DeckLayoutMode {
  return value === "dock" || value === "workspace" || value === "floating"
    ? value
    : "floating";
}

export function clampDockWidth(value: number, viewportWidth: number): number {
  const maximum = Math.max(340, Math.min(720, viewportWidth - 320));
  return Math.round(Math.max(340, Math.min(maximum, value)));
}

function initialDockWidth(): number {
  if (typeof window === "undefined") return 440;
  const stored = Number.parseInt(sessionStore()?.getItem(DECK_DOCK_WIDTH_KEY) ?? "", 10);
  return clampDockWidth(Number.isFinite(stored) ? stored : 440, window.innerWidth);
}

function initialFloatingPosition(): { readonly x: number; readonly y: number } {
  if (typeof window === "undefined") return { x: 720, y: 84 };
  return {
    x: Math.max(68, window.innerWidth - 476),
    y: 76,
  };
}

function shortTime(): string {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}

export function restoredTurn(turn: ConversationTurnPayload): Turn {
  const at = new Date(turn.recorded_at);
  const time = Number.isNaN(at.getTime())
    ? turn.recorded_at
    : at.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
  const source = turn.metadata.source ?? (turn.role === "assistant" ? "history" : undefined);
  return {
    id: turn.turn_id,
    role: turn.role === "operator" ? "operator" : "deck",
    text: turn.content,
    at: time,
    terminal: true,
    ...(source ? { source } : {}),
    ...(turn.metadata.agent ? { agent: turn.metadata.agent } : {}),
  };
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

const DEFAULT_NARRATOR = "Bragi";

/** Local slash commands handled entirely in the composer - they never reach
 *  the narrator or the typed pipeline. `name` is the canonical token; the
 *  first alias (if any) is shown as a hint. */
interface DeckSlashCommand {
  readonly name: string;
  readonly aliases: readonly string[];
  readonly summary: string;
}

const DECK_SLASH_COMMANDS: readonly DeckSlashCommand[] = [
  { name: "new", aliases: ["n"], summary: "Start a new conversation" },
  { name: "clear", aliases: ["c"], summary: "Clear this conversation's cached transcript" },
  { name: "close", aliases: ["q"], summary: "Close the command deck" },
  { name: "help", aliases: ["?", "h"], summary: "List the available slash commands" },
];

/** Parse a composer string into a slash command. Returns `null` when the input
 *  is not a slash command (normal prompt). For an unrecognised `/token` the
 *  canonical name is the empty string, which callers render as help. */
function matchSlashCommand(
  input: string,
): { readonly canonical: string; readonly token: string } | null {
  const trimmed = input.trim();
  if (!trimmed.startsWith("/") || trimmed.length < 2) return null;
  const token = trimmed.slice(1).split(/\s+/, 1)[0]?.toLowerCase() ?? "";
  for (const cmd of DECK_SLASH_COMMANDS) {
    if (cmd.name === token || cmd.aliases.includes(token)) {
      return { canonical: cmd.name, token };
    }
  }
  return { canonical: "", token };
}

/** One-line help block listing every slash command. */
function slashHelpText(): string {
  const lines = DECK_SLASH_COMMANDS.map((c) => {
    const alias = c.aliases.length > 0 ? ` (/${c.aliases.join(", /")})` : "";
    return `/${c.name}${alias} - ${c.summary}`;
  });
  return ["Available commands:", ...lines].join("\n");
}

export function replyAgent(
  reply: Pick<ProgressiveAnswer, "delegation" | "verification">,
): string {
  if (
    reply.verification?.status === "corrected" ||
    reply.verification?.status === "unverified"
  ) {
    return DEFAULT_NARRATOR;
  }
  return reply.delegation?.primary_agent ?? DEFAULT_NARRATOR;
}

function currentPathname(): string {
  return typeof window === "undefined" ? "/overview" : window.location.pathname;
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
  const deckUser = getDeckUser();
  const userScope = conversationUserScope(
    deckUser?.accountId ?? deckUser?.username ?? deckUser?.name ?? null,
    deckUser?.devMode ?? false,
  );
  const indexKey = conversationIndexKeyFor(userScope);
  const initialScreenSession = screenConversationKey(userScope, currentPathname());
  const initialRouteLabel = snapshot?.routeLabel ?? currentPathname();
  const [open, setOpen] = useState(false);
  const [layoutMode, setLayoutMode] = useState<DeckLayoutMode>(() =>
    parseDeckLayoutMode(sessionStore()?.getItem(DECK_LAYOUT_KEY) ?? null));
  const [floatingPosition, setFloatingPosition] = useState(initialFloatingPosition);
  const [dockWidth, setDockWidth] = useState(initialDockWidth);
  const [dockResizing, setDockResizing] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [draft, setDraft] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [activeSearchMatch, setActiveSearchMatch] = useState(0);
  // Highlighted row in the "/" slash-command palette (keyboard navigable).
  const [slashActiveIndex, setSlashActiveIndex] = useState(0);
  // Active conversation session. The general screen deck is "screen"; a chat
  // scoped to one agent uses e.g. "agent:Forseti" and keeps a separate
  // transcript so threads never bleed into each other.
  const [sessionKey, setSessionKey] = useState<string>(initialScreenSession);
  const [sessionLabel, setSessionLabel] = useState<string | null>(null);
  const sessionKeyRef = useRef<string>(initialScreenSession);
  const [turns, setTurns] = useState<readonly Turn[]>(() => {
    const store = sessionStore();
    return store ? parseTurns(store.getItem(transcriptKeyFor(initialScreenSession))) : [];
  });
  const [conversations, setConversations] = useState<readonly ConversationSummary[]>(() => {
    const store = sessionStore();
    const restored = store
      ? parseConversationIndex(store.getItem(indexKey))
      : [];
    const previous = restored.find((item) => item.key === initialScreenSession);
    return upsertConversation(
      restored,
      screenConversationSummary(
        initialScreenSession,
        currentPathname(),
        initialRouteLabel,
        new Date().toISOString(),
        previous,
      ),
    );
  });
  const turnsRef = useRef<readonly Turn[]>(turns);
  const [pending, setPending] = useState(false);
  const [retrievalProgress, setRetrievalProgress] =
    useState<VerificationProgress | null>(null);
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
  const sessionMetadataRef = useRef(new Map<string, ConversationSummary>());
  const openingBriefingLoadedRef = useRef(new Set<string>());
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const overlayRef = useRef<HTMLDivElement | null>(null);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const searchRef = useRef<HTMLInputElement | null>(null);
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const scrollFrameRef = useRef<number | null>(null);

  // Auto-grow the composer: keep it one line tall until the text wraps, then
  // grow with the content up to the CSS max-height. The vertical scrollbar
  // only appears once the content exceeds that ceiling, so a single-line
  // prompt never shows an idle scrollbar.
  const autoGrowInput = useCallback(() => {
    const el = inputRef.current;
    if (!el) return;
    const maxHeight = 180; // keep in sync with .deck-input max-height
    el.style.height = "auto";
    const next = Math.min(el.scrollHeight, maxHeight);
    el.style.height = `${next}px`;
    el.style.overflowY = el.scrollHeight > maxHeight ? "auto" : "hidden";
  }, []);
  useEffect(() => {
    autoGrowInput();
  }, [draft, open, autoGrowInput]);

  const selectLayoutMode = useCallback((mode: DeckLayoutMode) => {
    setLayoutMode(mode);
    try {
      sessionStore()?.setItem(DECK_LAYOUT_KEY, mode);
    } catch {
      /* best-effort preference */
    }
  }, []);

  const deckStyle = useMemo(() => {
    if (layoutMode === "floating") {
      return {
        left: `${floatingPosition.x}px`,
        top: `${floatingPosition.y}px`,
      };
    }
    if (layoutMode === "dock") return { width: `${dockWidth}px` };
    return undefined;
  }, [dockWidth, floatingPosition, layoutMode]);

  const startFloatingDrag = (event: MouseEvent) => {
    if (layoutMode !== "floating" || event.button !== 0) return;
    const target = event.target as HTMLElement | null;
    if (target?.closest("button, a, input, textarea")) return;
    event.preventDefault();
    const overlay = overlayRef.current;
    if (!overlay) return;
    const rect = overlay.getBoundingClientRect();
    const offsetX = event.clientX - rect.left;
    const offsetY = event.clientY - rect.top;
    setDragging(true);

    const onMove = (moveEvent: MouseEvent) => {
      const minX = 12;
      const minY = 12;
      setFloatingPosition({
        x: Math.max(minX, moveEvent.clientX - offsetX),
        y: Math.max(minY, moveEvent.clientY - offsetY),
      });
    };
    const onEnd = () => {
      setDragging(false);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onEnd);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onEnd);
  };

  const updateDockWidth = (value: number) => {
    const next = clampDockWidth(value, window.innerWidth);
    setDockWidth(next);
    return next;
  };

  const saveDockWidth = (value: number) => {
    try {
      sessionStore()?.setItem(DECK_DOCK_WIDTH_KEY, String(value));
    } catch {
      /* best-effort preference */
    }
  };

  const startDockResize = (event: MouseEvent) => {
    if (layoutMode !== "dock" || event.button !== 0) return;
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = dockWidth;
    let latest = dockWidth;
    setDockResizing(true);

    const onMove = (moveEvent: MouseEvent) => {
      latest = updateDockWidth(startWidth + startX - moveEvent.clientX);
    };
    const onEnd = () => {
      setDockResizing(false);
      saveDockWidth(latest);
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onEnd);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onEnd);
  };

  const onDockResizeKeyDown = (event: KeyboardEvent) => {
    if (layoutMode !== "dock" || (event.key !== "ArrowLeft" && event.key !== "ArrowRight")) {
      return;
    }
    event.preventDefault();
    const delta = event.key === "ArrowLeft" ? 20 : -20;
    const next = updateDockWidth(dockWidth + delta);
    saveDockWidth(next);
  };

  const updateConversationIndex = useCallback(
    (summary: ConversationSummary) => {
      setConversations((current) => {
        const next = upsertConversation(current, summary);
        const retained = new Set(next.map((item) => item.key));
        try {
          const store = sessionStore();
          store?.setItem(indexKey, serializeConversationIndex(next));
          for (const evicted of current) {
            if (!retained.has(evicted.key)) store?.removeItem(transcriptKeyFor(evicted.key));
          }
        } catch {
          /* best-effort */
        }
        return next;
      });
    },
    [indexKey],
  );

  useEffect(() => {
    if (!snapshot?.routeLabel) return;
    const key = screenConversationKey(userScope, currentPathname());
    const existing = conversations.find((item) => item.key === key);
    if (
      existing?.kind !== "screen-default" ||
      (existing.label === snapshot.routeLabel && existing.originLabel === snapshot.routeLabel)
    ) return;
    updateConversationIndex({
      ...existing,
      label: snapshot.routeLabel,
      originLabel: snapshot.routeLabel,
    });
  }, [conversations, snapshot?.routeLabel, updateConversationIndex, userScope]);

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
      turn.streaming
        ? {
            ...turn,
            streaming: false,
            terminal: false,
            verificationProgress: {
              phase: "unverified",
              label: "Verification stopped",
              completed: null,
              total: null,
            },
          }
        : turn,
    );
    turnsRef.current = completed;
    setTurns(completed);
    setPending(false);
    setRetrievalProgress(null);
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
  const streamContextTurn = useCallback((
    agent: string | null,
    fullText: string,
    source = "context",
  ) => {
    const turnId = newId();
    const shouldAnimate =
      document.visibilityState !== "hidden" &&
      (typeof document.hasFocus !== "function" || document.hasFocus());
    const seed: Turn = {
      id: turnId,
      role: "deck",
      text: shouldAnimate ? "" : fullText,
      source,
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

  const hydrateDurableTurns = useCallback(async (key: string): Promise<void> => {
    if (sessionKeyRef.current !== key || turnsRef.current.length > 0) return;
    try {
      const durable = await fetchConversationTurns(key);
      if (sessionKeyRef.current !== key || turnsRef.current.length > 0 || durable.length === 0) {
        return;
      }
      const restored = durable.map(restoredTurn);
      turnsRef.current = restored;
      setTurns(restored);
      try {
        sessionStore()?.setItem(transcriptKeyFor(key), serializeTurns(restored));
      } catch {
        /* browser cache is best-effort; durable history remains authoritative */
      }
    } catch {
      /* A missing server conversation is a normal first-open cache miss. */
    }
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
      kind: ConversationSummary["kind"] = agent ? "agent" : "screen-default",
      register = true,
      metadata?: ConversationSummary,
    ) => {
      if (key !== sessionKeyRef.current) cancelActiveRequest();
      const store = sessionStore();
      if (store && key !== sessionKeyRef.current) {
        try {
          const outgoingKey = sessionKeyRef.current;
          const outgoing = sessionMetadataRef.current.get(outgoingKey);
          const ephemeralEmpty =
            outgoing?.kind === "screen-thread" &&
            turnsRef.current.length === 0 &&
            !conversations.some((item) => item.key === outgoingKey);
          if (ephemeralEmpty) store.removeItem(transcriptKeyFor(outgoingKey));
          else store.setItem(transcriptKeyFor(outgoingKey), serializeTurns(turnsRef.current));
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
      if (next.length === 0) void hydrateDurableTurns(key);
      setSearchQuery("");
      setActiveSearchMatch(0);
      historyRef.current = EMPTY_HISTORY;
      const existing = conversations.find((item) => item.key === key);
      const now = new Date().toISOString();
      const baseSummary = metadata ?? existing ?? {
        key,
        label: conversationLabel ?? agent ?? t("deck.newConversation"),
        kind,
        ...(agent ? { agent } : {}),
        originPath: conversationPath(currentPathname()),
        originLabel: snapshot?.routeLabel ?? currentPathname(),
        createdAt: now,
        updatedAt: now,
      };
      const summary = existing?.kind === "screen-default" && conversationLabel
        ? {
            ...baseSummary,
            label: conversationLabel,
            originLabel: conversationLabel,
          }
        : baseSummary;
      sessionMetadataRef.current.set(key, summary);
      if (register) updateConversationIndex({ ...summary, updatedAt: now });
      const note = contextNote?.trim();
      if (next.length === 0 && note) {
        streamContextTurn(agent, note);
      }
    },
    [
      cancelActiveRequest,
      conversations,
      hydrateDurableTurns,
      snapshot?.routeLabel,
      streamContextTurn,
      updateConversationIndex,
    ],
  );

  const startNewConversation = useCallback(() => {
    const key = userConversationKey(userScope, `conversation:${newId()}`);
    const summary = manualConversationSummary(
      key,
      currentPathname(),
      snapshot?.routeLabel ?? currentPathname(),
      new Date().toISOString(),
      t("deck.newConversation"),
    );
    switchSession(key, null, undefined, summary.label, summary.kind, false, summary);
    setDraft("");
    focusInput();
  }, [focusInput, snapshot?.routeLabel, switchSession, userScope]);

  // Open the deck on the general (screen) session - used by the launcher, the
  // Cmd/Ctrl+K toggle, and the `/` shortcut, so those never drop the operator
  // into a lingering agent session.
  const openGeneralDeck = useCallback(() => {
    const key = screenConversationKey(userScope, currentPathname());
    if (sessionKeyRef.current !== key) {
      switchSession(
        key,
        null,
        undefined,
        snapshot?.routeLabel ?? currentPathname(),
        "screen-default",
      );
    }
    openDeck();
    if (
      !openingBriefingLoadedRef.current.has(key)
      && !turnsRef.current.some((turn) => turn.source === "briefing")
    ) {
      openingBriefingLoadedRef.current.add(key);
      void hydrateDurableTurns(key)
        .then(() => fetchOpeningBriefing(key))
        .then((briefing) => {
          if (briefing && sessionKeyRef.current === key) {
            streamContextTurn(
              "Bragi",
              `**${briefing.title}**\n\n${briefing.body_markdown}`,
              "briefing",
            );
          }
        })
        .catch(() => {
          openingBriefingLoadedRef.current.delete(key);
        });
    }
  }, [hydrateDurableTurns, openDeck, snapshot?.routeLabel, streamContextTurn, switchSession, userScope]);

  const removeCachedConversation = useCallback(
    (conversation: ConversationSummary) => {
      const removingActive = sessionKeyRef.current === conversation.key;
      if (removingActive) cancelActiveRequest();
      const remaining = conversations.filter((item) => item.key !== conversation.key);
      try {
        const store = sessionStore();
        store?.removeItem(transcriptKeyFor(conversation.key));
        store?.setItem(indexKey, serializeConversationIndex(remaining));
      } catch {
        /* best-effort */
      }
      sessionIdsRef.current.delete(conversation.key);
      setConversations(remaining);
      if (removingActive) {
        const routeKey = screenConversationKey(userScope, currentPathname());
        const fallback = remaining.find((item) => item.key === routeKey) ?? remaining[0];
        if (fallback) {
          switchSession(
            fallback.key,
            fallback.agent ?? null,
            undefined,
            fallback.label,
            fallback.kind,
          );
        } else {
          switchSession(
            routeKey,
            null,
            undefined,
            snapshot?.routeLabel ?? currentPathname(),
            "screen-default",
          );
        }
      }
      focusInput();
    },
    [cancelActiveRequest, conversations, focusInput, indexKey, snapshot?.routeLabel, switchSession, userScope],
  );

  // Trap Tab within the open overlay so keyboard focus cannot escape the modal
  // to the read-only page behind it (aria-modal contract).
  const onOverlayKeyDown = useCallback((e: KeyboardEvent) => {
    if (layoutMode !== "workspace") return;
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
  }, [layoutMode]);

  // While the deck overlay is open, mark the document so navigation-specific
  // overlay rules can apply without affecting other drawers.
  useEffect(() => {
    const workspaceClass = "deck-open";
    const dockClass = "deck-dock-right";
    const resizingClass = "deck-dock-resizing";
    document.body.classList.toggle(workspaceClass, open && layoutMode === "workspace");
    document.body.classList.toggle(dockClass, open && layoutMode === "dock");
    document.body.classList.toggle(resizingClass, open && layoutMode === "dock" && dockResizing);
    if (open && layoutMode === "dock") {
      document.body.style.setProperty("--deck-dock-width", `${dockWidth}px`);
    } else {
      document.body.style.removeProperty("--deck-dock-width");
    }
    return () => {
      document.body.classList.remove(workspaceClass, dockClass, resizingClass);
      document.body.style.removeProperty("--deck-dock-width");
    };
  }, [dockResizing, dockWidth, layoutMode, open]);

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
      const requestedKey =
        typeof detail?.sessionKey === "string" && detail.sessionKey
          ? detail.sessionKey
          : null;
      const key =
        requestedKey
          ? userConversationKey(userScope, requestedKey)
          : screenConversationKey(userScope, currentPathname());
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
          requestedKey?.startsWith("agent:") ? "agent" : "screen-thread",
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
  }, [openDeck, switchSession, streamContextTurn, userScope]);

  // Navigation keeps the overlay open but starts (or restores) the default
  // conversation owned by this user and the new canonical menu URL. Exception:
  // in full workspace mode the deck covers the whole content area, so a menu
  // click would land on a page hidden behind it - close the deck instead so
  // the navigated screen is visible.
  //
  // The listener is attached once and reads live state through refs, so it can
  // never miss a navigation that happens right after the deck opens (an effect
  // gated on `open` would attach a frame late). Closing when already closed is
  // a harmless no-op, so the handler does not need an open-guard.
  const layoutModeRef = useRef(layoutMode);
  const openRef = useRef(open);
  const routeLabelRef = useRef<string | undefined>(snapshot?.routeLabel);
  useEffect(() => { layoutModeRef.current = layoutMode; }, [layoutMode]);
  useEffect(() => { openRef.current = open; }, [open]);
  useEffect(() => { routeLabelRef.current = snapshot?.routeLabel; }, [snapshot?.routeLabel]);
  useEffect(() => {
    const switchToCurrentRoute = () => {
      if (layoutModeRef.current === "workspace") {
        // Full workspace covers the content area; a menu click would land on a
        // page hidden behind the deck, so close it to reveal the destination.
        closeDeck();
        return;
      }
      if (!openRef.current) return;
      const key = screenConversationKey(userScope, currentPathname());
      if (sessionKeyRef.current !== key) {
        switchSession(
          key,
          null,
          undefined,
          routeLabelRef.current ?? currentPathname(),
          "screen-default",
        );
      }
    };
    window.addEventListener("popstate", switchToCurrentRoute);
    window.addEventListener("fdai:route-changed", switchToCurrentRoute);
    return () => {
      window.removeEventListener("popstate", switchToCurrentRoute);
      window.removeEventListener("fdai:route-changed", switchToCurrentRoute);
    };
  }, [closeDeck, switchSession, userScope]);

  useEffect(() => () => cancelActiveRequest(), [cancelActiveRequest]);

  // Focus guard: while the deck is open, a live route behind it re-renders on
  // every stream frame. Those background re-renders can steal focus out of the
  // input onto a topbar/background control, which silently swallows the
  // operator's keystrokes (a stray Space then scrolls the page or toggles a
  // background button - e.g. closing the deck). Pull focus back to the input
  // whenever it escapes to anything that is neither inside the overlay nor the
  // still-interactive navigation shell. A genuine click on a background control still
  // fires (click precedes focus); only the stuck-focus is corrected.
  useEffect(() => {
    if (!open || layoutMode !== "workspace") return;
    const onFocusIn = (e: FocusEvent) => {
      const target = e.target as HTMLElement | null;
      if (!target) return;
      const overlay = overlayRef.current;
      if (overlay && overlay.contains(target)) return;
      if (target.closest(".navigation-shell")) return;
      requestAnimationFrame(() => inputRef.current?.focus());
    };
    document.addEventListener("focusin", onFocusIn);
    return () => document.removeEventListener("focusin", onFocusIn);
  }, [layoutMode, open]);

  // Follow new content (including streaming token growth) only while the
  // operator is reading the latest turn. If they scrolled up to re-read an
  // earlier answer, an arriving reply must not yank them back down.
  const lastTurnLen = turns.length > 0 ? (turns[turns.length - 1]?.text.length ?? 0) : 0;
  useEffect(() => {
    if (!stuck) return;
    if (scrollFrameRef.current !== null) cancelAnimationFrame(scrollFrameRef.current);
    scrollFrameRef.current = requestAnimationFrame(() => {
      scrollFrameRef.current = null;
      const el = scrollerRef.current;
      if (!el) return;
      const gap = el.scrollHeight - el.clientHeight - el.scrollTop;
      if (gap > 1) el.scrollTop = el.scrollHeight;
    });
    return () => {
      if (scrollFrameRef.current !== null) {
        cancelAnimationFrame(scrollFrameRef.current);
        scrollFrameRef.current = null;
      }
    };
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
      const summary = sessionMetadataRef.current.get(sessionKey);
      if (
        summary?.kind === "screen-thread" &&
        turns.length === 0 &&
        !conversations.some((item) => item.key === sessionKey)
      ) {
        store.removeItem(transcriptKeyFor(sessionKey));
        return;
      }
      store.setItem(transcriptKeyFor(sessionKey), serializeTurns(turns));
    } catch {
      /* storage full or blocked - persistence is best-effort */
    }
  }, [conversations, turns, sessionKey]);

  const jumpToLatest = useCallback(() => {
    const el = scrollerRef.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    setStuck(true);
  }, []);

  const pinTranscriptToLatest = useCallback(() => {
    setStuck(true);
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        const el = scrollerRef.current;
        if (el) el.scrollTop = el.scrollHeight;
      });
    });
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
    const sessionSummary = activeSummary ?? sessionMetadataRef.current.get(originSessionKey);
    const hasOperatorTurn = turnsRef.current.some((turn) => turn.role === "operator");
    updateConversationIndex({
      key: originSessionKey,
      label:
        sessionSummary
          ? conversationLabelForPrompt(sessionSummary, text, hasOperatorTurn)
          : t("deck.general"),
      kind: sessionSummary?.kind ?? "screen-default",
      ...(sessionSummary?.agent ? { agent: sessionSummary.agent } : {}),
      originPath: sessionSummary?.originPath ?? conversationPath(currentPathname()),
      originLabel: sessionSummary?.originLabel ?? snapshot?.routeLabel ?? currentPathname(),
      createdAt: sessionSummary?.createdAt ?? new Date().toISOString(),
      updatedAt: new Date().toISOString(),
    });
    setTurns((prev) => [...prev, opTurn]);
    turnsRef.current = [...turnsRef.current, opTurn];
    setDraft("");
    historyRef.current = recordHistory(historyRef.current, text);
    setPending(true);
    setRetrievalProgress(null);
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
            {
              id: newId(),
              role: "deck",
              text: renderActionResult(result),
              agent: DEFAULT_NARRATOR,
              terminal: true,
              at: shortTime(),
            },
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
      let visibleAcc = "";
      let pendingRevision = 0;
      const preparingStartedAt = Date.now();
      let revealTimer: number | null = null;
      let paintFrame: number | null = null;
      const paintQueue: string[] = [];
      let paintDrainResolve: (() => void) | null = null;
      // Reveal the streaming reply bubble on the first token (until then the
      // RetrievalTrace "preparing answer" surface stays up).
      const ensureTurn = () => {
        if (started || !isCurrent()) return;
        started = true;
        setPending(false);
        setRetrievalProgress(null);
        setSrStatus("Assistant is answering...");
        setTurns((prev) => {
          const next: readonly Turn[] = [
            ...prev,
            {
              id: deckId,
              role: "deck",
              text: visibleAcc,
              streaming: true,
              terminal: false,
              revision: pendingRevision,
              agent: DEFAULT_NARRATOR,
              at: shortTime(),
            },
          ];
          turnsRef.current = next;
          return next;
        });
        scheduleStreamPaint();
        pinTranscriptToLatest();
      };
      const revealWhenReady = () => {
        if (started || revealTimer !== null || !isCurrent()) return;
        const remaining = MIN_PREPARING_VISIBLE_MS - (Date.now() - preparingStartedAt);
        if (remaining <= 0) {
          ensureTurn();
          return;
        }
        revealTimer = window.setTimeout(() => {
          revealTimer = null;
          ensureTurn();
        }, remaining);
      };
      const scheduleStreamPaint = () => {
        if (!started || paintFrame !== null || paintQueue.length === 0 || !isCurrent()) return;
        paintFrame = requestAnimationFrame(() => {
          paintFrame = null;
          if (!isCurrent()) return;
          visibleAcc += drainStreamPaint(paintQueue);
          setTurns((prev) => {
            const next = prev.map((turn) =>
              turn.id === deckId ? { ...turn, text: visibleAcc } : turn,
            );
            turnsRef.current = next;
            return next;
          });
          if (paintQueue.length > 0) {
            scheduleStreamPaint();
          } else {
            paintDrainResolve?.();
            paintDrainResolve = null;
          }
        });
      };
      const waitForPaintDrain = async () => {
        if (paintQueue.length === 0 && paintFrame === null) return;
        await new Promise<void>((resolve) => {
          paintDrainResolve = resolve;
          scheduleStreamPaint();
        });
      };
      const reply = await askBackendStream(text, snapshot, history, {
        sessionId: sessionIdFor(sessionIdsRef.current, originSessionKey),
        onToken: (delta) => {
          if (!isCurrent()) return;
          paintQueue.push(delta);
          revealWhenReady();
          if (!started) return;
          scheduleStreamPaint();
        },
        onProgress: (progress) => {
          if (!isCurrent()) return;
          setSrStatus(progress.label);
          if (!started) {
            setRetrievalProgress(progress);
            return;
          }
          setTurns((prev) => {
            const next = prev.map((turn) =>
              turn.id === deckId ? { ...turn, verificationProgress: progress } : turn,
            );
            turnsRef.current = next;
            return next;
          });
        },
        onRevision: (answer, revision, status) => {
          if (!isCurrent()) return;
          visibleAcc = answer;
          paintQueue.length = 0;
          pendingRevision = revision;
          revealWhenReady();
          setSrStatus(
            status === "corrected"
              ? "Answer corrected."
              : status === "unverified"
                ? "Answer could not be verified."
                : "Answer verified.",
          );
          if (!started) return;
          if (paintFrame !== null) {
            cancelAnimationFrame(paintFrame);
            paintFrame = null;
          }
          setTurns((prev) => {
            const next = prev.map((turn) =>
              turn.id === deckId && revision > (turn.revision ?? 0)
                ? { ...turn, text: answer, revision }
                : turn,
            );
            turnsRef.current = next;
            return next;
          });
        },
        signal: controller.signal,
      });
      if (!started && isCurrent()) {
        const remaining = MIN_PREPARING_VISIBLE_MS - (Date.now() - preparingStartedAt);
        if (remaining > 0) {
          await new Promise<void>((resolve) => window.setTimeout(resolve, remaining));
        }
      }
      if (revealTimer !== null) {
        window.clearTimeout(revealTimer);
        revealTimer = null;
      }
      if (paintFrame !== null) {
        cancelAnimationFrame(paintFrame);
        paintFrame = null;
      }
      ensureTurn();
      await waitForPaintDrain();
      if (isCurrent()) {
        setTurns((prev) => {
          const next = prev.map((t) =>
            t.id === deckId
              ? {
                  ...t,
                  text: reply.text,
                  streaming: false,
                  terminal: reply.source !== "stopped" && !reply.source.startsWith("partial"),
                  citations: reply.citations,
                  followUps: reply.followUps,
                  source: reply.source,
                  agent: replyAgent(reply),
                  ...(reply.verification ? { verification: reply.verification } : {}),
                  ...(reply.router ? { router: reply.router } : {}),
                  ...(reply.answerPlan ? { answerPlan: reply.answerPlan } : {}),
                  ...(reply.codeArtifacts ? { codeArtifacts: reply.codeArtifacts } : {}),
                }
              : t,
            );
            turnsRef.current = next;
            return next;
          });
        pinTranscriptToLatest();
      }
    } finally {
      if (isCurrent()) {
        activeRequestRef.current = null;
        abortRef.current = null;
        inFlightRef.current = false;
        setPending(false);
        setRetrievalProgress(null);
        setSrStatus(controller.signal.aborted ? "Stopped." : "Answer ready.");
        setInFlight(false);
        focusInput();
      }
    }
  }, [
    snapshot,
    focusInput,
    pending,
    turns,
    conversations,
    updateConversationIndex,
    pinTranscriptToLatest,
  ]);

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

  // Append a local narrator-voiced notice (slash-command feedback). It never
  // hits the backend or the typed pipeline - purely a composer affordance.
  const appendDeckNotice = useCallback((text: string) => {
    const turn: Turn = {
      id: newId(),
      role: "deck",
      text,
      agent: DEFAULT_NARRATOR,
      terminal: true,
      at: shortTime(),
    };
    setTurns((prev) => [...prev, turn]);
    turnsRef.current = [...turnsRef.current, turn];
  }, []);

  // Intercept a `/command` typed in the composer. Returns true when the input
  // was a slash command (handled locally, not sent to the narrator). Unknown
  // `/tokens` render the help block instead of reaching the backend.
  const runSlashCommand = useCallback(
    (input: string): boolean => {
      const match = matchSlashCommand(input);
      if (match === null) return false;
      setDraft("");
      switch (match.canonical) {
        case "new":
          startNewConversation();
          break;
        case "clear":
          clearTurns();
          break;
        case "close":
          closeDeck();
          break;
        case "help":
          appendDeckNotice(slashHelpText());
          break;
        default:
          appendDeckNotice(`Unknown command "/${match.token}".\n\n${slashHelpText()}`);
      }
      return true;
    },
    [startNewConversation, clearTurns, closeDeck, appendDeckNotice],
  );

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
  //
  // Slash-command hint palette: surfaces while the operator is still typing the
  // command token (a leading `/` with no whitespace yet). Empties out the
  // moment the input stops looking like a bare command.
  const slashSuggestions = useMemo(() => {
    const trimmed = draft.trim();
    if (!/^\/\S*$/.test(trimmed)) return [] as DeckSlashCommand[];
    const token = trimmed.slice(1).toLowerCase();
    return DECK_SLASH_COMMANDS.filter(
      (c) => c.name.startsWith(token) || c.aliases.some((a) => a.startsWith(token)),
    );
  }, [draft]);
  // Keep the highlighted palette row in range as the filtered set changes.
  useEffect(() => {
    setSlashActiveIndex((i) => (slashSuggestions.length === 0 ? 0 : Math.min(i, slashSuggestions.length - 1)));
  }, [slashSuggestions.length]);
  const onInputKeyDown = useCallback(
    (e: KeyboardEvent) => {
      const el = e.target as HTMLTextAreaElement;
      // When the "/" palette is open, arrow keys move the selection and Enter
      // runs the highlighted command instead of submitting or recalling history.
      if (slashSuggestions.length > 0) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setSlashActiveIndex((i) => (i + 1) % slashSuggestions.length);
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          setSlashActiveIndex((i) => (i - 1 + slashSuggestions.length) % slashSuggestions.length);
          return;
        }
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          const picked = slashSuggestions[Math.min(slashActiveIndex, slashSuggestions.length - 1)];
          if (picked) runSlashCommand(`/${picked.name}`);
          return;
        }
        if (e.key === "Escape") {
          e.preventDefault();
          setDraft("");
          return;
        }
      }
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        if (runSlashCommand(el.value)) return;
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
    [submit, runSlashCommand, slashSuggestions, slashActiveIndex],
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
              d="M3 2.75h10a1.5 1.5 0 0 1 1.5 1.5v6a1.5 1.5 0 0 1-1.5 1.5H7L3.5 14v-2.25H3a1.5 1.5 0 0 1-1.5-1.5v-6A1.5 1.5 0 0 1 3 2.75Z"
              fill="none"
              stroke="currentColor"
              stroke-width="1.4"
              stroke-linecap="round"
              stroke-linejoin="round"
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
          class={`deck-overlay deck-overlay-mode-${layoutMode}${dragging ? " is-dragging" : ""}`}
          role={layoutMode === "workspace" ? "dialog" : "complementary"}
          aria-modal={layoutMode === "workspace" ? "true" : undefined}
          aria-label={t("deck.label")}
          ref={overlayRef}
          style={deckStyle}
          onKeyDown={onOverlayKeyDown}
        >
          <button
            type="button"
            class="deck-dock-resize-handle"
            role="separator"
            aria-label="Resize right sidebar"
            aria-orientation="vertical"
            aria-valuemin={340}
            aria-valuemax={clampDockWidth(720, typeof window === "undefined" ? 1440 : window.innerWidth)}
            aria-valuenow={dockWidth}
            onMouseDown={startDockResize}
            onKeyDown={onDockResizeKeyDown}
          >
            <span /><span /><span />
          </button>
          <div class="deck-header">
            <div
              class="deck-header-title"
              title={layoutMode === "floating" ? "Drag to move" : undefined}
              onMouseDown={startFloatingDrag}
            >
              <span class="deck-header-glyph" aria-hidden="true">
                <svg viewBox="0 0 16 16" width="14" height="14">
                  <path
                    d="M3 2.75h10a1.5 1.5 0 0 1 1.5 1.5v6a1.5 1.5 0 0 1-1.5 1.5H7L3.5 14v-2.25H3a1.5 1.5 0 0 1-1.5-1.5v-6A1.5 1.5 0 0 1 3 2.75Z"
                    fill="none"
                    stroke="currentColor"
                    stroke-width="1.4"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                  />
                </svg>
              </span>
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
            <button
              type="button"
              class="deck-header-new"
              onClick={startNewConversation}
              title={t("deck.newConversation")}
              aria-label={t("deck.newConversation")}
            >
              <span class="deck-header-new-glyph" aria-hidden="true">+</span>
              <span class="deck-header-new-label">{t("deck.newConversation")}</span>
            </button>
            <div class="deck-layout-controls" aria-label="Command deck layout">
              <button
                type="button"
                class="deck-layout-button"
                aria-label="Floating panel"
                title="Floating panel"
                aria-pressed={layoutMode === "floating"}
                onClick={() => selectLayoutMode("floating")}
              >
                <DeckLayoutIcon mode="floating" />
              </button>
              <button
                type="button"
                class="deck-layout-button"
                aria-label="Dock right"
                title="Dock right"
                aria-pressed={layoutMode === "dock"}
                onClick={() => selectLayoutMode("dock")}
              >
                <DeckLayoutIcon mode="dock" />
              </button>
              <button
                type="button"
                class="deck-layout-button"
                aria-label="Full workspace"
                title="Full workspace"
                aria-pressed={layoutMode === "workspace"}
                onClick={() => selectLayoutMode("workspace")}
              >
                <DeckLayoutIcon mode="workspace" />
              </button>
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
              currentPath={currentPathname()}
              onNew={startNewConversation}
              onRemove={removeCachedConversation}
              onSelect={(conversation) => {
                if (
                  conversation.kind !== "agent" &&
                  conversation.originPath !== conversationPath(currentPathname())
                ) {
                  navigate(conversation.originPath);
                }
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
              {pending ? (
                <RetrievalTrace
                  snapshot={snapshot}
                  health={health}
                  progress={retrievalProgress}
                />
              ) : null}
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
              if (runSlashCommand(draft)) return;
              submit(draft);
            }}
          >
            {slashSuggestions.length > 0 ? (
              <ul class="deck-slash-palette" aria-label="slash commands">
                {slashSuggestions.map((cmd, i) => (
                  <li key={cmd.name}>
                    <button
                      type="button"
                      class={`deck-slash-item${i === slashActiveIndex ? " is-active" : ""}`}
                      onMouseEnter={() => setSlashActiveIndex(i)}
                      onMouseDown={(e) => {
                        // Keep composer focus; run before the input blurs.
                        e.preventDefault();
                        runSlashCommand(`/${cmd.name}`);
                      }}
                    >
                      <span class="deck-slash-name">/{cmd.name}</span>
                      <span class="deck-slash-summary muted">{cmd.summary}</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
            <textarea
              ref={inputRef}
              class="deck-input"
              placeholder="Ask anything, or type / for commands"
              value={draft}
              rows={1}
              onInput={(e) => setDraft((e.target as HTMLTextAreaElement).value)}
              onKeyDown={onInputKeyDown}
            />
            <div class="deck-input-actions">
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

function DeckLayoutIcon({ mode }: { readonly mode: DeckLayoutMode }) {
  if (mode === "dock") {
    return (
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <rect x="2" y="2.5" width="12" height="11" rx="1.5" />
        <path d="M10 3v10" />
      </svg>
    );
  }
  if (mode === "workspace") {
    return (
      <svg viewBox="0 0 16 16" aria-hidden="true">
        <path d="M5.5 2.5h-3v3M10.5 2.5h3v3M5.5 13.5h-3v-3M10.5 13.5h3v-3" />
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 16 16" aria-hidden="true">
      <rect x="3" y="4" width="10" height="8" rx="1.5" />
      <path d="M3.5 6.5h9" />
    </svg>
  );
}

// ---------------------------------------------------------------------------
// Subcomponents (each with one job)
// ---------------------------------------------------------------------------

function ConversationSidebar({
  conversations,
  activeKey,
  currentPath,
  onNew,
  onSelect,
  onRemove,
}: {
  readonly conversations: readonly ConversationSummary[];
  readonly activeKey: string;
  readonly currentPath: string;
  readonly onNew: () => void;
  readonly onSelect: (conversation: ConversationSummary) => void;
  readonly onRemove: (conversation: ConversationSummary) => void;
}) {
  const groups = conversationGroups(conversations, currentPath);
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
          <>
            <ConversationGroup
              label={t("deck.currentScreen")}
              conversations={groups.current}
              activeKey={activeKey}
              showOrigin={false}
              onSelect={onSelect}
              onRemove={onRemove}
            />
            <ConversationGroup
              label={t("deck.otherScreens")}
              conversations={groups.other}
              activeKey={activeKey}
              showOrigin
              onSelect={onSelect}
              onRemove={onRemove}
            />
            <ConversationGroup
              label={t("deck.agentConversations")}
              conversations={groups.agents}
              activeKey={activeKey}
              showOrigin
              onSelect={onSelect}
              onRemove={onRemove}
            />
          </>
        )}
      </div>
    </aside>
  );
}

function ConversationGroup({
  label,
  conversations,
  activeKey,
  showOrigin,
  onSelect,
  onRemove,
}: {
  readonly label: string;
  readonly conversations: readonly ConversationSummary[];
  readonly activeKey: string;
  readonly showOrigin: boolean;
  readonly onSelect: (conversation: ConversationSummary) => void;
  readonly onRemove: (conversation: ConversationSummary) => void;
}) {
  if (conversations.length === 0) return null;
  return (
    <section class="deck-conversation-group" aria-label={label}>
      <h3>{label}</h3>
      {conversations.map((conversation) => (
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
            <span
              class="deck-conversation-avatar is-agent"
              aria-hidden="true"
              style={{
                WebkitMaskImage: agentIconUrl(conversation.agent ?? DEFAULT_NARRATOR),
                maskImage: agentIconUrl(conversation.agent ?? DEFAULT_NARRATOR),
              }}
            />
            <span class="deck-conversation-copy">
              <strong>{conversation.label}</strong>
              <small>
                {showOrigin && conversation.originLabel !== conversation.label
                  ? `${conversation.originLabel} · `
                  : ""}
                {new Date(conversation.updatedAt).toLocaleString()}
              </small>
            </span>
          </button>
          {!isScreenConversationKey(conversation.key) ? (
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
      ))}
    </section>
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
      class={`deck-turn deck-turn-${turn.role}${turn.streaming ? " is-streaming" : ""}${searchMatch ? " is-search-match" : ""}${activeSearchMatch ? " is-active-search-match" : ""}`}
    >
      {isDeck ? (
        <header class="deck-turn-head">
          <span class="deck-turn-role deck-turn-agent">
            <span
              class="deck-turn-agent-icon"
              aria-hidden="true"
              style={{
                WebkitMaskImage: agentIconUrl(turn.agent ?? DEFAULT_NARRATOR),
                maskImage: agentIconUrl(turn.agent ?? DEFAULT_NARRATOR),
              }}
            />
            {turn.agent ?? DEFAULT_NARRATOR}
          </span>
          {turn.source ? (
            <span
              class="deck-turn-source"
              title={routerTooltip(turn.router) ?? "reply source"}
            >
              {turn.source}
            </span>
          ) : null}
        </header>
      ) : null}
      {isDeck ? (
        <GroundedReply
          turnId={turn.id}
          text={turn.text}
          citations={turn.citations}
          source={turn.source}
          streaming={turn.streaming === true}
          verification={turn.verification}
          verificationProgress={turn.verificationProgress}
          answerPlan={turn.answerPlan}
          codeArtifacts={turn.codeArtifacts}
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
      <div class="deck-turn-foot">
        <span class="deck-turn-time muted">{turn.at}</span>
      </div>
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
        Ask about anything currently visible - tiles, KPIs, approvals, audit rows,
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
  "gate.hil": "High-risk actions routed to human approval.",
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
        Approvals, Trace, Blast Radius, Promotion, or Ontology.
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
