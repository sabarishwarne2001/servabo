/**
 * DOCUMENT PACKS DO WHAT THEY PROMISE (Final session 1, Phase 6; F-408).
 *
 *   - Enabling a pack proposes its suggested checks under Clause assertions. Nothing is added until an administrator clicks; one click
 *     adds the check and switches it on; a check read by an AI model says so on its button; "Not for us" is remembered.
 *   - The Redact menu on a document the pack recognises offers the pack's profile first (focused) and says why; a document it does
 *     not recognise gets no suggestion; with the pack off there is none.
 *   - A contributor is shown none of it.
 */
import { test, expect, settle } from "../support/fixtures";
import { api, uploadFile } from "../support/api";
import { addMember, signInAs, type Customer } from "../support/journey";
import { enterpriseCustomer, pdfOnDisk, processed } from "../support/workflow-helpers";

interface Pack {
  readonly id: string;
  readonly document_type: string;
  readonly label: string;
  readonly applied: boolean;
  readonly enabled: boolean;
  readonly redaction_profile: string | null;
}

async function pack(c: Customer, documentType: string): Promise<Pack> {
  const listed = await api<Pack[]>(c.session, "GET", `/workspaces/${c.wsId}/document-presets`);
  expect(listed.status, listed.text.slice(0, 300)).toBe(200);
  const found = listed.body.find((p) => p.document_type === documentType);
  expect(found, `the ${documentType} pack exists`).toBeTruthy();
  return found!;
}

async function enable(c: Customer, documentType: string, on = true): Promise<Pack> {
  const found = await pack(c, documentType);
  if (!found.applied) {
    const applied = await api(c.session, "POST", `/workspaces/${c.wsId}/document-presets/apply`, { preset_id: found.id });
    expect(applied.status, applied.text.slice(0, 200)).toBe(200);
  }
  const toggled = await api(c.session, "POST", `/workspaces/${c.wsId}/document-presets/${found.id}/enabled`, { enabled: on });
  expect(toggled.status, toggled.text.slice(0, 200)).toBe(200);
  return found;
}

const clauseChecks = async (c: Customer): Promise<Array<{ is_active: boolean; definition: { sentence: string } | null }>> => {
  const listed = await api<Array<{ is_active: boolean; definition: { sentence: string } | null }>>(
    c.session, "GET", `/workspaces/${c.wsId}/assertions/clause-checks`);
  expect(listed.status, listed.text.slice(0, 200)).toBe(200);
  return listed.body;
};

const NDA_LINES = [
  "Mutual Non-Disclosure Agreement",
  "Between Northwind Traders Ltd (Disclosing Party) and Contoso LLC (Receiving Party).",
  "Confidential Information means all non-public business information.",
  "Effective date: 1 October 2026. Term: 36 months. Governing law: England and Wales.",
];

test("an enabled pack proposes its checks; one click adds one, an AI-read one says so, and a declined one stays away", async ({ page }) => {
  test.setTimeout(240_000);
  const customer = await enterpriseCustomer("packchk");
  await enable(customer, "msa");
  await enable(customer, "nda");
  await signInAs(page, customer.email);
  await page.goto(customer.ws("assertions"));
  await settle(page);

  const section = page.getByTestId("pack-check-proposals");
  await expect(section.getByRole("heading", { name: "Suggested by your document packs" })).toBeVisible({ timeout: 30_000 });
  expect(await clauseChecks(customer), "enabling the packs added nothing by itself").toEqual([]);

  // A check the engine can read without a model: one click.
  const typed = section.getByRole("listitem").filter({ hasText: "A limitation of liability is present." });
  await expect(typed).toContainText("Understood as");
  await expect(typed).not.toContainText("An AI model reads this check");
  await typed.getByRole("button", { name: "Add this check" }).click();
  await expect(section.getByText("A limitation of liability is present.")).toHaveCount(0, { timeout: 20_000 });
  await expect(page.getByRole("heading", { name: "Clause checks" })).toBeVisible();
  await expect(page.getByText(/limitation of liability is present/i).first()).toBeVisible();
  const added = await clauseChecks(customer);
  expect(added).toHaveLength(1);
  expect(added[0]!.is_active, "a check added from a pack is switched on").toBe(true);

  // A check an AI model reads says so, on the card and on the button.
  const ai = section.getByRole("listitem").filter({ hasText: "A governing law is named." });
  await expect(ai).toContainText("An AI model reads this check");
  await expect(ai.getByRole("button", { name: "Add this check" })).toHaveCount(0);
  await ai.getByRole("button", { name: "Add, read by an AI model" }).click();
  await expect.poll(async () => (await clauseChecks(customer)).length, { timeout: 20_000 }).toBe(2);

  // Turned down: gone now, and not proposed again after a reload.
  const payment = section.getByRole("listitem").filter({ hasText: "Payment terms are no longer than 60 days." });
  await payment.getByRole("button", { name: "Not for us" }).click();
  await expect(payment).toHaveCount(0, { timeout: 20_000 });
  await page.reload();
  await settle(page);
  await expect(page.getByText("Payment terms are no longer than 60 days.")).toHaveCount(0);
  await expect(page.getByText("A limitation of liability is present.", { exact: true })).toHaveCount(0);
  expect((await clauseChecks(customer)).length, "declining added nothing").toBe(2);
});

