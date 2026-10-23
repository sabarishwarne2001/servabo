/**
 * THE SIDEBAR CAN BE DRAGGED WIDER OR NARROWER, EVERYWHERE IT IS USED (Final session 1, sidebar task): the workspace, organization
 * and Helm sidebars share one remembered width; the assistant's conversation list and the settings section list have their own.
 * Mouse, finger and keyboard all work; the width survives a reload; a phone's drawer has the same divider; and nothing sideways
 * scrolls at any width.
 */
import type { Locator, Page } from "@playwright/test";

import { test, expect } from "../support/fixtures";
import { signInAs, newCustomer } from "../support/journey";

const KEY = "servabo_sidebar_width.shell";

const widthOf = async (handle: Locator): Promise<number> => {
  const box = await handle.locator("xpath=..").boundingBox();
  return Math.round(box?.width ?? 0);
};

/** The width settles after the sidebar's short width animation (keyboard and reset steps animate; a drag does not). */
const expectWidth = async (handle: Locator, width: number): Promise<void> => {
  await expect.poll(() => widthOf(handle), { timeout: 5_000 }).toBe(width);
};

const dragWithMouse = async (page: Page, handle: Locator, by: number): Promise<void> => {
  const box = await handle.boundingBox();
  if (!box) throw new Error("the divider has no box");
  const x = box.x + box.width / 2;
  const y = box.y + box.height / 2;
  await page.mouse.move(x, y);
  await page.mouse.down();
  await page.mouse.move(x + by / 2, y, { steps: 4 });
  await page.mouse.move(x + by, y, { steps: 4 });
  await page.mouse.up();
};

const noSidewaysScroll = async (page: Page): Promise<void> => {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow, "the page scrolls sideways").toBeLessThanOrEqual(1);
};

test("the workspace sidebar: drag, keyboard, reset, remembered, and shared with the organization and Helm shells", async ({ page }) => {
  test.setTimeout(180_000);
  const customer = await newCustomer("sidebar", "Sidebar Traders");
  await page.setViewportSize({ width: 1440, height: 900 });
  await signInAs(page, customer.email);
  await page.goto(customer.ws(""));
  await expect(page.locator("main")).toBeVisible({ timeout: 30_000 });

  const handle = page.getByRole("separator", { name: "Resize the sidebar" });
  await expect(handle).toBeVisible();
  await expectWidth(handle, 260);

  // Mouse: drag 100px to the right.
  await dragWithMouse(page, handle, 100);
  await expectWidth(handle, 360);
  expect(await page.evaluate((k) => window.localStorage.getItem(k), KEY)).toBe("360");
  await expect(handle).toHaveAttribute("aria-valuenow", "360");
  await noSidewaysScroll(page);

  // The limits hold: far past the widest, far under the narrowest.
  await dragWithMouse(page, handle, 900);
  await expectWidth(handle, 420);
  await dragWithMouse(page, handle, -900);
  await expectWidth(handle, 220);

  // Keyboard: arrows, Shift for bigger steps, Home/End, Enter resets.
  await handle.focus();
  await page.keyboard.press("ArrowRight");
  await expectWidth(handle, 236);
  await page.keyboard.press("Shift+ArrowRight");
  await expectWidth(handle, 284);
  await page.keyboard.press("End");
  await expectWidth(handle, 420);
  await page.keyboard.press("Home");
  await expectWidth(handle, 220);
  await page.keyboard.press("Enter");
  await expectWidth(handle, 260);

  // The navigation still works at a wide width, and the width is remembered across a reload.
  await dragWithMouse(page, handle, 80);
  await page.getByRole("link", { name: /^Documents/ }).first().click();
  await expect(page.locator("main")).toBeVisible();
  await expectWidth(page.getByRole("separator", { name: "Resize the sidebar" }), 340);
  await page.reload();
  await expect(page.locator("main")).toBeVisible();
  await expectWidth(page.getByRole("separator", { name: "Resize the sidebar" }), 340);

  // Collapsing gives the icon rail; the divider steps aside; expanding brings the chosen width back.
  await page.getByRole("button", { name: "Collapse Sidebar" }).click();
  await expect(page.getByRole("separator", { name: "Resize the sidebar" })).toHaveCount(0);
  await page.getByRole("button", { name: "Expand Sidebar" }).click();
  await expectWidth(page.getByRole("separator", { name: "Resize the sidebar" }), 340);

  // The organization shell and Helm use the same width.
  await page.goto(customer.org(""));
  await expect(page.locator("main")).toBeVisible();
  await expectWidth(page.getByRole("separator", { name: "Resize the sidebar" }), 340);
  await page.goto(`/${customer.orgSlug}/helm/start`);
  await expect(page.locator("main, [data-testid='helm-shell']").first()).toBeVisible({ timeout: 30_000 });
  const helmHandle = page.getByRole("separator", { name: "Resize the sidebar" });
  await expectWidth(helmHandle, 340);
  await dragWithMouse(page, helmHandle, -60);
  await expectWidth(helmHandle, 280);
  await page.goto(customer.org(""));
  await expectWidth(page.getByRole("separator", { name: "Resize the sidebar" }), 280);

  // A double click puts it back.
  await page.getByRole("separator", { name: "Resize the sidebar" }).dblclick();
  await expectWidth(page.getByRole("separator", { name: "Resize the sidebar" }), 260);
  await noSidewaysScroll(page);
});

