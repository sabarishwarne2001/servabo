/**
 * REVOPS CONSOLE, THE MONEY ACTIONS (Platform -> Revenue operations; campaign session C).
 *
 * The platform super-admin's console moves real money records: it publishes plan price books (which
 * retire the book in force), creates promo codes, and runs invoiced enterprise contracts (activate,
 * issue invoices, mark paid, void, cancel) and the dispute hold. Spec 47 only opens the price-book
 * dialog and keeps the draft, and spec 26 pays and cancels one contract; nothing pressed Publish,
 * Create code, Void, Issue due invoices or Lift. Each is clicked here in the real browser and then
 * proved through the API (and the customer's audit trail, which is where a contract change is
 * recorded).
 *
 * SHARED STATE. Price books and promo codes are global to the whole e2e database. The console accepts
 * only USD and INR; USD prices are read by other specs, so this spec never touches a USD book and
 * proves that the USD books and the public USD prices are the same before and after. It publishes
 * one INR book of its own (the only other currency there is). Promo codes, organizations, contracts
 * and invoices are all created here, with unique names, and only those are changed.
 */
import { test, expect, expectHealthyPage, settle } from "../support/fixtures";
import { api, loginAs, type ApiSession } from "../support/api";
import { DODO_ORIGIN, runId } from "../support/env";
import { newCustomer, standIn, type Customer } from "../support/journey";

interface BookSummary {
  id: string; code: string; currency: string; status: string; content_digest: string | null;
  published_at: string | null; retired_at: string | null; entries: number;
}
interface BookDetail extends Omit<BookSummary, "entries"> {
  entries: Array<{ id: string; tier_key: string; billing_interval: string; unit_amount_micros: number; gateway_price_id: string | null }>;
}
interface Promo {
  id: string; code: string; percent_off: number | null; amount_off_micros: number | null; currency: string | null;
  duration: string; duration_in_months: number | null; max_redemptions: number | null; times_redeemed: number;
  gateway_coupon_id: string | null; is_active: boolean;
}
interface Invoice {
  id: string; invoice_number: string; status: string; subtotal_micros: number; discount_micros: number;
  tax_micros: number; total_micros: number; payment_reference: string | null; void_reason: string | null;
  paid_at: string | null; period_start: string;
}
interface Contract {
  id: string; contract_number: string; status: string; end_reason: string | null; organization_id: string; invoices: Invoice[];
}
interface Dispute {
  id: string; organization_id: string; gateway_dispute_id: string; status: string; holding_read_only: boolean;
  cleared_at: string | null; cleared_reason: string | null;
}
interface PublicPricing {
  plans: Array<{ key: string; prices: Array<{ interval: string; currency: string; unit_amount: number }> }>;
}
interface AuditPage { items: Array<{ action: string; resource_type: string; details: Record<string, string> | null }> }

const money = (minor: number): number => minor * 10_000; // the API keeps micros: 1 minor unit = 10,000 micros

async function booksOf(session: ApiSession): Promise<BookSummary[]> {
  const listed = await api<BookSummary[]>(session, "GET", "/admin/revops/price-books");
  expect(listed.status, listed.text.slice(0, 300)).toBe(200);
  return listed.body;
}

/** Every USD book that is not a draft (drafts are other specs' scratch work), as a comparable string. */
const usdBooksNow = async (session: ApiSession): Promise<string> =>
  JSON.stringify(
    (await booksOf(session))
      .filter((b) => b.currency === "USD" && b.status !== "DRAFT")
      .map((b) => [b.id, b.code, b.status, b.content_digest, b.retired_at])
      .sort(),
  );

/** The public price list for USD (what customers are charged), as a comparable string. */
async function usdPublicPrices(): Promise<string> {
  const pricing = await api<PublicPricing>(null, "GET", "/pricing");
  expect(pricing.status).toBe(200);
  return JSON.stringify(
    pricing.body.plans.map((plan) => [plan.key, plan.prices.filter((p) => p.currency === "USD")]),
  );
}

