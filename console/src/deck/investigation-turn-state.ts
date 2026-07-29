import type { Turn } from "./command-deck-presenters";

export function settleInvestigationTurn(
  turns: readonly Turn[],
  turnId: string,
): readonly Turn[] {
  return turns.map((turn) => turn.id === turnId
    ? { ...turn, streaming: false, terminal: true }
    : turn);
}

export function settleInvestigationTurns(
  turns: readonly Turn[],
  turnIds: ReadonlySet<string>,
): readonly Turn[] {
  return turns.map((turn) => turnIds.has(turn.id)
    ? { ...turn, streaming: false, terminal: true }
    : turn);
}
