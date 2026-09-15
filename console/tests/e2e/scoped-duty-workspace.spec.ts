import { expect, test, type Page, type Route } from "@playwright/test";

const AT = Date.parse("2026-09-15T12:00:00Z");
const CASE = `operator-${"a".repeat(32)}`;
const SOURCE = `sha256:${"b".repeat(64)}`;

async function install(page: Page, owner = true) {
  await page.clock.setFixedTime(AT);
  const posts: { path: string; body: Record<string, unknown> }[] = [];
  let failFirst = true;
  const handler = async (route: Route) => {
    if (route.request().resourceType() === "document") {
      await route.continue();
      return;
    }
    const path = new URL(route.request().url()).pathname.replace(/^\/api/, "");
    if (path === "/iam") {
      await route.fulfill({ json: {
        principal: { oid: "owner-1", roles: [owner ? "Owner" : "Reader"],
          capabilities: owner ? ["view-console", "manage-group-membership"] : ["view-console"] },
        roles: [{ value: "Reader", capabilities: ["view-console"], routine_assignment: true },
          { value: "Owner", capabilities: ["view-console", "manage-group-membership"], routine_assignment: true }],
        assignment_boundary: "identity-provider-group",
        access_authority: { source: "server-verified", is_owner: owner, can_manage_group_membership: owner },
        directory: { source: "microsoft-graph", availability: "unavailable", observed_at: null, detail: null },
        workflow: { access_request_authority: "proposal_only", assignment_authority: "observation_only", provider_mutation: "promotion_required" },
      } });
    } else if (path === "/handover/scoped-duties/catalog") {
      await route.fulfill({ json: { source_revision: SOURCE, scopes: ["scope:example"],
        observed_at: "2026-09-15T11:59:45Z", expires_at: "2026-09-15T12:01:45Z",
        artifact_delivery_available: true, execution_authority: false } });
    } else if (path === "/handover/scoped-duty-cases" && route.request().method() === "POST") {
      posts.push({ path, body: route.request().postDataJSON() });
      if (failFirst) {
        failFirst = false;
        await route.fulfill({ status: 503, json: { error: "Synthetic response uncertainty" } });
      } else {
        await route.fulfill({ status: 202, json: { case_id: CASE, proposal_id: CASE,
          accepted_at: "2026-09-15T12:00:00Z", state: "awaiting_core", execution_authority: false } });
      }
    } else if (path === `/handover/scoped-duty-cases/${CASE}`) {
      await route.fulfill({ json: { case_id: CASE, revision: null, state: "awaiting_core",
        request: posts[0]?.body.request, execution_authority: false } });
    } else if (path === "/handover/scoped-duties") {
      await route.fulfill({ status: 503, json: { error: "Synthetic observation unavailable" } });
    } else {
      await route.fulfill({ status: 503, json: { error: "Synthetic unrelated source unavailable" } });
    }
  };
  await page.route("**/api/**", handler);
  await page.route("**/iam**", handler);
  await page.route("**/handover/**", handler);
  return posts;
}

