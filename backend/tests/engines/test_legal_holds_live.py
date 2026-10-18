"""Legal holds belong to their workspace, and a released hold stays on record (Session C, F-500).

    pytest tests/engines/test_legal_holds_live.py -q

Found by the browser spec 88 (legal holds): the Legal holds panel has a "Released holds" list that
could never fill, because the list route returned active holds only; and the list and the release route
looked at the whole organization, so a second workspace saw (and could release) the first one's holds.
"""

from __future__ import annotations

import uuid

from tests.engines.conftest import Engines


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
