import { ReadApiError, type ReadApiTransport } from "./api-transport";
import {
  decodeRenderedReport,
  decodeReportingRegistry,
  decodeReportList,
  type RenderedReportView,
  type ReportingRegistry,
  type ReportList,
} from "./routes/reporting.model";

export class ReportingApiClient {
  readonly #transport: ReadApiTransport;

  constructor(transport: ReadApiTransport) {
    this.#transport = transport;
  }

  async reports(): Promise<ReportList> {
    return decodeReporting(decodeReportList, await this.#transport.getJson<unknown>("/reports"));
  }

  async registry(): Promise<ReportingRegistry> {
    return decodeReporting(
      decodeReportingRegistry,
      await this.#transport.getJson<unknown>("/reports/registry"),
    );
  }

  async render(
    reportId: string,
    variables: Readonly<Record<string, string>> = {},
  ): Promise<RenderedReportView> {
    return decodeReporting(
      decodeRenderedReport,
      await this.#transport.getJson<unknown>(
        `/reports/${encodeURIComponent(reportId)}/render`,
        new URLSearchParams(variables),
      ),
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
    if (error instanceof ReadApiError) throw error;
    throw new ReadApiError(502, error instanceof Error ? error.message : String(error));
  }
}