async function contractOf(session: ApiSession, id: string): Promise<Contract> {
  const found = await api<Contract>(session, "GET", `/admin/revops/contracts/${id}`);
  expect(found.status, found.text.slice(0, 300)).toBe(200);
  return found.body;
}

/** What the customer's owner sees in the organization's audit trail: the `operation` of each billing change. */
async function auditOperations(customer: Customer): Promise<string[]> {
  const page = await api<AuditPage>(customer.session, "GET", `/organizations/${customer.orgId}/audit-logs?limit=100`);
  expect(page.status, page.text.slice(0, 300)).toBe(200);
  return page.body.items
    .filter((row) => row.resource_type === "BILLING_ACCOUNT")
    .map((row) => row.details?.operation ?? row.details?.event ?? "")
    .filter(Boolean);
}

const isoDay = (offsetDays: number): string => new Date(Date.now() + offsetDays * 86_400_000).toISOString().slice(0, 10);

test.describe("RevOps price books: Publish", () => {
  test.use({ user: "P.superadmin" });

  test("a draft is filled, the dialog is kept once, then Publish retires the one in force and leaves USD alone", async ({ page, session }) => {
    const usdBooksBefore = await usdBooksNow(session!);
    const usdPricesBefore = await usdPublicPrices();
    const inForceBefore = (await booksOf(session!)).find((b) => b.currency === "INR" && b.status === "PUBLISHED");

    const code = `E2E-INR-${runId()}`.toUpperCase();
    await page.goto("/admin/revops?tab=books");
    await page.getByLabel("New book code").fill(code);
    await page.getByLabel("Currency").selectOption("INR");
    await page.getByRole("button", { name: "Draft book" }).click();
    const heading = page.getByRole("heading", { name: new RegExp(`${code} · INR · DRAFT`) });
    await expect(heading).toBeVisible();
    // An empty book cannot be published: the button is off.
    await expect(page.getByRole("button", { name: "Publish", exact: true })).toBeDisabled();

    const setPrice = async (plan: string, interval: string, amount: string): Promise<void> => {
      await page.getByLabel("Plan").selectOption(plan);
      await page.getByLabel("Interval").selectOption(interval);
      await page.getByLabel("Price (INR)").fill(amount);
      await page.getByRole("button", { name: "Set price" }).click();
      await expect(page.getByRole("button", { name: `Remove ${plan} ${interval}` })).toBeVisible();
    };
    await setPrice("business", "year", "24000");
    await setPrice("business", "month", "2500");
    await setPrice("developer", "year", "9000");
    await expect(page.getByRole("button", { name: "Publish", exact: true })).toBeEnabled();

    // The draft in the database is what the page shows.
    const draft = (await booksOf(session!)).find((b) => b.code === code);
    expect(draft?.status).toBe("DRAFT");
    expect(draft?.entries).toBe(3);
    const draftId = draft!.id;

    // Remove one price: it goes from the page and from the book.
    await page.getByRole("button", { name: "Remove developer year" }).click();
    await expect(page.getByRole("button", { name: "Remove developer year" })).toHaveCount(0);
    await expect.poll(async () => (await api<BookDetail>(session, "GET", `/admin/revops/price-books/${draftId}`)).body.entries.length).toBe(2);

    // The dialog names what it retires; "Keep the draft" publishes nothing.
    await page.getByRole("button", { name: "Publish", exact: true }).click();
    const confirm = page.getByRole("alertdialog", { name: new RegExp(`Publish ${code}`) });
    await expect(confirm).toContainText(/cannot be changed/i);
    await expect(confirm).toContainText(inForceBefore ? `${inForceBefore.code}, in force now, is retired.` : "It is the first INR price book.");
    await confirm.getByRole("button", { name: "Keep the draft" }).click();
    await expect(confirm).toHaveCount(0);
    await expect(heading).toBeVisible();
    expect((await api<BookDetail>(session, "GET", `/admin/revops/price-books/${draftId}`)).body.status).toBe("DRAFT");

    // Publish for real.
    await page.getByRole("button", { name: "Publish", exact: true }).click();
    await confirm.getByRole("button", { name: "Publish", exact: true }).click();
    await expect(page.getByRole("heading", { name: new RegExp(`${code} · INR · PUBLISHED`) })).toBeVisible();
    await expect(page.getByText(inForceBefore ? `${code} is published; ${inForceBefore.code} is retired.` : `${code} is published.`)).toBeVisible();
    await expect(page.getByText("A published book is immutable; draft a new one to change prices.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Publish", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^Remove / })).toHaveCount(0);

    // The database agrees: mine is the one INR book in force, with a digest and the two prices;
    // the one it replaced is retired.
    const mine = await api<BookDetail>(session, "GET", `/admin/revops/price-books/${draftId}`);
    expect(mine.body.status).toBe("PUBLISHED");
    expect(mine.body.content_digest).toMatch(/^[0-9a-f]{64}$/);
    expect(mine.body.published_at).not.toBeNull();
    expect(mine.body.entries.map((e) => [e.tier_key, e.billing_interval, e.unit_amount_micros]).sort()).toEqual([
      ["business", "month", money(250_000)],
      ["business", "year", money(2_400_000)],
    ]);
    await expect(page.getByText(new RegExp(`digest ${mine.body.content_digest!.slice(0, 12)}`))).toBeVisible();
    const inr = (await booksOf(session!)).filter((b) => b.currency === "INR");
    expect(inr.filter((b) => b.status === "PUBLISHED").map((b) => b.code)).toEqual([code]);
    if (inForceBefore) {
      const old = inr.find((b) => b.id === inForceBefore.id);
      expect(old?.status).toBe("RETIRED");
      expect(old?.retired_at).not.toBeNull();
    }

    // The customers' price list now sells the plan in rupees, and the dollar prices did not move.
    const pricing = await api<PublicPricing>(null, "GET", "/pricing");
    const business = pricing.body.plans.find((plan) => plan.key === "business");
    expect(business?.prices).toContainEqual({ interval: "year", currency: "INR", unit_amount: 2_400_000 });
    expect(await usdPublicPrices()).toBe(usdPricesBefore);
    expect(await usdBooksNow(session!)).toBe(usdBooksBefore);

    // Published is final, on the server too (draft-only routes answer 409 BOOK_NOT_DRAFT).
    const again = await api(session, "POST", `/admin/revops/price-books/${draftId}/publish`);
    expect(again.status).toBe(409);
    expect(again.text).toContain("BOOK_NOT_DRAFT");
    const change = await api(session, "PUT", `/admin/revops/price-books/${draftId}/entries`, {
      tier_key: "business", interval: "month", unit_amount: 1, gateway_price_id: null,
    });
    expect(change.status).toBe(409);
    expect(change.text).toContain("BOOK_NOT_DRAFT");

    // After a reload the page still shows it published, with no way to edit.
    await page.reload();
    await page.getByRole("button", { name: new RegExp(`^${code} ·`) }).click();
    await expect(page.getByRole("heading", { name: new RegExp(`${code} · INR · PUBLISHED`) })).toBeVisible();
    await expect(page.getByRole("button", { name: "Publish", exact: true })).toHaveCount(0);
    await expectHealthyPage(page);
  });
});

