import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";

const goalId = "a".repeat(64);
const slots = ["scope_exclusions", "decision_triggers", "runbook_rollback", "dependencies_escalation", "failure_risks", "source_governance"];

test("explicit handover slots and revisioned exemptions preserve desktop and mobile operation", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const goal: Record<string, unknown> = {
    goal_id: goalId, subject_ref: "synthetic-person", agent_name: "Muninn", state: "not_started", revision: 1,
    execution_authority: false, checklist_version: "1.0.0", required_slots: slots,
    evidence: [], slot_exemptions: {}, high_impact: true, owner_review: null, backup_review: null,
    allowed_operations: ["evidence", "not-applicable", "reuse", "snooze", "decline"],
  };
  const submitted: Record<string, unknown>[] = [];
  await page.route("**/handover/goals/**", async (route) => {
    if (route.request().method() === "POST") {
      const body = route.request().postDataJSON() as Record<string, unknown>;
      submitted.push(body);
      goal.slot_exemptions = { ...(goal.slot_exemptions as object), [String(body.slot)]: body.reason_ref };
      goal.revision = Number(goal.revision) + 1;
      goal.state = "in_progress";
    }
    await route.fulfill({ json: { goal } });
  });
  await page.route("http://127.0.0.1:8011/**", async (route) => {
    const origin = new URL(page.url()).origin;
    await route.fulfill({ status: 503, headers: { "Access-Control-Allow-Origin": origin }, json: { message: "synthetic ingestion unavailable" } });
  });
  await page.goto(`/documents?handover_goal=${goalId}`);
  const panel = page.locator(".handover-checklist");
  await expect(panel.getByRole("heading", { name: "Handover evidence checklist" })).toBeVisible();
  await expect(panel.locator("ol li")).toHaveCount(6);
  await expect(panel.getByText("Evidence checklist incomplete")).toBeVisible();
  await expect(panel.getByRole("button", { name: "Record Owner review" })).toHaveCount(0);
  await panel.getByRole("combobox", { name: "Evidence area", exact: true }).selectOption("scope_exclusions");
  await panel.getByRole("textbox", { name: "Reason reference", exact: true }).fill("reason:reviewed-exclusion");
  await panel.getByRole("button", { name: "Record not applicable" }).focus();
  await page.keyboard.press("Enter");
  await expect(panel.getByText("Not applicable, with reason")).toBeVisible();
  await panel.getByText("Goal and source details", { exact: true }).click();
  await expect(panel.getByText(goalId, { exact: true })).toBeVisible();
  expect(submitted).toEqual([{ expected_revision: 1, slot: "scope_exclusions", reason_ref: "reason:reviewed-exclusion" }]);
  for (const viewport of [{ width: 1440, height: 900 }, { width: 993, height: 641 }, { width: 390, height: 844 }, { width: 320, height: 844 }]) {
    await page.setViewportSize(viewport);
    expect(await panel.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await page.screenshot({ path: testInfo.outputPath(`checklist-${viewport.width}.png`), fullPage: true });
  }
  await page.emulateMedia({ reducedMotion: "reduce" });
  await expect(panel.getByRole("button", { name: "Refresh evidence" })).toBeEnabled();
  expect(await panel.getByRole("button", { name: "Refresh evidence" }).evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44);
  await page.addStyleTag({ content: ".handover-checklist { font-size: 200%; line-height: 1.5; letter-spacing: .12em; word-spacing: .16em; } .handover-checklist p { margin-block-end: 2em; }" });
  expect(await panel.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.emulateMedia({ forcedColors: "active" });
  await panel.getByRole("button", { name: "Refresh evidence" }).focus();
  await expect(panel.getByRole("button", { name: "Refresh evidence" })).toBeFocused();
});

async function stubUploadBoundary(page: Page): Promise<string[]> {
  const writes: string[] = [];
  await page.route("**/handover/goals/**", async (route) => {
    if (route.request().method() === "POST") {
      await route.fulfill({ status: 409, json: { message: "synthetic revision conflict" } });
      return;
    }
    await route.fulfill({ json: { goal: {
      goal_id: goalId, subject_ref: "synthetic-person", agent_name: "Muninn",
      state: "in_progress", revision: 1, execution_authority: false,
      checklist_version: "1.0.0", required_slots: slots, evidence: [], slot_exemptions: {},
      high_impact: true, owner_review: null, backup_review: null, allowed_operations: ["evidence"],
    } } });
  });
  await page.route("http://127.0.0.1:8011/**", async (route) => {
    const method = route.request().method();
    const pathname = new URL(route.request().url()).pathname;
    const headers = {
      "Access-Control-Allow-Origin": new URL(page.url()).origin,
      "Access-Control-Allow-Headers": "authorization,content-type",
      "Access-Control-Allow-Methods": "GET,POST,PUT,OPTIONS",
    };
    if (method === "OPTIONS") {
      await route.fulfill({ status: 204, headers });
      return;
    }
    if (method !== "GET") writes.push(`${method} ${pathname}`);
    const session = {
      upload_id: "synthetic-upload", document_id: "00000000-0000-0000-0000-000000000031",
      version_id: "00000000-0000-0000-0000-000000000032", source_name: "runbook.txt",
      state: "ready_with_warnings", collection_id: "shared-knowledge",
    };
    const body = pathname.endsWith("/capabilities") ? {
      supported_formats: ["text"], storage_modes: ["managed_copy"], max_file_size: 4096,
      max_batch_count: 10, archives_enabled: false, policy_versions: ["v1"], direct_upload: true,
    } : pathname === "/documents" ? { items: [] }
      : pathname === "/ingestion/uploads" ? {
        session, upload: { target: "/ingestion/uploads/synthetic-upload/content" },
      } : session;
    await route.fulfill({ headers, json: body });
  });
  return writes;
}

test("handover upload rejects multiple dropped files before content transfer", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const writes = await stubUploadBoundary(page);
  await page.goto(`/documents?handover_goal=${goalId}`);
  await expect(page.getByRole("button", { name: "Choose files", exact: true })).toBeEnabled();
  const transfer = await page.evaluateHandle(() => {
    const data = new DataTransfer();
    data.items.add(new File(["synthetic one"], "one.txt", { type: "text/plain" }));
    data.items.add(new File(["synthetic two"], "two.txt", { type: "text/plain" }));
    return data;
  });
  await page.locator(".document-drop-zone").dispatchEvent("drop", { dataTransfer: transfer });
  await transfer.dispose();
  await expect(page.getByRole("alert").filter({ hasText: "Select one file for the chosen handover evidence area." })).toBeVisible();
  await expect(page.locator(".document-upload-row")).toHaveCount(0);
  await expect(page.locator('input[type="file"]')).not.toHaveAttribute("multiple");
  const chooserReady = page.waitForEvent("filechooser");
  await page.getByRole("button", { name: "Choose files", exact: true }).focus();
  await page.keyboard.press("Enter");
  await (await chooserReady).setFiles({ name: "one.txt", mimeType: "text/plain", buffer: Buffer.from("synthetic one") });
  await expect(page.locator(".document-upload-row")).toHaveCount(1);
  await expect(page.getByRole("alert").filter({ hasText: "Select one file" })).toHaveCount(0);
  expect(writes).toEqual([]);
});

test("processing warnings never hide a failed handover evidence link", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const writes = await stubUploadBoundary(page);
  await page.goto(`/documents?handover_goal=${goalId}`);
  await expect(page.getByRole("button", { name: "Choose files", exact: true })).toBeEnabled();
  await page.getByRole("combobox", { name: "Evidence area", exact: true }).selectOption("scope_exclusions");
  await page.locator('input[type="file"]').setInputFiles({ name: "runbook.txt", mimeType: "text/plain", buffer: Buffer.from("synthetic runbook") });
  await page.locator(".document-consent input").check();
  await page.getByRole("button", { name: "Upload files", exact: true }).click();
  await expect(page.locator(".document-upload-row .status-ready")).toBeVisible();
  await expect(page.locator(".document-upload-notice")).toContainText("could not be linked to the handover");
  expect(writes.filter((item) => item === "POST /ingestion/uploads")).toHaveLength(1);
});
