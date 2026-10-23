#!/usr/bin/env node
/**
 * Runs the app's built-in self-checks (tenant resolution, tenant paths, tenant reconciliation,
 * permission parity) outside the browser and exits 1 on any failure.
 *
 *   npm run check:self
 *
 * They used to run only in a development browser's console (main.tsx, DEV only), so a change
 * that broke one was seen by whoever happened to open the console. esbuild bundles the four
 * modules (they are plain TypeScript, no React) and node runs them.
 */
import { build } from "esbuild";
import { mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const work = mkdtempSync(path.join(tmpdir(), "fp-self-checks-"));
const entry = path.join(work, "entry.ts");
const out = path.join(work, "self-checks.mjs");

writeFileSync(
  entry,
  `
import { runTenantResolutionSelfCheck } from "@/hooks/tenantResolution";
import { runTenantPathSelfCheck } from "@/routes/tenantPaths";
import { runTenantReconciliationSelfCheck } from "@/routes/tenantReconciliation";
import { runPermissionSelfCheck } from "@/permissions/selfCheck";
import { runDisplayFormatSelfCheck } from "@/utils/displayTime";
import { runBrandColourSelfCheck } from "@/utils/brandTheme";
import { runHelmMoneySelfCheck } from "@/components/helm/money";
import { runProblemKeySelfCheck } from "@/components/batches/problemKeys";
import { runGstFormatSelfCheck } from "@/components/gst/gstFormat";
export const checks = {
  "tenant resolution": runTenantResolutionSelfCheck,
  "tenant paths": runTenantPathSelfCheck,
  "tenant reconciliation": runTenantReconciliationSelfCheck,
  "permission parity": runPermissionSelfCheck,
  "display formatting": runDisplayFormatSelfCheck,
  "brand colours": runBrandColourSelfCheck,
  "helm money": runHelmMoneySelfCheck,
  "package problem keys": runProblemKeySelfCheck,
  "gst credit format": runGstFormatSelfCheck,
};
`,
);

try {
  await build({
    entryPoints: [entry],
    bundle: true,
    platform: "node",
    format: "esm",
    outfile: out,
    alias: { "@": path.join(ROOT, "src") },
    logLevel: "error",
    define: { "import.meta.env.DEV": "true", "import.meta.env.PROD": "false", "import.meta.env.MODE": '"test"' },
  });
  const { checks } = await import(pathToFileURL(out).href);
  let failed = 0;
  for (const [name, run] of Object.entries(checks)) {
    const failures = run();
    if (failures.length === 0) {
      console.log(`ok    ${name}`);
    } else {
      failed += failures.length;
      console.log(`FAIL  ${name}\n${failures.map((f) => `        - ${f}`).join("\n")}`);
    }
  }

  // Campaign session 3 (N-064): dates, times, numbers and money go through the display layer
  // (src/utils/displayTime.ts), which reads the person's language and clock and the workspace's
  // date format. A bare toLocale*String() or new Intl.*Format() reads the browser instead.
  // Website and payments session: also Intl's other formatters and navigator.language itself.
  // formatRelativeTime passed navigator.language straight to Intl.RelativeTimeFormat, which
  // throws on a tag like "en-US@posix" and took the whole Helm cockpit down.
  const BYPASS =
    /\.toLocale(?:Date|Time)?String\(|new Intl\.(?:NumberFormat|DateTimeFormat|RelativeTimeFormat|ListFormat|PluralRules)\(|navigator\.languages?\b/;
  const ALLOWED = new Set([path.join("src", "utils", "displayTime.ts")]);
  const bypasses = [];
  const walk = (dir) => {
    for (const name of readdirSync(dir)) {
      const full = path.join(dir, name);
      if (statSync(full).isDirectory()) {
        walk(full);
      } else if (/\.(ts|tsx)$/.test(name) && !name.endsWith(".d.ts")) {
        const relative = path.relative(ROOT, full);
        if (ALLOWED.has(relative)) continue;
        readFileSync(full, "utf8").split("\n").forEach((line, index) => {
          const code = line.replace(/\/\/.*$/, "").replace(/\{\/\*.*\*\/\}/, "");
          if (BYPASS.test(code)) bypasses.push(`${relative}:${index + 1}: ${line.trim()}`);
        });
      }
    }
  };
  walk(path.join(ROOT, "src"));
  if (bypasses.length === 0) {
    console.log("ok    one display layer");
  } else {
    failed += bypasses.length;
    console.log(`FAIL  one display layer\n${bypasses.map((f) => `        - ${f}`).join("\n")}`);
  }

  // Final session 1 (Phase 5): money, one way. Every amount goes through formatMoney (rupees in lakh and crore grouping
  // with the rupee sign, other currencies with their own symbol). A hand-built "INR " + amount, a template that glues
  // "INR" or "₹" to a number, or toLocaleString("en-US", ...) prints a number the way the browser or the developer felt
  // like. Only the formatter itself and Helm's rupee module are allowed to build currency text.
  const HAND_BUILT_MONEY = [
    /["'`]\s*INR\s+["'`]\s*\+/,
    /`\s*INR\s*\$\{/,
    /["'`]\s*₹\s*["'`]\s*\+/,
    /`\s*₹\s*\$\{/,
    /\.toLocaleString\(\s*["'`]en-US/,
  ];
  const MONEY_ALLOWED = new Set([
    path.join("src", "utils", "displayTime.ts"),
    path.join("src", "components", "helm", "money.ts"),
  ]);
  const handBuiltMoney = [];
  const scanMoney = (dir) => {
    for (const name of readdirSync(dir)) {
      const full = path.join(dir, name);
      if (statSync(full).isDirectory()) {
        scanMoney(full);
      } else if (/\.(ts|tsx)$/.test(name) && !name.endsWith(".d.ts") && !/\.test\.tsx?$/.test(name)) {
        const relative = path.relative(ROOT, full);
        if (MONEY_ALLOWED.has(relative)) continue;
        readFileSync(full, "utf8").split("\n").forEach((line, index) => {
          const trimmed = line.trim();
          if (trimmed.startsWith("//") || trimmed.startsWith("*") || trimmed.startsWith("/*")) return;
          const code = line.replace(/\/\/.*$/, "");
          if (HAND_BUILT_MONEY.some((pattern) => pattern.test(code))) handBuiltMoney.push(`${relative}:${index + 1}: ${trimmed}`);
        });
      }
    }
  };
  scanMoney(path.join(ROOT, "src"));
  if (handBuiltMoney.length === 0) {
    console.log("ok    money, one way");
  } else {
    failed += handBuiltMoney.length;
    console.log(`FAIL  money, one way\n${handBuiltMoney.map((f) => `        - ${f}`).join("\n")}`);
  }

  // Final session 1 (Phase 5): no raw error text. A person is shown a sentence written for them: `errorMessage(error, fallback)`
  // gives the server's own sentence for a refusal (4xx) and the caller's wording for a server fault (5xx, whose body is not
  // written for people). A toast or paragraph that prints `error.message` itself shows "Request failed with status code 500"
  // or "Internal Server Error". The crash screens' developer details are shown only in development and are allowed.
  const RAW_ERROR = [
    /toast\.(?:error|warning)\(\s*(?:[A-Za-z_$][\w$.?]*\.)?(?:error|err|e|failure|exception)\.message\b/,
    /\{\s*[A-Za-z_$][\w$.?]*(?:error|err|failure)\.message\s*\}/,
    /\{\s*String\(\s*(?:error|err)\s*\)\s*\}/,
  ];
  const RAW_ERROR_ALLOWED = new Set([
    path.join("src", "components", "common", "ErrorBoundary.tsx"),   // developer details, development builds only
    path.join("src", "components", "chat", "MessageStream.tsx"),     // the assistant's own stream error, written by the server for people
  ]);
  const rawErrors = [];
  const scanErrors = (dir) => {
    for (const name of readdirSync(dir)) {
      const full = path.join(dir, name);
      if (statSync(full).isDirectory()) {
        scanErrors(full);
      } else if (/\.tsx?$/.test(name) && !name.endsWith(".d.ts") && !/\.test\.tsx?$/.test(name)) {
        const relative = path.relative(ROOT, full);
        if (RAW_ERROR_ALLOWED.has(relative)) continue;
        readFileSync(full, "utf8").split("\n").forEach((line, index) => {
          const trimmed = line.trim();
          if (trimmed.startsWith("//") || trimmed.startsWith("*") || trimmed.startsWith("/*")) return;
          if (RAW_ERROR.some((pattern) => pattern.test(line))) rawErrors.push(`${relative}:${index + 1}: ${trimmed}`);
        });
      }
    }
  };
  scanErrors(path.join(ROOT, "src"));
  if (rawErrors.length === 0) {
    console.log("ok    no raw error text");
  } else {
    failed += rawErrors.length;
    console.log(`FAIL  no raw error text\n${rawErrors.map((f) => `        - ${f}`).join("\n")}`);
  }

  // Website and payments session (C10): Dodo Payments is the gateway customers see, so no screen
  // names Stripe (the dormant Stripe adapter's identifiers and comments are not shown to anyone).
  const stripeWords = [];
  const scan = (dir) => {
    for (const name of readdirSync(dir)) {
      const full = path.join(dir, name);
      if (statSync(full).isDirectory()) {
        scan(full);
      } else if (/\.(ts|tsx)$/.test(name) && !name.endsWith(".d.ts")) {
        const relative = path.relative(ROOT, full);
        readFileSync(full, "utf8").split("\n").forEach((line, index) => {
          const trimmed = line.trim();
          if (trimmed.startsWith("//") || trimmed.startsWith("*") || trimmed.startsWith("/*")) return;
          const code = line.replace(/\/\/.*$/, "").replace(/\{\/\*.*\*\/\}/, "");
          if (/\bStripe\b/.test(code)) stripeWords.push(`${relative}:${index + 1}: ${trimmed}`);
        });
      }
    }
  };
  scan(path.join(ROOT, "src"));
  if (stripeWords.length === 0) {
    console.log("ok    no Stripe on screen");
  } else {
    failed += stripeWords.length;
    console.log(`FAIL  no Stripe on screen\n${stripeWords.map((f) => `        - ${f}`).join("\n")}`);
  }
  // Session J: Servabo shows its own dialogs, never the browser's pop-ups ("localhost says"). A person
  // sees a pop-up in no theme, with no brand and no keyboard rules, and a browser test dismisses one
  // silently. Use ConfirmDialog (or `useConfirmDialog().ask`) or a sonner toast. Comment-only lines and
  // the contents of string literals are skipped. `beforeunload` is not a pop-up call and is not matched.
  const NATIVE_DIALOG = /(?<![\w.$])(?:window\.|globalThis\.)?(?:alert|confirm|prompt)\s*\(/;
  const withoutStrings = (line) =>
    line.replace(/"(?:[^"\\]|\\.)*"|'(?:[^'\\]|\\.)*'|`(?:[^`\\]|\\.)*`/g, '""').replace(/\/\/.*$/, "");
  const nativeDialogs = [];
  const scanDialogs = (dir) => {
    for (const name of readdirSync(dir)) {
      const full = path.join(dir, name);
      if (statSync(full).isDirectory()) {
        scanDialogs(full);
      } else if (/\.(ts|tsx)$/.test(name) && !name.endsWith(".d.ts")) {
        const relative = path.relative(ROOT, full);
        readFileSync(full, "utf8").split("\n").forEach((line, index) => {
          const trimmed = line.trim();
          if (trimmed.startsWith("//") || trimmed.startsWith("*") || trimmed.startsWith("/*")) return;
          // The call is matched on the line with strings blanked, but a call that precedes its own
          // string argument (`window.confirm(`Delete ${x}?`)`) still shows its name and bracket.
          if (NATIVE_DIALOG.test(withoutStrings(line))) nativeDialogs.push(`${relative}:${index + 1}: ${trimmed}`);
        });
      }
    }
  };
  scanDialogs(path.join(ROOT, "src"));
  if (nativeDialogs.length === 0) {
    console.log("ok    no native browser dialogs");
  } else {
    failed += nativeDialogs.length;
    console.log(`FAIL  no native browser dialogs\n${nativeDialogs.map((f) => `        - ${f}`).join("\n")}`);
  }

  // The browser specs never answer a dialog themselves: only the fixture (e2e/support/fixtures.ts) listens,
  // and it fails any test whose page showed an alert, confirm or prompt.
  const specDialogs = [];
  const scanSpecs = (dir) => {
    for (const name of readdirSync(dir)) {
      const full = path.join(dir, name);
      if (statSync(full).isDirectory()) {
        scanSpecs(full);
      } else if (/\.ts$/.test(name)) {
        const relative = path.relative(ROOT, full);
        readFileSync(full, "utf8").split("\n").forEach((line, index) => {
          const trimmed = line.trim();
          if (trimmed.startsWith("//") || trimmed.startsWith("*") || trimmed.startsWith("/*")) return;
          if (/(?:on|once|waitForEvent)\(\s*["'`]dialog["'`]/.test(line)) specDialogs.push(`${relative}:${index + 1}: ${trimmed}`);
        });
      }
    }
  };
  scanSpecs(path.join(ROOT, "e2e", "tests"));
  if (specDialogs.length === 0) {
    console.log("ok    no spec listens for native dialogs");
  } else {
    failed += specDialogs.length;
    console.log(`FAIL  no spec listens for native dialogs\n${specDialogs.map((f) => `        - ${f}`).join("\n")}`);
  }
  process.exitCode = failed ? 1 : 0;
} finally {
  rmSync(work, { recursive: true, force: true });
}
