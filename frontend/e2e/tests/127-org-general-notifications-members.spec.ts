/**
 * ORGANIZATION TABS, PART 1 (Final session 1, organization tabs task): General, Notifications and Members, each with its own
 * customer and real input: what a person can type, what the server keeps, what each role sees, and what is refused.
 * (The page-by-page smoke, role and plan sweeps are specs 01-03; these go deeper into what each tab does.)
 */
import { test, expect, expectHealthyPage } from "../support/fixtures";
import { api } from "../support/api";
import { addMember, newCustomer, signInAs } from "../support/journey";
import { enterpriseCustomer } from "../support/workflow-helpers";

interface Member {
  id: string;
  role: string;
  status: string;
  user: { email: string };
}

const membersOf = async (customer: Awaited<ReturnType<typeof newCustomer>>): Promise<Member[]> => {
  const listed = await api<{ items: Member[] }>(customer.session, "GET", `/organizations/${customer.orgId}/members`);
  expect(listed.status, listed.text).toBe(200);
  return listed.body.items;
};

test.describe("General", () => {
  test("a name is a real name: spaces alone cannot be saved, spaces around are dropped, and the new name shows everywhere", async ({ page }) => {
    test.setTimeout(120_000);
    const customer = await newCustomer("orggeneral", "General Check Ltd");
    await signInAs(page, customer.email);
    await page.goto(customer.org("settings"));
    const name = page.getByRole("textbox", { name: "Organization name" });
    const save = page.getByRole("button", { name: "Save changes" });
    await expect(name).toHaveValue("General Check Ltd", { timeout: 30_000 });
    await expect(save).toBeDisabled();

    await name.fill("");
    await expect(save).toBeDisabled();
    await name.fill("     ");
    await expect(save).toBeDisabled();
    await name.fill("General Check Ltd");
    await expect(save, "an unchanged name is not a change").toBeDisabled();

    await name.fill("  Renamed & <b>Sons</b>  ");
    await expect(save).toBeEnabled();
    await save.click();
    await expect(page.getByText("Organization updated.")).toBeVisible();
    await expect(name).toHaveValue("Renamed & <b>Sons</b>");
    await expect(save).toBeDisabled();

    // The server kept it trimmed, and every place that shows the name shows it as text.
    const stored = await api<{ name: string }>(customer.session, "GET", `/organizations/${customer.orgId}`);
    expect(stored.body.name).toBe("Renamed & <b>Sons</b>");
    await expect(page.getByRole("navigation", { name: "Breadcrumb" })).toContainText("Renamed & <b>Sons</b>");
    await page.reload();
    await expect(name).toHaveValue("Renamed & <b>Sons</b>", { timeout: 30_000 });
    expect(await page.locator("main b").count(), "the name was drawn as markup").toBe(0);

    // A direct API call with a blank name is refused with a reason, and nothing changes.
    const refused = await api(customer.session, "PATCH", `/organizations/${customer.orgId}`, { name: "   " });
    expect(refused.status, refused.text).toBe(422);
    await expectHealthyPage(page);
  });

  test("each role sees what it may do: a member reads, an admin renames but cannot archive, the owner can archive", async ({ page, browser }) => {
    test.setTimeout(240_000);
    const customer = await enterpriseCustomer("orgroles");
    const admin = await addMember(customer, "orgadmin", "ADMIN");
    const member = await addMember(customer, "orgmember", "MEMBER");

    const asMember = await browser.newContext();
    const memberPage = await asMember.newPage();
    try {
      await signInAs(memberPage, member.email);
      await memberPage.goto(customer.org("settings"));
      await expect(memberPage.getByRole("textbox", { name: "Organization name" })).toBeDisabled({ timeout: 30_000 });
      await expect(memberPage.getByText("Your role in this organization is read-only for these settings.")).toBeVisible();
      await expect(memberPage.getByRole("button", { name: "Save changes" })).toHaveCount(0);
      await expect(memberPage.getByRole("button", { name: "Archive organization" })).toHaveCount(0);
    } finally {
      await asMember.close();
    }

    await signInAs(page, admin.email);
    await page.goto(customer.org("settings"));
    const name = page.getByRole("textbox", { name: "Organization name" });
    await expect(name).toBeEnabled({ timeout: 30_000 });
    await expect(page.getByRole("button", { name: "Archive organization" }), "an admin must not see the danger zone").toHaveCount(0);
    await name.fill("Renamed By Admin");
    await page.getByRole("button", { name: "Save changes" }).click();
    await expect(page.getByText("Organization updated.")).toBeVisible();

    // The owner sees the danger zone; the API refuses an admin who calls it anyway.
    const refused = await api(admin.session, "POST", `/organizations/${customer.orgId}/archive`, { confirm_slug: customer.orgSlug });
    expect([403, 404], refused.text).toContain(refused.status);
    await signInAs(page, customer.email);
    await page.goto(customer.org("settings"));
    await expect(page.getByRole("button", { name: "Archive organization" })).toBeVisible({ timeout: 30_000 });
  });

  test("archiving needs the typed identifier, can be cancelled, and then closes the organization", async ({ page }) => {
    test.setTimeout(120_000);
    const customer = await newCustomer("orgarchive", "Archive Check Ltd");
    await signInAs(page, customer.email);
    await page.goto(customer.org("settings"));
    await page.getByRole("button", { name: "Archive organization" }).click();
    const confirm = page.getByRole("button", { name: "Archive organization" }).last();
    await expect(confirm).toBeDisabled();
    await page.getByLabel(/to confirm/).fill("not-the-identifier");
    await expect(confirm).toBeDisabled();
    await page.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByLabel(/to confirm/)).toHaveCount(0);
    const still = await api<{ status: string }>(customer.session, "GET", `/organizations/${customer.orgId}`);
    expect(still.body.status).toBe("ACTIVE");

    await page.getByRole("button", { name: "Archive organization" }).click();
    await page.getByLabel(/to confirm/).fill(` ${customer.orgSlug} `);
    await page.getByRole("button", { name: "Archive organization" }).last().click();
    await expect(page).toHaveURL(/\/workspaces/, { timeout: 30_000 });
    // A closed organization answers "archived" (or refuses with its suspended code); it is never still active.
    const closed = await api<{ status?: string; code?: string }>(customer.session, "GET", `/organizations/${customer.orgId}`);
    expect(closed.body.status === "ARCHIVED" || closed.status === 403, closed.text).toBe(true);
    // Nothing in an archived organization can be changed.
    const rename = await api(customer.session, "PATCH", `/organizations/${customer.orgId}`, { name: "Too late" });
    expect(rename.status, rename.text).toBeGreaterThanOrEqual(400);
  });
});

