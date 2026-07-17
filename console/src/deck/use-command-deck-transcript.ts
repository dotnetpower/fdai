import { useCallback, useEffect, useMemo, useRef, useState } from "preact/hooks";
import { matchingTurnIndexes } from "./command-deck-session";
import type { Turn } from "./command-deck-presenters";
import type { ConversationSummary } from "./conversation-sessions";
import { isNearBottom } from "./scroll-stick";
import { serializeTurns, transcriptKeyFor } from "./transcript-store";

interface MutableValueRef<T> {
  current: T;
}

interface UseCommandDeckTranscriptOptions {
  readonly turns: readonly Turn[];
  readonly conversations: readonly ConversationSummary[];
  readonly sessionKey: string;
  readonly turnsRef: MutableValueRef<readonly Turn[]>;
  readonly sessionMetadataRef: MutableValueRef<Map<string, ConversationSummary>>;
}

function sessionStore(): Storage | null {
  try {
    return typeof window !== "undefined" ? window.sessionStorage : null;
  } catch {
    return null;
  }
}

export function useCommandDeckTranscript({
  turns,
  conversations,
  sessionKey,
  turnsRef,
  sessionMetadataRef,
}: UseCommandDeckTranscriptOptions) {
  const [searchQuery, setSearchQuery] = useState("");
  const [activeSearchMatch, setActiveSearchMatch] = useState(0);
  const [stuck, setStuck] = useState(true);
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const scrollFrameRef = useRef<number | null>(null);

  const lastTurnLength = turns.length > 0
    ? (turns[turns.length - 1]?.text.length ?? 0)
    : 0;
  useEffect(() => {
    if (!stuck) return;
    if (scrollFrameRef.current !== null) cancelAnimationFrame(scrollFrameRef.current);
    scrollFrameRef.current = requestAnimationFrame(() => {
      scrollFrameRef.current = null;
      const scroller = scrollerRef.current;
      if (!scroller) return;
      const gap = scroller.scrollHeight - scroller.clientHeight - scroller.scrollTop;
      if (gap > 1) scroller.scrollTop = scroller.scrollHeight;
    });
    return () => {
      if (scrollFrameRef.current !== null) {
        cancelAnimationFrame(scrollFrameRef.current);
        scrollFrameRef.current = null;
      }
    };
  }, [lastTurnLength, stuck, turns.length]);

  const onTranscriptScroll = useCallback(() => {
    const scroller = scrollerRef.current;
    if (!scroller) return;
    setStuck(isNearBottom(
      scroller.scrollTop,
      scroller.scrollHeight,
      scroller.clientHeight,
    ));
  }, []);

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
    scroller.scrollTop = scroller.scrollHeight;
    setStuck(true);
  }, []);

  const pinTranscriptToLatest = useCallback(() => {
    setStuck(true);
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        const scroller = scrollerRef.current;
        if (scroller) scroller.scrollTop = scroller.scrollHeight;
      });
    });
  }, []);

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
    jumpToLatest,
    moveSearch,
    onTranscriptScroll,
    pinTranscriptToLatest,
    scrollerRef,
    searchMatches,
    searchQuery,
    setActiveSearchMatch,
    setSearchQuery,
    stuck,
  };
}
