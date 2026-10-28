"""Statement files through the same preview, confirm and import path as typed rows (Final 2T, Phase 3; N-203)."""

import hashlib
from pathlib import Path

from app.models.trinetra import TrinetraStatement
from tests.security.plans import put_on_plan
from tests.trinetra.test_api import world  # noqa: F401
from tests.trinetra.test_workflows import setup_case

FIXTURES = Path(__file__).parents[1] / "fixtures" / "trinetra"


def blob(name):
    return (FIXTURES / name).read_bytes()


def form(body, **more):
    return {"profile_id": body["profile_id"], "year": "2025", "pan": "ABCDE1234F", **more}


def post(client, tenant, url, path, name, data, content=None):
    content = blob(name) if content is None else content
    return client.post(url + path, headers=tenant.owner.headers, data=data,
                       files={"file": (name, content, "application/octet-stream")})


def test_the_template_downloads_as_csv_and_excel_for_anyone_who_can_read(client, tenant, world):
    for fmt, magic in (("csv", b"\xef\xbb\xbfDeductor TAN"), ("xlsx", b"PK")):
        r = client.get(world[0] + f"/statement-template.{fmt}", headers=tenant.viewer.headers)
        assert r.status_code == 200 and r.content.startswith(magic) and "attachment" in r.headers["content-disposition"]


def test_a_form_26as_text_file_is_previewed_confirmed_and_imported_then_allocated(client, tenant, world, db_session):
    url, body, case = setup_case(client, tenant, world)
    preview = post(client, tenant, url, "/statement-files/preview", "form26as_sample.txt", form(body))
    assert preview.status_code == 200, preview.text
    out = preview.json()
    assert out["reader"] == "form26as-text-v1" and out["official"] and out["verified"] is False
    assert out["tax_year_label"].startswith("FY 2025-26") and out["year_matches"] and out["file_pan_matches"] is True
    assert out["rows"] == 3 and out["total_micros"] == "4250000000" and "Unverified reader" in out["notice"]
    assert {d["tan_masked"] for d in out["deductors"]} == {"******345E", "******321K"}
    assert "ABCDE1234F" not in preview.text and "ABCD12345E" not in preview.text      # no PAN or TAN in the response
    assert any(c["name"].endswith("TDS deposited") and c["ok"] for c in out["checks"])
    imported = post(client, tenant, url, "/statement-files", "form26as_sample.txt",
                    form(body, confirmed="true", expected_sha256=out["sha256"]))
    assert imported.status_code == 200, imported.text
    snap = db_session.get(TrinetraStatement, imported.json()["id"])
    assert snap.source_work_item_id is None and snap.source_sha256 == out["sha256"] and snap.active
    assert snap.parser_version == "form26as-text-v1" and snap.source_meta["verified"] is False
    assert snap.rows[0]["section"] == "194C" and snap.rows[0]["on"] == "2025-06-15"
    # The case now sees the file's rows and says how they were read.
    detail = client.get(url + "/credits/" + case["id"], headers=tenant.owner.headers).json()
    assert detail["statement_reader"]["verified"] is False and detail["statement_reader"]["tax_year_label"].startswith("FY 2025-26")
    decision = {"revision": case["revision"], "action": "ALLOCATE", "reason": "Reviewed the previewed file and the invoice.",
                "allocations": [{"snapshot_id": imported.json()["id"], "line_id": "0", "amount": "2000"}]}
    allocated = client.post(url + f"/credits/{case['id']}/decisions", headers=tenant.owner.headers, json=decision)
    assert allocated.status_code == 200 and allocated.json()["status"] == "POSTED"


def test_the_file_must_be_the_one_previewed_and_for_this_entity_and_year(client, tenant, world, db_session):
    url, body, _ = setup_case(client, tenant, world)
    sha = hashlib.sha256(blob("form26as_sample.txt")).hexdigest()
    other = post(client, tenant, url, "/statement-files", "form26as_sample.txt", form(body, confirmed="true", expected_sha256="0" * 64))
    assert other.status_code == 422
    unconfirmed = post(client, tenant, url, "/statement-files", "form26as_sample.txt", form(body, confirmed="false", expected_sha256=sha))
    assert unconfirmed.status_code == 422
    wrong_year = post(client, tenant, url, "/statement-files", "form26as_sample.txt",
                      {**form(body, confirmed="true", expected_sha256=sha), "year": "2024"})
    assert wrong_year.status_code == 422 and "TRINETRA_FILE_YEAR_DIFFERS" in wrong_year.text
    swapped = blob("form26as_sample.txt").replace(b"ABCDE1234F", b"ZZZZZ9999Z")
    wrong_pan = post(client, tenant, url, "/statement-files", "form26as_sample.txt",
                     form(body, confirmed="true", expected_sha256=hashlib.sha256(swapped).hexdigest()), content=swapped)
    assert wrong_pan.status_code == 422 and "TRINETRA_FILE_PAN_DIFFERS" in wrong_pan.text and "ZZZZZ9999Z" not in wrong_pan.text
    assert db_session.query(TrinetraStatement).count() == 0


