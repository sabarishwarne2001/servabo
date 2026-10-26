import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Eye } from "lucide-react";
import PageHeader from "@/components/ui/PageHeader";
import { BUTTON_SECONDARY, SURFACE } from "@/components/ui/primitives";
import { DocumentPageViewer } from "@/components/workItems/DocumentPageViewer";
import { useActiveWorkspace } from "@/hooks/useActiveWorkspace";
import { getCreditDetail } from "@/services/api/trinetra";
import CaseReview from "./CaseReview";

function Source({ workspaceId, id, title }: { workspaceId: string; id: string; title: string }) {
  const [page, setPage] = useState(1);
  return (
    <section className={`${SURFACE} min-w-0 space-y-3 p-4`} aria-label={title}>
      <h2 className="font-semibold">{title}</h2>
      <DocumentPageViewer
        workspaceId={workspaceId}
        workItemId={id}
        page={page}
        onPageChange={setPage}
        locations={[]}
        canvasClassName="max-h-[60vh]"
      />
    </section>
  );
}

export default function CaseDetail({ creditId }: { creditId: string }) {
  const workspace = useActiveWorkspace();
  const workspaceId = workspace?.workspaceId ?? "";
  const detail = useQuery({
    queryKey: ["trinetra", workspaceId, "case", creditId],
    queryFn: () => getCreditDetail(workspaceId, creditId),
    enabled: Boolean(workspaceId),
  });
  return (
    <div className="space-y-6 p-4 sm:p-6">
      <PageHeader
        icon={Eye}
        eyebrow="TRINETRA"
        title="Review credit evidence"
        description="Compare canonical source documents and record a versioned human decision."
        actions={
          <Link className={BUTTON_SECONDARY} to="?">
            Back to credit queue
          </Link>
        }
      />
      {detail.isPending && <p role="status">Loading case evidence…</p>}
      {detail.isError && (
        <p role="alert">
          This case could not be loaded.{" "}
          <button className={BUTTON_SECONDARY} onClick={() => void detail.refetch()}>
            Try again
          </button>
        </p>
      )}
      {detail.data && (
        <>
          <p className="font-medium">
            {detail.data.counterparty} · {detail.data.reference} · {detail.data.period}
          </p>
          <div className="grid gap-4 lg:grid-cols-2">
            {detail.data.work_item_id && (
              <Source
                key={detail.data.work_item_id}
                workspaceId={workspaceId}
                id={detail.data.work_item_id}
                title="Invoice source"
              />
            )}
            {detail.data.statement_work_item_id ? (
              <Source
                key={detail.data.statement_work_item_id}
                workspaceId={workspaceId}
                id={detail.data.statement_work_item_id}
                title="Active statement source"
              />
            ) : (
              <section className={`${SURFACE} p-4`}>
                <h2 className="font-semibold">Statement evidence needed</h2>
                <p className="mt-3 text-sm text-muted-foreground">
                  No current statement source is available. An absent import does not establish
                  missing tax credit.
                </p>
              </section>
            )}
          </div>
          <section className={`${SURFACE} p-5`}>
            <CaseReview
              workspaceId={workspaceId}
              creditId={creditId}
              canDecide={workspace?.role === "ADMIN"}
            />
          </section>
        </>
      )}
    </div>
  );
}
