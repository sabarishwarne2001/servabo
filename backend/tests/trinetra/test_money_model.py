"""The whole money model (Final 2T, Phase 5; N-205): credit notes, reversals and corrections in a statement, advances, a sourced
taxable basis, several remittances, the statuses the brief names, and reject and annotate. Conservation holds in every case, a
statement amount is never spent twice, a statement row of another tax year is never matched, and nothing is inferred."""

import hashlib
import uuid
from datetime import date, datetime, timezone

from app.models.helm import HelmBankAccount, HelmBankImport, HelmBankLine, HelmBook
from app.models.trinetra import TrinetraCredit
from app.services.helm import vocabulary as hv
from tests.services.helm import factories
from tests.trinetra.test_api import world  # noqa: F401
from tests.trinetra.test_workflows import setup_case

HEAD = (b"Deductor TAN,Tax credited (INR),Row reference,Section or table item (as printed),Transaction date,Booking status,"
        b"Tax year label (as printed)\n")


def statement(client, tenant, url, body, rows, year="2025"):
    csv = HEAD + b"".join(r.encode() + b"\n" for r in rows)
    r = client.post(url + "/statement-files", headers=tenant.owner.headers,
                    data={"profile_id": body["profile_id"], "year": year, "pan": "ABCDE1234F", "confirmed": "true",
                          "expected_sha256": hashlib.sha256(csv).hexdigest()},
                    files={"file": ("s.csv", csv, "text/csv")})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def decide(client, tenant, url, case, action, **more):
    return client.post(url + f"/credits/{case['id']}/decisions", headers=tenant.owner.headers,
                       json={"revision": more.pop("revision", case["revision"]), "action": action,
                             "reason": more.pop("reason", "Reviewed the evidence and decided."), **more})


def get(client, tenant, url, case):
    return client.get(url + f"/credits/{case['id']}", headers=tenant.owner.headers).json()


def allocate(snapshot, line, amount):
    return {"snapshot_id": snapshot, "line_id": str(line), "amount": amount}


# --- credit notes ------------------------------------------------------------------------------------------------------


def credit_note(db, tenant, number, total, role="CREDIT_NOTE"):
    item = factories.document(db, workspace=tenant.workspace, organization_id=tenant.organization.id, role=role,
                              entities={"vendor_pan": "ABCDE1234F"}, number=number, on=date(2026, 3, 5), total=total, vendor="x")
    db.commit()
    return item


def review(client, tenant, url, case, evidence, **more):
    return client.post(url + f"/credits/{case['id']}/review", headers=tenant.owner.headers,
                       json={"revision": case["revision"], "reason": "Linked the credit note to the invoice.", "evidence": evidence, **more})


def test_a_credit_note_reduces_the_gross_an_expectation_can_rest_on_and_its_amount_is_read_not_typed(client, tenant, world, db_session):
    url, body, case = setup_case(client, tenant, world)
    note = credit_note(db_session, tenant, "CN-1", 18000)
    typed = review(client, tenant, url, case, [{"work_item_id": str(note.id), "kind": "CREDIT_NOTE"}])
    assert typed.status_code == 200, typed.text
    out = get(client, tenant, url, case)
    assert out["credit_notes_micros"] == "18000000000" and out["adjusted_gross_micros"] == "100000000000"
    assert out["gross_micros"] == "118000000000" and out["status"] != "EVIDENCE_NEEDED"      # 2,000 of 1,00,000 is still supported
    other = credit_note(db_session, tenant, "NOT-A-NOTE", 1000, role="OTHER")
    refused = review(client, tenant, url, typed.json(), [{"work_item_id": str(other.id), "kind": "CREDIT_NOTE"}])
    assert refused.status_code == 422 and "credit note" in refused.text.lower()
    too_big = credit_note(db_session, tenant, "CN-BIG", 120000)
    refused = review(client, tenant, url, typed.json(), [{"work_item_id": str(too_big.id), "kind": "CREDIT_NOTE"}])
    assert refused.status_code == 422 and "worth more" in refused.text


