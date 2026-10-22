"""Document packs that do what they promise (Final session 1, Phase 6, F-408): the suggested checks.

A pack lists checks it recommends ("The notice period is at most 90 days"). Until now the card only showed them, and a person had to
retype each one under Clause assertions. Now enabling a pack PROPOSES them there, and accepting one is one click:

    proposals()   the suggested checks of every pack ENABLED in the workspace, minus the ones already added as a clause
                  check (same sentence) and the ones an administrator turned down. Derived, not stored: disabling the pack
                  withdraws them, and a pack the platform updates is reflected at once.
    accept()      creates the clause check (a persisted rule with its assertion node), saves the sentence at the confidence
                  the pack's severity implies, and switches it on. The same code path the console's "New clause check" uses,
                  so compilation, versioning and the AI acknowledgement are the ones every clause check has.
    dismiss()     remembers the key on the workspace's row for that pack, so the check is not proposed again.

NOTHING IS ADDED BEHIND A PERSON'S BACK. Enabling a pack changes nothing in Clause assertions; accepting is an administrator's click.
A sentence the engine cannot turn into a typed check is read by an AI model and billed as assistant use: `requires_acknowledgement`
says so before the click, and the server refuses the accept unless the caller acknowledged it.

SEVERITY IS A CONFIDENCE SETTING. A check's confidence is how sure the engine must be before a document passes without a person
looking (higher sends more to review). HIGH asks for 0.97, MEDIUM for the usual 0.95, LOW for 0.90.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

logger = logging.getLogger("app.services.ingestion.pack_checks")

SEVERITY_THRESHOLD = {"HIGH": "0.97", "MEDIUM": "0.95", "LOW": "0.90"}
NAME_LIMIT = 120


class PackCheckError(ValueError):
    """A request that cannot be honoured; the message is for the person who made it."""


@dataclass(frozen=True)
class Proposal:
    key: str
    preset_id: uuid.UUID
    preset_label: str
    document_type: str
    sentence: str
    severity: str
    threshold: str
    understood_as: str
    requires_acknowledgement: bool


def _norm(sentence: str) -> str:
    return " ".join((sentence or "").casefold().split())


def check_key(preset_id: uuid.UUID, sentence: str) -> str:
    """A stable key for one suggested check of one pack."""
    return hashlib.sha256(f"{preset_id}:{_norm(sentence)}".encode("utf-8")).hexdigest()[:24]


def _enabled_rows(db: Session, workspace_id: uuid.UUID) -> list[tuple[Any, Any]]:
    from app.models.ingestion import DocumentSchemaPreset, WorkspaceSchemaPreset

    return list(db.execute(
        select(WorkspaceSchemaPreset, DocumentSchemaPreset)
        .join(DocumentSchemaPreset, DocumentSchemaPreset.id == WorkspaceSchemaPreset.preset_id)
        .where(WorkspaceSchemaPreset.workspace_id == workspace_id, WorkspaceSchemaPreset.enabled.is_(True))
        .order_by(DocumentSchemaPreset.industry, DocumentSchemaPreset.document_type, DocumentSchemaPreset.id)
    ).all())


def _existing_sentences(db: Session, workspace_id: uuid.UUID) -> set[str]:
    from app.services.assertions import clause_check_service

    return {
        _norm(check.definition.sentence)
        for check in clause_check_service.list_for_workspace(db, workspace_id=workspace_id)
        if check.definition is not None
    }


def proposals(db: Session, *, organization_id: uuid.UUID, workspace_id: uuid.UUID) -> list[Proposal]:
    """The checks the workspace's enabled packs suggest and that are neither added nor turned down."""
    from app.services.assertions import definition_service

    rows = _enabled_rows(db, workspace_id)
    if not rows:
        return []
    have = _existing_sentences(db, workspace_id)
    found: list[Proposal] = []
    seen: set[str] = set()
    for applied, preset in rows:
        turned_down = set(applied.dismissed_checks or [])
        for entry in preset.assertions or []:
            sentence = str((entry or {}).get("sentence") or "").strip()
            severity = str((entry or {}).get("severity") or "MEDIUM").upper()
            if not sentence:
                continue
            key = check_key(preset.id, sentence)
            if key in turned_down or key in seen or _norm(sentence) in have:
                continue
            threshold = SEVERITY_THRESHOLD.get(severity, SEVERITY_THRESHOLD["MEDIUM"])
            try:
                compiled = definition_service.preview(
                    db, organization_id=organization_id, sentence=sentence, threshold=threshold)
            except definition_service.AssertionError_:
                # A sentence the engine cannot compile is not offered: the pack's author must fix it. Logged, never raised.
                logger.warning("pack_checks.uncompilable", extra={"preset_id": str(preset.id), "sentence": sentence[:80]})
                continue
            if _norm(compiled.outcome.plan.sentence) in have:  # saved checks hold the engine's own wording of the sentence
                continue
            payload = compiled.as_payload()
            seen.add(key)
            found.append(Proposal(
                key=key, preset_id=preset.id, preset_label=preset.label, document_type=preset.document_type,
                sentence=sentence, severity=severity, threshold=threshold,
                understood_as=str(payload.get("understood_as") or ""),
                requires_acknowledgement=bool(payload.get("requires_acknowledgement")),
            ))
    return found


