import { expect, test, type Page } from "@playwright/test";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import type { LocalChannels } from "../../src/routes/local-channels";

const digest = "a".repeat(64);
const initial = {
  approved_revision: 0, approved_sha256: null as string | null,
  minimum_revision: 0, accepted_sha256: null as string | null,
  imported: false, mode: "development-pinned-export",
};

function contrast(first: string, second: string): number {
  const luminance = (value: string) => {
    const channels = value.match(/[\d.]+/g)?.slice(0, 3).map(Number);
    if (!channels || channels.length !== 3) throw new Error(`Unsupported computed color: ${value}`);
    return channels.map(value => {
      const component = value / 255;
      return component <= 0.04045 ? component / 12.92 : ((component + 0.055) / 1.055) ** 2.4;
    }).reduce((total, value, index) => total + value * [0.2126, 0.7152, 0.0722][index], 0);
  };
  const values = [luminance(first), luminance(second)].sort((a, b) => b - a);
  return (values[0] + 0.05) / (values[1] + 0.05);
}

async function assets(page: Page, directory: string) {
  await page.route("https://hub.test/**", async route => {
    const path = new URL(route.request().url()).pathname;
    if (path.startsWith("/v1/") || path === "/auth/config") {
      throw new Error(`Unexpected API request: ${path}`);
    }
    const file = path.startsWith("/assets/") || path.startsWith("/brand/") ? path : "/index.html";
    const contentType = file.endsWith(".js") ? "text/javascript" :
      file.endsWith(".css") ? "text/css" : file.endsWith(".svg") ? "image/svg+xml" : "text/html";
    await route.fulfill({ body: await readFile(resolve(directory, `.${file}`)), contentType });
  });
}

