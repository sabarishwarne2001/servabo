"""PHASE 4 — global search (Ctrl+K): documents, entities and cases.

One query across every workspace of an organization the caller may open,
never one more. The workspace set comes from
workspace_service.list_accessible_workspaces - the same answer the workspace
switcher shows: organization OWNER/ADMIN see every active workspace, anyone
else only the workspaces they hold a grant on. Every query below is filtered
by that set in SQL; nothing is fetched and filtered afterwards.

What matches:
* documents - the file name, or any extracted field value (an invoice number,
  a vendor name, a PO reference);
* entities - the display name of an active (not merged) entity record, when
  the plan includes the entity graph;
* cases - the case title, when the plan includes case intelligence;
* GST suppliers - by GSTIN or name, and GST invoices - by invoice number, from
  the reconciliation of the workspaces whose plan (or GST Credit add-on) opens
  the supplier and invoice lists; a workspace on the preview shows nothing here;
* automation rules - by name, only in workspaces where the person may see
  workflows (a contributor or more; a viewer is not shown them anywhere).

The text is matched literally (ILIKE with %, _ and \\ escaped), so a query can
never widen itself into a wildcard.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.orm import Session

from app.models.automation import AutomationRule
from app.models.cases import Case
from app.models.entity_graph import Entity
from app.models.gst import GstMatch
from app.models.organization import MembershipStatus, Organization, OrganizationRole
from app.models.work_item import WorkItem
from app.models.workspace import Workspace, WorkspaceMember, WorkspaceRole
from app.utils.like import contains_pattern

MIN_QUERY_LENGTH = 2
MAX_QUERY_LENGTH = 120
DEFAULT_LIMIT = 6
MAX_LIMIT = 20


class SearchQueryError(ValueError):
    pass


@dataclass(frozen=True)
class SearchHit:
    kind: str  # DOCUMENT | ENTITY | CASE | GST_SUPPLIER | GST_INVOICE | RULE
    id: uuid.UUID
    title: str
    subtitle: Optional[str]
    workspace_id: uuid.UUID
    workspace_slug: str
    workspace_name: str
    #: What to look the hit up by on its page: a GSTIN or an invoice number (GST hits), else None.
    reference: Optional[str] = None


@dataclass
class SearchResults:
    query: str
    workspaces_searched: int
    documents: list[SearchHit] = field(default_factory=list)
    entities: list[SearchHit] = field(default_factory=list)
    cases: list[SearchHit] = field(default_factory=list)
    suppliers: list[SearchHit] = field(default_factory=list)
    gst_invoices: list[SearchHit] = field(default_factory=list)
    rules: list[SearchHit] = field(default_factory=list)


def _pattern(query: str) -> str:
    return contains_pattern(query)


def _matched_field(entities: Any, needle: str) -> Optional[str]:
    """Which extracted field matched, for the result's second line."""
    if not isinstance(entities, dict):
        return None
    lowered = needle.lower()
    for key, value in entities.items():
        if isinstance(value, (str, int, float)) and lowered in str(value).lower():
            return f"{str(key).replace('_', ' ')}: {value}"
    return None


def search(
    db: Session,
    *,
    organization: Organization,
    user_id: uuid.UUID,
    organization_role: OrganizationRole,
    query: str,
    limit: int = DEFAULT_LIMIT,
) -> SearchResults:
    from app.api.capability_gate import has_capability
    from app.core import entitlements
    from app.services.workspace_service import list_accessible_workspaces

    text = " ".join((query or "").split())
    if len(text) < MIN_QUERY_LENGTH:
        raise SearchQueryError(f"Type at least {MIN_QUERY_LENGTH} characters to search.")
    text = text[:MAX_QUERY_LENGTH]
    limit = max(1, min(int(limit), MAX_LIMIT))

    workspaces: dict[uuid.UUID, Workspace] = {
        ws.id: ws
        for ws in list_accessible_workspaces(
            db, organization=organization, user_id=user_id, organization_role=organization_role
        )
    }
    results = SearchResults(query=text, workspaces_searched=len(workspaces))
    if not workspaces:
        return results
    allowed = list(workspaces)
    pattern = _pattern(text)

    def hit(kind: str, row_id: uuid.UUID, title: str, subtitle: Optional[str], workspace_id: uuid.UUID,
            reference: Optional[str] = None) -> SearchHit:
        ws = workspaces[workspace_id]
        return SearchHit(kind=kind, id=row_id, title=title, subtitle=subtitle, workspace_id=ws.id,
                         workspace_slug=ws.slug, workspace_name=ws.workspace_name, reference=reference)

    documents = db.execute(
        select(WorkItem.id, WorkItem.original_filename, WorkItem.extracted_entities, WorkItem.workspace_id)
        .where(
            WorkItem.workspace_id.in_(allowed),  # every one of them belongs to this organization
            or_(
                WorkItem.original_filename.ilike(pattern, escape="\\"),
                cast(WorkItem.extracted_entities, String).ilike(pattern, escape="\\"),
            ),
        )
        .order_by(WorkItem.created_at.desc())
        .limit(limit)
    ).all()
    results.documents = [
        hit("DOCUMENT", row.id, row.original_filename, _matched_field(row.extracted_entities, text), row.workspace_id)
        for row in documents
    ]

    if has_capability(db, organization_id=organization.id, capability_key=entitlements.ENTITY_GRAPH_CAPABILITY):
        entities = db.execute(
            select(Entity.id, Entity.display_name, Entity.kind, Entity.workspace_id)
            .where(
                Entity.organization_id == organization.id,
                Entity.workspace_id.in_(allowed),
                Entity.status == "ACTIVE",
                Entity.display_name.ilike(pattern, escape="\\"),
            )
            .order_by(Entity.display_name)
            .limit(limit)
        ).all()
        results.entities = [
            hit("ENTITY", row.id, row.display_name, row.kind.title(), row.workspace_id) for row in entities
        ]

    if has_capability(db, organization_id=organization.id, capability_key=entitlements.CASE_INTELLIGENCE_CAPABILITY):
        cases = db.execute(
            select(Case.id, Case.title, Case.status, Case.workspace_id)
            .where(
                Case.organization_id == organization.id,
                Case.workspace_id.in_(allowed),
                Case.title.ilike(pattern, escape="\\"),
            )
            .order_by(Case.title)
            .limit(limit)
        ).all()
        results.cases = [hit("CASE", row.id, row.title, row.status.title(), row.workspace_id) for row in cases]

    results.suppliers, results.gst_invoices = _gst_hits(db, organization=organization, workspaces=workspaces,
                                                       pattern=pattern, limit=limit, hit=hit)
    results.rules = _rule_hits(db, organization=organization, user_id=user_id, organization_role=organization_role,
                               workspaces=workspaces, pattern=pattern, limit=limit, hit=hit)
    return results


