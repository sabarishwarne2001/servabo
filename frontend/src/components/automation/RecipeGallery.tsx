/**
 * Session J — the recipe gallery: ready-made rules for a person who does not want to start from a blank page.
 *
 * Search and filter by what the recipe is about; choose one, answer the one or two things only they know (a Slack channel,
 * who to email), and the builder opens with the rule filled in so they can adjust it in plain words.
 */

import React, { useMemo, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Loader2, Lock, Search, Sparkles, X } from "lucide-react";

import { applyFillIns } from "@/components/automation/flow/flowModel";
import { inputClass } from "@/components/automation/flow/StepCard";
import { automationApi } from "@/services/api/automation";
import { automationKeys } from "@/services/api/queryKeys";
import type { AutomationRuleCreateRequest } from "@/types/automation";
import type { FlowCatalog } from "@/types/automationFlow";
import type { Recipe, RecipeFillIn } from "@/types/automationVolume";

interface RecipeGalleryProps {
  readonly open: boolean;
  readonly workspaceId: string;
  readonly catalog: FlowCatalog | undefined;
  readonly onClose: () => void;
  readonly onUse: (rule: AutomationRuleCreateRequest) => void;
  /** A locked recipe opens the upgrade dialog, which names the capability it needs. */
  readonly onUpgrade: (capability: string, feature: string) => void;
}

export const matchesRecipe = (recipe: Recipe, query: string, category: string): boolean => {
  if (category !== "All" && recipe.category !== category) {return false;}
  const needle = query.trim().toLowerCase();
  if (!needle) {return true;}
  return [recipe.title, recipe.summary, recipe.category, ...recipe.trigger_labels].some((text) => text.toLowerCase().includes(needle));
};

const FillInField: React.FC<{
  readonly fill: RecipeFillIn;
  readonly catalog: FlowCatalog | undefined;
  readonly value: string;
  readonly onChange: (value: string) => void;
}> = ({ fill, catalog, value, onChange }) => {
  const id = `recipe-fill-${fill.path}`;
  const chat = catalog?.resources.chat_endpoints ?? [];
  const members = catalog?.resources.members ?? [];
  return (
    <div>
      <label htmlFor={id} className="mb-1 block text-xs font-semibold">{fill.label}</label>
      {fill.kind === "chat_endpoint" ? (
        <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className={inputClass(false)}>
          <option value="">{chat.length ? "Choose a channel…" : "No Slack or Teams channel yet"}</option>
          {chat.map((endpoint) => (
            <option key={endpoint.id} value={endpoint.id}>
              {endpoint.kind === "SLACK" ? "Slack" : "Microsoft Teams"} · {endpoint.label}
            </option>
          ))}
        </select>
      ) : fill.kind === "member_email" ? (
        <select id={id} value={value} onChange={(e) => onChange(e.target.value)} className={inputClass(false)}>
          <option value="">Choose a person…</option>
          {members.map((member) => (
            <option key={member.email} value={member.email}>{member.name === member.email ? member.email : `${member.name} (${member.email})`}</option>
          ))}
        </select>
      ) : (
        <input id={id} type="email" value={value} placeholder="name@company.com" onChange={(e) => onChange(e.target.value)} className={inputClass(false)} />
      )}
      <p className="mt-1 text-[11px] text-muted-foreground">{fill.hint}</p>
    </div>
  );
};

