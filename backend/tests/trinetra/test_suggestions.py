"""Expectations from the records a business already has (Final 2T, Phase 4; N-204).

Printed hints, the expectations template (the bridge for Tally users) and the deductor directory. A suggestion is only ever a
suggestion: it becomes a case when a person accepts it, with a reason. Nothing a document or a file says confirms anything."""

import io
import uuid
from datetime import date

from app.models.trinetra import TrinetraCredit, TrinetraDeductor, TrinetraSuggestion
from app.services.trinetra.statements import expectations
from tests.services.gst.helpers import book_invoice
from tests.trinetra.test_api import world, SUPPLIER_A  # noqa: F401
from tests.trinetra.test_workflows import setup_case

HINT = {"vendor_pan": "ABCDE1234F", "tds_amount": "2000", "deductor_tan": "ABCD12345E", "tds_section": "194C",
        "bill_to": "First Customer Pvt Ltd"}


def profile(client, tenant, world):
    r = client.post(world[0] + "/profiles", headers=tenant.owner.headers, json={"name": "Synthetic Ltd", "pan": "ABCDE1234F"})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def invoice(db, tenant, number, **extra):
    item = book_invoice(db, tenant, number=number, supplier="a", gstin=SUPPLIER_A, on=date(2026, 3, 1), taxable=100000,
                        extra={**HINT, **extra})
    db.commit()
    return item


def scan(client, tenant, world, pid):
    r = client.post(world[0] + "/suggestions/scan", headers=tenant.owner.headers, json={"profile_id": pid})
    assert r.status_code == 200, r.text
    return r.json()


def listed(client, tenant, world, **q):
    suffix = "&".join(f"{k}={v}" for k, v in q.items())
    return client.get(world[0] + "/suggestions" + ("?" + suffix if suffix else ""), headers=tenant.viewer.headers).json()


def accept(client, tenant, world, sid, **more):
    return client.post(world[0] + f"/suggestions/{sid}/accept", headers=tenant.owner.headers,
                       json={"source_confirmation": "Checked the printed TDS against the customer's advice.", **more})


def test_a_printed_hint_becomes_a_suggestion_never_a_case(client, tenant, world, db_session):
    pid = profile(client, tenant, world)
    item = invoice(db_session, tenant, "H-1")
    assert scan(client, tenant, world, pid)["created"] == 1
    out = listed(client, tenant, world)
    assert out["total"] == 1
    s = out["items"][0]
    assert s["source"] == "PRINTED_HINT" and s["status"] == "OPEN" and s["amount_micros"] == "2000000000"
    assert s["tan_masked"] == "******345E" and s["section_text"] == "194C" and s["counterparty"] == "First Customer Pvt Ltd"
    assert s["work_item_id"] == str(item.id) and "ABCD12345E" not in str(out)
    assert db_session.query(TrinetraCredit).count() == 0          # nothing was confirmed
    # Re-scanning an unchanged invoice changes nothing.
    assert scan(client, tenant, world, pid) | {} == {"created": 0, "refreshed": 0, "unchanged": 1, "skipped": 0} | {}


def test_an_amount_over_the_gross_a_foreign_seller_or_an_existing_case_is_not_suggested(client, tenant, world, db_session):
    pid = profile(client, tenant, world)
    invoice(db_session, tenant, "X-1", tds_amount="999999999")                      # more than the gross
    invoice(db_session, tenant, "X-2", vendor_pan="ZZZZZ9999Z")                    # another seller
    invoice(db_session, tenant, "X-3", tds_amount="not an amount")                 # unreadable
    counts = scan(client, tenant, world, pid)
    assert counts["created"] == 0 and counts["skipped"] == 3


def test_a_dismissed_suggestion_stays_dismissed_until_its_evidence_changes(client, tenant, world, db_session):
    pid = profile(client, tenant, world)
    item = invoice(db_session, tenant, "D-1")
    scan(client, tenant, world, pid)
    sid = listed(client, tenant, world)["items"][0]["id"]
    short = client.post(world[0] + f"/suggestions/{sid}/dismiss", headers=tenant.owner.headers, json={"reason": "no"})
    assert short.status_code == 422
    done = client.post(world[0] + f"/suggestions/{sid}/dismiss", headers=tenant.owner.headers,
                       json={"reason": "The customer says nothing was withheld on this invoice."})
    assert done.status_code == 200 and done.json()["status"] == "DISMISSED"
    scan(client, tenant, world, pid)
    assert listed(client, tenant, world)["items"][0]["status"] == "DISMISSED"
    item.extracted_entities = {**item.extracted_entities, "tds_amount": "2500"}      # the printed figure was corrected
    db_session.commit()
    assert scan(client, tenant, world, pid)["refreshed"] == 1
    again = listed(client, tenant, world)["items"][0]
    assert again["status"] == "OPEN" and again["amount_micros"] == "2500000000"


