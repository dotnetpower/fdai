import type { BackendTurn } from "./backend";
import type { Turn } from "./command-deck-presenters";

/** Project rendered turns into the bounded history sent to the read API. */
export function backendHistoryForTurns(turns: readonly Turn[]): BackendTurn[] {
  return turns
    .filter((turn) => turn.kind !== "activity")
    .map((turn) => ({
      role: turn.role === "operator" ? "user" : "assistant",
      content: turn.groundingText ?? turn.text,
    }));
}
