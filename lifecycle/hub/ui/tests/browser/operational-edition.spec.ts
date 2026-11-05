import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const dist = resolve("../../release-hub/ui/dist");
const origin = "https://hub.test";

function release(id: string, state: "draft" | "published", channels: string[], label: string) {
  return {
    id, state, channels, label, manifest: JSON.stringify({ product: "FDAI", source_commit: "a".repeat(40) }),
    digest: "a".repeat(64), signed_payload_sha256: "b".repeat(64),
    signature: state === "draft" ? null : "development-signature",
    signature_status: state === "draft" ? "unsigned" : "development-key-verified",
    published_at: state === "draft" ? null : "2026-11-01T00:00:00Z", recalled_at: null,
  };
}

const catalog = {
  revision: 3, updated_at: "2026-11-01T00:00:00Z", expires_at: "2026-11-06T00:00:00Z",
  expired: false, key_id: "example-development-key", mode: "local-development",
  releases: [
    release("0.5.1", "published", ["DEV", "RELEASE"], "Lite Observe"),
    release("0.5.2", "published", ["DEV", "RELEASE_CANDIDATE"], "Standard SRE"),
    release("0.5.3", "draft", [], "Full Enterprise"),
  ],
  channels: { DEV: ["0.5.1", "0.5.2"], RELEASE_CANDIDATE: ["0.5.2"], RELEASE: ["0.5.1"] },
  events: [],
};

const composed = {
  stencil: {
    schema_version: "fdai.stencil.v1", stencil_id: "lite-observe-alert",
    title: "Lite", title_ko: "경량", description: "", description_ko: "",
    topology_profile: "lite-observe-alert", authority_granted: false,
    enabled_workloads: ["core-control-plane"], enabled_panel_ids: ["dashboard"],
    enabled_scheduled_jobs: [], enabled_loops: [], enabled_addons: [],
  },
  footprint: {
    stencil_digest: "sha256:" + "a".repeat(64), azure_rbac_posture: "read-only-observation",
    console_build_command: "npm run build", includes_clamav_sidecar: false,
    workload_count: 1, total_workloads: 1, enabled_panel_count: 1, total_panel_count: 1,
    omitted_workloads: [], required_azure_roles: ["Reader"],
  },
  release_manifest: { product: "FDAI", release_version: "0.5.4", source_commit: "a".repeat(40) },
};

async function serveAuthenticatedBuild(page: Page, data = catalog) {
  const unexpected: string[] = [];
  await page.route("**/*", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.origin !== origin || request.method() !== "GET") {
      unexpected.push(`${request.method()} ${url.pathname}`);
      return route.abort();
    }
    if (url.pathname === "/auth/config") {
      return route.fulfill({ json: { profile: "local-development" } });
    }
    if (url.pathname === "/v1/catalog") return route.fulfill({ json: data });
    if (url.pathname === "/v1/stencils") {
      return route.fulfill({ json: {
        presets: [], panels: [], workloads: [], locked_workloads: [],
        scheduled_jobs: [], locked_scheduled_jobs: [], loops: [], locked_loops: [],
        addons: [], locked_addons: [], locked_panels: [],
      } });
    }
    if (url.pathname === "/v1/deployment-requests") {
      return route.fulfill({ json: {
        requests: [{
          request_id: "a".repeat(64), subscription_id: "00000000-0000-0000-0000-000000000001",
          release_id: "0.5.2", channel: "RELEASE_CANDIDATE", region: "example-region",
          source_commit: "b".repeat(40), catalog_digest: "c".repeat(64),
          recorded_at: "2026-11-05T00:00:00Z", status: "requested", trust: "self-reported",
        }], limit: 25, offset: 0, has_more: false,
      } });
    }
    if (url.pathname === "/v1/auth/session") {
      return route.fulfill({ json: { authenticated: false, session: null, detected_accounts: [] } });
    }
    if (/^\/(v1|auth|healthz|readyz)(\/|$)/.test(url.pathname)) {
      unexpected.push(`${request.method()} ${url.pathname}`);
      return route.abort();
    }
    const path = url.pathname.startsWith("/assets/") || url.pathname.startsWith("/brand/") ? url.pathname : "/index.html";
    const contentType = path.endsWith(".js") ? "text/javascript" : path.endsWith(".css") ? "text/css"
      : path.endsWith(".png") ? "image/png" : path.endsWith(".svg") ? "image/svg+xml" : "text/html";
    return route.fulfill({ body: await readFile(resolve(dist, `.${path}`)), contentType });
  });
  return unexpected;
}

