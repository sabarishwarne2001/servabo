/**
 * AUTOMATION CONDITIONS ON MONEY AND DATES, TRIED ON REAL DOCUMENTS (Session J).
 *
 * A customer builds a rule in the browser: "Total amount is greater than ₹10,00,000 (INR)" AND "Invoice date is older
 * than 150 days". Then, before saving, "Test & preview" > "Try it on a document" is used on three invoices that were read
 * earlier:
 *   - old and big       -> the conditions are met, both reasons ✓;
 *   - recent and big    -> not met: the amount is ✓, the date is ✗ and shows the real age ("20 days old");
 *   - recent and small  -> not met: both ✗ and each shows the real value found on the document.
 * The rule is saved. The API holds the value as typed with currency INR and the day count as a number of days; no
 * micros anywhere. The rule card says it in one plain sentence, and the saved rule decides the same on a new document.
 *
 * Accessibility is scanned in both themes on the builder with its conditions and on the open preview dialog.
 * Stood in: the model that reads the three invoices (support/llm-mock.mjs).
 */
import { test, expect } from "../support/fixtures";
import { api } from "../support/api";
import { signInAs, type Customer } from "../support/journey";
import {
  builderOf, cardOf, enterpriseCustomer, expectAccessible, invoiceLines, listRules, processed, uploadLines,
} from "../support/workflow-helpers";

const daysAgo = (days: number): string => new Date(Date.now() - days * 86_400_000).toISOString().slice(0, 10);

let customer: Customer;
const names: Record<"oldBig" | "recentBig" | "recentSmall", string> = { oldBig: "", recentBig: "", recentSmall: "" };
const RULE = "Old big invoices";

