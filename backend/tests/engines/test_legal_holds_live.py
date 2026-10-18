"""Legal holds belong to their workspace, and a released hold stays on record (Session C, F-500).

    pytest tests/engines/test_legal_holds_live.py -q

Found by the browser spec 88 (legal holds): the Legal holds panel has a "Released holds" list that
could never fill, because the list route returned active holds only; and the list and the release route
looked at the whole organization, so a second workspace saw (and could release) the first one's holds.
"""

from __future__ import annotations

import uuid

from tests.engines.conftest import Engines, make_pdf
from tests.engines.isolation import _second_workspace


def _hold(engines: Engines, reason: str, document: uuid.UUID | None = None) -> dict:
    body = {"reason": reason, **({"work_item_id": str(document)} if document else {})}
    placed = engines.post("/work-items/retention-holds", body)
    assert placed.status_code == 201, placed.text
    return placed.json()


def test_a_released_hold_is_still_listed_with_its_release_time(engines: Engines) -> None:
    kept = _hold(engines, "Regulator inquiry")
    freed = _hold(engines, "Old matter")
    assert engines.delete(f"/work-items/retention-holds/{freed['id']}").status_code == 200

    listed = {h["id"]: h for h in engines.get("/work-items/retention-holds").json()}
    assert set(listed) == {kept["id"], freed["id"]}
    assert listed[kept["id"]]["released_at"] is None
    assert listed[freed["id"]]["released_at"] is not None


def test_holds_are_listed_and_released_only_in_their_own_workspace(engines: Engines) -> None:
    document = engines.upload("held.pdf", make_pdf([["Board minutes", "Privileged"]]))
    whole = _hold(engines, "Whole workspace hold")
    one = _hold(engines, "One document hold", document)
    other = _second_workspace(engines)
    base = f"/api/v1/workspaces/{other}/work-items/retention-holds"
    owner = engines.tenant.owner.headers

    # The second workspace sees none of the first one's holds ...
    assert engines.client.get(base, headers=owner).json() == []
    # ... and cannot release them, so the first workspace's documents stay protected.
    for hold in (whole, one):
        assert engines.client.delete(f"{base}/{hold['id']}", headers=owner).status_code == 404
    still = {h["id"]: h["released_at"] for h in engines.get("/work-items/retention-holds").json()}
    assert still == {whole["id"]: None, one["id"]: None}
    assert engines.delete(f"/work-items/{document}").status_code == 409

    # A hold placed in the second workspace is its own.
    mine = engines.client.post(base, json={"reason": "Second workspace hold"}, headers=owner)
    assert mine.status_code == 201, mine.text
    assert [h["reason"] for h in engines.client.get(base, headers=owner).json()] == ["Second workspace hold"]
    assert "Second workspace hold" not in {h["reason"] for h in engines.get("/work-items/retention-holds").json()}
