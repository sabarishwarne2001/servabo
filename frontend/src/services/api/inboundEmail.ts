/** Email-in's settings API (Final session 1, 2B). Workspace admins only. */
import apiClient from "@/services/api/client";

export interface InboundSender {
  readonly id: string;
  readonly pattern: string;
  readonly created_at: string;
}

export interface InboundAttachment {
  readonly name: string;
  readonly size?: number;
  readonly outcome: string;
  readonly note?: string;
  readonly work_item_id?: string;
  readonly batch_id?: string;
}

export interface InboundMessageView {
  readonly id: string;
  readonly from_address: string;
  readonly from_name: string | null;
  readonly subject: string | null;
  readonly received_at: string | null;
  readonly status: "ACCEPTED" | "HELD" | "DISCARDED";
  readonly hold_code: string | null;
  readonly hold_message: string | null;
  readonly can_approve: boolean;
  readonly documents: number;
  readonly attachments: readonly InboundAttachment[];
}

export interface InboundEmailView {
  readonly enabled: boolean;
  readonly address: string | null;
  readonly form: "domain" | "postmark" | null;
  readonly senders: readonly InboundSender[];
  readonly messages: readonly InboundMessageView[];
  readonly held_count: number;
}

const base = (workspaceId: string): string => `/workspaces/${encodeURIComponent(workspaceId)}/inbound-email`;

export const inboundEmailKeys = {
  all: (workspaceId: string) => ["ws", workspaceId, "inbound-email"] as const,
};

export const getInboundEmail = async (workspaceId: string): Promise<InboundEmailView> =>
  (await apiClient.get<InboundEmailView>(base(workspaceId))).data;

export const rotateInboundAddress = async (workspaceId: string): Promise<InboundEmailView> =>
  (await apiClient.post<InboundEmailView>(`${base(workspaceId)}/rotate`)).data;

export const addInboundSender = async (workspaceId: string, pattern: string): Promise<InboundEmailView> =>
  (await apiClient.post<InboundEmailView>(`${base(workspaceId)}/senders`, { pattern })).data;

export const removeInboundSender = async (workspaceId: string, senderId: string): Promise<void> => {
  await apiClient.delete(`${base(workspaceId)}/senders/${encodeURIComponent(senderId)}`);
};

export interface ApproveResult {
  readonly result: "accepted" | "held";
  readonly documents: number;
  readonly message: InboundMessageView;
}

export const approveInboundMessage = async (workspaceId: string, messageId: string): Promise<ApproveResult> =>
  (await apiClient.post<ApproveResult>(`${base(workspaceId)}/messages/${encodeURIComponent(messageId)}/approve`)).data;

export const discardInboundMessage = async (workspaceId: string, messageId: string): Promise<void> => {
  await apiClient.post(`${base(workspaceId)}/messages/${encodeURIComponent(messageId)}/discard`);
};
