/**
 * TRINETRA by role and by plan (Final session 2T, Phase 8): owner, workspace administrator and viewer on Enterprise; the owner on
 * Business. The screens show write forms only to someone the server lets write, the Approvals tab only on Enterprise, and the
 * policy form only to an organization owner or admin. In each case the server is asked too: what the screen hides is refused.
 */
import { test, expect } from "../support/fixtures";
import { api } from "../support/api";
import { signInAs } from "../support/journey";
import { bookInvoice, createCase, createProfile, liveCustomer, PAN, type LiveCustomer } from "../support/trinetra";

let enterprise: LiveCustomer;
let business: LiveCustomer;
let caseId: string;

test.describe("TRINETRA roles and plans", () => {
  test.setTimeout(300_000);
  test.beforeAll(async () => {
    enterprise = await liveCustomer("tr-roles-e", "enterprise", { people: true });
    const profile = await createProfile(enterprise);
    const invoice = await bookInvoice(enterprise, "TRR-1");
    caseId = (await createCase(enterprise, profile, invoice, "TRR-1")).id;
    business = await liveCustomer("tr-roles-b", "business");
    await createProfile(business);
  });

  test("the owner on Enterprise sees every tab, the write forms and the review controls", async ({ page }) => {
    await signInAs(page, enterprise.email);
    await page.goto(enterprise.ws("trinetra"));
    for (const name of ["Cases", "Statements", "Suggestions", "Reversals", "Approvals", "Closures"]) {
      await expect(page.getByRole("tab", { name })).toBeVisible();
    }
    await expect(page.getByText("Add reviewed evidence", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: /Synthetic Deductor Ltd/ }).click();
    const insight = page.getByRole("complementary", { name: "Case insight" });
    await expect(insight.getByRole("button", { name: "Record review", exact: true })).toBeVisible();
    await page.getByRole("tab", { name: "Statements" }).click();
    await expect(page.getByTestId("trinetra-import")).toBeVisible();
    await page.getByRole("tab", { name: "Approvals" }).click();
    await expect(page.getByTestId("trinetra-policy")).toBeVisible();
    await expect(page.getByRole("button", { name: "Save the policy" })).toBeVisible();
  });

  test("a workspace administrator who is not an organization admin writes evidence but cannot set the policy", async ({ page }) => {
    await signInAs(page, enterprise.admin!.email);
    await page.goto(enterprise.ws("trinetra"));
    await expect(page.getByText("Add reviewed evidence", { exact: true })).toBeVisible();
    await page.getByRole("tab", { name: "Approvals" }).click();
    await expect(page.getByText("Only an organization owner or admin changes the policy.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Save the policy" })).toHaveCount(0);
    const refused = await api(enterprise.admin!.session, "PUT", `/organizations/${enterprise.orgId}/trinetra/policy`, {
      threshold: "1000", actions: ["CA_REVIEWED"], approver_role: "OWNER",
    });
    expect([401, 403], refused.text).toContain(refused.status);
  });

  test("a viewer reads the cases and the evidence but is offered no way to write", async ({ page }) => {
    await signInAs(page, enterprise.viewer!.email);
    await page.goto(enterprise.ws("trinetra"));
    await expect(page.getByRole("button", { name: /Synthetic Deductor Ltd/ })).toBeVisible();
    await expect(page.getByText("Add reviewed evidence", { exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Export CSV", exact: true })).toHaveCount(0);
    await page.getByRole("button", { name: /Synthetic Deductor Ltd/ }).click();
    const insight = page.getByRole("complementary", { name: "Case insight" });
    await expect(insight).toContainText("₹2,000.00");
    await expect(insight.getByRole("button", { name: "Record review", exact: true })).toHaveCount(0);
    await page.getByRole("tab", { name: "Statements" }).click();
    await expect(page.getByTestId("trinetra-import")).toHaveCount(0);
    await expect(page.getByText("Only a workspace administrator imports a statement.")).toBeVisible();
    await page.getByRole("tab", { name: "Suggestions" }).click();
    await expect(page.getByRole("button", { name: /Accept/ })).toHaveCount(0);

    const url = `/workspaces/${enterprise.wsId}/trinetra`;
    const viewer = enterprise.viewer!.session;
    expect((await api(viewer, "GET", `${url}/credits`)).status).toBe(200);
    for (const [route, body] of [
      ["/profiles", { name: "Nope", pan: PAN }],
      [`/credits/${caseId}/decisions`, { revision: 1, action: "EXPLAINED", reason: "A viewer tries to decide." }],
      [`/credits/${caseId}/inquiries`, { document_kind: "CERTIFICATE" }],
      ["/suggestions/scan", {}],
    ] as const) {
      const refused = await api(viewer, "POST", url + route, body);
      expect(refused.status, `${route}: ${refused.text}`).toBe(403);
    }
  });

  test("Business has no Approvals tab and no approval chain; the owner still writes", async ({ page }) => {
    await signInAs(page, business.email);
    await page.goto(business.ws("trinetra"));
    await expect(page.getByRole("tab", { name: "Statements" })).toBeVisible();
    await expect(page.getByRole("tab", { name: "Approvals" })).toHaveCount(0);
    await expect(page.getByText("Add reviewed evidence", { exact: true })).toBeVisible();
    const chain = await api(business.session, "PUT", `/organizations/${business.orgId}/trinetra/policy`, {
      threshold: "1000", actions: ["CA_REVIEWED"], approver_role: "OWNER",
    });
    expect(chain.status, chain.text).toBe(402);
    const cross = await api(business.session, "GET", `/organizations/${business.orgId}/trinetra/cases`);
    expect([402, 403], cross.text).toContain(cross.status);
  });
});
