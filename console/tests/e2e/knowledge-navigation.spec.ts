import { expect, test, type Page } from "@playwright/test";

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  expect(await page.evaluate(
    () => document.documentElement.scrollWidth <= document.documentElement.clientWidth,
  )).toBe(true);
  expect(await page.locator(".shell-body > main").evaluate(
    (element) => element.scrollWidth <= element.clientWidth,
  )).toBe(true);
}

test("navigates the Knowledge domain without implying unavailable connectors are active", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/knowledge");

  await expect(page.locator(".page-header-title")).toContainText("Knowledge");
  await expect(page.locator(".page-header-title")).toContainText("Overview");
  await expect(page.locator(".knowledge-source-card")).toHaveCount(4);
  await expect(page.getByRole("link", { name: /Documents/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /GitHub/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /GitLab/ })).toBeVisible();
  await expect(page.getByRole("link", { name: /Azure DevOps/ })).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.getByRole("link", { name: /GitHub/ }).click();
  await expect(page).toHaveURL(/\/github$/);
  await expect(page.getByRole("heading", { name: "GitHub connection is not configured" }))
    .toBeVisible();
  await expect(page.getByText("No repository content has been synchronized or indexed"))
    .toBeVisible();

  await page.goto("/knowledge");
  await page.setViewportSize({ width: 993, height: 641 });
  await expect(page.locator(".knowledge-source-card")).toHaveCount(4);
  await expectNoHorizontalOverflow(page);

  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.locator(".knowledge-source-grid").evaluate(
    (element) => getComputedStyle(element).gridTemplateColumns.split(" ").length,
  )).toBe(1);
  await expect(page.locator(".knowledge-settings-link")).toHaveCSS("min-height", "44px");
  await expectNoHorizontalOverflow(page);
});

test("uploads a document without overriding collection reader policy", async ({ page }) => {
  let createPayload: Record<string, unknown> | null = null;
  let createAttempts = 0;
  let statusChecks = 0;
  await page.context().route("http://127.0.0.1:8011/ingestion/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const headers = { "Access-Control-Allow-Origin": "*" };
    if (url.pathname === "/ingestion/capabilities") {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers,
        body: JSON.stringify({
          supported_formats: ["text", "pdf", "docx", "pptx", "xlsx", "png", "jpeg", "tiff"],
          storage_modes: ["managed_copy"],
          max_file_size: 1024,
          max_batch_count: 1,
          archives_enabled: false,
          policy_versions: ["v1"],
          direct_upload: true,
          ocr_available: true,
        }),
      });
      return;
    }
    if (url.pathname === "/ingestion/uploads" && request.method() === "POST") {
      createAttempts += 1;
      createPayload = request.postDataJSON() as Record<string, unknown>;
      if (createAttempts === 1) {
        await route.fulfill({
          status: 400,
          contentType: "application/json",
          headers,
          body: JSON.stringify({ message: "temporary upload request failure" }),
        });
        return;
      }
      await route.fulfill({
        status: 201,
        contentType: "application/json",
        headers,
        body: JSON.stringify({
          session: uploadSession("created"),
          upload: {
            target: "/ingestion/uploads/upload-1/content",
            expires_at: "2026-09-04T10:00:00Z",
            completed_parts: [],
          },
        }),
      });
      return;
    }
    if (url.pathname.endsWith("/content")) {
      await route.fulfill({ status: 204, headers });
      return;
    }
    if (url.pathname.endsWith("/complete")) {
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        headers,
        body: JSON.stringify(uploadSession("received")),
      });
      return;
    }
    statusChecks += 1;
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers,
      body: JSON.stringify(uploadSession(
        statusChecks === 1 ? "held" : "ready",
        statusChecks === 1 ? "office_password_encrypted" : null,
      )),
    });
  });

  await page.goto("/documents");
  const filePicker = page.getByRole("button", { name: "Choose files" });
  await expect(filePicker).toBeVisible();
  await expect(filePicker).toHaveCSS("display", "flex");
  await expect(filePicker).toHaveCSS("cursor", "pointer");
  await expect(page.locator('input[type="file"]')).toHaveAttribute(
    "accept",
    ".txt,.md,.rst,.json,.yaml,.yml,.xml,.csv,.tf,.rego,.pdf,.docx,.pptx,.xlsx,.png,.jpg,.jpeg,.tif,.tiff",
  );
  await page.locator('input[type="file"]').setInputFiles({
    name: "guide.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("content"),
  });
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Upload files" }).click();
  await expect(page.getByText("temporary upload request failure")).toBeVisible();
  await page.getByRole("button", { name: "Retry" }).click();
  await page.getByRole("button", { name: "Upload files" }).click();
  await expect(page.getByText(/encrypted or protected document/)).toBeVisible();
  await page.getByRole("button", { name: "Check status" }).click();

  await expect(page.locator(".status-ready")).toHaveText("Ready");
  expect(createAttempts).toBe(2);
  expect(statusChecks).toBe(2);
  expect(createPayload).not.toBeNull();
  expect(createPayload).not.toHaveProperty("reader_groups");
  expect(createPayload).toMatchObject({
    collection_id: "shared-knowledge",
    access_descriptor_ref: "collection:shared-knowledge",
  });
});

function uploadSession(state: string, failureCode: string | null = null) {
  return {
    upload_id: "upload-1",
    document_id: "document-1",
    version_id: "version-1",
    source_name: "guide.txt",
    state,
    collection_id: "shared-knowledge",
    failure_code: failureCode,
  };
}
