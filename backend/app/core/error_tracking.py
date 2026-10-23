"""Error tracking (Final session 1, 4A): the owner sees which line failed, for whom and how often, before the customer finishes typing.

Sentry's free plan in its EU region, or a self-hosted GlitchTip (the same protocol; one setting changes), receives:

  * 5xx responses and unhandled exceptions of the API;
  * the exceptions of every background job (receipt.monthly, the GST recompute, the GST digest, the OCR worker's QR reading, ...);
  * the exceptions the email-in handler catches and turns into a 500;
  * (the web app has its own: `frontend/src/monitoring.ts`).

Nothing else. Expected 4xx are not sent; breadcrumbs, local variables, request bodies, cookies and the user are not collected. Whatever is
left is scrubbed a second time in `scrub_event` (`before_send`) before it leaves the process: emails, tokens, API keys, GSTINs, PANs, IRNs,
bank-account-like numbers, amounts, query-string values, document text and field values. Organization and workspace ids are kept as tags:
they are opaque UUIDs, and "which customer" is the question the owner asks first.

`SENTRY_DSN` empty means off: the SDK is never initialised and the module sends nothing. The tests prove the scrubbing against a stand-in
ingest (`tests/fakes/fake_sentry.py`), including that an event made of the worst a customer's data can offer leaves with none of it.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Mapping, Optional
from urllib.parse import urlsplit

logger = logging.getLogger("app.core.error_tracking")

_enabled = False

#: Header names that never leave the process, and any header whose name contains one of these words.
_SECRET_WORDS = ("authorization", "cookie", "token", "secret", "key", "password", "signature", "session", "csrf")
#: Keys of a dict (extra, contexts, request data) whose values are dropped whatever they hold.
_DROP_KEYS = ("data", "cookies", "body", "text", "content", "entities", "fields", "payload", "extracted_entities", "message_body",
              "attachments", "html", "from", "sender")

_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), "[email]"),
    (re.compile(r"eyJ[\w-]{5,}\.[\w-]{5,}\.[\w-]*"), "[token]"),
    (re.compile(r"(?i)\bbearer\s+[\w.~+/=-]{8,}"), "Bearer [token]"),
    (re.compile(r"(?i)\b(?:sk|pk|rk|gsk|xox[abp]|ghp|whsec|pdt|cus|sub|prod)[-_][\w-]{8,}"), "[key]"),
    (re.compile(r"(?i)(?:api[_-]?key|secret|password|passwd|token|authorization)(\"?\s*[:=]\s*\"?)[^\s\"',;&]{4,}"), r"[secret]"),
    (re.compile(r"\b[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]\b"), "[gstin]"),
    (re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b"), "[pan]"),
    (re.compile(r"\b[0-9a-fA-F]{64}\b"), "[irn]"),
    (re.compile(r"(?:₹|\bINR\b|\bRs\.?|\$|\bUSD\b|\bEUR\b|€)\s?-?\d[\d,]*(?:\.\d+)?"), "[amount]"),
    (re.compile(r"\b\d[\d,]*\.\d{2}\b"), "[amount]"),
    (re.compile(r"\b\d{9,18}\b"), "[number]"),
    (re.compile(r"\b[A-Z]{2,5}[-/]?\d{3,}[-/\w]*\b"), "[reference]"),
)


def scrub_text(value: str) -> str:
    """Emails, tokens, keys, GSTINs, PANs, IRNs, bank-account-like numbers, amounts and document references replaced by a word."""
    out = value
    for pattern, replacement in _PATTERNS:
        out = pattern.sub(replacement, out)
    return out[:2000]


def _scrub_value(value: Any, depth: int = 0) -> Any:
    if depth > 6:
        return "[deep]"
    if isinstance(value, str):
        return scrub_text(value)
    if isinstance(value, Mapping):
        return {k: ("[dropped]" if str(k).lower() in _DROP_KEYS or any(w in str(k).lower() for w in _SECRET_WORDS)
                    else _scrub_value(v, depth + 1)) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_scrub_value(v, depth + 1) for v in value[:50]]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return "[object]"


def _scrub_request(request: Mapping[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    url = str(request.get("url") or "")
    parts = urlsplit(url)
    # Path only: a query string can hold a token, an email or a search for a supplier. Path segments that are ids stay (they are opaque).
    out["url"] = scrub_text(f"{parts.scheme}://{parts.netloc}{parts.path}") if parts.scheme else scrub_text(parts.path)
    if request.get("method"):
        out["method"] = str(request["method"])[:10]
    # Header names are kept as a hint of what was sent; their values never are.
    out["headers"] = {k: "[dropped]" for k in (request.get("headers") or {}) if str(k).lower() in ("content-type", "user-agent", "accept")} or {}
    return out


def scrub_event(event: dict[str, Any], hint: Optional[Mapping[str, Any]] = None) -> Optional[dict[str, Any]]:
    """`before_send`. Returns the event with everything a customer's data could be in removed, or None to drop it."""
    try:
        if event.get("request"):
            event["request"] = _scrub_request(event["request"])
        event.pop("user", None)
        event.pop("breadcrumbs", None)
        event.pop("extra", None)
        event.pop("modules", None)
        if isinstance(event.get("message"), str):
            event["message"] = scrub_text(event["message"])
        if event.get("logentry"):
            event["logentry"] = {"message": scrub_text(str(event["logentry"].get("message") or "")), "params": []}
        for exception in (event.get("exception") or {}).get("values") or []:
            if isinstance(exception.get("value"), str):
                exception["value"] = scrub_text(exception["value"])
            for frame in ((exception.get("stacktrace") or {}).get("frames") or []):
                frame.pop("vars", None)
                for key in ("pre_context", "context_line", "post_context"):
                    frame.pop(key, None)       # source lines are our code, but a literal in them could be data: keep the location only
        contexts = event.get("contexts") or {}
        event["contexts"] = {k: v for k, v in contexts.items() if k in ("runtime", "os", "trace")}
        tags = event.get("tags") or {}
        event["tags"] = {k: (v if k in ("service", "job_type", "area", "organization_id", "workspace_id", "attempt", "status_code") else "[dropped]")
                         for k, v in dict(tags).items()}
        event["server_name"] = "servabo"
        return event
    except Exception:  # noqa: BLE001 - if scrubbing itself fails nothing is sent
        logger.warning("error_tracking.scrub_failed", exc_info=True)
        return None