def test_a_tax_year_file_is_never_taken_for_a_financial_year(client, tenant, world):
    url, body, _ = setup_case(client, tenant, world)
    sha = hashlib.sha256(blob("form168_sample.txt")).hexdigest()
    r = post(client, tenant, url, "/statement-files", "form168_sample.txt", form(body, confirmed="true", expected_sha256=sha))
    assert r.status_code == 422 and "Tax Year 2026-27" in r.text            # the user chose 2025
    ok = post(client, tenant, url, "/statement-files", "form168_sample.txt",
              {**form(body, confirmed="true", expected_sha256=sha), "year": "2026"})
    assert ok.status_code == 200, ok.text


def test_refusals_are_422_with_a_code_and_a_sentence_and_save_nothing(client, tenant, world, db_session):
    url, body, _ = setup_case(client, tenant, world)
    for name, content, code in (
        ("s.pdf", b"%PDF-1.7 x", "TRINETRA_PDF_STATEMENT"),
        ("s.zip", b"PK\x03\x04x", "TRINETRA_ZIP_STATEMENT"),
        ("s.txt", blob("form26as_sample.txt").replace(b"^150000.00^3000.00^3000.00^", b"^150000.00^3000.00^9.00^"), "TRINETRA_TOTAL_MISMATCH"),
        ("s.csv", b"a,b\n1,2\n", "TRINETRA_UNRECOGNIZED_LAYOUT"),
        ("s.csv", b"", "TRINETRA_EMPTY_FILE"),
    ):
        r = post(client, tenant, url, "/statement-files/preview", name, form(body), content=content)
        assert r.status_code == 422 and code in r.text, (name, r.status_code, r.text)
    assert db_session.query(TrinetraStatement).count() == 0


def test_the_same_file_is_idempotent_and_a_newer_file_supersedes(client, tenant, world, db_session):
    url, body, _ = setup_case(client, tenant, world)
    sha = hashlib.sha256(blob("servabo_template_sample.csv")).hexdigest()
    first = post(client, tenant, url, "/statement-files", "servabo_template_sample.csv", form(body, confirmed="true", expected_sha256=sha))
    again = post(client, tenant, url, "/statement-files", "servabo_template_sample.csv", form(body, confirmed="true", expected_sha256=sha))
    assert first.status_code == again.status_code == 200 and first.json()["id"] == again.json()["id"]
    newer = blob("servabo_template_sample.csv") + b"ABCD12345E,500.00,Q4-1,194C,10-Mar-2026,F,,,,FY 2025-26 / AY 2026-27\n"
    second = post(client, tenant, url, "/statement-files", "t.csv",
                  form(body, confirmed="true", expected_sha256=hashlib.sha256(newer).hexdigest()), content=newer)
    assert second.status_code == 200 and second.json()["id"] != first.json()["id"] and second.json()["revision"] == 2
    rows = db_session.query(TrinetraStatement).order_by(TrinetraStatement.revision).all()
    assert [r.active for r in rows] == [False, True]
    assert rows[0].source_meta["official"] is False and rows[0].source_meta["verified"] is True   # a transcription


def test_only_an_administrator_with_the_plan_may_preview_or_import(client, tenant, world, db_session):
    url, body, _ = setup_case(client, tenant, world)
    for who in (tenant.viewer, tenant.contributor):
        assert client.post(url + "/statement-files/preview", headers=who.headers, data=form(body),
                           files={"file": ("a.csv", blob("servabo_template_sample.csv"), "text/csv")}).status_code == 403
    put_on_plan(db_session, tenant.organization, "developer")
    assert client.post(url + "/statement-files/preview", headers=tenant.owner.headers, data=form(body),
                       files={"file": ("a.csv", blob("servabo_template_sample.csv"), "text/csv")}).status_code == 402


def test_a_row_whose_booking_status_is_not_final_cannot_be_allocated(client, tenant, world):
    url, body, case = setup_case(client, tenant, world)
    content = blob("servabo_template_sample.csv").replace(b"2000.00,Q1-1,194C,15-Jun-2025,F", b"2000.00,Q1-1,194C,15-Jun-2025,U")
    imported = post(client, tenant, url, "/statement-files", "t.csv",
                    form(body, confirmed="true", expected_sha256=hashlib.sha256(content).hexdigest()), content=content)
    assert imported.status_code == 200
    decision = {"revision": case["revision"], "action": "ALLOCATE", "reason": "Reviewed the previewed file and the invoice.",
                "allocations": [{"snapshot_id": imported.json()["id"], "line_id": "0", "amount": "2000"}]}
    r = client.post(url + f"/credits/{case['id']}/decisions", headers=tenant.owner.headers, json=decision)
    assert r.status_code == 422 and "booking status" in r.text and "'U'" in r.text
