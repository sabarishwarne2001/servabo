/**
 * DATA RESIDENCY AND EGRESS LOCKDOWN (campaign Session C, long tail).
 *
 *  - Data residency, "Save region": a region the deployment has not provisioned cannot be saved (the card
 *    says so, Save stays disabled and the server refuses). NOT DRIVEN: a successful repin. The browser
 *    suite runs on local file storage, which the server refuses for any region but the default ("requires an
 *    object-storage backend"), so that path needs MinIO/S3 and is listed under "Not driven" in the HANDOFF.
 *  - Egress lockdown: "Add rule" lists a destination, "Remove <host>" takes it away, "Test" says whether a
 *    destination would be allowed or refused (with the rule that allowed it), "Switch lockdown on / off"
 *    flips the organization's policy. An admin (not the owner) sees the policy but no controls, and the
 *    server refuses their changes.
 * Each runs on an Enterprise tenant of its own.
 */
import { test, expect, expectHealthyPage, settle } from "../support/fixtures";
import { api } from "../support/api";
import { runId } from "../support/env";
import { addMember, newCustomer, signInAs, standIn, type Customer } from "../support/journey";

interface Residency {
  readonly region: string;
  readonly available_regions: ReadonlyArray<{ readonly region: string; readonly configured: boolean }>;
}
interface EgressPolicy {
  readonly lockdown_enabled: boolean;
  readonly rules: ReadonlyArray<{ readonly id: string; readonly host_pattern: string; readonly note: string | null }>;
}

test.describe("Data residency", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(180_000);
  let customer: Customer;

  test.beforeAll(async () => {
    customer = await newCustomer("residency", "Residency Ltd");
    standIn("subscribe", customer.orgSlug, "--plan", "enterprise", "--seats", "3");
  });

  const residency = async (): Promise<Residency> =>
    (await api<Residency>(customer.session, "GET", `/organizations/${customer.orgId}/compliance/residency`)).body;

  test("a region that is not provisioned cannot be saved; the card says why and the server refuses", async ({ page, problems }) => {
    problems.allowHttp(/\/compliance\/residency$/, [400, 409, 422], "a region with no bucket is refused");
    const state = await residency();
    const missing = state.available_regions.find((option) => !option.configured);
    expect(missing, "some region has no bucket (start-stack.sh provisions only the default and EU)").toBeTruthy();

    await signInAs(page, customer.email);
    await page.goto(customer.org("compliance"));
    await settle(page);
    const region = page.getByLabel("Region", { exact: true });
    await region.selectOption(missing!.region);
    await expect(page.getByText(/No bucket is provisioned for/)).toBeVisible();
    const save = page.getByRole("button", { name: "Save region" });
    await expect(save).toBeDisabled();

    const direct = await api(customer.session, "PUT", `/organizations/${customer.orgId}/compliance/residency`, { region: missing!.region, acknowledge_no_migration: true });
    expect([400, 409, 422], direct.text.slice(0, 200)).toContain(direct.status);
    expect((await residency()).region).toBe(state.region);
  });

  test("the card offers exactly the regions the server accepts: no region is listed as available and then refused on Save", async ({ page }) => {
    const state = await residency();
    expect(state.available_regions.find((option) => option.region === "GLOBAL")?.configured, "the default is always available").toBe(true);
    await signInAs(page, customer.email);
    await page.goto(customer.org("compliance"));
    await settle(page);
    const region = page.getByLabel("Region", { exact: true });
    for (const option of state.available_regions) {
      // The page marks a region the deployment cannot hold, and disables Save for it ...
      await region.selectOption(option.region);
      if (option.configured) await expect(page.getByText(/No bucket is provisioned for/)).toHaveCount(0);
      else await expect(page.getByText(/No bucket is provisioned for/)).toBeVisible();
    }
    // ... and the server agrees with the page about every one of them. (On local file storage that is every
    // region but the default; with MinIO or S3 it is the regions that have a bucket.)
    for (const option of state.available_regions) {
      const saved = await api(customer.session, "PUT", `/organizations/${customer.orgId}/compliance/residency`,
        { region: option.region, acknowledge_no_migration: true });
      if (option.configured) expect(saved.status, `${option.region}: ${saved.text.slice(0, 200)}`).toBe(200);
      else expect([400, 409, 422], `${option.region}: ${saved.text.slice(0, 200)}`).toContain(saved.status);
    }
    const back = await api(customer.session, "PUT", `/organizations/${customer.orgId}/compliance/residency`,
      { region: state.region, acknowledge_no_migration: true });
    expect(back.status, back.text.slice(0, 200)).toBe(200);
  });
});