export const RecipeGallery: React.FC<RecipeGalleryProps> = ({ open, workspaceId, catalog, onClose, onUse, onUpgrade }) => {
  const [query, setQuery] = useState("");
  const [category, setCategory] = useState("All");
  const [chosen, setChosen] = useState<Recipe | null>(null);
  const [answers, setAnswers] = useState<Readonly<Record<string, string>>>({});

  const recipesQuery = useQuery({
    queryKey: automationKeys.recipes(workspaceId),
    queryFn: () => automationApi.getRecipes(workspaceId),
    enabled: open && Boolean(workspaceId),
    staleTime: 5 * 60_000,
  });
  const list = recipesQuery.data;

  const shown = useMemo(
    () => (list?.recipes ?? []).filter((recipe) => matchesRecipe(recipe, query, category)),
    [list, query, category],
  );

  if (!open) {return null;}

  const close = (): void => {
    setChosen(null);
    setAnswers({});
    onClose();
  };
  const use = (recipe: Recipe, given: Readonly<Record<string, string>>): void => {
    onUse(applyFillIns(recipe.rule, given));
    setChosen(null);
    setAnswers({});
  };
  const missing = chosen ? chosen.fill_ins.filter((fill) => !(answers[fill.path] ?? "").trim()) : [];

  return createPortal(
    <div
      className="fixed inset-0 z-[60] flex items-stretch justify-center bg-black/40 p-0 backdrop-blur-sm sm:p-6"
      role="dialog"
      aria-modal="true"
      aria-labelledby="recipe-gallery-title"
      onKeyDown={(event) => {
        if (event.key === "Escape") {
          event.stopPropagation();
          if (chosen) {setChosen(null);} else {close();}
        }
      }}
    >
      <div className="flex w-full max-w-5xl flex-col overflow-hidden border border-border bg-background shadow-2xl sm:rounded-xl">
        <header className="flex items-center justify-between gap-3 border-b border-border bg-card px-5 py-3">
          <div className="flex items-center gap-2">
            {chosen && (
              <button type="button" onClick={() => setChosen(null)} className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted" aria-label="Back to all recipes">
                <ArrowLeft className="h-4 w-4" />
              </button>
            )}
            <Sparkles className="h-4 w-4 text-primary" aria-hidden="true" />
            <h2 id="recipe-gallery-title" className="text-sm font-semibold uppercase tracking-wider">
              {chosen ? chosen.title : "Start from a recipe"}
            </h2>
          </div>
          <button type="button" onClick={close} className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground" aria-label="Close the recipes">
            <X className="h-5 w-5" />
          </button>
        </header>

        {recipesQuery.isLoading ? (
          <div className="flex flex-1 items-center justify-center p-10 text-sm text-muted-foreground" role="status">
            <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Loading recipes…
          </div>
        ) : recipesQuery.isError || !list ? (
          <div className="flex flex-1 items-center justify-center p-10 text-sm text-destructive" role="alert">
            The recipes could not be loaded.{" "}
            <button type="button" className="ml-1 underline" onClick={() => void recipesQuery.refetch()}>Retry</button>
          </div>
        ) : chosen ? (
          <div className="flex-1 overflow-y-auto p-6">
            <div className="mx-auto max-w-xl space-y-5">
              <p className="text-sm">{chosen.summary}</p>
              <p className="text-xs text-muted-foreground">Starts when: {chosen.trigger_labels.join(" or ")}.</p>
              {chosen.fill_ins.length > 0 ? (
                <div className="space-y-4 rounded-xl border border-border bg-card p-4">
                  <h3 className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">Two quick answers</h3>
                  {chosen.fill_ins.map((fill) => (
                    <FillInField
                      key={fill.path}
                      fill={fill}
                      catalog={catalog}
                      value={answers[fill.path] ?? ""}
                      onChange={(value) => setAnswers((current) => ({ ...current, [fill.path]: value }))}
                    />
                  ))}
                </div>
              ) : (
                <p className="rounded-xl border border-border bg-card p-4 text-sm text-muted-foreground">
                  Nothing to fill in. It opens in the builder so you can adjust it before it is switched on.
                </p>
              )}
              <button
                type="button"
                disabled={missing.length > 0}
                onClick={() => use(chosen, answers)}
                className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
              >
                Open in the builder
              </button>
              {missing.length > 0 && <p className="text-xs text-muted-foreground">Answer the above to continue.</p>}
            </div>
          </div>
        ) : (
          <div className="flex min-h-0 flex-1 flex-col">
            <div className="flex flex-wrap items-center gap-3 border-b border-border/60 px-5 py-3">
              <div className="relative min-w-[14rem] flex-1">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden="true" />
                <input
                  type="search"
                  aria-label="Search recipes"
                  value={query}
                  placeholder="Search recipes: invoice, GST, Slack…"
                  onChange={(e) => setQuery(e.target.value)}
                  className={`${inputClass(false)} pl-9`}
                />
              </div>
              <div role="group" aria-label="Recipe category" className="flex flex-wrap gap-1.5">
                {["All", ...list.categories].map((name) => (
                  <button
                    key={name}
                    type="button"
                    aria-pressed={category === name}
                    onClick={() => setCategory(name)}
                    className={`rounded-full border px-3 py-1 text-xs font-semibold ${
                      category === name ? "border-primary bg-primary/10 text-primary" : "border-border text-muted-foreground hover:bg-muted"
                    }`}
                  >
                    {name}
                  </button>
                ))}
              </div>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-5">
              {shown.length === 0 ? (
                <p className="py-10 text-center text-sm text-muted-foreground" role="status">No recipe matches. Try another word, or start from a blank rule.</p>
              ) : (
                <ul className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
                  {shown.map((recipe) => (
                    <li key={recipe.id} className="flex flex-col rounded-xl border border-border bg-card p-4 shadow-sm" data-testid={`recipe-${recipe.id}`}>
                      <span className="text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">{recipe.category}</span>
                      <h3 className="mt-1 text-sm font-semibold leading-snug">{recipe.title}</h3>
                      <p className="mt-1.5 flex-1 text-xs leading-relaxed text-muted-foreground">{recipe.summary}</p>
                      <p className="mt-2 text-[11px] text-muted-foreground">When: {recipe.trigger_labels.join(" or ")}</p>
                      {recipe.available ? (
                        <button
                          type="button"
                          onClick={() => (recipe.fill_ins.length ? setChosen(recipe) : use(recipe, {}))}
                          aria-label={`Use the recipe: ${recipe.title}`}
                          className="mt-3 rounded-lg border border-primary px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary/10"
                        >
                          Use this recipe
                        </button>
                      ) : (
                        <div className="mt-3 flex flex-wrap items-center gap-2">
                          <span className="inline-flex items-center gap-1.5 rounded-lg bg-muted px-2.5 py-1.5 text-xs font-semibold text-muted-foreground">
                            <Lock className="h-3.5 w-3.5" aria-hidden="true" /> {recipe.unavailable_reason ?? "Not in your plan"}
                          </span>
                          {recipe.locked_capability && (
                            <button
                              type="button"
                              onClick={() => onUpgrade(recipe.locked_capability ?? "", recipe.locked_feature ?? recipe.title)}
                              aria-label={`Upgrade to use the recipe: ${recipe.title}`}
                              className="rounded-lg border border-primary px-3 py-1.5 text-xs font-semibold text-primary hover:bg-primary/10"
                            >
                              Upgrade
                            </button>
                          )}
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
      </div>
    </div>,
    document.body,
  );
};
