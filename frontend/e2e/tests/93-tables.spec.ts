/**
 * TABLES (Tables page and table viewer; campaign Session C).
 *
 * A document's table is read and every figure is checked against the arithmetic it has to satisfy. A
 * table whose figures do not reconcile is "Needs review". On a tenant of its own (Business plan) this
 * presses each way a person settles one, in the browser, and checks the page, the API and a reload:
 * correcting the wrong cell (double-click, type, Enter) makes the checks pass; "Accept figures" marks
 * the table Reviewed with its figures as printed; "Reject table" marks it Rejected. A viewer sees the
 * table but has no buttons, and the server refuses their edit and their decision.
 */
import { test, expect, expectHealthyPage, settle } from "../support/fixtures";
import { api, fetchOnce, type ApiSession } from "../support/api";
import { API_BASE, runId } from "../support/env";
import { addMember, newCustomer, signInAs, standIn, type Customer } from "../support/journey";
import { buildPdf } from "../support/sample-docs";

interface TableCell { readonly row: number; readonly col: number; readonly text: string; readonly flags: readonly string[] }
interface TableDetail {
  readonly table: { readonly id: string; readonly status: string; readonly failed_checks: number; readonly original_filename: string };
  readonly cells: readonly TableCell[];
  readonly validations: ReadonlyArray<{ readonly scope: string; readonly outcome: string; readonly row_index: number | null; readonly col_index: number | null }>;
}

/** Five line items (qty × price = amount); the third line's amount is printed 5.00 too high. */
function flaggedTablePdf(label: string): Buffer {
  const rows: Array<[string, number, number]> = [["Bolts", 10, 2.5], ["Nuts", 20, 1.25], ["Washers", 40, 0.75], ["Gaskets", 5, 8], ["Clamps", 8, 6.5]];
  const printed = (index: number): number => rows[index][1] * rows[index][2] + (index === 2 ? 5 : 0);
  const total = rows.reduce((sum, row) => sum + row[1] * row[2], 0);
  return buildPdf([[
    `PARTS STATEMENT ${label}`,
    `Reference: STMT-${label}-${runId()}`,
    "Line items:",
    "|#|Description|Qty|Unit Price|Amount",
    ...rows.map((row, i) => `|${i + 1}|${row[0]}|${row[1]}|${row[2].toFixed(2)}|${printed(i).toFixed(2)}`),
    `|||||${total.toFixed(2)}`,
  ]]);
}

async function uploadTable(customer: Customer, label: string): Promise<string> {
  const form = new FormData();
  form.append("file", new Blob([new Uint8Array(flaggedTablePdf(label))], { type: "application/pdf" }), `parts-${label}-${runId()}.pdf`);
  const response = await fetchOnce(`${API_BASE}/workspaces/${customer.wsId}/work-items`, {
    method: "POST", headers: { Authorization: `Bearer ${customer.session.accessToken}` }, body: form,
  });
  expect(response.status, await response.clone().text()).toBe(201);
  const documentId = String(((await response.json()) as { id: string }).id);
  let tableId = "";
  await expect.poll(async () => {
    const found = await api<{ tables?: Array<{ id: string }> }>(customer.session, "GET", `/workspaces/${customer.wsId}/work-items/${documentId}/tables`);
    tableId = found.body.tables?.[0]?.id ?? "";
    return tableId;
  }, { timeout: 180_000, intervals: [2_000] }).not.toBe("");
  return tableId;
}

const detailOf = async (session: ApiSession, customer: Customer, tableId: string): Promise<TableDetail> => {
  const response = await api<TableDetail>(session, "GET", `/workspaces/${customer.wsId}/tables/${tableId}`);
  expect(response.status, response.text.slice(0, 200)).toBe(200);
  return response.body;
};