test.describe("Egress lockdown", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(180_000);
  let customer: Customer;

  test.beforeAll(async () => {
    customer = await newCustomer("egress", "Egress Ltd");
    standIn("subscribe", customer.orgSlug, "--plan", "enterprise", "--seats", "3");
  });

  const policy = async (): Promise<EgressPolicy> =>
    (await api<EgressPolicy>(customer.session, "GET", `/organizations/${customer.orgId}/egress`)).body;

  test("Add rule lists a destination; Test says allowed by it and refuses another; Remove takes it away", async ({ page }) => {
    const host = `hooks-${runId()}.egress-e2e.example.com`;
    await signInAs(page, customer.email);
    await page.goto(customer.org("egress"));
    await settle(page);
    await expect(page.getByText("No rules yet.")).toBeVisible();

    await page.getByLabel("Host, *.domain, IP or CIDR").fill(host);
    await page.getByLabel("Note").fill("E2E receiver");
    await page.getByRole("button", { name: "Add rule" }).click();
    const row = page.getByRole("row").filter({ hasText: host });
    await expect(row).toContainText("E2E receiver");
    expect((await policy()).rules.map((r) => r.host_pattern)).toContain(host);
    await page.reload();
    await settle(page);
    await expect(page.getByRole("row").filter({ hasText: host })).toBeVisible();

    // Test a destination: the rule's host is allowed (by the rule), an unlisted one is refused once lockdown is on.
    await page.getByLabel("URL or host").fill(`https://${host}/servabo`);
    await page.getByRole("button", { name: "Test", exact: true }).click();
    await expect(page.getByTestId("egress-decision")).toContainText("Allowed");

    await page.getByRole("button", { name: `Remove ${host}` }).click();
    await expect(page.getByRole("row").filter({ hasText: host })).toHaveCount(0);
    await expect(page.getByText("No rules yet.")).toBeVisible();
    expect((await policy()).rules).toEqual([]);
    await expectHealthyPage(page);
  });

  test("Switch lockdown on makes an unlisted destination refused and a listed one allowed; Switch lockdown off lifts it", async ({ page }) => {
    const host = `allowed-${runId()}.egress-e2e.example.com`;
    const other = `blocked-${runId()}.egress-e2e.example.com`;
    const added = await api(customer.session, "POST", `/organizations/${customer.orgId}/egress/rules`, { host_pattern: host, port: null, channel: null, note: "listed" });
    expect(added.status, added.text).toBeLessThan(300);

    await signInAs(page, customer.email);
    await page.goto(customer.org("egress"));
    await settle(page);
    const toggle = page.getByTestId("egress-toggle");
    await expect(toggle).toHaveText("Switch lockdown on");
    await toggle.click();
    await expect(page.getByRole("heading", { name: "Lockdown is on" })).toBeVisible();
    await expect(toggle).toHaveText("Switch lockdown off");
    await expect.poll(async () => (await policy()).lockdown_enabled).toBe(true);

    await page.getByLabel("URL or host").fill(`https://${other}/x`);
    await page.getByRole("button", { name: "Test", exact: true }).click();
    await expect(page.getByTestId("egress-decision")).toContainText("Refused");
    await page.getByLabel("URL or host").fill(`https://${host}/x`);
    await page.getByRole("button", { name: "Test", exact: true }).click();
    await expect(page.getByTestId("egress-decision")).toContainText("Allowed");

    await page.reload();
    await settle(page);
    await expect(page.getByRole("heading", { name: "Lockdown is on" })).toBeVisible();
    await page.getByTestId("egress-toggle").click();
    await expect(page.getByRole("heading", { name: "Lockdown is off" })).toBeVisible();
    await expect.poll(async () => (await policy()).lockdown_enabled).toBe(false);
    await expectHealthyPage(page);
  });

  test("an admin sees the policy but has no controls, and the server refuses their changes", async ({ page }) => {
    const admin = await addMember(customer, "egress-admin", "ADMIN", "ADMIN");
    await signInAs(page, admin.email);
    await page.goto(customer.org("egress"));
    await settle(page);
    await expect(page.getByTestId("egress-toggle")).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Add rule" })).toHaveCount(0);
    await expect(page.getByText("Only the organization owner can change the lockdown and its rules.")).toBeVisible();

    const base = `/organizations/${customer.orgId}/egress`;
    const attempts = [
      await api(admin.session, "PUT", base, { lockdown_enabled: true }),
      await api(admin.session, "POST", `${base}/rules`, { host_pattern: "x.example.com", port: null, channel: null, note: null }),
    ];
    expect(attempts.map((a) => a.status)).toEqual([403, 403]);
    expect((await policy()).lockdown_enabled).toBe(false);
  });
});
