"""Session J action `supplier.request_document` — ask a supplier for a document through a request link.

Opens a case from one of your published case templates ("Vendor onboarding", "Document request"), creates a document-request
link for the document you name, and emails the link to the supplier's KNOWN contact (the email contact Helm already holds
for that supplier GSTIN, the one the GST reminder uses). With no known contact nothing is created and nothing is sent; the
run says so and carries on.

The supplier is read from the trigger when it names one (`supplier_gstin`), else from the document's `vendor_gstin`. A
document the supplier uploads through the link is announced to automation as `document.received_by_link`, so a second rule
can take it from there. One open request per supplier, template and document type: a rule that fires again does not send a
second link while the first is open.
"""

from __future__ import annotations

import html
import uuid
from typing import Any, Optional

from pydantic import Field

from app.core.entitlements import CASE_INTELLIGENCE_CAPABILITY
from app.services.automation.actions.base import (
    ROLE_WORKSPACE_ADMIN,
    ActionConfig,
    ActionDefinition,
    ActionFailure,
    ActionOutcome,
    SaveContext,
)

ACTION_TYPE = "supplier.request_document"


class SupplierRequestDocumentConfig(ActionConfig):
    case_template_id: uuid.UUID = Field(description="A published case template the request belongs to.")
    document_type: str = Field(min_length=1, max_length=64, description="The kind of document asked for, as the template names it.")


def _template(db: Any, *, workspace_id: uuid.UUID, template_id: uuid.UUID) -> Optional[Any]:
    from app.models.cases import CaseTemplate
    from app.services.cases import vocabulary as v

    row = db.get(CaseTemplate, template_id)
    if row is None or row.workspace_id != workspace_id or row.status != v.TEMPLATE_PUBLISHED:
        return None
    return row


def _validate(ctx: SaveContext, config: ActionConfig) -> dict[str, str]:
    assert isinstance(config, SupplierRequestDocumentConfig)
    if _template(ctx.db, workspace_id=ctx.workspace_id, template_id=config.case_template_id) is None:
        return {"case_template_id": "Choose a published case template of this workspace."}
    return {}


def _supplier(state: Any) -> Optional[str]:
    from app.services.automation import document_fields as df
    from app.services.gst import fields as gf

    payload = dict(getattr(getattr(state, "trigger_event", None), "payload", None) or {})
    found = gf.gstin_of(payload.get("supplier_gstin"))
    work_item = getattr(state, "work_item", None)
    if found is None and work_item is not None:
        found = gf.gstin_of(df.read_by_alias(getattr(work_item, "extracted_entities", None) or {}, "vendor_gstin"))
    return found


def perform(state: Any, spec: Any) -> ActionOutcome:
    from sqlalchemy import select

    from app.core.config import settings
    from app.models.cases import Case, DocumentRequest
    from app.models.workspace import Workspace
    from app.services.cases import assembly, requests
    from app.services.cases import vocabulary as v
    from app.services.gst import reminder
    from app.services.helm import hands

    config = DEFINITION.parse_spec(spec)
    assert isinstance(config, SupplierRequestDocumentConfig)
    workspace = state.db.get(Workspace, state.execution.workspace_id)
    if workspace is None or workspace.is_sample:
        return ActionOutcome(summary="not sent: the sample company never sends email", details={"sent": False})
    template = _template(state.db, workspace_id=workspace.id, template_id=config.case_template_id)
    if template is None:
        raise ActionFailure("The case template is not published in this workspace any more.", recoverable=False)
    supplier = _supplier(state)
    if supplier is None:
        raise ActionFailure("This run names no supplier GSTIN (the trigger or the document must carry one).", recoverable=False)
    contact = reminder.known_contact(state.db, workspace, supplier)
    if not contact:
        return ActionOutcome(summary="not sent: no email contact is known for this supplier",
                             details={"sent": False, "supplier_gstin": supplier})
    label = f"Supplier {supplier}"
    open_request = state.db.execute(
        select(DocumentRequest.id).join(Case, Case.id == DocumentRequest.case_id).where(
            DocumentRequest.workspace_id == workspace.id, DocumentRequest.status == v.REQUEST_OPEN,
            DocumentRequest.document_type == config.document_type, DocumentRequest.recipient_label == label,
            Case.template_id == template.id).limit(1)).scalar_one_or_none()
    if open_request is not None:
        return ActionOutcome(summary="not sent: a request to this supplier is already open", external_ref=str(open_request),
                             details={"sent": False, "reused": True})
    case = assembly.open_case(state.db, template, anchor_kind=v.ASSEMBLY_MANUAL, title=label,
                              actor_user_id=state.rule.created_by_user_id)
    request, token = requests.create(state.db, case=case, document_type=config.document_type, recipient_label=label,
                                     actor_user_id=state.rule.created_by_user_id)
    link = f"{settings.FRONTEND_URL.rstrip('/')}/request/{token}"
    organization = hands._organization_name(state.db, workspace.organization_id)  # noqa: SLF001 - Helm's own mail identity
    text = (f"Hello,\n\n{organization} would like you to send a document: {config.document_type}.\n\n"
            f"Please upload it here (no account needed): {link}\n\nThank you.")
    page = (f"<p>Hello,</p><p>{html.escape(organization)} would like you to send a document: "
            f"<strong>{html.escape(config.document_type)}</strong>.</p>"
            f'<p><a href="{html.escape(link, quote=True)}">Upload it here</a> (no account needed).</p><p>Thank you.</p>')
    hands.send_mail(state.db, organization_id=workspace.organization_id, workspace_id=workspace.id, to=contact,
                    subject=f"{organization}: please send {config.document_type}", html_body=page, text_body=text)
    return ActionOutcome(summary="request link sent to the supplier's known contact", external_ref=str(request.id),
                         details={"sent": True, "case_id": str(case.id), "supplier_gstin": supplier})


DEFINITION = ActionDefinition(
    action_type=ACTION_TYPE,
    label="Ask a supplier for a document",
    description="Email a supplier's known contact a link to upload a document, and open a case for it.",
    category="Cases",
    config_model=SupplierRequestDocumentConfig,
    selector="automation.flow.supplier_request_document",
    perform=perform,
    capability=CASE_INTELLIGENCE_CAPABILITY,
    minimum_role=ROLE_WORKSPACE_ADMIN,
    validate_resources=_validate,
    idempotent=False,
    icon="file-up",
)
