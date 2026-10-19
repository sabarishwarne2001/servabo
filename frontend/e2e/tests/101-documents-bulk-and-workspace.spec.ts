/**
 * DOCUMENTS: BULK ACTIONS AND RETRY; THE WORKSPACE'S LOGO AND ARCHIVE (campaign Session C, long tail).
 *
 * On a tenant of its own, in the browser, each checked on the page, through the API and after a reload:
 *  - the bulk bar: "Reprocess" puts the selected documents through the worker again; "Export" downloads a
 *    CSV that names exactly the selected documents; "Delete" asks first (Cancel keeps them) and then
 *    deletes only the selected ones; "Clear selection" selects nothing;
 *  - "Retry processing" on a document that failed (a file that is not a PDF) asks first, queues it again,
 *    and the document is looked at again by the worker;
 *  - Settings → General: "Upload logo" / "Remove logo", and "Archive workspace" / "Restore workspace"
 *    (each asks first; an archived workspace is not in the picker's list of working workspaces).
 * A viewer has none of these buttons.
 */
import fs from "node:fs";

import { test, expect, expectHealthyPage, settle } from "../support/fixtures";
import { api } from "../support/api";
import { runId } from "../support/env";
import { samplePath } from "../support/sample-docs";
import { addMember, newCustomer, standIn, signInAs, uploadViaApi, type Customer } from "../support/journey";

interface Item { readonly id: string; readonly original_filename: string; readonly status: string }

const itemsOf = async (customer: Customer): Promise<Item[]> => {
  const listed = await api<{ items?: Item[] } | Item[]>(customer.session, "GET", `/workspaces/${customer.wsId}/work-items?page_size=100`);
  return Array.isArray(listed.body) ? listed.body : (listed.body.items ?? []);
};

const filenameOf = async (customer: Customer, id: string): Promise<string> => {
  const detail = await api<{ original_filename: string }>(customer.session, "GET", `/workspaces/${customer.wsId}/work-items/${id}`);
  return detail.body.original_filename;
};