test.describe("RevOps promo codes: Create code", () => {
  test.use({ user: "P.superadmin" });

  test("a code is created, switched off and on, and a duplicate is refused", async ({ page, session, problems }) => {
    const code = `E2EP${runId()}`.toUpperCase().slice(0, 20);
    const amountCode = `E2EA${runId()}`.toUpperCase().slice(0, 20);
    const before = await api<Promo[]>(session, "GET", "/admin/revops/promo-codes");
    const othersBefore = JSON.stringify(before.body.map((p) => [p.code, p.is_active, p.times_redeemed]).sort());

    await page.goto("/admin/revops?tab=promos");
    const form = page.locator("form", { has: page.getByRole("button", { name: "Create code" }) });
    const create = form.getByRole("button", { name: "Create code" });
    await expect(create).toBeDisabled(); // needs a code and a value
    await form.getByLabel("Code", { exact: true }).fill(code);
    await form.getByLabel("Percent", { exact: true }).fill("15");
    await form.getByLabel("Duration").selectOption("REPEATING");
    await form.getByLabel("Months").fill("4");
    await form.getByLabel("Redemption cap").fill("5");
    await create.click();
    await expect(page.getByText("Promo code created.")).toBeVisible();
    const row = page.getByRole("row", { name: new RegExp(code) });
    await expect(row).toContainText("15%");
    await expect(row).toContainText("4 months");
    await expect(row).toContainText("0 / 5");
    await expect(row).toContainText("contracts only");
    await expect(form.getByLabel("Code", { exact: true })).toHaveValue(""); // the form cleared itself

    // An amount off, in rupees, with no cap.
    await form.getByLabel("Code", { exact: true }).fill(amountCode);
    await form.getByLabel("Kind").selectOption("amount");
    await form.getByLabel("Duration").selectOption("ONCE");
    await form.getByLabel("Redemption cap").fill("");
    await form.getByLabel("Amount", { exact: true }).fill("500");
    await form.getByLabel("Currency").selectOption("INR");
    await create.click();
    await expect(page.getByRole("row", { name: new RegExp(amountCode) })).toContainText(/₹\s?500\.00/);

    const listed = await api<Promo[]>(session, "GET", "/admin/revops/promo-codes");
    const percent = listed.body.find((p) => p.code === code);
    expect(percent).toMatchObject({
      percent_off: 15, amount_off_micros: null, duration: "REPEATING", duration_in_months: 4,
      max_redemptions: 5, times_redeemed: 0, gateway_coupon_id: null, is_active: true,
    });
    const amount = listed.body.find((p) => p.code === amountCode);
    expect(amount).toMatchObject({
      percent_off: null, amount_off_micros: money(50_000), currency: "INR", duration: "ONCE", max_redemptions: null, is_active: true,
    });

    // Deactivate and activate, each proved after a reload.
    await row.getByRole("button", { name: "Deactivate" }).click();
    await expect(row.getByRole("button", { name: "Activate" })).toBeVisible();
    await expect.poll(async () => (await api<Promo[]>(session, "GET", "/admin/revops/promo-codes")).body.find((p) => p.code === code)?.is_active).toBe(false);
    await page.reload();
    await expect(page.getByRole("row", { name: new RegExp(code) }).getByRole("button", { name: "Activate" })).toBeVisible();
    await page.getByRole("row", { name: new RegExp(code) }).getByRole("button", { name: "Activate" }).click();
    await expect(page.getByRole("row", { name: new RegExp(code) }).getByRole("button", { name: "Deactivate" })).toBeVisible();
    await expect.poll(async () => (await api<Promo[]>(session, "GET", "/admin/revops/promo-codes")).body.find((p) => p.code === code)?.is_active).toBe(true);

    // The same code twice: the server refuses (409) and the page says so; nothing is duplicated.
    problems.allowHttp(/\/admin\/revops\/promo-codes$/, [409], "creating a code that exists is refused");
    await form.getByLabel("Code", { exact: true }).fill(code.toLowerCase());
    await form.getByLabel("Kind").selectOption("percent");
    await form.getByLabel("Percent", { exact: true }).fill("20");
    await create.click();
    await expect(page.getByText(/could not be created|already|taken|exists/i).first()).toBeVisible();
    const after = await api<Promo[]>(session, "GET", "/admin/revops/promo-codes");
    expect(after.body.filter((p) => p.code === code)).toHaveLength(1);
    expect(after.body.find((p) => p.code === code)?.percent_off).toBe(15);

    // No other code was touched.
    const others = after.body.filter((p) => p.code !== code && p.code !== amountCode);
    expect(JSON.stringify(others.map((p) => [p.code, p.is_active, p.times_redeemed]).sort())).toBe(othersBefore);
    await expectHealthyPage(page);
  });
});

