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

test("retries document capabilities after a transient loading failure", async ({ page }) => {
  let capabilityAttempts = 0;
  await page.context().route("http://127.0.0.1:8011/documents?**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "Access-Control-Allow-Origin": "*" },
      body: JSON.stringify({ items: [] }),
    });
  });
  await page.context().route("http://127.0.0.1:8011/ingestion/capabilities", async (route) => {
    capabilityAttempts += 1;
    const headers = { "Access-Control-Allow-Origin": "*" };
    if (capabilityAttempts === 1) {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        headers,
        body: JSON.stringify({ message: "temporary capability failure" }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers,
      body: JSON.stringify({
        supported_formats: ["text"],
        storage_modes: ["managed_copy"],
        max_file_size: 1024,
        max_batch_count: 1,
        archives_enabled: false,
        policy_versions: ["v1"],
        direct_upload: true,
        ocr_available: true,
        collections: ["shared-knowledge"],
      }),
    });
  });

  await page.goto("/documents");
  await expect(page.getByText("temporary capability failure")).toBeVisible();
  await page.getByRole("button", { name: "Retry" }).click();

  await expect(page.getByRole("button", { name: "Choose files" })).toBeEnabled();
  expect(capabilityAttempts).toBe(2);
});

test("uploads a document without overriding collection reader policy", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  let createPayload: Record<string, unknown> | null = null;
  let createAttempts = 0;
  let statusChecks = 0;
  const deletedVersions = new Set<string>();
  const previewVersions: string[] = [];
  const downloadVersions: string[] = [];
  let promotions = 0;
  await page.context().route("http://127.0.0.1:8011/documents?**", async (route) => {
    const persistedCurrent = documentSummary({
      version_id: "version-library-2",
      created_at: "2026-09-05T03:00:00Z",
      updated_at: "2026-09-05T03:01:00Z",
    });
    const persistedLegacy = documentSummary({
      document_id: "document-library-2",
      version_id: "version-library-legacy",
      created_at: "2026-09-04T03:00:00Z",
      updated_at: "2026-09-04T03:01:00Z",
    });
    const persistedPrior = documentSummary({
      version_id: "version-library-1",
      created_at: "2026-09-03T03:00:00Z",
      updated_at: "2026-09-03T03:01:00Z",
      active: false,
    });
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "Access-Control-Allow-Origin": "*" },
      body: JSON.stringify({
        items: [
          ...(!deletedVersions.has("version-library-2")
            ? [persistedCurrent]
            : !deletedVersions.has("version-library-1") ? [persistedPrior] : []),
          ...(!deletedVersions.has("version-library-legacy") ? [persistedLegacy] : []),
          documentSummary({
            document_id: "document-library-3",
            version_id: "version-library-3",
            source_name: "pending-runbook.txt",
            state: "extracting",
            index_status: "pending",
            preview_available: false,
            download_available: false,
            delete_available: false,
          }),
          documentSummary({
            document_id: "document-library-4",
            version_id: "version-library-4",
            source_name: "workspace-draft.txt",
            disposition: "workspace_draft",
            scope_kind: "workspace",
            derived_expires_at: "2026-09-12T03:01:00Z",
            promotable: true,
          }),
        ],
      }),
    });
  });
  await page.context().route("http://127.0.0.1:8011/documents/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const versionId = url.pathname.split("/")[4] ?? "";
    const headers = { "Access-Control-Allow-Origin": "*" };
    if (url.pathname.endsWith("/versions") && request.method() === "GET") {
      const documentId = url.pathname.split("/")[2];
      const items = documentId === "document-library-1"
        ? [
            documentSummary({
              version_id: "version-library-2",
              created_at: "2026-09-05T03:00:00Z",
              updated_at: "2026-09-05T03:01:00Z",
              source_sha256: "b".repeat(64),
            }),
            documentSummary({
              version_id: "version-library-1",
              created_at: "2026-09-03T03:00:00Z",
              updated_at: "2026-09-03T03:01:00Z",
              active: false,
              source_sha256: "a".repeat(64),
            }),
          ]
        : [documentSummary({
            document_id: "document-library-2",
            version_id: "version-library-legacy",
            created_at: "2026-09-04T03:00:00Z",
            updated_at: "2026-09-04T03:01:00Z",
            active: false,
            source_sha256: "a".repeat(64),
          })];
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers,
        body: JSON.stringify({ items }),
      });
      return;
    }
    if (url.pathname.endsWith("/preview")) {
      previewVersions.push(versionId);
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers,
        body: JSON.stringify({
          document_id: "document-library-1",
          version_id: "version-library-1",
          units: [{
            unit_id: "page-1",
            kind: "page",
            locator: "page:1",
            text: "Persistent governed preview",
          }],
          warnings: [],
        }),
      });
      return;
    }
    if (url.pathname.endsWith("/download")) {
      downloadVersions.push(versionId);
      await route.fulfill({
        status: 200,
        contentType: "application/octet-stream",
        headers: {
          ...headers,
          "Content-Disposition": 'attachment; filename="persisted-guide.txt"',
        },
        body: "persistent content",
      });
      return;
    }
    if (url.pathname.endsWith("/promote") && request.method() === "POST") {
      promotions += 1;
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        headers,
        body: JSON.stringify(uploadSession("uploading")),
      });
      return;
    }
    if (request.method() === "DELETE") {
      deletedVersions.add(versionId);
      await route.fulfill({
        status: 202,
        contentType: "application/json",
        headers,
        body: JSON.stringify({ state: "deleting" }),
      });
      return;
    }
    await route.fulfill({ status: 404, contentType: "application/json", headers, body: "{}" });
  });
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
          collections: ["shared-knowledge", "runbooks"],
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
          outcome: "created",
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
  await expect(page.getByText("persisted-guide.txt").first()).toBeVisible();
  await expect(page.locator(".document-index-status").filter({ hasText: "Indexed" }).first())
    .toBeVisible();
  await expect(page.getByRole("button", { name: "runbooks" })).toBeVisible();
  await expect(page.getByText("3 files from 4 latest records")).toBeVisible();
  await expect(page.getByText("persisted-guide.txt")).toHaveCount(1);
  const persistedGroup = page.locator(".document-file-group").filter({
    hasText: "persisted-guide.txt",
  });
  await persistedGroup.getByRole("button", { name: "Show version history" }).click();
  await expect(page.getByText("persisted-guide.txt")).toHaveCount(3);
  await expect(persistedGroup.getByText("Active version", { exact: true })).toHaveCount(1);
  await expect(persistedGroup.getByText("Version 2", { exact: true })).toBeVisible();
  await expect(persistedGroup.getByText("Version 1", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /Hide version history.*3 versions/ }))
    .toBeVisible();
  const historicalRow = persistedGroup.locator(".document-library-row").filter({
    hasText: "Version 2",
  });
  await historicalRow.getByRole("button", { name: "Preview" }).click();
  await expect(page.getByText("Persistent governed preview")).toBeVisible();
  await page.getByRole("button", { name: "Close" }).click();
  const historicalDownload = page.waitForEvent("download");
  await historicalRow.getByRole("button", { name: "Download" }).click();
  await expect(historicalDownload).resolves.toBeTruthy();
  await historicalRow.getByRole("button", { name: "Delete" }).click();
  await historicalRow.getByRole("button", { name: "Delete document" }).click();
  expect(deletedVersions).toContain("version-library-legacy");
  expect(previewVersions).toContain("version-library-legacy");
  expect(downloadVersions).toContain("version-library-legacy");
  await expect(page.getByText("persisted-guide.txt")).toHaveCount(1);
  const refreshedPersistedGroup = page.locator(".document-file-group").filter({
    hasText: "persisted-guide.txt",
  });
  await refreshedPersistedGroup.getByRole("button", { name: "Show version history" }).click();
  await expect(refreshedPersistedGroup.getByText("Version 1", { exact: true })).toBeVisible();
  await refreshedPersistedGroup.getByRole("button", { name: /Hide version history/ }).click();
  await page.getByRole("searchbox", { name: "Search documents" }).fill("pending");
  await expect(page.getByText("pending-runbook.txt")).toBeVisible();
  await expect(page.getByText("persisted-guide.txt")).toHaveCount(0);
  const unavailableActions = [
    ["Preview", "Preview becomes available after indexing and authorization checks."],
    ["Download", "Download requires an indexed, available, unprotected source."],
    ["Delete", "Deletion requires uploader or Owner authority and no legal hold."],
  ] as const;
  for (const [name, explanation] of unavailableActions) {
    const action = page.getByRole("button", { name });
    await expect(action).toHaveAttribute("aria-disabled", "true");
    await expect(action).not.toHaveAttribute("disabled");
    await action.focus();
    await expect(page.getByRole("tooltip", { name: explanation, exact: true })).toBeVisible();
    await action.press("Enter");
  }
  await expect(page.locator(".document-preview-panel")).toHaveCount(0);
  await expect(page.getByText("Delete this version and its indexed content?")).toHaveCount(0);
  await page.getByRole("searchbox", { name: "Search documents" }).fill("");
  await page.getByRole("button", { name: "Add to knowledge" }).click();
  await expect(page.getByText(/Add this document to governed knowledge/)).toBeVisible();
  await page.getByRole("button", { name: "Confirm addition" }).click();
  expect(promotions).toBe(1);
  await page.reload();
  await expect(page.getByText("persisted-guide.txt").first()).toBeVisible();
  await page.getByRole("button", { name: "Preview" }).first().click();
  await expect(page.getByText("Persistent governed preview")).toBeVisible();
  await page.getByRole("button", { name: "Close" }).click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download" }).first().click();
  await expect(download).resolves.toBeTruthy();
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

  await expect(page.locator(".document-upload-row .status-ready")).toHaveText("Ready");
  expect(createAttempts).toBe(2);
  expect(statusChecks).toBe(2);
  expect(createPayload).not.toBeNull();
  expect(createPayload).not.toHaveProperty("reader_groups");
  expect(createPayload).toMatchObject({
    collection_id: "shared-knowledge",
    access_descriptor_ref: "collection:shared-knowledge",
    disposition: "governed_knowledge",
    scope_kind: "collection",
    scope_ref: "shared-knowledge",
    replace_existing: true,
  });
  await expectNoHorizontalOverflow(page);

  await page.setViewportSize({ width: 993, height: 641 });
  await expect(page.getByText("persisted-guide.txt").first()).toBeVisible();
  await expectNoHorizontalOverflow(page);
  const nameBox = await page.locator(".document-library-name").first().boundingBox();
  const statusBox = await page.locator(".document-library-statuses").first().boundingBox();
  expect(nameBox).not.toBeNull();
  expect(statusBox).not.toBeNull();
  expect(nameBox!.x + nameBox!.width).toBeLessThanOrEqual(statusBox!.x);

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".document-library-row").first()).toHaveCSS(
    "grid-template-columns",
    /.+ .+/,
  );
  const mobileHistoryToggle = refreshedPersistedGroup.getByRole("button", {
    name: "Show version history",
  });
  await mobileHistoryToggle.focus();
  await mobileHistoryToggle.press("Enter");
  await expect(refreshedPersistedGroup.locator(".document-library-row")).toHaveCount(2);
  const mobileHistoryClose = refreshedPersistedGroup.getByRole("button", {
    name: /Hide version history/,
  });
  expect(await mobileHistoryClose.evaluate(
    (element) => element.getBoundingClientRect().height,
  )).toBeGreaterThanOrEqual(44);
  await expectNoHorizontalOverflow(page);

  const activeRow = refreshedPersistedGroup.locator(".document-library-row").filter({
    hasText: "Active version",
  });
  await activeRow.getByRole("button", { name: "Delete" }).click();
  await expect(page.getByText("Delete this version and its indexed content?")).toBeVisible();
  await activeRow.getByRole("button", { name: "Cancel" }).click();
  await activeRow.getByRole("button", { name: "Delete" }).click();
  await activeRow.getByRole("button", { name: "Delete document" }).click();
  await expect(page.getByText("persisted-guide.txt")).toHaveCount(1);
  await expect(page.getByText("3 files from 3 latest records")).toBeVisible();
});

