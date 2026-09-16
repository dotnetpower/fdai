import { expect, test, type Page, type Route } from "@playwright/test";

const observedAt = "2026-09-15T12:00:00Z";

interface FixtureOptions {
  readonly empty?: boolean;
  readonly failNextPage?: boolean;
  readonly initialGate?: Promise<void>;
  readonly malformed?: boolean;
  readonly unavailable?: boolean;
}

interface FixtureItem extends Record<string, unknown> {
  readonly artifact_id: string;
  readonly policy_id: string;
  readonly source_host: string;
  readonly final_host: string;
  readonly captured_at: string;
  readonly prompt_injection_finding_count: number;
  readonly retention_state: string;
}

test.describe.configure({ mode: "serial" });

test("renders the payload-free investigation hierarchy and exact provenance", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "desktop-chromium",
    "Desktop presentation must pass before responsive checks.",
  );
  const requests = await installFixtures(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/browser-evidence");

  await expect(page.locator(".browser-evidence-workbench")).toBeVisible();
  await expect(page.locator(".browser-evidence-page .kpi-card")).toHaveCount(5);
  await expect(page.locator(".browser-evidence-record")).toHaveCount(5);
  await expect(page.locator(".browser-evidence-record[aria-pressed=true]")).toHaveCount(1);
  await expect(page.getByLabel("Exact host")).toHaveValue("");
  await expect(page.locator(".browser-evidence-security")).toContainText(
    "Security review required",
  );
  await expect(page.getByText("Screenshot digest")).toBeVisible();
  await expect(page.getByText("Visible-text digest")).toBeVisible();
  await expect(page.getByText("Accessibility-snapshot digest")).toBeVisible();
  await expect(page.getByText("chromium-140.0")).toBeVisible();
  await expect(page.getByText("dashboard.example").first()).toBeVisible();
  await expect(page.getByText("status.example").first()).toBeVisible();
  await expect(page.getByText("Redirect admitted by policy")).toBeVisible();
  await expect(page.getByRole("link", { name: "Open exact audit record" }))
    .toHaveAttribute("href", "/audit?entry=42");
  await expect(page.getByRole("link", { name: "Open correlated trace" }))
    .toHaveAttribute("href", "/trace?correlation=correlation-1");
  await expect(page.locator("#browser-evidence-withheld")).toContainText(
    "2 withheld",
  );
  await expect(page.locator("#browser-evidence-withheld")).not.toContainText(
    "sha256:",
  );
  await expectNoHorizontalOverflow(page);
  const contrast = await evidenceContrastRatios(page);
  expect(contrast.every((ratio) => ratio >= 4.5)).toBe(true);
  expect(requests.some((url) => new URL(url).pathname.endsWith("/browser-evidence"))).toBe(false);
  await page.locator("main").screenshot({
    path: testInfo.outputPath("browser-evidence-desktop-1440x900.png"),
  });

  const held = page.getByRole("button", { name: /hold\.example/ });
  await held.focus();
  await expect(held).toBeFocused();
  const focus = await held.evaluate((element) => {
    const style = getComputedStyle(element);
    return { style: style.outlineStyle, width: Number.parseFloat(style.outlineWidth) };
  });
  expect(focus.style).not.toBe("none");
  expect(focus.width).toBeGreaterThanOrEqual(2);
  await held.press("Enter");
  await expect(page.locator("#browser-evidence-selected")).toContainText("legal-case:example");
  await expect(page.locator("#browser-evidence-selected")).toContainText("Legal hold");
  await expect(page.getByRole("link", { name: "Open exact artifact" })).toHaveAttribute(
    "href",
    new RegExp(`artifact=sha256%3A[0-9a-f]{64}`),
  );

  const more = page.locator(".browser-evidence-advanced summary");
  await more.focus();
  await expect(more).toBeFocused();
  await more.press("Enter");
  await expect(page.locator(".browser-evidence-advanced")).toHaveAttribute("open", "");
  await page.getByLabel("Policy id").fill("dashboard");
  await page.getByRole("button", { name: "Apply filters" }).click();
  await expect(page).toHaveURL(/policy=dashboard/);
  await expect(page.locator(".browser-evidence-record")).toHaveCount(1);
});

