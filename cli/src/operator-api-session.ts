/**
 * Resolve the optional loopback-only Operator API session used by the CLI.
 *
 * The server owns Azure CLI identity resolution and returns an opaque session
 * token. The token stays in memory and is never included in diagnostics.
 */

export type OperatorApiAuthMode = "local-azure-cli" | "none";

export interface OperatorApiSession {
  authMode: OperatorApiAuthMode;
  authorization?: string;
  roles: readonly string[];
}

const MAX_SESSION_TOKEN_LENGTH = 4096;
const MAX_PROFILE_CHARS = 16 * 1024;
const MAX_ROLE_COUNT = 16;
const MAX_ROLE_LENGTH = 128;

const normalizedBaseUrl = (baseUrl: string): string => baseUrl.replace(/\/$/, "");

function isLoopbackUrl(baseUrl: string): boolean {
  const hostname = new URL(baseUrl).hostname.toLowerCase();
  return hostname === "127.0.0.1" || hostname === "localhost" || hostname === "[::1]";
}

function parseProfile(payload: unknown): readonly string[] {
  if (
    typeof payload !== "object" ||
    payload === null ||
    (payload as { source?: unknown }).source !== "azure-cli" ||
    !("roles" in payload)
  ) {
    throw new Error("Operator API returned an invalid local authentication profile");
  }
  const roles = (payload as { roles?: unknown }).roles;
  if (!Array.isArray(roles) || roles.length > MAX_ROLE_COUNT) {
    throw new Error("Operator API returned an invalid local authentication profile");
  }
  if (
    !roles.every(
      (role) =>
        typeof role === "string" &&
        role.length > 0 &&
        role.length <= MAX_ROLE_LENGTH &&
        !/[\u0000-\u001f\u007f]/.test(role),
    )
  ) {
    throw new Error("Operator API returned an invalid local authentication profile");
  }
  return [...roles];
}

function parseSessionToken(value: string | null): string {
  const token = value?.trim() ?? "";
  if (
    token.length === 0 ||
    token.length > MAX_SESSION_TOKEN_LENGTH ||
    /[\u0000-\u0020\u007f]/.test(token)
  ) {
    throw new Error("Operator API returned an invalid local session token");
  }
  return token;
}

/**
 * Bootstrap local Azure CLI authentication when the loopback API exposes it.
 * Remote APIs and local APIs without the endpoint continue without a token.
 */
export async function createOperatorApiSession(baseUrl: string): Promise<OperatorApiSession> {
  if (!isLoopbackUrl(baseUrl)) return Object.freeze({ authMode: "none", roles: [] });

  const url = `${normalizedBaseUrl(baseUrl)}/local-auth/me`;
  const response = await fetch(url, {
    headers: { accept: "application/json" },
    redirect: "error",
  });
  if (response.status === 404) {
    return Object.freeze({ authMode: "none", roles: [] });
  }
  if (!response.ok) {
    throw new Error(`Operator API local authentication bootstrap failed (${response.status})`);
  }

  const rawProfile = await boundedProfileText(response);
  let payload: unknown;
  try {
    payload = JSON.parse(rawProfile) as unknown;
  } catch {
    throw new Error("Operator API returned an invalid local authentication profile");
  }
  const token = parseSessionToken(response.headers.get("x-fdai-local-session"));
  const session: OperatorApiSession = {
    authMode: "local-azure-cli",
    roles: Object.freeze([...parseProfile(payload)]),
  };
  Object.defineProperty(session, "authorization", {
    value: `Bearer ${token}`,
    enumerable: false,
    writable: false,
    configurable: false,
  });
  return Object.freeze(session);
}

async function boundedProfileText(response: Response): Promise<string> {
  const declared = response.headers.get("content-length");
  if (declared !== null && /^\d+$/.test(declared) && Number(declared) > MAX_PROFILE_CHARS) {
    throw new Error("Operator API returned an oversized local authentication profile");
  }
  if (!response.body) return "";
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let bytes = 0;
  let raw = "";
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      bytes += value.byteLength;
      if (bytes > MAX_PROFILE_CHARS) {
        await reader
          .cancel("local authentication profile exceeds the size limit")
          .catch(() => {});
        throw new Error("Operator API returned an oversized local authentication profile");
      }
      raw += decoder.decode(value, { stream: true });
    }
    return raw + decoder.decode();
  } finally {
    reader.releaseLock();
  }
}
