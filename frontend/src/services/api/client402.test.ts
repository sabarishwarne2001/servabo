/**
 * Final session 1 (3B): a 402 that says "your plan does not include this" must never raise the global "you are out of quota" banner.
 *
 * The server sends three 402 refusals about what the organization pays for (`ADDON_REQUIRED`, `CAPABILITY_REQUIRED`,
 * `BILLING_READ_ONLY`) and one about the trial (`TRIAL_ENDED`). Each carries its own message for the page that asked. A plan lock that
 * lands in the quota banner tells a customer who simply needs a higher plan that they have run out of something.
 */
import type { AxiosAdapter, InternalAxiosRequestConfig } from "axios";
import { afterEach, describe, expect, it } from "vitest";

import apiClient from "@/services/api/client";
import { useSessionGuardStore } from "@/store/useSessionGuardStore";

const refuse = (code: string): AxiosAdapter => (config: InternalAxiosRequestConfig) =>
  Promise.reject(
    Object.assign(new Error("Request failed with status code 402"), {
      isAxiosError: true,
      config,
      response: {
        status: 402,
        statusText: "Payment Required",
        headers: {},
        config,
        data: { code, message: `refused: ${code}`, details: {} },
      },
    }),
  );

const ask = async (code: string): Promise<void> => {
  const previous = apiClient.defaults.adapter;
  apiClient.defaults.adapter = refuse(code);
  try {
    await apiClient.get("/organizations/x/anything");
  } catch {
    /* the refusal is the point */
  } finally {
    if (previous === undefined) {
      delete (apiClient.defaults as { adapter?: unknown }).adapter;
    } else {
      apiClient.defaults.adapter = previous;
    }
  }
};

describe("402 refusals about the plan", () => {
  afterEach(() => useSessionGuardStore.getState().clearQuotaRefusal());

  it.each(["ADDON_REQUIRED", "CAPABILITY_REQUIRED", "BILLING_READ_ONLY", "TRIAL_ENDED"])(
    "%s does not raise the quota banner",
    async (code) => {
      await ask(code);
      expect(useSessionGuardStore.getState().quota).toBeNull();
    },
  );

  it("a real quota refusal still does", async () => {
    await ask("QUOTA_EXCEEDED");
    expect(useSessionGuardStore.getState().quota?.code).toBe("QUOTA_EXCEEDED");
  });
});