test("keeps empty, no-match, and load-more failure states distinct", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "desktop-chromium",
    "State behavior runs once on the accepted desktop composition.",
  );
  await installFixtures(page, { failNextPage: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/browser-evidence?policy=page-test");
  await expect(page.locator(".browser-evidence-record")).toHaveCount(25);
  await page.getByRole("button", { name: "Load more" }).click();
  await expect(page.locator(".browser-evidence-page-actions [role=alert]")).toContainText(
    "HTTP 503",
  );
  await expect(page.locator(".browser-evidence-record")).toHaveCount(25);
  await page.getByRole("button", { name: "Load more" }).click();
  await expect(page.locator(".browser-evidence-record")).toHaveCount(26);
  await expect(page.getByText("All currently matching admitted records are loaded."))
    .toBeVisible();

  await page.goto("/browser-evidence?host=missing.example");
  await expect(page.getByText("No admitted records match these filters")).toBeVisible();
  await expect(page.getByText("No admitted Browser evidence")).toHaveCount(0);

  await page.unroute("**/browser-evidence/snapshot*");
  await installFixtures(page, { empty: true });
  await page.goto("/browser-evidence");
  await expect(page.getByText("No admitted Browser evidence")).toBeVisible();
  await expect(page.locator(".browser-evidence-page .kpi-card").first())
    .toHaveAttribute("href", "#browser-evidence-withheld");
  await expect(page.locator("#browser-evidence-withheld")).toContainText("2 withheld");
  await expect(page.locator(".state-error")).toHaveCount(0);

  await page.screenshot({
    path: testInfo.outputPath("browser-evidence-empty-desktop.png"),
    fullPage: true,
  });
});

test("distinguishes loading, unavailable, and malformed workspace states", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "desktop-chromium",
    "Async state behavior runs once on desktop.",
  );
  let release = (): void => undefined;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await installFixtures(page, { initialGate: gate });
  await page.goto("/browser-evidence");
  await expect(page.locator(".browser-evidence-skeleton")).toBeVisible();
  release();
  await expect(page.locator(".browser-evidence-workbench")).toBeVisible();

  await page.unroute("**/browser-evidence/snapshot*");
  await installFixtures(page, { unavailable: true });
  await page.reload();
  await expect(page.getByText(
    "The versioned authoritative Browser evidence workspace is unavailable.",
  )).toBeVisible();
  await expect(page.getByText("No admitted Browser evidence")).toHaveCount(0);

  await page.unroute("**/browser-evidence/snapshot*");
  await installFixtures(page, { malformed: true });
  await page.reload();
  await expect(page.locator(".state-error")).toContainText(
    "invalid Operator API response",
  );
  await expect(page.getByText("No admitted Browser evidence")).toHaveCount(0);
});

test("reflows the accepted workspace and preserves adaptive preferences", async ({
  page,
}, testInfo) => {
  test.skip(
    testInfo.project.name !== "desktop-chromium",
    "Responsive checks run after desktop acceptance.",
  );
  await installFixtures(page);

  await page.setViewportSize({ width: 993, height: 641 });
  await page.goto("/browser-evidence");
  await expect(page.locator(".browser-evidence-workbench")).toBeVisible();
  await expectNoHorizontalOverflow(page);

  await page.setViewportSize({ width: 390, height: 844 });
  await expectNoHorizontalOverflow(page);
  expect(await gridColumnCount(page, ".browser-evidence-workbench")).toBe(1);
  await expectTouchTargets(
    page,
    ".browser-evidence-record, .browser-evidence-filters :is(input, select, button), "
      + ".browser-evidence-advanced summary, .browser-evidence-identity .btn",
  );

  await page.setViewportSize({ width: 320, height: 720 });
  await expectNoHorizontalOverflow(page);
  await page.addStyleTag({
    content: `
      .browser-evidence-page { letter-spacing: .12em !important; word-spacing: .16em !important; }
      .browser-evidence-page p { line-height: 1.5 !important; margin-bottom: 2em !important; }
    `,
  });
  await expectNoHorizontalOverflow(page);

  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => {
    localStorage.setItem("fdai:console:locale", "ko");
    localStorage.setItem("fdai:console:theme", "dark");
  });
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.getByText("보안 검토 필요")).toBeVisible();
  await expect(page.getByText("보류된 허용 요약")).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await page.locator("main").evaluate((element) => element.scrollTo(0, 0));
  await expect.poll(() => page.locator("main").evaluate((element) => element.scrollTop)).toBe(0);
  await page.locator("main").screenshot({
    path: testInfo.outputPath("browser-evidence-mobile-390x844-ko.png"),
  });

  await page.emulateMedia({ reducedMotion: "reduce" });
  const transitions = await page.locator(".browser-evidence-record").first().evaluate(
    (element) => getComputedStyle(element).transitionDuration.split(",").map((value) =>
      value.trim().endsWith("ms")
        ? Number.parseFloat(value) / 1000
        : Number.parseFloat(value)),
  );
  expect(transitions.every((value) => value <= 0.00001)).toBe(true);
  await page.emulateMedia({ forcedColors: "active", reducedMotion: "reduce" });
  await page.locator(".browser-evidence-record").first().focus();
  await expect(page.locator(".browser-evidence-record").first()).toBeFocused();
});