test.describe("Notifications", () => {
  test("a role change reaches the person it happened to; filters, read state and pages work", async ({ page }) => {
    test.setTimeout(300_000);
    const customer = await enterpriseCustomer("orgnotes");
    const person = await addMember(customer, "orgnotes-person", "MEMBER");
    const target = (await membersOf(customer)).find((m) => m.user.email === person.email)!;

    // 26 changes of role: 26 security notices for that person (one page holds 25).
    for (let round = 0; round < 13; round += 1) {
      for (const role of ["ADMIN", "MEMBER"]) {
        const changed = await api(customer.session, "PATCH", `/organizations/${customer.orgId}/members/${target.id}`, { role });
        expect(changed.status, changed.text).toBe(200);
      }
    }

    await signInAs(page, person.email);
    await page.goto(customer.org("notifications"));
    const list = page.getByRole("list", { name: "Organization notifications" });
    await expect(list.getByRole("listitem")).toHaveCount(25, { timeout: 30_000 });
    await expect(page.getByText("26", { exact: true }).first()).toBeVisible();
    await expect(page.getByText("· 26 unread")).toBeVisible();
    await expect(list.getByRole("listitem").first()).toContainText("Your role in orgnotes Ltd changed");

    // The newest notice is on top; reading it drops the unread count by one and the filter hides it.
    await list.getByRole("button", { name: "Mark as read" }).first().click();
    await expect(page.getByText("· 25 unread")).toBeVisible();
    await page.getByRole("checkbox", { name: "Unread only" }).check();
    await expect(page.getByText("25", { exact: true }).first()).toBeVisible();
    await expect(page.getByRole("button", { name: "Mark as unread" })).toHaveCount(0);
    await page.getByRole("checkbox", { name: "Unread only" }).uncheck();
    await page.getByRole("button", { name: "Mark as unread" }).first().click();
    await expect(page.getByText("· 26 unread")).toBeVisible();

    // Categories: security has them all, documents has none.
    await page.getByRole("combobox", { name: "Category" }).selectOption("DOCUMENT");
    await expect(page.getByText("Nothing matches these filters")).toBeVisible();
    await page.getByRole("combobox", { name: "Category" }).selectOption("SECURITY");
    await expect(list.getByRole("listitem")).toHaveCount(25);
    await page.getByRole("combobox", { name: "Category" }).selectOption("ALL");

    // Pages: 1-25 of 26, then the last one, then back.
    await expect(page.getByText("1–25 of 26")).toBeVisible();
    await page.getByRole("button", { name: "Next" }).click();
    await expect(page.getByText("26–26 of 26")).toBeVisible();
    await expect(list.getByRole("listitem")).toHaveCount(1);
    await expect(page.getByRole("button", { name: "Next" })).toBeDisabled();
    await page.getByRole("button", { name: "Previous" }).click();
    await expect(page.getByText("1–25 of 26")).toBeVisible();

    // The owner, who made the changes, has no such notices: a feed is one person's own.
    await signInAs(page, customer.email);
    await page.goto(customer.org("notifications"));
    await expect(page.getByRole("heading", { name: "Organization notifications" })).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/^Your role in .* changed$/)).toHaveCount(0);
    await expectHealthyPage(page);
  });
});