test.describe("Tables — correct, accept, reject", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);
  let customer: Customer;
  let toCorrect: string;
  let toAccept: string;
  let toReject: string;

  test.beforeAll(async () => {
    customer = await newCustomer("tables", "Tables Review Ltd");
    standIn("subscribe", customer.orgSlug, "--plan", "business", "--seats", "3");
    toCorrect = await uploadTable(customer, "correct");
    toAccept = await uploadTable(customer, "accept");
    toReject = await uploadTable(customer, "reject");
  });

  test("the list shows the tables that need review, and each opens with the figure that does not reconcile", async ({ page }) => {
    for (const id of [toCorrect, toAccept, toReject]) {
      const detail = await detailOf(customer.session, customer, id);
      expect(detail.table.status, "the printed amount is wrong, so the table is flagged").toBe("FLAGGED");
      expect(detail.table.failed_checks).toBeGreaterThan(0);
    }
    await signInAs(page, customer.email);
    await page.goto(customer.ws("tables"));
    await settle(page);
    await page.getByRole("tab", { name: "Needs review" }).click();
    await expect(page.getByRole("link", { name: /parts-correct-/ })).toBeVisible();
    await page.getByRole("link", { name: /parts-correct-/ }).click();
    await expect(page.getByRole("heading", { level: 1 })).toContainText("parts-correct-");
    await expect(page.getByText("Figures that do not reconcile")).toBeVisible();
    await expect(page.getByRole("button", { name: "Accept figures" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Reject table" })).toBeVisible();
    await expectHealthyPage(page);
  });

  test("correcting the wrong cell makes the checks pass; the correction is marked and survives a reload", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.ws(`tables/${toCorrect}`));
    await settle(page);
    const before = await detailOf(customer.session, customer, toCorrect);
    const failing = before.validations.find((v) => v.scope === "CELL" && v.outcome === "FAIL");
    expect(failing, "one printed amount does not reconcile").toBeTruthy();
    const wrong = before.cells.find((c) => c.row === failing!.row_index && c.col === failing!.col_index)!;
    expect(wrong.text).toContain("35.00");  // 40 × 0.75 = 30.00, printed 35.00

    const grid = page.getByTestId("table-grid");
    await grid.getByRole("cell", { name: wrong.text, exact: true }).dblclick();
    const editor = grid.getByLabel("Corrected value");
    await editor.fill("30.00");
    await editor.press("Enter");

    await expect(grid.getByLabel("corrected")).toBeVisible();
    await expect(page.getByText("Figures that do not reconcile")).toHaveCount(0);
    const after = await detailOf(customer.session, customer, toCorrect);
    expect(after.table.failed_checks).toBe(0);
    expect(after.cells.find((c) => c.row === wrong.row && c.col === wrong.col)).toMatchObject({ text: "30.00" });
    expect(after.cells.find((c) => c.row === wrong.row && c.col === wrong.col)?.flags).toContain("CORRECTED");

    await page.reload();
    await settle(page);
    await expect(page.getByTestId("table-grid").getByLabel("corrected")).toBeVisible();
    await expect(page.getByText("Figures that do not reconcile")).toHaveCount(0);
    // Nothing is left to decide on a table whose checks now pass.
    await expect(page.getByRole("button", { name: "Accept figures" })).toHaveCount(0);
    await expectHealthyPage(page);
  });

  test("Accept figures marks the table Reviewed, with the figures as printed, and it stays so after a reload", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.ws(`tables/${toAccept}`));
    await settle(page);
    await page.getByRole("button", { name: "Accept figures" }).click();
    await expect(page.getByRole("button", { name: "Accept figures" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Reject table" })).toHaveCount(0);
    await expect(page.getByText("Reviewed", { exact: true }).first()).toBeVisible();

    const detail = await detailOf(customer.session, customer, toAccept);
    expect(detail.table.status).toBe("REVIEWED");
    expect(detail.cells.some((c) => c.text === "35.00" && !c.flags.includes("CORRECTED"))).toBe(true);
    await page.reload();
    await settle(page);
    await expect(page.getByText("Reviewed", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Accept figures" })).toHaveCount(0);
  });

  test("Reject table marks the table Rejected and the list shows it", async ({ page }) => {
    await signInAs(page, customer.email);
    await page.goto(customer.ws(`tables/${toReject}`));
    await settle(page);
    await page.getByRole("button", { name: "Reject table" }).click();
    await expect(page.getByRole("button", { name: "Reject table" })).toHaveCount(0);
    expect((await detailOf(customer.session, customer, toReject)).table.status).toBe("REJECTED");
    await page.reload();
    await settle(page);
    await expect(page.getByRole("button", { name: "Accept figures" })).toHaveCount(0);

    await page.goto(customer.ws("tables"));
    await settle(page);
    const row = page.getByRole("link", { name: /parts-reject-/ });
    await expect(row).toBeVisible();
    await page.getByRole("tab", { name: "Needs review" }).click();
    await expect(page.getByRole("link", { name: /parts-reject-/ })).toHaveCount(0);
    await expectHealthyPage(page);
  });

  test("a viewer reads the table but cannot correct, accept or reject it, and the server refuses them", async ({ page }) => {
    const extra = await uploadTable(customer, "viewer");
    const viewer = await addMember(customer, "tables-viewer", "MEMBER", "VIEWER");
    await signInAs(page, viewer.email);
    await page.goto(customer.ws(`tables/${extra}`));
    await settle(page);
    await expect(page.getByTestId("table-grid")).toBeVisible();
    await expect(page.getByRole("button", { name: "Accept figures" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Reject table" })).toHaveCount(0);
    await expect(page.getByText("double-click a cell")).toHaveCount(0);

    const base = `/workspaces/${customer.wsId}/tables/${extra}`;
    const edit = await api(viewer.session, "PATCH", `${base}/cells`, { cells: [{ row: 3, col: 4, text: "30.00" }] });
    const accept = await api(viewer.session, "POST", `${base}/review`, { verdict: "ACCEPT" });
    expect([edit.status, accept.status]).toEqual([403, 403]);
    expect((await detailOf(customer.session, customer, extra)).table.status).toBe("FLAGGED");
    await expectHealthyPage(page);
  });
});
