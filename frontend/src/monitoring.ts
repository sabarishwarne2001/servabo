/**
 * Error tracking for the web app (Final session 1, 4A). Off unless VITE_SENTRY_DSN is set at build time: with it empty this module imports
 * nothing, loads no SDK and makes no request.
 *
 * What is sent: an exception nobody handled, an unhandled rejection that is not an expected refusal (a 4xx from the API is the product
 * talking), and an error a React boundary caught. Personal data is not collected (the SDK default; no user, no IP). What is not: breadcrumbs, request bodies, cookies, the person, the page's text, the
 * address's query string or hash. Text that does remain (an error message) is scrubbed the way the server scrubs it: emails, tokens,
 * keys, GSTINs, PANs, IRNs, bank-account-like numbers, amounts. The release and environment come from VITE_RELEASE and
 * VITE_SENTRY_ENVIRONMENT; traces default to 0.
 */

const PATTERNS: ReadonlyArray<readonly [RegExp, string]> = [
  [/[\w.+-]+@[\w-]+(?:\.[\w-]+)+/g, "[email]"],
  [/eyJ[\w-]{5,}\.[\w-]{5,}\.[\w-]*/g, "[token]"],
  [/\bbearer\s+[\w.~+/=-]{8,}/gi, "Bearer [token]"],
  [/\b(?:sk|pk|rk|gsk|xox[abp]|ghp|whsec|pdt|cus|sub|prod)[-_][\w-]{8,}/gi, "[key]"],
  [/(?:api[_-]?key|secret|password|passwd|token|authorization)("?\s*[:=]\s*"?)[^\s"',;&]{4,}/gi, "[secret]"],
  [/\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b/g, "[gstin]"],
  [/\b[A-Z]{5}[0-9]{4}[A-Z]\b/g, "[pan]"],
  [/\b[0-9a-fA-F]{64}\b/g, "[irn]"],
  [/(?:₹|\bINR\b|\bRs\.?|\$|\bUSD\b|\bEUR\b|€)\s?-?\d[\d,]*(?:\.\d+)?/g, "[amount]"],
  [/\b\d[\d,]*\.\d{2}\b/g, "[amount]"],
  [/\b\d{9,18}\b/g, "[number]"],
  [/\b[A-Z]{2,5}[-/]?\d{3,}[-/\w]*\b/g, "[reference]"],
];

export const scrubText = (value: string): string => PATTERNS.reduce((text, [pattern, replacement]) => text.replace(pattern, replacement), value).slice(0, 2000);

/** The address without its query string or hash (either can hold a token, an email or a search). */
export const scrubUrl = (raw: string): string => {
  try {
    const url = new URL(raw, "https://app.invalid");
    return scrubText(`${raw.startsWith("http") ? url.origin : ""}${url.pathname}`);
  } catch {
    return "[url]";
  }
};

interface EventLike {
  request?: { url?: string; headers?: unknown; cookies?: unknown; data?: unknown; query_string?: unknown };
  user?: unknown;
  breadcrumbs?: unknown;
  extra?: unknown;
  message?: string;
  exception?: { values?: Array<{ value?: string; stacktrace?: { frames?: Array<Record<string, unknown>> } }> };
  tags?: Record<string, unknown>;
  contexts?: Record<string, unknown>;
  [key: string]: unknown;
}

/** `beforeSend`: everything a person's data could be in is removed; what is left is the failure. */
export const scrubEvent = <T extends EventLike>(event: T): T => {
  if (event.request) {
    event.request = { url: scrubUrl(String(event.request.url ?? "")) };
  }
  delete event.user;
  delete event.breadcrumbs;
  delete event.extra;
  if (typeof event.message === "string") {
    event.message = scrubText(event.message);
  }
  for (const exception of event.exception?.values ?? []) {
    if (typeof exception.value === "string") {
      exception.value = scrubText(exception.value);
    }
    for (const frame of exception.stacktrace?.frames ?? []) {
      delete frame.vars;
      if (typeof frame.filename === "string") {
        frame.filename = scrubUrl(frame.filename);
      }
    }
  }
  const contexts = event.contexts ?? {};
  event.contexts = Object.fromEntries(Object.entries(contexts).filter(([key]) => ["browser", "os", "device", "trace"].includes(key)));
  return event;
};

/** An expected refusal (the API said 4xx) is the product working, not an error to report. */
export const isExpected = (error: unknown): boolean => {
  const status = (error as { status?: unknown } | null)?.status;
  return typeof status === "number" && status >= 400 && status < 500;
};

type Reporter = (error: unknown) => void;
let reporter: Reporter | null = null;

export const reportError = (error: unknown): void => {
  if (reporter && !isExpected(error)) {
    reporter(error);
  }
};

export const initMonitoring = async (): Promise<boolean> => {
  const dsn = String(import.meta.env["VITE_SENTRY_DSN"] ?? "").trim();
  if (!dsn) {
    return false;
  }
  const Sentry = await import("@sentry/browser");
  Sentry.init({
    dsn,
    environment: String(import.meta.env["VITE_SENTRY_ENVIRONMENT"] ?? "") || import.meta.env.MODE,
    release: String(import.meta.env["VITE_RELEASE"] ?? "") || undefined,
    tracesSampleRate: Number(import.meta.env["VITE_SENTRY_TRACES_SAMPLE_RATE"] ?? 0) || 0,
    maxBreadcrumbs: 0,
    sendClientReports: false,
    defaultIntegrations: false,
    integrations: [Sentry.globalHandlersIntegration(), Sentry.dedupeIntegration()],
    beforeSend: (event, hint) => (isExpected(hint?.originalException) ? null : scrubEvent(event as unknown as EventLike) as unknown as typeof event),
    beforeSendTransaction: () => null,
  });
  reporter = (error) => {
    Sentry.captureException(error);
  };
  return true;
};
