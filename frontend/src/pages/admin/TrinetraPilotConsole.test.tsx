/**
 * The TRINETRA pilot console: a platform administrator sees the server's mode and every enrolled organization, enrols one by
 * name with a reason, and withdraws one with a reason. Before this page enrolment was a command line or a raw API call.
 */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

const STATE = {
  mode: "pilot",
  items: [] as { organization_id: string; name: string; slug?: string; entitled?: boolean; reason: string; enrolled_by: string | null; enrolled_at: string }[],
};
const calls: { enrol: [string, string][]; withdraw: [string, string][] } = { enrol: [], withdraw: [] };

vi.mock("@/services/api/trinetraPilot", () => ({
  trinetraPilotKeys: { all: () => ["trinetra-pilot"], organizations: (q: string) => ["trinetra-pilot", "orgs", q] },
  getTrinetraPilot: async () => ({ mode: STATE.mode, items: STATE.items }),
  searchOrganizations: async () => [
    { id: "org-1", name: "Acme Traders", slug: "acme", status: "ACTIVE", tier_key: "business", has_active_contract: false },
    { id: "org-2", name: "Beta Starter", slug: "beta", status: "ACTIVE", tier_key: "starter", has_active_contract: false },
  ],
  enrolOrganization: async (id: string, reason: string) => {
    calls.enrol.push([id, reason]);
    STATE.items = [{ organization_id: id, name: "Acme Traders", slug: "acme", entitled: false, reason, enrolled_by: null, enrolled_at: "2026-10-30T03:00:00Z" }];
    return STATE.items[0];
  },
  withdrawOrganization: async (id: string, reason: string) => {
    calls.withdraw.push([id, reason]);
    STATE.items = [];
    return { organization_id: id, withdrawn: true };
  },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import TrinetraPilotConsole from "./TrinetraPilotConsole";

const show = (url = "/admin/trinetra"): void => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <TrinetraPilotConsole />
      </MemoryRouter>
    </QueryClientProvider>,
  );
};

afterEach(() => {
  cleanup();
  STATE.items = [];
  STATE.mode = "pilot";
  calls.enrol = [];
  calls.withdraw = [];
});

describe("TrinetraPilotConsole", () => {
  it("shows the mode, enrols a chosen organization with a reason, then withdraws it with a reason", async () => {
    show();
    expect((await screen.findByTestId("trinetra-pilot-mode")).textContent).toContain("pilot");
    expect(screen.getByText("No organization is enrolled.")).toBeTruthy();

    const enrol = screen.getByRole("button", { name: "Enrol in the pilot" });
    expect((enrol as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(await screen.findByLabelText("Organization"), { target: { value: "org-1" } });
    fireEvent.change(screen.getByLabelText("Reason for enrolling"), { target: { value: "short" } });
    expect((enrol as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Reason for enrolling"), { target: { value: "Owner's own pilot, CA has read it" } });
    expect((enrol as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(enrol);
    await waitFor(() => expect(calls.enrol).toEqual([["org-1", "Owner's own pilot, CA has read it"]]));

    const row = await screen.findByTestId("trinetra-pilot-row");
    expect((row).textContent).toContain("Acme Traders");
    expect((row).textContent).toContain("acme");
    expect((row).textContent).toContain("Its plan has no TRINETRA");
    fireEvent.click(screen.getByRole("button", { name: "Withdraw Acme Traders" }));
    const confirm = screen.getByRole("button", { name: "Confirm withdrawal" });
    expect((confirm as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Reason for withdrawing"), { target: { value: "Pilot over; customer asked" } });
    fireEvent.click(confirm);
    await waitFor(() => expect(calls.withdraw).toEqual([["org-1", "Pilot over; customer asked"]]));
  });

  it("preselects the organization the TRINETRA page linked from", async () => {
    show("/admin/trinetra?organization=org-2");
    await waitFor(() => expect((screen.getByLabelText("Organization") as HTMLSelectElement).value).toBe("org-2"));
  });

  it("warns that enrolment changes nothing outside pilot mode", async () => {
    STATE.mode = "off";
    show();
    expect((await screen.findByTestId("trinetra-pilot-mode-note")).textContent).toContain("TRINETRA_MODE");
  });
});
