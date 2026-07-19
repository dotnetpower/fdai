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
  return error instanceof ReadApiError && (error.status === 404 || error.status === 501);
}

export class ReadApiTransport {
  readonly #config: ConsoleConfig;
  readonly #auth: AuthContext;

  constructor(config: ConsoleConfig, auth: AuthContext) {
    this.#config = config;
    this.#auth = auth;
  }

  get baseUrl(): string {
    return this.#config.readApiBaseUrl;
  }

  readonly authorizationHeader = async (): Promise<string | null> => {
    return this.#authorizationHeader();
  };

  async #authorizationHeader(): Promise<string | null> {
    const authHeader = await this.#auth.getAuthorizationHeader();
    if (
      authHeader === null
      && this.#auth.account !== null
      && this.#auth.localAzureCli !== true
    ) {
      throw new ReadApiError(401, "Authentication token unavailable for signed-in account.");
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
      throw new ReadApiError(response.status, message);
    }
    return response;
  }
}