def _before_send(event: dict[str, Any], hint: Mapping[str, Any]) -> Optional[dict[str, Any]]:
    # Tag the customer from the request or job in progress (opaque UUIDs only).
    from app.core import request_context

    org, ws = request_context.get_organization_id(), request_context.get_workspace_id()
    tags = dict(event.get("tags") or {})
    if org:
        tags.setdefault("organization_id", str(org))
    if ws:
        tags.setdefault("workspace_id", str(ws))
    event["tags"] = tags
    return scrub_event(event, hint)


def init(service: str) -> bool:
    """Start error tracking for this process (`api`, `worker`). Does nothing, and imports nothing, when SENTRY_DSN is empty."""
    global _enabled
    from app.core.config import settings

    dsn = (settings.SENTRY_DSN or "").strip()
    if not dsn:
        return False
    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_sdk.init(
        dsn=dsn,
        environment=settings.SENTRY_ENVIRONMENT or settings.ENVIRONMENT,
        release=settings.SENTRY_RELEASE or settings.APP_VERSION,
        traces_sample_rate=float(settings.SENTRY_TRACES_SAMPLE_RATE or 0.0),
        send_default_pii=False,
        include_local_variables=False,
        include_source_context=False,
        max_breadcrumbs=0,
        attach_stacktrace=False,
        send_client_reports=False,
        server_name="servabo",
        default_integrations=True,
        # A logged error is not an unhandled one: only exceptions the code does not handle, and the ones `capture` is given, are sent.
        integrations=[LoggingIntegration(level=None, event_level=None)],
        before_send=_before_send,
        before_send_transaction=lambda event, hint: None,
        max_request_body_size="never",
    )
    sentry_sdk.set_tag("service", service)
    _enabled = True
    logger.info("error_tracking.on", extra={"service": service, "environment": settings.SENTRY_ENVIRONMENT or settings.ENVIRONMENT})
    return True


def enabled() -> bool:
    return _enabled


def shutdown() -> None:
    """Flush and stop (tests, and a clean exit). Safe when never started."""
    global _enabled
    if not _enabled:
        return
    import sentry_sdk

    sentry_sdk.get_client().close(timeout=2.0)
    _enabled = False


def capture(exc: BaseException, *, area: str, **tags: Any) -> None:
    """Report an exception the code caught and could not handle (a job that failed, an email-in message that broke). Never raises."""
    if not _enabled:
        return
    try:
        import sentry_sdk

        with sentry_sdk.new_scope() as scope:
            scope.set_tag("area", area)
            for key, value in tags.items():
                scope.set_tag(key, str(value)[:60])
            sentry_sdk.capture_exception(exc)
    except Exception:  # noqa: BLE001 - error tracking must never be the reason something fails
        logger.debug("error_tracking.capture_failed", exc_info=True)


def ingest_host(dsn: str) -> Optional[str]:
    """The host events are sent to (what the web app's Content-Security-Policy must allow), from a DSN; None for an empty or unreadable one."""
    parts = urlsplit((dsn or "").strip())
    return parts.hostname if parts.scheme in ("https", "http") and parts.hostname else None


__all__ = ["capture", "enabled", "ingest_host", "init", "scrub_event", "scrub_text", "shutdown"]