test.describe("Members", () => {
  test("seats, roles and removal: the list, the role menu a person is offered, and what removing does", async ({ page }) => {
    test.setTimeout(300_000);
    const customer = await enterpriseCustomer("orgmembers");
    const admin = await addMember(customer, "mem-admin", "ADMIN");
    const member = await addMember(customer, "mem-member", "MEMBER");

    await signInAs(page, customer.email);
    await page.goto(customer.org("members"));
    await expect(page.getByText("3", { exact: true }).first()).toBeVisible({ timeout: 30_000 });
    await expect(page.getByText(/· \d+ seats in use/)).toBeVisible();

    // The owner may set any role below owner; the owner's own row has no menu (nobody changes their own role).
    const roleOfMember = page.getByRole("combobox", { name: `Role for ${member.email}` });
    await expect(roleOfMember).toBeVisible();
    expect(await roleOfMember.locator("option").allTextContents()).not.toContain("Owner");
    await expect(page.getByRole("combobox", { name: `Role for ${customer.email}` })).toHaveCount(0);
    await expect(page.getByRole("button", { name: `Remove ${customer.email}` }), "the owner cannot remove themselves").toHaveCount(0);

    await roleOfMember.selectOption("ADMIN");
    await expect.poll(async () => (await membersOf(customer)).find((m) => m.user.email === member.email)?.role).toBe("ADMIN");
    await roleOfMember.selectOption("MEMBER");
    await expect.poll(async () => (await membersOf(customer)).find((m) => m.user.email === member.email)?.role).toBe("MEMBER");

    // Removal asks first; cancelling keeps the person; confirming removes them and frees the seat.
    const before = await api<{ seats_consumed: number }>(customer.session, "GET", `/organizations/${customer.orgId}/members`);
    await page.getByRole("button", { name: `Remove ${member.email}` }).click();
    await page.getByRole("button", { name: "Cancel" }).click();
    await expect(page.getByRole("combobox", { name: `Role for ${member.email}` })).toBeVisible();
    await page.getByRole("button", { name: `Remove ${member.email}` }).click();
    await page.getByRole("button", { name: "Confirm removal" }).click();
    await expect(page.getByRole("combobox", { name: `Role for ${member.email}` })).toHaveCount(0, { timeout: 15_000 });
    const after = await api<{ seats_consumed: number }>(customer.session, "GET", `/organizations/${customer.orgId}/members`);
    expect(after.body.seats_consumed).toBe(before.body.seats_consumed - 1);

    // "Show removed members" brings them back as former members, kept for attribution.
    await page.getByRole("checkbox", { name: "Show removed members" }).check();
    const row = page.getByRole("listitem").filter({ hasText: member.email });
    await expect(row).toContainText("Former member");
    await expect(row).toContainText("retained for attribution");
    await expect(row.getByRole("combobox")).toHaveCount(0);

    // The removed person is out at once; the admin sees the directory but not the removal switch for the owner.
    const gone = await api(member.session, "GET", `/organizations/${customer.orgId}`);
    expect([401, 403, 404]).toContain(gone.status);
    await signInAs(page, admin.email);
    await page.goto(customer.org("members"));
    await expect(page.getByRole("button", { name: `Remove ${customer.email}` })).toHaveCount(0, { timeout: 30_000 });
    await expect(page.getByRole("region", { name: "Invite people" })).toBeVisible();
  });

  test("a plain member sees who is in the organization, with no controls", async ({ page }) => {
    test.setTimeout(180_000);
    const customer = await newCustomer("orgmemberview", "Member View Ltd"); // the Free plan's two seats: owner and one member
    const member = await addMember(customer, "view-member", "MEMBER");
    await signInAs(page, member.email);
    await page.goto(customer.org("members"));
    await expect(page.getByText(customer.email)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByRole("combobox")).toHaveCount(0);
    await expect(page.getByRole("button", { name: /^Remove / })).toHaveCount(0);
    await expect(page.getByRole("region", { name: "Invite people" })).toHaveCount(0);
    await expect(page.getByRole("checkbox", { name: "Show removed members" })).toHaveCount(0);
    await expect(page.getByText(/requires an owner or administrator/)).toBeVisible();
    await expectHealthyPage(page);
  });

  test("an invitation holds a seat: invite, see it pending, and revoke it to free the seat", async ({ page }) => {
    test.setTimeout(180_000);
    const customer = await enterpriseCustomer("orginvite");
    await signInAs(page, customer.email);
    await page.goto(customer.org("members"));
    const seatsBefore = (await api<{ seats_consumed: number }>(customer.session, "GET", `/organizations/${customer.orgId}/members`)).body.seats_consumed;
    const invitee = `invited-${Date.now()}@e2e.example.com`;
    const panel = page.getByRole("region", { name: "Invite people" });
    // A malformed address never leaves the browser.
    await panel.getByRole("textbox", { name: "Email address" }).fill("not-an-email");
    await expect(panel.getByRole("button", { name: "Send invitation" })).toBeDisabled();
    await expect(panel.getByRole("list", { name: "Pending invitations" }).getByRole("listitem")).toHaveCount(0);
    await panel.getByRole("textbox", { name: "Email address" }).fill(invitee);
    await panel.getByRole("button", { name: "Send invitation" }).click();
    const pending = panel.getByRole("list", { name: "Pending invitations" }).getByRole("listitem").filter({ hasText: invitee });
    await expect(pending).toBeVisible({ timeout: 15_000 });
    const held = (await api<{ seats_consumed: number }>(customer.session, "GET", `/organizations/${customer.orgId}/members`)).body.seats_consumed;
    expect(held).toBe(seatsBefore + 1);
    // The same address twice is refused, not duplicated.
    await panel.getByRole("textbox", { name: "Email address" }).fill(invitee);
    await panel.getByRole("button", { name: "Send invitation" }).click();
    await expect(panel.getByRole("list", { name: "Pending invitations" }).getByRole("listitem").filter({ hasText: invitee })).toHaveCount(1);
    await pending.getByRole("button", { name: `Revoke the invitation to ${invitee}` }).click();
    await expect(pending).toHaveCount(0, { timeout: 15_000 });
    const freed = (await api<{ seats_consumed: number }>(customer.session, "GET", `/organizations/${customer.orgId}/members`)).body.seats_consumed;
    expect(freed).toBe(seatsBefore);
    await expectHealthyPage(page);
  });
});