def _find(db: Session, *, organization_id: uuid.UUID, workspace_id: uuid.UUID, key: str) -> Proposal:
    for proposal in proposals(db, organization_id=organization_id, workspace_id=workspace_id):
        if proposal.key == key:
            return proposal
    raise PackCheckError("That suggested check is not on offer any more: it was added, turned down, or its pack was disabled.")


def accept(
    db: Session, *, organization_id: uuid.UUID, workspace_id: uuid.UUID, user_id: uuid.UUID, key: str,
    acknowledge_llm: bool = False,
) -> Any:
    """Create the clause check for one proposal and switch it on. Flushes; the caller commits."""
    from app.services.assertions import clause_check_service, definition_service

    proposal = _find(db, organization_id=organization_id, workspace_id=workspace_id, key=key)
    if proposal.requires_acknowledgement and not acknowledge_llm:
        raise PackCheckError(
            "This check is read by an AI model and billed as assistant usage. Confirm that to add it.")
    try:
        check = clause_check_service.create(
            db, workspace_id=workspace_id, created_by_user_id=user_id,
            name=f"{proposal.preset_label}: {proposal.sentence}"[:NAME_LIMIT])
        definition_service.save(
            db, organization_id=organization_id, workspace_id=workspace_id, node=check.node,
            sentence=proposal.sentence, threshold=proposal.threshold,
            acknowledged_by=user_id if acknowledge_llm else None)
    except (clause_check_service.ClauseCheckError, definition_service.AssertionError_) as exc:
        raise PackCheckError(str(exc)) from exc
    # The first sentence switches a clause check on, as the console's save does (a check with no sentence is created off).
    check.rule.is_active = True
    db.flush([check.rule])
    return clause_check_service.get(db, workspace_id=workspace_id, rule_id=check.rule.id)


def dismiss(db: Session, *, organization_id: uuid.UUID, workspace_id: uuid.UUID, key: str) -> None:
    """Remember that this workspace turned the suggested check down. Flushes; the caller commits."""
    proposal = _find(db, organization_id=organization_id, workspace_id=workspace_id, key=key)
    from app.models.ingestion import WorkspaceSchemaPreset

    row = db.get(WorkspaceSchemaPreset, (workspace_id, proposal.preset_id))
    if row is None:  # pragma: no cover - _find only returns proposals of an enabled pack
        raise PackCheckError("That pack is not applied to this workspace.")
    row.dismissed_checks = [*(row.dismissed_checks or []), key]
    db.flush([row])


@dataclass(frozen=True)
class RedactionSuggestion:
    profile: str
    preset_label: str
    document_type: str


def redaction_suggestion(db: Session, *, workspace_id: uuid.UUID, text: str) -> Optional[RedactionSuggestion]:
    """The redaction profile of the enabled pack that fits this document's text, or None.

    The same matching extraction uses (at least two of the pack's phrases as whole words, the best-fitting pack wins), so the
    pack that shaped the document's fields is the pack that suggests how to redact it."""
    from app.services.entities import presets

    preset = presets.best_enabled_preset(db, workspace_id=workspace_id, text=text or "", redaction_only=True)
    if preset is None or not preset.redaction_profile:
        return None
    return RedactionSuggestion(profile=preset.redaction_profile, preset_label=preset.label, document_type=preset.document_type)


__all__ = ["PackCheckError", "Proposal", "RedactionSuggestion", "accept", "check_key", "dismiss", "proposals",
           "redaction_suggestion"]