test("keeps an unchanged upload on its existing version without sending content", async ({
  page,
}) => {
  let contentWrites = 0;
  await page.context().route("http://127.0.0.1:8011/documents?**", async (route) => {
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      headers: { "Access-Control-Allow-Origin": "*" },
      body: JSON.stringify({ items: [documentSummary()] }),
    });
  });
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
          supported_formats: ["text"],
          storage_modes: ["managed_copy"],
          max_file_size: 1024,
          max_batch_count: 1,
          archives_enabled: false,
          policy_versions: ["v1"],
          direct_upload: true,
          ocr_available: true,
          collections: ["shared-knowledge"],
        }),
      });
      return;
    }
    if (url.pathname === "/ingestion/uploads" && request.method() === "POST") {
      expect(request.postDataJSON()).toMatchObject({ replace_existing: true });
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        headers,
        body: JSON.stringify({
          outcome: "unchanged",
          session: uploadSession("ready"),
          upload: null,
        }),
      });
      return;
    }
    if (url.pathname.endsWith("/content")) contentWrites += 1;
    await route.fulfill({ status: 204, headers });
  });

  await page.goto("/documents");
  await page.locator('input[type="file"]').setInputFiles({
    name: "guide.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("content"),
  });
  await page.getByRole("checkbox").check();
  await page.getByRole("button", { name: "Upload files" }).click();

  await expect(page.getByText(
    "No content or policy changes were detected. The existing version was kept.",
  )).toBeVisible();
  await expect(page.locator(".document-upload-row .status-ready")).toHaveText("Ready");
  expect(contentWrites).toBe(0);
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

function documentSummary(overrides: Record<string, unknown> = {}) {
  return {
    document_id: "document-library-1",
    version_id: "version-library-1",
    source_name: "persisted-guide.txt",
    size_bytes: 17,
    media_type: "text/plain",
    observed_format: "text",
    state: "ready",
    classification: "unclassified",
    sensitivity_label: null,
    protection_state: "none",
    purposes: ["knowledge_base"],
    created_at: "2026-09-05T03:00:00Z",
    updated_at: "2026-09-05T03:01:00Z",
    active: true,
    available: true,
    warnings: [],
    failure_code: null,
    index_status: "indexed",
    preview_available: true,
    download_available: true,
    delete_available: true,
    disposition: "governed_knowledge",
    scope_kind: "collection",
    scope_ref: "shared-knowledge",
    source_expires_at: null,
    derived_expires_at: null,
    retention_state: "live",
    index_state: "active",
    promotable: false,
    ...overrides,
  };
}
