import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

// Follow the existing standalone harness: serve built bytes through a fully intercepted origin.
// This is isolated browser evidence, not proof that a persistent loopback server is running.
const cases = [
  { hub: "release", design: "edition", heading: "Change, carefully composed." },
  { hub: "lifecycle", design: "atlas", heading: "A clear view of every environment." },
  { hub: "lifecycle", design: "timeline", heading: "Make room for the next change." },
  { hub: "lifecycle", design: "ledger", heading: "Details that make the difference." },
] as const;

async function interceptBuild(page: Page, hub: "release" | "lifecycle") {
  const directory = hub === "release" ? resolve("../../release-hub/ui/dist") : resolve("dist");
  const forbidden: string[] = [];
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== "https://hub.test" || /^\/(v1|auth|healthz|readyz)(\/|$)/.test(url.pathname)
      || route.request().method() !== "GET") {
      forbidden.push(`${route.request().method()} ${url.pathname}`);
      return route.abort();
    }
    const path = url.pathname.startsWith("/assets/") || url.pathname.startsWith("/brand/") ? url.pathname : "/index.html";
    const contentType = path.endsWith(".js") ? "text/javascript" : path.endsWith(".css") ? "text/css"
      : path.endsWith(".png") ? "image/png" : path.endsWith(".svg") ? "image/svg+xml" : "text/html";
    return route.fulfill({ body: await readFile(resolve(directory, `.${path}`)), contentType });
  });
  return forbidden;
}

async function prepareSurface(page: Page, hub: "release" | "lifecycle", runtime: boolean) {
  if (!runtime) return { origin: "https://hub.test", forbidden: await interceptBuild(page, hub) };
  const origin = `http://127.0.0.1:${hub === "release" ? 5291 : 5290}`;
  const forbidden: string[] = [];
  // Let real Vite assets and History fallback run. Never contact a live backend,
  // provider or third-party origin, even if a preview accidentally imports auth.
  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (url.origin !== origin || /^\/(v1|auth|healthz|readyz)(\/|$)/.test(url.pathname)
      || route.request().method() !== "GET") {
      forbidden.push(`${route.request().method()} ${url.pathname}`);
      return route.abort();
    }
    return route.continue();
  });
  return { origin, forbidden };
}

async function assertLayout(page: Page) {
  expect(await page.evaluate(() => ({
    page: document.documentElement.scrollWidth <= window.innerWidth,
    content: document.querySelector("main")!.scrollWidth <= document.querySelector("main")!.clientWidth,
  }))).toEqual({ page: true, content: true });
  await expect(page.locator("h1")).toBeVisible();
  expect(await page.locator(".dp-switcher a[aria-current='page']").count()).toBe(
    (await page.locator(".dp-switcher").count()) === 0 ? 0 : 1,
  );
  const smallTargets = await page.locator("button, input:not([type=checkbox]), select, .dp-switcher a, .dp-edition-checks label").evaluateAll((elements) =>
    elements.filter((element) => {
      const bounds = element.getBoundingClientRect();
      return bounds.width > 0 && bounds.height > 0 && (bounds.height < 44 || bounds.width < 44);
    }).length);
  expect(smallTargets).toBe(0);
}

