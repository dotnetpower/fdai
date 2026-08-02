import type { AuthContext } from "./auth";
import type { ConsoleConfig } from "./config";
import type { ApiError } from "./types";

export class OperatorApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "OperatorApiError";
    this.status = status;
  }
}

export function isOptionalOperatorApiUnavailable(error: unknown): error is OperatorApiError {
  return error instanceof OperatorApiError
    && (error.status === 404 || error.status === 501 || error.status === 503);
}

export interface OperatorApiTransportOptions {
  readonly onUnauthorized?: (error: OperatorApiError) => void;
}

export class OperatorApiTransport {
  readonly #config: ConsoleConfig;
  readonly #auth: AuthContext;
  readonly #onUnauthorized: ((error: OperatorApiError) => void) | undefined;

  constructor(
    config: ConsoleConfig,
    auth: AuthContext,
    options: OperatorApiTransportOptions = {},
  ) {
    this.#config = config;
    this.#auth = auth;
    this.#onUnauthorized = options.onUnauthorized;
  }

  get baseUrl(): string {
    return this.#config.operatorApiBaseUrl;
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
        () => new OperatorApiError(
          401,
          "Authentication token request timed out. Retry or sign in again.",
        ),
      );
    } catch (error) {
      if (error instanceof OperatorApiError && error.status === 401) {
        this.#onUnauthorized?.(error);
      }
      throw error;
    }
    if (
      authHeader === null
      && this.#auth.account !== null
      && this.#auth.localAzureCli !== true
    ) {
      const error = new OperatorApiError(
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
      throw new OperatorApiError(
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
    const url = new URL(path, this.#config.operatorApiBaseUrl);
    if (params && params.toString().length > 0) {
      url.search = params.toString();
    }
    const headers: Record<string, string> = { accept };
    const authHeader = await this.#authorizationHeader();
    if (authHeader !== null) headers["authorization"] = authHeader;
    const controller = new AbortController();
    const timeout = globalThis.setTimeout(
      () => controller.abort(),
      this.#config.operatorApiRequestTimeoutMs,
    );
    let response: Response;
    try {
      response = await fetch(url.toString(), {
        method: "GET",
        headers,
        credentials: "omit",
        signal: controller.signal,
      });
    } catch (error) {
      if (controller.signal.aborted) {
        throw new OperatorApiError(504, "Operator API request timed out. Retry the request.");
      }
      throw error;
    } finally {
      globalThis.clearTimeout(timeout);
    }
    if (!response.ok) {
      let message = `HTTP ${response.status}`;
      try {
        const body = (await response.json()) as ApiError;
        message = body.error?.message ?? message;
      } catch {
        /* body was not JSON - fall through */
      }
      const error = new OperatorApiError(response.status, message);
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
