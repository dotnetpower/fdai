import { expect, test, type Page, type Route } from "@playwright/test";

const revision = "0123456789abcdef0123456789abcdef01234567";

function review(alias: string, overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    repository_alias: alias,
    revision,
    review_digest: "4".repeat(64),
    recorded_at: "2026-10-07T08:00:00+00:00",
    issue_count: 12,
    by_priority: { P0: 1, P1: 3, P2: 4, P3: 4, P4: 0 },
    by_severity: { critical: 1, high: 3, medium: 4, low: 2, undetermined: 2 },
    by_confidence: { hypothesis: 2, reported: 6, corroborated: 2, verified: 2, proven: 0 },
    known_exploited_count: 0,
    exposure: "exposed",
    coverage_complete: true,
    top_issue_ids: ["FDAI-SEC-0123456789ab"],
    decision: "urgent",
    ...overrides,
  };
}

async function mockApi(
  page: Page,
  posted: unknown[] = [],
  repositories: readonly Record<string, unknown>[] = [
    {
      repository_alias: "payments-api-with-a-deliberately-long-repository-alias",
      provider: "github",
      location: "example-organization/payments-api-with-a-deliberately-long-name",
      default_ref: "main",
      exposure: "exposed",
      enabled: true,
      registered_at: "2026-10-07T08:00:00+00:00",
    },
  ],
): Promise<void> {
  const handleApi = async (route: Route) => {
    const path = new URL(route.request().url()).pathname.replace(/^\/api/, "");
    if (path === "/code-security/repositories" && route.request().method() === "POST") {
      posted.push(route.request().postDataJSON());
      await route.fulfill({
        status: 202,
        json: {
          request_id: `operator-${"e".repeat(32)}`,
          correlation_id: null,
          dispatch_status: "pending",
          accepted_at: "2026-10-08T08:00:00+00:00",
          durably_queued: true,
        },
      });
      return;
    }
    if (path === "/code-security/issues") {
      await route.fulfill({
        json: {
          surface: "code-security-issues",
          repository_alias: "payments-api-with-a-deliberately-long-repository-alias",
          revision,
          source: "postgresql:state_kv:code-security-issues",
          available: true,
          complete: true,
          truncated: false,
          issues: [
            {
              issue_id: "FDAI-SEC-0123456789ab",
              priority: "P0",
              due_days: 2,
              severity: "critical",
              confidence: "verified",
              weakness_class: "command_injection",
              cwe_ids: [78],
              advisory_ids: [],
              package: null,
              producers: ["Opengrep", "gitleaks"],
              known_exploited: false,
            },
            {
              issue_id: "FDAI-SEC-ba9876543210",
              priority: "P1",
              due_days: 7,
              severity: "high",
              confidence: "corroborated",
              weakness_class: "vulnerable_dependency",
              cwe_ids: [],
              advisory_ids: ["CVE-2026-12345", "GHSA-abcd-efgh-ijkl"],
              package: "example-deliberately-long-dependency-package-name",
              producers: ["Trivy", "osv-scanner"],
              known_exploited: true,
            },
          ],
          gaps: [],
        },
      });
      return;
    }
    if (path === "/code-security/scan-requests" && route.request().method() === "POST") {
      posted.push(route.request().postDataJSON());
      await route.fulfill({
        status: 202,
        json: {
          request_id: `operator-${"c".repeat(32)}`,
          correlation_id: null,
          dispatch_status: "pending",
          accepted_at: "2026-10-08T08:00:00+00:00",
          durably_queued: true,
        },
      });
      return;
    }
    if (path === "/code-security/repositories") {
      await route.fulfill({
        json: {
          surface: "code-security-repositories",
          available: true,
          complete: true,
          source: "postgresql:state_kv:code-security-repository",
          repositories,
          gaps: [],
        },
      });
      return;
    }
    if (path === "/code-security/scan-requests") {
      await route.fulfill({
        json: {
          surface: "code-security-scan-requests",
          available: true,
          complete: true,
          source: "postgresql:state_kv:operator-proposal",
          requests: [
            {
              request_id: `operator-${"a".repeat(32)}`,
              kind: "scan",
              action: null,
              location: null,
              repository_alias: "payments-api-with-a-deliberately-long-repository-alias",
              ref: "release/2026-10",
              status: "completed",
              accepted_at: "2026-10-07T08:00:00+00:00",
              closed_at: "2026-10-07T08:04:00+00:00",
              rejection_reason: null,
              result: { revision, decision: "urgent", issue_count: 12, coverage_complete: true },
            },
            {
              request_id: `operator-${"b".repeat(32)}`,
              kind: "scan",
              action: null,
              location: null,
              repository_alias: "payments-api-with-a-deliberately-long-repository-alias",
              ref: null,
              status: "rejected",
              accepted_at: "2026-10-07T07:00:00+00:00",
              closed_at: "2026-10-07T07:00:05+00:00",
              rejection_reason: "source_unavailable",
              result: null,
            },
            {
              request_id: `operator-${"d".repeat(32)}`,
              kind: "repository_change",
              action: "register",
              location: "example-organization/payments-api-with-a-deliberately-long-name",
              repository_alias: "payments-api-with-a-deliberately-long-repository-alias",
              ref: null,
              status: "completed",
              accepted_at: "2026-10-07T06:00:00+00:00",
              closed_at: "2026-10-07T06:00:05+00:00",
              rejection_reason: null,
              result: { enabled: true },
            },
          ],
          gaps: [],
        },
      });
      return;
    }
    if (path === "/system/data-sources") {
      await route.fulfill({
        json: {
          surface: "read-data-sources",
          sources: [
            {
              key: "operational-state",
              source: "postgresql",
              routes: [
                "/code-security/reviews",
                "/code-security/packs",
                "/code-security/repositories",
                "/code-security/scan-requests",
                "/code-security/issues",
              ],
              availability: "available",
              configured: true,
              reachable: true,
              authoritative: true,
              durable: true,
              synthetic: false,
              reason: null,
              last_observed_at: "2026-10-07T08:00:00Z",
            },
          ],
        },
      });
      return;
    }
    if (path === "/code-security/reviews") {
      await route.fulfill({
        json: {
          surface: "code-security-reviews",
          available: true,
          complete: false,
          source: "postgresql:state_kv:code-security-review",
          reviews: [
            review("payments-api-with-a-deliberately-long-repository-alias", {
              source: {
                kind: "git_repository",
                provider: "github",
                revision_kind: "commit",
                trigger: "console",
                request_id: `operator-${"a".repeat(32)}`,
              },
              producers: ["Opengrep", "gitleaks"],
            }),
            review("mdash-imported-service", {
              source: { kind: "external_sarif", provider: "mdash", revision_kind: "commit", trigger: "cli", request_id: null },
              producers: ["MDASH"],
            }),
            review("example-service", {
              decision: "coverage_incomplete",
              coverage_complete: false,
              issue_count: 0,
              by_priority: { P0: 0, P1: 0, P2: 0, P3: 0, P4: 0 },
            }),
          ],
          gaps: [{ reason_code: "code_security_review_malformed" }],
        },
      });
      return;
    }
    if (path === "/code-security/packs") {
      await route.fulfill({
        json: {
          surface: "code-security-packs",
          available: true,
          complete: true,
          source: "postgresql:state_kv:code-security-pack",
          packs: [
            {
              pack_id: "fedcba987654",
              base_commit: revision,
              issue_count: 12,
              recorded_at: "2026-10-07T08:00:00+00:00",
              expires_at: "2099-10-14T08:00:00+00:00",
              revoked: false,
              latest_verification: {
                rescan_revision: revision,
                recorded_at: "2026-10-08T08:00:00+00:00",
                verdicts: { fixed_verified: 9, still_present: 2, inconclusive: 1, not_applicable: 0 },
              },
              adjudications: [],
            },
          ],
          gaps: [],
        },
      });
      return;
    }
    await route.fulfill({ status: 503, json: { detail: "unavailable" } });
  };
  await page.route("**/api/**", handleApi);
  await page.route("**/system/data-sources*", handleApi);
  await page.route("**/code-security/**", handleApi);
}

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 993, height: 641 },
  { width: 390, height: 844 },
]) {
  test(`renders code-security reviews without overflow at ${viewport.width}px`, async ({ page }) => {
    await page.setViewportSize(viewport);
    await mockApi(page);
    await page.goto("/code-security");

    await expect(page.getByRole("heading", { name: "Code security" }).first()).toBeVisible();
    await expect(page.getByText("payments-api-with-a-deliberately-long-repository-alias").first()).toBeVisible();
    await expect(page.getByText("Coverage incomplete").first()).toBeVisible();
    await expect(page.getByText("Withheld review records")).toBeVisible();
    await expect(page.getByRole("heading", { name: "Remediation packs" })).toBeVisible();
    await expect(page.getByText("fedcba987654", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: /approve|execute|fix/i })).toHaveCount(0);
    await expect(page.getByRole("heading", { name: "Repository scans" })).toBeVisible();
    await expect(page.getByText("The repository or ref could not be fetched.")).toBeVisible();
    await page.getByRole("button", { name: /External SARIF/ }).click();
    await expect(page.getByText("mdash-imported-service")).toBeVisible();
    await expect(page.getByText("example-service", { exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: /All sources/ }).click();
    await page.getByRole("button", { name: /^View payments-api-with-a-deliberately-long-repository-alias/ }).click();
    await expect(page.getByRole("heading", { name: /Issues in this review/ })).toBeVisible();
    await expect(page.getByText("example-deliberately-long-dependency-package-name CVE-2026-12345, GHSA-abcd-efgh-ijkl")).toBeVisible();
    await expect(page.getByText("CWE-78", { exact: true })).toBeVisible();

    const geometry = await page.evaluate(() => {
      const main = document.querySelector("main");
      return {
        documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
        mainOverflow: main === null ? null : main.scrollWidth - main.clientWidth,
      };
    });
    expect(geometry.documentOverflow).toBeLessThanOrEqual(0);
    expect(geometry.mainOverflow).not.toBeNull();
    expect(geometry.mainOverflow!).toBeLessThanOrEqual(0);
  });
}

