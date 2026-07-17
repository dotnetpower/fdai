import type { ReadApiTransport } from "./api-transport";
import {
  decodeIamAccessRequestPage,
  decodeIamOverview,
  decodeIamSelfStatus,
  decodeHumanIdentityResults,
  decodeIdentityRoster,
  type HumanIdentityResult,
  type IamAccessRequestPage,
  type IamOverview,
  type IamSelfStatus,
  type IdentityRosterItem,
} from "./routes/settings-iam.model";

export class IamApiClient {
  readonly #transport: ReadApiTransport;

  constructor(transport: ReadApiTransport) {
    this.#transport = transport;
  }

  async overview(): Promise<IamOverview> {
    return decodeIamOverview(await this.#transport.getJson<unknown>("/iam"));
  }

  async self(): Promise<IamSelfStatus> {
    return decodeIamSelfStatus(await this.#transport.getJson<unknown>("/iam/self"));
  }

  async searchUsers(query: string, limit = 20): Promise<readonly HumanIdentityResult[]> {
    const params = new URLSearchParams({ q: query, limit: String(limit) });
    return decodeHumanIdentityResults(
      await this.#transport.getJson<unknown>("/iam/directory/users", params),
    );
  }

  async roster(): Promise<readonly IdentityRosterItem[]> {
    return decodeIdentityRoster(
      await this.#transport.getJson<unknown>("/iam/directory/roster"),
    );
  }

  async listAccessRequests(limit = 50, cursor = 0): Promise<IamAccessRequestPage> {
    const params = new URLSearchParams({ limit: String(limit) });
    if (cursor > 0) params.set("cursor", String(cursor));
    return decodeIamAccessRequestPage(
      await this.#transport.getJson<unknown>("/iam/access-requests", params),
    );
  }
}