test.describe("RevOps contracts: Activate, Void, Issue due invoices, Mark paid, Cancel", () => {
  test.use({ user: "P.superadmin" });

  test("a contract's invoices are voided, issued again, paid and the contract cancelled, each audited", async ({ page, session }) => {
    const customer = await newCustomer("revops", `RevOps Customer ${runId()}`);
    const number = `E2E-RV-${runId()}`.toUpperCase();
    const promoCode = `E2EC${runId()}`.toUpperCase().slice(0, 20);
    const promo = await api<Promo>(session, "POST", "/admin/revops/promo-codes", { code: promoCode, percent_off: 10, duration: "ONCE" });
    expect(promo.status, promo.text).toBe(201);
    // A monthly contract that began yesterday: exactly the first period has started.
    const drafted = await api<Contract>(session, "POST", "/admin/revops/contracts", {
      organization_id: customer.orgId, contract_number: number, tier_key: "business", seats: 5, currency: "INR",
      billing_interval: "month", amount_per_period: 100_000, tax_rate_bps: 1800, term_start: isoDay(-1), term_end: isoDay(89),
      payment_terms_days: 30, promo_code: promoCode,
    });
    expect(drafted.status, drafted.text).toBe(201);
    const contractId = drafted.body.id;
    expect(drafted.body.status).toBe("DRAFT");

    await page.goto("/admin/revops?tab=contracts");
    await page.getByRole("row", { name: new RegExp(number) }).click();
    const detail = page.getByTestId("contract-detail");
    await expect(detail).toContainText(number);
    await expect(detail).toContainText("DRAFT");
    await expect(detail.getByRole("button", { name: "Issue due invoices" })).toHaveCount(0); // only an active contract issues

    // Activate: the organization is put on the plan, the first period is invoiced with the promo's 10%.
    await detail.getByRole("button", { name: "Activate" }).click();
    await expect(page.getByText("Contract activated. The organization is on the contract's plan.")).toBeVisible();
    await expect(detail).toContainText("ACTIVE");
    const first = detail.getByRole("row", { name: new RegExp(`${number}-001`) });
    await expect(first).toContainText("ISSUED");
    let contract = await contractOf(session!, contractId);
    expect(contract.status).toBe("ACTIVE");
    expect(contract.invoices).toHaveLength(1);
    const original = contract.invoices[0]!;
    expect(original.invoice_number).toBe(`${number}-001`);
    expect(original.subtotal_micros).toBe(money(100_000));
    expect(original.discount_micros).toBe(money(10_000));
    expect(original.tax_micros).toBe(money(16_200)); // 18% of the discounted 900.00
    expect(original.total_micros).toBe(money(106_200));
    const uses = await api<Array<{ organization_id: string; status: string; contract_number: string | null }>>(
      session, "GET", `/admin/revops/promo-codes/${promo.body.id}/redemptions`);
    expect(uses.body.map((u) => [u.organization_id, u.contract_number])).toEqual([[customer.orgId, number]]);

    // A customer cannot settle or void their own invoice: the platform routes are not theirs.
    for (const [route, body] of [["pay", { reference: "SELF-PAID" }], ["void", { reason: "customer says no" }]] as const) {
      const refused = await api(customer.session, "POST", `/admin/revops/invoices/${original.id}/${route}`, body);
      expect([403, 404], `${route} as the customer`).toContain(refused.status);
    }
    expect((await contractOf(session!, contractId)).invoices[0]?.status).toBe("ISSUED");

    // Void, first backing out of the dialog (nothing is sent), then a reason that is too short.
    await first.getByRole("button", { name: "Void" }).click();
    const voidDialog = page.getByRole("dialog", { name: `Void invoice ${number}-001?` });
    await expect(voidDialog).toContainText(/never collected/i);
    await expect(voidDialog.getByRole("button", { name: "Void invoice" })).toBeDisabled();
    await voidDialog.getByLabel("Reason").fill("ab");
    await expect(voidDialog.getByRole("button", { name: "Void invoice" })).toBeDisabled();
    await voidDialog.getByRole("button", { name: "Cancel" }).click();
    await expect(voidDialog).toHaveCount(0);
    expect((await contractOf(session!, contractId)).invoices[0]?.status).toBe("ISSUED");

    await first.getByRole("button", { name: "Void" }).click();
    await voidDialog.getByLabel("Reason").fill("Wrong PO on the invoice");
    await voidDialog.getByRole("button", { name: "Void invoice" }).click();
    await expect(page.getByText("Invoice voided.")).toBeVisible();
    await expect(first).toContainText("VOID");
    await expect(first.getByRole("button", { name: "Mark paid" })).toHaveCount(0);
    contract = await contractOf(session!, contractId);
    expect(contract.invoices[0]).toMatchObject({ status: "VOID", void_reason: "Wrong PO on the invoice" });

    // Issue due invoices: the voided period is issued again (suffix R1); pressing it twice adds nothing.
    await detail.getByRole("button", { name: "Issue due invoices" }).click();
    await expect(page.getByText("Every invoice that is due has been issued.")).toBeVisible();
    const reissued = detail.getByRole("row", { name: new RegExp(`${number}-001R1`) });
    await expect(reissued).toContainText("ISSUED");
    contract = await contractOf(session!, contractId);
    expect(contract.invoices.map((i) => [i.invoice_number, i.status])).toEqual([[`${number}-001`, "VOID"], [`${number}-001R1`, "ISSUED"]]);
    await detail.getByRole("button", { name: "Issue due invoices" }).click();
    await expect(detail.getByRole("row")).toHaveCount(1 + 2); // header + the two invoices
    expect((await contractOf(session!, contractId)).invoices).toHaveLength(2);

    // Mark paid needs a reference.
    await reissued.getByRole("button", { name: "Mark paid" }).click();
    const payDialog = page.getByRole("dialog", { name: "Record a payment" });
    await expect(payDialog.getByRole("button", { name: "Mark paid" })).toBeDisabled();
    await payDialog.getByLabel("Payment reference").fill("UTR-E2E-REVOPS-0042");
    await payDialog.getByRole("button", { name: "Mark paid" }).click();
    await expect(page.getByText("Invoice marked paid.")).toBeVisible();
    await expect(reissued).toContainText("PAID");
    contract = await contractOf(session!, contractId);
    const paid = contract.invoices.find((i) => i.invoice_number === `${number}-001R1`);
    expect(paid).toMatchObject({ status: "PAID", payment_reference: "UTR-E2E-REVOPS-0042" });
    expect(paid?.paid_at).not.toBeNull();
    // A paid or void invoice cannot be changed again.
    for (const [route, body] of [["void", { reason: "too late now" }], ["pay", { reference: "again" }]] as const) {
      const late = await api(session, "POST", `/admin/revops/invoices/${paid!.id}/${route}`, body);
      expect(late.status, late.text).toBe(409);
      expect(late.text).toContain("INVOICE_NOT_ISSUED");
    }

    // Cancel the contract: keep it once, then cancel.
    await detail.getByRole("button", { name: "Cancel contract" }).click();
    const cancelDialog = page.getByRole("alertdialog", { name: `Cancel contract ${number}?` });
    await expect(cancelDialog).toContainText(/Free plan/);
    await cancelDialog.getByRole("button", { name: "Keep the contract" }).click();
    await expect(cancelDialog).toHaveCount(0);
    expect((await contractOf(session!, contractId)).status).toBe("ACTIVE");
    await detail.getByRole("button", { name: "Cancel contract" }).click();
    await cancelDialog.getByRole("button", { name: "Cancel contract" }).click();
    await expect(page.getByText("Contract cancelled.")).toBeVisible();
    await expect(detail).toContainText("CANCELLED");
    await expect(detail.getByRole("button", { name: "Cancel contract" })).toHaveCount(0);
    await expect(detail.getByRole("button", { name: "Issue due invoices" })).toHaveCount(0);
    contract = await contractOf(session!, contractId);
    expect(contract).toMatchObject({ status: "CANCELLED", end_reason: "CANCELLED" });
    const issueAfter = await api(session, "POST", `/admin/revops/contracts/${contractId}/issue`);
    expect(issueAfter.status).toBe(409);
    expect(issueAfter.text).toContain("CONTRACT_NOT_ACTIVE");

    // After a reload the list shows the contract cancelled with its open/overdue counts.
    await page.reload();
    const listRow = page.getByRole("row", { name: new RegExp(number) });
    await expect(listRow).toContainText("CANCELLED");
    await expect(listRow).toContainText("0 / 0");

    // The customer's own audit trail records every step.
    const operations = await auditOperations(customer);
    for (const operation of ["contract.created", "contract.activated", "contract.invoice_voided", "contract.invoice_paid", "contract.ended"]) {
      expect(operations, `audit trail of ${customer.orgSlug}`).toContain(operation);
    }
    await expectHealthyPage(page);
  });
});