def test_accepting_needs_a_reason_makes_a_case_with_its_origin_and_maps_the_deductor(client, tenant, world, db_session):
    pid = profile(client, tenant, world)
    invoice(db_session, tenant, "A-1")
    scan(client, tenant, world, pid)
    sid = listed(client, tenant, world)["items"][0]["id"]
    assert client.post(world[0] + f"/suggestions/{sid}/accept", headers=tenant.viewer.headers,
                       json={"source_confirmation": "Checked the printed TDS against the advice."}).status_code == 403
    assert accept(client, tenant, world, sid, source_confirmation="short").status_code == 422
    ok = accept(client, tenant, world, sid)
    assert ok.status_code == 200, ok.text
    case = db_session.query(TrinetraCredit).one()
    assert case.expected_micros == 2_000_000_000 and case.review["origin"] == "suggestion:PRINTED_HINT"
    assert case.review["section_text"] == "194C" and case.counterparty == "First Customer Pvt Ltd"
    assert accept(client, tenant, world, sid).status_code == 409                    # already decided
    assert listed(client, tenant, world)["items"][0]["status"] == "ACCEPTED"
    mapping = db_session.query(TrinetraDeductor).one()
    assert mapping.status == "PROPOSED" and mapping.tan_masked == "******345E" and mapping.counterparty_name == "First Customer Pvt Ltd"
    history = client.get(world[0] + f"/credits/{ok.json()['id']}", headers=tenant.owner.headers).json()["events"]
    assert history[0]["action"] == "EXPECTATION_CONFIRMED" and "Checked the printed TDS" in history[0]["reason"]


def test_a_changed_invoice_cannot_be_accepted_on_the_old_suggestion(client, tenant, world, db_session):
    pid = profile(client, tenant, world)
    item = invoice(db_session, tenant, "S-1")
    scan(client, tenant, world, pid)
    sid = listed(client, tenant, world)["items"][0]["id"]
    item.stored_filename += ".replaced"
    db_session.commit()
    r = accept(client, tenant, world, sid)
    assert r.status_code == 409 and "changed" in r.text


def test_a_tan_seen_under_two_customers_is_flagged_and_blocks_acceptance_until_a_person_resolves_it(client, tenant, world, db_session):
    pid = profile(client, tenant, world)
    invoice(db_session, tenant, "T-1")
    invoice(db_session, tenant, "T-2", bill_to="A Different Customer Ltd")
    scan(client, tenant, world, pid)
    items = listed(client, tenant, world)["items"]
    assert len(items) == 2
    mapping = client.get(world[0] + "/deductors", headers=tenant.viewer.headers).json()["items"]
    assert len(mapping) == 1 and mapping[0]["status"] == "FLAGGED" and mapping[0]["seen_as"]
    assert "ABCD12345E" not in str(mapping)
    blocked = accept(client, tenant, world, items[0]["id"])
    assert blocked.status_code == 409 and "TRINETRA_DEDUCTOR_FLAGGED" in blocked.text
    resolved = client.post(world[0] + f"/deductors/{mapping[0]['id']}/confirm", headers=tenant.owner.headers,
                           json={"counterparty": "First Customer Pvt Ltd", "reason": "The TAN is the first customer's; the other is a trade name."})
    assert resolved.status_code == 200 and resolved.json()["status"] == "CONFIRMED" and resolved.json()["seen_as"] == []
    assert accept(client, tenant, world, items[0]["id"]).status_code == 200


def test_the_directory_is_confirmed_by_a_person_and_never_shows_a_tan(client, tenant, world, db_session):
    pid = profile(client, tenant, world)
    r = client.post(world[0] + "/deductors", headers=tenant.owner.headers,
                    json={"profile_id": pid, "tan": "ABCD12345E", "counterparty": "First Customer Pvt Ltd",
                          "reason": "From the customer's Form 16A, checked by the accountant."})
    assert r.status_code == 200 and r.json()["status"] == "CONFIRMED" and r.json()["tan_masked"] == "******345E"
    assert "ABCD12345E" not in r.text
    assert client.post(world[0] + "/deductors", headers=tenant.viewer.headers,
                       json={"profile_id": pid, "tan": "ABCD12345E", "counterparty": "x", "reason": "A long enough reason."}).status_code == 403


