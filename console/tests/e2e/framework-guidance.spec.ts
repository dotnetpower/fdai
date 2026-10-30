import { expect, test } from "@playwright/test";
import { frameworkFixture, installFrameworkFixture } from "./framework-guidance-fixtures";
import { guidanceText } from "../../src/routes/wara-guidance.model";

for (const framework of ["azure-waf", "azure-mcsb", "azure-caf"] as const) {
  test(`${framework} shared guidance, server-owned settings and history EN/KO, desktop before responsive (isolated fixtures)`, async ({ page }, testInfo) => {
    const fixture = frameworkFixture(framework);
    await installFrameworkFixture(page, fixture);
    const measurements: unknown[] = [];
    for (const viewport of [{ width: 1440, height: 900 }, { width: 993, height: 641 }, { width: 390, height: 844 }]) {
      await page.setViewportSize(viewport);
      for (const locale of ["en", "ko"] as const) {
        fixture.params.set("locale", locale);
        await page.goto(`/rules?${fixture.params}`);
        const drawer = page.getByRole("dialog");
        await expect(drawer.getByRole("heading", { name: guidanceText(fixture.guide.title, locale), level: 2, exact: true })).toBeVisible();
        await expect(drawer.locator(".wara-guidance-lead")).toHaveText(guidanceText(fixture.guide.summary, locale));
        await expect(drawer.locator("[data-guidance-node]")).toHaveCount(fixture.guide.diagram.nodes.length);
        await expect(drawer.locator("path[data-guidance-edge]")).toHaveCount(fixture.guide.diagram.edges.length);
        const expand = drawer.getByRole("button", { name: locale === "ko" ? "읽기 화면 넓히기" : "Expand reading view", exact: true });
        if (viewport.width > 1312) {
          await expand.click();
          await expect(drawer).toHaveClass(/is-expanded/);
        } else await expect(expand).toBeHidden();
        await page.screenshot({ animations: "disabled", path: testInfo.outputPath(`${framework}-${locale}-${viewport.width}-guide.png`) });
        await drawer.getByRole("link", { name: locale === "ko" ? "실제 환경 평가" : "Actual environment assessment", exact: true }).click();
        await expect(drawer.locator("#framework-runtime")).toBeFocused();
        await expect(drawer.getByText(locale === "ko" ? "검토된 설치 프로필의 재정의" : "Reviewed installation profile override", { exact: true })).toBeVisible();
        await expect(drawer.getByText(locale === "ko" ? "심각도별 기본값" : "Severity default", { exact: true })).toBeVisible();
        if (framework !== "azure-waf") await expect(drawer.getByText(/FDAI default|FDAI 기본값/)).toBeVisible();
        await expect(drawer.getByText(/Disabled assessment remains unknown|비활성화된 평가는 알 수 없음/)).toBeVisible();
        await expect(drawer.getByText(/Execution authority: none|실행 권한은 없습니다/)).toBeVisible();
        await expect(drawer.locator('input, [role="switch"]')).toHaveCount(0);
        const remediation = drawer.locator(".stack-section").filter({ has: page.getByRole("heading", { name: locale === "ko" ? "교정 조치 참고 정보" : "Remediation references", exact: true }) });
        await expect(remediation.getByText(/safety, approval and promotion|안전, 승인 및 승격/)).toBeAttached();
        if (framework === "azure-caf") await expect(remediation.getByRole("link")).toHaveCount(0);
        else {
          await expect(remediation.getByRole("link", { name: "storage.https-only", exact: true })).toHaveAttribute("href", /rule=storage.https-only/);
          await expect(remediation.getByText("storage.enable-https", { exact: true })).toBeAttached();
        }
        const geometry = await drawer.evaluate((element) => {
          const body = element.querySelector<HTMLElement>(".rule-drawer-body")!;
          return {
            document: [document.documentElement.scrollWidth, document.documentElement.clientWidth] as const,
            drawer: [element.scrollWidth, element.clientWidth] as const,
            body: [body.scrollWidth, body.clientWidth] as const,
          };
        });
        for (const [width, clientWidth] of Object.values(geometry)) expect(width).toBeLessThanOrEqual(clientWidth + 1);
        measurements.push({ framework, locale, viewport, geometry });
        await page.screenshot({ animations: "disabled", path: testInfo.outputPath(`${framework}-${locale}-${viewport.width}.png`) });
        await drawer.getByRole("button", { name: locale === "ko" ? "닫기" : "Close", exact: true }).click();
        await expect(drawer).toHaveCount(0);
        expect(new URL(page.url()).searchParams.get("q")).toBe("source");
        expect(new URL(page.url()).searchParams.has(framework === "azure-caf" ? "caf_control" : "control")).toBe(false);
        await page.goBack();
        await expect(page.getByRole("dialog")).toBeVisible();
        if (viewport.width === 1440 && locale === "en") {
          await page.getByRole("dialog").getByRole("button", { name: "Close", exact: true }).click();
          const row = page.locator(".data-table-row-action").filter({ hasText: "Source control title" });
          await row.click();
          await expect(page.getByRole("dialog")).toBeVisible();
          await page.getByRole("dialog").getByRole("button", { name: "Close", exact: true }).click();
          await row.focus();
          await page.keyboard.press("Enter");
          await expect(page.getByRole("dialog")).toBeVisible();
        }
      }
    }
    await testInfo.attach("geometry", { body: JSON.stringify(measurements), contentType: "application/json" });
  });

  test(`${framework} guide absence, mismatched source and tampered digest are explicit (isolated fixtures)`, async ({ page }) => {
    const fixture = frameworkFixture(framework);
    let mode: "absent" | "source" | "digest" = "absent";
    let releaseDetail: () => void = () => undefined;
    const pendingDetail = new Promise<void>((resolve) => { releaseDetail = resolve; });
    await installFrameworkFixture(page, fixture, (value) => ({
      ...value,
      guidance_unavailable_reason: mode === "absent" ? "source_pin_unavailable" : null,
      guidance: mode === "absent" ? null : mode === "source"
        ? { ...fixture.guide, source_digest: `sha256:${"d".repeat(64)}` }
        : { ...fixture.guide, summary: { en: "Unverified display text", ko: "검증되지 않은 표시 문구" } },
    }), () => pendingDetail);
    await page.goto(`/rules?${fixture.params}`);
    const drawer = page.getByRole("dialog");
    await expect(drawer.getByRole("status")).toHaveAttribute("aria-busy", "true");
    await expect(drawer.locator(".wara-guidance-content")).toHaveCount(0);
    releaseDetail();
    await expect(drawer.locator(".wara-guidance-unavailable")).toContainText("guidance is not available");
    await expect(drawer.locator(".wara-guidance-unavailable")).toContainText("source_pin_unavailable");
    await expect(drawer.locator(".wara-guidance-figure")).toHaveCount(0);
    await expect(drawer.getByText("Reviewed installation profile override", { exact: true })).toBeAttached();
    for (const next of ["source", "digest"] as const) {
      mode = next;
      await page.reload();
      await expect(drawer.getByText(/framework guidance/)).toBeVisible();
      await expect(drawer.locator(".wara-guidance-content")).toHaveCount(0);
      await expect(drawer.getByText("Unverified display text", { exact: true })).toHaveCount(0);
    }
  });
}