test.describe("RevOps disputes: Lift", () => {
  test.use({ user: "P.superadmin" });

  test("a lost dispute holds the organization read-only until the operator lifts it with a reason", async ({ page, session }) => {
    const customer = await newCustomer("revops-dispute", `Dispute Customer ${runId()}`);
    const subscribed = standIn("subscribe", customer.orgSlug, "--plan", "business", "--seats", "1");
    const subscriptionId = String(subscribed.subscription_id ?? "");
    expect(subscriptionId).not.toBe("");

    // The customer's bank reverses the payment: the stand-in Dodo sends the signed webhook.
    const state = await (await fetch(`${DODO_ORIGIN}/_fake/state`)).json() as {
      payments: Array<{ payment_id: string; subscription_id: string; status: string }>;
    };
    const payment = state.payments.filter((p) => p.status === "succeeded" && p.subscription_id === subscriptionId).at(-1);
    expect(payment, "a paid payment at the stand-in Dodo").toBeDefined();
    const sent = await fetch(`${DODO_ORIGIN}/_fake/dispute`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ payment_id: payment!.payment_id, status: "dispute_lost" }),
    });
    expect(sent.status).toBe(200);
    const disputeId = ((await sent.json()) as { dispute_id: string }).dispute_id;

    let dispute: Dispute | undefined;
    await expect.poll(async () => {
      const all = await api<Dispute[]>(session, "GET", "/admin/revops/disputes");
      dispute = all.body.find((d) => d.gateway_dispute_id === disputeId);
      return dispute?.holding_read_only;
    }, { message: "the webhook reaches the API and records the dispute", timeout: 60_000 }).toBe(true);
    const access = await api<{ writes_allowed: boolean; reason: string | null }>(
      customer.session, "GET", `/organizations/${customer.orgId}/billing/access`);
    expect(access.body).toMatchObject({ writes_allowed: false, reason: "PAYMENT_REVERSED" });

    await page.goto("/admin/revops?tab=disputes");
    const row = page.getByRole("row", { name: new RegExp(disputeId) });
    await expect(row).toContainText("lost");
    const lift = row.getByRole("button", { name: "Lift" });
    // The reason is required (the field refuses fewer than three characters): nothing is sent.
    await row.getByLabel("Why lift the hold").fill("ab");
    await lift.click();
    expect((await api<Dispute[]>(session, "GET", "/admin/revops/disputes")).body.find((d) => d.id === dispute!.id)?.holding_read_only).toBe(true);
    await row.getByLabel("Why lift the hold").fill("Paid by bank transfer, ref UTR-9917");
    await lift.click();
    await expect(page.getByText("Read-only hold lifted.")).toBeVisible();
    await expect(row).toContainText("Lifted: Paid by bank transfer, ref UTR-9917");
    await expect(row.getByRole("button", { name: "Lift" })).toHaveCount(0);

    const after = (await api<Dispute[]>(session, "GET", "/admin/revops/disputes")).body.find((d) => d.id === dispute!.id);
    expect(after).toMatchObject({ holding_read_only: false, cleared_reason: "Paid by bank transfer, ref UTR-9917" });
    expect(after?.cleared_at).not.toBeNull();
    await expect.poll(async () => (await api<{ writes_allowed: boolean }>(
      customer.session, "GET", `/organizations/${customer.orgId}/billing/access`)).body.writes_allowed).toBe(true);
    expect(await auditOperations(customer)).toContain("payment_reversal_lifted");

    await page.reload();
    await expect(page.getByRole("row", { name: new RegExp(disputeId) })).toContainText("Lifted: Paid by bank transfer");
    await expectHealthyPage(page);
  });
});

