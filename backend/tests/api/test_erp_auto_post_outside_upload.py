"""N-197 (Final session 2A, decided by the owner's delegated authority): ERP auto-post never posts a case that completed
because an outside party uploaded a document (a supplier, through a request link). Such a case waits for a person: it
is posted by hand, or automatically once a person closes it. A case our own documents completed posts as before.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

from app.models.cases import Case, CaseDocument, CaseTemplate
from app.services.cases import vocabulary as cv
from app.services.erp import sources as S
from app.services.erp import vocabulary as ev
from tests.services.helm import factories

NOW = datetime.now(timezone.utc)


def _case(db, tenant, template, *, status, sources):
    case = Case(organization_id=tenant.organization.id, workspace_id=tenant.workspace.id, template_id=template.id,
                anchor_kind="MANUAL", title=f"Case {status} {sources}", status=status,
                completed_at=NOW, closed_at=NOW if status == cv.CASE_CLOSED else None, created_at=NOW - timedelta(days=1))
    db.add(case)
    db.flush()
    for source in sources:
        item = factories.document(db, workspace=tenant.workspace, organization_id=tenant.organization.id, role="INVOICE",
                                  entities={}, number=f"N-{uuid.uuid4().hex[:5]}")
        db.add(CaseDocument(case_id=case.id, workspace_id=tenant.workspace.id, work_item_id=item.id, document_type="invoice",
                            source=source, added_at=NOW))
    db.flush()
    return case


def test_auto_post_skips_a_case_an_outside_upload_completed_until_a_person_closes_it(db_session, tenant, monkeypatch):
    template = CaseTemplate(organization_id=tenant.organization.id, workspace_id=tenant.workspace.id, key="vendor", version=1,
                            name="Vendor onboarding", status="PUBLISHED", assembly_key="MANUAL", required_documents=[], rules=[],
                            published_at=NOW)
    db_session.add(template)
    db_session.flush()
    ours = _case(db_session, tenant, template, status=cv.CASE_COMPLETE, sources=(cv.SOURCE_AUTO, cv.SOURCE_MANUAL))
    theirs = _case(db_session, tenant, template, status=cv.CASE_COMPLETE, sources=(cv.SOURCE_AUTO, cv.SOURCE_REQUEST))
    closed = _case(db_session, tenant, template, status=cv.CASE_CLOSED, sources=(cv.SOURCE_REQUEST,))
    monkeypatch.setattr(S, "load", lambda db, ws, kind, ident: S.Outcome(
        kind=kind, id=ident, workspace_id=ws, organization_id=tenant.organization.id, label="x", approved_at=NOW,
        work_item_id=None, objects=("VENDOR_BILL",)))

    automatic = {o.id for o in S.eligible(db_session, tenant.workspace.id, kinds=(ev.SOURCE_CASE,), for_auto=True)}
    assert ours.id in automatic and closed.id in automatic
    assert theirs.id not in automatic                       # waits for a person
    by_hand = {o.id for o in S.eligible(db_session, tenant.workspace.id, kinds=(ev.SOURCE_CASE,))}
    assert {ours.id, theirs.id, closed.id} <= by_hand        # a person can still post it from the console
