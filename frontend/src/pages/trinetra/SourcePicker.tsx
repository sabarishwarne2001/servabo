import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { getWorkItems } from "@/services/api/workItem";
import { BUTTON_SECONDARY, INPUT, SELECT } from "@/components/ui/primitives";

export default function SourcePicker({
  workspaceId,
  value,
  onChange,
  label = "Source document",
  required = false,
}: {
  workspaceId: string;
  value: string;
  onChange: (value: string) => void;
  label?: string;
  required?: boolean;
}) {
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const documents = useQuery({
    queryKey: ["trinetra", workspaceId, "documents", search, page],
    queryFn: () => getWorkItems(workspaceId, { page, pageSize: 25, search }),
  });
  return (
    <fieldset className="space-y-2 text-sm">
      <legend className="sr-only">{label} selection</legend>
      <label className="block">
        Search uploaded evidence
        <input
          className={`${INPUT} mt-1`}
          type="search"
          value={search}
          maxLength={200}
          onChange={(e) => {
            setSearch(e.target.value);
            setPage(1);
          }}
        />
      </label>
      <label className="block">
        {label}
        <select
          className={`${SELECT} mt-1`}
          required={required}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        >
          <option value="">Choose uploaded evidence</option>
          {value && !documents.data?.items.some((d) => d.id === value) && (
            <option value={value}>Selected evidence (outside these results)</option>
          )}
          {documents.data?.items.map((d) => (
            <option key={d.id} value={d.id}>
              {d.original_filename}
            </option>
          ))}
        </select>
      </label>
      <div className="flex items-center gap-2">
        <button
          className={BUTTON_SECONDARY}
          type="button"
          disabled={page === 1 || documents.isFetching}
          onClick={() => setPage(page - 1)}
        >
          Previous sources
        </button>
        <span>Page {page}</span>
        <button
          className={BUTTON_SECONDARY}
          type="button"
          disabled={documents.isFetching || !documents.data || page * 25 >= documents.data.total}
          onClick={() => setPage(page + 1)}
        >
          Next sources
        </button>
      </div>
      {documents.isPending && <p role="status">Loading sources…</p>}
      {documents.isError && (
        <p role="alert">
          Sources could not be loaded.{" "}
          <button
            type="button"
            className={BUTTON_SECONDARY}
            onClick={() => void documents.refetch()}
          >
            Try again
          </button>
        </p>
      )}
      {documents.data?.total === 0 && (
        <p>No documents match this search. Upload evidence through Documents.</p>
      )}
    </fieldset>
  );
}
