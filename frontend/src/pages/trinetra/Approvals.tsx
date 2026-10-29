import { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  BUTTON_PRIMARY,
  BUTTON_SECONDARY,
  INPUT,
  SELECT,
  SURFACE,
} from "@/components/ui/primitives";
import StatusPill from "@/components/ui/StatusPill";
import { useResolvedTenant } from "@/routes/TenantContext";
import { errorMessage } from "@/services/api/errors";
import {
  approveClosure,
  getClosurePolicy,
  listApprovals,
  rejectClosure,
  setClosurePolicy,
  type ClosureApproval,
} from "@/services/api/trinetra";
import { formatTimestamp } from "@/utils/displayTime";
import { rupees } from "./format";

const ACTION_WORDS: Readonly<Record<string, string>> = {
  CA_REVIEWED: "Confirmed by the accountant",
  EXPLAINED: "Closed with an explanation",
  UNRESOLVED: "Left unresolved",
};

const STATUS_WORDS: Readonly<Record<string, string>> = {
  PENDING: "Waiting for approval",
  APPROVED: "Approved",
  REJECTED: "Rejected",
  STALE: "Out of date",
};

/** `150000.00`-style text for the policy form from the server's millionths. */
const toInr = (micros: string): string => {
  const value = BigInt(micros);
  return `${value / 1_000_000n}.${((value % 1_000_000n) / 10_000n).toString().padStart(2, "0")}`;
};

function Policy({
  workspaceId,
  organizationId,
  canEdit,
}: {
  workspaceId: string;
  organizationId: string;
  canEdit: boolean;
}) {
  const cache = useQueryClient();
  const policy = useQuery({
    queryKey: ["trinetra", workspaceId, "policy"],
    queryFn: () => getClosurePolicy(workspaceId),
  });
  const [threshold, setThreshold] = useState("");
  const [actions, setActions] = useState<string[]>(["CA_REVIEWED"]);
  const [role, setRole] = useState<"ADMIN" | "OWNER">("ADMIN");
  const save = useMutation({
    mutationFn: () =>
      setClosurePolicy(organizationId, {
        threshold: threshold || "0",
        actions,
        approver_role: role,
      }),
    onSuccess: () => void cache.invalidateQueries({ queryKey: ["trinetra", workspaceId] }),
  });
  const current = policy.data?.policy ?? null;
  return (
    <section
      className={`${SURFACE} space-y-3 p-5`}
      aria-labelledby="closure-policy"
      data-testid="trinetra-policy"
    >
      <h2 id="closure-policy" className="font-semibold">
        When a closure needs a second person
      </h2>
      {policy.isPending && (
        <p role="status" className="text-sm">
          Loading the policy…
        </p>
      )}
      {policy.isError && (
        <p role="alert" className="text-sm text-destructive">
          The policy could not be loaded.
        </p>
      )}
      {policy.data && (
        <p className="text-sm" data-testid="trinetra-policy-summary">
          {current
            ? `Closing a case worth at least ${rupees(current.threshold_micros)} as ${current.actions.map((a) => ACTION_WORDS[a] ?? a).join(", ")} needs an organization ${current.approver_role.toLowerCase()} other than the person who asked.`
            : "No policy yet: a person with write access can close a case on their own."}
        </p>
      )}
      {canEdit ? (
        <form
          className="grid gap-3 text-sm sm:grid-cols-2"
          onSubmit={(e) => {
            e.preventDefault();
            save.mutate();
          }}
        >
          <label>
            Needs approval from this amount (INR)
            <input
              required
              inputMode="decimal"
              pattern="[0-9]+(\.[0-9]{1,2})?"
              className={`${INPUT} mt-1`}
              value={threshold}
              placeholder={current ? toInr(current.threshold_micros) : "50000"}
              onChange={(e) => setThreshold(e.target.value)}
            />
          </label>
          <label>
            Who approves
            <select
              className={`${SELECT} mt-1`}
              value={role}
              onChange={(e) => setRole(e.target.value as "ADMIN" | "OWNER")}
            >
              <option value="ADMIN">An organization admin or owner</option>
              <option value="OWNER">An organization owner</option>
            </select>
          </label>
          <fieldset className="sm:col-span-2">
            <legend>For these ways of closing</legend>
            <div className="mt-1 flex flex-wrap gap-4">
              {Object.entries(ACTION_WORDS).map(([key, label]) => (
                <label key={key} className="flex items-center gap-2">
                  <input
                    type="checkbox"
                    checked={actions.includes(key)}
                    onChange={(e) =>
                      setActions(
                        e.target.checked ? [...actions, key] : actions.filter((a) => a !== key),
                      )
                    }
                  />
                  {label}
                </label>
              ))}
            </div>
          </fieldset>
          <div className="sm:col-span-2">
            <button className={BUTTON_PRIMARY} disabled={save.isPending || !actions.length}>
              Save the policy
            </button>
          </div>
        </form>
      ) : (
        <p className="text-xs text-muted-foreground">
          Only an organization owner or admin changes the policy.
        </p>
      )}
      {save.isError && (
        <p role="alert" className="text-sm text-destructive">
          {errorMessage(save.error, "The policy could not be saved.")}
        </p>
      )}
    </section>
  );
}

