/**
 * ERROR TRACKING IS OFF WHEN THE DSN IS EMPTY (Final session 1, 4A): the web app loads no error-tracking SDK and sends nothing anywhere,
 * even when a page throws an error nobody handles. (The scrubbing and the "sends to the ingest" half are in
 * `frontend/src/monitoring.test.ts` and the backend's `tests/infra/test_error_tracking.py`, against stand-in ingests.)
 */
import { test, expect } from "../support/fixtures";
import { signInAs, newCustomer } from "../support/journey";

test("a web app built without a DSN sends nothing, even for an unhandled error", async ({ page }) => {
  test.setTimeout(120_000);
  const customer = await newCustomer("noerrtrack", "No Tracking Ltd");
  const requests: string[] = [];
  page.on("request", (request) => requests.push(request.url()));
  await signInAs(page, customer.email);
  await page.goto(customer.ws(""));
  await expect(page.locator("main")).toBeVisible({ timeout: 30_000 });
  // The same event the browser raises for an uncaught error (an error tracker listens for it), without failing the strict page policy.
  await page.evaluate(() => {
    const error = new Error("nobody handles this: priya@example.com INR 12,50,000.00");
    window.dispatchEvent(new ErrorEvent("error", { error, message: error.message }));
  });
  await page.waitForTimeout(1_500);
  expect(requests.filter((url) => /sentry|glitchtip|\.ingest\./i.test(url))).toEqual([]);
  expect(await page.evaluate(() => Boolean((window as unknown as { __SENTRY__?: unknown }).__SENTRY__))).toBe(false);
});
