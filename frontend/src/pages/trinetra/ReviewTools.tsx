import { Link } from "react-router-dom";
import { useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useTenant } from "@/hooks/useTenant";
import { workItemDetailsPath } from "@/routes/tenantPaths";
import { BUTTON_SECONDARY, INPUT, SELECT } from "@/components/ui/primitives";
import { reconfirmCredit, updateCreditReview, type CaseDetail } from "@/services/api/trinetra";
import { errorMessage } from "@/services/api/errors";
import SourcePicker from "./SourcePicker";
import { rupees } from "./format";

export default function ReviewTools({
  workspaceId,
  data,
  canDecide,
}: {
  workspaceId: string;
  data: CaseDetail;
  canDecide: boolean;
}) {
  const { state } = useTenant();
  const cache = useQueryClient();
  const [evidence, setEvidence] = useState(() =>
    (data.review?.evidence ?? []).map((e) => ({
      work_item_id: e.work_item_id,
      kind: e.kind,
      amount:
        e.amount_micros === null || e.amount_micros === undefined
          ? ""
          : `${BigInt(e.amount_micros) / 1000000n}.${((BigInt(e.amount_micros) % 1000000n) / 10000n).toString().padStart(2, "0")}`,
    })),
  );
  const [document, setDocument] = useState("");
  const save = useMutation({
    mutationFn: async (form: FormData) => {
      const reason = String(form.get("reason") ?? "");
      if (form.get("task") === "expectation") {
        return reconfirmCredit(workspaceId, data.id, {
          revision: data.revision,
          amount: String(form.get("amount")),
          reason,
          seller_name_confirmed: form.get("sellerName") === "on",
        });
      }
      return updateCreditReview(workspaceId, data.id, {
        revision: data.revision,
        assign_to_me: form.get("claim") === "on",
        priority: String(form.get("priority")),
        root_cause: String(form.get("cause") ?? ""),
        due_on: form.get("due") || null,
        reason,
        confirm_receivable: form.get("confirmReceivable") === "on",
        ...(form.get("clearBasis") === "on" ? { clear_basis: true } : {}),
        ...(form.get("basisAmount") && form.get("basisDoc")
          ? {
              basis: {
                amount: String(form.get("basisAmount")),
                source: String(form.get("basisSource")),
                evidence_work_item_id: String(form.get("basisDoc")),
              },
            }
          : {}),
        evidence: [
          ...evidence,
          ...(document
            ? [
                {
                  work_item_id: document,
                  kind: String(form.get("kind")),
                  amount: String(form.get("evidenceAmount") ?? ""),
                },
              ]
            : []),
        ].map((e) => ({ ...e, amount: e.amount || null })),
      });
    },
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["trinetra", workspaceId] });
    },
  });
  const source = (id: string | undefined, label: string) =>
    id && state.status === "ready" ? (
      <Link
        className="text-primary underline underline-offset-4"
        to={workItemDetailsPath(state.organization.organization_slug, state.workspace.slug, id)}
      >
        {label}
      </Link>
    ) : (
      <span className="text-muted-foreground">{label}: unavailable</span>
    );
  return (
    <div className="space-y-4 text-sm">
      <h3 className="font-semibold">Source evidence</h3>
      <p>{source(data.work_item_id, "Open invoice and its review discussion")}</p>
      <p>{source(data.statement_work_item_id, "Open active statement source")}</p>
      <p className="text-xs text-muted-foreground">
        Printed invoice fields (unapproved): {rupees(data.printed_evidence.amount_micros)} ·{" "}
        {data.printed_evidence.deductor_tan_masked ?? "TAN unavailable"} ·{" "}
        {data.printed_evidence.section_label ?? "Section unavailable"}. {data.printed_evidence.note}
      </p>
      {!data.source_current && (
        <p role="alert" className="text-destructive">
          The source changed. Reconfirm the supported expectation; previous allocations will be
          cleared.
        </p>
      )}
      <ul className="space-y-2">
        {data.bank_evidence.map((bank) => (
          <li key={bank.id}>
            Helm matched receipt · {bank.on} · {rupees(bank.amount_micros)}
          </li>
        ))}
      </ul>
      {!data.bank_evidence.length && (
        <p className="text-muted-foreground">
          No linked bank receipt is available under your Helm permissions. A cash shortfall is not
          evidence of TDS.
        </p>
      )}
      <section className="rounded border border-border p-3">
        <h3 className="font-medium">Receivable evidence projection</h3>
        <p className="mt-2">
          Cash received: {rupees(data.cash_projection.cash_received_micros)} · Reviewed withholding:{" "}
          {rupees(data.cash_projection.reviewed_withholding_micros)}
        </p>
        <p className="mt-2">
          Unexplained balance: {rupees(data.cash_projection.unexplained_micros)}
        </p>
        {data.cash_projection.status === "CONFLICT" && (
          <p role="alert">Cash and withholding exceed the invoice. Review for double counting.</p>
        )}
        <p className="mt-2 text-xs text-muted-foreground">
          {data.cash_projection.note} Unknown inputs remain unknown.
        </p>
      </section>
      <dl className="space-y-1">
        <div className="flex gap-2">
          <dt>Owner</dt>
          <dd>{data.review?.owner_id ? "Assigned reviewer" : "Unassigned"}</dd>
        </div>
        <div className="flex gap-2">
          <dt>Priority</dt>
          <dd>{data.review?.priority ?? "NORMAL"}</dd>
        </div>
        <div className="flex gap-2">
          <dt>Root cause</dt>
          <dd>{data.review?.root_cause || "Under investigation"}</dd>
        </div>
      </dl>
      {data.review?.evidence?.map((item) => (
        <p key={`${item.work_item_id}-${item.kind}`}>
          {source(item.work_item_id, item.kind.toLowerCase().replaceAll("_", " "))}
          {!item.current && " · source changed or removed"}
        </p>
      ))}
      {canDecide && (
        <>
          <details>
            <summary className="cursor-pointer font-medium">
              Correct or reconfirm expectation
            </summary>
            <form
              className="mt-3 space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                save.mutate(new FormData(e.currentTarget));
              }}
            >
              <input type="hidden" name="task" value="expectation" />
              <p className="text-xs text-muted-foreground">
                This creates a new review revision and removes current allocations. Reallocate only
                after checking the corrected source.
              </p>
              <label className="block">
                Supported deduction in INR
                <input
                  className={`${INPUT} mt-1`}
                  name="amount"
                  required
                  inputMode="decimal"
                  pattern="[0-9]+(\.[0-9]{1,2})?"
                />
              </label>
              <label className="flex items-start gap-2">
                <input type="checkbox" name="sellerName" />
                The seller's name on the invoice is a different spelling of this legal entity, and I
                checked it is the same.
              </label>
              <label className="block">
                Reconfirmation reason
                <textarea
                  className={`${INPUT} mt-1`}
                  name="reason"
                  required
                  minLength={10}
                  maxLength={1000}
                />
              </label>
              <button disabled={save.isPending} className={BUTTON_SECONDARY}>
                Reconfirm expectation
              </button>
            </form>
          </details>
          <details>
            <summary className="cursor-pointer font-medium">
              Ownership and supporting evidence
            </summary>
            <form
              className="mt-3 space-y-3"
              onSubmit={(e) => {
                e.preventDefault();
                save.mutate(new FormData(e.currentTarget));
              }}
            >
              <input type="hidden" name="task" value="review" />
              <label className="flex gap-2">
                <input type="checkbox" name="claim" />
                Assign this case to me
              </label>
              <label className="block">
                Priority
                <select
                  name="priority"
                  className={`${SELECT} mt-1`}
                  defaultValue={data.review?.priority ?? "NORMAL"}
                >
                  {["NORMAL", "HIGH", "URGENT"].map((p) => (
                    <option key={p}>{p}</option>
                  ))}
                </select>
              </label>
              <label className="block">
                Follow-up date
                <input
                  type="date"
                  name="due"
                  className={`${INPUT} mt-1`}
                  defaultValue={data.review?.due_on ?? ""}
                />
              </label>
              <label className="block">
                Root cause
                <input
                  name="cause"
                  maxLength={300}
                  className={`${INPUT} mt-1`}
                  defaultValue={data.review?.root_cause ?? ""}
                />
              </label>
              <p className="text-xs text-muted-foreground">
                Attach separate customer advice, accounting records and responses. Existing
                selections stay attached until removed. Upload and discuss records in Documents.
              </p>
              <ul className="space-y-2">
                {evidence.map((item) => (
                  <li key={item.work_item_id}>
                    {source(item.work_item_id, item.kind.toLowerCase().replaceAll("_", " "))}
                    <button
                      type="button"
                      className={`${BUTTON_SECONDARY} ml-2`}
                      onClick={() =>
                        setEvidence(evidence.filter((e) => e.work_item_id !== item.work_item_id))
                      }
                    >
                      Remove evidence
                    </button>
                  </li>
                ))}
              </ul>
              {evidence.length < 20 && (
                <SourcePicker
                  workspaceId={workspaceId}
                  value={document}
                  onChange={setDocument}
                  label="Supporting document"
                />
              )}
              <label className="block">
                Evidence kind
                <select name="kind" className={`${SELECT} mt-1`}>
                  {[
                    "DEDUCTOR_ADVICE",
                    "ACCOUNTING_RECORD",
                    "CERTIFICATE",
                    "CORRECTION_RESPONSE",
                    "CREDIT_NOTE",
                    "TRIGGERING_EVENT",
                  ].map((k) => (
                    <option key={k} value={k}>
                      {k.toLowerCase().replaceAll("_", " ")}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                Amount explicitly stated in evidence (INR)
                <input
                  name="evidenceAmount"
                  inputMode="decimal"
                  pattern="[0-9]+(\.[0-9]{1,2})?"
                  className={`${INPUT} mt-1`}
                />
              </label>
              <fieldset className="space-y-2 rounded border border-border p-3">
                <legend className="px-1">The amount the tax was computed on (optional)</legend>
                <p className="text-xs text-muted-foreground">
                  Only when an invoice, an accounting record or the customer's advice states it.
                  Servabo never works it out or checks a rate.
                  {data.basis_micros
                    ? ` Currently stated: ${rupees(data.basis_micros)} (${(data.basis_source ?? "").toLowerCase().replaceAll("_", " ")}).`
                    : ""}
                </p>
                <label className="block">
                  Amount stated (INR)
                  <input
                    name="basisAmount"
                    inputMode="decimal"
                    pattern="[0-9]+(\.[0-9]{1,2})?"
                    className={`${INPUT} mt-1`}
                  />
                </label>
                <label className="block">
                  Stated in
                  <select name="basisSource" className={`${SELECT} mt-1`}>
                    <option value="INVOICE">The invoice</option>
                    <option value="ACCOUNTING_RECORD">An accounting record</option>
                    <option value="DEDUCTOR_ADVICE">The customer's advice</option>
                  </select>
                </label>
                <label className="block">
                  The document that states it
                  <select name="basisDoc" className={`${SELECT} mt-1`} defaultValue="">
                    <option value="">Not stating one</option>
                    {data.work_item_id && <option value={data.work_item_id}>The invoice</option>}
                    {evidence.map((e) => (
                      <option key={e.work_item_id} value={e.work_item_id}>
                        {e.kind.toLowerCase().replaceAll("_", " ")}
                      </option>
                    ))}
                  </select>
                </label>
                {data.basis_micros && (
                  <label className="flex items-center gap-2">
                    <input type="checkbox" name="clearBasis" />
                    Remove the stated amount
                  </label>
                )}
              </fieldset>
              <label className="block">
                Review reason
                <textarea
                  name="reason"
                  required
                  minLength={10}
                  maxLength={1000}
                  className={`${INPUT} mt-1`}
                />
              </label>
              <label className="flex items-start gap-2">
                <input
                  type="checkbox"
                  name="confirmReceivable"
                  defaultChecked={data.review?.withholding_confirmed ?? false}
                />
                Confirm withholding for the receivable projection. Current customer advice and
                accounting amounts must agree. This holds Helm cash reminders until reviewed; it
                does not certify government posting.
              </label>
              <button disabled={save.isPending} className={BUTTON_SECONDARY}>
                Save review details
              </button>
            </form>
          </details>
        </>
      )}
      {save.isError && (
        <p role="alert" className="text-destructive">
          {errorMessage(save.error, "The review could not be saved.")}
        </p>
      )}
      {save.isSuccess && <p role="status">Review revision saved.</p>}
    </div>
  );
}
