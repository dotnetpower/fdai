import type { Answer } from "./answerer";

export const SEMANTIC_UNAVAILABLE_TEXT =
  "Semantic interpretation is unavailable for this turn.";

/** Return a terminal result without interpreting the operator's language. */
export function semanticUnavailable(
  reason: string,
): Answer & { readonly source: string } {
  return {
    text: SEMANTIC_UNAVAILABLE_TEXT,
    citations: [],
    followUps: [],
    source: `unavailable (${reason})`,
  };
}
