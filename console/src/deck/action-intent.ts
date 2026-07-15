/**
 * Action-intent detection for the command deck (mirrors the server-side
 * `fdai.agents.introspection.is_action_intent`).
 *
 * A leading imperative verb (after stripping polite filler) means the operator
 * wants to CHANGE something - the deck routes that to `POST /chat/action`
 * (submit a proposal into the typed pipeline) instead of the read-only
 * narrator. An interrogative ("what / why / show / list ...") is a question and
 * stays with the narrator.
 *
 * This is a detection heuristic only; the authoritative verb -> ActionType
 * mapping and the RBAC gate live server-side (console_action.py). Keeping the
 * verb list in sync with the Python set is a deliberate, small duplication so
 * the deck can decide which endpoint to call without a round-trip.
 */

/** Imperative verbs that denote a mutation request. Mirrors `_ACTION_VERBS`. */
const ACTION_VERBS: ReadonlySet<string> = new Set([
  "restart", "reboot", "delete", "remove", "drop", "destroy", "scale", "resize",
  "failover", "remediate", "encrypt", "execute", "run", "apply", "deploy",
  "provision", "rollback", "revert", "approve", "reject", "disable", "enable",
  "create", "kill", "drain", "terminate", "mutate", "patch", "update", "set",
  "start", "stop", "promote", "retire", "override", "flush", "purge", "grant",
  "revoke", "open", "transition", "assign",
]);

/** Polite prefixes stripped before inspecting the leading verb. */
const FILLER: ReadonlySet<string> = new Set([
  "please", "can", "could", "would", "you", "kindly", "pls", "hey", "ok", "okay",
]);

const INCIDENT_TERMS: readonly string[] = ["incident", "case", "인시던트", "케이스", "장애"];
const INCIDENT_CREATE_TERMS: readonly string[] = [
  "create", "open", "register", "start", "생성", "열어", "오픈", "등록", "접수",
];
const INCIDENT_CONFIRMATIONS: ReadonlySet<string> = new Set([
  "confirm", "confirmed", "yes", "proceed", "확인", "생성", "진행", "cancel", "취소",
]);

/**
 * Verbs that double as a noun / adjective, so a leading occurrence is NOT
 * automatically a command ("set of rules?", "run status?", "update history?").
 * Mirrors the server `_AMBIGUOUS_ACTION_VERBS`. Every entry is also in
 * {@link ACTION_VERBS}; an ambiguous lead is a command only when phrased
 * imperatively (no question mark, no interrogative marker).
 */
const AMBIGUOUS_ACTION_VERBS: ReadonlySet<string> = new Set([
  "set", "start", "stop", "update", "run", "apply", "patch", "drain",
]);

/**
 * Interrogative markers that flip an ambiguous-verb lead back to a question.
 * Mirrors the server `_QUESTION_MARKERS`.
 */
const QUESTION_MARKERS: ReadonlySet<string> = new Set([
  "what", "why", "who", "how", "when", "which", "where", "whose", "whom",
  "is", "are", "was", "were", "do", "does", "did", "show", "list", "tell",
  "explain", "describe", "status", "count", "many", "much", "any",
]);

/** Defensive cap mirroring the server `_MAX_QUESTION_LEN`: only a bounded
 *  prefix is inspected so a pathological input cannot inflate tokenization. */
const MAX_QUESTION_LEN = 2000;

/** The first non-filler token of `text`, lower-cased, or null. */
export function leadingVerb(text: string): string | null {
  const tokens = text.slice(0, MAX_QUESTION_LEN).toLowerCase().match(/[a-z0-9-]+/g);
  if (tokens === null) return null;
  for (const token of tokens) {
    if (FILLER.has(token)) continue;
    return token;
  }
  return null;
}

/** True when `text` is a mutation command (routes to the action endpoint).
 *
 * Deterministic and conservative, matching the server `is_action_intent`: a
 * leading imperative verb is a command, EXCEPT an ambiguous verb (one that
 * doubles as a noun) followed by a question mark or an interrogative marker,
 * which is a question and stays with the read-only narrator. Keeping this in
 * lockstep with the Python guard is why the ambiguous / question-marker sets
 * are mirrored above; drift would misroute a question to `POST /chat/action`.
 */
export function detectActionIntent(text: string): boolean {
  const normalized = text.slice(0, MAX_QUESTION_LEN).trim().toLowerCase();
  if (INCIDENT_CONFIRMATIONS.has(normalized)) return true;
  if (
    INCIDENT_TERMS.some((term) => normalized.includes(term)) &&
    INCIDENT_CREATE_TERMS.some((term) => normalized.includes(term))
  ) {
    return true;
  }
  if (
    normalized.includes("incident") &&
    ((normalized.includes("상태") && normalized.includes("변경")) ||
      (normalized.includes("담당자") && normalized.includes("지정")))
  ) {
    return true;
  }
  const verb = leadingVerb(text);
  if (verb === null) return false;
  if (AMBIGUOUS_ACTION_VERBS.has(verb)) {
    const head = text.slice(0, MAX_QUESTION_LEN).toLowerCase();
    if (head.includes("?")) return false;
    const tokens = head.match(/[a-z0-9-]+/g) ?? [];
    if (tokens.some((token) => QUESTION_MARKERS.has(token))) return false;
    return true;
  }
  return ACTION_VERBS.has(verb);
}
