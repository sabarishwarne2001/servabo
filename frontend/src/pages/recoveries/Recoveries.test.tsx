/**
 * Final session 2A (N-191): the Recoveries page shows Found, Being fixed and Verified with "Recovered, verified" as its
 * own figure (never added to what was found), a preview with the upgrade moment on a plan without it, and asks for a
 * reason of ten characters before closing an issue as not money.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { RecoveriesView, RecoveryIssue } from "@/services/api/recoveries";

import { Recoveries } from "./Recoveries";

const ANSWER: { current: RecoveriesView } = { current: {} as RecoveriesView };
const PROMPTED: string[] = [];

vi.mock("@/hooks/useActiveWorkspace", () => ({
  useActiveWorkspace: () => ({ workspaceId: "ws-1", organizationId: "org-1", role: "CONTRIBUTOR" }),
}));
vi.mock("@/hooks/useTenant", () => ({
  useTenant: () => ({
    state: { status: "ready", organization: { organization_slug: "acme" }, workspace: { slug: "books" }, organizationRole: "OWNER" },
  }),
}));
vi.mock("@/hooks/useUpgradePrompt", () => ({
  useUpgradePrompt: () => ({ isLocked: () => true, prompt: (capability: string) => PROMPTED.push(capability), dialog: null }),
}));
vi.mock("@/services/api/workspaces", () => ({
  listWorkspaceMembers: async () => ({ items: [{ id: "m1", status: "ACTIVE", user: { id: "u1", email: "asha@acme.in" } }] }),
}));
vi.mock("@/services/api/recoveries", () => ({
  MIN_REASON: 10,
  listRecoveries: async () => ANSWER.current,
  getRecovery: async (_ws: string, id: string) => ANSWER.current.items.find((i) => i.id === id),
  checkRecoveries: async () => ({ found: 0, verified: 0, not_money: 0, closed: 0, reopened: 0 }),
  closeRecoveryNotMoney: vi.fn(),
  reopenRecovery: vi.fn(),
  setRecoveryDueDate: vi.fn(),
  setRecoveryOwner: vi.fn(),
}));

const issue = (id: string, state: RecoveryIssue["state"], title: string): RecoveryIssue => ({
  id, kind: "GST_CREDIT", kind_label: "GST credit waiting on a supplier", state, title, work_item_id: null, document: null,
  currency: "INR", exposure_micros: 180_000_000, found_exposure_micros: 180_000_000, due_date: "2027-11-30",
  due_basis: "Section 16(4) time limit", due_set_by_person: false, owner_user_id: null, owner_email: null,
  close_reason: state === "VERIFIED" ? "The supplier reported it in the GSTR-2B for 2026-11." : null,
  first_found_at: "2026-10-01T00:00:00Z", verified_at: null, closed_at: null, version: 0, details: {}, evidence: {},
  next_actions: [{ key: "gst", label: "Remind the supplier on the GST page", scope: "workspace", path: "gst" }], outcomes: [],
});

const summary = (included: boolean): RecoveriesView["summary"] => ({
  counts: { FOUND: 1, BEING_FIXED: 0, VERIFIED: 1, NOT_MONEY: 0, CLOSED: 0 },
  found: [{ currency: "INR", amount_micros: 180_000_000 }],
  needs_owner: { count: 1, amounts: [{ currency: "INR", amount_micros: 180_000_000 }] },
  recovered_verified: included ? [{ currency: "INR", amount_micros: 540_000_000 }] : [],
  recovered_count: included ? 1 : 0,
});

const show = (): void => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Recoveries />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

afterEach(cleanup);

describe("Recoveries", () => {
  it("shows the three columns and keeps recovered apart from found", async () => {
    ANSWER.current = {
      included: true, kind_labels: {}, summary: summary(true),
      items: [issue("a", "FOUND", "GST credit waiting on Sahyadri for invoice W-1"), issue("b", "VERIFIED", "GST credit waiting on Nilgiri")],
    };
    show();
    expect(await screen.findByTestId("recoveries-board")).toBeTruthy();
    expect(screen.getByTestId("recoveries-column-FOUND").textContent).toContain("Sahyadri");
    expect(screen.getByTestId("recoveries-column-VERIFIED").textContent).toContain("Nilgiri");
    expect(screen.getByTestId("recoveries-found").textContent).toContain("180");
    expect(screen.getByTestId("recoveries-recovered").textContent).toContain("540");
    expect(screen.getByText("Found and recovered are separate figures: they are never added together.")).toBeTruthy();
  });

  it("asks for a reason of ten characters before closing as not money", async () => {
    ANSWER.current = { included: true, kind_labels: {}, summary: summary(true), items: [issue("a", "FOUND", "Waiting on Sahyadri")] };
    show();
    fireEvent.click(await screen.findByText("Waiting on Sahyadri"));
    const close = (await screen.findByTestId("recovery-not-money")) as HTMLButtonElement;
    expect(close.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Close as not money"), { target: { value: "too short" } });
    expect(close.disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Close as not money"), { target: { value: "Booked twice by mistake" } });
    expect(close.disabled).toBe(false);
    expect(screen.getByText("Remind the supplier on the GST page").closest("a")?.getAttribute("href")).toBe("/acme/books/gst");
  });

  it("shows a preview with the upgrade moment on a plan without Recoveries", async () => {
    ANSWER.current = { included: false, kind_labels: {}, summary: summary(false), items: [] };
    show();
    expect(await screen.findByTestId("recoveries-preview-lock")).toBeTruthy();
    expect(screen.queryByTestId("recoveries-board")).toBeNull();
    expect(screen.getByTestId("recoveries-found").textContent).toContain("180");
    fireEvent.click(screen.getByText("See Business"));
    expect(PROMPTED).toEqual(["capability.recoveries"]);
  });
});