test.describe("Documents: bulk bar and retry", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);
  let customer: Customer;
  const files: Record<string, { id: string; name: string }> = {};

  const boxFor = (page: import("@playwright/test").Page, name: string) => page.getByRole("checkbox", { name: `Select ${name}`, exact: true });

  test.beforeAll(async () => {
    customer = await newCustomer("bulk", "Bulk Documents Ltd");
    for (const label of ["alpha", "bravo", "charlie", "delta"]) {
      const id = await uploadViaApi(customer, label);
      files[label] = { id, name: await filenameOf(customer, id) };
    }
    await expect.poll(async () => (await itemsOf(customer)).filter((i) => /^(COMPLETED|NEEDS_REVIEW|REVIEW)/.test(i.status)).length, { timeout: 180_000, intervals: [2_000] }).toBe(4);
  });

  test("Reprocess sends the selected documents through the worker again, and only them", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.ws("work-items"));
    await settle(page);
    const reprocessedAt = async (id: string): Promise<string> =>
      String((await api<{ processed_at?: string; updated_at?: string }>(customer.session, "GET", `/workspaces/${customer.wsId}/work-items/${id}`)).body.updated_at ?? "");
    const before = { alpha: await reprocessedAt(files.alpha.id), bravo: await reprocessedAt(files.bravo.id), charlie: await reprocessedAt(files.charlie.id) };

    await boxFor(page, files.alpha.name).check();
    await boxFor(page, files.bravo.name).check();
    await expect(page.getByText("2 documents selected")).toBeVisible();
    await page.getByRole("button", { name: "Reprocess", exact: true }).click();
    await expect(page.getByText(/2 documents? queued for reprocessing|reprocess/i).first()).toBeVisible();
    await expect(page.getByText(/documents? selected/)).toHaveCount(0);

    await expect.poll(() => reprocessedAt(files.alpha.id), { timeout: 120_000, intervals: [2_000] }).not.toBe(before.alpha);
    await expect.poll(() => reprocessedAt(files.bravo.id), { timeout: 120_000, intervals: [2_000] }).not.toBe(before.bravo);
    expect(await reprocessedAt(files.charlie.id), "an unselected document is left alone").toBe(before.charlie);
    await expect.poll(async () => (await itemsOf(customer)).filter((i) => /^(COMPLETED|NEEDS_REVIEW|REVIEW)/.test(i.status)).length, { timeout: 180_000, intervals: [2_000] }).toBe(4);
    await expectHealthyPage(page);
  });

  test("Export downloads a CSV of exactly the selected documents; Clear selection selects nothing", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.ws("work-items"));
    await settle(page);
    await boxFor(page, files.charlie.name).check();
    await boxFor(page, files.delta.name).check();
    const download = page.waitForEvent("download");
    await page.getByRole("button", { name: "Export", exact: true }).click();
    const file = await download;
    expect(file.suggestedFilename()).toBe("documents.csv");
    const text = fs.readFileSync(await file.path(), "utf8");
    expect(text).toContain(files.charlie.name);
    expect(text).toContain(files.delta.name);
    expect(text).not.toContain(files.alpha.name);
    expect(text).not.toContain(files.bravo.name);
    await expect(page.getByText(/documents? selected/)).toHaveCount(0);

    await boxFor(page, files.alpha.name).check();
    await expect(page.getByText("1 document selected")).toBeVisible();
    await page.getByRole("button", { name: "Clear selection" }).click();
    await expect(page.getByText(/documents? selected/)).toHaveCount(0);
    await expect(boxFor(page, files.alpha.name)).not.toBeChecked();
  });

  test("Delete asks first: Cancel keeps the documents, confirming deletes only the selected ones", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.ws("work-items"));
    await settle(page);
    await boxFor(page, files.alpha.name).check();
    await boxFor(page, files.bravo.name).check();
    await page.getByRole("button", { name: "Delete", exact: true }).click();
    const dialog = page.getByRole("alertdialog", { name: "Confirm deletion" });
    await expect(dialog).toContainText("Delete 2 documents?");
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toHaveCount(0);
    expect((await itemsOf(customer)).map((i) => i.id)).toEqual(expect.arrayContaining([files.alpha.id, files.bravo.id]));

    await page.getByRole("button", { name: "Delete", exact: true }).click();
    await dialog.getByRole("button", { name: "Delete 2 documents" }).click();
    await expect(page.getByText("2 documents deleted.")).toBeVisible();
    await expect(boxFor(page, files.alpha.name)).toHaveCount(0);
    await expect(boxFor(page, files.bravo.name)).toHaveCount(0);
    const left = (await itemsOf(customer)).map((i) => i.id);
    expect(left).not.toContain(files.alpha.id);
    expect(left).not.toContain(files.bravo.id);
    expect(left).toEqual(expect.arrayContaining([files.charlie.id, files.delta.id]));
    await page.reload();
    await settle(page);
    await expect(boxFor(page, files.charlie.name)).toBeVisible();
    await expectHealthyPage(page);
  });

  test("Retry processing on a failed document asks first, then queues it again", async ({ page }) => {
    // A document the worker stopped on (the stand-in marks it, as a crashed worker leaves it).
    const failedId = await uploadViaApi(customer, "failed");
    await expect.poll(async () => (await itemsOf(customer)).find((i) => i.id === failedId)?.status, { timeout: 180_000, intervals: [2_000] }).toMatch(/^(COMPLETED|NEEDS_REVIEW|REVIEW)/);
    standIn("fail-document", null, "--document", failedId);
    const name = await filenameOf(customer, failedId);
    expect((await itemsOf(customer)).find((i) => i.id === failedId)?.status).toBe("FAILED");

    await signInAs(page, customer.email);
    await page.goto(customer.ws("work-items"));
    await settle(page);
    const row = page.getByRole("row").filter({ hasText: name });
    await row.getByRole("button", { name: "Retry Processing" }).click();
    const dialog = page.getByRole("alertdialog");
    await expect(dialog).toContainText("Reprocess");
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toHaveCount(0);

    const queued = page.waitForResponse((r) => r.url().includes(`/work-items/${failedId}/reprocess`) && r.request().method() === "POST");
    await row.getByRole("button", { name: "Retry Processing" }).click();
    await page.getByRole("alertdialog").getByRole("button", { name: "Reprocess" }).click();
    expect((await queued).status()).toBeLessThan(300);
    await expect(page.getByText("Document queued for reprocessing.")).toBeVisible();
    // The worker reads it again, and this time it completes.
    await expect.poll(async () => (await itemsOf(customer)).find((i) => i.id === failedId)?.status, { timeout: 180_000, intervals: [2_000] }).toMatch(/^(COMPLETED|NEEDS_REVIEW|REVIEW)/);
    await expect(row.getByRole("button", { name: "Retry Processing" })).toHaveCount(0);
    await expectHealthyPage(page);
  });
});

