"""Final session 1 (3C): Tally Prime, guided. Four answers make a working download target; the shipped mapping uses the customer's own
ledger names; an administrator on the ERP posting plan only."""

from __future__ import annotations

from sqlalchemy import select

from app.models.erp import ErpLookupTable, ErpMapping, ErpTarget
from app.services.erp import vocabulary as v
from tests.engines.conftest import Engines

ANSWERS = {"company": "Meridian Wholesale Pvt Ltd", "purchases": "Packaging Purchases", "cgst": "Input CGST 9%", "sgst": "Input SGST 9%",
           "igst": "Input IGST 18%", "tax": "Input GST"}


def test_the_guided_setup_makes_a_tally_download_target_with_the_customers_ledgers(engines: Engines):
    engines.plan("business")
    response = engines.post("/erp/tally/setup", ANSWERS)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["company"] == "Meridian Wholesale Pvt Ltd"
    engines.db.expire_all()
    target = engines.db.get(ErpTarget, body["target_id"])
    assert (target.format, target.transport, target.auth_mode, target.status) == (v.FORMAT_TALLY, v.TRANSPORT_DOWNLOAD, v.AUTH_NONE, v.TARGET_ACTIVE)
    assert target.config["tally"]["company"] == "Meridian Wholesale Pvt Ltd"
    accounts = engines.db.execute(select(ErpLookupTable).where(
        ErpLookupTable.workspace_id == engines.ws, ErpLookupTable.name == f"{target.config['lookup_prefix']}_accounts")).scalar_one()
    assert accounts.entries == {"default": "Packaging Purchases", "CGST": "Input CGST 9%", "SGST": "Input SGST 9%",
                                "IGST": "Input IGST 18%", "TAX": "Input GST"}
    mappings = engines.db.execute(select(ErpMapping).where(ErpMapping.target_id == target.id)).scalars().all()
    assert {m.object_kind for m in mappings} >= {v.OBJECT_VENDOR_BILL}


def test_unanswered_ledgers_fall_back_to_tallys_usual_names_and_the_company_is_required(engines: Engines):
    engines.plan("business")
    assert engines.post("/erp/tally/setup", {"company": " "}).status_code == 422
    body = engines.post("/erp/tally/setup", {"company": "Acme", "name": "Tally 2"}).json()
    engines.db.expire_all()
    target = engines.db.get(ErpTarget, body["target_id"])
    accounts = engines.db.execute(select(ErpLookupTable).where(
        ErpLookupTable.name == f"{target.config['lookup_prefix']}_accounts")).scalar_one()
    assert accounts.entries["CGST"] == "Input CGST" and accounts.entries["default"] == "Purchase Accounts"
    assert engines.post("/erp/tally/setup", {"company": "Acme", "name": "Tally 2"}).status_code == 409      # the name is taken


def test_only_an_administrator_on_the_erp_posting_plan(engines: Engines):
    engines.plan("business")
    assert engines.post("/erp/tally/setup", ANSWERS, as_user=engines.tenant.contributor).status_code == 403
    engines.plan("developer")
    assert engines.post("/erp/tally/setup", ANSWERS).status_code == 402
