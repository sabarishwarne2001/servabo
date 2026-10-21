/**
 * NO NATIVE BROWSER POP-UPS (Session J, Phase 5A): Servabo asks in its own dialog, never the browser's "localhost says".
 *
 * Part 1, the rule builder's question "Discard your changes?":
 *   - with nothing edited, X and Esc close the builder at once, with no question;
 *   - with an edit, X asks; "Keep editing" keeps the draft (the name is still there); Esc while the question is open closes
 *     ONLY the question (the builder stays, with its draft); "Discard changes" closes the builder and saves nothing;
 *   - the same when Esc is the first key; the save keys do nothing behind the question; a recipe that was not saved asks too.
 * Part 2, every other pop-up that Phase 5A replaced (commit d92c60f). Each is opened and answered both ways: Cancel (and Esc,
 * and a click beside the dialog) change nothing, the confirming button does the work. Already proven, with the same two
 * answers, in the specs named here: Erase record (90), Revoke feed (98), Restore default mapping and Do not send a posting
 * (86), Accept variance, the one that was a text prompt (96: Cancel and an empty note change nothing, a typed note is stored).
 * Covered here: Delete obligation, Delete holiday calendar, Delete lookup table, Delete comparison, Delete ERP target,
 * Change the sign-in method, Delete warehouse destination.
 *
 * Throughout, the page's `dialog` event must never fire: the strict fixture listens (specs never do) and records a
 * "nativedialog" problem, which fails the test and which every test here also asserts is absent; a last test proves the
 * log is not blind by calling confirm() on its own page.
 * Accessibility is scanned in both themes on the discard question and on the Delete obligation question.
 *
 * Stood in: the plan ("bought" through the stand-in, as every journey does); nothing else.
 */
import AxeBuilder from "@axe-core/playwright";
import type { Locator, Page, TestInfo } from "@playwright/test";

import { test, expect, expectHealthyPage, settle } from "../support/fixtures";
import { api, apiLogin, type ApiSession } from "../support/api";
import { runId } from "../support/env";
import { newCustomer, signInAs, standIn, uploadViaApi, type Customer } from "../support/journey";

let owner: Customer;
const stamp = runId();

/* ------------------------------------------------------------------ the fixture's dialog log */

test.afterEach(({ problems }) => {
  // The strict fixture listens for the page's dialog event (specs never do) and records each as a "nativedialog" problem.
  expect(problems.all.filter((p) => p.kind === "nativedialog").map((p) => p.message), "the browser's own pop-up appeared").toEqual([]);
});

/* ------------------------------------------------------------------ helpers */

const builderOf = (page: Page) => page.getByRole("dialog", { name: /New automation|Edit automation|New automation from a recipe/ });
const discardOf = (page: Page) => page.getByRole("alertdialog", { name: "Discard your changes?" });
const nameBox = (page: Page) => builderOf(page).getByRole("textbox", { name: "Name", exact: true });

async function openBuilder(page: Page): Promise<void> {
  await page.goto(owner.ws("automation"));
  await page.getByRole("button", { name: "Create New Rule" }).click();
  await expect(builderOf(page)).toBeVisible();
  await expect(nameBox(page)).toBeVisible();
}

async function axe(page: Page, testInfo: TestInfo, what: string): Promise<void> {
  await settle(page, 300);
  const results = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"]).analyze();
  const found = results.violations.filter((v) => v.impact === "serious" || v.impact === "critical")
    .map((v) => `${what}: ${v.impact} ${v.id}: ${v.help} — ${v.nodes.slice(0, 3).map((n) => n.target.join(" ")).join(" | ")}`);
  for (const v of results.violations.filter((x) => !found.some((f) => f.includes(x.id)))) {
    testInfo.annotations.push({ type: `axe ${v.impact}`, description: `${what}: ${v.id} (${v.nodes.length})` });
  }
  expect(found, `${what} with serious or critical accessibility violations`).toEqual([]);
}

