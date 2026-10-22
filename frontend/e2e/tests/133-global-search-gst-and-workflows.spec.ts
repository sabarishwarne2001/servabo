/**
 * GLOBAL SEARCH FINDS GST SUPPLIERS, GST INVOICES AND WORKFLOWS (Final session 1, Phase 5). Ctrl+K: a supplier by name or GSTIN, an
 * invoice in the GST books by number, an automation rule by name. Each result opens its page already narrowed; a person who may not
 * see workflows is offered none; a workspace whose plan does not open the GST lists shows no GST result; the second workspace of
 * the organization is only searched for a person who holds a grant on it.
 */
import { test, expect } from "../support/fixtures";
import { api } from "../support/api";
import { gstin, gstr2b } from "../support/gst";
import { addMember, newCustomer, signInAs, type Customer } from "../support/journey";
import { createRuleViaApi, enterpriseCustomer } from "../support/workflow-helpers";

const BUYER = gstin("27", "AAACN1234F");
const SAHYADRI = gstin("27", "AABCS5555K");
const DECCAN = gstin("29", "AAGCD7777P");

const statement = (): string =>
  gstr2b(BUYER, "2026-09", [
    { gstin: SAHYADRI, name: "Sahyadri Packaging", docs: [{ number: "SAH-1001", date: "2026-09-05", taxable: 1_250_000 }] },
    { gstin: DECCAN, name: "Deccan Plastics", docs: [{ number: "DEC-2001", date: "2026-09-12", taxable: 480_000 }] },
  ]);

const importStatement = async (c: Customer, workspaceId: string): Promise<void> => {
  const form = new FormData();
  form.append("file", new Blob([statement()], { type: "application/json" }), "GSTR2B_092026.json");
  const sent = await api(c.session, "POST", `/workspaces/${workspaceId}/gst/returns`, form);
  expect(sent.status, sent.text.slice(0, 300)).toBe(200);
};

const palette = (page: import("@playwright/test").Page) => page.getByRole("dialog", { name: "Search pages and records" });

const searchFor = async (page: import("@playwright/test").Page, text: string): Promise<void> => {
  await page.keyboard.press("Control+k");
  await expect(palette(page)).toBeVisible();
  await palette(page).getByRole("combobox").fill(text);
};

