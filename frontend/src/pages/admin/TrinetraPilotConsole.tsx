/**
 * The operator's TRINETRA pilot console (platform superadmins).
 *
 * In `TRINETRA_MODE=pilot` only an enrolled organization is live, and only if its plan includes TRINETRA (Business,
 * Enterprise). Enrolling and withdrawing each need a reason, which the server keeps in the organization's audit log. Before this
 * page the only ways were `scripts/trinetra_pilot.py` on the server and a raw API call.
 */
import React, { useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Eye, Loader2, RefreshCw } from "lucide-react";
import { toast } from "sonner";

import {
  BUTTON_PRIMARY, BUTTON_SECONDARY, FIELD_LABEL, HINT, INPUT, SCROLL_X, SECTION_TITLE, SELECT, SURFACE, TABLE_HEAD, TABLE_ROW, TEXTAREA,
} from "@/components/ui/primitives";
import { PageHeader } from "@/components/ui/PageHeader";
import { errorMessage } from "@/services/api/errors";
import {
  enrolOrganization, getTrinetraPilot, searchOrganizations, trinetraPilotKeys, withdrawOrganization,
} from "@/services/api/trinetraPilot";
import { formatTimestamp } from "@/utils/displayTime";

const MIN_REASON = 10;

const MODE_NOTES: Record<string, string> = {
  off: "This server runs with TRINETRA_MODE=off: nobody is live and enrolment changes nothing until the mode is pilot.",
  on: "This server runs with TRINETRA_MODE=on: every Business and Enterprise organization is live; enrolment changes nothing.",
};

