/**
 * Connect your books (Final session 1, 3C): Zoho Books with a sign-in at Zoho, and Tally Prime guided.
 *
 * Zoho: pick the data centre (India first), "Connect Zoho Books" opens Zoho's own consent screen, Zoho sends the person back here
 * and, if their login holds several organizations, they choose the one whose books these bills go to. A refused or expired sign-in
 * reads "Reconnect Zoho Books" (never a raw error). Tally Prime: five answers become a download target; the file is imported in
 * Tally Prime. Only an administrator changes anything; everyone else sees what is connected.
 */
import React, { useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useNavigate, useSearchParams } from "react-router-dom";
import { Loader2, PlugZap } from "lucide-react";
import { toast } from "sonner";

import { useConfirmDialog } from "@/components/common/useConfirmDialog";
import { BUTTON_PRIMARY, BUTTON_SECONDARY, HINT, INPUT, SECTION_TITLE, SELECT, SURFACE } from "@/components/ui/primitives";
import { erpTargetPath } from "@/routes/tenantPaths";
import {
  checkZoho,
  chooseZohoOrganization,
  connectZoho,
  disconnectZoho,
  erpConnectKeys,
  getZoho,
  listZohoOrganizations,
  setUpTally,
  type ZohoConnection,
} from "@/services/api/erpConnect";
import { erpKeys } from "@/services/api/erp";
import { errorMessage } from "@/services/api/errors";

const REASONS: Readonly<Record<string, string>> = {
  DENIED: "Zoho was not given permission, so nothing was connected.",
  INCOMPLETE: "Zoho did not send everything back. Try again.",
  BAD_STATE: "That sign-in link was not valid. Start again from Connect Zoho Books.",
  EXPIRED: "That sign-in took too long (more than ten minutes). Start again.",
  USED: "That sign-in link was already used. Start again.",
  EXCHANGE_FAILED: "Zoho did not accept the sign-in. Start again.",
  WRONG_DATA_CENTRE: "Your Zoho account is in a different data centre. Choose the right one and connect again.",
  PLAN: "Posting to an accounting system is not included in your plan.",
  NOT_CONFIGURED: "Zoho sign-in is not set up on this Servabo installation.",
};

const STATE_WORDS: Readonly<Record<string, string>> = {
  CONNECTED: "Connected",
  CHOOSE_ORGANIZATION: "Choose your Zoho organization",
  RECONNECT: "Needs reconnecting",
  DISCONNECTED: "Disconnected",
};

interface ConnectBooksProps {
  readonly workspaceId: string;
  readonly orgSlug: string;
  readonly workspaceSlug: string;
  readonly isAdmin: boolean;
}

