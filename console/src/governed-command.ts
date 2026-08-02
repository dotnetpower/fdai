import type { AuthContext } from "./auth";

export class GovernedCommandError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "GovernedCommandError";
  }
}

export async function putGovernedJson(
  auth: AuthContext,
  operatorApiBaseUrl: string,
  path: string,
  body: Record<string, unknown>,
  method: "POST" | "PUT" = "PUT",
): Promise<unknown> {
  const authorization = await auth.getAuthorizationHeader();
  const headers: Record<string, string> = {
    accept: "application/json",
    "content-type": "application/json",
  };
  if (authorization !== null) headers.authorization = authorization;
  const controller = new AbortController();
  const timer = globalThis.setTimeout(() => controller.abort(), 10_000);
  let response: Response;
  try {
    response = await fetch(new URL(path, operatorApiBaseUrl), {
      method,
      headers,
      credentials: "omit",
      signal: controller.signal,
      body: JSON.stringify(body),
    });
  } catch (reason) {
    if (reason instanceof DOMException && reason.name === "AbortError") {
      throw new GovernedCommandError("Request timed out", 0);
    }
    throw reason;
  } finally {
    globalThis.clearTimeout(timer);
  }
  if (!response.ok) {
    throw new GovernedCommandError(await errorMessage(response), response.status);
  }
  try {
    return await response.json();
  } catch {
    throw new GovernedCommandError("Response body was not JSON", response.status);
  }
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const payload = await response.json() as {
      readonly detail?: unknown;
      readonly error?: { readonly message?: unknown };
    };
    if (typeof payload.detail === "string") return payload.detail;
    if (typeof payload.error?.message === "string") return payload.error.message;
  } catch {
    // Keep the bounded status fallback.
  }
  return `HTTP ${response.status}`;
}