async function installFixtures(
  page: Page,
  options: FixtureOptions = {},
): Promise<string[]> {
  const requests: string[] = [];
  let nextPageAttempts = 0;
  await page.route("**/system/data-sources*", (route) => fulfill(route, {
    surface: "read-data-sources",
    sources: [{
      key: "operational-state",
      source: "postgresql",
      routes: ["/browser-evidence"],
      availability: "available",
      configured: true,
      reachable: true,
      authoritative: true,
      durable: true,
      synthetic: false,
      reason: null,
      last_observed_at: observedAt,
    }],
  }));
  await page.route("**/browser-evidence/snapshot*", async (route) => {
    requests.push(route.request().url());
    await options.initialGate;
    if (options.unavailable) {
      return fulfill(route, {
        error: {
          status: 503,
          message: "authoritative Operator projection is unavailable",
        },
      }, 503);
    }
    const url = new URL(route.request().url());
    if (options.empty) {
      return fulfill(route, workspaceResponse([], {
        snapshotTotal: 2,
        snapshotAdmitted: 0,
        snapshotWithheld: 2,
      }));
    }
    const policy = url.searchParams.get("policy");
    if (policy === "page-test") {
      const records = Array.from({ length: 26 }, (_, index) => retainedItem(index));
      const cursor = url.searchParams.get("cursor");
      if (cursor) {
        nextPageAttempts += 1;
        if (options.failNextPage && nextPageAttempts === 1) {
          return fulfill(route, { error: { status: 503, message: "HTTP 503" } }, 503);
        }
        return fulfill(route, workspaceResponse(records.slice(25), {
          snapshotTotal: 28,
          snapshotAdmitted: 26,
          snapshotWithheld: 2,
          matching: 26,
          summary: {
            security_finding_count: 0,
            legal_hold_count: 0,
            expiring_count: 0,
            expired_pending_purge_count: 0,
            retained_count: 26,
          },
        }));
      }
      return fulfill(route, workspaceResponse(records.slice(0, 25), {
        snapshotTotal: 28,
        snapshotAdmitted: 26,
        snapshotWithheld: 2,
        matching: 26,
        hasMore: true,
        nextCursor: "cursor-one",
        summary: {
          security_finding_count: 0,
          legal_hold_count: 0,
          expiring_count: 0,
          expired_pending_purge_count: 0,
          retained_count: 26,
        },
      }));
    }
    let items = defaultItems();
    const artifact = url.searchParams.get("artifact");
    const host = url.searchParams.get("host");
    const hostScope = url.searchParams.get("host_scope") ?? "either";
    const retention = url.searchParams.get("retention");
    const finding = url.searchParams.get("finding");
    if (artifact) items = items.filter((item) => item.artifact_id === artifact);
    if (host) {
      items = items.filter((item) =>
        (hostScope !== "final" && item.source_host === host)
        || (hostScope !== "requested" && item.final_host === host));
    }
    if (retention) items = items.filter((item) => item.retention_state === retention);
    if (finding === "present") {
      items = items.filter((item) => item.prompt_injection_finding_count > 0);
    }
    if (finding === "clear") {
      items = items.filter((item) => item.prompt_injection_finding_count === 0);
    }
    if (policy) items = items.filter((item) => item.policy_id === policy);
    if (url.searchParams.get("sort") === "newest") {
      items = [...items].sort((left, right) =>
        right.captured_at.localeCompare(left.captured_at)
        || right.artifact_id.localeCompare(left.artifact_id));
    }
    const payload = workspaceResponse(items, {
      matching: items.length,
      summary: summaryFor(items),
    });
    return fulfill(route, options.malformed ? { ...payload, unexpected: true } : payload);
  });
  return requests;
}

