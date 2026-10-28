"""Is the invoice's seller the receiving entity? (Final 2T, Phase 1.3)

Every PAN is normalized; the PAN is also derived from a valid seller GSTIN (characters 3 to 12); every identity the
invoice offers is compared, and a refusal names the field that disagrees (never the value). A match by name alone needs the
reviewer's explicit confirmation, recorded in the case history. Odd input is a 422, never a 500."""

from datetime import date

from tests.trinetra.test_api import world  # noqa: F401
from app.services.gst import builder as b
from tests.services.helm import factories

PAN = "ABCDE1234F"
MATCHING_GSTIN = b.make_gstin("27", PAN)
OTHER_GSTIN = b.make_gstin("27", "AABCS5555K")


def profile(client, tenant, world):
    r = client.post(world[0] + "/profiles", headers=tenant.owner.headers, json={"name": "Synthetic Ltd", "pan": PAN})
    assert r.status_code == 200, r.text
    return r.json()["id"]


def invoice(db, tenant, number, **entities):
    name = entities.pop("seller", "Synthetic Ltd")
    item = factories.invoice(db, workspace=tenant.workspace, organization_id=tenant.organization.id, number=number,
                             supplier=name, amount=118000, on=date(2026, 3, 1), extra=entities)
    db.commit()
    return item


def attempt(client, tenant, world, item, profile_id, **more):
    body = {"profile_id": profile_id, "work_item_id": str(item.id), "year": 2025, "counterparty": "Customer",
            "reference": f"R-{item.id}", "tan": "ABCD12345E", "amount": "2000",
            "source_confirmation": "Reviewed explicitly sourced withholding against the invoice.", **more}
    return client.post(world[0] + "/credits", headers=tenant.owner.headers, json=body)


def test_a_printed_pan_is_normalized_before_it_is_compared(client, tenant, world, db_session):
    pid = profile(client, tenant, world)
    item = invoice(db_session, tenant, "N-1", vendor_pan="abcde 1234-f")
    assert attempt(client, tenant, world, item, pid).status_code == 200


def test_the_pan_is_derived_from_a_valid_seller_gstin(client, tenant, world, db_session):
    pid = profile(client, tenant, world)
    ok = invoice(db_session, tenant, "G-1", vendor_gstin=MATCHING_GSTIN)
    assert attempt(client, tenant, world, ok, pid).status_code == 200
    wrong = invoice(db_session, tenant, "G-2", vendor_gstin=OTHER_GSTIN)
    r = attempt(client, tenant, world, wrong, pid)
    assert r.status_code == 422 and "vendor_gstin" in r.text
    assert OTHER_GSTIN not in r.text and "AABCS5555K" not in r.text


def test_every_identity_the_invoice_offers_must_agree_and_the_field_that_disagrees_is_named(client, tenant, world, db_session):
    pid = profile(client, tenant, world)
    clash = invoice(db_session, tenant, "C-1", vendor_pan=PAN, vendor_gstin=OTHER_GSTIN)
    r = attempt(client, tenant, world, clash, pid)
    assert r.status_code == 422 and "vendor_gstin" in r.text and "vendor_pan" not in r.text.split("disagree")[0]
    agree = invoice(db_session, tenant, "C-2", vendor_pan=PAN, vendor_gstin=MATCHING_GSTIN)
    assert attempt(client, tenant, world, agree, pid).status_code == 200
    wrong_pan = invoice(db_session, tenant, "C-3", vendor_pan="ZZZZZ9999Z")
    r = attempt(client, tenant, world, wrong_pan, pid)
    assert r.status_code == 422 and "vendor_pan" in r.text and "ZZZZZ9999Z" not in r.text


def test_a_match_by_name_alone_needs_the_reviewers_explicit_confirmation_and_is_recorded(client, tenant, world, db_session):
    pid = profile(client, tenant, world)
    item = invoice(db_session, tenant, "NM-1")  # no PAN and no GSTIN printed
    refused = attempt(client, tenant, world, item, pid)
    assert refused.status_code == 422 and "TRINETRA_SELLER_NAME_ONLY" in refused.text
    confirmed = attempt(client, tenant, world, item, pid, seller_name_confirmed=True)
    assert confirmed.status_code == 200, confirmed.text
    detail = client.get(world[0] + "/credits/" + confirmed.json()["id"], headers=tenant.owner.headers).json()
    assert any("name only" in (e.get("reason") or "").lower() for e in detail["events"])


def test_odd_input_is_a_422_never_a_500(client, tenant, world, db_session):
    pid = profile(client, tenant, world)
    for value in ("ÀBCDE1234F", "ＡＢＣＤＥ１２３４Ｆ", "ABCDE1234F" * 20, "\x00ABCDE1234F", 12345):
        item = invoice(db_session, tenant, f"O-{abs(hash(str(value)))}", vendor_pan=value)
        r = attempt(client, tenant, world, item, pid)
        assert r.status_code == 422, (value, r.status_code, r.text)
    bad = client.post(world[0] + "/profiles", headers=tenant.owner.headers, json={"name": "X", "pan": "ÀBCDE1234F"})
    assert bad.status_code == 422
