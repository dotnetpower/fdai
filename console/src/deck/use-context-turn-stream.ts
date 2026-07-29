import { useCallback } from "preact/hooks";
import type { Turn } from "./command-deck-presenters";

export const contextStreamPacer = { intervalMs: 16 };

type StateSetter<T> = (value: T | ((current: T) => T)) => void;
interface MutableValueRef<T> {
  current: T;
}

interface UseContextTurnStreamOptions {
  readonly turnsRef: MutableValueRef<readonly Turn[]>;
  readonly contextTimersRef: MutableValueRef<Set<number>>;
  readonly setTurns: StateSetter<readonly Turn[]>;
}

function shortTime(): string {
  const date = new Date();
  return `${String(date.getHours()).padStart(2, "0")}:${String(date.getMinutes()).padStart(2, "0")}:${String(date.getSeconds()).padStart(2, "0")}`;
}

function newId(): string {
  return `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
}

export function contextChunks(text: string): string[] {
  const words = text.match(/\s*\S+/gu) ?? [];
  if (words.length <= 1) return text.match(/[\s\S]{1,12}/gu) ?? [text];
  const chunks: string[] = [];
  let chunk = "";
  let wordCount = 0;
  for (const word of words) {
    if (chunk && (wordCount >= 2 || chunk.length + word.length > 32)) {
      chunks.push(chunk);
      chunk = "";
      wordCount = 0;
    }
    chunk += word;
    wordCount += 1;
  }
  if (chunk) chunks.push(chunk);
  return chunks;
}

export function useContextTurnStream({
  turnsRef,
  contextTimersRef,
  setTurns,
}: UseContextTurnStreamOptions) {
  return useCallback((
    agent: string | null,
    fullText: string,
    source = "context",
    groundingText?: string,
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
      ...(groundingText ? { groundingText } : {}),
    };
    setTurns((current) => [...current, seed]);
    turnsRef.current = [...turnsRef.current, seed];
    if (!shouldAnimate) return;
    const chunks = contextChunks(fullText);
    let index = 0;
    const scheduleStep = (): void => {
      const timer = window.setTimeout(() => {
        contextTimersRef.current.delete(timer);
        step();
      }, contextStreamPacer.intervalMs);
      contextTimersRef.current.add(timer);
    };
    const step = (): void => {
      if (index >= chunks.length) {
        setTurns((current) =>
          current.map((turn) =>
            turn.id === turnId ? { ...turn, streaming: false } : turn,
          ),
        );
        return;
      }
      const piece = chunks[index]!;
      index += 1;
      const complete = index >= chunks.length;
      setTurns((current) =>
        current.map((turn) =>
          turn.id === turnId
            ? { ...turn, text: turn.text + piece, streaming: !complete }
            : turn,
        ),
      );
      if (!complete) scheduleStep();
    };
    scheduleStep();
  }, [contextTimersRef, setTurns, turnsRef]);
}
