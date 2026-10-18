import React, { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle,
  CheckCircle2,
  Copy,
  Globe,
  Image as ImageIcon,
  Loader2,
  Monitor,
  Moon,
  Palette,
  RefreshCw,
  ShieldCheck,
  Star,
  Sun,
  Trash2,
  Undo2,
  Upload,
  type LucideIcon,
} from "lucide-react";

import {
  claimCustomDomain,
  clearFavicon,
  clearLogo,
  getBranding,
  listCustomDomains,
  reissueChallenge,
  releaseCustomDomain,
  requestCertificate,
  revokeCustomDomain,
  setPrimaryDomain,
  setSenderDomain,
  updateBranding,
  uploadFavicon,
  uploadLogo,
  verifyCustomDomain,
  verifySenderDomain,
} from "@/services/api/branding";
import { brandingKeys, entitlementKeys } from "@/services/api/queryKeys";
import { useResolvedOrganization } from "@/routes/OrganizationGuard";
import { useAuthenticatedImage } from "@/hooks/useAuthenticatedImage";
import { useImageFallback } from "@/hooks/useImageFallback";
import { BRANDING_ENDPOINTS } from "@/services/api/endpoints";
import { PlanLockBanner } from "@/components/billing/PlanLockBanner";
import { CAPABILITY } from "@/constants/capabilities";
import { useCapabilityAccess } from "@/hooks/useCapabilityAccess";
import { AddOnGraceNotice, AddOnLockCard } from "@/components/billing/AddOnLockCard";
import { useAddonAccess } from "@/hooks/useAddonAccess";
import { errorMessage as apiErrorMessage } from "@/services/api/errors";
import { addonRequiredDetail } from "@/services/api/entitlements";
import {
  CERTIFICATE_STATUS_LABELS,
  DOMAIN_STATUS_CLASSES,
  DOMAIN_STATUS_LABELS,
  SENDER_STATUS_LABELS,
  formatDateTime,
  isValidHexColor,
  type ColorScheme,
  type CustomDomainDetail,
  type TenantBrandingResponse,
  type TenantBrandingUpdate,
} from "@/types/branding";
import { PageHeader } from "@/components/ui/PageHeader";
import {
  BUTTON_DESTRUCTIVE,
  BUTTON_GHOST,
  BUTTON_PRIMARY,
  BUTTON_SECONDARY,
  FIELD_LABEL,
  HINT,
  INPUT as INPUT_BASE,
  SECTION_TITLE,
} from "@/components/ui/primitives";
import { BrandPreview } from "@/components/branding/BrandPreview";
import { BRAND_PRESETS, type BrandPreset } from "@/components/branding/brandPresets";
import { ColorField } from "@/components/branding/ColorField";

const CARD = "fp-card p-5 sm:p-6";
const LABEL = FIELD_LABEL;
const INPUT = `${INPUT_BASE} mt-1`;
const PRIMARY = BUTTON_PRIMARY;
const SECONDARY = BUTTON_SECONDARY;
const GHOST = BUTTON_GHOST;
const DANGER = BUTTON_DESTRUCTIVE;

const COLOR_FIELDS = [
  { key: "primary_color", label: "Primary", help: "Buttons, links and focus rings" },
  { key: "accent_color", label: "Accent", help: "The glow behind sign-in pages" },
  { key: "background_color", label: "Background", help: "Sign-in page backdrop" },
  { key: "foreground_color", label: "Text", help: "Sign-in page text" },
] as const;

type ColorKey = (typeof COLOR_FIELDS)[number]["key"];

const SCHEME_ICONS: Readonly<Record<ColorScheme, LucideIcon>> = { SYSTEM: Monitor, LIGHT: Sun, DARK: Moon };

const SCHEMES: readonly ColorScheme[] = ["SYSTEM", "LIGHT", "DARK"];

const errorMessage = (error: unknown): string =>
  apiErrorMessage(error, "Something went wrong. Please try again.");

const CopyButton: React.FC<{ value: string; label: string }> = ({
  value,
  label,
}) => {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      className={SECONDARY}
      onClick={() => {
        void navigator.clipboard?.writeText(value);
        setCopied(true);
        window.setTimeout(() => setCopied(false), 1500);
      }}
      aria-label={`Copy ${label}`}
    >
      <Copy className="h-3.5 w-3.5" aria-hidden />
      {copied ? "Copied" : "Copy"}
    </button>
  );
};

// ---------------------------------------------------------------------------
// DNS challenge
// ---------------------------------------------------------------------------

