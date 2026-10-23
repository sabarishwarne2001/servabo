/**
 * Final session 1 (4A): the web app's error tracking sends the failure and none of the person.
 * Empty DSN: nothing is loaded and nothing is sent. With a DSN: an unhandled error reaches the ingest scrubbed, an expected 4xx does not.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { initMonitoring, isExpected, reportError, scrubEvent, scrubText, scrubUrl } from "@/monitoring";

const LEAKY =
  "failed for priya.sharma@sahyadri.example with Bearer abcdef1234567890abcdef, GSTIN 27AABCS5555K1Z5, PAN AABCS5555K, total ₹12,50,000.00, account 50100234567891, INV-2026-04417";

describe("scrubText", () => {
  it("removes emails, tokens, keys, GSTINs, PANs, amounts, account numbers and document references", () => {
    const out = scrubText(`${LEAKY} key gsk_live_abcdefghijklmnop1234 jwt eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiIxMjM0NTYifQ.c2lnbmF0dXJl irn ${"9f1c".repeat(16)}`);
    for (const secret of ["priya.sharma", "abcdef1234567890", "27AABCS5555K1Z5", "AABCS5555K", "12,50,000", "50100234567891", "INV-2026-04417", "gsk_live", "eyJhbGci", "9f1c9f1c"]) {
      expect(out).not.toContain(secret);
    }
  });
  it("keeps the path of an address and drops its query string and hash", () => {
    expect(scrubUrl("https://app.example.com/acme/main/gst?token=abc&q=priya%40x.com#section")).toBe("https://app.example.com/acme/main/gst");
    expect(scrubUrl("/acme/main/work-items/5d11d699-e466-49c2-99d8-9efdf2cbcce3?email=a@b.co")).toBe("/acme/main/work-items/5d11d699-e466-49c2-99d8-9efdf2cbcce3");
  });
});

describe("scrubEvent", () => {
  it("strips the request, the person, the breadcrumbs and the variables, and scrubs the message", () => {
    const event = scrubEvent({
      request: { url: "https://app.example.com/x?token=abc", headers: { Authorization: "Bearer zzz" }, cookies: "a=b", data: "body" },
      user: { email: "a@b.co" }, breadcrumbs: [{ message: "click" }], extra: { text: "doc" },
      exception: { values: [{ value: LEAKY, stacktrace: { frames: [{ filename: "https://app.example.com/assets/a.js?v=1", vars: { x: 1 } }] } }] },
    });
    expect(JSON.stringify(event)).not.toMatch(/priya|zzz|Authorization|token=abc|a@b\.co|12,50,000/);
    expect(event.request).toEqual({ url: "https://app.example.com/x" });
    expect(event.exception?.values?.[0]?.stacktrace?.frames?.[0]).toEqual({ filename: "https://app.example.com/assets/a.js" });
  });
});

describe("isExpected", () => {
  it("is true for an API refusal (4xx) and false for a server error or a plain error", () => {
    expect(isExpected({ status: 404 })).toBe(true);
    expect(isExpected({ status: 402 })).toBe(true);
    expect(isExpected({ status: 500 })).toBe(false);
    expect(isExpected(new Error("x"))).toBe(false);
  });
});

describe("initMonitoring", () => {
  const envelopes: string[] = [];
  beforeEach(() => {
    envelopes.length = 0;
    vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: { body?: unknown }) => {
      envelopes.push(typeof init?.body === "string" ? init.body : new TextDecoder().decode(init?.body as Uint8Array));
      return new Response("{}", { status: 200 });
    }));
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("with no DSN loads nothing and sends nothing", async () => {
    vi.stubEnv("VITE_SENTRY_DSN", "");
    expect(await initMonitoring()).toBe(false);
    reportError(new Error(LEAKY));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(envelopes).toEqual([]);
    expect(fetch).not.toHaveBeenCalled();
  });

  it("with a DSN sends an error scrubbed, and not an expected refusal", async () => {
    vi.stubEnv("VITE_SENTRY_DSN", "https://publickeyabc@o1.ingest.de.sentry.io/1");
    vi.stubEnv("VITE_SENTRY_ENVIRONMENT", "production");
    expect(await initMonitoring()).toBe(true);
    reportError(Object.assign(new Error(LEAKY), { status: 403 }));
    reportError(new Error(LEAKY));
    const Sentry = await import("@sentry/browser");
    await Sentry.flush(2000);
    const body = envelopes.join("\n");
    expect(body).toContain("Error");
    expect(envelopes.length).toBe(1);
    for (const secret of ["priya.sharma", "27AABCS5555K1Z5", "12,50,000", "50100234567891", "INV-2026-04417"]) {
      expect(body).not.toContain(secret);
    }
  });
});
