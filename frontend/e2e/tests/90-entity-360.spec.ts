/**
 * ENTITY 360 (the record page of the entity graph): Rename, Erase record, "Split N into a new record"
 * and "Undo merge", each clicked in the browser on records the real pipeline made.
 *
 * Set-up (a Business-plan customer of its own, so the seeded tenants are untouched): real invoice PDFs
 * are uploaded; the worker reads them (the model stand-in extracts "Vendor", "Bill To", "Vendor Address")
 * and the entity graph resolves each vendor to one record per spelling. The model stand-in cannot read a
 * GSTIN or an IBAN, so two spellings of one supplier cannot be merged by a shared identifier here (that
 * path is proved in backend/tests/engines/test_entity_graph_live.py); the "really merged" records are made
 * with the reviewer's own merge call (POST .../merge), which is what the review hub's "Merge" button sends.
 *
 *   - Rename: Cancel keeps the name, an empty name is not sent, Save renames; it survives a reload, shows in
 *     the list search and in the API; the button is offered on an address record too.
 *   - Split: ticking documents counts them on the button; splitting two of three moves exactly those two to a
 *     new record the page opens, and the original keeps the third; splitting the only document is refused.
 *   - Undo merge: a record that had another merged into it lists it; the merged record's own link opens the
 *     survivor; "Undo merge" restores two separate records, each with its own documents, after a reload too.
 *   - Erase record (admin): dismissing the confirmation changes nothing; accepting removes the record, its
 *     links and its identifiers, the documents stay, and the record's address is gone.
 *   - A contributor renames, splits and undoes a merge but has no Erase button and the server says 403;
 *     a viewer sees none of the buttons and the server refuses each call.
 */
import { test, expect, expectHealthyPage, settle } from "../support/fixtures";
import { api, apiLogin, type ApiSession } from "../support/api";
import { runId } from "../support/env";
import { addMember, newCustomer, signInAs, standIn, type Customer } from "../support/journey";
import { buildPdf } from "../support/sample-docs";

interface EntityRow {
  readonly id: string;
  readonly kind: string;
  readonly display_name: string;
  readonly documents: number;
  readonly mentions: number;
  readonly merged_records: number;
}
interface Entity360 {
  readonly entity: EntityRow;
  readonly documents: ReadonlyArray<{ readonly mention_id: string; readonly work_item_id: string; readonly filename: string }>;
  readonly relationships: ReadonlyArray<{ readonly relation: string; readonly other_id: string; readonly other_name: string }>;
  readonly members: ReadonlyArray<{ readonly id: string; readonly display_name: string; readonly mentions: number }>;
}

const BILL_TO = "Northwind Retail Limited";
const ERASE_PROMPT = "its links to every document are erased. The documents themselves are kept.";

/** Vendor name -> the file names that name it. Every file is a real PDF the worker has to read. */
const SUPPLIERS: Readonly<Record<string, readonly string[]>> = {
  "Rowan Packaging Limited": ["rowan-1.pdf"],
  "Sable Logistics Limited": ["sable-1.pdf", "sable-2.pdf", "sable-3.pdf"],
  "Alder Trading Company": ["alder-1.pdf"],
  "Zinnia Wholesale Partners": ["zinnia-1.pdf"],
  "Elm Hardware Limited": ["elm-1.pdf"],
  "Fennel Supplies Limited": ["fennel-1.pdf"],
  "Juniper Textiles Limited": ["juniper-1.pdf", "juniper-2.pdf"],
  "Linden Stationers Limited": ["linden-1.pdf"],
  "Maple Cartons Limited": ["maple-1.pdf"],
};
const ADDRESS = "4 Quarry Lane, Leeds LS2 7QA, United Kingdom";

let customer: Customer;
let contributorEmail: string;
let viewerEmail: string;
let adminEmail: string;

async function entities(session: ApiSession, query = ""): Promise<EntityRow[]> {
  const listed = await api<{ items: EntityRow[] }>(session, "GET", `/workspaces/${customer.wsId}/entities?page_size=100${query}`);
  expect(listed.status, listed.text.slice(0, 300)).toBe(200);
  return listed.body.items;
}

async function detail(session: ApiSession, id: string): Promise<Entity360> {
  const got = await api<Entity360>(session, "GET", `/workspaces/${customer.wsId}/entities/${id}`);
  expect(got.status, got.text.slice(0, 300)).toBe(200);
  return got.body;
}

