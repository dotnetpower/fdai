import type { Answer } from "./answerer";

export const SEMANTIC_UNAVAILABLE_TEXT =
  "FDAI could not produce a verified answer for this turn.";

const RESPONSE_INTEGRITY_REASONS = new Set([
  "bad JSON",
  "confirmed receipt mismatch",
  "confirmed stream mismatch",
  "confirmed verification mismatch",
  "invalid advisory response",
  "invalid advisory stream",
  "malformed stream frame",
  "missing stream sequence",
  "no answer field",
  "sequence gap",
  "stream request mismatch",
  "terminal answer mismatch",
  "terminal canonical answer mismatch",
]);

const INCOMPLETE_ANSWER_REASONS = new Set([
  "empty stream",
  "missing terminal verification",
  "terminal canonical answer missing",
  "upstream returned empty completion",
]);

function unavailableText(reason: string): string {
  if (reason === "offline") {
    return "FDAI could not reach the conversation service. No answer was produced.";
  }
  if (reason === "model not configured") {
    return "No conversation model is configured for this environment. No answer was produced.";
  }
  if (reason === "blocked by content policy") {
    return "FDAI did not answer because the request was blocked by content policy. Remove sensitive data or instruction-override content before asking again.";
  }
  if (reason === "backend 401") {
    return "The conversation request was not authorized. Sign in again before asking.";
  }
  if (reason === "backend 403") {
    return "Your current role is not authorized for this conversation request.";
  }
  if (reason === "backend 429") {
    return "The conversation provider is rate limited. No answer was produced.";
  }
  if (/^backend 5\d\d$/.test(reason) || reason === "stream interrupted" || reason === "stream error") {
    return "The conversation service became unavailable before a verified answer completed.";
  }
  if (reason.startsWith("typed evidence hold")) {
    return "FDAI held the answer because the required evidence or canonical response was incomplete.";
  }
  if (RESPONSE_INTEGRITY_REASONS.has(reason)) {
    return "FDAI rejected an inconsistent conversation response. No answer was accepted.";
  }
  if (INCOMPLETE_ANSWER_REASONS.has(reason)) {
    return "FDAI received no complete verified answer. No answer was accepted.";
  }
  return SEMANTIC_UNAVAILABLE_TEXT;
}

/** Return a terminal result without interpreting the operator's language. */
export function semanticUnavailable(
  reason: string,
): Answer & { readonly source: string } {
  return {
    text: unavailableText(reason),
    citations: [],
    followUps: [],
    source: `unavailable (${reason})`,
  };
}
