/**
 * TRINETRA access by plan and by pilot enrolment (Final session 2T, Phase 8).
 *
 * Starter shows the synthetic examples and the plan sentence. A paid organization that the platform operator has not enrolled
 * sees the pilot sentence; enrolling it opens the live screens, and withdrawing closes them again. The server refuses what the
 * screens hide. Nothing here uses the seeded organizations a shared spec depends on, except Starter's read-only look.
 */
import { test, expect, settle } from "../support/fixtures";
import { ws, TENANTS } from "../support/env";
import { api, resolveWorkspaceId } from "../support/api";
import { signInAs } from "../support/journey";
import { enrol, liveCustomer, withdraw, PAN } from "../support/trinetra";

test.describe("TRINETRA on Starter", () => {
  test.use({ user: "A.owner" });
  test("a Starter organization is told about the plan, sees the examples and cannot write", async ({ page, session }) => {
    await page.goto(ws("A", "trinetra"));
    await expect(page.getByRole("heading", { level: 1, name: "Credit assurance" })).toBeVisible();
    const notice = page.getByTestId("trinetra-access-not_entitled");
    await expect(notice).toContainText("TDS credit comes with Business and Enterprise");
    await expect(notice.getByRole("link", { name: "See the plans" })).toBeVisible();
    await expect(page.getByText("Illustrative synthetic data", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Your workspace", exact: true })).toHaveCount(0);
    await expect(page.getByRole("tab", { name: "Statements" })).toHaveCount(0);
    const { workspaceId } = await resolveWorkspaceId(session!, TENANTS.A.org, TENANTS.A.ws);
    for (const [method, route, body] of [
      ["POST", "profiles", { name: "Blocked", pan: PAN }],
      ["GET", "credits", undefined],
      ["GET", "approvals", undefined],
      ["GET", "suggestions", undefined],
    ] as const) {
      const refused = await api(session!, method, `/workspaces/${workspaceId}/trinetra/${route}`, body);
      expect([402, 403, 409], `${method} ${route}: ${refused.text}`).toContain(refused.status);
    }
  });

  test("the organization view says the same", async ({ page }) => {
    await page.goto(`/organizations/${TENANTS.A.org}/trinetra`);
    await expect(page.getByTestId("trinetra-access-not_entitled")).toBeVisible();
    await settle(page);
  });
});

test.describe("TRINETRA on Business: the pilot", () => {
  test.setTimeout(180_000);
  test("an organization that is not enrolled sees the pilot sentence; enrolment opens it and withdrawal closes it", async ({ page }) => {
    const customer = await liveCustomer("tr-pilot", "business", { enrolled: false });
    await signInAs(page, customer.email);

    await page.goto(customer.ws("trinetra"));
    await expect(page.getByTestId("trinetra-access-not_enrolled")).toContainText(
      "TRINETRA is in a pilot, and your organization is not enrolled yet",
    );
    await expect(page.getByRole("button", { name: "Your workspace", exact: true })).toHaveCount(0);
    const refused = await api(customer.session, "POST", `/workspaces/${customer.wsId}/trinetra/profiles`, { name: "Not yet", pan: PAN });
    expect([402, 403, 409], refused.text).toContain(refused.status);

    await enrol(customer.orgId);
    await page.reload();
    await expect(page.getByTestId("trinetra-access-not_enrolled")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Your workspace", exact: true })).toBeVisible();
    const made = await api(customer.session, "POST", `/workspaces/${customer.wsId}/trinetra/profiles`, { name: "Now live", pan: PAN });
    expect(made.status, made.text).toBe(200);

    await withdraw(customer.orgId);
    await page.reload();
    await expect(page.getByTestId("trinetra-access-not_enrolled")).toBeVisible();
  });

  test("only the platform operator reaches the pilot console", async () => {
    const customer = await liveCustomer("tr-console", "business", { enrolled: false });
    for (const [method, route] of [
      ["GET", "/admin/trinetra/pilot"],
      ["PUT", `/admin/trinetra/pilot/${customer.orgId}`],
    ] as const) {
      const refused = await api(customer.session, method, route, method === "PUT" ? { reason: "I would like to be in the pilot." } : undefined);
      expect([401, 403, 404], `${method} ${route}`).toContain(refused.status);
    }
  });
});

test.describe("TRINETRA pilot console", () => {
  test.use({ user: "P.superadmin" });
  test.setTimeout(180_000);
  test("the platform administrator enrols an organization from the console with a reason, and withdraws it", async ({ page }) => {
    const customer = await liveCustomer("tr-console-ui", "business", { enrolled: false });
    const access = async () =>
      (await api<{ enrolled: boolean; live_enabled: boolean }>(customer.session, "GET", `/workspaces/${customer.wsId}/trinetra/access`)).body;
    expect((await access()).enrolled).toBe(false);

    await page.goto(`/admin/trinetra?organization=${customer.orgId}`);
    const console_ = page.getByTestId("trinetra-pilot-console");
    await expect(console_.getByRole("heading", { level: 1, name: "TRINETRA pilot" })).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId("trinetra-pilot-mode")).toHaveText("pilot");
    await page.getByLabel("Find by name or slug", { exact: true }).fill(customer.orgSlug);
    await expect(page.getByLabel("Organization", { exact: true })).toHaveValue(customer.orgId);
    const enrolButton = page.getByRole("button", { name: "Enrol in the pilot" });
    await expect(enrolButton).toBeDisabled();
    await page.getByLabel("Reason for enrolling", { exact: true }).fill("Browser specs: enrolled from the pilot console.");
    await enrolButton.click();
    const row = page.getByTestId("trinetra-pilot-row").filter({ hasText: customer.orgSlug });
    await expect(row).toHaveCount(1, { timeout: 15_000 });
    await expect(row).toContainText("Browser specs: enrolled from the pilot console.");
    expect(await access()).toMatchObject({ enrolled: true, live_enabled: true });

    await row.getByRole("button", { name: /^Withdraw / }).click();
    await row.getByLabel("Reason for withdrawing", { exact: true }).fill("Browser specs: withdrawn from the pilot console.");
    await row.getByRole("button", { name: "Confirm withdrawal" }).click();
    await expect(row).toHaveCount(0, { timeout: 15_000 });
    expect(await access()).toMatchObject({ enrolled: false, live_enabled: false });
    await settle(page);
  });
});

for (const key of ["B", "C"] as const) {
  test.describe(`TRINETRA seeded ${key} organization`, () => {
    test.use({ user: `${key}.owner` });
    test("in the shipped pilot mode an organization nobody enrolled stays on the examples", async ({ page }) => {
      await page.goto(ws(key, "trinetra"));
      await expect(page.getByTestId("trinetra-access-not_enrolled")).toBeVisible();
      await expect(page.getByText("Illustrative synthetic data", { exact: true })).toBeVisible();
    });
  });
}