test("a supplier, an invoice and a workflow are found, each opens narrowed, and the second workspace follows the person's grants", async ({ page, browser }) => {
  test.setTimeout(420_000);
  const customer = await enterpriseCustomer("searchgst");
  // A second workspace in the same organization, with its own books and workflow.
  const created = await api<{ id: string; slug: string }>(customer.session, "POST", `/organizations/${customer.orgId}/workspaces`, { workspace_name: "Branch office" });
  expect(created.status, created.text).toBeLessThan(300);
  const branch = created.body;
  await importStatement(customer, customer.wsId);
  await importStatement(customer, branch.id);
  await createRuleViaApi(customer, { name: "Chase Sahyadri late invoices", actions: [{ action_type: "notify.role", config: { roles: ["OWNER"], title: "Heads up", message: "Look at this." } }] });
  expect((await api(customer.session, "POST", `/workspaces/${branch.id}/automation/rules`, {
    name: "Branch only escalation", priority: 100, triggers: ["document.completed"], condition_groups: [], groups_operator: "AND",
    actions: [{ action_type: "notify.role", config: { roles: ["OWNER"], title: "Heads up", message: "Look at this." } }], else_actions: [], on_error: "CONTINUE", is_active: true,
  })).status).toBe(201);
  // A viewer with a grant on the first workspace only.
  const viewer = await addMember(customer, "searchgst-viewer", "MEMBER", "VIEWER");

  await signInAs(page, customer.email);
  await page.goto(customer.ws(""));
  await expect(page.locator("main")).toBeVisible({ timeout: 30_000 });

  // A supplier by part of its name: one result per workspace, each in plain words with its GSTIN.
  await searchFor(page, "sahyadri");
  const results = palette(page);
  await expect(results.getByText("GST suppliers").first()).toBeVisible({ timeout: 20_000 });
  await expect(results.getByText(new RegExp(`GSTIN ${SAHYADRI}`))).toHaveCount(2);
  await expect(results.getByText("Workflows").first()).toBeVisible();
  await expect(results.getByText("Chase Sahyadri late invoices")).toBeVisible();

  // Opening the supplier lands on the invoice list narrowed to it.
  await results.getByText(new RegExp(`GSTIN ${SAHYADRI}`)).first().click();
  await expect(page).toHaveURL(/\/gst\?tab=invoices&supplier=/);
  await expect(page.getByPlaceholder("Name or GSTIN")).toHaveValue(SAHYADRI, { timeout: 20_000 });
  await expect(page.getByText("SAH-1001").first()).toBeVisible({ timeout: 20_000 });
  await expect(page.getByText("DEC-2001")).toHaveCount(0);

  // An invoice by number, opened narrowed to that number.
  await searchFor(page, "dec-2001");
  await expect(palette(page).getByText("GST invoices").first()).toBeVisible({ timeout: 20_000 });
  await palette(page).getByText("DEC-2001").first().click();
  await expect(page).toHaveURL(/tab=invoices&number=DEC-2001/);
  await expect(page.getByPlaceholder("Invoice number")).toHaveValue("DEC-2001", { timeout: 20_000 });
  await expect(page.getByText("DEC-2001").first()).toBeVisible();

  // A workflow by name opens the Workflows page of its workspace.
  await searchFor(page, "chase sahyadri");
  await palette(page).getByText("Chase Sahyadri late invoices").click();
  await expect(page).toHaveURL(new RegExp(`/${customer.wsSlug}/automation`));

  // Text is matched literally: a wildcard finds nothing.
  await searchFor(page, "%%");
  await expect(palette(page).getByText("GST suppliers")).toHaveCount(0);
  await page.keyboard.press("Escape");

  // The viewer (granted the first workspace only) finds the supplier once and no workflow, and nothing from the second workspace.
  const ctx = await browser.newContext();
  const viewerPage = await ctx.newPage();
  try {
    await signInAs(viewerPage, viewer.email);
    await viewerPage.goto(customer.ws(""));
    await expect(viewerPage.locator("main")).toBeVisible({ timeout: 30_000 });
    await viewerPage.keyboard.press("Control+k");
    await viewerPage.getByRole("dialog", { name: "Search pages and records" }).getByRole("combobox").fill("sahyadri");
    const viewerResults = viewerPage.getByRole("dialog", { name: "Search pages and records" });
    await expect(viewerResults.getByText("GST suppliers").first()).toBeVisible({ timeout: 20_000 });
    await expect(viewerResults.getByText(new RegExp(`GSTIN ${SAHYADRI}`))).toHaveCount(1);
    await expect(viewerResults.getByText("Workflows")).toHaveCount(0);
    await expect(viewerResults.getByText("Branch office")).toHaveCount(0);
  } finally {
    await ctx.close();
  }
});

test("a workspace on a plan that does not open the GST lists shows no GST result, and the API says nothing about it", async ({ page }) => {
  test.setTimeout(240_000);
  const customer = await newCustomer("searchgst2", "Search Preview Ltd");
  await importStatement(customer, customer.wsId); // the preview (every plan) imports and shows the headline figures
  await signInAs(page, customer.email);
  await page.goto(customer.ws(""));
  await expect(page.locator("main")).toBeVisible({ timeout: 30_000 });
  await searchFor(page, "sahyadri");
  await expect(palette(page).getByText(/Nothing matches/).or(palette(page).getByRole("option")).first()).toBeVisible({ timeout: 20_000 });
  await expect(palette(page).getByText("GST suppliers")).toHaveCount(0);
  await expect(palette(page).getByText("GST invoices")).toHaveCount(0);
  const raw = await api<{ suppliers: unknown[]; gst_invoices: unknown[] }>(customer.session, "GET", `/organizations/${customer.orgId}/search?q=sahyadri`);
  expect(raw.body.suppliers).toEqual([]);
  expect(raw.body.gst_invoices).toEqual([]);
});
