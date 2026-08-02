/**
 * Operator API client. The console makes exactly three kinds of GET call
 * against the API defined in `src/fdai/delivery/operator_api/main.py`.
 * All routes are read-only; there are NO helpers here for POST / PUT /
 * DELETE / PATCH - the read-only invariant is enforced by not writing
 * such helpers in the first place (see app-shape.instructions.md).
 */

import type { AuthContext } from "./auth";
import {
  type AssignmentProjectionPage,
} from "./routes/settings-iam-assignments.model";
import {
  decodeReadDataSources,
  type ReadDataSourcesPayload,
  unavailableSourceReason,
} from "./api-data-sources";
import type { ConsoleConfig } from "./config";
import {
  isOptionalOperatorApiUnavailable,
  OperatorApiError,
  OperatorApiTransport,
  type OperatorApiTransportOptions,
} from "./api-transport";
import { IamApiClient } from "./api-iam-client";
import { InsightsApiClient } from "./api-insights-client";
import {
  OperationsApiClient,
  type AuditQuery,
  type IncidentQuery,
} from "./api-operations-client";
import { ReportingApiClient } from "./api-reporting-client";
import type {
  AuditPage,
  AutonomyPayload,
  DashboardKpi,
  EffectiveScope,
  FinOpsPayload,
  HilQueuePage,
  IncidentPage,
  RcaView,
} from "./types";
import {
  type RenderedReportView,
  type ReportingRegistry,
  type ReportList,
} from "./routes/reporting.model";
import {
  type HumanIdentityResult,
  type IamAccessRequestPage,
  type IamOverview,
  type IamSelfStatus,
  type IdentityRosterItem,
} from "./routes/settings-iam.model";

export class OperatorApiClient {
  readonly #transport: OperatorApiTransport;
  readonly #operations: OperationsApiClient;
  readonly #insights: InsightsApiClient;
  readonly #iam: IamApiClient;
  readonly #reporting: ReportingApiClient;
  #dataSourcesPromise: Promise<ReadDataSourcesPayload> | null = null;

  constructor(
    config: ConsoleConfig,
    auth: AuthContext,
    options: OperatorApiTransportOptions = {},
  ) {
    this.#transport = new OperatorApiTransport(config, auth, options);
    this.#operations = new OperationsApiClient(this.#transport);
    this.#insights = new InsightsApiClient(this.#transport);
    this.#iam = new IamApiClient(this.#transport);
    this.#reporting = new ReportingApiClient(this.#transport);
  }

  get operatorApiBaseUrl(): string {
    return this.#transport.baseUrl;
  }

  readonly authorizationHeader = async (): Promise<string | null> => {
    return this.#transport.authorizationHeader();
  };

  async listAudit(options: AuditQuery = {}): Promise<AuditPage> {
    await this.#requireAuthoritativeSource("/audit");
    return this.#operations.listAudit(options);
  }

  async listIncidents(options: IncidentQuery = {}): Promise<IncidentPage> {
    await this.#requireAuthoritativeSource("/incidents");
    return this.#operations.listIncidents(options);
  }

  /**
   * Fetch the RCA (root-cause analysis) view for one incident
   * (`GET /rca?correlation=...`). Read-only projection of the shadow
   * `rca.hypothesis` audit entries: tiered hypotheses, grounded
   * citations, and the linked response plan. An RCA hypothesis answers
   * "why", never "execute".
   */
  async rca(correlationId: string): Promise<RcaView> {
    await this.#requireAuthoritativeSource("/rca");
    return this.#operations.rca(correlationId);
  }

  /**
   * Fetch the effective monitoring / automated-action scope
   * (`GET /scope`). Opt-in like {@link finops}; callers MUST tolerate a
   * 404 as "scope view not served here". Read-only: authoring a scope
   * change is a policy-as-code PR, never a console write.
   */
  async scope(): Promise<EffectiveScope> {
    await this.#requireAuthoritativeSource("/scope");
    return this.#insights.scope();
  }

  async dashboardMetrics(): Promise<DashboardKpi> {
    await this.#requireAuthoritativeSource("/kpi");
    return this.#insights.dashboardMetrics();
  }

