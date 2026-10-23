"""Final session 1 (2C): "Getting started" ticks from a workspace's own data and from nothing else, live.

Workspace A reads a document; a second workspace of the same organization (B) has read nothing, and its checklist stays unticked while A's ticks. Another
organization's workspace is refused. (The tick rules themselves are tests/services/test_getting_started.py.)
"""

from __future__ import annotations

import uuid

from tests.engines.conftest import Engines

#: The collections this module proves isolated with its own assertions (tests/isolation/test_structural_invariants.py).
ISOLATION_PROVEN_HERE = ("getting-started",)


def _steps(response) -> dict[str, bool]:
    assert response.status_code == 200, response.text
    return {step["key"]: step["done"] for step in response.json()["steps"]}


def test_a_workspaces_checklist_ticks_from_its_own_documents_only(engines: Engines) -> None:
    engines.process("start.pdf", [["TAX INVOICE", "Invoice Number: GS-1"]], marker="GS-1", classification="Invoice",
                    entities={"invoice_number": "GS-1", "vendor_name": "Acme Supplies Ltd", "total_amount": "1000.00", "currency": "INR"})
    owner = engines.tenant.owner.headers
    mine = _steps(engines.client.get(f"/api/v1/workspaces/{engines.ws}/getting-started", headers=owner))
    assert mine.get("documents") is True and mine.get("read") is True, mine

    created = engines.post("/workspaces", {"workspace_name": f"Start B {uuid.uuid4().hex[:6]}"}, org=True)
    assert created.status_code == 201, created.text
    theirs = _steps(engines.client.get(f"/api/v1/workspaces/{created.json()['id']}/getting-started", headers=owner))
    assert theirs.get("documents") is False and theirs.get("read") is False, "B has read nothing: A's documents do not tick B's checklist"


def test_another_organizations_workspace_is_refused(engines: Engines) -> None:
    foreign = engines.tenant.foreign_workspace
    refused = engines.client.get(f"/api/v1/workspaces/{foreign.id}/getting-started", headers=engines.tenant.owner.headers)
    assert refused.status_code in (403, 404), refused.text
    outsider = engines.client.get(f"/api/v1/workspaces/{engines.ws}/getting-started", headers=engines.tenant.non_member.headers)
    assert outsider.status_code in (403, 404), outsider.text
