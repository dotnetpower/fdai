/**
 * MSAL.js wrapper. Handles sign-in redirect, silent token acquisition,
 * and produces the `Authorization: Bearer <token>` header the read API
 * expects. In dev mode the wrapper is a no-op — the API accepts
 * anonymous requests when `AIOPSPILOT_READ_API_DEV_MODE=1` is set.
 *
 * See docs/roadmap/user-rbac-and-identity.md § 10.1 for the full flow.
 */

import {
  PublicClientApplication,
  type AccountInfo,
  type Configuration,
  InteractionRequiredAuthError,
} from "@azure/msal-browser";
import type { ConsoleConfig } from "./config";

export interface AuthContext {
  /** True when MSAL is bypassed (dev mode). Handlers must not render a
   *  "Sign out" affordance in this state. */
  readonly devMode: boolean;
  /** The signed-in account, or `null` when not signed in / dev mode. */
  readonly account: AccountInfo | null;
  /** Return the current bearer token or `null` when dev mode. */
  getAuthorizationHeader(): Promise<string | null>;
  /** Trigger sign-in redirect. No-op in dev mode. */
  signIn(): Promise<void>;
  /** Sign out redirect. No-op in dev mode. */
  signOut(): Promise<void>;
}

class DevModeAuth implements AuthContext {
  readonly devMode = true;
  readonly account = null;
  async getAuthorizationHeader(): Promise<string | null> {
    return null;
  }
  async signIn(): Promise<void> {
    /* no-op */
  }
  async signOut(): Promise<void> {
    /* no-op */
  }
}

class MsalAuth implements AuthContext {
  readonly devMode = false;
  #client: PublicClientApplication;
  #scope: string;
  #account: AccountInfo | null = null;

  constructor(client: PublicClientApplication, scope: string) {
    this.#client = client;
    this.#scope = scope;
  }

  get account(): AccountInfo | null {
    return this.#account;
  }

  async initialize(): Promise<void> {
    // Consume any redirect response first — MSAL requires this before
    // any silent-acquire call.
    await this.#client.handleRedirectPromise();
    const accounts = this.#client.getAllAccounts();
    this.#account = accounts.length > 0 ? (accounts[0] ?? null) : null;
  }

  async getAuthorizationHeader(): Promise<string | null> {
    if (!this.#account) return null;
    try {
      const result = await this.#client.acquireTokenSilent({
        account: this.#account,
        scopes: [this.#scope],
      });
      return `Bearer ${result.accessToken}`;
    } catch (err) {
      if (err instanceof InteractionRequiredAuthError) {
        await this.signIn();
      }
      return null;
    }
  }

  async signIn(): Promise<void> {
    await this.#client.loginRedirect({ scopes: [this.#scope] });
  }

  async signOut(): Promise<void> {
    if (this.#account) {
      await this.#client.logoutRedirect({ account: this.#account });
    }
  }
}

export async function initAuth(config: ConsoleConfig): Promise<AuthContext> {
  if (config.devMode) {
    return new DevModeAuth();
  }
  if (!config.msalClientId || !config.msalTenantId || !config.msalApiScope) {
    // Fail loud in prod builds — the fork MUST set these envs before
    // shipping. The console refuses to load with a clear message rather
    // than silently rendering unauthenticated calls.
    throw new Error(
      "MSAL config missing: VITE_MSAL_CLIENT_ID / VITE_MSAL_TENANT_ID / " +
        "VITE_MSAL_API_SCOPE MUST all be set for a non-dev build."
    );
  }
  const msalConfig: Configuration = {
    auth: {
      clientId: config.msalClientId,
      authority: `https://login.microsoftonline.com/${config.msalTenantId}`,
      redirectUri: window.location.origin,
      postLogoutRedirectUri: window.location.origin,
    },
    cache: {
      // In-memory + sessionStorage per user-rbac-and-identity.md §10.1
      cacheLocation: "sessionStorage",
      storeAuthStateInCookie: false,
    },
  };
  const client = new PublicClientApplication(msalConfig);
  await client.initialize();
  const auth = new MsalAuth(client, config.msalApiScope);
  await auth.initialize();
  return auth;
}