def test_credit_notes_that_leave_less_gross_than_the_expectation_make_it_unsupported_until_reconfirmed(client, tenant, world, db_session):
    url, body, case = setup_case(client, tenant, world)
    note = credit_note(db_session, tenant, "CN-2", 117000)
    done = review(client, tenant, url, case, [{"work_item_id": str(note.id), "kind": "CREDIT_NOTE"}])
    assert done.status_code == 200
    out = get(client, tenant, url, case)
    assert out["adjusted_gross_micros"] == "1000000000" and out["status"] == "EVIDENCE_NEEDED" and out["expected_micros"] is None
    reconfirm = client.post(url + f"/credits/{case['id']}/reconfirm", headers=tenant.owner.headers,
                            json={"revision": done.json()["revision"], "amount": "1000", "reason": "Reconfirmed after the credit note."})
    assert reconfirm.status_code == 200 and reconfirm.json()["expected_micros"] == "1000000000"
    assert reconfirm.json()["status"] != "EVIDENCE_NEEDED"


# --- reversals and corrections in a statement --------------------------------------------------------------------------


def test_a_reversal_nets_only_after_a_person_pairs_it_and_an_unpaired_one_stays_an_exception(client, tenant, world, db_session):
    url, body, case = setup_case(client, tenant, world)
    snap = statement(client, tenant, url, body, [
        "ABCD12345E,2000.00,r0,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27",
        "ABCD12345E,-500.00,r1,194C,20-Jun-2025,F,FY 2025-26 / AY 2026-27",
        "MUMB54321K,-300.00,r2,194C,21-Jun-2025,F,FY 2025-26 / AY 2026-27"])
    assert get(client, tenant, url, case)["status"] == "SUGGESTED"        # the 2,000 row alone is still a candidate
    exceptions = client.get(url + "/exceptions", headers=tenant.viewer.headers).json()
    assert exceptions["total"] == 2 and {e["line_id"] for e in exceptions["items"]} == {"1", "2"}
    pair = {"profile_id": body["profile_id"], "snapshot_id": snap, "positive_line": 0, "negative_line": 1,
            "reason": "The 500 reversal is the customer's correction of the 2,000 row."}
    wrong = client.post(url + "/pairings", headers=tenant.owner.headers, json={**pair, "negative_line": 2})
    assert wrong.status_code == 422 and "same deductor" in wrong.text
    both = client.post(url + "/pairings", headers=tenant.owner.headers, json={**pair, "negative_line": 0, "positive_line": 1})
    assert both.status_code == 422
    assert client.post(url + "/pairings", headers=tenant.viewer.headers, json=pair).status_code == 403
    ok = client.post(url + "/pairings", headers=tenant.owner.headers, json=pair)
    assert ok.status_code == 200, ok.text
    assert client.post(url + "/pairings", headers=tenant.owner.headers, json=pair).status_code == 409       # already paired
    assert client.get(url + "/exceptions", headers=tenant.viewer.headers).json()["total"] == 1             # only the unpaired remains
    # The 2,000 row is now worth 1,500: it no longer matches the 2,000 expectation, and 2,000 cannot be allocated.
    assert get(client, tenant, url, case)["status"] == "AMOUNT_MISMATCH"
    over = decide(client, tenant, url, case, "ALLOCATE", allocations=[allocate(snap, 0, "2000")])
    assert over.status_code == 422 and "exceeds" in over.text
    # Withdrawing the pairing restores the row.
    gone = client.post(url + f"/pairings/{ok.json()['id']}/withdraw?profile_id={body['profile_id']}", headers=tenant.owner.headers,
                       json={"reason": "Paired by mistake; the reversal belongs elsewhere."})
    assert gone.status_code == 200 and get(client, tenant, url, case)["status"] == "SUGGESTED"