for (const width of [1440, 993, 390]) {
  test(`approved pin, explicit import, Plan and rejection at ${width}px`, async ({ page }, info) => {
    await page.setViewportSize({ width, height: 900 });
    await assets(page, resolve("dist"));
    let trust = { ...initial };
    await page.route("**/auth/config", route => route.fulfill({ json: { profile: "local-development" } }));
    await page.route("**/v1/catalog/trust", route => route.fulfill({ json: trust }));
    let local: LocalChannels = {
      revision: 0, digest: "c".repeat(64), accepted_sha256: digest, source_revision: 4,
      entries: [], available_releases: [{ release_id: "1.6.0", release_digest: "b".repeat(64) }],
      execution_authority: false,
    };
    const channel = width === 390 ? `local-${"a".repeat(58)}` : "local-reviewed";
    await page.route("**/v1/catalog/local-channels", async route => {
      if (route.request().method() === "POST") {
        expect(route.request().postDataJSON()).toEqual({
          revision: 0, accepted_sha256: digest, channel, release_id: "1.6.0",
          release_digest: "b".repeat(64), reason: "Independent local review",
          confirmation: `add 1.6.0 to ${channel}`,
        });
        local = { ...local, revision: 1, entries: [{
          revision: 1, channel, release_id: "1.6.0", release_digest: "b".repeat(64),
          actor: "customer-operator", reason: "Independent local review",
          eligible: true, hold_reason: null,
        }] };
      }
      await route.fulfill({ json: local });
    });
    await page.route("**/v1/catalog/trust/approve", async route => {
      const body = route.request().postDataJSON();
      expect(body).toEqual({
        revision: 4, sha256: digest, reason: "Independent customer review",
        confirmation: `approve 4 ${digest}`,
      });
      trust = { ...trust, approved_revision: 4, approved_sha256: digest };
      await route.fulfill({ json: trust });
    });
    let imported = false;
    await page.route("**/v1/catalog/import", async route => {
      expect(trust.approved_sha256).toBe(digest);
      if (imported) return route.fulfill({ status: 422, json: { error: "tampered_export" } });
      trust = { ...trust, minimum_revision: 4, accepted_sha256: digest, imported: true };
      imported = true;
      await route.fulfill({ json: trust });
    });
    await page.route("**/v1/installations/synthetic-installation/recompute", route =>
      route.fulfill({ json: { outcome: "issued", checks: [], plan_id: "synthetic-plan" } }));
    await page.goto("https://hub.test/catalog");
    await expect(page.getByRole("button", { name: "Import approved catalog" })).toBeDisabled();
    await page.getByLabel("Revision", { exact: true }).fill("4");
    await page.getByLabel("SHA-256", { exact: true }).fill(digest);
    await page.getByLabel("Approval reason").fill("Independent customer review");
    await page.getByLabel("Type approve, revision and digest separated by spaces").fill(`approve 4 ${digest}`);
    await page.getByRole("button", { name: "Approve exact pin" }).click();
    await expect(page.getByRole("button", { name: "Import approved catalog" })).toBeEnabled();
    await page.getByRole("button", { name: "Import approved catalog" }).click();
    await expect(page.getByRole("button", { name: "Compute Plan" })).toBeEnabled();
    await page.getByLabel("Local channel", { exact: true }).fill(channel);
    await page.getByRole("combobox", { name: "Imported RELEASE member", exact: true }).selectOption("1.6.0");
    await page.getByLabel("Curation reason", { exact: true }).fill("Independent local review");
    const confirm = page.getByLabel(`Type add 1.6.0 to ${channel} to confirm`, { exact: true });
    await confirm.fill("unreviewed");
    await expect(page.getByRole("button", { name: "Add reviewed local member" })).toBeDisabled();
    await confirm.fill(`add 1.6.0 to ${channel}`);
    await confirm.press("Tab");
    await expect(page.getByRole("button", { name: "Add reviewed local member" })).toBeFocused();
    await page.keyboard.press("Enter");
    await expect(page.getByText("Eligible for planning only", { exact: true })).toBeVisible();
    expect(await page.locator(".local-channels").evaluate(el => el.scrollWidth <= el.clientWidth)).toBe(true);
    if (width === 390) {
      expect(await page.getByRole("button", { name: "Add reviewed local member" })
        .evaluate(el => el.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44);
    }
    const panelWidth = await page.locator(".local-channels").evaluate(el => el.clientWidth);
    expect(await page.locator(".local-channel-members strong")
      .evaluate(el => el.getBoundingClientRect().width)).toBeGreaterThanOrEqual(panelWidth - 48);
    const colors = await page.locator(".local-channels").evaluate(el => {
      const input = el.querySelector("input"), label = el.querySelector("label");
      if (!input || !label) throw new Error("Expected local controls.");
      return {
        border: getComputedStyle(input).borderTopColor,
        background: getComputedStyle(input).backgroundColor,
        label: getComputedStyle(label).color,
        page: getComputedStyle(document.body).backgroundColor,
      };
    });
    expect(contrast(colors.border, colors.background)).toBeGreaterThanOrEqual(3);
    expect(contrast(colors.label, colors.page)).toBeGreaterThanOrEqual(4.5);
    console.log(JSON.stringify({
      scenario: `local-channel-${width}`,
      evidence: info.outputPath(`local-channel-${width}.png`),
      geometry: await page.locator(".local-channels").evaluate(el => {
        const label = el.querySelector("label"), input = el.querySelector("input");
        if (!label || !input) throw new Error("Expected the local curation controls.");
        return {
          scrollWidth: el.scrollWidth, clientWidth: el.clientWidth,
          documentWidth: document.documentElement.scrollWidth,
          viewportWidth: innerWidth,
          labelColor: getComputedStyle(label).color,
          inputBorder: getComputedStyle(input).borderTopColor,
          inputBackground: getComputedStyle(input).backgroundColor,
          panelBackground: getComputedStyle(el).backgroundColor,
          bodyBackground: getComputedStyle(document.body).backgroundColor,
        };
      }),
    }));
    await page.locator(".local-channels").screenshot({ path: info.outputPath(`local-channel-${width}.png`) });
    await page.getByLabel("Installation ID").fill("synthetic-installation");
    await page.getByRole("button", { name: "Compute Plan" }).click();
    await expect(page.getByRole("status")).toContainText("issued");
    await page.getByRole("button", { name: "Import approved catalog" }).click();
    await expect(page.getByRole("alert")).toContainText("Request rejected");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
    await page.evaluate(() => scrollTo(0, 0));
    await page.screenshot({ path: info.outputPath(`catalog-${width}.png`), fullPage: true });
  });
}

for (const failure of ["unverified", "changed-pin"]) {
test(`${failure} local curation is explicit and cannot submit`, async ({ page }) => {
  await assets(page, resolve("dist"));
  await page.route("**/auth/config", route => route.fulfill({ json: { profile: "local-development" } }));
  await page.route("**/v1/catalog/trust", route => route.fulfill({ json: {
    ...initial, imported: true, accepted_sha256: digest,
  } }));
  await page.route("**/v1/catalog/local-channels", route => failure === "unverified"
    ? route.fulfill({ status: 503, json: { error: "Review catalog trust, expiry and local evidence." } })
    : route.fulfill({ json: { revision: 0, accepted_sha256: "d".repeat(64), entries: [], available_releases: [] } }));
  await page.goto("https://hub.test/catalog");
  await expect(page.getByRole("alert")).toContainText(failure === "unverified" ? "local evidence" : "Accepted catalog changed");
  await expect(page.getByRole("button", { name: "Add reviewed local member" })).toHaveCount(0);
});
}

test("a late local write response cannot replace a newly imported catalog view", async ({ page }) => {
  await assets(page, resolve("dist"));
  const nextPin = "d".repeat(64);
  let currentPin = digest;
  let finishWrite: (() => Promise<void>) | undefined;
  const entry = {
    revision: 1, channel: "local-reviewed", release_id: "1.6.0", release_digest: "b".repeat(64),
    actor: "customer-operator", reason: "Reviewed source selection", eligible: true, hold_reason: null,
  };
  await page.route("**/auth/config", route => route.fulfill({ json: { profile: "local-development" } }));
  await page.route("**/v1/catalog/trust", route => route.fulfill({ json: {
    ...initial, imported: true, accepted_sha256: digest, approved_sha256: digest, minimum_revision: 4,
  } }));
  await page.route("**/v1/catalog/import", route => {
    currentPin = nextPin;
    return route.fulfill({ json: {
      ...initial, imported: true, accepted_sha256: nextPin, approved_sha256: nextPin,
      approved_revision: 5, minimum_revision: 5,
    } });
  });
  await page.route("**/v1/catalog/local-channels", async route => {
    const state = {
      revision: currentPin === digest ? 0 : 1, digest: "c".repeat(64), accepted_sha256: currentPin,
      source_revision: currentPin === digest ? 4 : 5,
      entries: currentPin === digest ? [] : [{ ...entry, eligible: false, hold_reason: "release_unknown" }],
      available_releases: currentPin === digest ? [{ release_id: "1.6.0", release_digest: "b".repeat(64) }] : [],
      execution_authority: false,
    };
    if (route.request().method() !== "POST") return route.fulfill({ json: state });
    await new Promise<void>(resolve => {
      finishWrite = async () => {
        await route.fulfill({ json: { ...state, revision: 1, entries: [entry] } });
        resolve();
      };
    });
  });
  await page.goto("https://hub.test/catalog");
  await page.getByLabel("Local channel", { exact: true }).fill("local-reviewed");
  await page.getByRole("combobox", { name: "Imported RELEASE member", exact: true }).selectOption("1.6.0");
  await page.getByLabel("Curation reason").fill("Reviewed source selection");
  await page.getByLabel("Type add 1.6.0 to local-reviewed to confirm", { exact: true })
    .fill("add 1.6.0 to local-reviewed");
  await page.getByRole("button", { name: "Add reviewed local member" }).click();
  await page.getByRole("button", { name: "Import approved catalog" }).click();
  await expect(page.locator(".local-channels")).toContainText("accepted catalog revision 5");
  await expect(page.locator(".local-channels")).toContainText("Held: release_unknown");
  if (!finishWrite) throw new Error("Expected the held old-scope write.");
  const response = page.waitForResponse(value =>
    value.url().endsWith("/v1/catalog/local-channels") && value.request().method() === "POST");
  await finishWrite();
  await response;
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await expect(page.locator(".local-channels")).toContainText("Held: release_unknown");
  await expect(page.locator(".local-channels")).not.toContainText("Eligible for planning only");
});

for (const kind of ["target", "release"]) {
  test(`${kind} remote profile exposes login, never business API before authentication`, async ({ page }) => {
    await assets(page, kind === "target" ? resolve("dist") : resolve("../../release-hub/ui/dist"));
    await page.route("**/auth/config", route => route.fulfill({ json: {
      profile: "remote-development", origin: "https://hub.test",
      clientId: "00000000-0000-0000-0000-000000000001",
      authority: "https://login.microsoftonline.com/00000000-0000-0000-0000-000000000000",
      scope: "api://synthetic-api/Hub.Access",
    } }));
    await page.route("https://login.microsoftonline.com/**", () => {
      throw new Error("Live access is not authorized.");
    });
    await page.goto("https://hub.test/");
    await expect(page.getByRole("button", { name: "Sign in with Microsoft Entra ID" })).toBeVisible();
    await expect(page.getByText("This is not a production trust root.", { exact: false })).toBeVisible();
  });
}