/** The one record that carries this display name (the test fails if there are two or none). */
async function one(session: ApiSession, name: string): Promise<EntityRow> {
  const found = (await entities(session)).filter((row) => row.display_name === name);
  expect(found.map((row) => row.display_name), `records named ${name}`).toHaveLength(1);
  return found[0];
}

const filenames = (view: Entity360): string[] => view.documents.map((doc) => doc.filename).sort();

/** The page of one record, as a signed-in person opens it. */
async function openRecord(page: import("@playwright/test").Page, id: string): Promise<void> {
  await page.goto(customer.ws(`entities/${id}`));
  await settle(page);
}

const heading = (page: import("@playwright/test").Page, name: string) => page.getByRole("heading", { level: 1, name, exact: true });
const section = (page: import("@playwright/test").Page, name: string) => page.getByRole("region", { name, exact: true });

test.describe("Entity 360 — the record page's buttons", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);

  test.beforeAll(async () => {
    test.setTimeout(480_000);
    customer = await newCustomer("entity360", "Entity 360 Trading Ltd");
    standIn("subscribe", customer.orgSlug, "--plan", "business", "--seats", "4");
    const contributor = await addMember(customer, "ent-contrib", "MEMBER", "CONTRIBUTOR");
    const viewer = await addMember(customer, "ent-viewer", "MEMBER", "VIEWER");
    const admin = await addMember(customer, "ent-admin", "MEMBER", "ADMIN");
    contributorEmail = contributor.email;
    viewerEmail = viewer.email;
    adminEmail = admin.email;

    let serial = 0;
    for (const [vendor, files] of Object.entries(SUPPLIERS)) {
      for (const file of files) {
        serial += 1;
        const lines = [
          "INVOICE",
          `Vendor: ${vendor}`,
          ...(vendor.startsWith("Rowan") ? [`Vendor Address: ${ADDRESS}`] : []),
          `Bill To: ${BILL_TO}`,
          `Invoice Number: INV-E360-${runId()}-${serial}`,
          "Invoice Date: 2026-09-15",
          "Currency: USD",
          "Total Amount Due: 99.00 USD",
        ];
        const form = new FormData();
        form.append("file", new Blob([new Uint8Array(buildPdf([lines]))], { type: "application/pdf" }), file);
        const up = await api(customer.session, "POST", `/workspaces/${customer.wsId}/work-items`, form);
        expect(up.status, up.text.slice(0, 300)).toBe(201);
      }
    }
    // The worker reads each PDF, then the graph resolves it: wait until every vendor has all its documents.
    await expect
      .poll(async () => {
        const session = await apiLogin(customer.email);
        const rows = await entities(session);
        const wrong = Object.entries(SUPPLIERS).filter(([vendor, files]) =>
          rows.filter((row) => row.display_name === vendor && row.documents === files.length).length !== 1);
        return wrong.map(([vendor]) => vendor);
      }, { timeout: 420_000, intervals: [3_000, 5_000] })
      .toEqual([]);
  });

  test("Rename: Cancel keeps the name, an empty name is not sent, Save renames and it survives a reload", async ({ page }) => {
    const session = await apiLogin(customer.email);
    const before = await one(session, "Rowan Packaging Limited");
    await signInAs(page, customer.email);
    await openRecord(page, before.id);
    await expect(heading(page, "Rowan Packaging Limited")).toBeVisible();

    await page.getByRole("button", { name: "Rename", exact: true }).click();
    const box = page.getByRole("textbox", { name: "Name" });
    await expect(box).toHaveValue("Rowan Packaging Limited");
    await expect(page.getByRole("button", { name: "Rename", exact: true })).toHaveCount(0);

    // Cancel: back to the heading, nothing sent, nothing stored.
    await box.fill("Thrown Away Name");
    await page.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(heading(page, "Rowan Packaging Limited")).toBeVisible();
    await expect(box).toHaveCount(0);
    expect((await detail(session, before.id)).entity.display_name).toBe("Rowan Packaging Limited");

    // An empty name is not sent: the box stays open, the record keeps its name.
    await page.getByRole("button", { name: "Rename", exact: true }).click();
    const renamedCalls: string[] = [];
    page.on("request", (request) => { if (request.method() === "PATCH") renamedCalls.push(request.url()); });
    await box.fill("   ");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(box).toBeVisible();
    expect(renamedCalls).toEqual([]);
    expect((await detail(session, before.id)).entity.display_name).toBe("Rowan Packaging Limited");

    // Save: the heading changes, the server has it, a reload still shows it, the list finds the new name only.
    await box.fill("  Rowan Packaging & Print Limited ");
    const saved = page.waitForResponse((r) => r.request().method() === "PATCH" && r.url().endsWith(`/entities/${before.id}`));
    await page.getByRole("button", { name: "Save", exact: true }).click();
    expect((await saved).status()).toBe(200);
    await expect(heading(page, "Rowan Packaging & Print Limited")).toBeVisible();
    await expect(box).toHaveCount(0);
    expect((await detail(session, before.id)).entity.display_name).toBe("Rowan Packaging & Print Limited");

    await page.reload();
    await settle(page);
    await expect(heading(page, "Rowan Packaging & Print Limited")).toBeVisible();
    await expect(section(page, "Documents")).toContainText("rowan-1.pdf");
    expect((await entities(session, "&q=Rowan")).map((row) => row.display_name)).toEqual(["Rowan Packaging & Print Limited"]);

    await page.goto(customer.ws("entities"));
    await settle(page);
    await expect(page.getByRole("link", { name: "Rowan Packaging & Print Limited", exact: true })).toBeVisible();
    await expect(page.getByRole("link", { name: "Rowan Packaging Limited", exact: true })).toHaveCount(0);

    // The address on the same invoice is a record of its own, and an address can be renamed too.
    const address = (await entities(session)).find((row) => row.kind === "ADDRESS");
    expect(address, "the invoice's vendor address became a record").toBeTruthy();
    await openRecord(page, address?.id ?? "");
    await page.getByRole("button", { name: "Rename", exact: true }).click();
    await page.getByRole("textbox", { name: "Name" }).fill("Rowan Leeds yard");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(heading(page, "Rowan Leeds yard")).toBeVisible();
    expect((await detail(session, address?.id ?? "")).entity.display_name).toBe("Rowan Leeds yard");
    await expectHealthyPage(page);
  });

  test("Split: ticked documents move to a new record the page opens; the original keeps the rest; one document cannot be split away from nothing", async ({ page, problems }) => {
    const session = await apiLogin(customer.email);
    const sable = await one(session, "Sable Logistics Limited");
    expect(filenames(await detail(session, sable.id))).toEqual(["sable-1.pdf", "sable-2.pdf", "sable-3.pdf"]);
    await signInAs(page, customer.email);
    await openRecord(page, sable.id);

    const documents = section(page, "Documents");
    await expect(documents.getByRole("listitem")).toHaveCount(3);
    await expect(page.getByRole("button", { name: /^Split \d+ into a new record$/ })).toHaveCount(0);

    await page.getByLabel("Select sable-1.pdf", { exact: true }).check();
    await expect(page.getByRole("button", { name: "Split 1 into a new record" })).toBeVisible();
    await page.getByLabel("Select sable-2.pdf", { exact: true }).check();
    await page.getByLabel("Select sable-3.pdf", { exact: true }).check();
    await expect(page.getByRole("button", { name: "Split 3 into a new record" })).toBeVisible();
    await page.getByLabel("Select sable-2.pdf", { exact: true }).uncheck();
    await expect(page.getByRole("button", { name: "Split 2 into a new record" })).toBeVisible();

    // Nothing moved yet.
    expect(filenames(await detail(session, sable.id))).toEqual(["sable-1.pdf", "sable-2.pdf", "sable-3.pdf"]);

    const split = page.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith(`/entities/${sable.id}/split`));
    await page.getByRole("button", { name: "Split 2 into a new record" }).click();
    const response = await split;
    expect(response.status()).toBe(200);
    const created = (await response.json()) as EntityRow;
    expect(created.id).not.toBe(sable.id);

    // The page opened the new record, holding exactly the two chosen documents.
    await expect(page).toHaveURL(new RegExp(`/entities/${created.id}$`));
    await expect(heading(page, "Sable Logistics Limited")).toBeVisible();
    await expect(documents.getByRole("listitem")).toHaveCount(2);
    await expect(documents).toContainText("sable-1.pdf");
    await expect(documents).toContainText("sable-3.pdf");
    await expect(documents).not.toContainText("sable-2.pdf");
    await expect(page.getByRole("button", { name: /^Split \d+ into a new record$/ })).toHaveCount(0);

    expect(filenames(await detail(session, created.id))).toEqual(["sable-1.pdf", "sable-3.pdf"]);
    expect(filenames(await detail(session, sable.id))).toEqual(["sable-2.pdf"]);
    const records = (await entities(session)).filter((row) => row.display_name === "Sable Logistics Limited");
    expect(records.map((row) => row.documents).sort()).toEqual([1, 2]);

    await page.reload();
    await settle(page);
    await expect(documents.getByRole("listitem")).toHaveCount(2);

    // The original, reopened, keeps the third document only.
    await openRecord(page, sable.id);
    await expect(documents.getByRole("listitem")).toHaveCount(1);
    await expect(documents).toContainText("sable-2.pdf");

    // Splitting the only document away would leave an empty record: refused, and the page says why.
    problems.allowHttp(/\/entities\/[^/]+\/split$/, [400], "a split must leave a document behind");
    await page.getByLabel("Select sable-2.pdf", { exact: true }).check();
    await page.getByRole("button", { name: "Split 1 into a new record" }).click();
    await expect(page.getByRole("alert").filter({ hasText: "A split must leave at least one document on the original record." })).toBeVisible();
    expect(filenames(await detail(session, sable.id))).toEqual(["sable-2.pdf"]);
    expect((await entities(session)).filter((row) => row.display_name === "Sable Logistics Limited")).toHaveLength(2);
    await expectHealthyPage(page);
  });

  test("Undo merge: a record with another merged into it gives it back, separate again, after a reload too", async ({ page }) => {
    const session = await apiLogin(customer.email);
    const alder = await one(session, "Alder Trading Company");
    const zinnia = await one(session, "Zinnia Wholesale Partners");
    const merged = await api(session, "POST", `/workspaces/${customer.wsId}/entities/${zinnia.id}/merge`, { into_entity_id: alder.id });
    expect(merged.status, merged.text.slice(0, 300)).toBe(200);
    expect((await entities(session)).filter((row) => row.display_name === "Zinnia Wholesale Partners")).toHaveLength(0);

    await signInAs(page, customer.email);
    // The merged record's own address opens the surviving record.
    await openRecord(page, zinnia.id);
    await expect(page).toHaveURL(new RegExp(`/entities/${alder.id}$`));
    await expect(heading(page, "Alder Trading Company")).toBeVisible();
    await expect(page.getByText("2 documents", { exact: false }).first()).toBeVisible();
    const members = section(page, "Merged records");
    await expect(members).toContainText("Zinnia Wholesale Partners");
    await expect(members).toContainText("1 mention");
    await expect(section(page, "Documents")).toContainText("alder-1.pdf");
    await expect(section(page, "Documents")).toContainText("zinnia-1.pdf");

    const undone = page.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith(`/entities/${zinnia.id}/unmerge`));
    await members.getByRole("button", { name: "Undo merge" }).click();
    expect((await undone).status()).toBe(200);
    await expect(members).toContainText("Nothing has been merged into this record.");
    await expect(members.getByRole("button", { name: "Undo merge" })).toHaveCount(0);
    await expect(section(page, "Documents")).toContainText("alder-1.pdf");
    await expect(section(page, "Documents")).not.toContainText("zinnia-1.pdf");

    // The server: two separate records again, each with its own document.
    const alderNow = await detail(session, alder.id);
    expect(filenames(alderNow)).toEqual(["alder-1.pdf"]);
    expect(alderNow.members).toEqual([]);
    const zinniaNow = await detail(session, zinnia.id);
    expect(zinniaNow.entity.id).toBe(zinnia.id);
    expect(filenames(zinniaNow)).toEqual(["zinnia-1.pdf"]);

    await page.reload();
    await settle(page);
    await expect(members).toContainText("Nothing has been merged into this record.");
    await openRecord(page, zinnia.id);
    await expect(page).toHaveURL(new RegExp(`/entities/${zinnia.id}$`));
    await expect(heading(page, "Zinnia Wholesale Partners")).toBeVisible();
    await expect(section(page, "Documents")).toContainText("zinnia-1.pdf");
    await expectHealthyPage(page);
  });

  test("Erase record (admin): dismissing the confirmation changes nothing; accepting removes the record and its links, the documents stay", async ({ page, problems }) => {
    const session = await apiLogin(customer.email);
    const elm = await one(session, "Elm Hardware Limited");
    const before = await detail(session, elm.id);
    expect(filenames(before)).toEqual(["elm-1.pdf"]);
    const workItemId = before.documents[0].work_item_id;
    const customerRecord = await one(session, BILL_TO);
    expect((await detail(session, customerRecord.id)).relationships.map((r) => r.other_name)).toContain("Elm Hardware Limited");
    const chipNames = async (): Promise<string[]> =>
      (await api<{ chips: Array<{ display_name: string }> }>(session, "GET", `/workspaces/${customer.wsId}/work-items/${workItemId}/entities`))
        .body.chips.map((chip) => chip.display_name);
    expect(await chipNames()).toContain("Elm Hardware Limited");

    await signInAs(page, adminEmail);
    await openRecord(page, elm.id);
    const erase = page.getByRole("button", { name: "Erase record" });

    // Cancel: the in-app question is shown with its warning, and nothing is sent or removed.
    const sent: string[] = [];
    page.on("request", (request) => { if (request.method() === "DELETE") sent.push(request.url()); });
    await erase.click();
    const question = page.getByRole("alertdialog");
    await expect(question).toBeVisible();
    await expect(question).toContainText(ERASE_PROMPT);
    await question.getByRole("button", { name: "Cancel", exact: true }).click();
    await expect(question).toHaveCount(0);
    await expect(heading(page, "Elm Hardware Limited")).toBeVisible();
    expect(sent).toEqual([]);
    expect((await detail(session, elm.id)).entity.display_name).toBe("Elm Hardware Limited");

    // Accept: the record is erased and the page goes back to the list.
    const gone = page.waitForResponse((r) => r.request().method() === "DELETE" && r.url().endsWith(`/entities/${elm.id}`));
    await erase.click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Erase record", exact: true }).click();
    expect((await gone).status()).toBe(200);
    await expect(page).toHaveURL(new RegExp(`/${customer.wsSlug}/entities$`));
    await expect(page.getByRole("heading", { name: "Entity graph" })).toBeVisible();
    await expect(page.getByRole("link", { name: "Elm Hardware Limited", exact: true })).toHaveCount(0);
    await expect(page.getByRole("link", { name: "Fennel Supplies Limited", exact: true })).toBeVisible();

    // The server: the record is gone from the list, the search and its own address; its links went with it.
    expect((await entities(session)).map((row) => row.display_name)).not.toContain("Elm Hardware Limited");
    expect(await entities(session, "&q=Elm Hardware")).toEqual([]);
    const direct = await api(session, "GET", `/workspaces/${customer.wsId}/entities/${elm.id}`);
    expect(direct.status).toBe(404);
    expect((await detail(session, customerRecord.id)).relationships.map((r) => r.other_name)).not.toContain("Elm Hardware Limited");
    expect(await chipNames()).not.toContain("Elm Hardware Limited");
    expect(await chipNames()).toContain(BILL_TO);

    // The document itself is kept.
    const item = await api<{ id: string; filename?: string; original_filename?: string }>(session, "GET", `/workspaces/${customer.wsId}/work-items/${workItemId}`);
    expect(item.status, item.text.slice(0, 200)).toBe(200);
    expect(item.text).toContain("elm-1.pdf");

    // After a reload the list still does not have it, and its old address says so.
    await page.reload();
    await settle(page);
    await expect(page.getByRole("link", { name: "Elm Hardware Limited", exact: true })).toHaveCount(0);
    // Only now is the erased record asked for, on purpose, and it answers 404.
    problems.allowHttp(/\/entities\/[^/]+(\/graph.*)?$/, [404], "the erased record's old address is opened on purpose");
    await openRecord(page, elm.id);
    await expect(page.getByText("Could not load this record")).toBeVisible();
    await expectHealthyPage(page);
  });

  test("a viewer sees none of the record's buttons, and the server refuses each of them", async ({ page }) => {
    const owner = await apiLogin(customer.email);
    const linden = await one(owner, "Linden Stationers Limited");
    const maple = await one(owner, "Maple Cartons Limited");
    const merged = await api(owner, "POST", `/workspaces/${customer.wsId}/entities/${maple.id}/merge`, { into_entity_id: linden.id });
    expect(merged.status, merged.text.slice(0, 300)).toBe(200);
    const juniper = await one(owner, "Juniper Textiles Limited");

    await signInAs(page, viewerEmail);
    await openRecord(page, linden.id);
    await expect(heading(page, "Linden Stationers Limited")).toBeVisible();
    await expect(section(page, "Merged records")).toContainText("Maple Cartons Limited");
    await expect(page.getByRole("button", { name: "Rename", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Erase record" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Undo merge" })).toHaveCount(0);
    await openRecord(page, juniper.id);
    await expect(section(page, "Documents").getByRole("listitem")).toHaveCount(2);
    await expect(page.getByRole("checkbox")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /into a new record$/ })).toHaveCount(0);

    const viewer = await apiLogin(viewerEmail);
    const base = `/workspaces/${customer.wsId}/entities`;
    const mentionId = (await detail(owner, juniper.id)).documents[0].mention_id;
    const refusals = [
      await api(viewer, "PATCH", `${base}/${juniper.id}`, { display_name: "Viewer Rename" }),
      await api(viewer, "POST", `${base}/${juniper.id}/split`, { mention_ids: [mentionId] }),
      await api(viewer, "POST", `${base}/${maple.id}/unmerge`, {}),
      await api(viewer, "DELETE", `${base}/${juniper.id}`),
    ];
    expect(refusals.map((r) => r.status), refusals.map((r) => r.text.slice(0, 120)).join(" | ")).toEqual([403, 403, 403, 403]);
    // Nothing changed.
    expect((await detail(owner, juniper.id)).entity.display_name).toBe("Juniper Textiles Limited");
    expect(filenames(await detail(owner, juniper.id))).toEqual(["juniper-1.pdf", "juniper-2.pdf"]);
    expect((await detail(owner, linden.id)).members.map((m) => m.display_name)).toEqual(["Maple Cartons Limited"]);
    await expectHealthyPage(page);
  });

  test("a contributor renames, splits and undoes a merge, but has no Erase button and the server says 403", async ({ page }) => {
    const owner = await apiLogin(customer.email);
    const fennel = await one(owner, "Fennel Supplies Limited");
    const juniper = await one(owner, "Juniper Textiles Limited");
    const linden = await one(owner, "Linden Stationers Limited");
    const members = (await detail(owner, linden.id)).members;
    expect(members.map((m) => m.display_name)).toEqual(["Maple Cartons Limited"]);
    const mapleId = members[0].id;

    await signInAs(page, contributorEmail);
    await openRecord(page, fennel.id);
    await expect(page.getByRole("button", { name: "Rename", exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Erase record" })).toHaveCount(0);

    // Rename.
    await page.getByRole("button", { name: "Rename", exact: true }).click();
    await page.getByRole("textbox", { name: "Name" }).fill("Fennel Supplies (UK) Limited");
    await page.getByRole("button", { name: "Save", exact: true }).click();
    await expect(heading(page, "Fennel Supplies (UK) Limited")).toBeVisible();
    expect((await detail(owner, fennel.id)).entity.display_name).toBe("Fennel Supplies (UK) Limited");

    // The server refuses the erase, whatever the page shows, and the record stays.
    const contributor = await apiLogin(contributorEmail);
    const refused = await api(contributor, "DELETE", `/workspaces/${customer.wsId}/entities/${fennel.id}`);
    expect(refused.status, refused.text.slice(0, 200)).toBe(403);
    expect((await detail(owner, fennel.id)).entity.display_name).toBe("Fennel Supplies (UK) Limited");

    // Split: one of Juniper's two documents.
    await openRecord(page, juniper.id);
    await page.getByLabel("Select juniper-2.pdf", { exact: true }).check();
    const split = page.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith(`/entities/${juniper.id}/split`));
    await page.getByRole("button", { name: "Split 1 into a new record" }).click();
    const created = (await (await split).json()) as EntityRow;
    await expect(page).toHaveURL(new RegExp(`/entities/${created.id}$`));
    await expect(section(page, "Documents").getByRole("listitem")).toHaveCount(1);
    await expect(section(page, "Documents")).toContainText("juniper-2.pdf");
    expect(filenames(await detail(owner, created.id))).toEqual(["juniper-2.pdf"]);
    expect(filenames(await detail(owner, juniper.id))).toEqual(["juniper-1.pdf"]);

    // Undo merge.
    await openRecord(page, linden.id);
    const merged = section(page, "Merged records");
    await expect(merged).toContainText("Maple Cartons Limited");
    const undone = page.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith(`/entities/${mapleId}/unmerge`));
    await merged.getByRole("button", { name: "Undo merge" }).click();
    expect((await undone).status()).toBe(200);
    await expect(merged).toContainText("Nothing has been merged into this record.");
    expect((await detail(owner, linden.id)).members).toEqual([]);
    expect(filenames(await detail(owner, mapleId))).toEqual(["maple-1.pdf"]);
    await page.reload();
    await settle(page);
    await expect(merged).toContainText("Nothing has been merged into this record.");
    await expectHealthyPage(page);
  });
});
