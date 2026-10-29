"""The server-side pilot enrolment script (Final session 2T): it does what the platform operator's console does, with the same audit,
and refuses a missing organization or a short reason."""

import importlib.util
import json
from pathlib import Path

import pytest

from app.models.audit_log import AuditLog
from app.models.trinetra import TrinetraPilot

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "trinetra_pilot.py"


def load():
    spec = importlib.util.spec_from_file_location("trinetra_pilot_script", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_enrol_list_and_withdraw_by_slug_are_audited(tenant, db_session, capsys):
    script = load()
    slug = tenant.organization.slug
    assert script.main(["enrol", "--organization", slug, "--reason", "Pilot with the owner's own files."]) == 0
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1])["enrolled"] is True
    db_session.expire_all()
    assert db_session.get(TrinetraPilot, tenant.organization.id) is not None

    assert script.main(["list"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert tenant.organization.id.hex in {item["organization_id"].replace("-", "") for item in listed["items"]}

    assert script.main(["withdraw", "--organization", slug, "--reason", "Pilot over; the customer asked to stop."]) == 0
    db_session.expire_all()
    assert db_session.get(TrinetraPilot, tenant.organization.id) is None
    operations = [row.details.get("operation") for row in db_session.query(AuditLog).filter_by(resource_id=tenant.organization.id)
                  if isinstance(row.details, dict)]
    assert "trinetra.pilot_enrolled" in operations and "trinetra.pilot_withdrawn" in operations


def test_a_missing_organization_or_a_short_reason_is_refused(tenant):
    script = load()
    with pytest.raises(SystemExit):
        script.main(["enrol", "--organization", "no-such-organization", "--reason", "A long enough reason."])
    with pytest.raises(SystemExit):
        script.main(["enrol", "--organization", tenant.organization.slug, "--reason", "short"])
