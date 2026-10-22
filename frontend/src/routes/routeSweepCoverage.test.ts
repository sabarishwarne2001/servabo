/**
 * Every page the router defines is walked by the accessibility and phone-width sweeps (Final session 1, F-573).
 *
 * Specs 72 (axe, light and dark) and 74 (four widths) walk the page catalogue in e2e/support/routes.ts; spec 132 walks the pages that
 * catalogue predates (GST Credit, Helm, the new-workspace form, the jobs console). A page added to ROUTE_PATTERNS that is in neither
 * would be a page no sweep ever opens, which is how eleven of ninety-nine specs ended up the only ones with an accessibility check.
 * This test fails for such a page; a route that cannot be walked says why in NOT_WALKED.
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const read = (relative: string): string => fs.readFileSync(path.resolve(process.cwd(), relative), "utf8");

/** Static (no `:param`) route segments of ROUTE_PATTERNS, by key. */
function staticRoutes(): Array<{ key: string; value: string }> {
  const body = /export const ROUTE_PATTERNS = \{([\s\S]*?)\n\} as const;/.exec(read("src/routes/tenantPaths.ts"))?.[1] ?? "";
  const found: Array<{ key: string; value: string }> = [];
  for (const match of body.matchAll(/^\s{2}(\w+): ("[^"]*"|`[^`]*`),?\s*$/gm)) {
    const value = match[2]!.slice(1, -1);
    if (!value.includes(":") && !value.includes("$")) {found.push({ key: match[1]!, value });}
  }
  return found;
}

/** Routes no sweep opens, and why. */
const NOT_WALKED: Readonly<Record<string, string>> = {
  organizationShell: "a layout, not a page",
  workspaceShell: "a layout, not a page",
  helmShell: "a layout, not a page",
  platformShell: "a layout, not a page",
  organizationBillingReturn: "the page a payment provider sends a customer back to; spec 71 and the journeys open it with the provider's answer",
  partnerPortalShell: "the partner portal has its own sign-in; spec 100 walks it",
};

describe("the sweeps walk every page", () => {
  const catalogue = read("e2e/support/routes.ts");
  const spec132 = read("e2e/tests/132-new-pages-sweep.spec.ts");
  const covered = new Set<string>();
  for (const match of catalogue.matchAll(/\bsub: "([^"]*)"/g)) {covered.add(match[1]!);}
  for (const match of catalogue.matchAll(/\bpath: "\/admin\/([^"]*)"/g)) {covered.add(match[1]!);}
  for (const match of spec132.matchAll(/ws\("C", "([^"]*)"\)/g)) {covered.add(match[1]!);}
  for (const match of spec132.matchAll(/org\("C", "([^"]*)"\)/g)) {covered.add(match[1]!);}
  for (const match of spec132.matchAll(/"\/admin\/([^"]*)"/g)) {covered.add(match[1]!);}
  const helmList = /HELM_PAGES = \[([^\]]*)\]/.exec(spec132)?.[1] ?? "";
  for (const match of helmList.matchAll(/"([^"]*)"/g)) {covered.add(match[1]!);}

  for (const { key, value } of staticRoutes()) {
    if (key in NOT_WALKED) {continue;}
    it(`${key} ("${value || "/"}") is walked by spec 72/74 or 132`, () => {
      const sub = value.replace(/^\/organizations\/\$\{P_ORG\}\//, "").replace(/^\//, "");
      const workspaceLike = key.startsWith("workspace") || key.startsWith("organization") || key.startsWith("helm") || key.startsWith("platform");
      expect(workspaceLike, `${key} is not a recognised kind of page`).toBe(true);
      expect(covered.has(sub), `${key} ("${sub}") is in neither e2e/support/routes.ts nor spec 132: add it to one, or to NOT_WALKED with a reason`).toBe(true);
    });
  }

  it("lists every NOT_WALKED key as a real route key", () => {
    const keys = new Set(staticRoutes().map((r) => r.key));
    const body = read("src/routes/tenantPaths.ts");
    for (const key of Object.keys(NOT_WALKED)) {expect(keys.has(key) || body.includes(`${key}:`), key).toBe(true);}
  });
});