function Row({ workspaceId, item }: { workspaceId: string; item: ClosureApproval }) {
  const cache = useQueryClient();
  const [reason, setReason] = useState("");
  const [open, setOpen] = useState<"approve" | "reject" | null>(null);
  const done = () => {
    setOpen(null);
    setReason("");
    void cache.invalidateQueries({ queryKey: ["trinetra", workspaceId] });
  };
  const approve = useMutation({
    mutationFn: () => approveClosure(workspaceId, item.id, reason),
    onSuccess: done,
  });
  const reject = useMutation({
    mutationFn: () => rejectClosure(workspaceId, item.id, reason),
    onSuccess: done,
  });
  const active = open === "approve" ? approve : reject;
  return (
    <li className="space-y-2 p-4 text-sm" data-testid="trinetra-approval" data-status={item.status}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span>
          <span className="font-medium">{ACTION_WORDS[item.action] ?? item.action}</span> · worth{" "}
          {rupees(item.amount_micros)} · case revision {item.case_revision}
        </span>
        <StatusPill status={item.status} label={STATUS_WORDS[item.status] ?? item.status} />
      </div>
      <p className="text-muted-foreground">
        Asked {formatTimestamp(item.created_at)}: {item.reason}
      </p>
      {item.decided_reason && (
        <p className="text-xs text-muted-foreground">
          Decided {item.decided_at ? formatTimestamp(item.decided_at) : ""}: {item.decided_reason}
        </p>
      )}
      {item.status === "PENDING" && !open && (
        <div className="flex gap-2">
          <button className={BUTTON_PRIMARY} onClick={() => setOpen("approve")}>
            Approve
          </button>
          <button className={BUTTON_SECONDARY} onClick={() => setOpen("reject")}>
            Reject
          </button>
        </div>
      )}
      {open && (
        <form
          className="space-y-2"
          onSubmit={(e) => {
            e.preventDefault();
            (open === "approve" ? approve : reject).mutate();
          }}
        >
          <label className="block">
            {open === "approve" ? "Why you approve" : "Why you reject"}
            <textarea
              required
              minLength={10}
              maxLength={1000}
              className={`${INPUT} mt-1`}
              value={reason}
              onChange={(e) => setReason(e.target.value)}
            />
          </label>
          <div className="flex gap-2">
            <button className={BUTTON_PRIMARY} disabled={active.isPending}>
              {open === "approve" ? "Approve this closure" : "Reject this closure"}
            </button>
            <button type="button" className={BUTTON_SECONDARY} onClick={() => setOpen(null)}>
              Cancel
            </button>
          </div>
          {active.isError && (
            <p role="alert" className="text-destructive">
              {errorMessage(active.error, "That could not be recorded.")}
            </p>
          )}
        </form>
      )}
    </li>
  );
}

/** Enterprise: the policy for closing cases, and the closures waiting for a second person. A person never approves their own. */
export default function Approvals({
  workspaceId,
  organizationId,
}: {
  workspaceId: string;
  organizationId: string;
}) {
  const { organizationRole } = useResolvedTenant();
  const approvals = useQuery({
    queryKey: ["trinetra", workspaceId, "approvals"],
    queryFn: () => listApprovals(workspaceId),
  });
  const items = approvals.data?.items ?? [];
  const canEdit = organizationRole === "OWNER" || organizationRole === "ADMIN";
  return (
    <div className="space-y-4">
      <Policy workspaceId={workspaceId} organizationId={organizationId} canEdit={canEdit} />
      <section className={`${SURFACE} overflow-hidden`} aria-labelledby="approval-list">
        <h2 id="approval-list" className="border-b border-border p-5 font-semibold">
          Closures waiting for approval
        </h2>
        {approvals.isPending && (
          <p role="status" className="p-5 text-sm">
            Loading approvals…
          </p>
        )}
        {approvals.isError && (
          <p role="alert" className="p-5 text-sm text-destructive">
            The approvals could not be loaded.
          </p>
        )}
        {approvals.data && !items.length && (
          <p className="p-6 text-center text-sm text-muted-foreground">
            Nothing is waiting for approval.
          </p>
        )}
        <ul className="divide-y divide-border">
          {items.map((item) => (
            <Row key={item.id} workspaceId={workspaceId} item={item} />
          ))}
        </ul>
      </section>
    </div>
  );
}