export const ConnectBooks: React.FC<ConnectBooksProps> = ({ workspaceId, orgSlug, workspaceSlug, isAdmin }) => {
  const [params, setParams] = useSearchParams();
  const zoho = useQuery({ queryKey: erpConnectKeys.zoho(workspaceId), queryFn: () => getZoho(workspaceId), enabled: Boolean(workspaceId) });
  const reason = params.get("zoho") === "error" ? REASONS[params.get("reason") ?? ""] ?? "Zoho Books could not be connected." : null;
  const justConnected = params.get("zoho") === "connected";

  return (
    <div className="space-y-4" data-testid="connect-books">
      {reason ? (
        <p role="alert" className="rounded-lg border border-destructive/40 bg-destructive/5 p-3 text-sm" data-testid="zoho-error">
          {reason}{" "}
          <button type="button" className="underline" onClick={() => setParams({})}>Dismiss</button>
        </p>
      ) : null}
      {justConnected ? (
        <p role="status" className="rounded-lg border border-emerald-500/40 bg-emerald-500/10 p-3 text-sm" data-testid="zoho-connected">
          Zoho Books is connected. Approved bills can now be posted to it.{" "}
          <button type="button" className="underline" onClick={() => setParams({})}>Dismiss</button>
        </p>
      ) : null}
      <section className={`${SURFACE} space-y-3 p-4`} aria-labelledby="zoho-title">
        <h2 id="zoho-title" className={SECTION_TITLE}>Zoho Books</h2>
        <p className={HINT}>
          Sign in at Zoho and approved purchase bills are posted to your Zoho Books with the vendor’s GSTIN, the place of supply, the HSN or
          SAC code and the tax on every line. Servabo never sees your Zoho password.
        </p>
        {zoho.isLoading ? <Loader2 className="h-4 w-4 animate-spin" aria-label="Loading" /> : null}
        {zoho.isError ? <p className="text-sm text-destructive">{errorMessage(zoho.error, "Could not load Zoho Books.")}</p> : null}
        {zoho.data && !zoho.data.configured ? (
          <p className={HINT} data-testid="zoho-not-configured">
            Zoho sign-in is not set up on this Servabo installation. Ask the person who runs Servabo to add the Zoho app settings.
          </p>
        ) : null}
        {zoho.data?.connections.map((connection) => (
          <ZohoRow key={connection.target_id} workspaceId={workspaceId} connection={connection} isAdmin={isAdmin}
            dataCentres={zoho.data.data_centres} orgSlug={orgSlug} workspaceSlug={workspaceSlug} />
        ))}
        {zoho.data?.configured && isAdmin ? (
          <NewZoho workspaceId={workspaceId} dataCentres={zoho.data.data_centres} defaultCentre={zoho.data.default_data_centre} />
        ) : null}
        {zoho.data?.configured && !isAdmin ? <p className={HINT}>A workspace admin connects Zoho Books.</p> : null}
      </section>
      <TallyGuide workspaceId={workspaceId} orgSlug={orgSlug} workspaceSlug={workspaceSlug} isAdmin={isAdmin} />
    </div>
  );
};

const NewZoho: React.FC<{ readonly workspaceId: string; readonly dataCentres: readonly { key: string; label: string }[];
  readonly defaultCentre: string }> = ({ workspaceId, dataCentres, defaultCentre }) => {
  const [centre, setCentre] = useState(defaultCentre);
  const connect = useMutation({
    mutationFn: () => connectZoho(workspaceId, centre),
    onSuccess: (result) => window.location.assign(result.authorize_url),
    onError: (error: unknown) => toast.error(errorMessage(error, "Could not start the Zoho sign-in.")),
  });
  return (
    <div className="flex flex-wrap items-end gap-2">
      <label className="text-xs font-medium">
        Zoho data centre
        <select className={`${SELECT} mt-1 block w-60`} value={centre} onChange={(e) => setCentre(e.target.value)}>
          {dataCentres.map((d) => <option key={d.key} value={d.key}>{d.label}</option>)}
        </select>
      </label>
      <button type="button" className={BUTTON_PRIMARY} disabled={connect.isPending} onClick={() => connect.mutate()}>
        {connect.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <PlugZap className="h-4 w-4" aria-hidden />}
        Connect Zoho Books
      </button>
      <p className={`${HINT} basis-full`}>Not sure? Look at the address you sign in to Zoho at: zoho.in is India, zoho.com is the United States, zoho.eu is Europe.</p>
    </div>
  );
};

