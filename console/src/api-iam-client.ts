import type { OperatorApiTransport } from "./api-transport";
import type {
  HumanIdentityResult,
  IamAccessRequestPage,
  IamOverview,
  IamSelfStatus,
  IdentityRosterItem,
} from "./routes/settings-iam.model";
import type { AssignmentProjectionPage } from "./routes/settings-iam-assignments.model";

export class IamApiClient {
  readonly #transport: OperatorApiTransport;

  constructor(transport: OperatorApiTransport) {
    this.#transport = transport;
  }

  async overview(): Promise<IamOverview> {
    const { decodeIamOverview } = await import("./routes/settings-iam.model");
    return decodeIamOverview(await this.#transport.getJson<unknown>("/iam"));
  }

  async self(): Promise<IamSelfStatus> {
    const { decodeIamSelfStatus } = await import("./routes/settings-iam.model");
    return decodeIamSelfStatus(await this.#transport.getJson<unknown>("/iam/self"));
  }

  async searchUsers(query: string, limit = 20): Promise<readonly HumanIdentityResult[]> {
    const { decodeHumanIdentityResults } = await import("./routes/settings-iam.model");
    const params = new URLSearchParams({ q: query, limit: String(limit) });
    return decodeHumanIdentityResults(
      await this.#transport.getJson<unknown>("/iam/directory/users", params),
    );
  }

  async roster(): Promise<readonly IdentityRosterItem[]> {
    const { decodeIdentityRoster } = await import("./routes/settings-iam.model");
    return decodeIdentityRoster(
      await this.#transport.getJson<unknown>("/iam/directory/roster"),
    );
  }

  async listAccessRequests(limit = 50, cursor = 0): Promise<IamAccessRequestPage> {
    const { decodeIamAccessRequestPage } = await import("./routes/settings-iam.model");
    const params = new URLSearchParams({ limit: String(limit) });
    if (cursor > 0) params.set("cursor", String(cursor));
    return decodeIamAccessRequestPage(
      await this.#transport.getJson<unknown>("/iam/access-requests", params),
    );
  }

  async assignments(limit = 100, cursor = 0): Promise<AssignmentProjectionPage> {
    const { decodeAssignmentProjectionPage } = await import(
      "./routes/settings-iam-assignments.model"
    );
    const params = new URLSearchParams({ limit: String(limit) });
    if (cursor > 0) params.set("cursor", String(cursor));
    return decodeAssignmentProjectionPage(
      await this.#transport.getJson<unknown>("/iam/assignments", params),
    );
  }
}
