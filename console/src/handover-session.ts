/** Browser login identity only; the server independently enforces every handover budget. */
const SESSION_KEY = "fdai.handover.login-session.v1";

export function handoverLoginSessionId(storage: Storage | null): string {
  const existing = storage?.getItem(SESSION_KEY)?.trim();
  if (existing) return existing;
  const generated = typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `handover-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
  storage?.setItem(SESSION_KEY, generated);
  return generated;
}

/** Successful authentication redirects begin a new bounded login, not a new allowance. */
export function resetHandoverLoginSession(storage: Storage | null): void {
  storage?.removeItem(SESSION_KEY);
}

/** Retain the goal suffix consumed by the server-binding transport. */
export function handoverConversationKey(goalId: string, loginSessionId: string): string {
  return `login:${loginSessionId}:handover:${goalId}`;
}