def build_template(rows):
    import csv

    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow(expectations.COLUMNS)
    writer.writerows(rows)
    return out.getvalue().encode()


def test_the_expectations_template_previews_each_row_and_creates_suggestions_only(client, tenant, world, db_session):
    pid = profile(client, tenant, world)
    invoice(db_session, tenant, "TPL-1", tds_amount="1", deductor_tan="ABCD12345E")       # printed hint differs; the template wins
    invoice(db_session, tenant, "TPL-2")
    invoice(db_session, tenant, "TPL-DUP")
    invoice(db_session, tenant, "TPL-DUP")
    body = build_template([
        ["TPL-1", "ABCD12345E", "2,000.00", "194C"],
        ["MISSING", "ABCD12345E", "100.00", ""],
        ["TPL-DUP", "ABCD12345E", "100.00", ""],
        ["TPL-2", "ABCD12345E", "9,99,99,999.00", ""],
    ])
    files = {"file": ("expected.csv", body, "text/csv")}
    preview = client.post(world[0] + "/suggestions/template/preview", headers=tenant.owner.headers, data={"profile_id": pid}, files=files)
    assert preview.status_code == 200, preview.text
    statuses = {r["reference"]: r["status"] for r in preview.json()["items"]}
    assert statuses == {"TPL-1": "OK", "MISSING": "NOT_FOUND", "TPL-DUP": "AMBIGUOUS", "TPL-2": "TDS_EXCEEDS_GROSS"}
    assert "ABCD12345E" not in preview.text
    refused = client.post(world[0] + "/suggestions/template", headers=tenant.owner.headers, data={"profile_id": pid}, files=files)
    assert refused.status_code == 422 and "TRINETRA_TEMPLATE_ROWS_REFUSED" in refused.text
    assert db_session.query(TrinetraSuggestion).count() == 0
    done = client.post(world[0] + "/suggestions/template", headers=tenant.owner.headers,
                       data={"profile_id": pid, "skip_refused": "true"}, files=files)
    assert done.status_code == 200 and done.json() == {"created": 1, "refreshed": 0, "skipped": 3}
    suggestion = db_session.query(TrinetraSuggestion).one()
    assert suggestion.source == "TEMPLATE" and suggestion.amount_micros == 2_000_000_000 and suggestion.status == "OPEN"
    assert db_session.query(TrinetraCredit).count() == 0


def test_a_bad_expectations_row_is_refused_with_its_number_and_the_template_downloads(client, tenant, world):
    pid = profile(client, tenant, world)
    for rows, fragment in ((["T", "BADTAN", "1.00", ""], "TAN"), (["T", "ABCD12345E", "abc", ""], "amount"),
                           (["T", "ABCD12345E", "0", ""], "positive")):
        r = client.post(world[0] + "/suggestions/template/preview", headers=tenant.owner.headers, data={"profile_id": pid},
                        files={"file": ("e.csv", build_template([rows]), "text/csv")})
        assert r.status_code == 422 and "Row 2" in r.text and fragment.lower() in r.text.lower(), r.text
    for fmt in ("csv", "xlsx"):
        assert client.get(world[0] + f"/suggestion-template.{fmt}", headers=tenant.viewer.headers).status_code == 200


def test_the_printed_section_travels_with_the_case_and_blocks_a_different_printed_section(client, tenant, world, db_session):
    pid = profile(client, tenant, world)
    invoice(db_session, tenant, "SEC-1", tds_section="194Q")
    scan(client, tenant, world, pid)
    sid = listed(client, tenant, world)["items"][0]["id"]
    case = accept(client, tenant, world, sid).json()
    import hashlib
    csv = (b"Deductor TAN,Tax credited (INR),Row reference,Section or table item (as printed),Transaction date,Booking status\n"
           b"ABCD12345E,2000.00,r1,194C,15-Jun-2025,F\n")
    imported = client.post(world[0] + "/statement-files", headers=tenant.owner.headers,
                           data={"profile_id": pid, "year": "2025", "pan": "ABCDE1234F", "confirmed": "true",
                                 "expected_sha256": hashlib.sha256(csv).hexdigest()}, files={"file": ("t.csv", csv, "text/csv")})
    assert imported.status_code == 200, imported.text
    detail = client.get(world[0] + f"/credits/{case['id']}", headers=tenant.owner.headers).json()
    assert detail["status"] != "SUGGESTED" and detail["candidate_ids"] == []      # 194Q on the case, 194C on the row
