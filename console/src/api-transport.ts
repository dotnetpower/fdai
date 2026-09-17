import type { AuthContext } from "./auth";
import type { ConsoleConfig } from "./config";
import type { ApiError } from "./types";

export class OperatorApiError extends Error {
  readonly status: number;
  readonly kind: "http" | "projection-unavailable";
  readonly reason: string | undefined;

  constructor(
    status: number,
    message: string,
    kind: "http" | "projection-unavailable" = "http",
    reason?: string,
  ) {
    super(message);
    this.name = "OperatorApiError";
    this.status = status;
    this.kind = kind;
    this.reason = reason;
  }
}

export function isOptionalOperatorApiUnavailable(error: unknown): error is OperatorApiError {
  return error instanceof OperatorApiError
    && (
      error.status === 404
      || error.status === 501
      || error.kind === "projection-unavailable"
    );
}

const PROJECTION_UNAVAILABLE_MESSAGE = "authoritative Operator projection is unavailable";

function responseError(status: number, message: string, reason?: unknown): OperatorApiError {
  return new OperatorApiError(
    status,
    message,
    status === 503 && message === PROJECTION_UNAVAILABLE_MESSAGE
      ? "projection-unavailable"
      : "http",
    reason === undefined ? undefined
      : typeof reason === "string" && /^[a-z_]{1,64}$/.test(reason)
        ? reason : "invalid_recovery_reason",
  );
}

export interface OperatorApiTransportOptions {
  readonly onUnauthorized?: (error: OperatorApiError) => void;
  readonly sampleResponse?: (
    path: string,
    params: URLSearchParams,
  ) => unknown | undefined;
}

export class OperatorApiTransport {
  readonly #config: ConsoleConfig;
  readonly #auth: AuthContext;
  readonly #onUnauthorized: ((error: OperatorApiError) => void) | undefined;
  readonly #sampleResponse: OperatorApiTransportOptions["sampleResponse"];

  constructor(
    config: ConsoleConfig,
    auth: AuthContext,
    options: OperatorApiTransportOptions = {},
  ) {
    this.#config = config;
    this.#auth = auth;
    this.#onUnauthorized = options.onUnauthorized;
    this.#sampleResponse = options.sampleResponse;
  }

  get baseUrl(): string {
    return this.#config.operatorApiBaseUrl;
  }

  readonly authorizationHeader = (): Promise<string | null> =>
    this.#authorizationHeader();

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

  async postJson<T>(
    path: string,
    body: Record<string, unknown>,
    idempotencyKey: string,
  ): Promise<T> {
    if (this.#sampleResponse !== undefined) {
      throw new OperatorApiError(405, "Sample mode does not permit Operator API mutations.");
    }
    if (!idempotencyKey.trim()) {
      throw new OperatorApiError(400, "Idempotency key is required.");
    }
    const url = new URL(path, this.#config.operatorApiBaseUrl);
    const headers: Record<string, string> = {
      accept: "application/json",
      "content-type": "application/json",
      "idempotency-key": idempotencyKey,
    };
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
        method: "POST",
        headers,
        body: JSON.stringify(body),
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
        const payload = (await response.json()) as ApiError;
        message = payload.error?.message ?? message;
      } catch {
        /* body was not JSON */
      }
      throw responseError(response.status, message);
    }
    try {
      return (await response.json()) as T;
    } catch {
      throw new OperatorApiError(response.status, "response body was not JSON");
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
    if (this.#sampleResponse !== undefined) {
      const value = this.#sampleResponse(url.pathname, url.searchParams);
      if (value === undefined) {
        throw new OperatorApiError(404, `No Sample response is registered for ${url.pathname}.`);
      }
      return new Response(JSON.stringify(value), {
        status: 200,
        headers: { "content-type": "application/json" },
      });
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
      let reason: unknown;
      try {
        const body = (await response.json()) as ApiError;
        message = body.error?.message ?? message;
        reason = body.error?.reason;
      } catch {
        /* body was not JSON - fall through */
      }
      const error = responseError(response.status, message, reason);
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
