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
