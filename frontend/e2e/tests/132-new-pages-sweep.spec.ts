/**
 * THE PAGES THE OLDER SWEEPS DO NOT LIST (Final session 1, Phase 5): GST Credit (workspace and
 * organization), Helm's pages, the new-workspace form and the jobs console.
 *
 * Specs 72 and 74 walk the page catalogue (support/routes.ts), which predates these pages. Each one is
 * opened as the Enterprise owner (the jobs console as platform staff) and must:
 *   - show no serious or critical axe finding, in the light and in the dark theme (Helm in dark is
 *     its Night Bridge look);
 *   - fit a 390px phone: the page is as wide as the window, a wide table scrolls inside its own box;
 *   - not land on the error page or the not-found page.
 * Then three dialogs a phone must be able to use are opened at 390px and must sit inside the screen.
 * Not walked, and why: pages that need an id in the address (a case, a certificate, an ERP posting),
 * which the specs for those features open; the partner portal, which has its own sign-in (spec 100).
 */
import AxeBuilder from "@axe-core/playwright";
import type { Page, TestInfo } from "@playwright/test";

import { test, expect, settle } from "../support/fixtures";
import { TENANTS, org, ws } from "../support/env";

const TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"];
const HELM_PAGES = ["", "plan", "mandates", "ledger", "time-machine", "bank", "certificates", "settings", "start", "setup"] as const;
const helm = (sub: string): string => `/${TENANTS.C.org}/helm${sub ? `/${sub}` : ""}`;

const TARGETS: ReadonlyArray<{ readonly id: string; readonly path: string }> = [
  { id: "workspace GST Credit", path: ws("C", "gst") },
  { id: "organization GST Credit", path: org("C", "gst") },
  { id: "organization TRINETRA", path: org("C", "trinetra") },
  { id: "new workspace", path: org("C", "workspaces/new") },
  ...HELM_PAGES.map((sub) => ({ id: `Helm ${sub || "cockpit"}`, path: helm(sub) })),
];

async function open(page: Page, path: string): Promise<void> {
  await page.goto(path);
  await expect(page.locator("main, [role='main']").first()).toBeVisible();
  await settle(page);
  const text = (await page.locator("body").innerText()).slice(0, 4000);
  expect(text, `${path} landed on an error page`).not.toMatch(/Something went wrong|Page not found|couldn.t be found/i);
}

async function audit(page: Page, testInfo: TestInfo, where: string): Promise<void> {
  const results = await new AxeBuilder({ page }).withTags(TAGS).analyze();
  const blocking = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical");
  for (const v of results.violations.filter((v) => !blocking.includes(v))) {
    testInfo.annotations.push({ type: `axe ${v.impact}`, description: `${where}: ${v.id} (${v.nodes.length})` });
  }
  expect(
    blocking.map((v) => `${v.impact} ${v.id}: ${v.help} — ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`),
    `${where} has serious or critical accessibility violations`,
  ).toEqual([]);
}

for (const scheme of ["light", "dark"] as const) {
  test.describe(`accessibility, ${scheme} theme — pages the catalogue lacks`, () => {
    test.use({ user: "C.owner", colorScheme: scheme });
    for (const target of TARGETS) {
      test(target.id, async ({ page }, testInfo) => {
        await open(page, target.path);
        await audit(page, testInfo, `${target.id} (${scheme})`);
      });
    }
  });
}

test.describe("phone, 390px — pages the catalogue lacks", () => {
  test.use({ user: "C.owner", viewport: { width: 390, height: 844 } });
  for (const target of TARGETS) {
    test(target.id, async ({ page }) => {
      await open(page, target.path);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
      expect(overflow, `${target.id} scrolls sideways by ${overflow}px at 390px`).toBeLessThanOrEqual(1);
    });
  }
});

test.describe("dialogs fit a 390px phone", () => {
  test.use({ user: "C.owner", viewport: { width: 390, height: 844 } });

  async function insideScreen(page: Page, what: string): Promise<void> {
    const box = await page.getByRole("dialog").first().boundingBox();
    expect(box, `${what} has no dialog`).not.toBeNull();
    expect(box!.x, `${what} starts left of the screen`).toBeGreaterThanOrEqual(-1);
    expect(box!.x + box!.width, `${what} runs past the right edge`).toBeLessThanOrEqual(391);
    expect(box!.y + box!.height, `${what} runs past the bottom`).toBeLessThanOrEqual(845);
  }

  test("the command palette", async ({ page }) => {
    await open(page, ws("C", ""));
    await page.keyboard.press("Control+k");
    await expect(page.getByRole("dialog").first()).toBeVisible();
    await insideScreen(page, "the command palette");
  });

  test("the recipe gallery", async ({ page }) => {
    await open(page, ws("C", "automation"));
    await page.getByRole("button", { name: /start from a recipe/i }).click();
    await expect(page.getByRole("dialog").first()).toBeVisible();
    await insideScreen(page, "the recipe gallery");
  });
});

test.describe("the jobs console, as platform staff", () => {
  test.use({ user: "P.superadmin", viewport: { width: 390, height: 844 } });
  test("fits 390px and has no serious accessibility finding", async ({ page }, testInfo) => {
    await open(page, "/admin/jobs");
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth);
    expect(overflow, `the jobs console scrolls sideways by ${overflow}px at 390px`).toBeLessThanOrEqual(1);
    await audit(page, testInfo, "jobs console");
  });
});
