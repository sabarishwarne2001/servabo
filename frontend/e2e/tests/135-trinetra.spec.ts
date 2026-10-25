import AxeBuilder from "@axe-core/playwright";
import { test, expect, settle } from "../support/fixtures";
import { ws, TENANTS, type TenantKey, type UserKey } from "../support/env";
import { api, resolveWorkspaceId } from "../support/api";

for (const [tenant, user] of [
  ["A", "A.owner"],
  ["B", "B.owner"],
  ["C", "C.owner"],
  ["C", "C.viewer"],
] as [TenantKey, UserKey][]) {
  test.describe(`TRINETRA synthetic preview · ${user}`, () => {
    test.use({ user });
    test("sample is consistent, searchable and read only", async ({ page, session }) => {
      await page.goto(ws(tenant, "trinetra"));
      await expect(page.getByRole("heading", { level: 1, name: "Credit assurance" })).toBeVisible();
      await expect(page.getByText("Illustrative synthetic data", { exact: true })).toBeVisible();
      await page.getByRole("textbox", { name: "Search customer or invoice" }).fill("Exact posted");
      await page.getByRole("button", { name: /Exact posted/ }).click();
      await expect(page.getByRole("complementary", { name: "Case insight" })).toContainText(
        "₹2,000.00",
      );
      await expect(page.getByRole("button", { name: "Record review" })).toHaveCount(0);
      await page
        .getByRole("textbox", { name: "Search customer or invoice" })
        .fill("no-such-customer");
      await expect(page.getByText("No cases match these filters.")).toBeVisible();
      const { workspaceId: wid } = await resolveWorkspaceId(
        session!,
        TENANTS[tenant].org,
        TENANTS[tenant].ws,
      );
      const denied = await api(session!, "POST", `/workspaces/${wid}/trinetra/profiles`, {
        name: "Blocked synthetic profile",
        pan: "ABCDE1234F",
      });
      expect([402, 403, 503]).toContain(denied.status);
    });
  });
}

for (const scheme of ["light", "dark"] as const) {
  test.describe(`TRINETRA accessibility · ${scheme}`, () => {
    test.use({ user: "C.owner", colorScheme: scheme });
    test("keyboard, responsive layout and axe", async ({ page }) => {
      await page.goto(ws("C", "trinetra"));
      await settle(page);
      const search = page.getByRole("textbox", { name: "Search customer or invoice" });
      await search.fill("Exact posted");
      const selected = page.getByRole("button", { name: /Exact posted/ });
      await selected.focus();
      await page.keyboard.press("Enter");
      await expect(selected).toHaveAttribute("aria-pressed", "true");
      const scan = await new AxeBuilder({ page })
        .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
        .analyze();
      expect(
        scan.violations.filter((v) => v.impact === "serious" || v.impact === "critical"),
      ).toEqual([]);
      await search.fill("");
      await page.screenshot({ path: `../.dev/trinetra-${scheme}.png`, fullPage: true });
      for (const width of [390, 768, 1440]) {
        await page.setViewportSize({ width, height: 900 });
        expect(
          await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth),
        ).toBeLessThanOrEqual(1);
      }
    });
  });
}
