import { PublicClientApplication } from "@azure/msal-browser";
import "./auth.css";

let authorization: (() => Promise<string>) | undefined;

/** Access tokens stay in MSAL's session cache, never URLs, local configuration, or UI output. */
export async function initializeAuth(root: HTMLElement): Promise<boolean> {
  const response = await fetch("/auth/config", { cache: "no-store" });
  if (!response.ok) throw new Error("Authentication configuration unavailable.");
  const config: unknown = await response.json();
  if (typeof config !== "object" || config === null || !("profile" in config)) {
    throw new Error("Invalid authentication configuration.");
  }
  if (config.profile === "local-development") return true;
  if (config.profile === "remote-unconfigured") {
    if (!("origin" in config) || config.origin !== window.location.origin ||
        !("product" in config) || !["release", "lifecycle"].includes(String(config.product))) {
      throw new Error("Invalid standalone Hub configuration.");
    }
    authorization = undefined;
    root.replaceChildren();
    root.classList.add("auth-shell");
    const title = document.createElement("h1");
    title.textContent = config.product === "release" ? "FDAI Release Hub" : "FDAI Lifecycle Hub";
    const note = document.createElement("p");
    note.textContent = "Operator sign-in is not configured. Management APIs are unavailable. " +
      "This page reports runtime status only; management functionality is not ready.";
    const status = document.createElement("p");
    status.setAttribute("role", "status");
    status.textContent = "Checking this Hub's runtime...";
    root.append(title, note, status);
    const [health, ready] = await Promise.all([
      fetch("/healthz", { cache: "no-store" }),
      fetch("/readyz", { cache: "no-store" }),
    ]);
    const healthBody: unknown = health.ok ? await health.json() : null;
    const readyBody: unknown = ready.ok ? await ready.json() : null;
    const alive = typeof healthBody === "object" && healthBody !== null &&
      "status" in healthBody && ["ok", "healthy"].includes(String(healthBody.status));
    const available = typeof readyBody === "object" && readyBody !== null &&
      "status" in readyBody && readyBody.status === "ready";
    status.textContent = `${alive ? "API process responding" : "API health unavailable"}. ` +
      `${available ? "Database schema ready" : "Database readiness unavailable"}. ` +
      "Anonymous management API access is not enabled.";
    return false;
  }
  if (config.profile !== "remote-development" ||
      !("clientId" in config) || typeof config.clientId !== "string" ||
      !("authority" in config) || typeof config.authority !== "string" ||
      !("scope" in config) || typeof config.scope !== "string" ||
      !("origin" in config) || config.origin !== window.location.origin) {
    throw new Error("Invalid remote authentication configuration.");
  }
  const client = new PublicClientApplication({
    auth: { clientId: config.clientId, authority: config.authority, redirectUri: config.origin },
    cache: { cacheLocation: "sessionStorage" },
  });
  await client.initialize();
  const result = await client.handleRedirectPromise();
  const accounts = client.getAllAccounts();
  const account = result?.account ?? (accounts.length === 1 ? accounts[0] : undefined);
  const scopes = [config.scope];
  if (!account) {
    root.replaceChildren();
    root.classList.add("auth-shell");
    const title = document.createElement("h1");
    title.textContent = "FDAI Hub development validation";
    const note = document.createElement("p");
    note.textContent = "Sign in with the approved operator account. This is not a production trust root.";
    const button = document.createElement("button");
    button.textContent = "Sign in with Microsoft Entra ID";
    button.onclick = () => {
      void client.loginRedirect({ scopes, prompt: "select_account" }).catch(() => {
        note.textContent = "Sign-in failed. Review the Entra registration and try again.";
      });
    };
    root.append(title, note, button);
    return false;
  }
  client.setActiveAccount(account);
  authorization = async () => {
    const token = await client.acquireTokenSilent({ account, scopes });
    return `Bearer ${token.accessToken}`;
  };
  return true;
}

export async function authenticatedFetch(path: string, init?: RequestInit): Promise<Response> {
  const headers = new Headers(init?.headers);
  if (authorization) headers.set("Authorization", await authorization());
  return fetch(path, { ...init, headers });
}

export function showAuthFailure(root: HTMLElement): void {
  root.textContent = "Authentication is unavailable. Review the Hub configuration and sign in again.";
  root.setAttribute("role", "alert");
}
