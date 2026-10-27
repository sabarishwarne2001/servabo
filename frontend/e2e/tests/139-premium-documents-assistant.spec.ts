/** Real API/persistence coverage. E2E_LLM=1 uses the repository's deterministic model. */
import AxeBuilder from "@axe-core/playwright";
import { test, expect } from "../support/fixtures";
import { api, resolveWorkspaceId } from "../support/api";
import { runId, ws } from "../support/env";

test.use({ user: "C.owner" });

test("document filters survive reload and counts remain workspace-wide", async ({
  page,
  session,
}) => {
  const { workspaceId } = await resolveWorkspaceId(session!, "caretakers-global", "operations");
  const counts = await api<{ total: number }>(
    session,
    "GET",
    `/workspaces/${workspaceId}/work-items/counts`,
  );
  expect(counts.status).toBe(200);
  await page.goto(
    ws(
      "C",
      "work-items?search=INV-E2E-100&format=pdf&status=COMPLETED&sort=original_filename&order=asc",
    ),
  );
  await expect(page.locator("tbody tr")).toHaveCount(2);
  await expect(page.getByRole("button", { name: "Show total documents" })).toContainText(
    String(counts.body.total),
  );
  await page.reload();
  await expect(page.getByRole("textbox", { name: "Search documents by filename" })).toHaveValue(
    "INV-E2E-100",
  );
  await expect(page.getByRole("combobox", { name: "Filter by format" })).toHaveValue("pdf");
  await page.getByRole("button", { name: "Reset", exact: true }).click();
  await expect(page).not.toHaveURL(/search=|format=|status=/);
  await page.getByLabel("Uploaded from", { exact: true }).fill("2099-01-01");
  await page.getByRole("button", { name: "Apply Filters" }).click();
  await expect(page.getByText("No documents found", { exact: true })).toBeVisible();
  await expect(page).toHaveURL(/from=2099-01-01/);
});

test("sort and rows per page send the server contract", async ({ page }) => {
  await page.goto(ws("C", "work-items"));
  await expect(page.locator("tbody tr").first()).toBeVisible();
  const sorted = page.waitForResponse(
    (r) => r.url().includes("sort_by=original_filename") && r.request().method() === "GET",
  );
  await page.getByRole("button", { name: "Document Filename" }).click();
  expect((await sorted).ok()).toBe(true);
  const resized = page.waitForResponse(
    (r) => r.url().includes("limit=25") && r.request().method() === "GET",
  );
  await page.getByLabel("Rows per page").selectOption("25");
  expect((await resized).ok()).toBe(true);
  await expect(page).toHaveURL(/pageSize=25/);
});

test("starters fill the composer; cited answers persist and export", async ({ page }) => {
  test.skip(process.env.E2E_LLM !== "1", "Needs a configured test model.");
  await page.goto(ws("C", "assistant"));
  await page.getByRole("button", { name: "New", exact: true }).click();
  await page.getByRole("button", { name: /Extract key information/ }).click();
  const input = page.getByRole("textbox", { name: "Message to the assistant" });
  await expect(input).toHaveValue(/Extract the key names/);
  await input.fill("What is the total amount due on invoice INV-E2E-1001?");
  await input.press("Enter");
  await expect(page.getByRole("button", { name: /^Open citation / }).first()).toBeVisible({
    timeout: 90000,
  });
  await expect(page.locator("main")).toContainText(/1,?250/);
  await page
    .getByRole("button", { name: /^Open citation / })
    .first()
    .click();
  await expect(page.getByTestId("citation-drawer")).toBeVisible();
  await page
    .getByTestId("citation-drawer")
    .getByRole("button", { name: "Close citation drawer" })
    .click();
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export", exact: true }).click();
  expect((await download).suggestedFilename()).toMatch(/\.md$/);
  await page.reload();
  await expect(page.getByRole("button", { name: /^Open citation / }).first()).toBeVisible();
});