async function exercise(page: Page, design: typeof cases[number]["design"]) {
  if (design === "edition") {
    const canvas = page.getByRole("region", { name: /릴리스 버전 계통 캔버스/ });
    const drawer = page.getByRole("dialog", { name: "릴리스 상세 · 예시" });
    await expect(canvas.locator(".dp-edition-node")).toHaveCount(4);
    await expect(canvas.locator(".dp-edition-lines g")).toHaveCount(3);
    await expect(page.locator(".dp-edition-components")).toHaveCount(0);
    await expect(drawer).toHaveCount(0);
    await expect(page.locator(".dp-edition-context, .dp-detail")).toHaveCount(0);
    expect(await canvas.evaluate((element) => element.scrollHeight <= element.clientHeight)).toBe(true);
    const branch = canvas.getByRole("button", { name: /예시 릴리스 0\.5\.4/ });
    await branch.focus();
    await page.keyboard.press("Home");
    await expect(canvas.getByRole("button", { name: /예시 릴리스 0\.5\.1/ })).toBeFocused();
    await page.keyboard.press("End");
    await expect(branch).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(drawer).toBeVisible();
    await expect(drawer.locator("#release-detail")).toContainText("0.5.4 / The next chapter");
    await expect(drawer.getByRole("region", { name: "Lifecycle 사용 현황" })).toHaveCount(0);
    const bounds = await drawer.boundingBox();
    expect(bounds).not.toBeNull();
    expect(bounds!.x + bounds!.width).toBeGreaterThanOrEqual(1439);
    expect(bounds!.x).toBeGreaterThan(1000);
    const components = drawer.locator("#release-detail details").first();
    await expect(components).not.toHaveAttribute("open", "");
    await components.locator("summary").click();
    await expect(components.locator("li")).toHaveCount(8);
    await expect(components).toContainText("Isolated executor");
    await page.keyboard.press("Escape");
    await expect(drawer).toHaveCount(0);
    await expect(branch).toBeFocused();
    const releaseTable = page.getByRole("region", { name: "릴리스 목록 표" });
    const tableTypography = await releaseTable.locator("tbody tr").first().evaluate((row) => {
      const version = row.querySelector<HTMLButtonElement>(".dp-edition-version")!;
      const values = [version, row.querySelector("small")!, row.cells[1], row.querySelector(".dp-status")!, row.cells[3]];
      return {
        sizes: [...new Set(values.map((element) => getComputedStyle(element).fontSize))],
        families: [...new Set(values.map((element) => getComputedStyle(element).fontFamily))],
        versionBorder: getComputedStyle(version).borderWidth,
        versionHeight: version.getBoundingClientRect().height,
      };
    });
    expect(tableTypography.sizes).toEqual(["13px"]);
    expect(tableTypography.families).toHaveLength(1);
    expect(tableTypography.versionBorder).toBe("0px");
    expect(tableTypography.versionHeight).toBeGreaterThanOrEqual(44);
    const tableRelease = page.getByRole("button", { name: "0.5.2", exact: true });
    await tableRelease.focus();
    await page.keyboard.press("Enter");
    await expect(drawer).toBeVisible();
    await expect(drawer.locator("#release-detail")).toContainText("0.5.2 / Precision");
    await drawer.getByRole("button", { name: "닫기" }).click();
    await expect(drawer).toHaveCount(0);
    await expect(tableRelease).toBeFocused();
    await page.getByLabel("릴리스 검색").fill("no-match");
    await expect(page.getByText("일치하는 예시가 없습니다.", { exact: false })).toBeVisible();
    await page.getByLabel("릴리스 검색").fill("");
    await page.getByLabel("채널", { exact: true }).selectOption("RELEASE");
    await expect(page.locator(".dp-edition-library .dp-table tbody tr")).toHaveCount(2);
    const heights = await page.locator(".dp-edition .dp-table tbody tr").evaluateAll((rows) =>
      rows.map((row) => row.getBoundingClientRect().height));
    expect(heights.every((height) => height <= 64)).toBe(true);
  } else if (design === "atlas" || design === "ledger") {
    await page.getByRole("button", { name: /Offline/ }).focus();
    await page.keyboard.press("Enter");
    await expect(page.locator("#installation-detail")).toContainText("알 수 없음");
    await page.getByLabel("설치 검색").fill("no-match");
    await expect(page.locator(".dp-empty")).toBeVisible();
    await page.getByLabel("설치 검색").fill("");
    await page.getByLabel("검토 범위").selectOption("unknown");
    await expect(page.getByRole("button", { name: /Offline/ })).toHaveCount(1);
    await page.getByLabel("검토 범위").selectOption("all");
  } else {
    const disclosure = page.locator(".dp-window summary").first();
    await disclosure.focus(); await page.keyboard.press("Enter");
    await expect(page.locator(".dp-window details").first()).toHaveAttribute("open", "");
    await expect(page.locator(".dp-steps").first()).toBeVisible();
    await page.getByRole("button", { name: "11월 07일" }).click();
    await expect(page.locator(".dp-window")).toHaveCount(1);
    await expect(page.locator(".dp-window")).toContainText("West");
    await page.locator(".dp-window summary").focus(); await page.keyboard.press("Enter");
  }
  // Exercise keyboard focus rather than relying on a pointer-focused element's style.
  await page.getByRole("link", { name: /운영 화면으로/ }).focus();
  await page.keyboard.press("Tab");
  expect(await page.evaluate(() => {
    const element = document.activeElement;
    return element !== null && element !== document.body && getComputedStyle(element).outlineStyle !== "none";
  })).toBe(true);
}

