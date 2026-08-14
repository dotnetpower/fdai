import { createHash } from "node:crypto";
import { writeFile } from "node:fs/promises";

import { expect, test, type Page, type Response, type TestInfo } from "@playwright/test";

import { buildBrowserEvidenceProvenance } from "./browser-evidence-provenance";
import { restoreBrowserEntraSessionStorage } from "./browser-entra-state";

const TARGET_CORRELATION = process.env.FDAI_E2E_INCIDENT_RCA_CORRELATION_ID;
const NO_RCA_CORRELATION = process.env.FDAI_E2E_INCIDENT_NO_RCA_CORRELATION_ID;
const AUTHENTICATED_EXTERNAL_STACK = Boolean(
  process.env.FDAI_E2E_BASE_URL &&
  process.env.FDAI_E2E_STORAGE_STATE &&
  TARGET_CORRELATION &&
  NO_RCA_CORRELATION,
);

function digest(value: unknown): string {
  const body = typeof value === "string" || Buffer.isBuffer(value)
    ? value
    : JSON.stringify(canonicalJsonValue(value));
  return `sha256:${createHash("sha256").update(body).digest("hex")}`;
}

function canonicalJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonicalJsonValue);
  if (typeof value !== "object" || value === null) return value;
  return Object.fromEntries(
    Object.entries(value)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, canonicalJsonValue(item)]),
  );
}

function jsonRecord(value: unknown, label: string): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

function jsonArray(value: unknown, label: string): readonly unknown[] {
  if (!Array.isArray(value)) throw new Error(`${label} must be an array`);
  return value;
}

async function responseJson(response: Response): Promise<Record<string, unknown>> {
  expect(response.status()).toBe(200);
  return jsonRecord(await response.json(), new URL(response.url()).pathname);
}

function isJsonResponse(response: Response, pathname: string): boolean {
  return new URL(response.url()).pathname === pathname &&
    response.headers()["content-type"]?.includes("application/json") === true;
}

async function waitForReadyShell(page: Page): Promise<void> {
  await expect(page.locator(".shell")).toBeVisible({ timeout: 15_000 });
  await expect(page.locator("main [aria-busy='true']")).toHaveCount(0, { timeout: 20_000 });
  await expect(page.getByText("FDAI could not verify your access.")).toHaveCount(0);
}

async function retainArtifact(testInfo: TestInfo, artifact: object): Promise<void> {
  const artifactPath = testInfo.outputPath("incident-rca-report-assurance.json");
  await writeFile(artifactPath, `${JSON.stringify(artifact, null, 2)}\n`, "utf8");
  await testInfo.attach("incident-rca-report-assurance", {
    path: artifactPath,
    contentType: "application/json",
  });
}