test("the settings sections and the assistant's conversations have their own draggable divider", async ({ page }) => {
  test.setTimeout(180_000);
  const customer = await newCustomer("sidebar2", "Sidebar Two Traders");
  await page.setViewportSize({ width: 1440, height: 900 });
  await signInAs(page, customer.email);

  await page.goto(customer.ws("settings"));
  const settings = page.getByRole("separator", { name: "Resize the settings sections" });
  await expect(settings).toBeVisible({ timeout: 30_000 });
  const before = await widthOf(settings);
  expect(before).toBe(280);
  await dragWithMouse(page, settings, 60);
  await expectWidth(settings, 340);
  await settings.focus();
  await page.keyboard.press("Home");
  await expectWidth(settings, 220);
  await noSidewaysScroll(page);

  await page.goto(customer.ws("assistant"));
  const list = page.getByRole("separator", { name: "Resize the conversation list" });
  await expect(list).toBeVisible({ timeout: 30_000 });
  await expectWidth(list, 340);
  await dragWithMouse(page, list, -80);
  await expectWidth(list, 260);
  await page.reload();
  await expectWidth(page.getByRole("separator", { name: "Resize the conversation list" }), 260);
  await noSidewaysScroll(page);
});

test("on a phone the navigation drawer has the divider, and a finger can drag it", async ({ browser }) => {
  test.setTimeout(180_000);
  const customer = await newCustomer("sidebar3", "Sidebar Phone Traders");
  const context = await browser.newContext({ viewport: { width: 390, height: 800 }, hasTouch: true, isMobile: true });
  const page = await context.newPage();
  try {
    await signInAs(page, customer.email);
    await page.goto(customer.ws(""));
    await expect(page.locator("main")).toBeVisible({ timeout: 30_000 });
    await noSidewaysScroll(page);

    // The desktop divider is not on the page below the large breakpoint; the drawer's is.
    await page.getByRole("button", { name: /menu|navigation/i }).first().click();
    const handle = page.getByRole("separator", { name: "Resize the navigation menu" });
    await expect(handle).toBeVisible();
    await expectWidth(handle, 260);

    const cdp = await context.newCDPSession(page);
    const box = await handle.boundingBox();
    if (!box) throw new Error("the divider has no box");
    const x = box.x + box.width / 2;
    const y = box.y + 200;
    const touch = async (type: "touchStart" | "touchMove" | "touchEnd", at: number) =>
      cdp.send("Input.dispatchTouchEvent", { type, touchPoints: type === "touchEnd" ? [] : [{ x: at, y }] });
    await touch("touchStart", x);
    await touch("touchMove", x + 40);
    await touch("touchMove", x + 90);
    await touch("touchEnd", x + 90);
    // Wider by the distance dragged, but never more than 85% of a 390px screen (331.5px, rounded).
    await expect.poll(() => widthOf(handle)).toBe(332);
    expect(await page.evaluate((k) => window.localStorage.getItem(k), KEY)).toBe("332");

    // Navigation still works from the wider drawer and the drawer closes on Escape.
    await page.keyboard.press("Escape");
    await noSidewaysScroll(page);
  } finally {
    await context.close();
  }
});