def test_a_pairing_cannot_shrink_a_row_below_what_is_already_allocated(client, tenant, world, db_session):
    url, body, case = setup_case(client, tenant, world)
    snap = statement(client, tenant, url, body, [
        "ABCD12345E,2000.00,r0,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27",
        "ABCD12345E,-500.00,r1,194C,20-Jun-2025,F,FY 2025-26 / AY 2026-27"])
    assert decide(client, tenant, url, case, "ALLOCATE", allocations=[allocate(snap, 0, "2000")]).status_code == 200
    refused = client.post(url + "/pairings", headers=tenant.owner.headers,
                          json={"profile_id": body["profile_id"], "snapshot_id": snap, "positive_line": 0, "negative_line": 1,
                                "reason": "The reversal belongs to this row, I believe."})
    assert refused.status_code == 409 and "allocated" in refused.text


# --- advances and earlier triggering events -------------------------------------------------------------------------------


def test_an_earlier_period_is_a_persons_decision_with_a_reason_and_evidence_never_inferred(client, tenant, world, db_session):
    url, body, case = setup_case(client, tenant, world)
    receipt = credit_note(db_session, tenant, "ADV-1", 1000, role="OTHER")
    invoice2 = world[2]
    make = {**body, "work_item_id": str(invoice2.id), "reference": "TR-2", "year": 2024}
    plain = client.post(url + "/credits", headers=tenant.owner.headers, json=make)
    assert plain.status_code == 422 and "period" in plain.text                       # a 2024 case for a March 2026 invoice is refused
    event = {"reason": "An advance of 50,000 was received in March 2025 against this order.", "evidence_work_item_id": str(receipt.id)}
    later = client.post(url + "/credits", headers=tenant.owner.headers,
                        json={**make, "year": 2026, "triggering_event": event})
    assert later.status_code == 422 and "before the invoice" in later.text            # a LATER year is not an earlier event
    short = client.post(url + "/credits", headers=tenant.owner.headers,
                        json={**make, "year": 2024, "triggering_event": {**event, "reason": "advance"}})
    assert short.status_code == 422
    ok = client.post(url + "/credits", headers=tenant.owner.headers, json={**make, "year": 2024, "triggering_event": event})
    assert ok.status_code == 422 or ok.status_code == 200
    # world[2] is dated 2026-03-02 (tax year 2025): 2024 is earlier, so the case is accepted.
    assert ok.status_code == 200, ok.text
    out = get(client, tenant, url, ok.json())
    assert out["year"] == 2024 and out["review"]["triggering_event"]["reason"].startswith("An advance")
    assert [e["kind"] for e in out["review"]["evidence"]] == ["TRIGGERING_EVENT"]
    reconfirmed = client.post(url + f"/credits/{ok.json()['id']}/reconfirm", headers=tenant.owner.headers,
                              json={"revision": ok.json()["revision"], "amount": "1500", "reason": "Reconfirmed after the advance receipt."})
    assert reconfirmed.status_code == 200, reconfirmed.text
    # A 2024 case only ever matches rows of tax year 2024.
    snap = statement(client, tenant, url, {**body}, ["ABCD12345E,1500.00,x0,194C,15-Jun-2024,F,FY 2024-25 / AY 2025-26"], year="2024")
    assert get(client, tenant, url, ok.json())["status"] == "SUGGESTED" and snap


# --- a taxable basis, only when sourced -------------------------------------------------------------------------------