test("a contributor is shown none of the suggestions", async ({ page }) => {
  test.setTimeout(180_000);
  const customer = await enterpriseCustomer("packchk2");
  await enable(customer, "msa");
  const contributor = await addMember(customer, "packchk2-contrib", "MEMBER", "CONTRIBUTOR");
  await signInAs(page, contributor.email);
  await page.goto(customer.ws("assertions"));
  await settle(page);
  await expect(page.getByTestId("pack-check-proposals")).toHaveCount(0);
  const refused = await api(contributor.session, "GET", `/workspaces/${customer.wsId}/document-presets/check-proposals`);
  expect(refused.status).toBe(403);
});

test("the Redact menu offers the pack's profile first on a document the pack recognises, and only there", async ({ page }) => {
  test.setTimeout(420_000);
  const customer = await enterpriseCustomer("packred");
  const nda = await enable(customer, "nda");
  const matching = await uploadFile(customer.session, customer.wsId, pdfOnDisk("nda", NDA_LINES));
  expect(matching.status, matching.text.slice(0, 200)).toBeLessThan(300);
  const plain = await uploadFile(customer.session, customer.wsId, pdfOnDisk("notes", ["Weekly stand-up notes", "Nothing about agreements"]));
  expect(plain.status, plain.text.slice(0, 200)).toBeLessThan(300);
  const matchingId = String(matching.body.id);
  const plainId = String(plain.body.id);
  await processed(customer, matchingId);
  await processed(customer, plainId);

  await signInAs(page, customer.email);
  await page.goto(customer.ws(`work-items/${matchingId}`));
  await settle(page);
  await page.getByRole("button", { name: "Redact" }).click();
  const menu = page.getByRole("menu", { name: "Redaction profile" });
  await expect(menu).toBeVisible();
  const first = menu.getByRole("menuitem").first();
  await expect(first).toHaveAttribute("data-suggested", "true", { timeout: 20_000 });
  await expect(first).toContainText(/Financial|All identifiers|India KYC|HIPAA Safe Harbor/);
  await expect(first).toContainText(`Suggested by your ${nda.label} pack`);
  await expect(first).toBeFocused();
  await page.keyboard.press("Escape");

  await page.goto(customer.ws(`work-items/${plainId}`));
  await settle(page);
  await page.getByRole("button", { name: "Redact" }).click();
  await expect(page.getByRole("menu", { name: "Redaction profile" })).toBeVisible();
  await expect(page.getByText(/Suggested by your/)).toHaveCount(0);

  // With the pack off, the document the pack recognised is offered nothing either.
  await enable(customer, "nda", false);
  await page.goto(customer.ws(`work-items/${matchingId}`));
  await settle(page);
  await page.getByRole("button", { name: "Redact" }).click();
  await expect(page.getByRole("menu", { name: "Redaction profile" })).toBeVisible();
  await expect(page.getByText(/Suggested by your/)).toHaveCount(0);
});