test("queues a scan request for a registered repository", async ({ page }) => {
  const posted: unknown[] = [];
  await mockApi(page, posted);
  await page.goto("/code-security");
  await page.getByLabel("Branch, tag, or commit").fill("release/2026-10");
  await page.getByRole("button", { name: "Request scan" }).click();
  await expect(page.getByText("Scan request queued.", { exact: false })).toBeVisible();
  expect(posted).toEqual([
    {
      repository_alias: "payments-api-with-a-deliberately-long-repository-alias",
      ref: "release/2026-10",
    },
  ]);
});

test("queues an Owner registration change from the Console", async ({ page }) => {
  const posted: unknown[] = [];
  await mockApi(page, posted);
  await page.goto("/code-security");
  await page.getByText("Register a GitHub repository").click();
  const form = page.locator(".code-security-register-form");
  await form.getByLabel("Alias", { exact: true }).fill("new-service");
  await form.getByLabel("GitHub repository", { exact: true }).fill("example-organization/new-service");
  await form.getByLabel("Exposure", { exact: true }).selectOption("internal");
  await page.getByRole("button", { name: "Request registration" }).click();
  await expect(page.getByText("Change request queued.", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "Disable" }).first().click();
  expect(posted).toEqual([
    {
      action: "register",
      repository_alias: "new-service",
      location: "example-organization/new-service",
      exposure: "internal",
    },
    { action: "disable", repository_alias: "payments-api-with-a-deliberately-long-repository-alias" },
  ]);
});

