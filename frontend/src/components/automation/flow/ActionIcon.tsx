/**
 * Session J — the drawing for an action. The catalog names a word per action (`mail`, `tag`, `shield`); actions that
 * predate the word are drawn from their type. An action nobody has drawn gets the lightning bolt, never a blank.
 */

import React from "react";
import {
  Bell,
  BookUp,
  CalendarCheck,
  ClipboardCheck,
  Database,
  EyeOff,
  FileUp,
  Gauge,
  Mail,
  MessageSquare,
  PenLine,
  Shield,
  Tag,
  UserCheck,
  Webhook,
  Zap,
  type LucideIcon,
} from "lucide-react";

const BY_WORD: Readonly<Record<string, LucideIcon>> = {
  "calendar-check": CalendarCheck,
  "file-up": FileUp,
  mail: Mail,
  "message-square": MessageSquare,
  shield: Shield,
  tag: Tag,
  "user-check": UserCheck,
  zap: Zap,
};

const BY_TYPE: Readonly<Record<string, LucideIcon>> = {
  "webhook.send": Webhook,
  "redaction.start": EyeOff,
  "review.escalate": ClipboardCheck,
  "warehouse.export": Database,
  "notify.role": Bell,
  "autonomy.decide": Gauge,
  "email.send": Mail,
  "work_item.mutate": PenLine,
  "erp.post": BookUp,
};

export const iconFor = (actionType: string, word: string | undefined): LucideIcon => {
  const typed = BY_TYPE[actionType];
  if (typed) {return typed;}
  if (word && word !== "zap") {return BY_WORD[word] ?? Zap;}
  return Zap;
};

export const ActionIcon: React.FC<{ readonly actionType: string; readonly word?: string | undefined; readonly className?: string }> = ({
  actionType, word, className = "h-3.5 w-3.5",
}) => {
  const Icon = iconFor(actionType, word);
  return <Icon className={className} aria-hidden="true" />;
};