def test_the_taxable_basis_is_kept_only_when_a_document_states_it(client, tenant, world, db_session):
    url, body, case = setup_case(client, tenant, world)
    assert get(client, tenant, url, case)["basis_micros"] is None
    advice = credit_note(db_session, tenant, "ADV-2", 1, role="OTHER")
    basis = {"amount": "100000", "source": "DEDUCTOR_ADVICE", "evidence_work_item_id": str(advice.id)}
    not_attached = review(client, tenant, url, case, [], basis=basis)
    assert not_attached.status_code == 422 and "stated by" in not_attached.text
    ok = review(client, tenant, url, case, [{"work_item_id": str(advice.id), "kind": "DEDUCTOR_ADVICE", "amount": "2000"}], basis=basis)
    assert ok.status_code == 200, ok.text
    out = get(client, tenant, url, case)
    assert out["basis_micros"] == "100000000000" and out["basis_source"] == "DEDUCTOR_ADVICE"
    # It survives a later review update, and clearing it is explicit. It is never derived from the gross, the bank or GST.
    again = review(client, tenant, url, ok.json(), [{"work_item_id": str(advice.id), "kind": "DEDUCTOR_ADVICE", "amount": "2000"}])
    assert again.status_code == 200 and get(client, tenant, url, case)["basis_micros"] == "100000000000"
    cleared = review(client, tenant, url, again.json(), [], clear_basis=True)
    assert cleared.status_code == 200 and get(client, tenant, url, case)["basis_micros"] is None


# --- several remittances ----------------------------------------------------------------------------------------------


def bank_lines(db, tenant, work_item, amounts, currency="INR"):
    book = db.query(HelmBook).filter_by(workspace_id=tenant.workspace.id).first()
    if book is None:
        book = HelmBook(organization_id=tenant.organization.id, workspace_id=tenant.workspace.id, kind=hv.BOOK_WORKSPACE,
                        name="Engineering", status=hv.BOOK_ACTIVE)
        db.add(book)
        db.flush()
    account = db.query(HelmBankAccount).filter_by(book_id=book.id).first()
    if account is None:
        account = HelmBankAccount(organization_id=book.organization_id, book_id=book.id, name="HDFC", last4="7766", currency="INR")
        db.add(account)
        db.flush()
    imported = HelmBankImport(organization_id=book.organization_id, book_id=book.id, bank_account_id=account.id,
                              filename="s.csv", sha256=uuid.uuid4().hex + uuid.uuid4().hex, lines_read=len(amounts), lines_new=len(amounts), lines_matched=len(amounts))
    db.add(imported)
    db.flush()
    for n, amount in enumerate(amounts):
        db.add(HelmBankLine(organization_id=book.organization_id, book_id=book.id, bank_account_id=account.id, import_id=imported.id,
                            line_no=n + 1, on_date=date(2026, 3, 10 + n), description="NEFT", reference=f"r{n}", amount_micros=amount * 1_000_000,
                            currency=currency, fingerprint=uuid.uuid4().hex + uuid.uuid4().hex, status="MATCHED",
                            workspace_id=tenant.workspace.id, work_item_id=work_item.id))
    db.commit()


def test_several_remittances_add_up_and_a_figure_helm_cannot_give_is_unknown(client, tenant, world, db_session):
    url, body, case = setup_case(client, tenant, world)
    assert get(client, tenant, url, case)["cash_projection"]["cash_received_micros"] is None        # nothing matched: unknown, not zero
    bank_lines(db_session, tenant, world[1], [60000, 40000, 16000])
    projection = get(client, tenant, url, case)["cash_projection"]
    assert projection["cash_received_micros"] == "116000000000"
    # A matched receipt in another currency makes the total unknown: it is never silently left out.
    bank_lines(db_session, tenant, world[1], [10], currency="USD")
    assert get(client, tenant, url, case)["cash_projection"]["cash_received_micros"] is None


# --- the statuses the brief names ------------------------------------------------------------------------------------------


