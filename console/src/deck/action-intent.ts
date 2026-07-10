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
  "revoke",
]);

/** Polite prefixes stripped before inspecting the leading verb. */
const FILLER: ReadonlySet<string> = new Set([
  "please", "can", "could", "would", "you", "kindly", "pls", "hey", "ok", "okay",
]);

/** The first non-filler token of `text`, lower-cased, or null. */
export function leadingVerb(text: string): string | null {
  const tokens = text.toLowerCase().match(/[a-z0-9-]+/g);
  if (tokens === null) return null;
  for (const token of tokens) {
    if (FILLER.has(token)) continue;
    return token;
  }
  return null;
}

/** True when `text` is a mutation command (routes to the action endpoint). */
export function detectActionIntent(text: string): boolean {
  const verb = leadingVerb(text);
  return verb !== null && ACTION_VERBS.has(verb);
}
