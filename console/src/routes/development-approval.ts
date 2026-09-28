const REAUTH_KEY = "fdai:development-approval-reauth";

/** The Operator accepts a development self-approval at most 10 minutes after sign-in. */
export const DEVELOPMENT_REAUTH_WINDOW_MS = 10 * 60 * 1000;

/** Remember which approval asked for a fresh sign-in, and when, across the redirect. */
export function markDevelopmentReauthentication(approvalId: string, now = Date.now()): void {
  window.sessionStorage.setItem(REAUTH_KEY, JSON.stringify({ approvalId, markedAt: now }));
}

export function hasDevelopmentReauthentication(approvalId: string, now = Date.now()): boolean {
  const raw = window.sessionStorage.getItem(REAUTH_KEY);
  if (raw === null) return false;
  try {
    const value: unknown = JSON.parse(raw);
    if (typeof value !== "object" || value === null) return false;
    const marked = (value as { readonly approvalId?: unknown }).approvalId;
    const markedAt = (value as { readonly markedAt?: unknown }).markedAt;
    return marked === approvalId
      && typeof markedAt === "number"
      && now >= markedAt
      && now - markedAt <= DEVELOPMENT_REAUTH_WINDOW_MS;
  } catch {
    return false;
  }
}

export function clearDevelopmentReauthentication(): void {
  window.sessionStorage.removeItem(REAUTH_KEY);
}
