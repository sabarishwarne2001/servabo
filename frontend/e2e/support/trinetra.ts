/**
 * Support for the TRINETRA browser specs (Final session 2T).
 *
 * Each spec works in an organization of its own (`liveCustomer`), put on a paid plan and enrolled in the pilot by the platform
 * operator through the real console API, the way a launch would do it. Nothing here touches the seeded organizations, so
 * spec 135 (which expects the shipped, not-enrolled state) is never affected by the specs that go live.
 * Everything typed in is synthetic: the PAN, TAN, names and amounts belong to no one.
 */
import fs from "node:fs";
import path from "node:path";

import { expect } from "@playwright/test";

import { api, loginAs, type ApiSession } from "./api";
import { BACKEND_DIR } from "./env";
import { addMember, newCustomer, standIn, type Customer } from "./journey";
import { buildPdf } from "./sample-docs";

export const PAN = "ABCDE1234F";
export const TAN = "ABCD12345E";
export const ENTITY = "Synthetic Trinetra Services Ltd";
export const DEDUCTOR = "Synthetic Deductor Ltd";
const FIXTURES = path.join(BACKEND_DIR, "tests", "fixtures", "trinetra");

/** A synthetic statement file from the backend's own fixtures (the same files its tests read). */
export function fixture(name: string): { name: string; mimeType: string; buffer: Buffer } {
  const mimeType = name.endsWith(".csv") ? "text/csv" : "text/plain";
  return { name, mimeType, buffer: fs.readFileSync(path.join(FIXTURES, name)) };
}

export const TEMPLATE_HEAD =
  "Deductor TAN,Tax credited (INR),Row reference,Section or table item (as printed),Transaction date,Booking status,Tax year label (as printed)\n";

/** A statement in the Servabo template with the given rows (amounts in rupees). */
export function templateFile(rows: string[]): { name: string; mimeType: string; buffer: Buffer } {
  return { name: "my-statement.csv", mimeType: "text/csv", buffer: Buffer.from(TEMPLATE_HEAD + rows.join("\n") + "\n") };
}

let operator: ApiSession | null = null;

async function platformOperator(): Promise<ApiSession> {
  operator ??= await loginAs("P.superadmin");
  return operator;
}

/** The platform operator enrols an organization in the pilot (what the launch checklist does for a customer). */
export async function enrol(orgId: string, reason = "Browser specs: synthetic pilot enrolment."): Promise<void> {
  const done = await api(await platformOperator(), "PUT", `/admin/trinetra/pilot/${orgId}`, { reason });
  expect(done.status, done.text).toBe(200);
}

export async function withdraw(orgId: string, reason = "Browser specs: synthetic pilot withdrawal."): Promise<void> {
  const done = await api(await platformOperator(), "POST", `/admin/trinetra/pilot/${orgId}/withdraw`, { reason });
  expect(done.status, done.text).toBe(200);
}

export interface LiveCustomer extends Customer {
  admin?: { email: string; session: ApiSession };
  viewer?: { email: string; session: ApiSession };
}

/** A new organization on `plan`, enrolled in the pilot, with a workspace administrator and a viewer when asked for. */
export async function liveCustomer(
  label: string,
  plan: "business" | "enterprise",
  options: { people?: boolean; enrolled?: boolean } = {},
): Promise<LiveCustomer> {
  const customer: LiveCustomer = await newCustomer(label, `${ENTITY.split(" ")[0]} ${label}`);
  standIn("subscribe", customer.orgSlug, "--plan", plan, "--seats", "4");
  if (options.enrolled !== false) await enrol(customer.orgId);
  if (options.people) {
    customer.admin = await addMember(customer, `${label}-admin`, "MEMBER", "ADMIN");
    customer.viewer = await addMember(customer, `${label}-viewer`, "MEMBER", "VIEWER");
  }
  return customer;
}

const invoiceLines = (reference: string) => [
  "INVOICE",
  `Vendor: ${ENTITY}`,
  `Vendor PAN: ${PAN}`,
  `Bill To: ${DEDUCTOR}`,
  `Invoice Number: ${reference}`,
  "Invoice Date: 2026-03-01",
  "Currency: INR",
  "Total Amount Due: INR 118000.00",
];

/** Upload one invoice through the real pipeline and wait until it has been read (the worker's job). Returns the document id. */
export async function bookInvoice(customer: Customer, reference: string): Promise<string> {
  const form = new FormData();
  form.append("file", new Blob([new Uint8Array(buildPdf([invoiceLines(reference)]))], { type: "application/pdf" }), `${reference}.pdf`);
  const sent = await api<{ id: string }>(customer.session, "POST", `/workspaces/${customer.wsId}/work-items`, form);
  expect(sent.status, sent.text).toBe(201);
  await expect
    .poll(
      async () => {
        const r = await api<{ status: string; extracted_entities: Record<string, unknown> | null }>(
          customer.session, "GET", `/workspaces/${customer.wsId}/work-items/${sent.body.id}`);
        return r.body.status === "COMPLETED" ? r.body.extracted_entities?.currency : r.body.status;
      },
      { timeout: 180_000, intervals: [2000, 4000] },
    )
    .toBe("INR");
  return sent.body.id;
}

const trinetra = (customer: Customer, sub = "") => `/workspaces/${customer.wsId}/trinetra${sub}`;

export async function createProfile(customer: Customer, session: ApiSession = customer.session): Promise<string> {
  const made = await api<{ id: string }>(session, "POST", trinetra(customer, "/profiles"), { name: ENTITY, pan: PAN });
  expect(made.status, made.text).toBe(200);
  return made.body.id;
}

/** A case with a supported expectation of ₹2,000 against the invoice (what the reviewer typed, with its source). */
export async function createCase(customer: Customer, profileId: string, workItemId: string, reference: string): Promise<{ id: string; revision: number }> {
  const made = await api<{ id: string; revision: number }>(customer.session, "POST", trinetra(customer, "/credits"), {
    profile_id: profileId,
    work_item_id: workItemId,
    year: 2025,
    counterparty: DEDUCTOR,
    reference,
    tan: TAN,
    amount: "2000",
    source_confirmation: "Reviewed explicitly sourced withholding against the invoice.",
  });
  expect(made.status, made.text).toBe(200);
  return made.body;
}

/** Import a statement through the API (the screens that do it are covered by their own spec). */
export async function importStatement(customer: Customer, profileId: string, file: { name: string; mimeType: string; buffer: Buffer }): Promise<string> {
  const form = new FormData();
  form.append("profile_id", profileId);
  form.append("year", "2025");
  form.append("pan", PAN);
  form.append("confirmed", "true");
  const { createHash } = await import("node:crypto");
  form.append("expected_sha256", createHash("sha256").update(file.buffer).digest("hex"));
  form.append("file", new Blob([new Uint8Array(file.buffer)], { type: file.mimeType }), file.name);
  const made = await api<{ id: string }>(customer.session, "POST", trinetra(customer, "/statement-files"), form);
  expect(made.status, made.text).toBe(200);
  return made.body.id;
}
