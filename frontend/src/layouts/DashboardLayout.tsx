import React, { useCallback } from "react";
import { Outlet, useNavigate } from "react-router-dom";
import { authApi } from "@/services/api/auth";
import { useAuthStore } from "@/store/useAuthStore";
import { useUIStore } from "@/store/useUIStore";
import { ROUTES } from "@/constants/routes";
import DesktopSidebar from "@/components/layout/DesktopSidebar";
import { SidebarResizeHandle } from "@/components/layout/SidebarResizeHandle";
import { SHELL_SIDEBAR, useSidebarWidth } from "@/components/layout/sidebarWidth";
import Sidebar from "@/components/layout/Sidebar";
import { Header } from "@/components/layout/Header";
import { VerificationBanner } from "@/components/common/VerificationBanner";
import IncomingOwnershipBanner from "@/components/organization/IncomingOwnershipBanner";
import PendingInvitationsBanner from "@/components/invitations/PendingInvitationsBanner";
import DunningBanner from "@/components/billing/DunningBanner";
// ARCH30-T4F:ts-member-notice-import-dash — A5.
import MemberAccessNotice from "@/components/billing/MemberAccessNotice";
import TrialBanner from "@/components/billing/TrialBanner";
import { canSeeValueReceipt } from "@/components/billing/ValueReceipt";
import { DisplayPreferencesBoundary } from "@/components/common/DisplayPreferencesBoundary";
import { RouteErrorBoundary } from "@/components/common/RouteErrorBoundary";
import { useTenant } from "@/hooks/useTenant";
// ARCH30-T4:ts-mount-tz-import — A3. Mounted on the layout every
// authenticated route renders, because login is not the only way a
// session begins.
import { useTimezoneCapture } from "@/hooks/useTimezoneCapture";
// ARCH36-S1:command-palette-mount — Ctrl+K / ⌘K. Mounted here because this
// layout only renders beneath TenantGuard, and the palette builds tenant paths.
import UploadTray from "@/components/upload/UploadTray";
import CommandPalette from "@/components/layout/CommandPalette";

export const DashboardLayout: React.FC = () => {
  const navigate = useNavigate();

  // ARCH30-T4:ts-mount-tz-call — A3. No-op after the first session
  // in which a timezone gets set; see the hook for why it never
  // overwrites a chosen one.
  useTimezoneCapture();

  const clearAuth = useAuthStore((state) => state.clearAuth);
  const beginSignOut = useAuthStore((state) => state.beginSignOut);
  const isSidebarCollapsed = useUIStore((state) => state.isSidebarCollapsed);
  const sidebarWidth = useSidebarWidth(SHELL_SIDEBAR);
  const { state: tenantState } = useTenant();
  const billingOrganizationId =
    tenantState.status === "ready" &&
    ["OWNER", "ADMIN", "BILLING"].includes(String(tenantState.organizationRole).toUpperCase())
      ? tenantState.organization.organization_id
      : null;

  const handleLogout = useCallback(async (): Promise<void> => {
    // ARCH-29 Tranche 1. Set BEFORE the await, not after.
    //
    // `logoutRequest()` revokes the session server-side. Any authenticated
    // request still in flight during that await 401s, the interceptor clears
    // local state, and the guard above this layout re-renders while still
    // mounted at the current deep path — emitting its own redirect to
    // `/login?redirect=<deep path>` before either line below executes. That
    // guard redirect, not this handler, is what put the user back into their
    // settings tab after signing out. Raising the flag first means the guard
    // already knows the exit was deliberate when the race opens.
    beginSignOut();
    try {
      await authApi.logoutRequest();
    } finally {
      // `finally`, because a network failure on the way out must still end the
      // session locally. F-206: `leaving` keeps `isSigningOut` raised until the
      // sign-in screen mounts and lowers it (AuthLayout), so the page being left
      // sends nothing and the guard does not read the exit as an expiry. It is
      // never left raised: the sign-in screen, or any new session, lowers it,
      // so the NEXT involuntary expiry still keeps its destination.
      clearAuth({ leaving: true });
      navigate(ROUTES.LOGIN, { replace: true });
    }
  }, [beginSignOut, clearAuth, navigate]);

  return (
    <div className="flex h-screen w-full overflow-hidden bg-background text-foreground transition-colors duration-200">
      {/* The width is the person's own (drag the divider; it is remembered). A collapsed sidebar is the fixed icon rail. */}
      <div
        className="relative z-20 hidden h-screen shrink-0 transition-[width] duration-200 ease-out-expo lg:block"
        style={{ width: isSidebarCollapsed ? 68 : sidebarWidth, maxWidth: "50vw" }}
      >
        <DesktopSidebar onLogout={handleLogout} />
        {isSidebarCollapsed ? null : <SidebarResizeHandle spec={SHELL_SIDEBAR} label="Resize the sidebar" />}
      </div>

      <Sidebar onLogout={handleLogout} />
      <CommandPalette />
      {/* ARCH38-S2:upload-tray. Mounted on the shell, not a page: the tray has
          to survive navigation, and a page-owned tray dies at the first route
          change while its uploads are still running. */}
      <UploadTray />

      <div className="fp-canvas flex min-w-0 flex-1 flex-col h-screen overflow-hidden">
        <Header />
        <IncomingOwnershipBanner />
        <PendingInvitationsBanner />
        <VerificationBanner />
        {billingOrganizationId ? (
          <DunningBanner organizationId={billingOrganizationId} canManageBilling />
        ) : tenantState.status === "ready" ? (
          <MemberAccessNotice organizationId={tenantState.organization.organization_id} />
        ) : null}
        {tenantState.status === "ready" ? (
          <TrialBanner
            organizationId={tenantState.organization.organization_id}
            organizationSlug={tenantState.organization.organization_slug}
            canChoosePlan={String(tenantState.organizationRole).toUpperCase() === "OWNER"}
            canSeeReceipt={canSeeValueReceipt(String(tenantState.organizationRole))}
          />
        ) : null}

        <main className="flex-1 overflow-y-auto bg-transparent p-3 sm:p-5 md:px-8 md:py-7">
          <DisplayPreferencesBoundary>
            <RouteErrorBoundary>
              <Outlet />
            </RouteErrorBoundary>
          </DisplayPreferencesBoundary>
        </main>
      </div>
    </div>
  );
};

export default DashboardLayout;
