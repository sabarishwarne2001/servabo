/**
 * LEGAL HOLDS (Settings → General; campaign Session C).
 *
 * A hold stops deletion of what it covers. In a customer's own workspace this drives every button the
 * panel has, in the browser, and checks each result on the page, through the API and after a reload:
 * "Place hold" needs a reason (three characters) and records it; a document under a hold cannot be
 * deleted (the Documents page says why, the server answers 409 RETENTION_HOLD) while another document
 * can; "Release" frees the document, and the released hold moves under "Released holds". A hold on the
 * whole workspace refuses every delete. A contributor sees the holds but has no way to place or
 * release one, and the server refuses them.
 */
import { test, expect, expectHealthyPage, settle } from "../support/fixtures";
import { api } from "../support/api";
import { addMember, newCustomer, signInAs, uploadViaApi, type Customer } from "../support/journey";

interface Hold {
  readonly id: string;
  readonly reason: string;
  readonly reference: string | null;
  readonly work_item_id: string | null;
  readonly released_at: string | null;
}

const holdsOf = async (customer: Customer): Promise<Hold[]> => {
  const listed = await api<Hold[]>(customer.session, "GET", `/workspaces/${customer.wsId}/work-items/retention-holds`);
  expect(listed.status, listed.text.slice(0, 200)).toBe(200);
  return listed.body;
};

const documentExists = async (customer: Customer, id: string): Promise<boolean> =>
  (await api(customer.session, "GET", `/workspaces/${customer.wsId}/work-items/${id}`)).status === 200;