function workspaceResponse(
  items: readonly FixtureItem[],
  options: {
    readonly snapshotTotal?: number;
    readonly snapshotAdmitted?: number;
    readonly snapshotWithheld?: number;
    readonly matching?: number;
    readonly hasMore?: boolean;
    readonly nextCursor?: string | null;
    readonly summary?: ReturnType<typeof summaryFor>;
  } = {},
) {
  const hasMore = options.hasMore ?? false;
  return {
    schema_version: "2.0.0",
    surface: "browser-evidence-workspace",
    consistency: "drift_aware",
    summary_scope: "filtered_and_snapshot",
    observed_at: observedAt,
    source_observed_at: "2026-09-15T11:59:00Z",
    loaded_count: items.length,
    matching_admitted_count: options.matching ?? items.length,
    snapshot_total_count: options.snapshotTotal ?? 7,
    snapshot_admitted_count: options.snapshotAdmitted ?? 5,
    snapshot_withheld_count: options.snapshotWithheld ?? 2,
    withheld_reasons: {
      invalid_metadata: 1,
      trust_invalid: 0,
      isolation_unverified: 1,
    },
    summary: options.summary ?? summaryFor(items),
    has_more: hasMore,
    next_cursor: options.nextCursor ?? null,
    page_complete: !hasMore,
    items,
  };
}

function summaryFor(items: readonly FixtureItem[]) {
  return {
    security_finding_count: items.reduce(
      (total, item) => total + Number(item["prompt_injection_finding_count"]),
      0,
    ),
    legal_hold_count: items.filter((item) => item["retention_state"] === "held").length,
    expiring_count: items.filter((item) => item["retention_state"] === "expiring").length,
    expired_pending_purge_count: items.filter(
      (item) => item["retention_state"] === "expired_pending_purge",
    ).length,
    retained_count: items.filter((item) => item["retention_state"] === "retained").length,
  };
}

function defaultItems(): FixtureItem[] {
  return [
    artifact(0, {
      source_host: "dashboard.example",
      final_host: "status.example",
      redirected: true,
      prompt_injection_finding_count: 2,
      audit: { state: "exact", sequence: "42", correlation_id: "correlation-1" },
      browser_version: "chromium-140.0",
    }),
    artifact(1, {
      source_host: "expired.example",
      final_host: "expired.example",
      captured_at: "2026-09-14T10:00:00Z",
      expires_at: "2026-09-15T11:00:00Z",
      retention_state: "expired_pending_purge",
      audit: { state: "ambiguous", sequence: null, correlation_id: null },
    }),
    artifact(2, {
      source_host: "expiring.example",
      final_host: "expiring.example",
      expires_at: "2026-09-18T12:00:00Z",
      retention_state: "expiring",
    }),
    artifact(3, {
      source_host: "hold.example",
      final_host: "hold.example",
      retention_state: "held",
      legal_hold: true,
      legal_hold_ref: "legal-case:example",
      legal_hold_at: "2026-09-15T10:00:00Z",
    }),
    artifact(4, {
      source_host: "retained.example",
      final_host: "retained.example",
    }),
  ];
}

function retainedItem(index: number): FixtureItem {
  const digest = index.toString(16).padStart(64, "0");
  return artifact(index, {
    artifact_id: `sha256:${digest}`,
    source_host: `page-${index}.example`,
    final_host: `page-${index}.example`,
    policy_id: "page-test",
    captured_at: new Date(Date.parse(observedAt) - index * 60_000).toISOString(),
  });
}

