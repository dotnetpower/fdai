/**
 * deck-user - the signed-in operator's identity + Entra App Roles, made
 * available to the chat deck.
 *
 * The deck forwards this (as `_user` in the chat request's view_context) so the
 * narrator can answer "what can I do?" from the operator's real roles. The
 * roles come from the verified MSAL id token (`account.idTokenClaims.roles`) -
 * the same App Role claim the read API verifies server-side. This is
 * informational only: the chat is read-only and every real permission is
 * enforced by the executor / PR / HIL gates regardless of what the narrator
 * explains, so surfacing the roles here cannot grant access.
 *
 * Set once at app init (App, after auth resolves); read by backend.ts when it
 * builds a chat request.
 */

import type { AuthContext } from "../auth";

export interface DeckUser {
  readonly accountId: string;
  readonly name: string | null;
  readonly username: string | null;
  readonly roles: readonly string[];
  readonly devMode: boolean;
}

let current: DeckUser | null = null;

export function setDeckUser(user: DeckUser | null): void {
  current = user;
}

export function getDeckUser(): DeckUser | null {
  return current;
}

/** Derive the deck user from the MSAL auth context (roles from id-token claims). */
export function deckUserFromAuth(auth: AuthContext): DeckUser {
  if (auth.devMode && !auth.localAzureCli) {
    return { accountId: "dev", name: "dev", username: null, roles: [], devMode: true };
  }
  const account = auth.account;
  const claims = (account?.idTokenClaims ?? {}) as Record<string, unknown>;
  const rawRoles = claims["roles"];
  const roles = Array.isArray(rawRoles)
    ? rawRoles.filter((r): r is string => typeof r === "string")
    : [];
  return {
    accountId: account?.homeAccountId ?? account?.localAccountId ?? "anonymous",
    name: account?.name ?? null,
    username: account?.username ?? null,
    roles,
    devMode: auth.devMode,
  };
}
