"""Read-only probe of a Dodo Payments TEST account (Session C, C2).

    python scripts/dodo_probe.py                                   # products only
    python scripts/dodo_probe.py --subscription-id sub_… --payment-id pay_…
    python scripts/dodo_probe.py --subscription-id sub_… --after-plan-change
    python scripts/dodo_probe.py --webhook-file captured-webhook.json

docs/billing/DODO.md section 6 lists ten things Servabo assumes about Dodo that were built from Dodo's
documentation and proven only against the stand-in (`tests/fakes/fake_dodo.py`). This script asks a real
Dodo TEST account the questions it can ask without changing anything, and says, for each of the ten
points, one of:

    matches                 what Dodo answered is what Servabo reads
    differs: …              what is different, in words
    not checked (…)         why the probe cannot judge it, and what to do instead

READ ONLY. It sends GET requests and nothing else (the one HTTP helper below has no other verb, and the
tests assert the stand-in saw nothing but GETs). It asks for: the products list (with paging), one
product, a subscription, a payment, and the invoice of that payment.

NO PERSONAL DATA IN THE OUTPUT. It prints the SHAPE of each answer: field names and types. The only
values it ever prints are a short list of plain labels that carry no customer information (a status
such as "active", a currency code, a billing interval, a tax category, true/false flags) and the
NAMES of the keys inside `metadata`. Ids, e-mail addresses, names, amounts and metadata values are
never printed, so the output can be pasted into a chat or an issue.

TEST MODE ONLY. Like dodo_setup.py it refuses when DODO_LIVEMODE is true or the base is Dodo's live
host. `--api-base` points it at a local stand-in (the tests use `fake_dodo.py`).

Exit status: 0 nothing differs (points that cannot be checked are listed, not failed);
1 something differs or an id was not found; 2 refused (live mode / no key) or Dodo could not be reached.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence

LIVE_HOST = "https://live.dodopayments.com"
TEST_HOST = "https://test.dodopayments.com"

#: The only field NAMES whose value is printed: plain labels with no customer information.
PRINTABLE_VALUES = frozenset({
    "status", "dispute_status", "currency", "payment_frequency_interval", "tax_category", "type",
    "payload_type", "is_recurring", "tax_inclusive", "cancel_at_next_billing_date",
})

#: The keys the checkout puts in `metadata` (docs/billing/DODO.md section 2).
METADATA_KEYS = ("organization_id", "quota_tier_key", "client_reference_id")


class ProbeError(RuntimeError):
    """Dodo could not be asked (network, key refused)."""


class NotFound(ProbeError):
    """Dodo answered 404 for an id."""


# ---------------------------------------------------------------------------- the one door to Dodo


class ReadOnlyDodo:
    """Dodo's API through GET requests only. There is deliberately no other method on this class."""

    def __init__(self, *, api_key: str, api_base: str) -> None:
        import httpx

        self._http = httpx.Client(base_url=api_base.rstrip("/"), timeout=20, follow_redirects=False,
                                  headers={"Authorization": f"Bearer {api_key}"})

    def get(self, path: str, params: Optional[Mapping[str, Any]] = None) -> tuple[int, str, bytes]:
        try:
            response = self._http.get(path, params=params)
        except Exception as exc:  # noqa: BLE001 - reported in words
            raise ProbeError(f"Could not reach Dodo: {exc}") from exc
        if response.status_code in (401, 403):
            raise ProbeError(f"Dodo refused the key (HTTP {response.status_code}). Check that DODO_API_KEY is the "
                             "TEST key (Developer > API keys, with Test Mode on).")
        return response.status_code, response.headers.get("content-type", ""), response.content

    def get_json(self, path: str, params: Optional[Mapping[str, Any]] = None) -> Any:
        status, _, content = self.get(path, params)
        if status == 404:
            raise NotFound(path)
        if status >= 400:
            raise ProbeError(f"Dodo answered HTTP {status} for GET {path.split('?')[0]}.")
        try:
            return json.loads(content)
        except ValueError as exc:
            raise ProbeError(f"Dodo's answer for GET {path} is not JSON.") from exc


# ---------------------------------------------------------------------------- shapes


