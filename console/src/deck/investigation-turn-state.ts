import type { Turn } from "./command-deck-presenters";

export interface InvestigationFlowPosition {
  readonly inFlow: boolean;
  readonly continuation: boolean;
  readonly start: boolean;
  readonly end: boolean;
}

export function investigationFlowPosition(
  turns: readonly Turn[],
  index: number,
): InvestigationFlowPosition {
  const inFlow = turnContinuesInvestigation(turns, index);
  const continuation = inFlow && !isInvestigationTurn(turns[index]);
  return {
    inFlow,
    continuation,
    start: inFlow && !turnContinuesInvestigation(turns, index - 1),
    end: inFlow && !turnContinuesInvestigation(turns, index + 1),
  };
}

function turnContinuesInvestigation(turns: readonly Turn[], index: number): boolean {
  const turn = turns[index];
  if (!turn) return false;
  if (isInvestigationTurn(turn)) return true;
  return turn.role === "deck" && isInvestigationTurn(turns[index - 1]);
}

function isInvestigationTurn(turn: Turn | undefined): boolean {
  return turn?.kind === "activity" ||
    (turn?.kind === "message" && turn.source === "investigation");
}

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
