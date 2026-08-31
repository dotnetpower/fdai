/**
 * MSAL.js wrapper. Handles sign-in redirect, silent token acquisition,
 * and produces the `Authorization: Bearer <token>` header the Operator API
 * expects. In dev mode the wrapper is a no-op - the API accepts
 * anonymous requests when `FDAI_OPERATOR_API_DEV_MODE=1` is set. Local Azure
 * CLI mode reads only a browser-safe profile from the local API; the CLI
 * access token remains in the API process.
 *
 * See docs/roadmap/interfaces/user-rbac-and-identity.md § 10.1 for the full flow.
 */

import type {
  AccountInfo,
  Configuration,
  PublicClientApplication,
} from "@azure/msal-browser";
import {
  installAuthSessionKeeper,
  msalCacheLocationForOrigin,
} from "./auth-session";
import type { ConsoleConfig } from "./config";

type InteractionRequiredAuthErrorConstructor =
  typeof import("@azure/msal-browser").InteractionRequiredAuthError;

export interface AuthAccount {
  readonly homeAccountId: string;
  readonly localAccountId: string;
  readonly username: string;
  readonly name?: string;
  readonly idTokenClaims?: Record<string, unknown>;
}

export interface AuthContext {
  /** True when MSAL is bypassed (dev mode). Handlers must not render a
   *  "Sign out" affordance in this state. */
  readonly devMode: boolean;
  /** True when the local API projected the active Azure CLI user. */
  readonly localAzureCli?: boolean;
  /** The signed-in account, or `null` when not signed in / dev mode. */
  readonly account: AuthAccount | null;
  /** True when this context can start an interactive identity-provider login. */
  readonly interactiveSignIn?: boolean;
  /** Return the current bearer token or `null` when dev mode. */
  getAuthorizationHeader(): Promise<string | null>;
  /** Trigger sign-in redirect. No-op in dev mode. */
  signIn(): Promise<void>;
  /** Sign out redirect. No-op in dev mode. */
  signOut(): Promise<void>;
  /** Keep an authenticated browser session warm for this App lifecycle. */
  startSessionKeeper?(): () => void;
}

class DevModeAuth implements AuthContext {
  readonly devMode = true;
  readonly interactiveSignIn = false;
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

interface LocalCliProfile {
  readonly oid: string;
  readonly username: string;
  readonly name: string | null;
  readonly roles: readonly string[];
  readonly source: "azure-cli";
}

class LocalAzureCliAuth implements AuthContext {
  readonly devMode = true;
  readonly localAzureCli = true;
  readonly interactiveSignIn = false;
  readonly account: AuthAccount;
  #sessionToken: string;

  constructor(profile: LocalCliProfile, sessionToken: string) {
    this.#sessionToken = sessionToken;
    this.account = {
      homeAccountId: profile.oid,
      localAccountId: profile.oid,
      username: profile.username,
      ...(profile.name ? { name: profile.name } : {}),
      idTokenClaims: { roles: [...profile.roles] },
    };
  }

  async getAuthorizationHeader(): Promise<string | null> {
    return "Bearer " + this.#sessionToken;
  }
  async signIn(): Promise<void> {
    /* no-op */
  }
  async signOut(): Promise<void> {
    /* no-op */
  }
}

class MsalAuth implements AuthContext {
  readonly interactiveSignIn = true;
  readonly devMode: boolean;
  #client: PublicClientApplication;
  #scope: string;
  #interactionRequiredAuthError: InteractionRequiredAuthErrorConstructor;
  #account: AccountInfo | null = null;
  #authorizationRequest: Promise<string | null> | null = null;
  #interactiveRequestPending = false;

  constructor(
    client: PublicClientApplication,
    scope: string,
    interactionRequiredAuthError: InteractionRequiredAuthErrorConstructor,
    options: { readonly devMode?: boolean } = {},
  ) {
    this.#client = client;
    this.#scope = scope;
    this.#interactionRequiredAuthError = interactionRequiredAuthError;
    this.devMode = options.devMode ?? false;
  }

  get account(): AuthAccount | null {
    return this.#account;
  }

  async initialize(): Promise<void> {
    // Consume any redirect response first - MSAL requires this before
    // any silent-acquire call.
    const redirectResult = await this.#client.handleRedirectPromise();
    const accounts = this.#client.getAllAccounts();
    this.#account = redirectResult?.account ?? (accounts.length > 0 ? (accounts[0] ?? null) : null);
  }

