/**
 * GST CREDIT NOTICES AND THE MONDAY DIGEST (Final session 1, 3A).
 *
 * Two customers of their own, each with a GSTR-2B imported (no invoices of their own, so what the file reports shows as "not in your
 * books", in lakhs so the grouping can be read):
 *   - a Business-plan owner: the import tells the owners and administrators in the organization's bell, once; "GST credit" is a
 *     category with a switch, offered to the people who act on it and not to a plain member; the digest does not go out on a Tuesday
 *     or before 09:00 on a Monday, goes out on a Monday as one email in rupees with Indian grouping, and never twice in a week;
 *     an owner who turned the category off is skipped;
 *   - a Developer-plan owner (a preview): the digest carries the headline figures and one line saying what the lists would add and
 *     what the add-on costs, taken from the catalogue.
 * The clock is played by the stand-in (`run-job --now`), which the job honours outside production only.
 */
import { test, expect } from "../support/fixtures";
import { api } from "../support/api";
import { gstin, gstr2b } from "../support/gst";
import { addMember, newCustomer, signInAs, standIn, type Customer } from "../support/journey";
import { readMails } from "../support/mail";

const BUYER = gstin("27", "AAACN1234F");
const SUPPLIER = gstin("27", "AABCS5555K");
const MONDAY = "2026-10-19T09:30:00+00:00";
const TUESDAY = "2026-10-20T09:30:00+00:00";
const EARLY_MONDAY = "2026-10-19T08:30:00+00:00";
const NEXT_MONDAY = "2026-10-26T09:30:00+00:00";

const statement = (): string =>
  gstr2b(BUYER, "2026-09", [
    { gstin: SUPPLIER, name: "Sahyadri Packaging", docs: [{ number: "S-1", date: "2026-09-05", taxable: 1_250_000 }] },
  ]);

const importStatement = async (c: Customer): Promise<void> => {
  const form = new FormData();
  form.append("file", new Blob([statement()], { type: "application/json" }), "GSTR2B_092026.json");
  const sent = await api(c.session, "POST", `/workspaces/${c.wsId}/gst/returns`, form);
  expect(sent.status, sent.text.slice(0, 300)).toBe(200);
};

const digest = (c: Customer, now: string): { emails: number; organizations: number } => {
  const outcome = standIn("run-job", c.orgSlug, "--job", "gst.digest", "--now", now) as { status?: string; result?: { emails: number; organizations: number } };
  expect(outcome.status).toBe("SUCCEEDED");
  return outcome.result ?? { emails: -1, organizations: -1 };
};

const digestsTo = (email: string, since: number) => readMails(email, since).filter((m) => /Your GST credit this week/.test(m.text));

let business: Customer;
let preview: Customer;
let member: { email: string };
const startedAt = Date.now() - 2_000;

test.describe("GST notices and digest", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);

  test.beforeAll(async () => {
    test.setTimeout(420_000);
    business = await newCustomer("gstdigest", "Digest Traders Ltd");
    standIn("subscribe", business.orgSlug, "--plan", "business", "--seats", "4");
    member = await addMember(business, "gstdigest-member", "MEMBER", "VIEWER");
    await importStatement(business);
    preview = await newCustomer("gstpreview", "Preview Traders Ltd");
    standIn("subscribe", preview.orgSlug, "--plan", "developer", "--seats", "1");
    await importStatement(preview);
  });

  test("an import tells the organization once, in the bell, with the rupees in Indian grouping", async ({ page }) => {
    await signInAs(page, business.email);
    await page.goto(business.org(""));
    await page.getByRole("button", { name: "Open organization notifications" }).click();
    const dialog = page.getByRole("dialog", { name: "Organization notifications" });
    await expect(dialog.getByText("GSTR-2B imported")).toHaveCount(1, { timeout: 30_000 });
    await expect(dialog).toContainText("September 2026");
    await expect(dialog).toContainText("were imported into");
  });

  test("GST credit is a switch for the people who act on it, and not for a plain member", async ({ page }) => {
    await signInAs(page, business.email);
    await page.goto(`${business.ws("settings")}?section=notifications`);
    const list = page.getByRole("list", { name: "Email notifications" });
    await expect(list.getByRole("switch", { name: "GST credit" })).toHaveAttribute("aria-checked", "true", { timeout: 20_000 });
    await signInAs(page, member.email);
    await page.goto(`${business.ws("settings")}?section=notifications`);
    await expect(page.getByRole("list", { name: "Email notifications" })).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("switch", { name: "GST credit" })).toHaveCount(0);
  });

  test("not on a Tuesday, not before nine on a Monday; on a Monday one email, never twice in a week", async () => {
    expect(digest(business, TUESDAY).emails).toBe(0);
    expect(digest(business, EARLY_MONDAY).emails).toBe(0);
    expect(digestsTo(business.email, startedAt)).toHaveLength(0);
    expect(digest(business, MONDAY).emails).toBeGreaterThanOrEqual(1);
    const mails = digestsTo(business.email, startedAt);
    expect(mails).toHaveLength(1);
    expect(mails[0].text).toContain("INR 2,25,000.00");              // Indian grouping, not 225,000.00
    expect(mails[0].text).not.toContain("225,000.00");
    expect(mails[0].text).toContain("Open GST Credit");
    expect(mails[0].text).not.toContain("Unlock the lists");          // the lists are open on Business
    digest(business, MONDAY);
    expect(digestsTo(business.email, startedAt)).toHaveLength(1);
  });

  test("an owner who turned the category off is skipped the next Monday", async () => {
    const before = digestsTo(business.email, startedAt).length;
    const off = await api(business.session, "PUT", "/me/notification-preferences", { category: "gst_credit", email: false });
    expect(off.status, off.text).toBe(200);
    try {
      digest(business, NEXT_MONDAY);
      expect(digestsTo(business.email, startedAt)).toHaveLength(before);
    } finally {
      await api(business.session, "PUT", "/me/notification-preferences", { category: "gst_credit", email: true });
    }
  });

  test("a plan that shows only the headline is told what the lists would add and what they cost", async () => {
    // The job sweeps every organization, so the Monday run above already reached this one; running it again adds nothing for that week.
    digest(preview, MONDAY);
    const mails = digestsTo(preview.email, startedAt);
    expect(mails.length).toBeGreaterThanOrEqual(1);
    for (const mail of mails) {
      expect(mail.text).toContain("Unlock the lists: GST Credit add-on, $49 a month");
      expect(mail.text).toContain("INR 2,25,000.00");
      expect(mail.text).not.toContain("Waiting on ");
    }
  });
});