test.describe("RevOps console is the platform operator's only", () => {
  test.use({ user: "A.owner" });

  test("a customer owner does not see the console and the server refuses every money route", async ({ page, session }) => {
    await page.goto("/admin/revops");
    await settle(page);
    await expect(page).not.toHaveURL(/\/admin\/revops$/);
    await expect(page.locator("body")).not.toContainText("Revenue operations");
    await expect(page.getByRole("link", { name: /Revenue operations/ })).toHaveCount(0);

    const operator = await loginAs("P.superadmin");
    const code = `E2E-NOPE-${runId()}`.toUpperCase();
    const bogus = "00000000-0000-4000-8000-000000000000";
    const attempts: Array<[string, string, unknown?]> = [
      ["GET", "/admin/revops/metrics"],
      ["GET", "/admin/revops/price-books"],
      ["POST", "/admin/revops/price-books", { code, currency: "INR", notes: null }],
      ["POST", `/admin/revops/price-books/${bogus}/publish`],
      ["POST", "/admin/revops/promo-codes", { code, percent_off: 50, duration: "FOREVER" }],
      ["PUT", `/admin/revops/promo-codes/${bogus}/active`, { is_active: false }],
      ["POST", `/admin/revops/contracts/${bogus}/issue`],
      ["POST", `/admin/revops/contracts/${bogus}/end`, { reason: "CANCELLED" }],
      ["POST", `/admin/revops/invoices/${bogus}/pay`, { reference: "x" }],
      ["POST", `/admin/revops/invoices/${bogus}/void`, { reason: "nope" }],
      ["GET", "/admin/revops/disputes"],
      ["POST", `/admin/revops/disputes/${bogus}/lift`, { reason: "nope" }],
    ];
    for (const [method, route, body] of attempts) {
      const refused = await api(session, method, route, body);
      expect([403, 404], `${method} ${route} as a customer owner`).toContain(refused.status);
    }
    expect((await api(null, "GET", "/admin/revops/metrics")).status).toBe(401);
    // Nothing the refused requests asked for exists.
    expect((await booksOf(operator)).some((b) => b.code === code)).toBe(false);
    const promos = await api<Promo[]>(operator, "GET", "/admin/revops/promo-codes");
    expect(promos.body.some((p) => p.code === code)).toBe(false);
  });
});