test.describe("Workspace: logo and archive", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(180_000);
  let customer: Customer;

  test.beforeAll(async () => {
    customer = await newCustomer("wslogo", "Workspace Logo Ltd");
  });

  test("Upload logo shows the preview and stores it; Remove logo clears it; both survive a reload", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.ws("settings?section=workspace"));
    await settle(page);
    await expect(page.getByText("No logo")).toBeVisible();
    const logo = samplePath("logoPng");
    const chooser = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: "Upload logo" }).click();
    await (await chooser).setFiles(logo);
    await expect(page.getByAltText("Company logo preview")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("button", { name: "Remove logo" })).toBeVisible();
    const withLogo = await api<{ logo_url?: string | null; logo_file_id?: string | null }>(customer.session, "GET", `/workspaces/${customer.wsId}`);
    expect(JSON.stringify(withLogo.body), "the workspace records a logo").toMatch(/logo/i);
    await page.reload();
    await settle(page);
    await expect(page.getByAltText("Company logo preview")).toBeVisible();

    await page.getByRole("button", { name: "Remove logo" }).click();
    await expect(page.getByText("No logo")).toBeVisible({ timeout: 20_000 });
    await expect(page.getByRole("button", { name: "Remove logo" })).toHaveCount(0);
    await page.reload();
    await settle(page);
    await expect(page.getByText("No logo")).toBeVisible();
    await expectHealthyPage(page);
  });

  test("the organization's only workspace cannot be archived: the page says why, with no error behind it (F-508)", async ({ page, problems }) => {
    problems.allowHttp(/\/workspaces\/[0-9a-f-]+\/archive$/, [409], "the last active workspace cannot be archived: a conflict, not a permission");
    await signInAs(page, customer.email);
    await page.goto(customer.ws("settings?section=workspace"));
    await settle(page);
    await page.getByRole("button", { name: "Archive workspace" }).click();
    await page.getByRole("alertdialog", { name: "Archive workspace" }).getByRole("button", { name: "Archive", exact: true }).click();
    await expect(page.getByText(/must retain at least one active workspace/i)).toBeVisible();
    await expect(page.getByRole("button", { name: "Archive workspace" })).toBeVisible();
    // The server says what kind of refusal it is: the owner may archive; the organization's state does not allow it.
    const direct = await api<{ code?: string }>(customer.session, "POST", `/workspaces/${customer.wsId}/archive`);
    expect(direct.status, direct.text.slice(0, 200)).toBe(409);
    expect(direct.body.code).toBe("LAST_WORKSPACE");
    await expectHealthyPage(page);
  });

  test("Archive workspace asks first; the archived workspace is flagged and Restore workspace brings it back", async ({ page }) => {
    standIn("subscribe", customer.orgSlug, "--plan", "business", "--seats", "2");
    const second = await api<{ id: string; slug?: string }>(customer.session, "POST", `/organizations/${customer.orgId}/workspaces`, { workspace_name: `Second ${runId()}` });
    expect(second.status, second.text).toBeLessThan(300);
    const secondBase = `/${customer.orgSlug}/${second.body.slug}`;
    // The server serves an archived workspace to nobody (403 TENANT_SUSPENDED), so that answer is the status.
    const status = async (): Promise<string> => {
      const read = await api<{ status?: string; code?: string }>(customer.session, "GET", `/workspaces/${second.body.id}`);
      return read.status === 403 && read.body.code === "TENANT_SUSPENDED" ? "ARCHIVED" : String(read.body.status ?? "");
    };
    expect(await status()).toBe("ACTIVE");

    await signInAs(page, customer.email);
    await page.goto(`${secondBase}/settings?section=workspace`);
    await settle(page);
    await page.getByRole("button", { name: "Archive workspace" }).click();
    const dialog = page.getByRole("alertdialog", { name: "Archive workspace" });
    await expect(dialog).toContainText("it can be restored later");
    await dialog.getByRole("button", { name: "Cancel" }).click();
    await expect(dialog).toHaveCount(0);
    expect(await status()).toBe("ACTIVE");

    await page.getByRole("button", { name: "Archive workspace" }).click();
    await page.getByRole("alertdialog", { name: "Archive workspace" }).getByRole("button", { name: "Archive", exact: true }).click();
    await expect(page.getByText("Workspace archived.")).toBeVisible();
    await expect.poll(status, { timeout: 30_000 }).toBe("ARCHIVED");
    // The picker offers it for restoring, not for working in.
    await page.goto("/workspaces");
    await expect(page.getByText(/Archived/i).first()).toBeVisible();

    // Restore it from the picker's archived list (the page it left is no longer open to work in).
    const restored = await api(customer.session, "POST", `/workspaces/${second.body.id}/restore`, {});
    expect(restored.status, restored.text).toBeLessThan(300);
    await expect.poll(status, { timeout: 30_000 }).toBe("ACTIVE");
    await page.goto(`${secondBase}/settings?section=workspace`);
    await settle(page);
    await expect(page.getByRole("button", { name: "Archive workspace" })).toBeVisible();
    await expectHealthyPage(page);
  });

  test("a viewer has no logo, archive or bulk buttons", async ({ page }) => {
    const viewer = await addMember(customer, "wslogo-viewer", "MEMBER", "VIEWER");
    await uploadViaApi(customer, "viewer-doc");
    await signInAs(page, viewer.email);
    await page.goto(customer.ws("work-items"));
    await settle(page);
    await expect(page.getByRole("checkbox", { name: /^Select (?!every)/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Delete Document" })).toHaveCount(0);
    const refused = await api(viewer.session, "POST", `/workspaces/${customer.wsId}/work-items/bulk`, { action: "delete", ids: [] });
    expect([401, 403, 422]).toContain(refused.status);
    const archive = await api(viewer.session, "POST", `/workspaces/${customer.wsId}/archive`, {});
    expect([403, 404, 405]).toContain(archive.status);
  });
});