function artifact(index: number, overrides: Partial<FixtureItem> = {}): FixtureItem {
  const digest = (index + 1).toString(16).padStart(64, "0");
  return {
    artifact_id: `sha256:${digest}`,
    policy_id: index === 0 ? "dashboard" : "evidence",
    policy_version: 4,
    source_host: "dashboard.example",
    final_host: "dashboard.example",
    redirected: false,
    captured_at: new Date(Date.parse(observedAt) - (index + 1) * 60_000).toISOString(),
    expires_at: "2026-10-15T12:00:00Z",
    selector_count: 18,
    redaction_count: 7,
    prompt_injection_finding_count: 0,
    digest_presence: {
      screenshot: true,
      text: true,
      accessibility_snapshot: false,
    },
    browser_version: "chromium-test",
    custody_audit_ref: `00000000-0000-4000-8000-${(index + 1).toString().padStart(12, "0")}`,
    retention_state: "retained",
    legal_hold: false,
    legal_hold_ref: null,
    legal_hold_at: null,
    audit: { state: "missing", sequence: null, correlation_id: null },
    isolation_verified: true,
    untrusted: true,
    can_authorize_action: false,
    ...overrides,
  };
}

async function fulfill(route: Route, payload: unknown, status = 200): Promise<void> {
  await route.fulfill({
    status,
    contentType: "application/json",
    body: JSON.stringify(payload),
  });
}

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  const geometry = await page.evaluate(() => {
    const main = document.querySelector("main");
    return {
      document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
      main: main ? main.scrollWidth - main.clientWidth : -1,
    };
  });
  expect(geometry).toEqual({ document: 0, main: 0 });
}

async function gridColumnCount(page: Page, selector: string): Promise<number> {
  return await page.locator(selector).evaluate(
    (element) => getComputedStyle(element).gridTemplateColumns.split(" ").length,
  );
}

async function expectTouchTargets(page: Page, selector: string): Promise<void> {
  const targets = await page.locator(selector).evaluateAll((elements) =>
    elements
      .filter((element) => !element.hasAttribute("disabled"))
      .map((element) => {
        const rect = element.getBoundingClientRect();
        return { width: rect.width, height: rect.height };
      }));
  expect(targets.length).toBeGreaterThan(0);
  expect(targets.every(({ width, height }) => width >= 44 && height >= 44)).toBe(true);
}

async function evidenceContrastRatios(page: Page): Promise<number[]> {
  return await page.locator(".browser-evidence-page").evaluate((element) => {
    const style = getComputedStyle(element);
    const background = style.getPropertyValue("--cs-card").trim();
    const colors = [
      style.getPropertyValue("--cs-text-soft").trim(),
      style.getPropertyValue("--browser-evidence-success").trim(),
      style.getPropertyValue("--browser-evidence-warning").trim(),
      style.getPropertyValue("--browser-evidence-danger").trim(),
    ];
    const channels = (value: string): [number, number, number] => {
      if (/^#[0-9a-f]{6}$/i.test(value)) {
        return [
          Number.parseInt(value.slice(1, 3), 16),
          Number.parseInt(value.slice(3, 5), 16),
          Number.parseInt(value.slice(5, 7), 16),
        ];
      }
      const match = value.match(/^rgba?\(\s*([\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)/i);
      if (!match) throw new Error(`Unsupported color: ${value}`);
      return [
        Number.parseFloat(match[1] ?? "0"),
        Number.parseFloat(match[2] ?? "0"),
        Number.parseFloat(match[3] ?? "0"),
      ];
    };
    const luminance = (value: string): number => {
      const values = channels(value).map((channel) => {
        const normalized = channel / 255;
        return normalized <= 0.04045
          ? normalized / 12.92
          : ((normalized + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * (values[0] ?? 0)
        + 0.7152 * (values[1] ?? 0)
        + 0.0722 * (values[2] ?? 0);
    };
    const backgroundLuminance = luminance(background);
    return colors.map((color) => {
      const foregroundLuminance = luminance(color);
      return (
        Math.max(backgroundLuminance, foregroundLuminance) + 0.05
      ) / (
        Math.min(backgroundLuminance, foregroundLuminance) + 0.05
      );
    });
  });
}
