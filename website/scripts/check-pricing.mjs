// Final session 2A (N-187): the price list opens in rupees (India, the target market) and the switch shows dollars,
// with no JavaScript, on the pricing page, the home page and the TRINETRA page; yearly and the add-on follow. The
// figures come from src/data/pricing.json, which the backend writes from the plan seed.
import { readFile } from "node:fs/promises";

import { chromium } from "@playwright/test";

import { serve } from "./serve-dist.mjs";

const data = JSON.parse(await readFile(new URL("../src/data/pricing.json", import.meta.url), "utf-8"));
const price = (key, interval, currency) =>
  data.plans.find((p) => p.key === key).prices.find((p) => p.interval === interval && p.currency === currency).unit_amount / 100;
const rupees = (n) => `₹${n.toLocaleString("en-IN")}`;
const dollars = (n) => `$${n.toLocaleString("en-US")}`;

const server = await serve(Number(process.env.PORT ?? 4324));
const browser = await chromium.launch({ executablePath: process.env.E2E_CHROMIUM_PATH || undefined });
const failures = [];
const visible = async (page, text) => page.getByText(text, { exact: true }).first().isVisible();
try {
  for (const path of ["/pricing", "/", "/trinetra"]) {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
    await page.goto(server.url + path, { waitUntil: "networkidle" });
    const starterInr = rupees(price("developer", "month", "INR"));
    const starterUsd = dollars(price("developer", "month", "USD"));
    if (!(await visible(page, starterInr))) failures.push(`${path}: ${starterInr} is not shown by default`);
    if (await visible(page, starterUsd)) failures.push(`${path}: ${starterUsd} is shown before switching to dollars`);
    await page.getByText("$ Elsewhere").first().click();
    if (!(await visible(page, starterUsd))) failures.push(`${path}: ${starterUsd} is not shown after switching`);
    if (await visible(page, starterInr)) failures.push(`${path}: ${starterInr} is still shown after switching`);
    if (path === "/pricing") {
      await page.getByText("₹ India").first().click();
      await page.getByText("Yearly").first().click();
      const yearly = rupees(price("business", "year", "INR"));
      if (!(await visible(page, yearly))) failures.push(`/pricing: Business yearly ${yearly} is not shown`);
      const body = await page.locator("body").innerText();
      if (!body.includes("GST extra")) failures.push("/pricing: does not say GST extra");
      if (!body.includes("per user / month")) failures.push("/pricing: does not say per user per month");
      // "Developer API keys" is a feature; the plan is "Starter".
      if (/\bDeveloper\b(?! API)/.test(body)) failures.push("/pricing: still names the Developer plan (it is Starter, N-187)");
      const gst = data.addons.find((a) => a.key === "addon.gst_credit");
      const gstInr = rupees(gst.prices.find((p) => p.interval === "month" && p.currency === "INR").unit_amount / 100);
      const card = await page.locator('[data-addon="addon.gst_credit"]').innerText();
      if (!card.includes(gstInr)) failures.push(`/pricing: the GST Credit add-on's ${gstInr} is not shown`);
    }
    await page.close();
  }
} finally {
  await browser.close();
  await server.close();
}
if (failures.length) {
  console.error(failures.join("\n"));
  process.exit(1);
}
console.log("pricing: rupees by default, dollars on the switch, yearly and the add-on on the pricing page");
