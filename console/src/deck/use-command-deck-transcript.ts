import { useCallback, useEffect, useMemo, useRef, useState } from "preact/hooks";
import { matchingTurnIndexes } from "./command-deck-session";
import type { Turn } from "./command-deck-presenters";
import type { ConversationSummary } from "./conversation-sessions";
import {
  followAfterScroll,
  followStepScrollTop,
  followTargetScrollTop,
  isNearBottom,
  jumpToLatestVisible,
  type FollowState,
} from "./scroll-stick";
import { serializeTurns, transcriptKeyFor } from "./transcript-store";
import { sessionStore } from "./use-command-deck-sessions";

interface MutableValueRef<T> {
  current: T;
}

interface UseCommandDeckTranscriptOptions {
  readonly open: boolean;
  readonly turns: readonly Turn[];
  readonly conversations: readonly ConversationSummary[];
  readonly sessionKey: string;
  readonly turnsRef: MutableValueRef<readonly Turn[]>;
  readonly sessionMetadataRef: MutableValueRef<Map<string, ConversationSummary>>;
}

export function useCommandDeckTranscript({
  open,
  turns,
  conversations,
  sessionKey,
  turnsRef,
  sessionMetadataRef,
}: UseCommandDeckTranscriptOptions) {
  const [searchQuery, setSearchQuery] = useState("");
  const [activeSearchMatch, setActiveSearchMatch] = useState(0);
  const [jumpVisible, setJumpVisible] = useState(false);
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const followFrameRef = useRef<number | null>(null);
  const followRef = useRef<FollowState>({ following: true, mode: "bottom", expected: 0 });
  // The question being answered and, once the turn settles, the element to reveal below it.
  const pinRef = useRef<string | null>(null);
  const revealRef = useRef<{ readonly turnId: string; readonly childSelector: string } | null>(null);

  const followTarget = useCallback((scroller: HTMLElement): number => {
    const scrollerTop = scroller.getBoundingClientRect().top;
    const contentTop = (element: Element) =>
      element.getBoundingClientRect().top - scrollerTop + scroller.scrollTop;
    const pin = pinRef.current ? document.getElementById(`deck-turn-${pinRef.current}`) : null;
    const revealTurn = revealRef.current
      ? document.getElementById(`deck-turn-${revealRef.current.turnId}`)
      : null;
    const reveal = revealTurn && revealRef.current
      ? revealTurn.querySelector(revealRef.current.childSelector) ?? revealTurn
      : null;
    return followTargetScrollTop(followRef.current.mode, {
      maxScrollTop: scroller.scrollHeight - scroller.clientHeight,
      clientHeight: scroller.clientHeight,
      pinTop: pin && scroller.contains(pin) ? contentTop(pin) : null,
      revealBottom: reveal && scroller.contains(reveal)
        ? contentTop(reveal) + reveal.getBoundingClientRect().height
        : null,
    });
  }, []);

  // Only real content counts as newer below; the transcript's bottom padding is blank.
  const updateJump = useCallback((scroller: HTMLElement) => {
    const last = scroller.firstElementChild?.lastElementChild;
    const contentBelow = last
      ? last.getBoundingClientRect().bottom - scroller.getBoundingClientRect().bottom
      : 0;
    setJumpVisible(jumpToLatestVisible(
      scroller.scrollHeight - scroller.clientHeight - scroller.scrollTop,
      contentBelow,
    ));
  }, []);

  const applyFollow = useCallback(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const next = followStepScrollTop(followRef.current, scroller.scrollTop, followTarget(scroller));
    if (next !== null) scroller.scrollTop = next;
    followRef.current = { ...followRef.current, expected: scroller.scrollTop };
    updateJump(scroller);
  }, [followTarget, updateJump]);

  const scheduleFollow = useCallback(() => {
    if (followFrameRef.current !== null) cancelAnimationFrame(followFrameRef.current);
    followFrameRef.current = requestAnimationFrame(() => {
      followFrameRef.current = null;
      applyFollow();
    });
  }, [applyFollow]);

  useEffect(() => () => {
    if (followFrameRef.current !== null) cancelAnimationFrame(followFrameRef.current);
  }, []);

  const lastTurnLength = turns.length > 0
    ? (turns[turns.length - 1]?.text.length ?? 0)
    : 0;
  useEffect(() => {
    scheduleFollow();
  }, [lastTurnLength, scheduleFollow, turns.length]);

  // A different conversation starts at its newest content.
  useEffect(() => {
    pinRef.current = null;
    revealRef.current = null;
    followRef.current = { following: true, mode: "bottom", expected: 0 };
    scheduleFollow();
  }, [scheduleFollow, sessionKey]);

  useEffect(() => {
    if (!open) return;
    const scroller = scrollerRef.current;
    const content = scroller?.firstElementChild;
    if (!scroller || !content || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() => scheduleFollow());
    observer.observe(content);
    return () => observer.disconnect();
  }, [open, scheduleFollow]);

  const onTranscriptScroll = useCallback(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    const next = followAfterScroll(
      followRef.current,
      scroller.scrollTop,
      followTarget(scroller),
      isNearBottom(scroller.scrollTop, scroller.scrollHeight, scroller.clientHeight),
    );
    followRef.current = next;
    updateJump(scroller);
  }, [followTarget, updateJump]);

  useEffect(() => {
    turnsRef.current = turns;
    const store = sessionStore();
    if (!store || turns.some((turn) => turn.streaming === true)) return;
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
  }, [conversations, sessionKey, sessionMetadataRef, turns, turnsRef]);

  const jumpToLatest = useCallback(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    followRef.current = { following: true, mode: "bottom", expected: scroller.scrollTop };
    scroller.scrollTop = scroller.scrollHeight;
    applyFollow();
  }, [applyFollow]);

  /** A new question is pinned: the view follows its answer without lifting the question away. */
  const followQuestion = useCallback((turnId: string) => {
    pinRef.current = turnId;
    revealRef.current = null;
    followRef.current = {
      following: true,
      mode: "pin",
      expected: scrollerRef.current?.scrollTop ?? 0,
    };
    scheduleFollow();
  }, [scheduleFollow]);

  /** New live content arrived; a follower moves toward it, a reader who scrolled away stays put. */
  const followLatestContent = useCallback(() => {
    requestAnimationFrame(() => scheduleFollow());
  }, [scheduleFollow]);

  /** A settled turn reveals its verification row when the view is still following. */
  const revealCompletedWork = useCallback((
    turnId: string,
    childSelector: string,
  ) => {
    revealRef.current = { turnId, childSelector };
    requestAnimationFrame(() => scheduleFollow());
  }, [scheduleFollow]);

  const searchMatches = useMemo(
    () => matchingTurnIndexes(turns, searchQuery),
    [searchQuery, turns],
  );

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

  return {
    activeSearchMatch,
    followLatestContent,
    followQuestion,
    jumpToLatest,
    jumpVisible,
    moveSearch,
    onTranscriptScroll,
    revealCompletedWork,
    scrollerRef,
    searchMatches,
    searchQuery,
    setActiveSearchMatch,
    setSearchQuery,
  };
}
