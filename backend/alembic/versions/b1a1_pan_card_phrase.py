"""The Aadhaar / PAN card pack recognises a real PAN card (Session B, F-400).

A document pack applies to a new document that mentions at least two of its phrases. The pack's
three phrases were "aadhaar", "permanent account number" and "unique identification": an Aadhaar
card carries the first and the third, but a PAN card carries only the second, so enabling the pack
never changed how a PAN card was read. A PAN card also says "Income Tax Department" (it is the
department that issues it); with that as a fourth phrase a PAN card has two.

The new phrase is added to the platform's pack only (`organization_id IS NULL`); an organization's
own copy of a pack is its own to edit. The downgrade takes the phrase out again.

Revision ID: b1a1_pan_card_phrase
Revises: w1a4_hold_notices
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op
from sqlalchemy import text

revision: str = "b1a1_pan_card_phrase"
down_revision: Union[str, None] = "w1a4_hold_notices"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

#: document_type -> phrases added to the platform pack's classifier hints.
ADDED_HINTS: dict[str, tuple[str, ...]] = {"india_id_card": ("income tax department",)}


def add_hints(connection) -> None:
    """Add `ADDED_HINTS` to the platform packs that lack them (also what the test fixtures call)."""
    for document_type, phrases in ADDED_HINTS.items():
        for phrase in phrases:
            connection.execute(text(
                "UPDATE document_schema_presets "
                "SET classifier_hints = classifier_hints || to_jsonb(CAST(:phrase AS text)) "
                "WHERE organization_id IS NULL AND document_type = :document_type "
                "AND NOT (classifier_hints ? :phrase)"
            ), {"document_type": document_type, "phrase": phrase})


def remove_hints(connection) -> None:
    for document_type, phrases in ADDED_HINTS.items():
        for phrase in phrases:
            connection.execute(text(
                "UPDATE document_schema_presets SET classifier_hints = classifier_hints - CAST(:phrase AS text) "
                "WHERE organization_id IS NULL AND document_type = :document_type"
            ), {"document_type": document_type, "phrase": phrase})


def upgrade() -> None:
    add_hints(op.get_bind())


def downgrade() -> None:
    remove_hints(op.get_bind())