const ZohoRow: React.FC<{
  readonly workspaceId: string;
  readonly connection: ZohoConnection;
  readonly isAdmin: boolean;
  readonly dataCentres: readonly { key: string; label: string }[];
  readonly orgSlug: string;
  readonly workspaceSlug: string;
}> = ({ workspaceId, connection, isAdmin, orgSlug, workspaceSlug }) => {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const { ask, confirmDialog } = useConfirmDialog();
  const [chosen, setChosen] = useState("");
  const refresh = (): Promise<void> => queryClient.invalidateQueries({ queryKey: erpKeys.all(workspaceId) });
  const organizations = useQuery({
    queryKey: erpConnectKeys.organizations(workspaceId, connection.target_id),
    queryFn: () => listZohoOrganizations(workspaceId, connection.target_id),
    enabled: isAdmin && connection.state === "CHOOSE_ORGANIZATION",
    retry: false,
  });
  const choose = useMutation({
    mutationFn: () => chooseZohoOrganization(workspaceId, connection.target_id, chosen),
    onSuccess: async () => { toast.success("Zoho organization chosen."); await refresh(); },
    onError: (error: unknown) => toast.error(errorMessage(error, "Could not choose that organization.")),
  });
  const check = useMutation({
    mutationFn: () => checkZoho(workspaceId, connection.target_id),
    onSuccess: async (view) => { toast[view.state === "CONNECTED" ? "success" : "error"](view.state === "CONNECTED" ? "Zoho Books is connected." : "Zoho Books needs to be reconnected."); await refresh(); },
    onError: (error: unknown) => toast.error(errorMessage(error, "Could not check Zoho Books.")),
  });
  const reconnect = useMutation({
    mutationFn: () => connectZoho(workspaceId, connection.data_centre ?? "IN", connection.target_id),
    onSuccess: (result) => window.location.assign(result.authorize_url),
    onError: (error: unknown) => toast.error(errorMessage(error, "Could not start the Zoho sign-in.")),
  });
  const disconnect = useMutation({
    mutationFn: () => disconnectZoho(workspaceId, connection.target_id),
    onSuccess: async (result) => {
      toast.success(result.revoked_at_zoho ? "Disconnected, and Zoho’s access was revoked." : "Disconnected here. Remove the app under Zoho’s connected apps too.");
      await refresh();
    },
    onError: (error: unknown) => toast.error(errorMessage(error, "Could not disconnect.")),
  });
  const confirmDisconnect = async (): Promise<void> => {
    if (await ask({ title: "Disconnect Zoho Books?", message: "Servabo revokes its access at Zoho and forgets the sign-in. Postings already made stay in your books; new ones wait until you connect again.", confirmText: "Disconnect" })) {
      disconnect.mutate();
    }
  };
  return (
    <div className="rounded-lg border border-border/70 p-3" data-testid="zoho-connection">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-sm font-semibold">{connection.name}</p>
        <span className="rounded-full border border-border px-2 py-0.5 text-[11px] font-semibold" data-testid="zoho-state">{STATE_WORDS[connection.state]}</span>
        {connection.data_centre_label ? <span className={HINT}>{connection.data_centre_label}</span> : null}
        {connection.organization_name ? <span className={HINT}>· {connection.organization_name}</span> : null}
        {connection.state === "CONNECTED" ? (
          <button type="button" className="ml-auto text-xs underline" onClick={() => navigate(erpTargetPath(orgSlug, workspaceSlug, connection.target_id))}>Mappings and tax codes</button>
        ) : null}
      </div>
      {connection.state === "RECONNECT" ? (
        <p role="alert" className="mt-2 text-sm text-amber-800 dark:text-amber-300">
          Zoho no longer accepts the saved sign-in. Postings wait and are sent again once you reconnect.
        </p>
      ) : null}
      {connection.state === "CHOOSE_ORGANIZATION" && isAdmin ? (
        <div className="mt-2 flex flex-wrap items-end gap-2">
          {organizations.isLoading ? <Loader2 className="h-4 w-4 animate-spin" aria-label="Loading" /> : null}
          {organizations.data ? (
            <>
              <label className="text-xs font-medium">
                Zoho organization
                <select className={`${SELECT} mt-1 block w-72`} value={chosen} onChange={(e) => setChosen(e.target.value)}>
                  <option value="">Choose…</option>
                  {organizations.data.map((o) => <option key={o.organization_id} value={o.organization_id}>{o.name}</option>)}
                </select>
              </label>
              <button type="button" className={BUTTON_PRIMARY} disabled={!chosen || choose.isPending} onClick={() => choose.mutate()}>Use this organization</button>
            </>
          ) : null}
          {organizations.isError ? <p className="text-sm text-destructive">{errorMessage(organizations.error, "Could not list your Zoho organizations.")}</p> : null}
        </div>
      ) : null}
      {isAdmin ? (
        <div className="mt-2 flex flex-wrap gap-2">
          {connection.state === "RECONNECT" ? (
            <button type="button" className={BUTTON_PRIMARY} disabled={reconnect.isPending} onClick={() => reconnect.mutate()}>Reconnect Zoho Books</button>
          ) : null}
          {connection.state === "DISCONNECTED" ? (
            <button type="button" className={BUTTON_PRIMARY} disabled={reconnect.isPending} onClick={() => reconnect.mutate()}>Connect again</button>
          ) : null}
          {connection.state === "CONNECTED" || connection.state === "RECONNECT" ? (
            <button type="button" className={BUTTON_SECONDARY} disabled={check.isPending} onClick={() => check.mutate()}>Check connection</button>
          ) : null}
          {connection.state !== "DISCONNECTED" ? (
            <button type="button" className={BUTTON_SECONDARY} disabled={disconnect.isPending} onClick={() => void confirmDisconnect()}>Disconnect</button>
          ) : null}
        </div>
      ) : null}
      {confirmDialog}
    </div>
  );
};