test("Browser Entra binds Incident RCA evidence to the optional PDF report", async ({ page }, testInfo) => {
  test.skip(!AUTHENTICATED_EXTERNAL_STACK, "requires Browser Entra state and RCA correlations");
  test.setTimeout(120_000);
  const targetCorrelation = TARGET_CORRELATION!;
  const noRcaCorrelation = NO_RCA_CORRELATION!;
  const targetRef = digest(targetCorrelation);
  const noRcaRef = digest(noRcaCorrelation);
  const runConfiguration = {
    schema_version: "1.0.0",
    authentication: "browser_entra",
    routes: ["/incidents", "/rca", "/reports/incident-rca-dossier"],
    target_ref: targetRef,
    unavailable_target_ref: noRcaRef,
    expected_pdf_format: "application/pdf",
  };
  const provenance = buildBrowserEvidenceProvenance(
    process.env.FDAI_E2E_SOURCE_REVISION,
    process.env.FDAI_E2E_WORKSPACE_PATCH_SHA256,
    runConfiguration,
  );

  await restoreBrowserEntraSessionStorage(page);
  const incidentResponses: Response[] = [];
  page.on("response", (response) => {
    if (isJsonResponse(response, "/incidents") && response.status() === 200) {
      incidentResponses.push(response);
    }
  });
  const auditResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return isJsonResponse(response, "/audit") &&
      url.searchParams.get("correlation_id") === targetCorrelation &&
      response.status() === 200;
  });
  await page.goto(
    `/incidents?status=all&correlation=${encodeURIComponent(targetCorrelation)}`,
    { waitUntil: "domcontentloaded" },
  );
  await waitForReadyShell(page);
  await expect(page.locator("#incident-detail")).toBeVisible();
  await expect(page.locator(".incident-outcome-analytics")).toBeVisible();
  await expect(page.locator(".incident-milestones")).toBeVisible();
  const milestoneCount = await page.locator(".incident-milestones li").count();
  expect(milestoneCount).toBeGreaterThan(0);
  const incidentEnvelopes = await Promise.all(incidentResponses.map(responseJson));
  const incidentEnvelope = incidentEnvelopes.find((envelope) =>
    jsonArray(envelope.items, "incident items").some((raw) =>
      jsonRecord(raw, "incident item").correlation_id === targetCorrelation,
    ),
  );
  if (incidentEnvelope === undefined) {
    throw new Error("exact target incident envelope was not observed");
  }
  const incidentTarget = jsonRecord(
    jsonArray(incidentEnvelope.items, "incident items").find((raw) =>
      jsonRecord(raw, "incident item").correlation_id === targetCorrelation,
    ),
    "target incident",
  );
  const sourceContextRecorded = incidentTarget.source !== null;
  const responsePlanRecorded = incidentTarget.response_plan !== null;
  const sourceContextVisible = await page.locator(".incident-source-context").count() > 0;
  expect(sourceContextVisible).toBe(sourceContextRecorded || responsePlanRecorded);
  const auditEnvelope = await responseJson(await auditResponsePromise);
  const auditItems = jsonArray(auditEnvelope.items, "audit items");

  const rcaResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return isJsonResponse(response, "/rca") &&
      url.searchParams.get("correlation") === targetCorrelation;
  });
  await page.goto(`/root-cause-analysis?correlation=${encodeURIComponent(targetCorrelation)}`, {
    waitUntil: "domcontentloaded",
  });
  await waitForReadyShell(page);
  const rcaEnvelope = await responseJson(await rcaResponsePromise);
  const hypotheses = jsonArray(rcaEnvelope.hypotheses, "RCA hypotheses");
  expect(hypotheses.length).toBeGreaterThan(0);
  const citationCount = hypotheses.reduce((total, raw) => {
    const hypothesis = jsonRecord(raw, "RCA hypothesis");
    return total + jsonArray(hypothesis.citations, "RCA citations").length;
  }, 0);
  expect(citationCount).toBeGreaterThan(0);
  expect(rcaEnvelope.response).not.toBeNull();
  await expect(page.locator("a[href^='/reports/incident-rca-dossier']")).toBeVisible();

  const reportListPromise = page.waitForResponse((response) =>
    isJsonResponse(response, "/reports") && response.status() === 200,
  );
  const registryPromise = page.waitForResponse((response) =>
    isJsonResponse(response, "/reports/registry") && response.status() === 200,
  );
  const reportRenderPromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return isJsonResponse(response, "/reports/incident-rca-dossier/render") &&
      url.searchParams.get("format") === null &&
      response.status() === 200;
  });
  await page.goto(
    `/reports/incident-rca-dossier?correlation_id=${encodeURIComponent(targetCorrelation)}`,
    { waitUntil: "domcontentloaded" },
  );
  await waitForReadyShell(page);
  const reportList = await responseJson(await reportListPromise);
  const registry = await responseJson(await registryPromise);
  const reportEnvelope = await responseJson(await reportRenderPromise);
  expect(jsonArray(reportList.formats, "report formats")).toContain("pdf");
  expect(jsonArray(registry.formats, "registry formats")).toContain("pdf");
  const downloadButton = page.getByRole("button", { name: /Download PDF|PDF 다운로드/ });
  await expect(downloadButton).toBeVisible();
  await expect(downloadButton).toBeEnabled();

  const pdfResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return url.pathname === "/reports/incident-rca-dossier/render" &&
      url.searchParams.get("format") === "pdf";
  });
  const downloadPromise = page.waitForEvent("download");
  await downloadButton.click();
  const [pdfResponse, download] = await Promise.all([pdfResponsePromise, downloadPromise]);
  expect(pdfResponse.status()).toBe(200);
  expect(pdfResponse.headers()["content-type"]).toContain("application/pdf");
  expect(download.suggestedFilename()).toBe("incident-rca-dossier.pdf");
  const pdfBody = await pdfResponse.body();
  expect(pdfBody.subarray(0, 5).toString()).toBe("%PDF-");

  const unavailableResponsePromise = page.waitForResponse((response) => {
    const url = new URL(response.url());
    return isJsonResponse(response, "/rca") &&
      url.searchParams.get("correlation") === noRcaCorrelation;
  });
  await page.goto(`/root-cause-analysis?correlation=${encodeURIComponent(noRcaCorrelation)}`, {
    waitUntil: "domcontentloaded",
  });
  await waitForReadyShell(page);
  const unavailableEnvelope = await responseJson(await unavailableResponsePromise);
  expect(jsonArray(unavailableEnvelope.hypotheses, "unavailable RCA hypotheses")).toHaveLength(0);
  await expect(page.locator(".rca-unavailable-state")).toBeVisible();

  await retainArtifact(testInfo, {
    schema_version: "1.0.0",
    evidence_type: "authenticated_incident_rca_report_assurance",
    receipt_source: "live_browser_entra",
    ...provenance,
    run_configuration: runConfiguration,
    captured_at: new Date().toISOString(),
    authentication: "browser_entra",
    passed: true,
    target_ref: targetRef,
    incident: {
      envelope_digest: digest(incidentEnvelope),
      audit_digest: digest(auditEnvelope),
      audit_record_count: auditItems.length,
      milestone_count: milestoneCount,
      source_context_recorded: sourceContextRecorded,
      source_context_visible: sourceContextVisible,
      response_plan_recorded: responsePlanRecorded,
      unavailable_source_or_plan_preserved: !sourceContextRecorded || !responsePlanRecorded,
      title_source: incidentTarget.title_source,
    },
    rca: {
      envelope_digest: digest(rcaEnvelope),
      hypothesis_count: hypotheses.length,
      citation_count: citationCount,
      response_plan_recorded: rcaEnvelope.response !== null,
    },
    report: {
      envelope_digest: digest(reportEnvelope),
      pdf_body_digest: digest(pdfBody),
      pdf_bytes: pdfBody.byteLength,
      pdf_content_type: pdfResponse.headers()["content-type"],
      suggested_filename: download.suggestedFilename(),
    },
    unavailable_behavior: {
      target_ref: noRcaRef,
      envelope_digest: digest(unavailableEnvelope),
      hypothesis_count: 0,
      unavailable_state_visible: true,
    },
    execution_authority: false,
  });
});
