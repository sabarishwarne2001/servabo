import React, { useCallback, useEffect, useRef, useState } from "react";

import { Sparkles } from "lucide-react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { assistantKeys } from "@/services/api/queryKeys";
import { assistantApi } from "@/services/api/assistant";
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
  const queryClient = useQueryClient();
  const drafts = useRef<Record<string, string>>({});
  const workspace = useActiveWorkspace();
  const { workspaceRole } = useResolvedTenant();
  const conversationsWidth = useSidebarWidth(ASSISTANT_SIDEBAR);
  const workspaceId = workspace?.workspaceId ?? "";
  const activeWorkspace = useRef(workspaceId);
  activeWorkspace.current = workspaceId;
  const canWrite = isAtLeast(workspaceRole, "CONTRIBUTOR");

  const [session, setSession] = useState<ConversationSession | null>(null);
  const [draft, setDraft] = useState<Draft | null>(null);

  useEffect(() => {
    setSession(null);
    setDraft(null);
    drafts.current = {};
  }, [workspaceId]);

  const start = useMutation({
    mutationFn: (prompt: string) => assistantApi.createConversation(workspaceId).then((created) => ({ created, prompt, startedWorkspace: workspaceId })),
    onSuccess: ({ created, prompt, startedWorkspace }) => {
      if (startedWorkspace !== activeWorkspace.current) {return;}
      setSession({ id: created.id, title: created.title, kind: "workspace", scope_mode: "WORKSPACE", work_item_id: null, document_title: null, scope_document_count: 0, model_override: null, pinned: false, archived: false, message_count: 0, created_at: created.created_at, last_message_at: null });
      setDraft({ text: prompt, nonce: Date.now() });
      void queryClient.invalidateQueries({ queryKey: assistantKeys.sessionsRoot(workspaceId) });
    },
    onError: () => toast.error("The conversation could not be created. Please try again."),
  });

  const select = useCallback((next: ConversationSession | null) => {
    if (next?.id !== session?.id) {setDraft(null);}
    setSession((current) => {
      if (current === next) {
        return current;
      }
      if (current && next && current.id === next.id && JSON.stringify(current) === JSON.stringify(next)) {
        return current;
      }
      return next;
    });
  }, [session?.id]);

  const insertTemplate = useCallback((text: string) => {
    setDraft({ text, nonce: Date.now() });
  }, []);

  if (!workspaceId) {
    return null;
  }

  return (
    <div className="intelligence-page assistant-page flex h-full min-w-0 flex-col space-y-4">
      <header className="intelligence-header flex shrink-0 items-center gap-4">
        <span className="intelligence-mark" aria-hidden="true"><Sparkles /></span><div className="space-y-1">
        <h1 className="text-2xl font-semibold tracking-tight sm:text-3xl">AI Assistant</h1>
        <p className="text-xs text-muted-foreground sm:text-sm">
          Ask across the whole workspace, a chosen set of documents, or one document — every
          answer cites the passages it used.
        </p>
      </div></header>

      <section
        className="flex min-h-0 flex-1 flex-col gap-3 sm:gap-4 lg:grid lg:h-[calc(100vh-13rem)] lg:grid-rows-[minmax(0,1fr)] lg:grid-cols-[var(--conversations-side)_minmax(0,1fr)]"
        style={{ "--conversations-side": `${conversationsWidth}px` } as React.CSSProperties}
      >
        <div className="relative min-h-0 max-h-72 shrink-0 lg:h-full lg:max-h-none">
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

        <div className="assistant-workbench flex min-h-[480px] min-w-0 flex-1 flex-col lg:h-full lg:min-h-0">
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
              key={`${workspaceId}:${session?.id ?? "welcome"}`}
              mode="global"
              initialText={session ? drafts.current[session.id] ?? "" : ""}
              onDraftChange={(text) => { if (session) {drafts.current[session.id] = text;} }}
              onStart={(prompt) => start.mutate(prompt)}
              isStarting={start.isPending}
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