const TallyGuide: React.FC<{ readonly workspaceId: string; readonly orgSlug: string; readonly workspaceSlug: string; readonly isAdmin: boolean }> = ({
  workspaceId, orgSlug, workspaceSlug, isAdmin,
}) => {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ company: "", purchases: "", cgst: "", sgst: "", igst: "", tax: "" });
  const setup = useMutation({
    mutationFn: () => setUpTally(workspaceId, form),
    onSuccess: async (result) => {
      toast.success("Tally Prime target created.");
      await queryClient.invalidateQueries({ queryKey: erpKeys.all(workspaceId) });
      navigate(erpTargetPath(orgSlug, workspaceSlug, result.target_id));
    },
    onError: (error: unknown) => toast.error(errorMessage(error, "Could not set up Tally Prime.")),
  });
  const field = (key: keyof typeof form, label: string, placeholder: string): React.ReactNode => (
    <label className="block text-xs font-medium">
      {label}
      <input className={`${INPUT} mt-1`} value={form[key]} placeholder={placeholder} maxLength={200}
        onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
    </label>
  );
  return (
    <section className={`${SURFACE} space-y-3 p-4`} aria-labelledby="tally-title">
      <h2 id="tally-title" className={SECTION_TITLE}>Tally Prime</h2>
      <p className={HINT}>
        Answer five questions and each approved bill becomes one balanced Purchase voucher: the supplier credited, your purchase ledger
        debited, and the tax booked to Input CGST and Input SGST for a supplier in your state, or Input IGST for another state. You download
        the file and import it in Tally Prime.
      </p>
      {isAdmin && !open ? <button type="button" className={BUTTON_SECONDARY} onClick={() => setOpen(true)}>Set up Tally Prime</button> : null}
      {!isAdmin ? <p className={HINT}>A workspace admin sets up Tally Prime.</p> : null}
      {open && isAdmin ? (
        <form className="grid gap-3 sm:grid-cols-2" onSubmit={(e) => { e.preventDefault(); setup.mutate(); }} aria-label="Set up Tally Prime">
          <div className="sm:col-span-2">{field("company", "Company, exactly as spelled in Tally Prime", "Meridian Wholesale Pvt Ltd")}</div>
          {field("purchases", "Purchase ledger", "Purchase Accounts")}
          {field("tax", "Input tax ledger (when a bill has no GST split)", "Input Tax")}
          {field("cgst", "Input CGST ledger", "Input CGST")}
          {field("sgst", "Input SGST ledger", "Input SGST")}
          {field("igst", "Input IGST ledger", "Input IGST")}
          <div className="sm:col-span-2 flex gap-2">
            <button type="submit" className={BUTTON_PRIMARY} disabled={!form.company.trim() || setup.isPending}>Create the Tally target</button>
            <button type="button" className={BUTTON_SECONDARY} onClick={() => setOpen(false)}>Cancel</button>
          </div>
        </form>
      ) : null}
    </section>
  );
};

export default ConnectBooks;
