"""The Tally Prime file on Starter, through the API (Final session 2A, N-187, closes N-174).

Starter includes the Tally file without ERP posting: it sets up Tally, sees only its Tally targets and postings, and is
refused any other ERP target or a Zoho Books connection with the upgrade moment naming Business.
"""

from __future__ import annotations

from tests.engines.conftest import Engines

ANSWERS = {"company": "Acme Traders", "purchases": "Purchase Accounts", "cgst": "Input CGST", "sgst": "Input SGST",
           "igst": "Input IGST"}


def test_starter_sets_up_tally_and_sees_only_tally_targets(engines: Engines):
    engines.plan("business")
    other = engines.post("/erp/targets", {"name": "CSV export", "format": "CSV", "transport": "DOWNLOAD"})
    assert other.status_code == 201, other.text
    engines.plan("developer")
    made = engines.post("/erp/tally/setup", ANSWERS)
    assert made.status_code == 201, made.text
    listed = engines.get("/erp/targets")
    assert listed.status_code == 200, listed.text
    assert [t["id"] for t in listed.json()["items"]] == [made.json()["target_id"]], "a CSV target is ERP posting"
    assert engines.get(f"/erp/targets/{made.json()['target_id']}").status_code == 200
    assert engines.get(f"/erp/targets/{other.json()['target']['id']}").status_code == 402
    assert engines.get("/erp/postings").status_code == 200
    assert engines.get("/erp/catalog").status_code == 200


def test_starter_is_refused_any_other_erp_target_naming_business(engines: Engines):
    engines.plan("developer")
    refused = engines.post("/erp/targets", {"name": "CSV export", "format": "CSV", "transport": "DOWNLOAD"})
    assert refused.status_code == 402, refused.text
    body = refused.json()
    assert body["details"]["capability_name"] == "ERP posting" and body["details"]["remedy"] == "PLAN_UPGRADE"
    assert body["details"]["included_in"], "the refusal names the plans that include ERP posting"
    zoho = engines.post("/erp/zoho/connect", {})
    assert zoho.status_code == 402, zoho.text


def test_free_has_no_tally_file(engines: Engines):
    engines.plan("free")
    assert engines.post("/erp/tally/setup", ANSWERS).status_code == 402
