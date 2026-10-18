"""scripts/dodo_probe.py against the stand-in Dodo (Session C, C2).

The probe is what the owner runs on their own PC against a real Dodo TEST account. These tests prove
it on the stand-in: what it reports for a healthy account, that it only ever sends GET, that it never
prints customer data, that a difference is named, and that it refuses live mode.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from tests.fakes.fake_dodo import FakeDodo

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dodo_probe.py"
OWNER_EMAIL = "private.person@example.com"


def _script():
    spec = importlib.util.spec_from_file_location("dodo_probe_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module  # dataclasses look their module up there
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def account():
    """A stand-in Dodo with two products, one paid subscription and its payment."""
    dodo = FakeDodo()
    developer = dodo.add_product(name="Servabo Developer (per seat, monthly)", price=4_900)
    dodo.add_product(name="Servabo Business (per seat, monthly)", price=29_900)
    checkout = dodo.checkout(product_id=developer, quantity=3, email=OWNER_EMAIL,
                             metadata={"organization_id": "org-secret-123", "quota_tier_key": "developer",
                                       "client_reference_id": "ref-secret-456"})
    subscription = dodo.pay(checkout)
    payment = next(iter(dodo.payments.values()))
    with dodo.serving() as base_url:
        yield dodo, {"DODO_API_KEY": "dodo_test_key_for_probe", "DODO_API_BASE": base_url}, subscription, payment


def _run(args: list[str], environ: dict[str, str], capsys) -> tuple[int, str]:
    code = _script().main(args, environ)
    return code, capsys.readouterr().out


def _point(out: str, number: int) -> str:
    return next(line for line in out.splitlines() if line.startswith(f"  {number:>2}."))


@pytest.mark.parametrize("environ", [
    {"DODO_LIVEMODE": "true", "DODO_API_KEY": "k"},
    {"DODO_LIVEMODE": "1", "DODO_API_KEY": "k"},
    {"DODO_API_KEY": "k", "DODO_API_BASE": "https://live.dodopayments.com"},
])
def test_live_mode_is_refused_before_any_call(environ, capsys) -> None:
    code, out = _run([], environ, capsys)
    assert code == 2 and "TEST account only" in out


def test_the_live_host_is_refused_even_when_passed_on_the_command_line(capsys) -> None:
    code, out = _run(["--api-base", "https://live.dodopayments.com"], {"DODO_API_KEY": "k"}, capsys)
    assert code == 2 and "TEST account only" in out


def test_a_missing_key_is_explained(capsys) -> None:
    code, out = _run([], {}, capsys)
    assert code == 2 and "DODO_API_KEY is not set" in out


def test_a_refused_key_stops_with_a_plain_message(account, capsys) -> None:
    dodo, environ, _, _ = account
    dodo.failures["/products"] = 401
    code, out = _run([], environ, capsys)
    assert code == 2 and "refused the key" in out and "TEST key" in out


def test_a_healthy_account_matches_and_says_what_it_could_not_check(account, capsys) -> None:
    dodo, environ, subscription, payment = account
    code, out = _run(["--subscription-id", subscription["subscription_id"], "--after-plan-change",
                      "--payment-id", payment["payment_id"]], environ, capsys)
    assert code == 0, out
    assert "matches" in _point(out, 1) and "subscription_id, refunds[] and disputes[] are present" in _point(out, 1)
    assert "matches" in _point(out, 4) and "organization_id" in _point(out, 4)
    assert "matches" in _point(out, 6) and "page_number moves to the next product" in _point(out, 6)
    for number, needs in {2: "POST", 3: "POST", 5: "browser", 7: "DODO_LIVEMODE", 8: "retry", 9: "--webhook-file", 10: "pricing"}.items():
        line = _point(out, number)
        assert "not checked" in line and needs in line, line
    assert "PDF" in out and "Nothing differs. 3 of 10 points matched" in out
    # The shape is shown: field names with types, and the plain labels.
    assert "expected  price.price: integer" in out and "expected  refunds: array" in out
    assert "next_billing_date: timestamp  (ISO 8601 UTC with Z)" in out
    assert "metadata: object  keys: client_reference_id, organization_id, quota_tier_key" in out
    assert "status: string  = active" in out


def test_it_sends_only_get_requests(account, capsys) -> None:
    dodo, environ, subscription, payment = account
    _run(["--subscription-id", subscription["subscription_id"], "--payment-id", payment["payment_id"]], environ, capsys)
    assert dodo.calls, "the probe asked Dodo nothing"
    assert {method for method, _, _ in dodo.calls} == {"GET"}
    assert not [path for _, path, _ in dodo.calls if path.startswith("/_fake")]
    # What it asked for: the list (with paging), one product, a subscription, a payment, an invoice.
    paths = [path for _, path, _ in dodo.calls]
    assert "/products" in paths and any(p.startswith("/products/pdt_") for p in paths)
    assert f"/subscriptions/{subscription['subscription_id']}" in paths
    assert f"/payments/{payment['payment_id']}" in paths
    assert f"/invoices/payments/{payment['payment_id']}" in paths


def test_the_class_that_talks_to_dodo_has_no_way_to_write() -> None:
    methods = {name for name in vars(_script().ReadOnlyDodo) if not name.startswith("_")}
    assert methods == {"get", "get_json"}


def test_no_customer_data_is_printed(account, capsys) -> None:
    dodo, environ, subscription, payment = account
    dodo.refund(payment["payment_id"], amount=1_000)
    dodo.dispute(payment["payment_id"])
    customer = next(iter(dodo.customers.values()))
    _, out = _run(["--subscription-id", subscription["subscription_id"], "--payment-id", payment["payment_id"]],
                  environ, capsys)
    for private in (OWNER_EMAIL, "private.person", customer["customer_id"], subscription["subscription_id"],
                    payment["payment_id"], "org-secret-123", "ref-secret-456", "4242", "dodo_test_key_for_probe",
                    str(payment["total_amount"]), "Servabo Developer"):
        assert private not in out, private


def test_a_refunded_and_disputed_payment_shows_those_fields(account, capsys) -> None:
    dodo, environ, subscription, payment = account
    dodo.refund(payment["payment_id"], amount=1_000)
    dodo.dispute(payment["payment_id"], status="dispute_lost")
    code, out = _run(["--payment-id", payment["payment_id"]], environ, capsys)
    assert code == 0, out
    assert "refunds[].status: string" in out and "disputes[].dispute_id: string" in out
    assert "disputes[].dispute_status: string  = dispute_lost" in out
    assert "matches" in _point(out, 1) and "payment, refunds and disputes are all there" in _point(out, 1)


def test_without_ids_the_other_points_say_what_they_need(account, capsys) -> None:
    _, environ, _, _ = account
    code, out = _run([], environ, capsys)
    assert code == 0
    assert "pass --payment-id" in _point(out, 1)
    assert "--subscription-id and --after-plan-change" in _point(out, 4)
    assert "matches" in _point(out, 6)


def test_a_payment_without_its_subscription_id_differs(account, capsys) -> None:
    dodo, environ, _, payment = account
    dodo.payments[payment["payment_id"]]["subscription_id"] = None
    code, out = _run(["--payment-id", payment["payment_id"]], environ, capsys)
    assert code == 1
    assert "differs: subscription_id is null, Servabo reads string" in _point(out, 1)
    assert "1 point(s) differ" in out


def test_metadata_lost_in_a_plan_change_differs(account, capsys) -> None:
    dodo, environ, subscription, _ = account
    dodo.subscriptions[subscription["subscription_id"]]["metadata"] = {"client_reference_id": "x"}
    code, out = _run(["--subscription-id", subscription["subscription_id"], "--after-plan-change"], environ, capsys)
    assert code == 1
    line = _point(out, 4)
    assert "differs" in line and "organization_id, quota_tier_key" in line and "client_reference_id" not in line.split("carries")[1]


def test_a_subscription_with_a_different_shape_is_named(account, capsys) -> None:
    dodo, environ, subscription, _ = account
    stored = dodo.subscriptions[subscription["subscription_id"]]
    stored["quantity"] = "3"            # a string, not a number
    stored.pop("next_billing_date")     # missing
    code, out = _run(["--subscription-id", subscription["subscription_id"]], environ, capsys)
    assert code == 1
    assert "quantity is string, Servabo reads integer" in out and "next_billing_date is missing" in out


def test_an_unknown_id_is_reported_not_crashed_on(account, capsys) -> None:
    _, environ, _, _ = account
    code, out = _run(["--subscription-id", "sub_nope", "--payment-id", "pay_nope"], environ, capsys)
    assert code == 1
    assert "no subscription with that id" in out and "no payment with that id" in out


def test_paging_that_dodo_ignores_differs() -> None:
    probe_module = _script()

    class IgnoresPaging:
        def get_json(self, path, params=None):
            if path == "/products":
                return {"items": [{"product_id": f"pdt_{i}"} for i in range(3)]}
            return {"product_id": "pdt_0", "is_recurring": True, "tax_category": "saas",
                    "price": {"type": "recurring_price", "price": 1, "currency": "USD", "tax_inclusive": False,
                              "payment_frequency_interval": "Month", "payment_frequency_count": 1}}

    lines: list[str] = []
    probe = probe_module.Probe(IgnoresPaging(), say=lines.append)
    probe.products(None, 100)
    assert probe.points[6].status == "differs"
    assert "page_size=1 was ignored" in probe.points[6].detail


def test_an_empty_account_asks_for_the_test_products(account, capsys) -> None:
    dodo, environ, _, _ = account
    dodo.products.clear()
    code, out = _run([], environ, capsys)
    assert code == 0 and "dodo_setup.py --create-test-products" in out


def _webhook(tmp_path: Path, body: dict) -> Path:
    path = tmp_path / "webhook.json"
    path.write_text(json.dumps(body), encoding="utf-8")
    return path


def test_a_captured_webhook_checks_the_timestamp_and_the_livemode_flag(account, tmp_path, capsys) -> None:
    dodo, environ, subscription, payment = account
    body = json.loads(dodo.outbox[-1].body)
    code, out = _run(["--webhook-file", str(_webhook(tmp_path, body))], environ, capsys)
    assert code == 0, out
    assert "matches" in _point(out, 9) and "ISO 8601 UTC with Z" in _point(out, 9)
    assert body["data"]["customer"]["email"] not in out and OWNER_EMAIL not in out

    code, out = _run(["--webhook-file", str(_webhook(tmp_path, {**body, "livemode": False}))], environ, capsys)
    assert code == 1 and "carries a livemode flag" in _point(out, 9)

    code, out = _run(["--webhook-file", str(_webhook(tmp_path, {**body, "timestamp": 1_760_000_000}))], environ, capsys)
    assert code == 1 and "timestamp is integer, Servabo reads timestamp" in _point(out, 9)


@pytest.mark.parametrize("written, expected", [
    ("2026-10-18T10:00:00Z", "ISO 8601 UTC with Z"),
    ("2026-10-18T10:00:00+05:30", "ISO 8601 with offset"),
    ("2026-10-18T10:00:00", "ISO 8601 without a time zone (read as UTC)"),
    ("18 October 2026", None),
    ("sub_2026-10-18", None),
])
def test_timestamp_formats_are_told_apart(written, expected) -> None:
    assert _script().timestamp_format(written) == expected
