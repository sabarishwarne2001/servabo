import { useAuthenticatedImage } from "@/hooks/useAuthenticatedImage";
import { useImageFallback } from "@/hooks/useImageFallback";
import { ServaboMark } from "@/components/branding/ServaboMark";

interface WorkspaceLogoProps {
  workspace: {
    id: string;
    workspace_name: string;
    company_logo_url?: string | null;
  };
  /** Size and shape. Used for the workspace's own logo and for the Servabo logo shown in its place. */
  className?: string;
}

/**
 * A workspace's logo. A workspace that has not uploaded one (every new workspace), or whose logo cannot be
 * loaded, shows the Servabo logo instead, so there is never an empty or initials-only badge.
 */
export function WorkspaceLogo({ workspace, className = "h-8 w-8 rounded object-cover" }: WorkspaceLogoProps) {
  const src = useAuthenticatedImage(workspace.company_logo_url ?? null);
  const { failed: loadError, onError } = useImageFallback(src);

  if (!src || loadError) {
    return <ServaboMark className={className} title={`${workspace.workspace_name} (Servabo logo)`} />;
  }

  return <img src={src} alt={`${workspace.workspace_name} logo`} className={className} onError={onError} />;
}

export default WorkspaceLogo;
