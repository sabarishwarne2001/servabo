import React, { useEffect, useMemo, useRef } from "react";
import DOMPurify from "dompurify";
import type { Config as PurifyConfig } from "dompurify";
import hljs from "highlight.js/lib/common";
import { marked } from "marked";

import type { CitationClaim } from "@/services/streaming/resumableStream";

const ALLOWED_URI_REGEXP = /^(?:https|mailto):/i;

const PURIFY_CONFIG: PurifyConfig = {
  ALLOWED_TAGS: [
    "p", "br", "hr",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "strong", "em", "del", "code", "pre", "blockquote",
    "ul", "ol", "li",
    "table", "thead", "tbody", "tr", "th", "td",
    "a", "span",
    // F-357. Text itself. DOMPurify adds "#text" to a custom list only when KEEP_CONTENT is on;
    // with it off (a removed element takes its content with it) every answer rendered as empty
    // paragraphs.
    "#text",
  ],
  ALLOWED_ATTR: ["href", "title", "class", "data-claim-id", "data-citation-index"],
  ALLOWED_URI_REGEXP,
  KEEP_CONTENT: false,
  FORBID_TAGS: ["style", "script", "iframe", "object", "embed", "form", "input"],
  FORBID_ATTR: ["style", "srcset", "formaction", "background"],
  RETURN_DOM: false,
  RETURN_DOM_FRAGMENT: false,
};

let hookInstalled = false;

const installLinkHook = (): void => {
  if (hookInstalled) {
    return;
  }
  DOMPurify.addHook("afterSanitizeAttributes", (node) => {
    if (node.tagName === "A" && node.hasAttribute("href")) {
      node.setAttribute("target", "_blank");
      node.setAttribute("rel", "noopener noreferrer nofollow");
    }
  });
  hookInstalled = true;
};

const insertCitationMarkers = (
  text: string,
  claims: readonly CitationClaim[],
): string => {
  if (claims.length === 0) {
    return text;
  }

  const valid = claims
    .filter((claim) => {
      const [start, end] = claim.text_span;
      return (
        Number.isInteger(start) &&
        Number.isInteger(end) &&
        start >= 0 &&
        end <= text.length &&
        end > start
      );
    })
    .slice()
    .sort((a, b) => b.text_span[0] - a.text_span[0]);

  let result = text;

  valid.forEach((claim, reverseIndex) => {
    const [start, end] = claim.text_span;
    const number = valid.length - reverseIndex;
    const cited = result.slice(start, end);
    const id = escapeAttribute(claim.claim_id);

    result =
      result.slice(0, start) +
      `<span class="fp-claim" data-claim-id="${id}">` +
      cited +
      `<span class="fp-citation" data-claim-id="${id}" ` +
      `data-citation-index="${number}">${number}</span>` +
      "</span>" +
      result.slice(end);
  });

  return result;
};

const escapeAttribute = (value: string): string =>
  value.replace(/[&<>"']/g, (char) => {
    switch (char) {
      case "&":
        return "&amp;";
      case "<":
        return "&lt;";
      case ">":
        return "&gt;";
      case '"':
        return "&quot;";
      default:
        return "&#39;";
    }
  });

/** Insert native citation buttons only after sanitizing provider-authored HTML. */
const addNumericCitations = (html: string, count: number): string => {
  if (!count) {return html;}
  const root = document.createElement("div");
  root.innerHTML = html;
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
  const nodes: Text[] = [];
  while (walker.nextNode()) {nodes.push(walker.currentNode as Text);}
  for (const node of nodes) {
    if (node.parentElement?.closest("code, pre, a")) {continue;}
    const text = node.textContent ?? "";
    const matches = [...text.matchAll(/\[(\d+)\]/g)].filter((match) => Number(match[1]) >= 1 && Number(match[1]) <= count);
    if (!matches.length) {continue;}
    const fragment = document.createDocumentFragment();
    let offset = 0;
    for (const match of matches) {
      fragment.append(document.createTextNode(text.slice(offset, match.index)));
      const button = document.createElement("button");
      button.type = "button";
      button.className = "fp-source-citation mx-0.5 rounded border border-primary/30 bg-primary/10 px-1 text-xs font-semibold text-primary";
      button.dataset.sourceIndex = match[1];
      button.setAttribute("aria-label", `Open citation ${match[1]}`);
      button.textContent = match[0];
      fragment.append(button);
      offset = match.index + match[0].length;
    }
    fragment.append(document.createTextNode(text.slice(offset)));
    node.replaceWith(fragment);
  }
  return root.innerHTML;
};

