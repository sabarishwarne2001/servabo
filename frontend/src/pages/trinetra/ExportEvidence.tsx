import { useMutation } from "@tanstack/react-query";
import { downloadDossier } from "@/services/api/trinetra";
import { BUTTON_SECONDARY } from "@/components/ui/primitives";
import { errorMessage } from "@/services/api/errors";

export default function ExportEvidence({ workspaceId }: { workspaceId: string }) {
  const save = useMutation({
    mutationFn: async (format: "csv" | "xlsx" | "html") => {
      const blob = await downloadDossier(workspaceId, format);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `trinetra-evidence.${format}`;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  });
  return (
    <div className="flex flex-wrap gap-2" aria-label="Export evidence">
      {(["csv", "xlsx", "html"] as const).map((format) => (
        <button
          key={format}
          className={BUTTON_SECONDARY}
          disabled={save.isPending}
          onClick={() => save.mutate(format)}
        >
          Export {format === "html" ? "evidence report" : format.toUpperCase()}
        </button>
      ))}
      {save.isError && (
        <p role="alert">{errorMessage(save.error, "The evidence export could not be created.")}</p>
      )}
    </div>
  );
}
