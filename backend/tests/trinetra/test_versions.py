"""'Changed' means the evidence changed, not that its row was touched (Final 2T, Phase 1.2).

An invoice, a piece of evidence or a statement is versioned by a fingerprint of what it is: the stored file, the extracted
fields TRINETRA reads and the DocumentRole facts (role, total, currency, date); a statement by its stored file. A rename, a
summary, a tag, a reprocess with the same fields or a no-op healing leaves it current."""

import copy
from datetime import date, datetime, timedelta, timezone

from tests.trinetra.test_api import world  # noqa: F401
from tests.trinetra.test_helm_adapter import confirmed_case
from tests.trinetra.test_workflows import import_and_allocate
from app.models.document_role import DocumentRole


def touch(db, item):
    """Everything an automation, a rename, batch healing or a same-fields reprocess does to a document."""
    item.original_filename = "renamed-by-an-automation.pdf"
    item.summary = "A summary set by an automation."
    item.extracted_entities = copy.deepcopy(item.extracted_entities)  # reprocess with the same fields
    item.updated_at = datetime.now(timezone.utc) + timedelta(seconds=5)
    db.commit()


def case(client, tenant, path):
    return client.get(path, headers=tenant.owner.headers).json()


def test_touching_the_invoice_or_the_statement_leaves_a_posted_case_posted(client, tenant, world, db_session):
    url, _, credit, _, _ = import_and_allocate(client, tenant, world)
    path = url + "/credits/" + credit["id"]
    assert case(client, tenant, path)["status"] == "POSTED"
    touch(db_session, world[1])
    touch(db_session, world[2])
    after = case(client, tenant, path)
    assert after["status"] == "POSTED" and after["source_current"] is True
    assert after["posted_micros"] == "2000000000" and after["expected_micros"] == "2000000000"


def test_touching_a_piece_of_evidence_keeps_a_confirmed_withholding_confirmed(client, tenant, world, db_session):
    path, _, _ = confirmed_case(client, tenant, world)
    touch(db_session, world[2])
    touch(db_session, world[1])
    projection = case(client, tenant, path)["cash_projection"]
    assert projection["reviewed_withholding_micros"] == "2000000000"


def test_a_corrected_field_a_different_file_or_a_changed_total_makes_the_invoice_stale(client, tenant, world, db_session):
    url, _, credit, _, _ = import_and_allocate(client, tenant, world)
    path = url + "/credits/" + credit["id"]
    invoice = world[1]
    # A field TRINETRA reads is corrected.
    invoice.extracted_entities = {**invoice.extracted_entities, "vendor_pan": "ZZZZZ9999Z"}
    db_session.commit()
    assert case(client, tenant, path)["source_current"] is False
    invoice.extracted_entities = {**invoice.extracted_entities, "vendor_pan": "ABCDE1234F"}
    db_session.commit()
    assert case(client, tenant, path)["source_current"] is True  # back to what was reviewed
    # A different file.
    original = invoice.stored_filename
    invoice.stored_filename = original + ".v2"
    db_session.commit()
    assert case(client, tenant, path)["source_current"] is False
    invoice.stored_filename = original
    db_session.commit()
    # A changed total in the DocumentRole facts.
    role = db_session.query(DocumentRole).filter_by(work_item_id=invoice.id).one()
    role.total_micros = role.total_micros + 1_000_000
    db_session.commit()
    assert case(client, tenant, path)["source_current"] is False


def test_a_changed_statement_file_makes_the_snapshot_unusable_but_a_rename_does_not(client, tenant, world, db_session):
    url, _, credit, _, _ = import_and_allocate(client, tenant, world)
    path = url + "/credits/" + credit["id"]
    statement = world[2]
    touch(db_session, statement)
    assert case(client, tenant, path)["status"] == "POSTED"
    statement.stored_filename = statement.stored_filename + ".v2"
    db_session.commit()
    after = case(client, tenant, path)
    assert after["status"] == "PENDING_REPORT" and after["posted_micros"] == "0"