def _gst_hits(db: Session, *, organization: Organization, workspaces: dict[uuid.UUID, Workspace], pattern: str,
              limit: int, hit: Any) -> tuple[list[SearchHit], list[SearchHit]]:
    """Suppliers and invoices from the GST reconciliation, only in workspaces whose plan opens the lists.

    The same test as the supplier and invoice endpoints (`gst.gate.full_access`): the sample company and any workspace
    of an organization with the plan's capability or the add-on. A workspace on the preview contributes nothing, so a
    search never shows what the page itself would lock.
    """
    from app.services.gst import gate

    open_workspaces = [wid for wid, ws in workspaces.items() if gate.full_access(db, ws)]
    if not open_workspaces:
        return [], []

    supplier_rows = db.execute(
        select(
            GstMatch.workspace_id,
            GstMatch.supplier_gstin,
            func.max(GstMatch.supplier_name).label("supplier_name"),
            func.count().label("documents"),
        )
        .where(
            GstMatch.organization_id == organization.id,
            GstMatch.workspace_id.in_(open_workspaces),
            GstMatch.supplier_gstin.is_not(None),
            or_(GstMatch.supplier_gstin.ilike(pattern, escape="\\"), GstMatch.supplier_name.ilike(pattern, escape="\\")),
        )
        .group_by(GstMatch.workspace_id, GstMatch.supplier_gstin)
        .order_by(func.max(GstMatch.supplier_name), GstMatch.supplier_gstin)
        .limit(limit)
    ).all()
    suppliers = [
        hit(
            "GST_SUPPLIER",
            uuid.uuid5(row.workspace_id, f"gst-supplier:{row.supplier_gstin}"),
            row.supplier_name or row.supplier_gstin,
            f"GSTIN {row.supplier_gstin} \u00b7 {row.documents} {'document' if row.documents == 1 else 'documents'}",
            row.workspace_id,
            row.supplier_gstin,
        )
        for row in supplier_rows
    ]

    invoice_rows = db.execute(
        select(GstMatch.id, GstMatch.workspace_id, GstMatch.doc_number, GstMatch.supplier_name, GstMatch.supplier_gstin,
               GstMatch.status)
        .where(
            GstMatch.organization_id == organization.id,
            GstMatch.workspace_id.in_(open_workspaces),
            GstMatch.doc_number.is_not(None),
            GstMatch.doc_number.ilike(pattern, escape="\\"),
        )
        .order_by(GstMatch.doc_date.desc().nulls_last(), GstMatch.doc_number)
        .limit(limit)
    ).all()
    invoices = [
        hit(
            "GST_INVOICE",
            row.id,
            row.doc_number,
            " \u00b7 ".join(part for part in (row.supplier_name or row.supplier_gstin, row.status.replace("_", " ").title()) if part),
            row.workspace_id,
            row.doc_number,
        )
        for row in invoice_rows
    ]
    return suppliers, invoices


#: Seeing workflows is a contributor's right (N-019): a viewer is offered none, so search offers none either.
_RULE_READERS = (WorkspaceRole.CONTRIBUTOR, WorkspaceRole.ADMIN)


def _rule_hits(db: Session, *, organization: Organization, user_id: uuid.UUID, organization_role: OrganizationRole,
               workspaces: dict[uuid.UUID, Workspace], pattern: str, limit: int, hit: Any) -> list[SearchHit]:
    from app.core.organization_permissions import IMPLICIT_WORKSPACE_ADMIN_ROLES

    if organization_role in IMPLICIT_WORKSPACE_ADMIN_ROLES:
        readable = list(workspaces)
    else:
        granted = db.execute(
            select(WorkspaceMember.workspace_id).where(
                WorkspaceMember.user_id == user_id,
                WorkspaceMember.workspace_id.in_(list(workspaces)),
                WorkspaceMember.role.in_(_RULE_READERS),
                WorkspaceMember.status == MembershipStatus.ACTIVE,
            )
        ).scalars().all()
        readable = list(granted)
    if not readable:
        return []
    rows = db.execute(
        select(AutomationRule.id, AutomationRule.name, AutomationRule.is_active, AutomationRule.workspace_id)
        .where(
            AutomationRule.workspace_id.in_(readable),
            AutomationRule.deleted_at.is_(None),
            AutomationRule.name.ilike(pattern, escape="\\"),
        )
        .order_by(AutomationRule.name)
        .limit(limit)
    ).all()
    return [hit("RULE", row.id, row.name, "Active" if row.is_active else "Paused", row.workspace_id) for row in rows]


__all__ = ["SearchHit", "SearchQueryError", "SearchResults", "search"]