test("authenticated Edition reads live catalog and keeps original workspaces intact", async ({ page }) => {
  const unexpected = await serveAuthenticatedBuild(page);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(`${origin}/#/edition`);
  await expect(page.getByRole("heading", { name: "Releases", exact: true })).toBeVisible();
  await page.locator(".workspace-bar select").selectOption("ko");
  const sidebar = page.getByRole("navigation", { name: "Release Hub" });
  await expect(sidebar.locator("a.nav-link")).toHaveCount(3);
  await expect(sidebar.getByRole("link", { name: "릴리스 계통" })).toHaveAttribute("aria-current", "page");
  expect(await page.evaluate(() => ({
    sidebar: getComputedStyle(document.querySelector(".side")!).backgroundColor,
    body: getComputedStyle(document.body).backgroundColor,
    active: getComputedStyle(document.querySelector(".nav-link.current")!).backgroundColor,
    top: getComputedStyle(document.querySelector(".workspace-bar")!).backgroundColor,
  }))).toEqual({
    sidebar: "rgb(255, 255, 255)", body: "rgb(255, 255, 255)",
    active: "rgba(0, 0, 0, 0)", top: "rgba(0, 0, 0, 0)",
  });
  await expect(page.locator(".rh-edition-nav")).toHaveCount(0);
  const canvas = page.getByRole("region", { name: "릴리스 계통 캔버스, 가로 스크롤 가능" });
  await expect(canvas.locator(".rh-edition-node")).toHaveCount(3);
  await expect(canvas.locator("svg g")).toHaveCount(2);
  await expect(canvas.locator(".rh-edition-node").first()).toHaveAttribute("href", "#/edition/releases/0.5.1");
  await expect(page.getByRole("region", { name: "릴리스 목록 표" }).locator("tbody tr")).toHaveCount(3);
  const draft = canvas.getByRole("link", { name: /릴리스 0\.5\.3, DRAFT/ });
  await draft.focus();
  await page.keyboard.press("Home");
  await expect(canvas.getByRole("link", { name: /릴리스 0\.5\.1, RELEASE/ })).toBeFocused();
  await page.keyboard.press("End");
  await expect(draft).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(`${origin}/#/edition/releases/0.5.3`);
  await expect(page.locator(".rh-edition-workspace .rh-lineage-card")).toHaveCount(5);
  await page.goBack();
  await expect(page).toHaveURL(`${origin}/#/edition/selected/0.5.3`);
  await expect(draft).toBeFocused();
  await draft.press("Enter");
  await expect(page).toHaveURL(`${origin}/#/edition/releases/0.5.3`);
  await page.getByRole("link", { name: "← Edition" }).click();
  await expect(page).toHaveURL(`${origin}/#/edition/selected/0.5.3`);
  await expect(draft).toBeFocused();
  await expect(draft).toHaveAttribute("aria-current", "true");
  await sidebar.getByRole("link", { name: "릴리스 계통" }).click();
  await expect(page).toHaveURL(`${origin}/#/edition`);
  await expect(canvas.locator('.rh-edition-node[aria-current="true"]')).toHaveCount(0);
  const releaseLink = page.getByRole("region", { name: "릴리스 목록 표" }).getByRole("link", { name: "v0.5.2" });
  await releaseLink.click();
  await expect(page).toHaveURL(`${origin}/#/edition/releases/0.5.2`);
  await expect(page.getByRole("heading", { name: /FDAI 0\.5\.2/ })).toBeVisible();
  await expect(page.locator(".rh-edition-workspace .rh-workspace-pipeline-section")).toBeVisible();
  const stageGraph = page.getByRole("region", { name: "릴리스 버전 계통 그래프 (좌우 화살표 키로 이동)" });
  const rcStage = stageGraph.getByRole("button", { name: /^4\. RC 카나리,/ });
  const releaseStage = stageGraph.getByRole("button", { name: /^5\. 운영 RELEASE,/ });
  await rcStage.focus();
  await page.keyboard.press("ArrowRight");
  await expect(releaseStage).toBeFocused();
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  expect(unexpected).toEqual([]);
  await releaseStage.click();
  const evidence = page.locator("details.release-disclosure").filter({
    has: page.getByText("승격 근거 및 차단 이유", { exact: true }),
  });
  await expect(evidence).toHaveAttribute("open", "");
  await expect(evidence.locator("summary")).toBeFocused();
  await expect(evidence.getByText("독립적인 게이트 관찰 근거가 제공되지 않음")).toHaveCount(2);
  await expect(evidence.getByText("검증 레이블 0개 충족")).toHaveCount(0);
  expect(unexpected).toEqual([]);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await stageGraph.getByRole("button", { name: /^2\. 소스·다이제스트,/ }).click();
  await expect(page.locator("details.release-disclosure").filter({
    has: page.getByText("기술 세부 정보 및 고급 작업", { exact: true }),
  })).toHaveAttribute("open", "");
  const topologyChrome = await page.locator(".rh-edition-workspace .rh-lineage-card").first().evaluate((element) => {
    const style = getComputedStyle(element);
    return {
      left: style.borderLeftColor, right: style.borderRightColor,
      leftWidth: style.borderLeftWidth, rightWidth: style.borderRightWidth,
      canvasPattern: getComputedStyle(document.querySelector(".rh-edition-workspace .rh-lineage-scroll")!).backgroundImage,
      canvasColor: getComputedStyle(document.querySelector(".rh-edition-workspace .rh-lineage-scroll")!).backgroundColor,
      panelRadius: getComputedStyle(document.querySelector(".rh-edition-workspace .rh-workspace-pipeline-section")!).borderRadius,
      panelPadding: getComputedStyle(document.querySelector(".rh-edition-workspace .rh-workspace-pipeline-section")!).paddingTop,
    };
  });
  expect(topologyChrome.left).toBe(topologyChrome.right);
  expect(topologyChrome.leftWidth).toBe(topologyChrome.rightWidth);
  expect(topologyChrome.canvasPattern).toContain("radial-gradient");
  expect(topologyChrome.canvasColor).toBe("rgb(243, 241, 234)");
  expect(topologyChrome.panelRadius).toBe("8px");
  expect(topologyChrome.panelPadding).toBe("0px");
  expect(await page.locator(".rh-edition-workspace .rh-lineage-card").first().evaluate((element) => ({
    layout: getComputedStyle(element).display,
    dividers: [...element.querySelectorAll(".rh-lineage-card-bottom, .rh-lineage-card-action")]
      .map((part) => getComputedStyle(part).borderTopWidth),
  }))).toEqual({ layout: "flex", dividers: ["0px", "0px"] });
  const editorialCard = await page.locator(".rh-edition-workspace .rh-lineage-card.status-complete").first()
    .evaluate((element) => ({
      radius: getComputedStyle(element).borderRadius,
      shadow: getComputedStyle(element).boxShadow,
      titleSize: getComputedStyle(element.querySelector(".rh-node-title")!).fontSize,
      badgeBorder: getComputedStyle(element.closest(".rh-lineage-node-wrap")!.querySelector(".rh-lineage-badge")!).borderWidth,
    }));
  expect(editorialCard.radius).toBe("11px");
  expect(editorialCard.shadow).not.toBe("none");
  expect(editorialCard.titleSize).toBe("13px");
  expect(editorialCard.badgeBorder).toBe("0px");
  expect(await page.locator(".rh-edition-workspace .rh-lineage-badge.status-complete").first()
    .evaluate((element) => getComputedStyle(element).color)).toBe("rgb(74, 105, 103)");
  await page.emulateMedia({ reducedMotion: "reduce" });
  expect(await page.locator(".rh-edition-workspace .rh-lineage-card.status-complete").first()
    .evaluate((element) => getComputedStyle(element).transitionDuration)).toBe("0s");
  await page.emulateMedia({ reducedMotion: "no-preference" });
  expect(await page.locator(".rh-edition-workspace .rh-node-cta").first().evaluate((element) =>
    element.getBoundingClientRect().bottom <= element.closest(".rh-lineage-card")!.getBoundingClientRect().bottom,
  )).toBe(true);
  expect(await page.locator(".rh-edition-workspace .rh-lineage-card.status-complete .rh-lineage-card-action").first()
    .evaluate((element) => getComputedStyle(element).display)).toBe("none");
  expect(await page.locator(".rh-edition-workspace .rh-lineage-card.status-pending .rh-lineage-card-action").first()
    .evaluate((element) => getComputedStyle(element).display)).not.toBe("none");
  expect(await page.locator(".rh-edition-workspace .rh-lineage-badge.status-complete").first()
    .evaluate((element) => getComputedStyle(element).backgroundColor)).toBe("rgba(0, 0, 0, 0)");
  expect(await page.locator(".rh-edition-workspace .rh-lineage-badge.status-running").first()
    .evaluate((element) => getComputedStyle(element).backgroundColor)).toBe("rgba(0, 0, 0, 0)");
  expect(await page.locator(".rh-edition-workspace .rh-argo-app-header .status")
    .evaluate((element) => getComputedStyle(element).backgroundColor)).toBe("rgba(0, 0, 0, 0)");
  expect(await page.locator(".rh-edition-workspace .rh-workspace-pipeline-head .stage-pill.done").first()
    .evaluate((element) => getComputedStyle(element).backgroundColor)).toBe("rgba(0, 0, 0, 0)");
  await expect(page.locator(".rh-edition-workspace .rh-lineage-card")).toHaveCount(5);
  expect(await page.locator(".rh-edition-workspace .rh-lineage-canvas-svg").evaluate(
    (element) => element.getBoundingClientRect().width,
  )).toBe(await page.locator(".rh-edition-workspace .rh-lineage-canvas-svg").evaluate(
    (element: SVGSVGElement) => element.viewBox.baseVal.width,
  ));
  await expect(page.locator(".rh-edition-workspace .rh-lineage-badge").filter({ hasText: "소속 기록" })).toHaveCount(2);
  await expect(page.locator(".rh-edition-workspace")).not.toContainText("정상 · RELEASE");
  await expect(sidebar.getByRole("link", { name: "릴리스 계통" })).toHaveAttribute("aria-current", "page");
  await page.getByRole("link", { name: "← Edition" }).click();
  await expect(page).toHaveURL(`${origin}/#/edition/selected/0.5.2`);
  await expect(canvas.getByRole("link", { name: /릴리스 0\.5\.2, RC/ })).toBeFocused();
  expect(await canvas.evaluate((element) => getComputedStyle(element).backgroundImage)).toBe(topologyChrome.canvasPattern);
  await page.goto(`${origin}/#/releases/0.5.1`);
  await expect(page.getByText("RELEASE 채널 소속", { exact: true })).toBeVisible();
  await expect(page.getByText("운영 RELEASE 배포 완료")).toHaveCount(0);
  await sidebar.getByRole("link", { name: "릴리스 계통" }).click();
  await expect(page).toHaveURL(`${origin}/#/edition`);
  await page.goto(`${origin}/#/releases`);
  await expect(page).toHaveURL(`${origin}/#/releases`);
  await expect(page.locator(".rh-lineage-section")).toBeVisible();
  await page.getByRole("link", { name: "← 릴리스 계통" }).click();
  await expect(page).toHaveURL(`${origin}/#/edition`);
  await page.getByRole("searchbox", { name: "검색" }).fill("0.5.2");
  await expect(page.getByRole("region", { name: "릴리스 목록 표" }).locator("tbody tr")).toHaveCount(1);
  await page.getByRole("searchbox", { name: "검색" }).fill("");
  await page.getByRole("combobox", { name: "채널" }).selectOption("RELEASE");
  await expect(page.getByRole("region", { name: "릴리스 목록 표" }).locator("tbody tr")).toHaveCount(1);
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  }
  const mobileNode = page.getByRole("region", { name: "릴리스 계통 캔버스, 가로 스크롤 가능" })
    .getByRole("link", { name: /릴리스 0\.5\.2, RC/ });
  await mobileNode.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(`${origin}/#/edition/releases/0.5.2`);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.getByRole("link", { name: "← Edition" }).click();
  await expect(page).toHaveURL(`${origin}/#/edition/selected/0.5.2`);
  await expect(mobileNode).toBeFocused();
  await expect(page.getByRole("heading", { name: "릴리스 계통" })).toBeVisible();
  await expect(sidebar.locator("a.nav-link")).toHaveCount(3);
  await sidebar.getByRole("link", { name: "배포 관리" }).click();
  await expect(page.getByRole("navigation", { name: "배포 관리 영역" }).getByRole("link", { name: "배포 채널" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("link", { name: "Release 0.5.1" }).first()).toHaveAttribute("href", "#/edition/releases/0.5.1");
  await page.getByRole("navigation", { name: "배포 관리 영역" }).getByRole("link", { name: "배포 요청" }).click();
  await expect(page.getByRole("heading", { name: "구독 배포 요청 현황" })).toBeVisible();
  await expect(page.getByRole("button", { name: "요청 새로고침" })).toBeEnabled();
  await expect(page.getByRole("region", { name: "Deployment request records" }).getByRole("link", { name: "0.5.2" }))
    .toHaveAttribute("href", "#/edition/releases/0.5.2");
  await sidebar.getByRole("link", { name: "신뢰·이력" }).click();
  await expect(page.getByRole("navigation", { name: "신뢰·이력 영역" }).getByRole("link", { name: "서명·리콜" })).toHaveAttribute("aria-current", "page");
  await page.getByRole("navigation", { name: "신뢰·이력 영역" }).getByRole("link", { name: "활동 이력" }).click();
  await expect(page.getByRole("heading", { name: /변경 및 감사 이력/ })).toBeVisible();
  await expect(sidebar.getByRole("link", { name: "신뢰·이력" })).toHaveAttribute("aria-current", "page");
  expect(unexpected).toEqual([]);
  expect(errors).toEqual([]);
});

test("authenticated Edition handles an empty catalog without fabricating nodes", async ({ page }) => {
  const unexpected = await serveAuthenticatedBuild(page, {
    ...catalog, revision: 0, releases: [], channels: { DEV: [], RELEASE_CANDIDATE: [], RELEASE: [] },
  });
  await page.goto(`${origin}/#/edition`);
  await expect(page.locator(".rh-edition-node")).toHaveCount(0);
  await expect(page.locator(".rh-edition-empty").first()).toBeVisible();
  await expect(page.getByRole("link", { name: /Stencil builder/ })).toHaveAttribute("href", "#/edition/new");
  expect(unexpected).toEqual([]);
});

test("Edition single-release navigation returns to the selected node", async ({ page }) => {
  const oneRelease = catalog.releases[0]!;
  const unexpected = await serveAuthenticatedBuild(page, {
    ...catalog, releases: [oneRelease], channels: { DEV: [oneRelease.id], RELEASE: [oneRelease.id] },
  });
  await page.goto(`${origin}/#/edition`);
  const node = page.getByRole("link", { name: /Release 0\.5\.1, RELEASE/ });
  await node.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(`${origin}/#/edition/releases/0.5.1`);
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await page.getByRole("link", { name: "<- Edition" }).click();
  await expect(page).toHaveURL(`${origin}/#/edition/selected/0.5.1`);
  await expect(node).toBeFocused();
  expect(unexpected).toEqual([]);
});

test("Edition restores the selected release in a long scrolling lineage", async ({ page }) => {
  const releases = Array.from({ length: 8 }, (_, index) =>
    release(`0.6.${index}`, "published", ["DEV"], `Release ${index}`));
  const unexpected = await serveAuthenticatedBuild(page, {
    ...catalog, releases, channels: { DEV: releases.map((item) => item.id) },
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(`${origin}/#/edition`);
  const canvas = page.getByRole("region", { name: "Scrollable release lineage" });
  const last = canvas.getByRole("link", { name: /Release 0\.6\.7, DEV/ });
  await last.focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(`${origin}/#/edition/releases/0.6.7`);
  await page.getByRole("link", { name: "<- Edition" }).click();
  await expect(page).toHaveURL(`${origin}/#/edition/selected/0.6.7`);
  await expect(last).toBeFocused();
  expect(await canvas.evaluate((element) => {
    const current = element.querySelector<HTMLElement>('.rh-edition-node[aria-current="true"]')!;
    const viewport = element.getBoundingClientRect();
    const node = current.getBoundingClientRect();
    return element.scrollLeft > 0 && node.left >= viewport.left && node.right <= viewport.right;
  })).toBe(true);
  expect(unexpected).toEqual([]);
});

test("Edition rejects an unknown return selection without showing another release", async ({ page }) => {
  const unexpected = await serveAuthenticatedBuild(page);
  await page.goto(`${origin}/#/edition/selected/does-not-exist`);
  await expect(page.getByRole("heading", { name: "Release unavailable" })).toBeVisible();
  await expect(page.locator(".rh-edition-node")).toHaveCount(0);
  await expect(page.getByRole("link", { name: "Back to Edition" })).toHaveAttribute("href", "#/edition");
  expect(unexpected).toEqual([]);
});

test("three-group navigation opens the real builder and retains legacy bookmarks", async ({ page }) => {
  const unexpected = await serveAuthenticatedBuild(page, {
    ...catalog,
    events: [{
      revision: 3, release_id: "0.5.2", action: "publish", reason: "Reviewed development release",
      channel: "DEV", occurred_at: "2026-11-05T00:00:00Z", actor: "local-operator",
    }],
  });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto(`${origin}/`);
  await expect(page.getByRole("heading", { name: "Releases", exact: true })).toBeVisible();
  const sidebar = page.getByRole("navigation", { name: "Release Hub" });
  await expect(sidebar.locator("a.nav-link")).toHaveCount(3);
  await expect(sidebar.getByRole("link", { name: "Release lineage" })).toHaveAttribute("aria-current", "page");
  await page.getByRole("link", { name: /Stencil builder.*Create release/ }).click();
  await expect(page).toHaveURL(`${origin}/#/edition/new`);
  await expect(page.getByRole("heading", { name: "Stencils & Custom Build" })).toBeVisible();
  await expect(page.getByRole("combobox", { name: "Builder language" })).toHaveCount(0);
  await expect(page.getByRole("link", { name: "← Release lineage" })).toHaveAttribute("href", "#/edition");
  await page.goto(`${origin}/#/stencils`);
  await expect(page.getByRole("heading", { name: "Stencils & Custom Build" })).toBeVisible();
  await expect(page.getByRole("link", { name: "← Release lineage" })).toBeVisible();
  await page.goto(`${origin}/#/deployment-requests`);
  await expect(sidebar.getByRole("link", { name: "Deployment management" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("navigation", { name: "Deployment management sections" })
    .getByRole("link", { name: "Deployment requests" })).toHaveAttribute("aria-current", "page");
  await page.goto(`${origin}/#/activity`);
  await expect(sidebar.getByRole("link", { name: "Trust & activity" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("navigation", { name: "Trust and activity sections" })
    .getByRole("link", { name: "Activity" })).toHaveAttribute("aria-current", "page");
  await expect(page.getByRole("link", { name: "Release 0.5.2" })).toHaveAttribute("href", "#/edition/releases/0.5.2");
  expect(unexpected).toEqual([]);
  expect(errors).toEqual([]);
});

test("quick promotion requires a fresh catalog and never acts on a failed read", async ({ page }) => {
  const unexpected = await serveAuthenticatedBuild(page);
  await page.goto(`${origin}/#/edition/releases/0.5.2`);
  const button = page.getByRole("button", { name: "1-Click Promote RELEASE ->" });
  await expect(button).toBeVisible();
  await page.route(`${origin}/v1/catalog`, (route) => route.fulfill({
    status: 503, json: { error: "Catalog unavailable" },
  }));
  await button.click();
  await expect(page.getByRole("alert")).toContainText("Action not completed or verified");
  expect(unexpected).toEqual([]);
});

test("quick promotion does not claim success when POST and independent readback disagree", async ({ page }) => {
  const unexpected = await serveAuthenticatedBuild(page);
  let promotionPosts = 0;
  await page.route(`${origin}/v1/releases/0.5.2/promote`, (route) => {
    promotionPosts += 1;
    return route.fulfill({ json: { ...catalog, revision: 4 } });
  });
  await page.goto(`${origin}/#/edition/releases/0.5.2`);
  await page.getByRole("button", { name: "1-Click Promote RELEASE ->" }).click();
  await expect(page.getByRole("alert")).toContainText("Promotion outcome unconfirmed");
  await expect(page.getByRole("button", { name: "1-Click Promote RELEASE ->" })).toBeDisabled();
  expect(promotionPosts).toBe(1);
  expect(unexpected).toEqual([]);
});

test("quick promotion does not silently advance a release whose stage changed since display", async ({ page }) => {
  const unexpected = await serveAuthenticatedBuild(page);
  await page.goto(`${origin}/#/edition/releases/0.5.2`);
  const button = page.getByRole("button", { name: "1-Click Promote RELEASE ->" });
  await expect(button).toBeVisible();
  const advanced = {
    ...catalog,
    revision: 4,
    releases: catalog.releases.map((item) => item.id === "0.5.2"
      ? { ...item, channels: ["DEV", "RELEASE_CANDIDATE", "RELEASE"] } : item),
  };
  await page.route(`${origin}/v1/catalog`, (route) => route.fulfill({ json: advanced }));
  await button.click();
  await expect(page.getByRole("alert")).toContainText("Action not completed or verified");
  expect(unexpected).toEqual([]);
});

test("quick registration stops before DEV publication when its independent readback is missing", async ({ page }) => {
  const unexpected = await serveAuthenticatedBuild(page);
  let registrations = 0;
  let publications = 0;
  await page.route(`${origin}/v1/stencils/compose`, (route) => route.fulfill({ json: composed }));
  await page.route(`${origin}/v1/releases/0.5.4/register`, (route) => {
    registrations += 1;
    return route.fulfill({ json: { ...catalog, revision: 4 } });
  });
  await page.route(`${origin}/v1/releases/0.5.4/publish`, (route) => {
    publications += 1;
    return route.fulfill({ json: { ...catalog, revision: 5 } });
  });
  await page.goto(`${origin}/#/releases`);
  await page.getByRole("button", { name: /1-Click Create Release/ }).click();
  await expect(page.getByRole("alert")).toContainText("Registration outcome unconfirmed");
  expect(registrations).toBe(1);
  expect(publications).toBe(0);
  expect(unexpected).toEqual([]);
});

test("quick creation reports confirmed registration separately from failed DEV publication", async ({ page }) => {
  const unexpected = await serveAuthenticatedBuild(page);
  let registered = false;
  const afterRegistration = {
    ...catalog, revision: 4,
    releases: [...catalog.releases, release("0.5.4", "draft", [], "Lite")],
    events: [{
      revision: 4, release_id: "0.5.4", action: "register",
      reason: "Register reviewed Stencil release manifest", channel: null,
      occurred_at: "2026-11-05T00:00:00Z",
    }],
  };
  await page.route(`${origin}/v1/stencils/compose`, (route) => route.fulfill({ json: composed }));
  await page.route(`${origin}/v1/catalog`, (route) => route.fulfill({ json: registered ? afterRegistration : catalog }));
  await page.route(`${origin}/v1/releases/0.5.4/register`, (route) => {
    registered = true;
    return route.fulfill({ json: afterRegistration });
  });
  await page.route(`${origin}/v1/releases/0.5.4/publish`, (route) => route.fulfill({
    status: 409, json: { error: "Signing unavailable" },
  }));
  await page.goto(`${origin}/#/releases`);
  await page.getByRole("button", { name: /1-Click Create Release/ }).click();
  await expect(page.getByRole("alert")).toContainText("Release 0.5.4 registration confirmed");
  await expect(page.getByRole("alert")).toContainText("DEV publication outcome unconfirmed");
  expect(unexpected).toEqual([]);
});

test("keyboard activation of the inline promotion action does not activate its parent card", async ({ page }) => {
  const unexpected = await serveAuthenticatedBuild(page);
  await page.goto(`${origin}/#/edition/releases/0.5.2`);
  const button = page.getByRole("button", { name: "1-Click Promote RELEASE ->" });
  await button.focus();
  await page.keyboard.press("Enter");
  await expect.poll(() => unexpected).toEqual(["POST /v1/releases/0.5.2/promote"]);
  await expect(page.getByRole("dialog")).toHaveCount(0);
});

test("destructive confirmation requires typing the release ID rather than using a prefilled value", async ({ page }) => {
  const unexpected = await serveAuthenticatedBuild(page);
  await page.goto(`${origin}/#/edition/releases/0.5.3`);
  await page.getByRole("button", { name: "Review DEV publication" }).click();
  const dialog = page.getByRole("dialog", { name: "Publish to DEV" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Confirm publish to dev" })).toBeDisabled();
  await dialog.getByRole("textbox", { name: "Type 0.5.3 to confirm" }).fill("0.5.3");
  await expect(dialog.getByRole("button", { name: "Confirm publish to dev" })).toBeEnabled();
  expect(unexpected).toEqual([]);
});

test("capability recall history links to Trust and unsigned drafts do not count as signed", async ({ page }) => {
  const draft = release("0.5.3", "draft", [], "Draft Stencil");
  draft.manifest = JSON.stringify({
    product: "FDAI", source_commit: "a".repeat(40),
    stencil: {
      stencil_id: "lite-observe-alert", stencil_digest: "sha256:" + "a".repeat(64),
      enabled_workloads: ["core-control-plane"], enabled_panel_ids: ["dashboard"],
    },
  });
  const unexpected = await serveAuthenticatedBuild(page, {
    ...catalog, releases: [draft], channels: { DEV: [] },
    events: [{
      revision: 3, release_id: "core-control-plane", action: "recall_capability",
      reason: "Review required", channel: null, occurred_at: "2026-11-05T00:00:00Z",
      actor: "local-operator",
    }],
  });
  await page.goto(`${origin}/#/activity`);
  await expect(page.getByRole("link", { name: "Capability core-control-plane" })).toHaveAttribute("href", "#/trust");
  await page.goto(`${origin}/#/trust`);
  await expect(page.getByText("Signed Stencil blueprints in catalog")).toHaveCount(0);
  expect(unexpected).toEqual([]);
});

test("refreshing the catalog also reloads deployment requests without losing the open tab", async ({ page }) => {
  const unexpected = await serveAuthenticatedBuild(page);
  let requests = 0;
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/v1/deployment-requests") requests += 1;
  });
  await page.goto(`${origin}/#/deployment-requests`);
  await expect.poll(() => requests).toBe(1);
  await page.getByRole("button", { name: "Refresh catalog" }).click();
  await expect.poll(() => requests).toBe(2);
  await expect(page).toHaveURL(`${origin}/#/deployment-requests`);
  expect(unexpected).toEqual([]);
});

test("catalog expiry becomes visible without an explicit refresh", async ({ page }) => {
  const unexpected = await serveAuthenticatedBuild(page, {
    ...catalog, expires_at: new Date(Date.now() + 2_500).toISOString(),
  });
  await page.goto(`${origin}/#/trust`);
  await expect(page.getByText(/Catalog export expired at/)).toHaveCount(0);
  await expect(page.getByText(/Catalog export expired at/)).toBeVisible({ timeout: 5_000 });
  expect(unexpected).toEqual([]);
});

test("capability recall requires an operator-typed target before enabling the write", async ({ page }) => {
  const unexpected = await serveAuthenticatedBuild(page);
  await page.goto(`${origin}/#/trust`);
  await page.getByText("Configure surgical capability recall or lift", { exact: true }).click();
  const recall = page.getByRole("button", { name: "Recall capability 'isolated-executor'" });
  await expect(recall).toBeDisabled();
  await page.getByRole("textbox", { name: "Audit reason" }).fill("Observed defective executor");
  await page.getByRole("textbox", { name: "Type isolated-executor to confirm" }).fill("isolated-executor");
  await expect(recall).toBeEnabled();
  expect(unexpected).toEqual([]);
});

test("release activity includes recalls of capabilities declared by that release only", async ({ page }) => {
  const candidate = release("0.5.2", "published", ["DEV", "RELEASE_CANDIDATE"], "Candidate");
  candidate.manifest = JSON.stringify({
    product: "FDAI", source_commit: "a".repeat(40),
    capability_maximums: { "isolated-executor": {} },
  });
  const unexpected = await serveAuthenticatedBuild(page, {
    ...catalog, releases: [candidate], events: [
      { revision: 2, release_id: "isolated-executor", action: "recall_capability",
        reason: "Defect found", channel: null, occurred_at: "2026-11-05T00:00:00Z" },
      { revision: 3, release_id: "unrelated-workload", action: "recall_capability",
        reason: "Unrelated", channel: null, occurred_at: "2026-11-05T00:00:01Z" },
    ],
  });
  await page.goto(`${origin}/#/edition/releases/0.5.2`);
  const history = page.locator("details.release-disclosure").filter({
    has: page.getByText("Release activity", { exact: true }),
  });
  await history.locator("summary").click();
  await expect(history.getByRole("link", { name: "Capability isolated-executor" })).toHaveAttribute("href", "#/trust");
  await expect(history.getByText("Unrelated")).toHaveCount(0);
  expect(unexpected).toEqual([]);
});

test("catalog export downloads exact bytes instead of opening an unauthenticated URL", async ({ page }) => {
  const unexpected = await serveAuthenticatedBuild(page);
  const raw = '{"revision":3,"exact":true}\n';
  await page.route(`${origin}/v1/catalog/export`, (route) => route.fulfill({
    body: raw, contentType: "application/json",
  }));
  await page.goto(`${origin}/#/trust`);
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "Download authenticated JSON export" }).click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe("fdai-release-catalog-3.json");
  expect(await download.failure()).toBeNull();
  expect(await readFile(await download.path(), "utf8")).toBe(raw);
  expect(unexpected).toEqual([]);
});

test("registration preset loading failures are shown inside the confirmation dialog", async ({ page }) => {
  const unexpected = await serveAuthenticatedBuild(page);
  await page.route(`${origin}/v1/stencils`, (route) => route.fulfill({
    status: 503, json: { error: "Stencil catalog unavailable" },
  }));
  await page.goto(`${origin}/#/releases`);
  await page.getByRole("button", { name: "Register release" }).click();
  const dialog = page.getByRole("dialog", { name: "Register release" });
  await expect(dialog.getByRole("alert")).toContainText("Could not fill preset");
  await expect(dialog.getByRole("button", { name: "Confirm register release" })).toBeDisabled();
  expect(unexpected).toEqual([]);
});

test("a delayed session refresh cannot restore the signed-in badge after logout", async ({ page }) => {
  const unexpected = await serveAuthenticatedBuild(page);
  let delaySession = false;
  let releaseSession: (() => void) | undefined;
  await page.route(`${origin}/v1/auth/session`, async (route) => {
    if (delaySession) await new Promise<void>((resolve) => { releaseSession = resolve; });
    await route.fulfill({ json: {
      authenticated: true, actor: "operator", detected_accounts: [],
      session: { principal: "operator", display_name: "Operator", tenant_id: "00000000-0000-0000-0000-000000000001",
        auth_method: "entra-workstation", signed_in_at: "2026-11-05T00:00:00Z" },
    } });
  });
  await page.route(`${origin}/v1/auth/entra/logout`, (route) => route.fulfill({ json: {
    authenticated: false, actor: "local-operator", session: null, detected_accounts: [],
  } }));
  await page.goto(`${origin}/#/edition`);
  const signOut = page.getByRole("button", { name: "Sign out" });
  await expect(signOut).toBeVisible();
  delaySession = true;
  await page.getByRole("button", { name: "Refresh catalog" }).click();
  await expect.poll(() => !!releaseSession).toBe(true);
  await signOut.click();
  await expect(page.getByRole("button", { name: "Sign in with Microsoft Entra ID" })).toBeVisible();
  const delayedResponse = page.waitForResponse((response) =>
    new URL(response.url()).pathname === "/v1/auth/session");
  releaseSession?.();
  await delayedResponse;
  await page.waitForLoadState("networkidle");
  await expect(page.getByRole("button", { name: "Sign out" })).toHaveCount(0);
  expect(unexpected).toEqual([]);
});

test("rejected sign-out retains the account and surfaces an actionable warning", async ({ page }) => {
  const unexpected = await serveAuthenticatedBuild(page);
  await page.route(`${origin}/v1/auth/session`, (route) => route.fulfill({ json: {
    authenticated: true, actor: "operator", detected_accounts: [],
    session: { principal: "operator", display_name: "Operator", tenant_id: "00000000-0000-0000-0000-000000000001",
      auth_method: "entra-workstation", signed_in_at: "2026-11-05T00:00:00Z" },
  } }));
  await page.route(`${origin}/v1/auth/entra/logout`, (route) => route.fulfill({
    status: 503, json: { error: "Not ready" },
  }));
  await page.goto(`${origin}/#/edition`);
  const signOut = page.getByRole("button", { name: "Sign out" });
  await expect(signOut).toBeVisible();
  await signOut.click();
  await expect(page.getByRole("alert")).toContainText("Sign-out outcome unconfirmed");
  await expect(signOut).toBeVisible();
  expect(unexpected).toEqual([]);
});