test("scoped editor preserves uncertain creation and honest Core state across responsive layouts", async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const posts = await install(page);
  await page.goto("/agent-oversight/mapping-reviews");
  const panel = page.locator(".scoped-duty-workspace");
  await expect(panel.getByRole("heading", { name: "Scoped ownership", exact: true })).toBeVisible();
  await expect(panel.getByText("Ownership only.", { exact: false })).toBeVisible();
  await panel.locator("#scoped-binding-0-scope_ref").selectOption("scope:example");
  await panel.locator("#scoped-binding-0-subject_ref").fill("person:example-primary");
  await panel.locator("#scoped-binding-0-effective_from").fill("2026-09-15T11:00:00Z");
  await panel.locator("#scoped-binding-0-effective_until").fill("2026-09-16T12:00:00Z");
  await panel.getByRole("button", { name: "Add declaration", exact: true }).click();
  await panel.locator("#scoped-binding-1-scope_ref").selectOption("scope:example");
  await panel.locator("#scoped-binding-1-kind").selectOption("schedule");
  await expect(panel.locator("#scoped-binding-1-fallback")).toBeVisible();
  await panel.locator("#scoped-binding-1-subject_ref").fill("rotation:example-backup");
  await panel.locator("#scoped-binding-1-fallback").fill("person:example-fallback");
  await panel.locator("#scoped-binding-1-duty").selectOption("backup");
  await panel.locator("#scoped-binding-1-effective_from").fill("2026-09-15T11:00:00Z");
  await panel.locator("#scoped-binding-1-effective_until").fill("2026-09-16T12:00:00Z");
  await panel.locator("#scoped-justification").fill("Synthetic independent coverage review for the exact operating scope.");
  await panel.getByRole("button", { name: "Request draft", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(panel.getByRole("button", { name: "Retry unchanged creation", exact: true })).toBeVisible();
  await panel.getByRole("button", { name: "Retry unchanged creation", exact: true }).click();
  await expect(panel.getByRole("status").filter({ hasText: "Request accepted, awaiting Core." })).toBeVisible();
  expect(posts).toHaveLength(2);
  expect(posts[0]!.body).toEqual(posts[1]!.body);
  expect(Object.keys(posts[0]!.body)).not.toContain("roles");
  await panel.getByRole("button", { name: "Refresh case", exact: true }).click();
  await expect(panel.getByText("Core has not materialized this request.", { exact: false })).toBeVisible();
  await expect(panel.getByRole("button", { name: "Approve ownership plan", exact: true })).toHaveCount(0);
  await expect(page).toHaveURL(new RegExp(`scoped_case=${CASE}`));
  for (const viewport of [{ width: 1440, height: 900 }, { width: 993, height: 641 }, { width: 390, height: 844 }, { width: 320, height: 844 }]) {
    await page.setViewportSize(viewport);
    expect(await panel.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    await page.screenshot({ path: info.outputPath(`scoped-duty-${viewport.width}.png`), fullPage: true });
  }
  await page.addStyleTag({ content: `
    .scoped-duty-workspace { --cs-type-body-size: 28px; --cs-type-compact-size: 26px; --cs-type-section-title-size: 36px; --cs-type-panel-title-size: 30px; }
    .scoped-duty-workspace * { line-height: 1.5 !important; letter-spacing: .12em !important; word-spacing: .16em !important; }
    .scoped-duty-workspace p { margin-block-end: 2em !important; }
  ` });
  expect(await panel.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  await page.emulateMedia({ reducedMotion: "reduce", forcedColors: "active" });
  const refresh = panel.getByRole("button", { name: "Refresh catalog", exact: true });
  await refresh.focus();
  await expect(refresh).toBeFocused();
  expect(await refresh.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44);
});

test("Reader receives no scoped request or lookup controls", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const posts = await install(page, false);
  await page.goto("/agent-oversight/mapping-reviews");
  const panel = page.locator(".scoped-duty-workspace");
  await expect(panel.getByText("A server-confirmed Owner capability", { exact: false })).toBeVisible();
  await expect(panel.locator("input, select, textarea, button")).toHaveCount(0);
  expect(posts).toEqual([]);
});

function pendingCase() {
  const bindings = ["primary", "backup"].map((duty) => ({
    agent_name: "Odin", scope_ref: "scope:example", duty,
    subject: { kind: "user", ref: `person:example-${duty}` }, fallback: null,
    effective_from: "2026-09-15T11:00:00Z", effective_until: "2026-09-16T12:00:00Z",
  }));
  const request = { schema_version: "1.0.0", source_revision: SOURCE, bindings, supersedes_case_id: null };
  return {
    case_id: CASE, core_case_id: "00000000-0000-0000-0000-000000000011", state: "pending_review",
    revision: 2, requester_ref: "requester-1", request, reviews: [] as Record<string, unknown>[],
    pr_ref: null, candidate_digest: null, merge_commit_sha: null, execution_authority: false,
    plan: { kind: "scoped_duty_review", schema_version: "1.0.0", source_revision: SOURCE,
      input_digest: "c".repeat(64), digest: "d".repeat(64), resolution_at: "2026-09-15T11:59:45Z",
      checked_at: "2026-09-15T11:59:45Z", coverage_basis: "current_observation_only",
      current_coverage: true, review_required: true, execution_authority: false,
      policy: { max_resolution_age_microseconds: 300_000_000, read_timeout_seconds: 5, total_timeout_seconds: 120 },
      bindings: bindings.map((binding) => ({ binding, scope: { scope_ref: "scope:example", source_revision: SOURCE },
        resolution: { subject: binding.subject, people: [binding.subject], at: "2026-09-15T11:59:45Z",
          observed_at: "2026-09-15T11:59:45Z", valid_until: "2026-09-15T12:01:45Z", provenance_ref: "directory:synthetic",
          provenance_digest: "e".repeat(64), complete: true }, held_reason: null, schedule_failure: null,
        used_fallback: false, digest: "f".repeat(64) })),
      coverage: [{ agent_name: "Odin", scope_ref: "scope:example", primary_refs: ["person:example-primary"],
        backup_refs: ["person:example-backup"], escalation_refs: [], held_reasons: [] }],
    },
  };
}

test("independent review waits for authoritative refresh and prevents repeat approval", async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await install(page);
  const value = pendingCase();
  const commands: unknown[] = [];
  await page.route(`**/handover/scoped-duty-cases/${CASE}**`, async (route) => {
    if (route.request().method() === "POST") {
      commands.push(route.request().postDataJSON());
      await route.fulfill({ status: 202, json: { case_id: CASE, proposal_id: `operator-${"b".repeat(32)}`,
        accepted_at: "2026-09-15T12:00:00Z", state: "awaiting_core", execution_authority: false } });
    } else await route.fulfill({ json: value });
  });
  await page.goto(`/agent-oversight/mapping-reviews?scoped_case=${CASE}`);
  const panel = page.locator(".scoped-duty-workspace");
  await expect(panel.getByText("Pending independent review", { exact: true })).toBeVisible();
  await panel.getByText("Retained request and plan evidence", { exact: true }).click();
  await panel.getByRole("button", { name: "Approve ownership plan", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(panel.getByRole("button", { name: "Approve ownership plan", exact: true })).toBeDisabled();
  expect(commands).toEqual([{ expected_revision: 2, decision: "approve", plan_digest: "d".repeat(64) }]);
  await expect(panel.getByText("Pending independent review", { exact: true })).toBeVisible();
  value.revision = 3;
  value.reviews = [{ reviewer_ref: "owner-1", decision: "approve", plan_digest: "d".repeat(64), reviewed_at: "2026-09-15T12:00:00Z" }];
  await panel.getByRole("button", { name: "Refresh case", exact: true }).click();
  await expect(panel.getByText("Recorded independent reviews: 1 / 2", { exact: true })).toBeVisible();
  await expect(panel.getByRole("button", { name: "Approve ownership plan", exact: true })).toBeDisabled();
  await panel.getByRole("heading", { name: "Scoped ownership", exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("scoped-duty-desktop-top.png"), fullPage: true });
  await page.clock.setFixedTime(AT + 120_000);
  await page.evaluate(() => window.dispatchEvent(new Event("focus")));
  await expect(panel.getByText("This observation is no longer current.", { exact: false })).toBeVisible();
});

test("Korean scoped editor keeps explicit unavailable evidence readable at narrow width", async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await install(page);
  await page.goto("/agent-oversight/mapping-reviews?locale=ko");
  const panel = page.locator(".scoped-duty-workspace");
  await expect(panel.getByRole("heading", { name: "범위별 담당 체계", exact: true })).toBeVisible();
  await panel.locator("#scoped-observation-scope").selectOption("scope:example");
  await panel.getByRole("button", { name: "현재 관찰 읽기", exact: true }).click();
  await expect(panel.getByText("범위별 담당 원본 또는 요청 연결을 사용할 수 없습니다.", { exact: false })).toBeVisible();
  await page.setViewportSize({ width: 320, height: 844 });
  expect(await panel.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  await panel.getByRole("heading", { name: "범위별 담당 체계", exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("scoped-duty-korean-320.png"), fullPage: true });
});

test("account change discards the prior IAM capability before reading private scoped data", async ({ page }) => {
  await install(page);
  await page.goto("/agent-oversight/mapping-reviews");
  await expect(page.locator(".scoped-duty-workspace")).toBeVisible();
  await page.evaluate(async () => {
    const viewPath = "/src/routes/agent-oversight-views.tsx";
    const preactPath = "/node_modules/.vite/deps/preact.js";
    const [{ AgentOversightBody }, { h, render }] = await Promise.all([import(viewPath), import(preactPath)]);
    const host = document.createElement("div");
    host.id = "scoped-account-fence";
    document.body.append(host);
    const auth = { account: { homeAccountId: "first", localAccountId: "first" } };
    const overview = { principal: { oid: "first", capabilities: ["manage-group-membership"], roles: ["Owner"] } };
    const client = new Proxy({
      operatorApiBaseUrl: location.origin,
      authorizationHeader: async () => null,
      iamOverview: async () => auth.account.localAccountId === "first" ? overview : new Promise(() => {}),
    }, { get(target, key) { return key in target ? Reflect.get(target, key) : async () => { throw new Error("Synthetic unrelated read unavailable"); }; } });
    const draw = () => render(h(AgentOversightBody, { stewardshipState: { status: "idle" }, client, auth }), host);
    draw();
    Object.assign(window, { scopedAccountSwitch: () => {
      auth.account = { homeAccountId: "second", localAccountId: "second" };
      draw();
    } });
  });
  const host = page.locator("#scoped-account-fence");
  await expect(host.locator(".scoped-duty-workspace input").first()).toBeVisible();
  await page.evaluate(() => (window as unknown as { scopedAccountSwitch: () => void }).scopedAccountSwitch());
  await expect(host.locator(".scoped-duty-workspace input")).toHaveCount(0);
  await expect(host.locator('[role="status"][aria-busy="true"]')).toBeVisible();
});

test("first-frame loading, contrast, focus and touch targets remain measurable", async ({ page }, info) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await install(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/handover/scoped-duties/catalog", async (route) => {
    await gate;
    await route.fulfill({ json: { source_revision: SOURCE, scopes: ["scope:example"],
      observed_at: "2026-09-15T11:59:45Z", expires_at: "2026-09-15T12:01:45Z",
      artifact_delivery_available: true, execution_authority: false } });
  });
  await page.goto("/agent-oversight/mapping-reviews");
  const panel = page.locator(".scoped-duty-workspace");
  await expect(panel.locator('.loading-skeleton[role="status"][aria-busy="true"]')).toBeVisible();
  await expect(panel.locator('.loading-skeleton-layout[aria-hidden="true"]')).toBeVisible();
  release();
  await expect(panel.locator(".loading-skeleton")).toHaveCount(0);
  for (const theme of ["light", "dark"]) {
    await page.evaluate((value) => document.documentElement.setAttribute("data-theme", value), theme);
    const measurements = await panel.evaluate((root) => {
      const rgba = (value: string) => value.match(/[\d.]+/g)!.map(Number);
      const light = (rgb: number[]) => {
        const v = rgb.slice(0, 3).map((channel) => channel / 255 <= .04045 ? channel / 255 / 12.92 : ((channel / 255 + .055) / 1.055) ** 2.4);
        return v[0]! * .2126 + v[1]! * .7152 + v[2]! * .0722;
      };
      const background = (element: Element) => {
        const ancestors: Element[] = [];
        for (let e: Element | null = element; e; e = e.parentElement) ancestors.unshift(e);
        let result = [255, 255, 255];
        for (const e of ancestors) {
          const color = rgba(getComputedStyle(e).backgroundColor), alpha = color[3] ?? 1;
          result = result.map((v, i) => color[i]! * alpha + v * (1 - alpha));
        }
        return result;
      };
      const ratio = (a: number[], b: number[]) => (Math.max(light(a), light(b)) + .05) / (Math.min(light(a), light(b)) + .05);
      return [...root.querySelectorAll("h3,h4,p,dt,dd,legend,code,.cs-control-label,.cs-control-help,button,input,select,textarea")]
        .filter((e) => e.checkVisibility() && !e.matches(":disabled") && !e.classList.contains("sr-only"))
        .map((e) => {
          const style = getComputedStyle(e), rect = e.getBoundingClientRect();
          const control = e.matches("button,input,select,textarea");
          return { tag: e.tagName, control, text: ratio(rgba(style.color), background(e)),
            border: control ? ratio(rgba(style.borderTopColor), background(e.parentElement!)) : null,
            width: rect.width, height: rect.height };
        });
    });
    await info.attach(`scoped-measurements-${theme}.json`, { body: JSON.stringify(measurements), contentType: "application/json" });
    expect(measurements.filter((m) => m.text < 4.5)).toEqual([]);
    expect(measurements.filter((m) => m.control && (m.height < 44 || m.width < 44))).toEqual([]);
    expect(measurements.filter((m) => m.control && m.border! < 3)).toEqual([]);
    const refresh = panel.getByRole("button", { name: "Refresh catalog", exact: true });
    await refresh.focus();
    await expect(refresh).toBeFocused();
    expect(await refresh.evaluate((e) => getComputedStyle(e).outlineStyle)).toBe("solid");
  }
  await page.evaluate(() => document.documentElement.setAttribute("data-theme", "light"));
  await panel.getByRole("heading", { name: "Scoped ownership", exact: true }).scrollIntoViewIfNeeded();
  await page.screenshot({ path: info.outputPath("scoped-default-desktop.png") });
});