def test_duplicate_late_corrected_and_unresolved_are_reachable_and_leave_correctly(client, tenant, world, db_session):
    url, body, case = setup_case(client, tenant, world)
    twin = "ABCD12345E,2000.00,{n},194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27"
    snap = statement(client, tenant, url, body, [twin.format(n="a"), twin.format(n="b")])
    assert get(client, tenant, url, case)["status"] == "DUPLICATE_SUSPECTED"
    # A person rejects one twin (with a reason, on the case's current revision): it is not offered again for that snapshot.
    stale = decide(client, tenant, url, case, "REJECT_MATCH", snapshot_id=snap, line_id="1", revision=99)
    assert stale.status_code == 409
    rejected = decide(client, tenant, url, case, "REJECT_MATCH", snapshot_id=snap, line_id="1", reason="The second row is the deductor's duplicate booking.")
    assert rejected.status_code == 200, rejected.text
    out = get(client, tenant, url, case)
    assert out["status"] == "SUGGESTED" and out["candidate_ids"] == ["0"] and out["review_state"] == "OPEN"
    # Annotate the match with a note: recorded in the history, the case state unchanged.
    noted = decide(client, tenant, url, rejected.json(), "ANNOTATE", note="Matches the customer's Form 16A of 30 July.",
                   reason="Added the 16A reference for the accountant.")
    assert noted.status_code == 200 and noted.json()["review_state"] == "OPEN"
    assert decide(client, tenant, url, noted.json(), "ANNOTATE", reason="Missing the text of the note here.").status_code == 422
    row = db_session.query(TrinetraCredit).one()
    assert row.review["annotations"][0]["text"].startswith("Matches the customer's") and len(row.review["rejected_candidates"]) == 1
    actions = [e["action"] for e in get(client, tenant, url, case)["events"]]
    assert "REJECT_MATCH" in actions and "ANNOTATE" in actions
    # Allocate the remaining row; it was booked in the year it belongs to, so it is POSTED.
    done = decide(client, tenant, url, noted.json(), "ALLOCATE", allocations=[allocate(snap, 0, "2000")])
    assert done.status_code == 200 and done.json()["status"] == "POSTED"
    # Unresolved: closed without resolution, with a reason; reopening brings it back to work.
    closed = decide(client, tenant, url, done.json(), "REOPEN", reason="Reopened to close it as unresolved instead.")
    assert closed.status_code == 200
    unresolved = decide(client, tenant, url, closed.json(), "UNRESOLVED", reason="The customer never answered; nothing more to do.")
    assert unresolved.status_code == 200 and unresolved.json()["status"] == "UNRESOLVED" and unresolved.json()["review_state"] == "UNRESOLVED"
    back = decide(client, tenant, url, unresolved.json(), "REOPEN", reason="The customer replied after all.")
    assert back.status_code == 200 and back.json()["review_state"] == "OPEN"