  async getAuthorizationHeader(): Promise<string | null> {
    const account = this.#account;
    if (!account) return null;
    if (this.#authorizationRequest === null) {
      this.#authorizationRequest = this.#acquireAuthorizationHeader(account).finally(() => {
        this.#authorizationRequest = null;
      });
    }
    return this.#authorizationRequest;
  }

  startSessionKeeper(): () => void {
    if (!this.#account) return () => {};
    return installAuthSessionKeeper(async (trigger) => {
      const authorization = await this.getAuthorizationHeader();
      console.info("auth_session_refresh", {
        status: authorization === null ? "unavailable" : "succeeded",
        trigger,
      });
    });
  }

  async #acquireAuthorizationHeader(account: AccountInfo): Promise<string | null> {
    try {
      const result = await this.#client.acquireTokenSilent({
        account,
        scopes: [this.#scope],
      });
      return `Bearer ${result.accessToken}`;
    } catch (err) {
      if (err instanceof this.#interactionRequiredAuthError) {
        await this.signIn();
      } else {
        console.warn("auth_session_refresh_failed", {
          error_code: authErrorCode(err),
        });
      }
      return null;
    }
  }

  async signIn(): Promise<void> {
    if (this.#interactiveRequestPending) return;
    this.#interactiveRequestPending = true;
    try {
      await this.#client.loginRedirect({
        scopes: [this.#scope],
        ...(this.#account?.username ? { loginHint: this.#account.username } : {}),
      });
    } finally {
      this.#interactiveRequestPending = false;
    }
  }

  async signOut(): Promise<void> {
    if (this.#account) {
      await this.#client.logoutRedirect({ account: this.#account });
    }
  }
}

export async function initAuth(config: ConsoleConfig): Promise<AuthContext> {
  if (config.devMode && config.localAzureCliAuth) {
    throw new Error("VITE_DEV_MODE and VITE_LOCAL_AZURE_CLI_AUTH MUST NOT both be enabled.");
  }
  if (config.localAzureCliAuth) {
    const response = await fetch(`${config.operatorApiBaseUrl.replace(/\/$/, "")}/local-auth/me`, {
      headers: { accept: "application/json" },
      cache: "no-store",
    });
    if (!response.ok) {
      throw new Error(
        `Local Azure CLI auth failed (${response.status}). Run 'az login' and start the Operator API with FDAI_OPERATOR_API_LOCAL_AZURE_CLI=1.`
      );
    }
    const sessionToken = response.headers.get("x-fdai-local-session");
    if (!sessionToken) {
      throw new Error("Local Azure CLI auth returned no local session token.");
    }
    return new LocalAzureCliAuth(parseLocalCliProfile(await response.json()), sessionToken);
  }
  if (config.devMode) {
    if (
      config.localLoginPrompt &&
      config.msalClientId &&
      config.msalTenantId &&
      config.msalApiScope
    ) {
      return initializeMsal(config, true);
    }
    return new DevModeAuth();
  }
  if (!config.msalClientId || !config.msalTenantId || !config.msalApiScope) {
    // Fail loud in prod builds - the fork MUST set these envs before
    // shipping. The console refuses to load with a clear message rather
    // than silently rendering unauthenticated calls.
    throw new Error(
      "MSAL config missing: VITE_MSAL_CLIENT_ID / VITE_MSAL_TENANT_ID / " +
        "VITE_MSAL_API_SCOPE MUST all be set for a non-dev build."
    );
  }
  return initializeMsal(config, false);
}

async function initializeMsal(config: ConsoleConfig, devMode: boolean): Promise<AuthContext> {
  const { InteractionRequiredAuthError, PublicClientApplication } = await import(
    "@azure/msal-browser"
  );
  const msalConfig: Configuration = {
    auth: {
      clientId: config.msalClientId,
      authority: `https://login.microsoftonline.com/${config.msalTenantId}`,
      redirectUri: window.location.origin,
      postLogoutRedirectUri: window.location.origin,
    },
    cache: {
      cacheLocation: msalCacheLocationForOrigin(window.location.origin),
    },
  };
  const client = new PublicClientApplication(msalConfig);
  await client.initialize();
  const auth = new MsalAuth(client, config.msalApiScope, InteractionRequiredAuthError, { devMode });
  await auth.initialize();
  return auth;
}

function authErrorCode(value: unknown): string {
  if (typeof value !== "object" || value === null) return "unknown";
  const errorCode = (value as { readonly errorCode?: unknown }).errorCode;
  return typeof errorCode === "string" && errorCode ? errorCode : "unknown";
}

function parseLocalCliProfile(value: unknown): LocalCliProfile {
  if (typeof value !== "object" || value === null) {
    throw new Error("Local Azure CLI auth returned an invalid profile.");
  }
  const record = value as Record<string, unknown>;
  if (
    typeof record.oid !== "string" ||
    !record.oid ||
    typeof record.username !== "string" ||
    !record.username ||
    record.source !== "azure-cli" ||
    !Array.isArray(record.roles) ||
    !record.roles.every((role) => typeof role === "string") ||
    !(record.name === null || typeof record.name === "string")
  ) {
    throw new Error("Local Azure CLI auth returned an invalid profile.");
  }
  return {
    oid: record.oid,
    username: record.username,
    name: record.name,
    roles: record.roles,
    source: "azure-cli",
  };
}