test.describe("Legal holds", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(150_000);
  let customer: Customer;
  let held: { id: string; name: string };
  let other: { id: string; name: string };
  const REASON = "Litigation hold — Acme v. Servabo";

  const upload = async (label: string): Promise<{ id: string; name: string }> => {
    const id = await uploadViaApi(customer, label);
    const detail = await api<{ original_filename: string }>(customer.session, "GET", `/workspaces/${customer.wsId}/work-items/${id}`);
    return { id, name: detail.body.original_filename };
  };

  test.beforeAll(async () => {
    customer = await newCustomer("holds", "Legal Holds Ltd");
    held = await upload("held");
    other = await upload("other");
  });

  const holdsPanel = (page: import("@playwright/test").Page) => page.getByRole("region", { name: "Legal holds" });
  const rowOf = (page: import("@playwright/test").Page, name: string) => page.getByRole("row").filter({ hasText: name });

  async function tryDelete(page: import("@playwright/test").Page, name: string): Promise<void> {
    await page.goto(customer.ws("work-items"));
    await settle(page);
    await rowOf(page, name).getByRole("button", { name: "Delete Document" }).click();
    await page.getByRole("alertdialog", { name: "Delete Document" }).getByRole("button", { name: "Delete", exact: true }).click();
  }

  test("a hold needs a reason; placing one records it, with its reference and document, and it survives a reload", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.ws("settings?section=workspace"));
    await settle(page);
    const panel = holdsPanel(page);
    await expect(panel).toBeVisible();
    await expect(panel).toContainText("No active holds");

    const place = panel.getByRole("button", { name: "Place hold" });
    await expect(place).toBeDisabled();
    await panel.getByLabel("Reason (recorded in the audit log)").fill("ab");
    await expect(place).toBeDisabled();
    await panel.getByLabel("Reason (recorded in the audit log)").fill(REASON);
    await panel.getByLabel("Reference (optional)").fill("CASE-42");
    await panel.getByLabel("Document ID (optional)").fill(held.id);
    await expect(place).toBeEnabled();
    await place.click();

    await expect(page.getByText("Legal hold placed.")).toBeVisible();
    await expect(panel).not.toContainText("No active holds");
    const item = panel.getByRole("listitem").filter({ hasText: REASON });
    await expect(item).toContainText("One document");
    await expect(item).toContainText("Ref CASE-42");
    await expect(item.getByRole("button", { name: "Release" })).toBeVisible();
    // The form is cleared for the next hold.
    await expect(panel.getByLabel("Reason (recorded in the audit log)")).toHaveValue("");

    const holds = await holdsOf(customer);
    expect(holds.map((h) => [h.reason, h.reference, h.work_item_id, h.released_at])).toEqual([[REASON, "CASE-42", held.id, null]]);

    await page.reload();
    await settle(page);
    await expect(holdsPanel(page).getByRole("listitem").filter({ hasText: REASON })).toContainText("Ref CASE-42");
    await expectHealthyPage(page);
  });

  test("the held document cannot be deleted: the page says why, the server refuses, and another document can go", async ({ page, problems }) => {
    problems.allowHttp(/\/work-items\/[0-9a-f-]+$/, [409], "deleting a document under a legal hold is refused");
    await signInAs(page, customer.email);

    await tryDelete(page, held.name);
    await expect(page.getByText(`A retention hold is in place: ${REASON}`)).toBeVisible();
    await expect(page.getByText("Document deleted successfully.")).toHaveCount(0);
    expect(await documentExists(customer, held.id)).toBe(true);
    const direct = await api<{ detail: { code: string; message: string } }>(customer.session, "DELETE", `/workspaces/${customer.wsId}/work-items/${held.id}`);
    expect(direct.status).toBe(409);
    expect(direct.body.detail.code).toBe("RETENTION_HOLD");

    await page.reload();
    await settle(page);
    await expect(rowOf(page, held.name)).toHaveCount(1);

    // A hold covers its own document only.
    await tryDelete(page, other.name);
    await expect(page.getByText("Document deleted successfully.")).toBeVisible();
    await expect(rowOf(page, other.name)).toHaveCount(0);
    expect(await documentExists(customer, other.id)).toBe(false);
  });

  test("Release frees the document; the hold moves under Released holds and the delete now works", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.ws("settings?section=workspace"));
    await settle(page);
    const panel = holdsPanel(page);
    await panel.getByRole("listitem").filter({ hasText: REASON }).getByRole("button", { name: "Release" }).click();

    await expect(page.getByText("Legal hold released.")).toBeVisible();
    await expect(panel).toContainText("No active holds");
    const released = panel.getByText(/^Released holds \(1\)/);
    await expect(released).toBeVisible();
    await released.click();
    await expect(panel).toContainText(REASON);
    const holds = await holdsOf(customer);
    expect(holds).toHaveLength(1);
    expect(holds[0].released_at).not.toBeNull();

    await page.reload();
    await settle(page);
    await expect(holdsPanel(page)).toContainText("No active holds");
    await expect(holdsPanel(page)).toContainText("Released holds (1)");

    await tryDelete(page, held.name);
    await expect(page.getByText("Document deleted successfully.")).toBeVisible();
    expect(await documentExists(customer, held.id)).toBe(false);
  });

  test("a hold with no document covers the whole workspace: every delete is refused until it is released", async ({ page, problems }) => {
    problems.allowHttp(/\/work-items\/[0-9a-f-]+$/, [409], "deleting under a whole-workspace hold is refused");
    const third = await upload("third");
    await signInAs(page, customer.email);
    await page.goto(customer.ws("settings?section=workspace"));
    await settle(page);
    const panel = holdsPanel(page);
    await panel.getByLabel("Reason (recorded in the audit log)").fill("Regulator inquiry");
    await panel.getByRole("button", { name: "Place hold" }).click();
    await expect(page.getByText("Legal hold placed.")).toBeVisible();
    await expect(panel.getByRole("listitem").filter({ hasText: "Regulator inquiry" })).toContainText("Whole workspace");

    await tryDelete(page, third.name);
    await expect(page.getByText("A retention hold is in place: Regulator inquiry")).toBeVisible();
    expect(await documentExists(customer, third.id)).toBe(true);

    await page.goto(customer.ws("settings?section=workspace"));
    await settle(page);
    await holdsPanel(page).getByRole("listitem").filter({ hasText: "Regulator inquiry" }).getByRole("button", { name: "Release" }).click();
    await expect(page.getByText("Legal hold released.")).toBeVisible();
    await tryDelete(page, third.name);
    await expect(page.getByText("Document deleted successfully.")).toBeVisible();
    expect(await documentExists(customer, third.id)).toBe(false);
  });

  test("a contributor sees the holds but cannot place or release one, and the server refuses them", async ({ page }) => {
    const fourth = await upload("fourth");
    const placed = await api<Hold>(customer.session, "POST", `/workspaces/${customer.wsId}/work-items/retention-holds`, {
      reason: "Audit freeze", reference: null, work_item_id: fourth.id,
    });
    expect(placed.status, placed.text).toBeLessThan(300);

    const contributor = await addMember(customer, "holds-contributor", "MEMBER", "CONTRIBUTOR");
    await signInAs(page, contributor.email);
    await page.goto(customer.ws("settings?section=workspace"));
    await settle(page);
    const panel = holdsPanel(page);
    // Listing is open to the workspace; the controls are not.
    if (await panel.count()) {
      await expect(panel).toContainText("Audit freeze");
      await expect(panel.getByRole("button", { name: "Place hold" })).toHaveCount(0);
      await expect(panel.getByRole("button", { name: "Release" })).toHaveCount(0);
    }

    const refusedPlace = await api(contributor.session, "POST", `/workspaces/${customer.wsId}/work-items/retention-holds`, {
      reason: "Let me in", reference: null, work_item_id: null,
    });
    expect(refusedPlace.status).toBe(403);
    const refusedRelease = await api(contributor.session, "DELETE", `/workspaces/${customer.wsId}/work-items/retention-holds/${placed.body.id}`);
    expect(refusedRelease.status).toBe(403);
    const stillThere = (await holdsOf(customer)).filter((h) => h.released_at === null);
    expect(stillThere.map((h) => h.reason)).toEqual(["Audit freeze"]);
    await expectHealthyPage(page);
  });
});
