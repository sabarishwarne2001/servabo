/**
 * ANALYTICS "SYNC NOW" AND THE SOVEREIGN LICENCE'S "VERIFY AND INSTALL" (campaign Session C, long tail).
 *
 *  - Analytics → Sync schedules → "Sync now": on a destination made through the real form (Tenant C owns the
 *    warehouse add-on), the button needs a destination and a dataset; pressing it queues a background job
 *    ("Queued. Job …"), the run appears in the history, and, the bucket being unreachable from the sandbox,
 *    the worker records it as failed with a reason instead of leaving it queued. The destination is removed
 *    afterwards.
 *  - Sovereign console → Licence → "Verify and install" (platform administrator): text that is not a licence
 *    and a licence whose signature does not verify are both refused with a reason, and the installed
 *    licence status is unchanged. (Installing a valid licence changes the whole platform's state, so it is
 *    not driven here.)
 */
import { test, expect, expectHealthyPage, settle } from "../support/fixtures";
import { api, loginAs, resolveWorkspaceId } from "../support/api";
import { TENANTS, org, runId } from "../support/env";

interface Run { readonly id: string; readonly destination_id: string; readonly status: string; readonly error?: string | null }

test.describe("Analytics: Sync now", () => {
  test.use({ user: "C.owner" });
  test.setTimeout(240_000);

  test("Sync now queues a run that appears in the history and ends with a reason (the bucket is unreachable here)", async ({ page, problems }) => {
    problems.allowHttp(/\/analytics\//, [400, 409, 422, 502], "the sandbox cannot reach a warehouse bucket");
    const owner = await loginAs("C.owner");
    const { organizationId } = await resolveWorkspaceId(owner, TENANTS.C.org, TENANTS.C.ws);
    const label = `Sync now bucket ${runId()}`;
    await page.goto(org("C", "analytics"));
    await page.getByRole("button", { name: "Add destination" }).first().click();
    await page.getByRole("textbox", { name: "Label" }).fill(label);
    await page.getByRole("textbox", { name: "Bucket" }).fill("caretakers-e2e-bucket");
    await page.getByRole("textbox", { name: "Region" }).fill("eu-west-2");
    await page.getByRole("textbox", { name: "Key prefix" }).fill("servabo/");
    await page.getByRole("textbox", { name: "Access key ID" }).fill("AKIAE2ETESTONLY0000");
    await page.getByRole("textbox", { name: "Secret access key" }).fill("e2e-secret-not-real");
    await page.getByRole("button", { name: "Add destination" }).last().click();
    await expect(page.locator("main")).toContainText(label, { timeout: 20_000 });
    const destinations = await api<Array<{ id: string; label: string }>>(owner, "GET", `/organizations/${organizationId}/analytics/destinations`);
    const destination = destinations.body.find((row) => row.label === label);
    expect(destination, destinations.text).toBeTruthy();

    try {
      await page.getByRole("tab", { name: "Sync schedules", exact: true }).click();
      await settle(page, 300);
      const sync = page.getByRole("button", { name: "Sync now" });
      await expect(sync, "needs a destination first").toBeDisabled();
      await page.locator("#manual-destination").selectOption(destination!.id);
      await expect(sync).toBeEnabled();
      await sync.click();
      await expect(page.getByText(/^Queued\. Job /)).toBeVisible({ timeout: 20_000 });

      const mine = async (): Promise<Run | undefined> => {
        const body = (await api<Run[] | { items: Run[] }>(owner, "GET", `/organizations/${organizationId}/analytics/runs`)).body;
        const rows = Array.isArray(body) ? body : body.items;
        return rows.find((row) => row.destination_id === destination!.id);
      };
      await expect.poll(async () => (await mine())?.status, { timeout: 120_000, intervals: [2_000] }).toMatch(/FAILED|SUCCEEDED|ERROR/i);
      const run = await mine();
      expect(run?.status).toMatch(/FAILED|ERROR/i);
      await page.reload();
      await settle(page);
      await page.getByRole("tab", { name: "Run history", exact: true }).click();
      await expect(page.locator("main")).toContainText(/failed/i);
      await expectHealthyPage(page);
    } finally {
      await api(owner, "DELETE", `/organizations/${organizationId}/analytics/destinations/${destination!.id}`);
    }
  });
});

test.describe("Sovereign licence: Verify and install", () => {
  test.use({ user: "P.superadmin" });

  test("text that is not a licence, and a licence that does not verify, are refused with a reason; the status is unchanged", async ({ page, problems }) => {
    problems.allowHttp(/\/admin\/sovereign\/licence$/, [400, 402, 409, 422], "a licence that does not verify is refused (402 LICENCE_REQUIRED)");
    const operator = await loginAs("P.superadmin");
    const status = async (): Promise<string> =>
      JSON.stringify((await api<{ licence?: unknown }>(operator, "GET", "/admin/sovereign/status")).body.licence ?? null);
    const before = await status();

    await page.goto("/admin/sovereign?tab=licence");
    await settle(page);
    const install = page.getByRole("button", { name: "Verify and install" });
    await expect(install, "nothing to install yet").toBeDisabled();
    const box = page.getByLabel("Install a licence (the JSON document)");

    await box.fill("this is not a licence");
    await install.click();
    await expect(page.getByRole("alert").or(page.getByText(/not valid|invalid|could not|refused|malformed/i)).first()).toBeVisible({ timeout: 15_000 });

    await box.fill(JSON.stringify({ format: "servabo-licence/1", licence_id: "LIC-E2E", licensee: "Nobody", key_id: "unknown", features: [], signature: "AAAA" }));
    await install.click();
    await expect(page.getByText(/signature|key|verify|unknown|refused|invalid/i).first()).toBeVisible({ timeout: 15_000 });

    expect(await status(), "a refused licence changes nothing").toBe(before);
    await expectHealthyPage(page);
  });
});
