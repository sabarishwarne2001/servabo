"""Which pack a new document matches (Session B): whole words, and one answer when two tie.

A pack is chosen when a new document mentions at least two of its phrases. The match was a plain
substring ("lease" matched "pleased", so the offer letter "We are pleased to offer you..." woke the
lease pack), and when two enabled packs matched equally the one the database happened to return
first won.
"""

from __future__ import annotations

import uuid

import pytest

from app.models.ingestion import DocumentSchemaPreset, WorkspaceSchemaPreset
from app.services.entities import presets


def _count(hints: list[str], text: str) -> int:
    return presets._hint_count(hints, text)  # noqa: SLF001


def test_a_phrase_must_be_a_whole_word() -> None:
    assert _count(["lease"], "We are pleased to offer you the position.") == 0
    assert _count(["lease"], "Please release the funds.") == 0
    assert _count(["lease"], "Residential LEASE Agreement") == 1
    assert _count(["lease"], "the lease, signed today") == 1
    assert _count(["tenant"], "Landlord and tenants") == 0


def test_a_phrase_of_several_words_matches_across_line_breaks_and_spacing() -> None:
    assert _count(["permanent account number"], "Permanent  Account\nNumber Card") == 1
    assert _count(["follow-up"], "Follow-up: GP review in two weeks") == 1
    assert _count(["hs code"], "HS code 8471.30") == 1
    assert _count(["hs code"], "NHS codes") == 0


def test_a_phrase_with_punctuation_at_its_edge_still_matches() -> None:
    assert _count(["p<"], "P<INDRAMAN<<PRIYA") == 1


def _pack(db, document_type: str, hints: list[str], *, pack_id: uuid.UUID) -> DocumentSchemaPreset:
    pack = DocumentSchemaPreset(
        id=pack_id, organization_id=None, industry="LEGAL", document_type=document_type, version=1,
        label=document_type.replace("_", " ").title(), description="x",
        schema={"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]},
        assertions=[], classifier_hints=hints, redaction_profile=None)
    db.add(pack)
    db.flush()
    return pack


@pytest.mark.parametrize("insertion_order", ["z_first", "a_first"])
def test_two_enabled_packs_that_tie_give_one_answer(db_session, tenant, insertion_order: str) -> None:
    """Both packs match two of their two phrases. Whichever the database returns first used to win; now
    the pack whose phrases the document matches more completely wins, and a true tie goes to the
    alphabetically first document type, whatever the order the rows were written in."""
    low, high = uuid.UUID(int=1), uuid.UUID(int=2**127)
    specs = [("z_pack", ["alpha clause", "beta clause"], low), ("a_pack", ["alpha clause", "beta clause"], high)]
    for document_type, hints, pack_id in (specs if insertion_order == "z_first" else specs[::-1]):
        _pack(db_session, document_type, hints, pack_id=pack_id)
    for pack_id in (low, high):
        db_session.add(WorkspaceSchemaPreset(workspace_id=tenant.workspace.id, preset_id=pack_id, enabled=True,
                                             enabled_at=__import__("datetime").datetime.now(
                                                 __import__("datetime").timezone.utc)))
    db_session.commit()

    context = presets.prompt_context(db_session, workspace_id=tenant.workspace.id,
                                     text="The alpha clause and the beta clause apply.")

    assert context is not None and "A Pack" in context, context


def test_the_pack_whose_phrases_match_more_completely_wins(db_session, tenant) -> None:
    """Two phrases of two (the specific pack) beat two phrases of five (the broad one)."""
    broad, specific = uuid.UUID(int=3), uuid.UUID(int=2**126)
    _pack(db_session, "a_broad", ["alpha clause", "beta clause", "c1", "c2", "c3"], pack_id=broad)
    _pack(db_session, "z_specific", ["alpha clause", "beta clause"], pack_id=specific)
    from datetime import datetime, timezone

    for pack_id in (broad, specific):
        db_session.add(WorkspaceSchemaPreset(workspace_id=tenant.workspace.id, preset_id=pack_id, enabled=True,
                                             enabled_at=datetime.now(timezone.utc)))
    db_session.commit()
    context = presets.prompt_context(db_session, workspace_id=tenant.workspace.id,
                                     text="The alpha clause and the beta clause apply.")
    assert context is not None and "Z Specific" in context, context
