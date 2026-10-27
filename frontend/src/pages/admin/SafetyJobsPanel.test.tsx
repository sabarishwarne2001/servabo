/**
 * Final session 2A (Phase 2): the safety-jobs panel turns red and names the late jobs; when every job reported in
 * time it says so and is not red.
 */
import { cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SafetyJobStatus, SafetyJobsResponse } from "@/types/platformJobs";

import { SafetyJobsPanel } from "./SafetyJobsPanel";

const ANSWER: { current: SafetyJobsResponse } = { current: { jobs: [], degraded: false } };
vi.mock("@/services/api/platformJobs", () => ({
  platformJobKeys: { safety: () => ["platform-jobs", "safety"] },
  getSafetyJobs: async () => ANSWER.current,
}));

const job = (name: string, label: string, state: SafetyJobStatus["state"]): SafetyJobStatus => ({
  name, label, state, schedule: "daily", deadline_hours: 26, last_success_at: state === "OK" ? "2026-10-26T03:00:00Z" : null,
  last_failure_at: null, last_started_at: null, last_outcome: state === "OK" ? "SUCCEEDED" : null, last_detail: null,
  run: `servabo-sweep ${name}`,
});

const show = (): void => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}><SafetyJobsPanel /></QueryClientProvider>);
};

afterEach(cleanup);

describe("SafetyJobsPanel", () => {
  it("is red and names every late job, with the command to run it", async () => {
    ANSWER.current = {
      degraded: true,
      jobs: [job("compliance", "Retention and erasure", "STALE"), job("backup", "Database backup", "NEVER_RAN"), job("uptime", "Uptime", "OK")],
    };
    show();
    const alert = await screen.findByTestId("safety-jobs-alert");
    expect(alert.textContent).toContain("2 jobs are late: Retention and erasure, Database backup");
    expect(screen.getByTestId("safety-jobs").getAttribute("data-degraded")).toBe("true");
    expect(screen.getByText("Never reported")).toBeTruthy();
    expect(screen.getByText("servabo-sweep compliance")).toBeTruthy();
  });

  it("says every job is on time when none is late", async () => {
    ANSWER.current = { degraded: false, jobs: [job("uptime", "Uptime", "OK"), job("pitr-drill", "PITR drill", "UNWATCHED")] };
    show();
    expect(await screen.findByText("Every watched job has reported in time.")).toBeTruthy();
    expect(screen.queryByTestId("safety-jobs-alert")).toBeNull();
    expect(screen.getByText("Switched off here")).toBeTruthy();
  });
});