test.describe("Automation: money and date conditions, tried on documents", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);

  test.beforeAll(async () => {
    test.setTimeout(240_000);
    customer = await enterpriseCustomer("conditions");
    const made = {
      oldBig: await uploadLines(customer, "oldbig", invoiceLines({ number: "OB-1", total: "12,50,000.00", invoiceDate: daysAgo(200) })),
      recentBig: await uploadLines(customer, "recentbig", invoiceLines({ number: "RB-1", total: "12,50,000.00", invoiceDate: daysAgo(20) })),
      recentSmall: await uploadLines(customer, "recentsmall", invoiceLines({ number: "RS-1", total: "2,50,000.00", invoiceDate: daysAgo(20) })),
    };
    for (const [key, id] of Object.entries(made)) {
      const item = await processed(customer, id);
      names[key as keyof typeof names] = String(item.original_filename);
    }
  });

  test("build the two conditions, try them on three documents, then save", async ({ page }, testInfo) => {
    await signInAs(page, customer.email);
    await page.goto(customer.ws("automation"));
    await page.getByRole("button", { name: "Create New Rule" }).click();
    const builder = builderOf(page);
    await expect(builder.getByRole("heading", { name: "New automation" })).toBeVisible();
    await builder.getByRole("textbox", { name: "Name", exact: true }).fill(RULE);

    // When: a document has been processed (the AI fields are in).
    await builder.getByTestId("flow-node-trigger").click();
    await builder.getByRole("checkbox", { name: /^Document processed \(AI fields ready\)/ }).check();

    // Only if: the money condition, typed the way a person writes it in India.
    await builder.getByTestId("flow-node-conditions").click();
    await builder.getByRole("button", { name: "Add a condition group" }).click();
    const field = builder.getByRole("combobox", { name: "Field" });
    await field.selectOption({ label: "Total amount" });
    await builder.getByRole("combobox", { name: "Comparison" }).selectOption({ label: "is greater than" });
    await builder.getByRole("textbox", { name: "Value" }).fill("₹10,00,000");
    await builder.getByRole("combobox", { name: "Currency" }).selectOption("INR");

    // ... and the date condition, a count of days.
    await builder.getByRole("button", { name: "Condition", exact: true }).click();
    await expect(builder.getByRole("combobox", { name: "Field" })).toHaveCount(2);
    await builder.getByRole("combobox", { name: "Field" }).nth(1).selectOption({ label: "Invoice date" });
    await builder.getByRole("combobox", { name: "Comparison" }).nth(1).selectOption({ label: "is older than" });
    const days = builder.getByRole("spinbutton", { name: "Value" });
    await days.fill("150");
    await expect(builder.getByText("days", { exact: true })).toBeVisible();

    // Then: tell the owner (needs no outside endpoint).
    await builder.getByTestId("flow-node-actions").click();
    await builder.getByRole("combobox", { name: "Add an action" }).first().selectOption("notify.role");
    await builder.getByRole("button", { name: "Owner", exact: true }).click();

    // The sentence at the side reads the rule back in words.
    const summary = builder.getByRole("complementary", { name: "Rule summary" });
    await expect(summary).toContainText("total amount is greater than");
    await expect(summary).toContainText("invoice date is older than 150 days");
    await expect(builder.getByLabel("Rule status")).toContainText("No blocking issues");

    await builder.getByTestId("flow-node-conditions").click();
    await expectAccessible(page, testInfo, "builder with money and date conditions", '[role="dialog"]');

    // Test & preview > Try it on a document.
    await builder.getByRole("button", { name: "Test & preview" }).click();
    const preview = page.getByRole("alertdialog", { name: "Test & preview" });
    await expect(preview).toBeVisible();
    await preview.getByRole("tab", { name: "Try it on a document" }).click();
    const pick = preview.getByLabel("Pick a recent document");
    await expect(pick.locator("option", { hasText: names.oldBig })).toHaveCount(1);

    // 1. Old and big: met, every reason ticked.
    await pick.selectOption({ label: names.oldBig });
    await preview.getByRole("button", { name: "Try it" }).click();
    await expect(preview.getByText(`The conditions are met for ${names.oldBig}`)).toBeVisible();
    let reasons = preview.getByRole("list", { name: "What each condition decided" });
    await expect(reasons.getByRole("listitem")).toHaveCount(2);
    for (const item of await reasons.getByRole("listitem").all()) await expect(item).toContainText("✓");
    await expect(reasons).toContainText("Total amount (INR 12,50,000.00) is greater than INR 10,00,000.00");
    await expect(reasons).toContainText(/Invoice date \(.*\) is older than 150 days/);
    await expect(reasons).toContainText("200 days old");
    await expect(preview.getByRole("list", { name: "What each step would do" })).toBeVisible();

    await expectAccessible(page, testInfo, "preview dialog, conditions met", '[role="alertdialog"]');

    // 2. Recent and big: not met. The amount passes, the date does not, and says how old it is.
    await pick.selectOption({ label: names.recentBig });
    await preview.getByRole("button", { name: "Try it" }).click();
    await expect(preview.getByText(`The conditions are not met for ${names.recentBig}: nothing would run.`)).toBeVisible();
    reasons = preview.getByRole("list", { name: "What each condition decided" });
    await expect(reasons.getByRole("listitem").filter({ hasText: "Total amount" })).toContainText("✓");
    const dateReason = reasons.getByRole("listitem").filter({ hasText: "Invoice date" });
    await expect(dateReason).toContainText("✗");
    await expect(dateReason).toContainText("20 days old");
    await expect(dateReason).toContainText(daysAgo(20));

    // 3. Recent and small: both fail, each with the value found on the document.
    await pick.selectOption({ label: names.recentSmall });
    await preview.getByRole("button", { name: "Try it" }).click();
    await expect(preview.getByText(`The conditions are not met for ${names.recentSmall}`)).toBeVisible();
    reasons = preview.getByRole("list", { name: "What each condition decided" });
    const amountReason = reasons.getByRole("listitem").filter({ hasText: "Total amount" });
    await expect(amountReason).toContainText("✗");
    await expect(amountReason).toContainText("INR 2,50,000.00");
    await expect(reasons.getByRole("listitem").filter({ hasText: "Invoice date" })).toContainText("✗");

    // Nothing was run, sent or saved by trying.
    expect((await listRules(customer)).filter((r) => r.name === RULE)).toHaveLength(0);

    await preview.getByRole("button", { name: "Close" }).click();
    await expect(preview).toHaveCount(0);

    await builder.getByRole("button", { name: "Create rule" }).click();
    await expect(builder).toHaveCount(0, { timeout: 20_000 });
    await expect(cardOf(page, RULE)).toBeVisible();
    await expect(cardOf(page, RULE).getByTestId("rule-sentence")).toContainText("older than 150 days");
  });

  test("the server keeps the money as typed, in rupees, with INR; the date as a number of days", async () => {
    const rule = (await listRules(customer)).find((r) => r.name === RULE)!;
    expect(rule).toBeTruthy();
    expect(rule.is_active).toBe(true);
    expect(rule.triggers).toEqual(["document.ready"]);
    const conditions = rule.condition_groups!.flatMap((g) => g.conditions);
    expect(conditions).toHaveLength(2);
    const money = conditions.find((c) => c.field === "total_amount")!;
    expect(money.operator).toBe("GREATER_THAN");
    expect(String(money.value)).toBe("₹10,00,000");        // as the person typed it
    expect(money.currency).toBe("INR");
    expect(JSON.stringify(rule.condition_groups)).not.toMatch(/micros/i);
    expect(Number(String(money.value).replace(/[^\d.]/g, ""))).toBe(1_000_000);   // rupees, not millionths
    const date = conditions.find((c) => c.field === "invoice_date")!;
    expect(date.operator).toBe("OLDER_THAN_DAYS");
    expect(String(date.value)).toBe("150");
    expect(date.currency ?? null).toBeNull();
  });

  test("the saved rule decides the same on the same documents (the server's draft check agrees)", async () => {
    // The preview in the builder and the engine share one evaluator; ask the saved rule's own test too.
    const rule = (await listRules(customer)).find((r) => r.name === RULE)!;
    const documents = await api<{ items: Array<{ id: string; original_filename: string }> }>(
      customer.session, "GET", `/workspaces/${customer.wsId}/work-items?limit=100`);
    const idOf = (name: string): string => documents.body.items.find((d) => d.original_filename === name)!.id;
    const verdict = async (name: string): Promise<boolean> => {
      const tried = await api<{ matched: boolean }>(customer.session, "POST", `/workspaces/${customer.wsId}/automation/rules/${rule.id}/test`, { work_item_id: idOf(name) });
      expect(tried.status, tried.text.slice(0, 300)).toBe(200);
      return tried.body.matched;
    };
    expect(await verdict(names.oldBig)).toBe(true);
    expect(await verdict(names.recentBig)).toBe(false);
    expect(await verdict(names.recentSmall)).toBe(false);
  });
});