def _type_of(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "timestamp" if timestamp_format(value) else "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def timestamp_format(value: Any) -> Optional[str]:
    """How a timestamp is written, or None if it is not one. Matches what Servabo's parser accepts."""
    if not isinstance(value, str) or len(value) < 10 or not value[:4].isdigit() or value[4] != "-":
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.endswith("Z"):
        return "ISO 8601 UTC with Z"
    return "ISO 8601 with offset" if parsed.tzinfo is not None else "ISO 8601 without a time zone (read as UTC)"


def flatten(value: Any, prefix: str = "") -> dict[str, tuple[str, Any]]:
    """Every field path of `value` with its type. Lists are described by their first entry (`refunds[].amount`)."""
    found: dict[str, tuple[str, Any]] = {}
    if isinstance(value, dict):
        for key, inner in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            found[path] = (_type_of(inner), inner)
            if key == "metadata":
                continue  # its values are customer-controlled; only its key names are reported
            found.update(flatten(inner, path))
    elif isinstance(value, list) and value:
        found.update(flatten(value[0], f"{prefix}[]"))
        found[f"{prefix}[]"] = (_type_of(value[0]), value[0])
    return found


@dataclass(frozen=True)
class Field:
    path: str
    types: tuple[str, ...]
    required: bool = True


def _fields(*rows: tuple[str, str] | tuple[str, str, bool]) -> tuple[Field, ...]:
    return tuple(Field(r[0], tuple(r[1].split("|")), r[2] if len(r) == 3 else True) for r in rows)  # type: ignore[misc]


#: What Servabo reads from each answer (dodo_gateway.py `fetch_subscription`, `fetch_payment`, and
#: `scripts/dodo_setup.py` for products). "timestamp" is a string that parses as an ISO 8601 instant.
PRODUCT_FIELDS = _fields(
    ("product_id", "string"), ("is_recurring", "boolean"), ("tax_category", "string"), ("price", "object"),
    ("price.type", "string"), ("price.price", "integer"), ("price.currency", "string"),
    ("price.payment_frequency_interval", "string"), ("price.payment_frequency_count", "integer"),
    ("price.tax_inclusive", "boolean"),
)
SUBSCRIPTION_FIELDS = _fields(
    ("subscription_id", "string"), ("status", "string"), ("customer", "object"), ("customer.customer_id", "string"),
    ("customer.email", "string", False), ("product_id", "string"), ("quantity", "integer"),
    ("previous_billing_date", "timestamp"), ("next_billing_date", "timestamp"),
    ("cancel_at_next_billing_date", "boolean"), ("cancelled_at", "timestamp|null", False),
    ("currency", "string"), ("metadata", "object"),
)
PAYMENT_FIELDS = _fields(
    ("payment_id", "string"), ("status", "string"), ("subscription_id", "string"), ("customer", "object"),
    ("customer.customer_id", "string"), ("currency", "string"), ("total_amount", "integer"), ("tax", "integer"),
    ("created_at", "timestamp"), ("refunds", "array"), ("disputes", "array"),
)
REFUND_FIELDS = _fields(("refunds[].amount", "integer|string"), ("refunds[].status", "string"))  # a number or a numeric string: both are read
DISPUTE_FIELDS = _fields(("disputes[].dispute_id", "string"), ("disputes[].dispute_status", "string"),
                         ("disputes[].amount", "integer|string"))
WEBHOOK_FIELDS = _fields(("business_id", "string"), ("type", "string"), ("timestamp", "timestamp"),
                         ("data", "object"), ("data.payload_type", "string"))


def compare(found: Mapping[str, tuple[str, Any]], expected: Sequence[Field]) -> list[str]:
    """Plain-words differences between an answer's shape and what Servabo reads (empty: they match)."""
    problems: list[str] = []
    for item in expected:
        if item.path not in found:
            if item.required:
                problems.append(f"{item.path} is missing")
            continue
        actual = found[item.path][0]
        if actual not in item.types and not (actual == "timestamp" and "string" in item.types):
            problems.append(f"{item.path} is {actual}, Servabo reads {' or '.join(item.types)}")
    return problems


def render_shape(found: Mapping[str, tuple[str, Any]], expected: Sequence[Field], say: Callable[[str], None]) -> None:
    """One line per field: its name, its type (and a plain label where that carries no customer data)."""
    wanted = {item.path for item in expected}
    for path in sorted(found, key=lambda p: (p not in wanted, p)):
        type_name, value = found[path]
        leaf = path.rsplit(".", 1)[-1].replace("[]", "")
        note = ""
        if type_name == "timestamp":
            note = f"  ({timestamp_format(value)})"
        elif leaf in PRINTABLE_VALUES and type_name in ("string", "boolean"):
            note = f"  = {str(value).lower() if isinstance(value, bool) else value}"
        elif type_name == "object" and leaf == "metadata":
            note = f"  keys: {', '.join(sorted(map(str, value))) or '(none)'}"
        elif type_name == "array":
            note = f"  ({len(value)} entr{'y' if len(value) == 1 else 'ies'})"
        mark = "expected" if path in wanted else "extra   "
        say(f"      {mark}  {path}: {type_name}{note}")


# ---------------------------------------------------------------------------- results


@dataclass
class Point:
    number: int
    title: str
    status: str = "not checked"  # matches | differs | not checked
    detail: str = ""

    def line(self) -> str:
        if self.status == "matches":
            return f"  {self.number:>2}. matches        {self.title}" + (f" ({self.detail})" if self.detail else "")
        if self.status == "differs":
            return f"  {self.number:>2}. differs: {self.detail}   [{self.title}]"
        return f"  {self.number:>2}. not checked ({self.detail})   [{self.title}]"


def _points() -> dict[int, Point]:
    titles = {
        1: "GET /payments/{id} carries subscription_id, refunds[] and disputes[]",
        2: "change-plan accepts an empty answer, do_not_bill and on_payment_failure",
        3: "the preview's total_amount is the amount charged",
        4: "metadata survives a plan change",
        5: "the return URL carries subscription_id and status",
        6: "GET /products pages with page_size / page_number; GET /products/{id} has the full price",
        7: "a live key and a test key cannot be told apart from the key",
        8: "Dodo's payment-retry window for an on-hold subscription",
        9: "webhook timestamp format, and no livemode flag in the body",
        10: "the fee figures",
    }
    points = {n: Point(n, t) for n, t in titles.items()}
    points[2].detail = "needs a POST; do journey 'upgrade' and 'scheduled downgrade' in docs/billing/DODO-LOCAL-TEST.md"
    points[3].detail = "needs a POST; do journey 'upgrade' (the preview amount against the charged amount)"
    points[4].detail = "needs a subscription that has been upgraded: pass --subscription-id and --after-plan-change"
    points[5].detail = "a browser journey: do 'checkout success' and read the address Dodo returns to"
    points[7].detail = "no read-only call can tell; Servabo relies on DODO_LIVEMODE and the host, and this probe refuses a live setting"
    points[8].detail = "needs a declined renewal and Dodo's dashboard; read Dodo's retry settings by hand"
    points[9].detail = "needs a captured webhook body: pass --webhook-file"
    points[10].detail = "from Dodo's pricing page; compare by hand"
    return points


# ---------------------------------------------------------------------------- the probe


@dataclass
class Probe:
    dodo: ReadOnlyDodo
    say: Callable[[str], None] = print
    points: dict[int, Point] = field(default_factory=_points)
    errors: list[str] = field(default_factory=list)

    def _set(self, number: int, problems: Sequence[str], detail: str = "") -> None:
        point = self.points[number]
        point.status = "differs" if problems else "matches"
        point.detail = "; ".join(problems) if problems else detail

    # -- products (point 6)
    def products(self, product_id: Optional[str], page_size: int) -> None:
        self.say("\nProducts")
        problems: list[str] = []
        self.say(f"  GET /products?page_size={page_size}&page_number=0")
        first = self.dodo.get_json("/products", {"page_size": page_size, "page_number": 0})
        items = first.get("items") if isinstance(first, dict) else None
        if not isinstance(items, list):
            problems.append("the answer is not {items: […]}")
            items = []
        else:
            self.say(f"    answered {{items: […]}} with {len(items)} product(s)")
        if len(items) > page_size:
            problems.append(f"page_size={page_size} was ignored ({len(items)} products came back)")

        # Paging proof: one product per page. Two different pages must give two different products.
        paging = ""
        if isinstance(first, dict) and isinstance(items, list):
            one = self.dodo.get_json("/products", {"page_size": 1, "page_number": 0})
            two = self.dodo.get_json("/products", {"page_size": 1, "page_number": 1})
            ones, twos = (one.get("items") if isinstance(one, dict) else None), (two.get("items") if isinstance(two, dict) else None)
            if not isinstance(ones, list) or not isinstance(twos, list):
                problems.append("a one-product page does not answer {items: […]}")
            elif len(ones) > 1 or len(twos) > 1:
                problems.append("page_size=1 was ignored (more than one product came back)")
            elif len(items) >= 2:
                first_id = (ones[0] or {}).get("product_id") if ones else None
                second_id = (twos[0] or {}).get("product_id") if twos else None
                if not first_id or not second_id or first_id == second_id:
                    problems.append("page_number did not move to a different product")
                else:
                    paging = "page_number moves to the next product"
            else:
                paging = "the account has fewer than two products, so page_number could only be shown to be accepted"

        chosen = product_id or next((str(i.get("product_id")) for i in items if isinstance(i, dict) and i.get("product_id")), None)
        if chosen is None:
            self.say("  No product to read: create the test products first (python scripts/dodo_setup.py --create-test-products).")
            self.points[6].detail = "the account has no products yet; run dodo_setup.py --create-test-products and probe again"
            if problems:
                self._set(6, problems)
            return
        self.say("  GET /products/{id}  (one product)")
        try:
            product = self.dodo.get_json(f"/products/{chosen}")
        except NotFound:
            self.errors.append("that product id was not found in this account")
            self.say("    Dodo has no product with that id.")
            return
        found = flatten(product)
        render_shape(found, PRODUCT_FIELDS, self.say)
        problems += compare(found, PRODUCT_FIELDS)
        self._set(6, problems, paging)

    # -- subscription (point 4)
    def subscription(self, subscription_id: str, after_plan_change: bool) -> None:
        self.say("\nSubscription")
        self.say("  GET /subscriptions/{id}")
        try:
            raw = self.dodo.get_json(f"/subscriptions/{subscription_id}")
        except NotFound:
            self.errors.append("that subscription id was not found in this account")
            self.say("    Dodo has no subscription with that id (is it from the TEST dashboard?).")
            return
        found = flatten(raw)
        render_shape(found, SUBSCRIPTION_FIELDS, self.say)
        problems = compare(found, SUBSCRIPTION_FIELDS)
        shape_note = "the fields Servabo reads are all there"
        if problems:
            self.say("    differs: " + "; ".join(problems))
        else:
            self.say(f"    matches: {shape_note}")
        if after_plan_change:
            metadata = raw.get("metadata") if isinstance(raw, dict) and isinstance(raw.get("metadata"), dict) else {}
            lost = [key for key in METADATA_KEYS if key not in metadata]
            self._set(4, [f"after the plan change, metadata no longer carries {', '.join(lost)}"] if lost else [],
                      "metadata still carries organization_id, quota_tier_key and client_reference_id")
            if lost:
                self.points[4].detail += " (Servabo falls back to the product id, so nothing breaks; the checkout key is gone)"
        elif problems:
            self.errors.append("the subscription's shape differs from what Servabo reads")

    # -- payment (point 1) and invoice
    def payment(self, payment_id: str) -> None:
        self.say("\nPayment")
        self.say("  GET /payments/{id}")
        try:
            raw = self.dodo.get_json(f"/payments/{payment_id}")
        except NotFound:
            self.errors.append("that payment id was not found in this account")
            self.say("    Dodo has no payment with that id (is it from the TEST dashboard?).")
            return
        found = flatten(raw)
        expected = list(PAYMENT_FIELDS)
        notes: list[str] = []
        if isinstance(raw.get("refunds"), list) and raw["refunds"]:
            expected += REFUND_FIELDS
        else:
            notes.append("refund entries not read (this payment has none)")
        if isinstance(raw.get("disputes"), list) and raw["disputes"]:
            expected += DISPUTE_FIELDS
        else:
            notes.append("dispute entries not read (this payment has none)")
        render_shape(found, expected, self.say)
        problems = compare(found, expected)
        self._set(1, problems, "payment, refunds and disputes are all there")
        if not problems and notes:
            self.points[1].detail = ("subscription_id, refunds[] and disputes[] are present; " + "; ".join(notes)
                                     + "; pass a refunded or disputed payment to read them")

        self.say("\nInvoice")
        self.say("  GET /invoices/payments/{payment_id}")
        status, content_type, content = self.dodo.get("/invoices/payments/" + payment_id)
        if status == 404:
            self.say("    Dodo has no invoice for that payment (a failed payment has none).")
        elif status >= 400:
            self.errors.append(f"the invoice call answered HTTP {status}")
            self.say(f"    HTTP {status}")
        elif content.startswith(b"%PDF"):
            self.say(f"    a PDF of {len(content):,} bytes ({content_type or 'no content type'}): matches what Servabo expects")
        else:
            self.errors.append("the invoice is not a PDF")
            self.say(f"    differs: not a PDF ({content_type or 'no content type'})")

    # -- a captured webhook (point 9)
    def webhook(self, path: Path) -> None:
        self.say("\nCaptured webhook")
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.errors.append("the webhook file could not be read as JSON")
            self.say("    The file is not JSON.")
            return
        if not isinstance(body, dict):
            self.errors.append("the webhook file is not a JSON object")
            return
        found = flatten(body)
        render_shape(found, WEBHOOK_FIELDS, self.say)
        problems = compare(found, WEBHOOK_FIELDS)
        written = timestamp_format(body.get("timestamp"))
        if "livemode" in body or "data.livemode" in found:
            problems.append("the body carries a livemode flag")
        self._set(9, problems, f"timestamp is {written or 'not an ISO 8601 string'}; no livemode flag in the body")


# ---------------------------------------------------------------------------- the command


def _base(args_base: Optional[str], environ: Mapping[str, str]) -> str:
    return (args_base or environ.get("DODO_API_BASE") or TEST_HOST).strip().rstrip("/")


def main(argv: Optional[list[str]] = None, environ: Optional[Mapping[str, str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Read-only probe of a Dodo Payments TEST account.")
    parser.add_argument("--subscription-id", help="a subscription from your test account")
    parser.add_argument("--payment-id", help="a payment from your test account (a refunded or disputed one shows more)")
    parser.add_argument("--product-id", help="a product to read (default: the first in the list)")
    parser.add_argument("--after-plan-change", action="store_true",
                        help="say that --subscription-id has been through a plan change (checks point 4)")
    parser.add_argument("--webhook-file", type=Path, help="a webhook body saved as JSON (checks point 9)")
    parser.add_argument("--page-size", type=int, default=100, help="products per page for the list call (default 100)")
    parser.add_argument("--api-base", help=f"default: DODO_API_BASE, else {TEST_HOST}")
    args = parser.parse_args(argv)
    env = dict(os.environ if environ is None else environ)

    base = _base(args.api_base, env)
    if str(env.get("DODO_LIVEMODE", "")).strip().lower() in ("1", "true", "yes", "on") or base == LIVE_HOST:
        print("Refused: this probe works on a Dodo TEST account only. Unset DODO_LIVEMODE and use the "
              f"test host ({TEST_HOST}).")
        return 2
    api_key = (env.get("DODO_API_KEY") or "").strip()
    if not api_key:
        print("DODO_API_KEY is not set. Copy the TEST key from Dodo's dashboard (Developer > API keys, "
              "with Test Mode on) into backend/.env or the shell, then run this again.")
        return 2
    if args.after_plan_change and not args.subscription_id:
        print("--after-plan-change needs --subscription-id.")
        return 2

    probe = Probe(ReadOnlyDodo(api_key=api_key, api_base=base))
    print(f"Dodo test account at {base}. Read-only: only GET requests are sent. Shapes are printed, never customer data.")
    try:
        probe.products(args.product_id, max(1, args.page_size))
        if args.subscription_id:
            probe.subscription(args.subscription_id, args.after_plan_change)
        if args.payment_id:
            probe.payment(args.payment_id)
    except ProbeError as exc:
        print(f"\n{exc}")
        return 2
    if args.webhook_file:
        probe.webhook(args.webhook_file)
    if not args.payment_id:
        probe.points[1].detail = "needs a payment id: pass --payment-id from a payment in the test dashboard"
    if not args.subscription_id and not probe.points[4].detail.startswith("needs a subscription"):
        probe.points[4].detail = "needs a subscription that has been upgraded: pass --subscription-id and --after-plan-change"

    print("\nThe ten points in docs/billing/DODO.md section 6:")
    for number in sorted(probe.points):
        print(probe.points[number].line())
    differs = [p for p in probe.points.values() if p.status == "differs"]
    for message in probe.errors:
        print(f"\nProblem: {message}.")
    if differs or probe.errors:
        print(f"\n{len(differs)} point(s) differ" + (f" and {len(probe.errors)} problem(s) need attention" if probe.errors else "")
              + ". Record them in docs/billing/DODO-LOCAL-TEST.md (the results table).")
        return 1
    checked = sum(1 for p in probe.points.values() if p.status == "matches")
    print(f"\nNothing differs. {checked} of 10 points matched; the others need the journeys (docs/billing/DODO-LOCAL-TEST.md).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