test("scope and templates persist through the real APIs", async ({ page }) => {
  await page.goto(ws("C", "assistant"));
  await page.getByRole("button", { name: "New", exact: true }).click();
  await page.getByRole("button", { name: "Whole workspace", exact: true }).click();
  const picker = page.getByRole("dialog", { name: /documents|scope/i });
  await picker.getByRole("checkbox").first().check();
  await picker.getByRole("button", { name: /Search selected \(1\)/ }).click();
  await expect(page.getByRole("button", { name: "1 selected document(s)" })).toBeVisible();
  await page.getByRole("button", { name: "Templates", exact: true }).click();
  const templates = page.getByRole("dialog", { name: "Prompt templates" });
  const name = `Premium template ${runId()}`;
  await templates.getByPlaceholder("Template name").fill(name);
  await templates.locator("textarea").fill("List the obligations with source citations.");
  await templates.getByRole("button", { name: /Save template/i }).click();
  await templates.getByText(name, { exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Message to the assistant" })).toHaveValue(
    "List the obligations with source citations.",
  );
});

test("unsent drafts stay with their conversation", async ({ page }) => {
  await page.goto(ws("C", "assistant"));
  await page.getByRole("button", { name: "New", exact: true }).click();
  const first = page.locator('[aria-label="Conversations"] button[aria-current="true"]');
  const title = `Draft ${runId()}`;
  await first
    .locator("..")
    .getByRole("button", { name: /^Actions for/ })
    .click();
  await page.getByRole("menuitem", { name: "Rename", exact: true }).click();
  await page.getByRole("textbox", { name: "Conversation title" }).fill(title);
  await page.getByRole("button", { name: "Save title" }).click();
  await page
    .getByRole("textbox", { name: "Message to the assistant" })
    .fill("An unsent question for this conversation only");
  await page.getByRole("button", { name: "New", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "Message to the assistant" })).toHaveValue("");
  await page
    .getByRole("button", { name: new RegExp(title) })
    .first()
    .click();
  await expect(page.getByRole("textbox", { name: "Message to the assistant" })).toHaveValue(
    "An unsent question for this conversation only",
  );
});

test("both themes and narrow viewports keep the console usable", async ({ page }, testInfo) => {
  test.setTimeout(180000);
  for (const theme of ["dark", "light"] as const) {
    await page.emulateMedia({ colorScheme: theme, reducedMotion: "reduce" });
    await page.addInitScript((value) => {
      localStorage.setItem(
        "servabo_ui_preferences",
        JSON.stringify({ state: { theme: value }, version: 0 }),
      );
    }, theme);
    for (const width of [1440, 768, 390]) {
      await page.setViewportSize({ width, height: 960 });
      for (const route of ["work-items", "assistant"]) {
        await page.goto(ws("C", route));
        await expect(
          page.getByRole("heading", {
            name: route === "work-items" ? "Documents Database" : "AI Assistant",
            exact: true,
          }),
        ).toBeVisible();
        await expect
          .poll(() =>
            page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
          )
          .toBe(true);
        if (route === "assistant" && width >= 1024) {
          const bounds = await page.locator(".assistant-workbench").boundingBox();
          expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(970);
          await expect(
            page.getByRole("textbox", { name: "Message to the assistant" }),
          ).toBeInViewport();
        }
        if (width !== 768) {
          const accessibility = await new AxeBuilder({ page })
            .include(".intelligence-page")
            .withTags(["wcag2a", "wcag2aa", "wcag21aa", "wcag22aa"])
            .analyze();
          expect(accessibility.violations).toEqual([]);
        }
        await page.screenshot({
          path: testInfo.outputPath(`${route}-${theme}-${width}.png`),
          fullPage: true,
        });
      }
    }
  }
  const accessibility = await new AxeBuilder({ page })
    .include(".intelligence-page")
    .withTags(["wcag2a", "wcag2aa", "wcag21aa"])
    .analyze();
  expect(accessibility.violations).toEqual([]);
});

test("failed sends keep the question available for retry", async ({ page, problems }) => {
  problems.allowHttp(
    /\/assistant\/conversations\/[^/]+\/messages$/,
    [503],
    "Controlled provider-unavailable response tests composer recovery.",
  );
  await page.goto(ws("C", "assistant"));
  await page.getByRole("button", { name: "New", exact: true }).click();
  await page.route(/\/assistant\/conversations\/[^/]+\/messages$/, (route) =>
    route.fulfill({ status: 503, json: { detail: "Temporarily unavailable" } }),
  );
  const question = "A question retained when the service is unavailable";
  await page.getByRole("textbox", { name: "Message to the assistant" }).fill(question);
  await page.getByRole("button", { name: "Send message" }).click();
  await expect(page.getByTestId("assistant-send-failure")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Message to the assistant" })).toHaveValue(
    question,
  );
});

test.describe("viewer controls", () => {
  test.use({ user: "C.viewer" });
  test("readers are not offered scope, model or message mutations", async ({ page }) => {
    await page.goto(ws("C", "assistant"));
    await expect(page.getByRole("button", { name: "New", exact: true })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Send message" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Summarize documents/ })).toHaveCount(0);
  });
});