/**
 * One Servabo question, answered every way. `reopen` opens it again; `unchanged` and `done` read the real state (through
 * the API, not the page). The safe button has focus first; Cancel, Esc and a click beside the dialog change nothing; the
 * confirming button does the work and the dialog goes away.
 */
async function askAndAnswer(
  page: Page,
  options: {
    title: string;
    confirm: string;
    reopen: () => Promise<void>;
    unchanged: () => Promise<void>;
    done: () => Promise<void>;
    mentions?: RegExp;
  },
): Promise<void> {
  const dialog = page.getByRole("alertdialog", { name: options.title });
  const open = async (): Promise<Locator> => {
    await options.reopen();
    await expect(dialog).toBeVisible();
    return dialog;
  };
  await open();
  if (options.mentions) await expect(dialog).toContainText(options.mentions);
  // The safe answer is where the keyboard starts, and the confirming button says what it will do.
  await expect(dialog.getByRole("button", { name: "Cancel", exact: true })).toBeFocused();
  await expect(dialog.getByRole("button", { name: options.confirm, exact: true })).toBeEnabled();

  await dialog.getByRole("button", { name: "Cancel", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await options.unchanged();

  await open();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  await options.unchanged();

  await open();
  await page.mouse.click(4, 4);            // the dimmed area beside the dialog
  await expect(dialog).toHaveCount(0);
  await options.unchanged();

  await open();
  await dialog.getByRole("button", { name: options.confirm, exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await options.done();
}

const exists = async (session: ApiSession, path: string): Promise<boolean> => {
  const got = await api(session, "GET", path);
  expect([200, 404], `${path} -> ${got.status} ${got.text.slice(0, 200)}`).toContain(got.status);
  return got.status === 200;
};

const ws = (suffix: string): string => `/workspaces/${owner.wsId}${suffix}`;

test.describe("Servabo's own dialogs, never the browser's", () => {
  test.describe.configure({ mode: "serial" });
  test.setTimeout(240_000);

  test.beforeAll(async () => {
    test.setTimeout(420_000);
    owner = await newCustomer("popups", "No Native Popups Ltd");
    standIn("subscribe", owner.orgSlug, "--plan", "enterprise", "--seats", "3");
  });

  /* ================================================================ part 1: the builder */

  test("the builder with nothing edited closes with X and with Esc, with no question", async ({ page }) => {
    await signInAs(page, owner.email);
    await openBuilder(page);
    await builderOf(page).getByRole("button", { name: "Close the flow builder" }).click();
    await expect(builderOf(page)).toHaveCount(0);
    await expect(discardOf(page)).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Create New Rule" })).toBeVisible();

    await page.getByRole("button", { name: "Create New Rule" }).click();
    await expect(nameBox(page)).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(builderOf(page)).toHaveCount(0);
    await expect(discardOf(page)).toHaveCount(0);

    // Typing and then taking it back is no edit either.
    await page.getByRole("button", { name: "Create New Rule" }).click();
    await nameBox(page).fill("a");
    await nameBox(page).fill("");
    await builderOf(page).getByRole("button", { name: "Close the flow builder" }).click();
    await expect(builderOf(page)).toHaveCount(0);
    await expect(discardOf(page)).toHaveCount(0);
    expect((await api<unknown[]>(owner.session, "GET", ws("/automation/rules"))).body).toEqual([]);
    await expectHealthyPage(page);
  });

  test("an edit then X: the question appears; 'Keep editing' keeps the draft; Esc closes only the question; 'Discard changes' closes the builder", async ({ page }) => {
    await signInAs(page, owner.email);
    await openBuilder(page);
    const draft = `Draft I will not keep ${stamp}`;
    await nameBox(page).fill(draft);
    const close = builderOf(page).getByRole("button", { name: "Close the flow builder" });

    await close.click();
    const question = discardOf(page);
    await expect(question).toBeVisible();
    await expect(question).toContainText("The edits you made to this rule will be lost.");
    await expect(question.getByRole("button", { name: "Keep editing", exact: true })).toBeFocused();   // the safe answer first
    await question.getByRole("button", { name: "Keep editing", exact: true }).click();
    await expect(question).toHaveCount(0);
    await expect(builderOf(page)).toBeVisible();
    await expect(nameBox(page)).toHaveValue(draft);

    // Esc with the question open closes the question and nothing behind it.
    await close.click();
    await expect(question).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(question).toHaveCount(0);
    await expect(builderOf(page)).toBeVisible();
    await expect(nameBox(page)).toHaveValue(draft);

    // A click beside the question is "Keep editing" too.
    await close.click();
    await expect(question).toBeVisible();
    await page.mouse.click(4, 4);
    await expect(question).toHaveCount(0);
    await expect(builderOf(page)).toBeVisible();

    await close.click();
    await question.getByRole("button", { name: "Discard changes", exact: true }).click();
    await expect(question).toHaveCount(0);
    await expect(builderOf(page)).toHaveCount(0);
    expect((await api<unknown[]>(owner.session, "GET", ws("/automation/rules"))).body, "nothing was saved").toEqual([]);

    // A new builder starts empty: the discarded draft is gone.
    await page.getByRole("button", { name: "Create New Rule" }).click();
    await expect(nameBox(page)).toHaveValue("");
    await expectHealthyPage(page);
  });

  test("an edit then Esc as the very first key: the question; a second Esc closes only the question; a third Esc asks again; 'Discard changes' closes the builder", async ({ page }) => {
    await signInAs(page, owner.email);
    await openBuilder(page);
    const draft = `Esc first ${stamp}`;
    await nameBox(page).fill(draft);

    await page.keyboard.press("Escape");
    const question = discardOf(page);
    await expect(question).toBeVisible();
    await expect(builderOf(page)).toBeVisible();

    await page.keyboard.press("Escape");
    await expect(question).toHaveCount(0);
    await expect(builderOf(page)).toBeVisible();
    await expect(nameBox(page)).toHaveValue(draft);

    await page.keyboard.press("Escape");
    await expect(question).toBeVisible();                       // the builder still has unsaved edits: it asks again, once
    await expect(page.getByRole("alertdialog")).toHaveCount(1);
    await question.getByRole("button", { name: "Discard changes", exact: true }).click();
    await expect(builderOf(page)).toHaveCount(0);
    await expect(question).toHaveCount(0);
    expect((await api<unknown[]>(owner.session, "GET", ws("/automation/rules"))).body).toEqual([]);
    await expectHealthyPage(page);
  });

  test("behind the question the save keys do nothing; after 'Keep editing' they save", async ({ page }) => {
    await signInAs(page, owner.email);
    await openBuilder(page);
    const name = `Saved by key ${stamp}`;
    await nameBox(page).fill(name);
    await builderOf(page).getByRole("checkbox", { name: /^Document uploaded/ }).check();
    await builderOf(page).getByTestId("flow-node-actions").click();
    await builderOf(page).getByRole("combobox", { name: "Add an action" }).first().selectOption("notify.role");
    await builderOf(page).getByRole("button", { name: "Owner", exact: true }).click();

    const creates: string[] = [];
    page.on("request", (request) => {
      if (request.method() === "POST" && /\/automation\/rules$/.test(new URL(request.url()).pathname)) creates.push(request.url());
    });
    await builderOf(page).getByRole("button", { name: "Close the flow builder" }).click();
    await expect(discardOf(page)).toBeVisible();
    await page.keyboard.press("Control+s");
    await page.keyboard.press("Control+Enter");
    await page.waitForTimeout(500);
    expect(creates, "a save key acted behind the question").toEqual([]);
    await expect(discardOf(page)).toBeVisible();
    await discardOf(page).getByRole("button", { name: "Keep editing", exact: true }).click();
    await expect(builderOf(page)).toBeVisible();

    const saved = page.waitForResponse((r) => /\/automation\/rules$/.test(new URL(r.url()).pathname) && r.request().method() === "POST");
    await page.keyboard.press("Control+s");
    expect((await saved).status()).toBe(201);
    await expect(builderOf(page)).toHaveCount(0);
    const names = (await api<Array<{ name: string }>>(owner.session, "GET", ws("/automation/rules"))).body.map((r) => r.name);
    expect(names).toEqual([name]);
  });

  test("a recipe that was not saved asks before it is closed, and editing a saved rule asks only after a change", async ({ page }) => {
    await signInAs(page, owner.email);
    await page.goto(owner.ws("automation"));
    await page.getByRole("button", { name: "Start from a recipe" }).click();
    await page.getByTestId("recipe-weekly-digest").getByRole("button", { name: /^Use the recipe:/ }).click();
    await expect(builderOf(page)).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(discardOf(page)).toBeVisible();
    await discardOf(page).getByRole("button", { name: "Discard changes", exact: true }).click();
    await expect(builderOf(page)).toHaveCount(0);

    // Editing the saved rule: no change, no question; a change, the question; 'Discard changes' leaves the rule as it was.
    const saved = (await api<Array<{ id: string; name: string }>>(owner.session, "GET", ws("/automation/rules"))).body[0]!;
    await page.reload();
    await page.getByRole("button", { name: `Edit rule ${saved.name}` }).click();
    await expect(builderOf(page)).toBeVisible();
    await nameBox(page).press("Escape");
    await expect(builderOf(page)).toHaveCount(0);
    await expect(discardOf(page)).toHaveCount(0);
    await page.getByRole("button", { name: `Edit rule ${saved.name}` }).click();
    await nameBox(page).fill(`${saved.name} changed`);
    await builderOf(page).getByRole("button", { name: "Close the flow builder" }).click();
    await discardOf(page).getByRole("button", { name: "Discard changes", exact: true }).click();
    await expect(builderOf(page)).toHaveCount(0);
    expect((await api<{ name: string }>(owner.session, "GET", ws(`/automation/rules/${saved.id}`))).body.name).toBe(saved.name);
    await expectHealthyPage(page);
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`the discard question has no serious or critical accessibility violation, ${scheme} theme`, async ({ page }, testInfo) => {
      await page.emulateMedia({ colorScheme: scheme });
      await signInAs(page, owner.email);
      await openBuilder(page);
      await nameBox(page).fill(`Scanned ${stamp}`);
      await builderOf(page).getByRole("button", { name: "Close the flow builder" }).click();
      await expect(discardOf(page)).toBeVisible();
      await axe(page, testInfo, "the discard question over the builder");
      await discardOf(page).getByRole("button", { name: "Keep editing", exact: true }).click();
      await page.keyboard.press("Escape");
      await discardOf(page).getByRole("button", { name: "Discard changes", exact: true }).click();
    });
  }

  /* ================================================================ part 2: the other replaced pop-ups */

  test("Delete this obligation?", async ({ page }) => {
    const title = `Send the renewal notice ${stamp}`;
    const day = new Date(Date.now() + 45 * 86_400_000).toISOString().slice(0, 10);
    const made = await api<{ obligation: { id: string } }>(owner.session, "POST", ws("/obligations"), {
      kind: "NOTICE", title, rule: { kind: "FIXED", date: day, roll: "NONE" },
    });
    expect(made.status, made.text.slice(0, 300)).toBe(201);
    const id = made.body.obligation.id;
    await signInAs(page, owner.email);
    await page.goto(owner.ws(`obligations/${id}`));
    await expect(page.getByRole("heading", { name: title, level: 1 })).toBeVisible({ timeout: 30_000 });
    await askAndAnswer(page, {
      title: "Delete this obligation?",
      confirm: "Delete obligation",
      mentions: /The obligation is removed\. This cannot be undone\./,
      reopen: async () => { await page.getByRole("button", { name: "Delete", exact: true }).click(); },
      unchanged: async () => { expect(await exists(owner.session, ws(`/obligations/${id}`))).toBe(true); },
      done: async () => { await expect.poll(() => exists(owner.session, ws(`/obligations/${id}`))).toBe(false); },
    });
    await expectHealthyPage(page);
  });

  for (const scheme of ["light", "dark"] as const) {
    test(`the Delete obligation question has no serious or critical accessibility violation, ${scheme} theme`, async ({ page }, testInfo) => {
      await page.emulateMedia({ colorScheme: scheme });
      const day = new Date(Date.now() + 50 * 86_400_000).toISOString().slice(0, 10);
      const made = await api<{ obligation: { id: string } }>(owner.session, "POST", ws("/obligations"), {
        kind: "NOTICE", title: `Scanned obligation ${scheme} ${stamp}`, rule: { kind: "FIXED", date: day, roll: "NONE" },
      });
      expect(made.status, made.text.slice(0, 300)).toBe(201);
      await signInAs(page, owner.email);
      await page.goto(owner.ws(`obligations/${made.body.obligation.id}`));
      await page.getByRole("button", { name: "Delete", exact: true }).click();
      await expect(page.getByRole("alertdialog", { name: "Delete this obligation?" })).toBeVisible();
      await axe(page, testInfo, "the Delete obligation question");
      await page.getByRole("alertdialog").getByRole("button", { name: "Cancel", exact: true }).click();
    });
  }

  test("Delete a holiday calendar?", async ({ page }) => {
    const name = `Company holidays ${stamp}`;
    const made = await api<{ id: string }>(owner.session, "POST", ws("/holiday-calendars"), {
      name, holidays: [{ date: "2027-01-26", name: "Republic Day" }], weekend_days: [6, 7],
    });
    expect(made.status, made.text.slice(0, 300)).toBeLessThan(300);
    const id = made.body.id;
    const listed = async (): Promise<boolean> =>
      (await api<{ items: Array<{ id: string }> }>(owner.session, "GET", ws("/holiday-calendars"))).body.items.some((c) => c.id === id);
    await signInAs(page, owner.email);
    await page.goto(owner.ws("obligations"));
    await page.getByRole("tab", { name: "Holiday calendars" }).click();
    const card = page.getByRole("listitem").filter({ hasText: name });
    await expect(card).toBeVisible({ timeout: 30_000 });
    await askAndAnswer(page, {
      title: `Delete ${name}?`,
      confirm: "Delete calendar",
      mentions: /Its obligations fall back to weekends only\./,
      reopen: async () => { await card.getByRole("button", { name: "Delete" }).click(); },
      unchanged: async () => { expect(await listed()).toBe(true); await expect(card).toBeVisible(); },
      done: async () => { await expect.poll(listed).toBe(false); await expect(card).toHaveCount(0); },
    });
    await expectHealthyPage(page);
  });

  test("Delete a lookup table?", async ({ page }) => {
    const name = `departments_${stamp.replace(/[^a-z0-9]/g, "")}`;
    const made = await api<{ id: string }>(owner.session, "POST", ws("/erp/lookups"), { name, entries: { Finance: "6100" } });
    expect(made.status, made.text.slice(0, 300)).toBeLessThan(300);
    const listed = async (): Promise<boolean> =>
      (await api<{ items: Array<{ name: string }> }>(owner.session, "GET", ws("/erp/lookups"))).body.items.some((t) => t.name === name);
    await signInAs(page, owner.email);
    await page.goto(owner.ws("erp"));
    await page.getByRole("tab", { name: "Lookup tables" }).click();
    const card = page.locator("article").filter({ has: page.getByRole("heading", { name, exact: true }) });
    await expect(card).toBeVisible({ timeout: 30_000 });
    await askAndAnswer(page, {
      title: `Delete ${name}?`,
      confirm: "Delete table",
      mentions: /The lookup table is removed\./,
      reopen: async () => { await card.getByRole("button", { name: "Delete" }).click(); },
      unchanged: async () => { expect(await listed()).toBe(true); await expect(card).toBeVisible(); },
      done: async () => { await expect.poll(listed).toBe(false); await expect(card).toHaveCount(0); },
    });
    await expectHealthyPage(page);
  });

  test("Delete this comparison?", async ({ page }) => {
    const first = await uploadViaApi(owner, "compare-a");
    const second = await uploadViaApi(owner, "compare-b");
    for (const id of [first, second]) {
      await expect.poll(async () => String((await api<{ status?: string }>(owner.session, "GET", ws(`/work-items/${id}`))).body.status ?? ""),
        { timeout: 240_000, intervals: [2_000] }).not.toMatch(/^(PENDING|QUEUED|PROCESSING|UPLOADED|)$/);
    }
    const run = await api<{ run: { id: string } }>(owner.session, "POST", ws("/corroboration/runs"), { work_item_ids: [first, second] });
    expect(run.status, run.text.slice(0, 300)).toBeLessThan(300);
    const id = run.body.run.id;
    await signInAs(page, owner.email);
    await page.goto(owner.ws(`corroboration/${id}`));
    await expect(page.getByRole("button", { name: "Delete", exact: true })).toBeVisible({ timeout: 30_000 });
    await askAndAnswer(page, {
      title: "Delete this comparison?",
      confirm: "Delete comparison",
      mentions: /every decision recorded on it are removed/,
      reopen: async () => { await page.getByRole("button", { name: "Delete", exact: true }).click(); },
      unchanged: async () => { expect(await exists(owner.session, ws(`/corroboration/runs/${id}`))).toBe(true); },
      done: async () => { await expect.poll(() => exists(owner.session, ws(`/corroboration/runs/${id}`))).toBe(false); },
    });
    await expectHealthyPage(page);
  });

  test("Delete an ERP target? and Change the sign-in method?", async ({ page }) => {
    // A target with nothing posted can be deleted.
    const gone = await api<{ target: { id: string; name: string } }>(owner.session, "POST", ws("/erp/targets"), {
      name: `Target to delete ${stamp}`, format: "CSV", transport: "DOWNLOAD",
    });
    expect(gone.status, gone.text.slice(0, 300)).toBe(201);
    const goneId = gone.body.target.id;
    await signInAs(page, owner.email);
    await page.goto(owner.ws(`erp/targets/${goneId}`));
    await expect(page.getByRole("heading", { level: 1 })).toContainText(gone.body.target.name);
    await askAndAnswer(page, {
      title: `Delete ${gone.body.target.name}?`,
      confirm: "Delete target",
      mentions: /The target and its mappings are removed\./,
      reopen: async () => { await page.getByRole("button", { name: "Delete", exact: true }).click(); },
      unchanged: async () => { expect(await exists(owner.session, ws(`/erp/targets/${goneId}`))).toBe(true); },
      done: async () => { await expect.poll(() => exists(owner.session, ws(`/erp/targets/${goneId}`))).toBe(false); },
    });

    // A target with a stored credential asks before the sign-in method changes (which removes the credential).
    const kept = await api<{ target: { id: string; name: string; auth_mode: string; credential_set: boolean } }>(owner.session, "POST", ws("/erp/targets"), {
      name: `Target to re-sign-in ${stamp}`, format: "JSON", transport: "HTTP", preset: "QUICKBOOKS_ONLINE", auth_mode: "BEARER",
      config: { http: { base_url: "https://qbo.erp-popups.test" }, qbo: { realm_id: "9130" }, oauth: { token_url: "https://oauth.erp-popups.test/token" } }, credential: { token: `e2e-token-${stamp}` },
    });
    expect(kept.status, kept.text.slice(0, 300)).toBe(201);
    const keptId = kept.body.target.id;
    const row = async (): Promise<{ auth_mode: string; credential_set: boolean }> =>
      (await api<{ target: { auth_mode: string; credential_set: boolean } }>(owner.session, "GET", ws(`/erp/targets/${keptId}`))).body.target;
    expect(await row()).toMatchObject({ auth_mode: "BEARER", credential_set: true });

    await page.goto(owner.ws(`erp/targets/${keptId}`));
    await expect(page.getByRole("heading", { level: 1 })).toContainText(kept.body.target.name);
    const sign = page.locator("label").filter({ has: page.getByText("Sign-in", { exact: true }) }).locator("select");
    await askAndAnswer(page, {
      title: "Change the sign-in method?",
      confirm: "Change and remove credential",
      mentions: /removes the stored credential/,
      reopen: async () => {
        await sign.selectOption({ index: (await sign.locator("option").allTextContents()).findIndex((t) => !/Bearer/.test(t)) });
        await page.getByRole("button", { name: "Save settings" }).click();
      },
      unchanged: async () => { expect(await row()).toMatchObject({ auth_mode: "BEARER", credential_set: true }); },
      done: async () => {
        await expect.poll(async () => (await row()).credential_set).toBe(false);
        expect((await row()).auth_mode).not.toBe("BEARER");
      },
    });
    await expectHealthyPage(page);
  });

  test("Delete a warehouse destination?", async ({ page }) => {
    // Warehouse sync is part of the Enterprise plan, so the owner can add a destination at once.
    await signInAs(page, owner.email);
    const label = `Bucket to remove ${stamp}`;
    await page.goto(owner.org("analytics"));
    await page.getByRole("button", { name: "Add destination" }).first().click();
    await page.getByRole("textbox", { name: "Label" }).fill(label);
    await page.getByRole("textbox", { name: "Bucket" }).fill("popups-e2e-bucket");
    await page.getByRole("textbox", { name: "Region" }).fill("eu-west-2");
    await page.getByRole("textbox", { name: "Key prefix" }).fill("servabo/");
    await page.getByRole("textbox", { name: "Access key ID" }).fill("AKIAE2ETESTONLY0000");
    await page.getByRole("textbox", { name: "Secret access key" }).fill("e2e-secret-not-real");
    await page.getByRole("button", { name: "Add destination" }).last().click();
    await expect(page.locator("main")).toContainText(label, { timeout: 20_000 });
    const listed = async (): Promise<boolean> =>
      (await api<Array<{ label: string }>>(await apiLogin(owner.email), "GET", `/organizations/${owner.orgId}/analytics/destinations`)).body.some((d) => d.label === label);
    expect(await listed()).toBe(true);
    const card = page.locator("main").locator("div").filter({ hasText: label }).filter({ has: page.getByRole("button", { name: "Remove" }) }).last();
    await askAndAnswer(page, {
      title: `Delete "${label}"?`,
      confirm: "Delete destination",
      mentions: /The warehouse destination is removed\./,
      reopen: async () => { await card.getByRole("button", { name: "Remove" }).click(); },
      unchanged: async () => { expect(await listed()).toBe(true); },
      done: async () => { await expect.poll(listed).toBe(false); },
    });
    await expectHealthyPage(page);
  });

  /* ================================================================ the witness is not blind */

  test("the fixture's dialog log does record a native confirm() (so a silent log above means something)", async ({ page, problems }) => {
    await page.goto("about:blank");
    const answer = await page.evaluate(() => window.confirm("Delete everything?"));
    expect(answer).toBe(false);                                   // the fixture dismisses it so the page cannot hang
    const seen = problems.all.filter((p) => p.kind === "nativedialog");
    expect(seen.map((p) => p.message)).toEqual(["confirm: Delete everything?"]);
    expect(problems.unexpected(), "the fixture would fail a test for it").toHaveLength(1);
    // The pop-up was this test's own doing: take it out of the log so the test can end green.
    problems.all.splice(0, problems.all.length, ...problems.all.filter((p) => p.kind !== "nativedialog"));
    expect(problems.unexpected()).toHaveLength(0);
  });
});
