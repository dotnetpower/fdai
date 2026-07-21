import type { AuthContext } from "./auth";
import type { ConsoleConfig } from "./config";
import type { ApiError } from "./types";

export class ReadApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ReadApiError";
    this.status = status;
  }
}

export function isOptionalReadApiUnavailable(error: unknown): error is ReadApiError {
  return error instanceof ReadApiError
    && (error.status === 404 || error.status === 501 || error.status === 503);
}

export interface ReadApiTransportOptions {
  readonly onUnauthorized?: (error: ReadApiError) => void;
}

export class ReadApiTransport {
  readonly #config: ConsoleConfig;
  readonly #auth: AuthContext;
  readonly #onUnauthorized: ((error: ReadApiError) => void) | undefined;

  constructor(
    config: ConsoleConfig,
    auth: AuthContext,
    options: ReadApiTransportOptions = {},
  ) {
    this.#config = config;
    this.#auth = auth;
    this.#onUnauthorized = options.onUnauthorized;
  }

  get baseUrl(): string {
    return this.#config.readApiBaseUrl;
  }

  readonly authorizationHeader = async (): Promise<string | null> => {
    return this.#authorizationHeader();
  };

  async #authorizationHeader(): Promise<string | null> {
    let authHeader: string | null;
    try {
      authHeader = await withTimeout(
        this.#auth.getAuthorizationHeader(),
        this.#config.authTokenTimeoutMs,
        () => new ReadApiError(
          401,
          "Authentication token request timed out. Retry or sign in again.",
        ),
      );
    } catch (error) {
      if (error instanceof ReadApiError && error.status === 401) {
        this.#onUnauthorized?.(error);
      }
      throw error;
    }
    if (
      authHeader === null
      && this.#auth.account !== null
      && this.#auth.localAzureCli !== true
    ) {
      const error = new ReadApiError(
        401,
        "Authentication token unavailable for signed-in account.",
      );
      this.#onUnauthorized?.(error);
      throw error;
    }
    return authHeader;
  }

  async getJson<T>(path: string, params?: URLSearchParams): Promise<T> {
    const response = await this.getResponse(path, params, "application/json");
    try {
      return (await response.json()) as T;
    } catch {
      throw new ReadApiError(
        response.status,
        `response body was not JSON (${response.headers.get("content-type") ?? "no content-type"})`,
      );
    }
  }

  async getResponse(
    path: string,
    params: URLSearchParams | undefined,
    accept: string,
  ): Promise<Response> {
    const url = new URL(path, this.#config.readApiBaseUrl);
    if (params && params.toString().length > 0) {
      url.search = params.toString();
    }
    const headers: Record<string, string> = { accept };
    const authHeader = await this.#authorizationHeader();
    if (authHeader !== null) headers["authorization"] = authHeader;
    const response = await fetch(url.toString(), {
      method: "GET",
      headers,
      credentials: "omit",
    });
    if (!response.ok) {
      let message = `HTTP ${response.status}`;
      try {
        const body = (await response.json()) as ApiError;
        message = body.error?.message ?? message;
      } catch {
        /* body was not JSON - fall through */
      }
      const error = new ReadApiError(response.status, message);
      throw error;
    }
    return response;
  }
}

async function withTimeout<T>(
  operation: Promise<T>,
  timeoutMs: number,
  timeoutError: () => Error,
): Promise<T> {
  let timer: ReturnType<typeof globalThis.setTimeout> | undefined;
  const timeout = new Promise<never>((_resolve, reject) => {
    timer = globalThis.setTimeout(() => reject(timeoutError()), timeoutMs);
  });
  try {
    return await Promise.race([operation, timeout]);
  } finally {
    if (timer !== undefined) globalThis.clearTimeout(timer);
  }
}