const ChallengeInstructions: React.FC<{ domain: CustomDomainDetail }> = ({
  domain,
}) => (
  <div className="mt-3 rounded-lg border border-border/70 bg-muted/40 p-3">
    <p className={LABEL}>Publish this TXT record, then verify</p>
    <p className={`${HINT} mt-1`}>
      DNS changes can take up to 48 hours to propagate. Verification is also
      retried automatically in the background.
    </p>
    <dl className="mt-3 space-y-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <dt className="w-20 text-muted-foreground">Name</dt>
        <dd className="font-mono text-xs break-all">
          {domain.challenge.record_name}
        </dd>
        <CopyButton
          value={domain.challenge.record_name}
          label="record name"
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <dt className="w-20 text-muted-foreground">Type</dt>
        <dd className="font-mono text-xs">{domain.challenge.record_type}</dd>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <dt className="w-20 text-muted-foreground">Value</dt>
        <dd className="font-mono text-xs break-all">
          {domain.challenge.record_value}
        </dd>
        <CopyButton
          value={domain.challenge.record_value}
          label="record value"
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <dt className="w-20 text-muted-foreground">Expires</dt>
        <dd className="text-xs">
          {formatDateTime(domain.challenge.expires_at)}
        </dd>
      </div>
    </dl>
  </div>
);

// ---------------------------------------------------------------------------
// One domain row
// ---------------------------------------------------------------------------

interface DomainRowProps {
  readonly domain: CustomDomainDetail;
  readonly isOwner: boolean;
  readonly busy: boolean;
  /**
   * ARCH30-T4F:domainrow-maintain-prop — A4. The server's
   * `can_maintain`, not a local derivation from the add-on state. The
   * backend already refuses verify / reissue / set-primary /
   * request-certificate in GRACE and LAPSED; before this, the console
   * still offered all four, so the only way to discover the rule was
   * to press a button and read a 402. Destructive and cleanup actions
   * are deliberately NOT gated on this — a tenant who has stopped
   * paying must always be able to stop serving and release a hostname.
   */
  readonly canMaintain: boolean;
  readonly maintainReason: string;
  readonly onVerify: (id: string) => void;
  readonly onReissue: (id: string) => void;
  readonly onPrimary: (id: string, next: boolean) => void;
  readonly onCertificate: (id: string) => void;
  readonly onRevoke: (id: string) => void;
  readonly onRelease: (id: string) => void;
}

// ARCH30-T4F:domainrow-maintain-destructure — A4.
const DomainRow: React.FC<DomainRowProps> = ({
  domain,
  isOwner,
  busy,
  canMaintain,
  maintainReason,
  onVerify,
  onReissue,
  onPrimary,
  onCertificate,
  onRevoke,
  onRelease,
}) => (
  <li className="rounded-xl border border-border/70 bg-muted/20 p-4">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <div className="flex items-center gap-2">
        <Globe className="h-4 w-4 text-muted-foreground" aria-hidden />
        <span className="font-medium">{domain.hostname}</span>
        {domain.is_primary ? (
          <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 px-2 py-0.5 text-xs text-primary">
            <Star className="h-3 w-3" aria-hidden />
            Primary
          </span>
        ) : null}
      </div>
      <span
        className={`rounded-full px-2 py-0.5 text-xs ${DOMAIN_STATUS_CLASSES[domain.status]}`}
      >
        {DOMAIN_STATUS_LABELS[domain.status]}
      </span>
    </div>

    <p className={`${HINT} mt-2`}>
      TLS: {CERTIFICATE_STATUS_LABELS[domain.certificate_status]}
      {domain.certificate_expires_at
        ? ` · expires ${formatDateTime(domain.certificate_expires_at)}`
        : ""}
      {domain.last_checked_at
        ? ` · last checked ${formatDateTime(domain.last_checked_at)}`
        : ""}
    </p>

    {domain.last_failure_reason ? (
      <p className="mt-2 flex items-start gap-2 text-xs text-amber-700 dark:text-amber-300">
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        {domain.last_failure_reason}
      </p>
    ) : null}

    {domain.certificate_last_error ? (
      <p className="mt-2 flex items-start gap-2 text-xs text-destructive">
        <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
        {domain.certificate_last_error}
      </p>
    ) : null}

    {domain.status !== "VERIFIED" ? (
      <ChallengeInstructions domain={domain} />
    ) : null}

    {isOwner ? (
      <div className="mt-3 flex flex-wrap gap-2">
        {/* ARCH30-T4F:domainrow-gate-verify-reissue — A4 */}
        <button
          type="button"
          className={SECONDARY}
          disabled={busy || !canMaintain}
          title={canMaintain ? undefined : maintainReason}
          onClick={() => onVerify(domain.id)}
        >
          <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
          Verify now
        </button>
        <button
          type="button"
          className={SECONDARY}
          disabled={busy || !canMaintain}
          title={canMaintain ? undefined : maintainReason}
          onClick={() => onReissue(domain.id)}
        >
          <RefreshCw className="h-3.5 w-3.5" aria-hidden />
          New challenge
        </button>
        <button
          type="button"
          className={PRIMARY}
          /*
           * The server's flag, not a local derivation. See CustomDomainDetail
           * in @/types/branding: enabling this from status would show an
           * enabled button the API then refuses.
           */
          /* ARCH30-T4F:domainrow-gate-certificate — A4. Two independent
             reasons to refuse: the domain is not in a state where a
             certificate can be issued, or the add-on no longer covers
             maintenance. Both disable; the tooltip names whichever
             applies. */
          disabled={busy || !domain.may_request_certificate || !canMaintain}
          title={canMaintain ? undefined : maintainReason}
          onClick={() => onCertificate(domain.id)}
        >
          <ShieldCheck className="h-3.5 w-3.5" aria-hidden />
          {domain.certificate_status === "NONE"
            ? "Request certificate"
            : "Renew certificate"}
        </button>
        {domain.status === "VERIFIED" && !domain.is_primary ? (
          <button
            type="button"
            className={SECONDARY}
            /* ARCH30-T4F:domainrow-gate-primary — A4 */
            disabled={busy || !canMaintain}
            title={canMaintain ? undefined : maintainReason}
            onClick={() => onPrimary(domain.id, true)}
          >
            <Star className="h-3.5 w-3.5" aria-hidden />
            Make primary
          </button>
        ) : null}
        {domain.status !== "REVOKED" ? (
          <button
            type="button"
            className={DANGER}
            disabled={busy}
            onClick={() => onRevoke(domain.id)}
          >
            Stop serving
          </button>
        ) : null}
        <button
          type="button"
          className={DANGER}
          disabled={busy}
          onClick={() => onRelease(domain.id)}
          title="Deletes the claim. Another organization could then take this hostname."
        >
          <Trash2 className="h-3.5 w-3.5" aria-hidden />
          Release
        </button>
      </div>
    ) : (
      <p className={`${HINT} mt-3`}>
        Domain changes are restricted to the organization owner.
      </p>
    )}
  </li>
);

