import { FileText, ListChecks, Scale, ShieldCheck, Sparkles } from "lucide-react";

const STARTERS = [
  {
    title: "Summarize documents",
    detail: "A concise overview of the key points",
    prompt:
      "Summarize the key points in the documents in this conversation’s scope, citing your sources.",
    Icon: FileText,
  },
  {
    title: "Extract key information",
    detail: "Find the details that matter",
    prompt:
      "Extract the key names, dates, amounts, and obligations from the documents in scope. Cite the source for each.",
    Icon: ListChecks,
  },
  {
    title: "Compare documents",
    detail: "Explore differences and similarities",
    prompt:
      "Compare the documents in scope. Highlight meaningful differences and similarities, with citations. If there are not enough documents, say so.",
    Icon: Scale,
  },
  {
    title: "Ask about compliance",
    detail: "Understand policies, terms, and obligations",
    prompt:
      "Identify the policies, terms, and obligations stated in the documents in scope. Cite supporting passages and explain any gaps in the evidence.",
    Icon: ShieldCheck,
  },
] as const;

export default function AssistantWelcome({
  onPrompt,
  disabled = false,
  readOnly = false,
}: {
  readonly onPrompt: (prompt: string) => void;
  readonly disabled?: boolean;
  readonly readOnly?: boolean;
}) {
  return (
    <div className="assistant-welcome">
      <div className="assistant-orb" aria-hidden="true">
        <Sparkles />
      </div>
      <h2 className="text-xl font-semibold tracking-tight sm:text-2xl">
        Ask anything about <span>your documents</span>
      </h2>
      <p className="mt-2 max-w-lg text-sm leading-6 text-muted-foreground">
        {readOnly
          ? "Select a conversation to read it. Asking the assistant needs contributor access."
          : "Explore your documents, extract information, and uncover insights — with citations to the sources."}
      </p>
      {!readOnly && (
        <div className="assistant-starters">
          {STARTERS.map(({ title, detail, prompt, Icon }) => (
            <button
              type="button"
              key={title}
              disabled={disabled}
              onClick={() => onPrompt(prompt)}
              className="assistant-starter"
            >
              <span className="assistant-starter-icon">
                <Icon className="h-5 w-5" aria-hidden="true" />
              </span>
              <span>
                <strong className="block text-xs font-semibold sm:text-sm">{title}</strong>
                <span className="mt-1 block text-xs text-muted-foreground">{detail}</span>
              </span>
            </button>
          ))}
        </div>
      )}
      <p className="mt-5 text-[11px] text-muted-foreground">
        Answers are grounded in the conversation’s document scope. Verify important details against
        the sources.
      </p>
    </div>
  );
}