for (const scenario of cases) {
  test(`${scenario.hub} ${scenario.design}: isolated rendering, interaction and responsive keyboard checks`, async ({ page }, testInfo) => {
    const runtime = testInfo.project.metadata.previewRuntime === true;
    const { origin, forbidden } = await prepareSurface(page, scenario.hub, runtime);
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.setViewportSize({ width: 1440, height: 900 });
    const url = `${origin}/design-previews/${scenario.design}`;
    const response = await page.goto(url);
    expect(response?.status()).toBe(200);
    await expect(page).toHaveURL(url);
    await expect(page.getByRole("heading", { level: 1 })).toHaveText(scenario.heading);
    await expect(page.locator(".dp-notice")).toContainText("예시 데이터");
    await expect(page.locator(".dp-switcher a")).toHaveCount(scenario.hub === "release" ? 0 : 3);
    await page.keyboard.press("Tab");
    await expect(page.locator(".dp-skip")).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.locator("main")).toBeFocused();
    await exercise(page, scenario.design);
    await assertLayout(page);
    await testInfo.attach("preview-surface", {
      body: JSON.stringify({ url, venue: runtime ? "loopback-vite" : "intercepted-build", status: response?.status() }),
      contentType: "application/json",
    });
    // Source is generic fixed fixtures only; never collect an authenticated production surface.
    await testInfo.attach("desktop-expanded", { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
    for (const viewport of [{ width: 993, height: 641 }, { width: 390, height: 844 }, { width: 320, height: 844 }]) {
      await page.setViewportSize(viewport);
      await assertLayout(page);
      await testInfo.attach(`width-${viewport.width}`, { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
    }
    await page.emulateMedia({ reducedMotion: "reduce" });
    await expect(page.locator("h1")).toBeVisible();
    await page.reload();
    await expect(page.locator("h1")).toHaveText(scenario.heading);
    if (scenario.hub === "release") {
      await expect(page.locator(".dp-brand")).toContainText("Edition preview");
    } else {
      await page.locator(".dp-switcher a").last().click();
      await expect(page.locator(".dp-switcher a").last()).toHaveAttribute("aria-current", "page");
    }
    expect(forbidden).toEqual([]);
    expect(errors).toEqual([]);
  });
}

test("release Edition: six operating areas stay interactive and sample-only", async ({ page }, testInfo) => {
  const { origin, forbidden } = await prepareSurface(page, "release", testInfo.project.metadata.previewRuntime === true);
  await page.goto(`${origin}/design-previews/edition`);
  const navigation = page.getByRole("navigation", { name: "Edition 기능 탐색" });
  const builder = page.locator("#edition-builder");
  await expect(navigation.getByRole("button")).toHaveCount(5);
  await expect(builder).not.toHaveAttribute("open", "");
  await expect(page.getByText("릴리스의 흐름을 읽다.")).toHaveCount(0);
  await expect(page.getByText("노드 선택 · 방향키로 이동")).toHaveCount(0);

  await builder.locator("summary").first().click();
  await expect(builder).toHaveAttribute("open", "");
  await page.getByRole("button", { name: /Full Enterprise/ }).click();
  await expect(page.getByText("60개 · 운영 화면 기준")).toBeVisible();
  await page.getByRole("checkbox", { name: "Isolated executor" }).uncheck();
  await expect(page.getByText("4개 · 미선택 4개")).toBeVisible();
  await page.getByText("대표 메뉴 선택 보기").click();
  await page.getByRole("checkbox", { name: "Audit" }).uncheck();
  await expect(page.getByText("대표 7개 · 전체 카탈로그 아님")).toBeVisible();
  await page.getByRole("button", { name: "릴리스 등록 흐름 검토" }).click();
  await expect(page.getByRole("region", { name: "운영 절차 미리보기" })).toContainText("작업은 실행되지 않았습니다");
  await page.getByRole("textbox", { name: "작업 사유" }).fill("예시 검토");
  await expect(page.getByRole("button", { name: "프리뷰에서 실행할 수 없음" })).toBeDisabled();
  await builder.locator("summary").first().click();
  await expect(builder).not.toHaveAttribute("open", "");

  await navigation.getByRole("button", { name: /릴리스$/ }).click();
  await expect(page.getByRole("heading", { name: "릴리스", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "운영 절차 미리보기" })).toHaveCount(0);
  await page.getByRole("button", { name: "승격 근거 검토" }).click();
  await expect(page.getByRole("region", { name: "운영 절차 미리보기" })).toContainText("카나리");
  const compare = page.getByRole("region", { name: "버전 비교" });
  const baseVersion = compare.getByRole("combobox", { name: "기준 버전" });
  expect(await baseVersion.evaluate((element) => ({
    width: element.getBoundingClientRect().width,
    height: element.getBoundingClientRect().height,
  }))).toEqual({ width: 104, height: 44 });
  await expect(baseVersion.locator("option")).toHaveText(["v0.5.3", "v0.5.2", "v0.5.4", "v0.5.1"]);
  await baseVersion.selectOption("0.5.1");
  await expect(compare.getByRole("columnheader", { name: "기준 v0.5.1" })).toBeVisible();
  await expect(compare.getByRole("columnheader", { name: "선택 v0.5.3" })).toBeVisible();
  await expect(compare.getByRole("row", { name: /에디션/ })).toContainText("Lite Observe");
  await expect(compare.getByRole("row", { name: /채널/ })).toContainText("RELEASE_CANDIDATE");
  await expect(compare).toContainText("매니페스트 차이는 예시에서 제공하지 않습니다.");
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await assertLayout(page);
    expect(await compare.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true);
  }
  await page.setViewportSize({ width: 1440, height: 900 });

  await navigation.getByRole("button", { name: /배포 채널/ }).click();
  await expect(page.getByRole("heading", { name: "배포 채널" })).toBeVisible();
  await page.getByRole("button", { name: /v0.5.4 · Full Enterprise/ }).click();
  await expect(page.getByRole("dialog", { name: "릴리스 상세 · 예시" })).toContainText("0.5.4 / The next chapter");
  await page.getByRole("dialog").getByRole("button", { name: "닫기" }).click();

  await navigation.getByRole("button", { name: /배포 요청/ }).click();
  await expect(page.getByRole("heading", { name: "배포 요청" })).toBeVisible();
  await expect(page.getByRole("region", { name: "예시 배포 요청 목록" })).toContainText("소유권·배포 결과 미확인");
  await expect(page.getByRole("region", { name: "예시 배포 요청 목록" }).locator("tbody tr")).toHaveCount(2);
  await page.getByRole("searchbox", { name: "요청 검색" }).fill("no-such-request");
  await expect(page.getByText("일치하는 예시 요청이 없습니다.")).toBeVisible();

  await navigation.getByRole("button", { name: /활동 이력/ }).click();
  await page.getByRole("combobox", { name: "릴리스별 예시 활동" }).selectOption("0.5.3");
  await expect(page.locator(".dp-edition-activity li")).toHaveCount(1);

  await navigation.getByRole("button", { name: /서명·리콜/ }).click();
  await expect(page.getByRole("heading", { name: "서명·리콜" })).toBeVisible();
  await expect(page.getByText("없음 · 서명된 카탈로그 아님")).toBeVisible();
  await page.getByRole("button", { name: "회수·해제 절차" }).click();
  await expect(page.getByRole("region", { name: "운영 절차 미리보기" })).toContainText("API에 전송하지 않습니다");
  await page.setViewportSize({ width: 390, height: 844 });
  await assertLayout(page);
  await builder.locator("summary").first().click();
  await expect(builder).toHaveAttribute("open", "");
  await assertLayout(page);
  await page.getByRole("button", { name: "릴리스 등록 흐름 검토" }).click();
  await assertLayout(page);
  await page.getByRole("region", { name: /릴리스 버전 계통 캔버스/ })
    .getByRole("button", { name: /예시 릴리스 0\.5\.2/ }).click();
  const mobileDrawer = page.getByRole("dialog", { name: "릴리스 상세 · 예시" });
  await expect(mobileDrawer).toBeVisible();
  expect(await mobileDrawer.evaluate((element) => ({
    right: element.getBoundingClientRect().right,
    width: element.getBoundingClientRect().width,
    noHorizontalOverflow: element.scrollWidth <= element.clientWidth,
  }))).toEqual({ right: 390, width: 390, noHorizontalOverflow: true });
  await page.keyboard.press("Escape");
  await expect(mobileDrawer).toHaveCount(0);
  await testInfo.attach("edition-feature-mobile", { body: await page.screenshot({ fullPage: true }), contentType: "image/png" });
  expect(forbidden).toEqual([]);
});

test("release installation monitor: registered reports only, with an explicit unregistered boundary", async ({ page }, testInfo) => {
  const { origin, forbidden } = await prepareSurface(page, "release", testInfo.project.metadata.previewRuntime === true);
  const path = "/design-previews/edition/installations";
  await page.goto(`${origin}${path}`);
  await expect(page.getByRole("heading", { name: "등록 설치 현황" })).toBeVisible();
  await expect(page.getByRole("region", { name: "조회 범위" })).toContainText("등록하지 않은 설치의 수와 사용 버전은 알 수 없습니다");
  await expect(page.getByText("실시간 데이터 아님")).toBeVisible();
  const table = page.getByRole("region", { name: "등록 설치 표" });
  await expect(table.locator("tbody tr")).toHaveCount(5);
  await expect(page.getByRole("region", { name: "최근 보고된 사용 버전" })).toContainText("v0.5.2");
  await expect(page.getByRole("region", { name: "최근 보고된 사용 버전" })).not.toContainText("v0.5.4");
  await expect(table.locator("tbody tr").filter({ hasText: "West / 보조 운영" })).toContainText("확인 불가");
  await expect(table.locator("tbody tr").filter({ hasText: "Lab / 시험 환경" })).toContainText("보고 없음");
  await page.getByLabel("보고 상태").selectOption("stale");
  await expect(table.locator("tbody tr")).toHaveCount(1);
  await expect(table).toContainText("West / 보조 운영");
  await page.getByLabel("보고 상태").selectOption("all");
  await page.getByRole("searchbox", { name: "설치 검색" }).fill("0.5.4");
  await expect(table.locator("tbody tr")).toHaveCount(1);
  await expect(table).toContainText("Lab / 시험 환경");
  await page.getByRole("searchbox", { name: "설치 검색" }).fill("no-match");
  await expect(page.getByText("일치하는 등록 설치 예시가 없습니다.")).toBeVisible();
  await page.getByRole("searchbox", { name: "설치 검색" }).fill("");
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await assertLayout(page);
    expect(await table.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(true);
  }
  await page.reload();
  await expect(table.locator("tbody tr")).toHaveCount(5);
  await page.getByRole("link", { name: "릴리스 계통" }).click();
  await expect(page).toHaveURL(`${origin}/design-previews/edition`);
  await expect(page.getByRole("link", { name: "설치 현황" })).toHaveAttribute("href", path);
  expect(forbidden).toEqual([]);
});

for (const hub of ["release", "lifecycle"] as const) {
  test(`${hub}: unknown preview route never enters live authentication`, async ({ page }, testInfo) => {
    const { origin, forbidden } = await prepareSurface(page, hub, testInfo.project.metadata.previewRuntime === true);
    await page.goto(`${origin}/design-previews/not-a-design`);
    await expect(page.getByRole("heading", { name: "시안을 찾을 수 없습니다" })).toBeVisible();
    await page.getByRole("link", { name: "시안 열기" }).click();
    await expect(page.locator("h1")).not.toHaveText("시안을 찾을 수 없습니다");
    expect(forbidden).toEqual([]);
  });
}

test("retired Release Hub designs never enter operational authentication", async ({ page }, testInfo) => {
  const { origin, forbidden } = await prepareSurface(page, "release", testInfo.project.metadata.previewRuntime === true);
  for (const design of ["control", "atelier"]) {
    await page.goto(`${origin}/design-previews/${design}`);
    await expect(page.getByRole("heading", { name: "시안을 찾을 수 없습니다" })).toBeVisible();
  }
  expect(forbidden).toEqual([]);
});
