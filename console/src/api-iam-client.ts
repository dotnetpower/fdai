import type { OperatorApiTransport } from "./api-transport";
import type {
  HumanIdentityResult,
  IamAccessRequestPage,
  IamOverview,
  IamSelfStatus,
  IdentityRosterItem,
} from "./routes/settings-iam.model";
import type { AssignmentProjectionPage } from "./routes/settings-iam-assignments.model";
import type {
  ReportLineContactRequest,
  ReportingLineCase,
  ReportingLineProjection,
} from "./routes/report-lines.model";

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

  async reportingLines(limit = 100, cursor = 0): Promise<ReportingLineProjection> {
    const { decodeReportingLineProjection } = await import("./routes/report-lines.model");
    const params = new URLSearchParams({ limit: String(limit) });
    if (cursor > 0) params.set("cursor", String(cursor));
    return decodeReportingLineProjection(
      await this.#transport.getJson<unknown>("/handover/reporting-lines", params),
    );
  }

  async createReportingLineCase(
    body: Record<string, unknown>,
    idempotencyKey: string,
  ): Promise<ReportingLineCase> {
    const { decodeReportingLineCase } = await import("./routes/report-lines.model");
    return decodeReportingLineCase(
      await this.#transport.postJson<unknown>(
        "/handover/reporting-line-cases",
        body,
        idempotencyKey,
      ),
    );
  }

  async decideReportingLineCase(
    operatorCaseId: string,
    operation: "confirm" | "review",
    body: Record<string, unknown>,
    idempotencyKey: string,
  ): Promise<ReportingLineCase> {
    const { decodeReportingLineCase } = await import("./routes/report-lines.model");
    return decodeReportingLineCase(
      await this.#transport.postJson<unknown>(
        `/handover/reporting-line-cases/${encodeURIComponent(operatorCaseId)}/${operation}`,
        body,
        idempotencyKey,
      ),
    );
  }

  async reportLineContactRequests(): Promise<readonly ReportLineContactRequest[]> {
    const { decodeReportLineContactRequests } = await import("./routes/report-lines.model");
    return decodeReportLineContactRequests(
      await this.#transport.getJson<unknown>("/hil/report-line-contact-requests"),
    );
  }

  async decideReportLineContact(
    approvalId: string,
    consent: boolean,
    expectedRevision: number,
    idempotencyKey: string,
  ): Promise<unknown> {
    return this.#transport.postJson<unknown>(
      `/hil/${encodeURIComponent(approvalId)}/report-line-contact`,
      { consent, expected_revision: expectedRevision },
      idempotencyKey,
    );
  }
}