// ---------------------------------------------------------------------------
// Logo and favicon
// ---------------------------------------------------------------------------

const AssetTile: React.FC<{
  readonly label: string;
  readonly hint: string;
  readonly hasFile: boolean;
  readonly previewUrl: string | null;
  readonly accept: string;
  readonly canEdit: boolean;
  readonly busy: boolean;
  readonly onUpload: (file: File) => void;
  readonly onClear: () => void;
}> = ({ label, hint, hasFile, previewUrl, accept, canEdit, busy, onUpload, onClear }) => {
  const image = useImageFallback(previewUrl);
  return (
    <div className="flex items-center gap-3 rounded-xl border border-border/70 bg-muted/30 p-3">
      <span
        aria-hidden
        className="flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-lg border border-border bg-background text-muted-foreground"
      >
        {previewUrl && !image.failed ? (
          <img src={previewUrl} alt="" className="max-h-full max-w-full object-contain" onError={image.onError} />
        ) : hasFile ? (
          <CheckCircle2 className="h-5 w-5 text-emerald-600 dark:text-emerald-400" />
        ) : (
          <ImageIcon className="h-5 w-5" />
        )}
      </span>
      <div className="min-w-0 flex-1">
        <p className={LABEL}>{label}</p>
        <p className={HINT}>{hasFile ? "Uploaded" : hint}</p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          <label
            className={`${SECONDARY} h-8 px-2.5 text-xs ${canEdit ? "cursor-pointer" : "pointer-events-none opacity-50"}`}
            aria-disabled={!canEdit}
          >
            {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Upload className="h-3.5 w-3.5" aria-hidden />}
            Upload
            <input
              disabled={!canEdit}
              type="file"
              accept={accept}
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) {
                  onUpload(file);
                }
                event.target.value = "";
              }}
            />
          </label>
          {hasFile ? (
            <button type="button" className={`${DANGER} h-8 px-2.5 text-xs`} disabled={busy} onClick={onClear}>
              <Trash2 className="h-3.5 w-3.5" aria-hidden />
              Remove
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
};

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

const OrganizationBranding: React.FC = () => {
  const { organization, organizationId, organizationRole } = useResolvedOrganization();
  const queryClient = useQueryClient();
  const isOwner = String(organizationRole).toUpperCase() === "OWNER";
  // F-201. Saving the brand needs custom branding, the sender domain needs custom email (the
  // server's gates). On a plan without them every control was live and each click was a save
  // refused with 402. They stay visible and read-only; removing a logo stays possible.
  const brandingAccess = useCapabilityAccess(organizationId, CAPABILITY.customBranding);
  const senderAccess = useCapabilityAccess(organizationId, CAPABILITY.customEmail);
  const canBrand = brandingAccess.isLoading || brandingAccess.granted;
  const canSender = senderAccess.isLoading || senderAccess.granted;

  const [hostname, setHostname] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  const [senderDraft, setSenderDraft] = useState<string | null>(null);
  const [brandDraft, setBrandDraft] = useState<string | null>(null);
  const [colorDraft, setColorDraft] = useState<Partial<Record<ColorKey, string>>>(
    {},
  );

  const domainsQuery = useQuery({
    queryKey: brandingKeys.domains(organizationId),
    queryFn: () => listCustomDomains(organizationId),
  });

  // ARCH-30 Tranche 2 (D-8, D-6). The lock card replaces the section only when
  // there is nothing on file; a tenant with hostnames always sees them, so it
  // can revoke or release what it no longer pays for.
  const domainAddon = useAddonAccess(organizationId, "addon.custom_domain");
  const domainCount = domainsQuery.data?.length ?? 0;
  const showDomainLock =
    domainAddon.access?.state === "NOT_GRANTED" &&
    !domainsQuery.isLoading &&
    domainCount === 0;
  const domainCanCreate = domainAddon.access?.can_create ?? false;
  // ARCH30-T4F:domain-maintain-derivation — A4. `can_maintain` is a
  // separate server flag from `can_create` and the split is the point:
  // GRACE forbids creating new domains while still allowing the ones on
  // file to be verified, and LAPSED forbids both. Deriving one from the
  // other in the console would get GRACE wrong in one direction or the
  // other. Defaults to `true` while the entitlement query is in flight,
  // so a slow response does not flicker every control to disabled.
  const domainCanMaintain = domainAddon.access?.can_maintain ?? true;
  // ARCH30-T4F:domainrow-call-maintain — A4. Passed to every row.
  const domainMaintainReason =
    domainAddon.access?.state === "LAPSED"
      ? "Custom domains have lapsed. You can still stop serving or release a hostname; verification and certificates need the add-on restored."
      : "Custom domains are in a grace period. Verification, certificates and primary changes are paused until billing is resolved.";

  const brandingQuery = useQuery({
    queryKey: brandingKeys.branding(organizationId),
    queryFn: () => getBranding(organizationId),
  });

  const branding: TenantBrandingResponse | undefined = brandingQuery.data;
  // F-058. The preview reads the organization's own logo through the
  // authenticated console route. `logo_url` is the PUBLIC path, which answers
  // only on a verified custom domain, so on the app host it was always a 404.
  // Keyed by the file id, so a new upload is fetched fresh; no request when
  // there is no logo.
  const logoPreviewSrc = useAuthenticatedImage(
    branding?.logo_file_id
      ? `${BRANDING_ENDPOINTS.logo(organizationId)}?v=${branding.logo_file_id}`
      : null,
  );

  const colors = useMemo(() => {
    const resolved = {} as Record<ColorKey, string>;
    for (const field of COLOR_FIELDS) {
      resolved[field.key] =
        colorDraft[field.key] ?? branding?.[field.key] ?? "";
    }
    return resolved;
  }, [branding, colorDraft]);

  const brandName = brandDraft ?? branding?.brand_name ?? "";

  const refresh = () => {
    void queryClient.invalidateQueries({
      queryKey: brandingKeys.all(organizationId),
    });
  };

  const report = (message: string) => {
    setNotice(message);
    setProblem(null);
  };

  const fail = (error: unknown) => {
    setProblem(errorMessage(error));
    // An add-on refusal means the lock state we rendered is stale.
    if (addonRequiredDetail(error)) {
      void queryClient.invalidateQueries({ queryKey: entitlementKeys.all(organizationId) });
    }
    setNotice(null);
  };

  const claim = useMutation({
    mutationFn: () => claimCustomDomain(organizationId, { hostname }),
    onSuccess: (created) => {
      setHostname("");
      report(
        `${created.hostname} claimed. Publish the TXT record below, then verify.`,
      );
      refresh();
    },
    onError: fail,
  });

  const verify = useMutation({
    mutationFn: (id: string) => verifyCustomDomain(organizationId, id),
    onSuccess: (result) => {
      // resolver_failed is reported differently from a missing record. Our DNS
      // outage is not the customer's problem and must not read as one.
      report(
        result.verified
          ? `${result.hostname} is verified.`
          : result.resolver_failed
            ? "We could not reach a DNS resolver. That is on our side — try again shortly."
            : result.detail,
      );
      refresh();
    },
    onError: fail,
  });

  const reissue = useMutation({
    mutationFn: (id: string) => reissueChallenge(organizationId, id),
    onSuccess: () => {
      report("A new challenge token was issued. Update your TXT record.");
      refresh();
    },
    onError: fail,
  });

  const primary = useMutation({
    mutationFn: ({ id, next }: { id: string; next: boolean }) =>
      setPrimaryDomain(organizationId, id, next),
    onSuccess: () => {
      report("Primary hostname updated.");
      refresh();
    },
    onError: fail,
  });

  const certificate = useMutation({
    mutationFn: (id: string) => requestCertificate(organizationId, id),
    onSuccess: () => {
      report("Certificate issuance requested.");
      refresh();
    },
    onError: fail,
  });

  const revoke = useMutation({
    mutationFn: (id: string) => revokeCustomDomain(organizationId, id),
    onSuccess: () => {
      report("This hostname is no longer served. The claim is retained.");
      refresh();
    },
    onError: fail,
  });

  const release = useMutation({
    mutationFn: (id: string) => releaseCustomDomain(organizationId, id),
    onSuccess: () => {
      report("Hostname released. Another organization can now claim it.");
      refresh();
    },
    onError: fail,
  });

  const saveTokens = useMutation({
    mutationFn: (payload: TenantBrandingUpdate) =>
      updateBranding(organizationId, payload),
    onSuccess: () => {
      setBrandDraft(null);
      setColorDraft({});
      report("Branding saved.");
      refresh();
    },
    onError: fail,
  });

  const logoUpload = useMutation({
    mutationFn: (file: File) => uploadLogo(organizationId, file),
    onSuccess: () => {
      report("Logo updated.");
      refresh();
    },
    onError: fail,
  });

  const faviconUpload = useMutation({
    mutationFn: (file: File) => uploadFavicon(organizationId, file),
    onSuccess: () => {
      report("Favicon updated.");
      refresh();
    },
    onError: fail,
  });

  const logoClear = useMutation({
    mutationFn: () => clearLogo(organizationId),
    onSuccess: () => {
      report("Logo removed.");
      refresh();
    },
    onError: fail,
  });

  const faviconClear = useMutation({
    mutationFn: () => clearFavicon(organizationId),
    onSuccess: () => {
      report("Favicon removed.");
      refresh();
    },
    onError: fail,
  });

  const saveSender = useMutation({
    mutationFn: (value: string | null) =>
      setSenderDomain(organizationId, { sender_domain: value }),
    onSuccess: () => {
      setSenderDraft(null);
      report("Sender domain saved. Publish the records, then verify.");
      refresh();
    },
    onError: fail,
  });

  const checkSender = useMutation({
    mutationFn: () => verifySenderDomain(organizationId),
    onSuccess: (result) => {
      report(
        (result as any).may_send_as_tenant
          ? "Sender domain verified. Mail will now be sent from your domain."
          : ((result as any).degradation_reason ??
            "The sender domain has not verified yet."),
      );
      refresh();
    },
    onError: fail,
  });

  const busy =
    claim.isPending ||
    verify.isPending ||
    reissue.isPending ||
    primary.isPending ||
    certificate.isPending ||
    revoke.isPending ||
    release.isPending;

  const dirtyColors = COLOR_FIELDS.filter(
    (field) => colorDraft[field.key] !== undefined,
  );
  const invalidColors = dirtyColors.filter(
    (field) =>
      (colors[field.key] ?? "") !== "" && !isValidHexColor(colors[field.key]),
  );

  const applyPreset = (preset: BrandPreset) => {
    setColorDraft(
      Object.fromEntries(COLOR_FIELDS.map((field) => [field.key, preset.colours[field.key]])) as Partial<
        Record<ColorKey, string>
      >,
    );
  };

  const discardDrafts = () => {
    setBrandDraft(null);
    setColorDraft({});
  };

  // The address bar in the preview: the hostname a visitor would actually use, if there is one.
  const verifiedDomains = (domainsQuery.data ?? []).filter((domain) => domain.status === "VERIFIED");
  const previewHostname =
    (verifiedDomains.find((domain) => domain.is_primary) ?? verifiedDomains[0])?.hostname ?? "app.yourcompany.com";

  const submitTokens = () => {
    const payload: TenantBrandingUpdate = {};
    if (brandDraft !== null) {
      payload.brand_name = brandDraft.trim() === "" ? null : brandDraft.trim();
    }
    for (const field of dirtyColors) {
      const value = colors[field.key]?.trim() ?? "";
      payload[field.key] = value === "" ? null : value.toLowerCase();
    }
    saveTokens.mutate(payload);
  };

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PlanLockBanner capability={CAPABILITY.customBranding} feature="Custom branding" />
      <PageHeader
        icon={Palette}
        eyebrow={organization.organization_name}
        title="Branding & custom domains"
        description="Reach Servabo at your own hostname, show your own brand, and send notifications from your own domain."
      />

      {notice ? (
        <div role="status"
          className="flex items-start gap-2 rounded-lg border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-800 dark:text-emerald-200">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          {notice}
        </div>
      ) : null}
      {problem ? (
        <div role="alert"
          className="flex items-start gap-2 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          {problem}
        </div>
      ) : null}

      {/* ---- Custom domains ---- */}
      {showDomainLock && domainAddon.access ? (
        <AddOnLockCard
          organizationId={organizationId}
          addon={domainAddon.access}
          canPurchase={isOwner}
        />
      ) : (
      <section className={CARD}>
        <h2 className={SECTION_TITLE}>Custom domains</h2>
        {domainAddon.access && domainAddon.access.state !== "ACTIVE" ? (
          <AddOnGraceNotice
            organizationId={organizationId}
            addon={domainAddon.access}
            canPurchase={isOwner}
          />
        ) : null}
        <p className={`${HINT} mt-1`}>
          A hostname resolves to exactly one organization, so we verify you
          control the DNS zone before serving it. A certificate is only ever
          requested after that verification succeeds.
        </p>

        {/* F-060: the deployment's switch, from the branding read. Unknown
            (older server) behaves as before. */}
        {branding?.custom_domains_enabled === false ? (
          <p className="mt-4 rounded-lg border border-border/70 bg-muted/40 p-3 text-sm text-muted-foreground" role="status">
            Custom domains are not switched on for this Servabo deployment, so a hostname
            cannot be claimed here yet. Ask your platform administrator to enable custom
            domains.
          </p>
        ) : null}

        {isOwner && domainCanCreate && branding?.custom_domains_enabled !== false ? (
          <div className="mt-4 flex flex-wrap items-end gap-2">
            <div className="min-w-64 flex-1">
              <label className={LABEL} htmlFor="hostname">
                Hostname
              </label>
              <input
                id="hostname"
                className={INPUT}
                placeholder="ai.acme.com"
                value={hostname}
                onChange={(event) => setHostname(event.target.value)}
                autoComplete="off"
              />
            </div>
            <button
              type="button"
              className={PRIMARY}
              disabled={!hostname.trim() || claim.isPending}
              onClick={() => claim.mutate()}
            >
              {claim.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
              ) : (
                <Globe className="h-4 w-4" aria-hidden />
              )}
              Claim domain
            </button>
          </div>
        ) : null}

        <div className="mt-4">
          {domainsQuery.isLoading ? (
            <p className={HINT}>Loading domains…</p>
          ) : domainsQuery.data && domainsQuery.data.length > 0 ? (
            <ul className="space-y-3">
              {domainsQuery.data.map((domain) => (
                <DomainRow
                  key={domain.id}
                  domain={domain}
                  isOwner={isOwner}
                  busy={busy}
                  canMaintain={domainCanMaintain}
                  maintainReason={domainMaintainReason}
                  onVerify={(id) => verify.mutate(id)}
                  onReissue={(id) => reissue.mutate(id)}
                  onPrimary={(id, next) => primary.mutate({ id, next })}
                  onCertificate={(id) => certificate.mutate(id)}
                  onRevoke={(id) => revoke.mutate(id)}
                  onRelease={(id) => release.mutate(id)}
                />
              ))}
            </ul>
          ) : (
            <p className={HINT}>No custom domains yet.</p>
          )}
        </div>
      </section>
      )}

      {/* ---- Brand tokens ---- */}
      <section className={CARD} aria-labelledby="brand-title">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h2 id="brand-title" className={SECTION_TITLE}>Brand</h2>
            <p className={`${HINT} mt-1 max-w-2xl`}>
              Colours are six-digit hex values, chosen here with the picker or a preset. Named colours, rgb(),
              CSS variables and stylesheet fragments are not accepted — branding is a fixed set of tokens rather
              than stylesheet input, because these pages are served from an origin shared with other tenants.
            </p>
          </div>
          <span
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold ${
              branding?.is_enabled
                ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300"
                : "border-border bg-muted/50 text-muted-foreground"
            }`}
          >
            <span
              aria-hidden
              className={`h-1.5 w-1.5 rounded-full ${branding?.is_enabled ? "bg-emerald-500" : "bg-muted-foreground/60"}`}
            />
            {branding?.is_enabled ? "Live" : "Not applied"}
          </span>
        </div>
        <p className={`${HINT} mt-2 max-w-2xl`} data-testid="brand-colour-reach">
          On your verified domains, the primary colour is used for buttons, links and focus rings on the sign-in
          pages and in the app; the accent colour for the glow behind the sign-in pages; the background and text
          colours and the colour scheme for the sign-in pages. Inside the app, light or dark stays each
          person&apos;s own choice.
        </p>

        <div className="mt-6 grid gap-8 lg:grid-cols-[minmax(0,1fr)_minmax(0,26rem)]">
          <div className="min-w-0 space-y-7">
            {/* Identity */}
            <div className="grid gap-5 sm:grid-cols-2">
              <div className="sm:col-span-2">
                <label className={LABEL} htmlFor="brand-name">
                  Brand name
                </label>
                <input
                  id="brand-name"
                  className={INPUT}
                  value={brandName}
                  maxLength={120}
                  onChange={(event) => setBrandDraft(event.target.value)}
                  placeholder="Acme Inc."
                  disabled={!canBrand}
                />
                <p className={`${HINT} mt-1`}>
                  Ampersands and apostrophes are fine. Angle brackets, double quotes and backslashes are not.
                </p>
              </div>

              <AssetTile
                label="Logo"
                hint="PNG, JPEG or WebP"
                hasFile={Boolean(branding?.logo_file_id)}
                previewUrl={logoPreviewSrc}
                accept="image/png,image/jpeg,image/webp"
                canEdit={canBrand}
                busy={logoUpload.isPending || logoClear.isPending}
                onUpload={(file) => logoUpload.mutate(file)}
                onClear={() => logoClear.mutate()}
              />
              <AssetTile
                label="Favicon"
                hint="PNG, ICO or WebP"
                hasFile={Boolean(branding?.favicon_file_id)}
                previewUrl={null}
                accept="image/png,image/x-icon,image/webp"
                canEdit={canBrand}
                busy={faviconUpload.isPending || faviconClear.isPending}
                onUpload={(file) => faviconUpload.mutate(file)}
                onClear={() => faviconClear.mutate()}
              />
            </div>

            {/* Colours */}
            <div className="space-y-4">
              <div className="flex flex-wrap items-end justify-between gap-2">
                <h3 className="text-sm font-semibold text-foreground">Colours</h3>
                <p className={HINT}>Start from a preset, then adjust any colour.</p>
              </div>
              <div className="grid grid-cols-2 gap-2 sm:grid-cols-3" role="group" aria-label="Colour presets">
                {BRAND_PRESETS.map((preset) => {
                  const active = COLOR_FIELDS.every(
                    (field) => colors[field.key].trim().toLowerCase() === preset.colours[field.key],
                  );
                  return (
                    <button
                      key={preset.id}
                      type="button"
                      disabled={!canBrand}
                      aria-pressed={active}
                      aria-label={`Apply ${preset.name} preset`}
                      onClick={() => applyPreset(preset)}
                      className={`flex items-center gap-2.5 rounded-lg border px-2.5 py-2 text-left text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 ${
                        active ? "border-primary bg-primary/5" : "border-border bg-card hover:bg-muted/60"
                      }`}
                    >
                      <span aria-hidden className="flex -space-x-1">
                        {COLOR_FIELDS.map((field) => (
                          <span
                            key={field.key}
                            className="h-4 w-4 rounded-full border border-card"
                            style={{ backgroundColor: preset.colours[field.key] }}
                          />
                        ))}
                      </span>
                      {preset.name}
                    </button>
                  );
                })}
              </div>

              <div className="grid gap-6 sm:grid-cols-2">
                {COLOR_FIELDS.map((field) => (
                  <ColorField
                    key={field.key}
                    id={`color-${field.key}`}
                    label={field.label}
                    help={field.help}
                    value={colors[field.key] ?? ""}
                    disabled={!canBrand}
                    onChange={(next) => setColorDraft((current) => ({ ...current, [field.key]: next }))}
                  />
                ))}
              </div>
            </div>

            {/* Colour scheme: applies as soon as it is pressed, as before. */}
            <div>
              <span className={LABEL} id="scheme-label">Colour scheme</span>
              <p className={HINT}>How the sign-in pages look. Applies as soon as you choose.</p>
              <div
                role="group"
                aria-labelledby="scheme-label"
                className="mt-2 inline-flex rounded-lg bg-muted/70 p-0.5"
              >
                {SCHEMES.map((scheme) => {
                  const Icon = SCHEME_ICONS[scheme];
                  const selected = branding?.color_scheme === scheme;
                  return (
                    <button
                      key={scheme}
                      type="button"
                      aria-pressed={selected}
                      className={`inline-flex h-8 items-center gap-1.5 rounded-md px-3 text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 ${
                        selected ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                      }`}
                      disabled={!canBrand || saveTokens.isPending}
                      onClick={() => saveTokens.mutate({ color_scheme: scheme })}
                    >
                      <Icon className="h-3.5 w-3.5" aria-hidden />
                      {scheme.charAt(0) + scheme.slice(1).toLowerCase()}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="border-t border-border/60 pt-5">
              <div className="flex flex-wrap items-center gap-2">
                <button
                  type="button"
                  className={PRIMARY}
                  disabled={
                    !canBrand ||
                    saveTokens.isPending ||
                    invalidColors.length > 0 ||
                    (brandDraft === null && dirtyColors.length === 0)
                  }
                  onClick={submitTokens}
                >
                  {saveTokens.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
                  Save brand
                </button>
                {brandDraft !== null || dirtyColors.length > 0 ? (
                  <button type="button" className={GHOST} disabled={saveTokens.isPending} onClick={discardDrafts}>
                    <Undo2 className="h-3.5 w-3.5" aria-hidden />
                    Discard changes
                  </button>
                ) : null}
                <button
                  type="button"
                  className={`${SECONDARY} sm:ml-auto`}
                  disabled={!canBrand || saveTokens.isPending}
                  onClick={() => saveTokens.mutate({ is_enabled: !branding?.is_enabled })}
                >
                  {branding?.is_enabled ? "Disable custom branding" : "Enable custom branding"}
                </button>
              </div>
              <p className={`${HINT} mt-2`}>
                {!canBrand
                  ? "Custom branding is included on higher plans. What is on file stays; you can still remove a logo or favicon."
                  : branding?.is_enabled
                    ? "Custom branding is live on your verified domains."
                    : "Saved but not applied. Nothing a visitor sees changes until you enable it."}
              </p>
            </div>
          </div>

          <div className="min-w-0">
            <div className="lg:sticky lg:top-20">
              <div className="mb-2 flex items-center justify-between gap-2">
                <span className={LABEL}>Live preview</span>
                <span className={HINT}>Updates as you edit</span>
              </div>
              <BrandPreview
                colours={colors}
                scheme={branding?.color_scheme ?? "SYSTEM"}
                brandName={brandName}
                logoUrl={logoPreviewSrc}
                hostname={previewHostname}
              />
            </div>
          </div>
        </div>
      </section>

      {/* ---- Sender domain ---- */}
      <section className={CARD}>
        <h2 className={SECTION_TITLE}>Notification sender domain</h2>
        <p className={`${HINT} mt-1`}>
          Send notifications from your own domain. Until SPF and DKIM verify,
          mail goes out from the Servabo platform address.
        </p>

        {branding?.sender.degradation_reason ? (
          /*
           * The server's sentence, rendered verbatim. ARCH-25 invariant 5
           * requires a lapsed sender domain to degrade visibly, and putting
           * this copy in a local switch over sender_domain_status is how it
           * eventually goes quiet again.
           */
          <p className="mt-3 flex items-start gap-2 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-sm text-amber-900 dark:text-amber-200">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            {branding.sender.degradation_reason}
          </p>
        ) : null}

        <div className="mt-4 flex flex-wrap items-end gap-2">
          <div className="min-w-64 flex-1">
            <label className={LABEL} htmlFor="sender-domain">
              Sender domain
            </label>
            <input
              id="sender-domain"
              className={INPUT}
              placeholder="mail.acme.com"
              value={senderDraft ?? branding?.sender.sender_domain ?? ""}
              onChange={(event) => setSenderDraft(event.target.value)}
              disabled={!canSender}
            />
          </div>
          <button
            type="button"
            className={PRIMARY}
            disabled={!canSender || saveSender.isPending}
            onClick={() =>
              saveSender.mutate(
                (senderDraft ?? "").trim() === ""
                  ? null
                  : (senderDraft ?? "").trim(),
              )
            }
          >
            Save
          </button>
          <button
            type="button"
            className={SECONDARY}
            disabled={
              !canSender || checkSender.isPending || !branding?.sender.sender_domain
            }
            onClick={() => checkSender.mutate()}
          >
            <RefreshCw className="h-3.5 w-3.5" aria-hidden />
            Check records
          </button>
          <span className={HINT}>
            {SENDER_STATUS_LABELS[
              branding?.sender.sender_domain_status ?? "UNSET"
            ]}
            {branding?.sender.sender_domain_checked_at
              ? ` · checked ${formatDateTime(branding.sender.sender_domain_checked_at)}`
              : ""}
          </span>
        </div>

        {branding && branding.sender.required_records.length > 0 ? (
          <ul className="mt-4 space-y-2">
            {branding.sender.required_records.map((record) => (
              <li
                key={record.purpose}
                className="rounded-lg border border-border/70 bg-muted/20 p-3 text-sm"
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{record.purpose}</span>
                  <span className={HINT}>
                    {record.present ? "Found" : "Not found"}
                  </span>
                </div>
                <p className="mt-1 font-mono text-xs break-all">
                  {record.record_name}
                </p>
                <div className="mt-1 flex flex-wrap items-center gap-2">
                  <p className="font-mono text-xs break-all">
                    {record.record_value}
                  </p>
                  <CopyButton
                    value={record.record_value}
                    label={`${record.purpose} value`}
                  />
                </div>
              </li>
            ))}
          </ul>
        ) : null}
      </section>
    </div>
  );
};

export default OrganizationBranding;
