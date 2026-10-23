import React, { useCallback, useEffect, useState } from "react";

import ChatSessionBar from "@/components/assistant/ChatSessionBar";
import ConversationSidebar from "@/components/assistant/ConversationSidebar";
import { ChatPanel } from "@/components/assistant/ChatPanel";
import { useActiveWorkspace } from "@/hooks/useActiveWorkspace";
import { isAtLeast } from "@/permissions/workspacePermissions";
import { useResolvedTenant } from "@/routes/TenantContext";
import { SidebarResizeHandle } from "@/components/layout/SidebarResizeHandle";
import { ASSISTANT_SIDEBAR, useSidebarWidth } from "@/components/layout/sidebarWidth";
import type { ConversationSession } from "@/types/assistantSuite";

interface Draft {
  readonly text: string;
  readonly nonce: number;
}

/**
 * ARCH39-S1:assistant-page — the workspace AI Assistant.
 *
 * What ARCH-39 changed on this page
 * =================================
 *
 * The sidebar lists sessions from `GET /assistant/sessions` (summaries) rather
 * than `GET /assistant/conversations`, which returned every message of every
 * conversation. Workspace and document conversations are labelled and
 * filterable; conversations can be searched, pinned, archived and exported.
 *
 * Above the chat, the session bar shows what the conversation searches (the
 * whole workspace, selected documents, or — for a document conversation —
 * only that document), lets the user choose a model the workspace's provider
 * offers, and inserts organization prompt templates into the composer.
 */
export const Assistant: React.FC = () => {
  const workspace = useActiveWorkspace();
  const { workspaceRole } = useResolvedTenant();
  const conversationsWidth = useSidebarWidth(ASSISTANT_SIDEBAR);
  const workspaceId = workspace?.workspaceId ?? "";
  const canWrite = isAtLeast(workspaceRole, "CONTRIBUTOR");

  const [session, setSession] = useState<ConversationSession | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);

  useEffect(() => {
    setSession(null);
    setDraft(null);
  }, [workspaceId]);

  const select = useCallback((next: ConversationSession | null) => {
    setSession((current) => {
      if (current === next) {
        return current;
      }
      if (current && next && current.id === next.id && JSON.stringify(current) === JSON.stringify(next)) {
        return current;
      }
      return next;
    });
  }, []);

  const insertTemplate = useCallback((text: string) => {
    setDraft({ text, nonce: Date.now() });
  }, []);

  if (!workspaceId) {
    return null;
  }

  return (
    <div className="flex h-full flex-col space-y-3">
      <header className="shrink-0 space-y-0.5">
        <h1 className="text-xl font-semibold tracking-tight sm:text-2xl">AI Assistant</h1>
        <p className="text-xs text-muted-foreground sm:text-sm">
          Ask across the whole workspace, a chosen set of documents, or one document — every
          answer cites the passages it used.
        </p>
      </header>

      <section
        className="flex min-h-0 flex-1 flex-col gap-3 sm:gap-4 lg:grid lg:h-[calc(100vh-13rem)] lg:grid-cols-[var(--conversations-side)_minmax(0,1fr)]"
        style={{ "--conversations-side": `${conversationsWidth}px` } as React.CSSProperties}
      >
        <div className="relative max-h-72 shrink-0 lg:h-full lg:max-h-none">
          <ConversationSidebar
            workspaceId={workspaceId}
            selectedId={session?.id ?? null}
            onSelect={select}
            canWrite={canWrite}
          />
          {/* On a computer the list's width is the person's own: drag the divider between the list and the chat. */}
          <SidebarResizeHandle
            spec={ASSISTANT_SIDEBAR}
            label="Resize the conversation list"
            viewportShare={0.5}
            className="hidden !right-[-10px] !translate-x-0 lg:block"
          />
        </div>

        <div className="flex min-h-[480px] flex-1 flex-col lg:h-full lg:min-h-0">
          {session && (
            <ChatSessionBar
              workspaceId={workspaceId}
              session={session}
              canWriteTemplates={canWrite}
              onInsertTemplate={insertTemplate}
            />
          )}
          <div className="relative min-h-0 w-full flex-1">
            <ChatPanel
              mode="global"
              {...(session ? { conversationId: session.id } : {})}
              {...(draft ? { draft } : {})}
              readOnly={!canWrite}
              className="h-full w-full shadow-sm"
            />
          </div>
        </div>
      </section>
    </div>
  );
};

Assistant.displayName = "Assistant";
export default React.memo(Assistant);