def test_a_late_booking_and_a_verified_correction_have_their_own_statuses(client, tenant, world, db_session):
    url, body, case = setup_case(client, tenant, world)
    # Transaction dated in FY 2025-26, booked after the year end (in Tax Year 2026-27).
    csv = HEAD + b"ABCD12345E,2000.00,l0,194C,10-Feb-2026,F,FY 2025-26 / AY 2026-27\n"
    template = (b"Deductor TAN,Tax credited (INR),Row reference,Section or table item (as printed),Transaction date,Booking status,"
                b"Tax year label (as printed)\n")
    assert csv.startswith(template)
    # `Date of booking` is printed by the Form 26AS text download; here we write it through that reader's shape.
    txt = (b"^File Creation Date^Permanent Account Number (PAN)^Current Status of PAN^Financial Year^Assessment Year^Name of Assessee^\n"
           b"^28-10-2026^ABCDE1234F^Active^2025-26^2026-27^X^\n^PART-A - Details of Tax Deducted at Source^\n"
           b"^Sr. No.^Name of Deductor^TAN of Deductor^Total Amount Paid/ Credited(Rs.)^Total Tax Deducted(Rs.)^Total TDS Deposited(Rs.)^\n"
           b"^1^C^ABCD12345E^100000.00^2000.00^2000.00^\n"
           b"^^Sr. No.^Section^Transaction Date^Status of Booking^Date of Booking^Remarks^Amount Paid / Credited(Rs.)^Tax Deducted(Rs.)^TDS Deposited(Rs.)^\n"
           b"^^1^194C^10-Feb-2026^F^20-May-2026^-^100000.00^2000.00^2000.00^\n")
    r = client.post(url + "/statement-files", headers=tenant.owner.headers,
                    data={"profile_id": body["profile_id"], "year": "2025", "pan": "ABCDE1234F", "confirmed": "true",
                          "expected_sha256": hashlib.sha256(txt).hexdigest()}, files={"file": ("AS.txt", txt, "text/plain")})
    assert r.status_code == 200, r.text
    done = decide(client, tenant, url, case, "ALLOCATE", allocations=[allocate(r.json()["id"], 0, "2000")])
    assert done.status_code == 200 and done.json()["status"] == "LATE_POSTING"
    summary = client.get(url + "/summary", headers=tenant.owner.headers).json()
    assert summary["unresolved"] == 0                      # posted, even if late
    # A correction response attached BEFORE the snapshot that shows the posting makes it VERIFIED_CORRECTED.
    correction = credit_note(db_session, tenant, "CORR-1", 1, role="OTHER")
    attached = review(client, tenant, url, done.json(), [{"work_item_id": str(correction.id), "kind": "CORRECTION_RESPONSE"}])
    assert attached.status_code == 200
    assert get(client, tenant, url, case)["status"] == "LATE_POSTING"        # the correction came AFTER the posting appeared
    # A newer statement imported AFTER the correction response shows the posting: verified corrected.
    newer = statement(client, tenant, url, body, ["ABCD12345E,2000.00,n0,194C,10-Feb-2026,F,FY 2025-26 / AY 2026-27",
                                                  "MUMB54321K,10.00,n1,194C,10-Feb-2026,F,FY 2025-26 / AY 2026-27"])
    current = get(client, tenant, url, case)
    assert current["status"] in ("SUGGESTED", "PENDING_REPORT", "POSSIBLE_MISSING_POSTING", "AMOUNT_MISMATCH")
    final = decide(client, tenant, url, current, "ALLOCATE", allocations=[allocate(newer, 0, "2000")])
    assert final.status_code == 200 and final.json()["status"] == "VERIFIED_CORRECTED"
    ca = decide(client, tenant, url, final.json(), "CA_REVIEWED", reason="Accountant reviewed the corrected posting.")
    assert ca.status_code == 200 and ca.json()["review_state"] == "CA_REVIEWED"


def test_each_unpaired_reversal_lists_the_rows_it_could_reverse_so_a_person_can_choose(client, tenant, world, db_session):
    url, body, case = setup_case(client, tenant, world)
    statement(client, tenant, url, body, [
        "ABCD12345E,2000.00,r0,194C,15-Jun-2025,F,FY 2025-26 / AY 2026-27",
        "ABCD12345E,-500.00,r1,194C,20-Jun-2025,F,FY 2025-26 / AY 2026-27",
        "MUMB54321K,900.00,r2,194C,21-Jun-2025,F,FY 2025-26 / AY 2026-27",
        "MUMB54321K,-300.00,r3,194C,22-Jun-2025,F,FY 2025-26 / AY 2026-27"])
    exceptions = client.get(url + "/exceptions", headers=tenant.viewer.headers).json()["items"]
    by_line = {e["line_id"]: e for e in exceptions}
    assert set(by_line) == {"1", "3"}
    assert [c["line_id"] for c in by_line["1"]["candidates"]] == ["0"]              # same deductor only, never the other customer's row
    assert [c["line_id"] for c in by_line["3"]["candidates"]] == ["2"]
    first = by_line["1"]["candidates"][0]
    assert first["amount_micros"] == "2000000000" and first["reference"] == "r0" and "deductor_key" not in str(first)
