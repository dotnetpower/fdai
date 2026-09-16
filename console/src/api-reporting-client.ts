import { OperatorApiError, type OperatorApiTransport } from "./api-transport";
import {
  type RenderedReportView,
  type ReportingRegistry,
  type ReportList,
} from "./routes/reporting.model";

export class ReportingApiClient {
  readonly #transport: OperatorApiTransport;

  constructor(transport: OperatorApiTransport) {
    this.#transport = transport;
  }

  async reports(): Promise<ReportList> {
    const payload = await this.#transport.getJson<unknown>("/reports");
    const { decodeReportList } = await import("./routes/reporting.model");
    return decodeReporting(decodeReportList, payload);
  }

  async registry(): Promise<ReportingRegistry> {
    const payload = await this.#transport.getJson<unknown>("/reports/registry");
    const { decodeReportingRegistry } = await import("./routes/reporting.model");
    return decodeReporting(decodeReportingRegistry, payload);
  }

  async render(
    reportId: string,
    variables: Readonly<Record<string, string>> = {},
  ): Promise<RenderedReportView> {
    const payload = await this.#transport.getJson<unknown>(
      `/reports/${encodeURIComponent(reportId)}/render`,
      new URLSearchParams(variables),
    );
    const { decodeRenderedReport } = await import("./routes/reporting.model");
    return decodeReporting(
      decodeRenderedReport,
      payload,
    );
  }

  async download(
    reportId: string,
    format: string,
    variables: Readonly<Record<string, string>> = {},
  ): Promise<Blob> {
    const params = new URLSearchParams(variables);
    params.set("format", format);
    const response = await this.#transport.getResponse(
      `/reports/${encodeURIComponent(reportId)}/render`,
      params,
      format === "pdf" ? "application/pdf" : "application/octet-stream",
    );
    return response.blob();
  }
}

function decodeReporting<T>(decode: (value: unknown) => T, value: unknown): T {
  try {
    return decode(value);
  } catch (error) {
    if (error instanceof OperatorApiError) throw error;
    throw new OperatorApiError(502, error instanceof Error ? error.message : String(error));
  }
}