const TrinetraPilotConsole: React.FC = () => {
  const queryClient = useQueryClient();
  const [params] = useSearchParams();
  const [search, setSearch] = useState("");
  const [chosen, setChosen] = useState<string>(params.get("organization") ?? "");
  const [reason, setReason] = useState("");
  const [withdrawing, setWithdrawing] = useState<string | null>(null);
  const [withdrawReason, setWithdrawReason] = useState("");

  const pilot = useQuery({ queryKey: trinetraPilotKeys.all(), queryFn: getTrinetraPilot });
  const organizations = useQuery({
    queryKey: trinetraPilotKeys.organizations(search.trim()),
    queryFn: () => searchOrganizations(search.trim()),
  });
  const enrolled = useMemo(() => new Set((pilot.data?.items ?? []).map((row) => row.organization_id)), [pilot.data]);
  const refresh = async (): Promise<void> => {
    await queryClient.invalidateQueries({ queryKey: trinetraPilotKeys.all() });
    // The organization's own TRINETRA pages ask again (they read the same enrolment).
    await queryClient.invalidateQueries({ queryKey: ["trinetra"] });
  };

  const enrol = useMutation({
    mutationFn: () => enrolOrganization(chosen, reason.trim()),
    onSuccess: async (row) => {
      toast.success(`${row.name ?? "The organization"} is enrolled in the TRINETRA pilot.`);
      setReason("");
      await refresh();
    },
    onError: (error) => toast.error(errorMessage(error, "The organization could not be enrolled.")),
  });
  const withdraw = useMutation({
    mutationFn: (organizationId: string) => withdrawOrganization(organizationId, withdrawReason.trim()),
    onSuccess: async () => {
      toast.success("The organization was taken out of the pilot.");
      setWithdrawing(null);
      setWithdrawReason("");
      await refresh();
    },
    onError: (error) => toast.error(errorMessage(error, "The organization could not be withdrawn.")),
  });

  const mode = pilot.data?.mode;
  const options = organizations.data ?? [];
  const canEnrol = Boolean(chosen) && reason.trim().length >= MIN_REASON && !enrol.isPending;

  return (
    <div className="mx-auto max-w-7xl space-y-6" data-testid="trinetra-pilot-console">
      <PageHeader
        icon={Eye}
        eyebrow="Platform"
        title="TRINETRA pilot"
        description="Choose which organizations may use live TDS credit evidence while TRINETRA is in its pilot. Every change needs a reason and is kept in that organization's audit log."
        actions={
          <button type="button" className={BUTTON_SECONDARY} onClick={() => void refresh()}>
            <RefreshCw className="h-3.5 w-3.5" aria-hidden />Refresh
          </button>
        }
      />

      {pilot.isLoading ? <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />Loading…</div> : null}
      {pilot.isError ? <p role="alert" className="text-sm text-destructive">{errorMessage(pilot.error, "The pilot could not be loaded.")}</p> : null}

      {mode ? (
        <section className={`${SURFACE} space-y-1 p-4 text-sm`} aria-label="Mode">
          <p>
            This server's mode: <strong data-testid="trinetra-pilot-mode">{mode}</strong>
          </p>
          {MODE_NOTES[mode] ? (
            <p className="text-destructive" data-testid="trinetra-pilot-mode-note">{MODE_NOTES[mode]}</p>
          ) : (
            <p className={HINT}>Only the organizations below are live, and only while their plan includes TRINETRA (Business or Enterprise).</p>
          )}
        </section>
      ) : null}

      <section className={`${SURFACE} space-y-3 p-4`} aria-label="Enrol an organization">
        <h2 className={SECTION_TITLE}>Enrol an organization</h2>
        <p className={HINT}>
          Read docs/trinetra/LAUNCH-GATES.md first. A Starter organization stays on the examples even when enrolled.
        </p>
        <div className="grid gap-3 md:grid-cols-2">
          <label className="space-y-1">
            <span className={FIELD_LABEL}>Find by name or slug</span>
            <input className={INPUT} value={search} onChange={(event) => setSearch(event.target.value)} placeholder="acme" />
          </label>
          <label className="space-y-1">
            <span className={FIELD_LABEL}>Organization</span>
            <select
              className={SELECT}
              aria-label="Organization"
              value={chosen}
              onChange={(event) => setChosen(event.target.value)}
            >
              <option value="">Choose an organization</option>
              {options.map((org) => (
                <option key={org.id} value={org.id} disabled={enrolled.has(org.id)}>
                  {org.name} ({org.slug}) · {org.tier_key ?? "no plan"}{enrolled.has(org.id) ? " · enrolled" : ""}
                </option>
              ))}
              {chosen && !options.some((org) => org.id === chosen) ? <option value={chosen}>{chosen}</option> : null}
            </select>
          </label>
        </div>
        <label className="block space-y-1">
          <span className={FIELD_LABEL}>Reason for enrolling</span>
          <textarea
            className={TEXTAREA}
            aria-label="Reason for enrolling"
            value={reason}
            maxLength={500}
            onChange={(event) => setReason(event.target.value)}
            placeholder="Pilot with the owner's own files; the CA has read the wording"
          />
          <span className={HINT}>At least {MIN_REASON} characters.</span>
        </label>
        <button type="button" className={BUTTON_PRIMARY} disabled={!canEnrol} onClick={() => enrol.mutate()}>
          {enrol.isPending ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : null}
          Enrol in the pilot
        </button>
      </section>

      <section className={`${SURFACE} ${SCROLL_X} p-4`} aria-label="Enrolled organizations" tabIndex={0}>
        <h2 className={SECTION_TITLE}>Enrolled organizations</h2>
        {pilot.data && pilot.data.items.length === 0 ? <p className="mt-2 text-sm text-muted-foreground">No organization is enrolled.</p> : null}
        {pilot.data && pilot.data.items.length > 0 ? (
          <table className="mt-2 w-full text-sm">
            <thead>
              <tr className={TABLE_HEAD}>
                <th className="py-2 pr-3">Organization</th><th className="pr-3">Reason</th><th className="pr-3">Enrolled</th><th className="pr-3"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {pilot.data.items.map((row) => {
                const name = row.name ?? row.organization_id;
                return (
                  <tr key={row.organization_id} className={TABLE_ROW} data-testid="trinetra-pilot-row">
                    <td className="py-2 pr-3">
                      <span className="font-medium">{name}</span>
                      {row.slug ? <span className={`block ${HINT}`}>{row.slug}</span> : null}
                      {row.entitled === false ? (
                        <span className="block text-xs text-destructive">Its plan has no TRINETRA: it stays on the examples.</span>
                      ) : null}
                    </td>
                    <td className="pr-3">{row.reason}</td>
                    <td className="pr-3 whitespace-nowrap">{formatTimestamp(row.enrolled_at)}</td>
                    <td className="py-2 pr-3 text-right">
                      {withdrawing === row.organization_id ? (
                        <div className="flex flex-wrap items-center justify-end gap-2">
                          <input
                            className={INPUT}
                            aria-label="Reason for withdrawing"
                            value={withdrawReason}
                            maxLength={500}
                            onChange={(event) => setWithdrawReason(event.target.value)}
                            placeholder="Pilot over; the customer asked to stop"
                          />
                          <button
                            type="button"
                            className={BUTTON_PRIMARY}
                            disabled={withdrawReason.trim().length < MIN_REASON || withdraw.isPending}
                            onClick={() => withdraw.mutate(row.organization_id)}
                          >
                            Confirm withdrawal
                          </button>
                          <button type="button" className={BUTTON_SECONDARY} onClick={() => setWithdrawing(null)}>Cancel</button>
                        </div>
                      ) : (
                        <button
                          type="button"
                          className={BUTTON_SECONDARY}
                          aria-label={`Withdraw ${name}`}
                          onClick={() => { setWithdrawing(row.organization_id); setWithdrawReason(""); }}
                        >
                          Withdraw
                        </button>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : null}
      </section>
    </div>
  );
};

export default TrinetraPilotConsole;