export interface MarkdownRendererProps {
  readonly numericCitationCount?: number;
  readonly onNumericCitationClick?: (index: number) => void;
  readonly content: string;
  readonly claims?: readonly CitationClaim[];
  readonly onCitationClick?: (claimId: string) => void;
  readonly activeClaimId?: string | null;
  readonly className?: string;
}

export const MarkdownRenderer: React.FC<MarkdownRendererProps> = ({
  content,
  numericCitationCount = 0,
  onNumericCitationClick,
  claims = [],
  onCitationClick,
  activeClaimId = null,
  className = "",
}) => {
  const containerRef = useRef<HTMLDivElement>(null);

  const html = useMemo(() => {
    installLinkHook();

    const marked_ = insertCitationMarkers(content, claims);

    const raw = marked.parse(marked_, {
      async: false,
      gfm: true,
      breaks: true,
    }) as string;

    const sanitized = DOMPurify.sanitize(raw, PURIFY_CONFIG) as unknown as string;
    return addNumericCitations(sanitized, numericCitationCount);
  }, [content, claims, numericCitationCount]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !onNumericCitationClick) {return;}
    const click = (event: MouseEvent) => {
      const button = (event.target as HTMLElement)?.closest<HTMLElement>(".fp-source-citation");
      if (button && container.contains(button)) {onNumericCitationClick(Number(button.dataset.sourceIndex) - 1);}
    };
    container.addEventListener("click", click);
    return () => container.removeEventListener("click", click);
  }, [html, onNumericCitationClick]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    const blocks = container.querySelectorAll<HTMLElement>(
      "pre code:not([data-highlighted])",
    );

    blocks.forEach((block) => {
      try {
        hljs.highlightElement(block);
      } catch {
        // Plain text fallback
      }
      block.setAttribute("data-highlighted", "yes");
    });
  }, [html]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container || !onCitationClick) {
      return;
    }

    const onClick = (event: MouseEvent) => {
      const target = (event.target as HTMLElement | null)?.closest<HTMLElement>(
        ".fp-citation",
      );
      const claimId = target?.getAttribute("data-claim-id");
      if (claimId) {
        event.preventDefault();
        onCitationClick(claimId);
      }
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Enter" && event.key !== " ") {
        return;
      }
      const target = (
        document.activeElement as HTMLElement | null
      )?.closest<HTMLElement>(".fp-citation");
      const claimId = target?.getAttribute("data-claim-id");
      if (claimId && target && container.contains(target)) {
        event.preventDefault();
        onCitationClick(claimId);
      }
    };

    container.addEventListener("click", onClick);
    container.addEventListener("keydown", onKeyDown);

    return () => {
      container.removeEventListener("click", onClick);
      container.removeEventListener("keydown", onKeyDown);
    };
  }, [onCitationClick]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) {
      return;
    }

    container
      .querySelectorAll<HTMLElement>(".fp-citation")
      .forEach((marker) => {
        marker.setAttribute("role", "button");
        marker.setAttribute("tabindex", "0");
        marker.setAttribute(
          "aria-label",
          `Show source ${marker.getAttribute("data-citation-index") ?? ""}`,
        );

        const isActive =
          activeClaimId !== null &&
          marker.getAttribute("data-claim-id") === activeClaimId;
        marker.setAttribute("data-active", isActive ? "true" : "false");
      });
  }, [html, activeClaimId]);

  return (
    <div
      ref={containerRef}
      className={`fp-markdown ${className}`}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
};

export default MarkdownRenderer;