test("presents repository registration as the primary empty-state task", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await mockApi(page, [], []);
  await page.goto("/code-security");

  const registration = page.locator(".code-security-register");
  await expect(registration).toHaveAttribute("open", "");
  await expect(page.getByLabel("Alias", { exact: true })).toBeVisible();
  await expect(page.getByLabel("GitHub repository", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Request registration" })).toBeDisabled();
  await expect(page.getByText("No repository is registered for Console scans.")).toHaveCount(0);

  const geometry = await registration.evaluate((element) => {
    const form = element.querySelector(".code-security-register-form");
    const alias = element.querySelector<HTMLInputElement>('input[required]');
    const summary = element.querySelector("summary");
    if (form === null || alias === null || summary === null) throw new Error("registration controls missing");
    return {
      columns: getComputedStyle(form).gridTemplateColumns.split(" ").length,
      inputHeight: alias.getBoundingClientRect().height,
      summaryHeight: summary.getBoundingClientRect().height,
      documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    };
  });
  expect(geometry.columns).toBe(12);
  expect(geometry.inputHeight).toBeGreaterThanOrEqual(40);
  expect(geometry.summaryHeight).toBeGreaterThanOrEqual(48);
  expect(geometry.documentOverflow).toBeLessThanOrEqual(0);

  await page.setViewportSize({ width: 390, height: 844 });
  const mobileGeometry = await registration.evaluate((element) => {
    const fields = [...element.querySelectorAll("label")].map((field) => field.getBoundingClientRect());
    const input = element.querySelector("input");
    const button = element.querySelector("button");
    if (fields.length === 0 || input === null || button === null) throw new Error("registration controls missing");
    return {
      oneColumn: fields.every((field) => Math.abs(field.width - fields[0]!.width) < 1)
        && fields.every((field, index) => index === 0 || field.top > fields[index - 1]!.top),
      inputHeight: input.getBoundingClientRect().height,
      buttonHeight: button.getBoundingClientRect().height,
      documentOverflow: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    };
  });
  expect(mobileGeometry.oneColumn).toBe(true);
  expect(mobileGeometry.inputHeight).toBeGreaterThanOrEqual(44);
  expect(mobileGeometry.buttonHeight).toBeGreaterThanOrEqual(44);
  expect(mobileGeometry.documentOverflow).toBeLessThanOrEqual(0);
});
