import { Link } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useTenant } from "@/hooks/useTenant";
import { workItemDetailsPath } from "@/routes/tenantPaths";
import { BUTTON_SECONDARY, INPUT, SELECT } from "@/components/ui/primitives";
import { reconfirmCredit, updateCreditReview, type CaseDetail } from "@/services/api/trinetra";
import { errorMessage } from "@/services/api/errors";
import { getWorkItems } from "@/services/api/workItem";
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
  const documents = useQuery({
    queryKey: ["trinetra", workspaceId, "documents"],
    queryFn: () => getWorkItems(workspaceId, { page: 1, pageSize: 100 }),
    enabled: canDecide,
  });
  const save = useMutation({
    mutationFn: async (form: FormData) => {
      const reason = String(form.get("reason") ?? "");
      if (form.get("task") === "expectation") {
        return reconfirmCredit(workspaceId, data.id, {
          revision: data.revision,
          amount: String(form.get("amount")),
          reason,
        });
      }
      const evidenceId = String(form.get("document") ?? "").trim();
      return updateCreditReview(workspaceId, data.id, {
        revision: data.revision,
        assign_to_me: form.get("claim") === "on",
        priority: String(form.get("priority")),
        root_cause: String(form.get("cause") ?? ""),
        due_on: form.get("due") || null,
        reason,
        evidence: evidenceId
          ? [
              {
                work_item_id: evidenceId,
                kind: String(form.get("kind")),
                amount: form.get("evidenceAmount") || null,
              },
            ]
          : [],
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
        <div>Owner: {data.review?.owner_id ? "Assigned reviewer" : "Unassigned"}</div>
        <div>Priority: {data.review?.priority ?? "NORMAL"}</div>
        <div>Root cause: {data.review?.root_cause || "Under investigation"}</div>
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
                Choose an existing source document. This replaces the supporting evidence selection;
                historical references remain in the review history. Upload and discuss records in
                Documents.
              </p>
              <label className="block">
                Supporting document
                <select name="document" className={`${SELECT} mt-1`}>
                  <option value="">No supporting document</option>
                  {documents.data?.items.map((doc) => (
                    <option key={doc.id} value={doc.id}>
                      {doc.original_filename}
                    </option>
                  ))}
                </select>
              </label>
              <label className="block">
                Evidence kind
                <select name="kind" className={`${SELECT} mt-1`}>
                  {[
                    "DEDUCTOR_ADVICE",
                    "ACCOUNTING_RECORD",
                    "CERTIFICATE",
                    "CORRECTION_RESPONSE",
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