  /**
   * Fetch the FinOps cost summary (`GET /finops`). This is a fork opt-in
   * panel; callers MUST tolerate a 404 (`OperatorApiError` status 404) as
   * "cost axis not served here" rather than a hard failure.
   */
  async finops(): Promise<FinOpsPayload> {
    await this.#requireAuthoritativeSource("/finops");
    return this.#insights.finops();
  }

  /**
   * Fetch the autonomy measurement summary (`GET /kpi/autonomy`). Opt-in
   * like {@link finops}; callers MUST tolerate a 404 as "measurement
   * surface not served here".
   */
  async autonomy(): Promise<AutonomyPayload> {
    await this.#requireAuthoritativeSource("/kpi/autonomy");
    return this.#insights.autonomy();
  }

  async listHilQueue(opts: { limit?: number; query?: string } = {}): Promise<HilQueuePage> {
    await this.#requireAuthoritativeSource("/hil-queue");
    return this.#operations.listHilQueue(opts);
  }

  async dataSources(): Promise<ReadDataSourcesPayload> {
    this.#dataSourcesPromise ??= this.#insights
      .panel<unknown>("/system/data-sources")
      .then(decodeReadDataSources);
    try {
      return await this.#dataSourcesPromise;
    } catch (error) {
      this.#dataSourcesPromise = null;
      throw error;
    }
  }

  async iamOverview(): Promise<IamOverview> {
    return this.#iam.overview();
  }

  async iamSelf(): Promise<IamSelfStatus> {
    return this.#iam.self();
  }

  async searchIamUsers(query: string, limit = 20): Promise<readonly HumanIdentityResult[]> {
    return this.#iam.searchUsers(query, limit);
  }

  async iamRoster(): Promise<readonly IdentityRosterItem[]> {
    return this.#iam.roster();
  }

  async listIamAccessRequests(limit = 50, cursor = 0): Promise<IamAccessRequestPage> {
    return this.#iam.listAccessRequests(limit, cursor);
  }

  async listHumanAssignments(limit = 100, cursor = 0): Promise<AssignmentProjectionPage> {
    return this.#iam.assignments(limit, cursor);
  }

  async reports(): Promise<ReportList> {
    await this.#requireAuthoritativeSource("/reports");
    return this.#reporting.reports();
  }

  async reportingRegistry(): Promise<ReportingRegistry> {
    await this.#requireAuthoritativeSource("/reports/registry");
    return this.#reporting.registry();
  }

  async renderReport(
    reportId: string,
    variables: Readonly<Record<string, string>> = {},
  ): Promise<RenderedReportView> {
    await this.#requireAuthoritativeSource("/reports");
    return this.#reporting.render(reportId, variables);
  }

  async downloadReport(
    reportId: string,
    format: string,
    variables: Readonly<Record<string, string>> = {},
  ): Promise<Blob> {
    await this.#requireAuthoritativeSource("/reports");
    return this.#reporting.download(reportId, format, variables);
  }

  /**
   * Fetch a fork-supplied read-only panel payload. Backs the `ReadPanel`
   * seam in `src/fdai/delivery/operator_api/panels.py`: a fork registers
   * a GET route on the API and a matching console panel, then reads it
   * here. This is GET-only like every other call - a panel MUST NOT mutate
   * state (see app-shape.instructions.md § Operator console).
   */
  async panel<T>(path: string, params?: Record<string, string>): Promise<T> {
    await this.#requireAuthoritativeSource(path);
    return this.#insights.panel<T>(path, params);
  }

  async #requireAuthoritativeSource(path: string): Promise<void> {
    let sources: ReadDataSourcesPayload;
    try {
      sources = await this.dataSources();
    } catch (error) {
      if (isOptionalOperatorApiUnavailable(error)) return;
      throw error;
    }
    const reason = unavailableSourceReason(sources, path);
    if (reason !== null) throw new OperatorApiError(503, reason);
  }
}

export { isOptionalOperatorApiUnavailable, OperatorApiError };
export {
  decodeAuditPage,
  decodeHilQueuePage,
  decodeIncidentPage,
  decodeRcaView,
} from "./api-operations";
export {
  decodeAutonomyPayload,
  decodeDashboardKpi,
  decodeScopeView,
} from "./api-insights";
export { decodeReadDataSources, sourceForRoute, unavailableSourceReason } from "./api-data-sources";
export type { ReadDataSourceStatus, ReadDataSourcesPayload } from "./api-data-sources";
