"""Email-in (Final session 1, 2B): documents forwarded to a workspace's own address.

PROVIDER: Postmark inbound. Read on 2026-10-22 in Postmark's inbound manual (postmarkapp.com/manual), its webhook article
(postmarkapp.com/support/article/what-are-webhooks-explained) and practitioner summaries of both:

* The webhook body is JSON with `From`, `FromFull {Email, Name}`, `To`, `ToFull [{Email, MailboxHash}]`, `OriginalRecipient`,
  `Subject`, `MessageID`, `Date`, `MailboxHash`, `TextBody`, `HtmlBody`, `Attachments [{Name, Content (base64), ContentType,
  ContentLength, ContentID}]`.
* `MailboxHash` is the part after the `+` in `<hash>+<value>@inbound.postmarkapp.com`: the route key used until the owner
  has a domain. With a custom domain the whole local part is the key.
* Postmark retries a failing webhook up to 10 times with growing intervals (1 minute to 6 hours); it retries 5xx, 408 and 429
  and treats other 4xx answers, 403 among them, as permanent. (The 403-stops-retries rule is from Postmark's support article
  and two practitioner pages, not from a statement in the manual itself: Final session 2 confirms it with a real server.)
* Postmark does not sign inbound payloads. It documents HTTP basic auth in the webhook URL (over HTTPS only) and an IP
  allowlist as the protection.

WHAT IS ANSWERED, AND WHY
  200  the message was received (accepted, held, or already seen: Postmark stops retrying);
  401  the credential is missing or wrong (nothing is revealed about addresses);
  403  the address is unknown, rotated or its workspace is archived (Postmark stops retrying a dead address);
  404  email-in is not switched on here (no credential configured);
  413  the body is over INBOUND_EMAIL_MAX_BODY_MB;  422  the body is not a Postmark inbound message;
  429  the rate limit (Postmark retries later).   5xx  anything unexpected: Postmark retries, and nothing was half-added.

Nothing in this module logs a body, an attachment, an address's token or a sender.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import logging
import re
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from typing import Any, Optional

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.storage import StorageNamespace, get_storage_driver, tenant_key
from app.models.inbound_email import InboundEmailAddress, InboundEmailSender, InboundMessage
from app.models.organization import OrganizationRole
from app.models.workspace import Workspace, WorkspaceStatus
from app.services import document_intake_service, file_validation_service, plan_admission, trial_service
from app.services.ingestion import archive, archive_intake

logger = logging.getLogger("app.services.inbound_email")

TOKEN_RE = re.compile(r"^[a-z0-9]{24,64}$")
POSTMARK_HOST = "inbound.postmarkapp.com"

# Why a message waits.
HOLD_SENDER = "SENDER_NOT_ALLOWED"
HOLD_NO_ATTACHMENT = "NO_ATTACHMENT"
HOLD_GSTR2B = "GSTR2B_ONLY"
HOLD_OVER_LIMIT = "OVER_LIMIT"
HOLD_TRIAL_ENDED = "TRIAL_ENDED"
#: Holds an admin can approve (their attachments are kept); the others only wait to be discarded.
APPROVABLE = frozenset({HOLD_SENDER, HOLD_OVER_LIMIT, HOLD_TRIAL_ENDED})

HOLD_TEXT = {
    HOLD_SENDER: "The sender is not on this workspace's list of allowed senders. Approve it to add its documents, or discard it.",
    HOLD_NO_ATTACHMENT: "No attachment Servabo can read.",
    HOLD_GSTR2B: archive.GSTR2B_SKIP_MESSAGE,
    HOLD_OVER_LIMIT: "Your plan's monthly limit is used up, so nothing was added. Upgrade, then approve it.",
    HOLD_TRIAL_ENDED: "The free trial has ended, so nothing was added. Choose a plan, then approve it.",
}

# Per-attachment outcomes.
ADDED = "ADDED"
ZIP_QUEUED = "ZIP_QUEUED"
SKIPPED_GSTR2B = "SKIPPED_GSTR2B"
IGNORED_INLINE = "IGNORED_INLINE"
REFUSED = "REFUSED"
UNREADABLE = "UNREADABLE"
HELD_FILE = "HELD"


class InboundRefused(Exception):
    """The webhook call is refused with `status` and a short reason (never a detail about other tenants)."""

    def __init__(self, status: int, reason: str) -> None:
        super().__init__(reason)
        self.status = status
        self.reason = reason


# ------------------------------------------------------------------------------------------------ switch and credentials

def is_enabled() -> bool:
    password = settings.POSTMARK_INBOUND_WEBHOOK_PASSWORD
    return bool(settings.POSTMARK_INBOUND_WEBHOOK_USER.strip()) and bool(password and password.get_secret_value().strip())


def credentials_match(user: Optional[str], password: Optional[str]) -> bool:
    """Both compared in constant time, and both always compared, so the answer's timing says nothing about which was wrong."""
    expected_password = settings.POSTMARK_INBOUND_WEBHOOK_PASSWORD
    wanted_user = settings.POSTMARK_INBOUND_WEBHOOK_USER.strip().encode()
    wanted_password = (expected_password.get_secret_value().strip() if expected_password else "").encode()
    user_ok = secrets.compare_digest((user or "").encode(), wanted_user)
    password_ok = secrets.compare_digest((password or "").encode(), wanted_password)
    return bool(user_ok & password_ok)


def ip_allowed(client_ip: Optional[str]) -> bool:
    raw = settings.POSTMARK_INBOUND_ALLOWED_IPS.strip()
    if not raw:
        return True
    try:
        address = ipaddress.ip_address((client_ip or "").strip())
    except ValueError:
        return False
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            if address in ipaddress.ip_network(part, strict=False):
                return True
        except ValueError:
            logger.warning("inbound_email.bad_allowed_ip_entry")
    return False


# ------------------------------------------------------------------------------------------------ addresses

def address_for(token: str) -> Optional[str]:
    """The address people forward to, or None while email-in has no address form configured."""
    domain = settings.INBOUND_EMAIL_DOMAIN.strip().lower()
    if domain:
        return f"{token}@{domain}"
    hashed = settings.POSTMARK_INBOUND_HASH.strip()
    if hashed:
        return f"{hashed}+{token}@{POSTMARK_HOST}"
    return None


def new_token() -> str:
    return secrets.token_hex(16)  # 32 lower-case hex characters, 128 bits: never derived from a name or slug


def active_address(db: Session, *, organization_id: uuid.UUID, workspace_id: uuid.UUID,
                   user_id: Optional[uuid.UUID] = None) -> InboundEmailAddress:
    row = db.execute(
        sa.select(InboundEmailAddress).where(InboundEmailAddress.workspace_id == workspace_id, InboundEmailAddress.retired_at.is_(None))
    ).scalar_one_or_none()
    if row is None:
        row = InboundEmailAddress(organization_id=organization_id, workspace_id=workspace_id, token=new_token(), created_by_user_id=user_id)
        db.add(row)
        db.flush()
    return row


def rotate(db: Session, *, organization_id: uuid.UUID, workspace_id: uuid.UUID, user_id: Optional[uuid.UUID]) -> InboundEmailAddress:
    """A new token. The old one stops working at once, and mail still sent to it is refused (403)."""
    now = datetime.now(timezone.utc)
    db.execute(
        sa.update(InboundEmailAddress)
        .where(InboundEmailAddress.workspace_id == workspace_id, InboundEmailAddress.retired_at.is_(None))
        .values(retired_at=now)
    )
    row = InboundEmailAddress(organization_id=organization_id, workspace_id=workspace_id, token=new_token(), created_by_user_id=user_id)
    db.add(row)
    db.flush()
    return row


# ------------------------------------------------------------------------------------------------ the message

@dataclass
class Attachment:
    name: str
    content_type: str
    data: bytes
    content_id: str = ""
    problem: str = ""


@dataclass
class Parsed:
    message_id: str
    sender: str
    sender_name: str
    subject: str
    received_at: datetime
    token_candidates: list[str]
    attachments: list[Attachment] = field(default_factory=list)


def _local_part_candidates(address: str) -> list[str]:
    local = (address or "").split("@", 1)[0].strip().lower()
    out = []
    if "+" in local:
        out.append(local.split("+", 1)[1])
    out.append(local)
    return out


def parse(payload: Any) -> Parsed:
    """Read a Postmark inbound body. Raises InboundRefused(422) when it is not one."""
    if not isinstance(payload, dict):
        raise InboundRefused(422, "not a Postmark inbound message")
    message_id = str(payload.get("MessageID") or "").strip()
    if not message_id or len(message_id) > 200:
        raise InboundRefused(422, "no MessageID")
    full = payload.get("FromFull") if isinstance(payload.get("FromFull"), dict) else {}
    sender = str(full.get("Email") or payload.get("From") or "").strip().lower()
    if "<" in sender and ">" in sender:
        sender = sender[sender.index("<") + 1: sender.index(">")].strip()
    if not sender or "@" not in sender:
        raise InboundRefused(422, "no sender")
    raw_date = str(payload.get("Date") or "")
    try:
        received = parsedate_to_datetime(raw_date) if raw_date else datetime.now(timezone.utc)
        if received.tzinfo is None:
            received = received.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        received = datetime.now(timezone.utc)

    candidates: list[str] = []
    mailbox_hash = str(payload.get("MailboxHash") or "").strip().lower()
    if mailbox_hash:
        candidates.append(mailbox_hash)
    to_full = payload.get("ToFull") if isinstance(payload.get("ToFull"), list) else []
    for entry in to_full:
        if isinstance(entry, dict):
            if entry.get("MailboxHash"):
                candidates.append(str(entry["MailboxHash"]).strip().lower())
            candidates.extend(_local_part_candidates(str(entry.get("Email") or "")))
    for key in ("OriginalRecipient", "To"):
        candidates.extend(_local_part_candidates(str(payload.get(key) or "")))
    candidates = [c for c in dict.fromkeys(candidates) if TOKEN_RE.match(c)]

    attachments: list[Attachment] = []
    for raw in payload.get("Attachments") or []:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("Name") or "attachment")[:255]
        content_type = str(raw.get("ContentType") or "application/octet-stream")[:128]
        try:
            data = base64.b64decode(str(raw.get("Content") or ""), validate=False)
            problem = ""
        except (binascii.Error, ValueError):
            data, problem = b"", "could not be decoded"
        attachments.append(Attachment(name=name, content_type=content_type, data=data, content_id=str(raw.get("ContentID") or ""), problem=problem))

    return Parsed(
        message_id=message_id,
        sender=sender[:320],
        sender_name=str(full.get("Name") or payload.get("FromName") or "")[:200],
        subject=str(payload.get("Subject") or "")[:500],
        received_at=received,
        token_candidates=candidates,
        attachments=attachments,
    )


def resolve_token(db: Session, candidates: list[str]) -> Optional[InboundEmailAddress]:
    """The address row for the first candidate that is a known token. A retired one is returned too: the caller refuses it."""
    if not candidates:
        return None
    rows = db.execute(sa.select(InboundEmailAddress).where(InboundEmailAddress.token.in_(candidates))).scalars().all()
    by_token = {row.token: row for row in rows}
    for candidate in candidates:
        if candidate in by_token:
            return by_token[candidate]
    return None


def sender_allowed(db: Session, *, workspace_id: uuid.UUID, address: str) -> bool:
    address = address.strip().lower()
    domain = address.rsplit("@", 1)[-1]
    patterns = set(
        db.execute(sa.select(InboundEmailSender.pattern).where(InboundEmailSender.workspace_id == workspace_id)).scalars()
    )
    return address in patterns or domain in patterns


def normalise_pattern(raw: str) -> str:
    """An address or a domain, lower-case. `@supplier.in` and `*@supplier.in` mean the domain."""
    value = (raw or "").strip().lower().lstrip("*")
    if value.startswith("@"):
        value = value[1:]
    if not value or " " in value or len(value) > 255 or value.count("@") > 1 or not re.match(r"^[a-z0-9._%+\-]+(@[a-z0-9.\-]+)?$|^[a-z0-9.\-]+$", value):
        raise ValueError("Enter an email address (ap@supplier.in) or a domain (supplier.in).")
    return value


# ------------------------------------------------------------------------------------------------ processing

@dataclass
class Outcome:
    status: str                      # "accepted" | "held" | "duplicate"
    documents: int = 0
    message: Optional[InboundMessage] = None
    hold_code: Optional[str] = None


class _LimitHit(Exception):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _is_ignorable_inline(attachment: Attachment) -> bool:
    return (
        attachment.content_type.lower().startswith("image/")
        and bool(attachment.content_id)
        and len(attachment.data) < int(settings.INBOUND_EMAIL_IGNORE_INLINE_IMAGES_KB) * 1024
    )


def _source(message: InboundMessage) -> dict[str, Any]:
    return {
        "kind": "EMAIL", "sender": message.from_address, "subject": message.subject,
        "received_at": message.received_at.isoformat() if message.received_at else None,
        "inbound_message_id": str(message.id),
    }


def _ingest_attachments(db: Session, message: InboundMessage, attachments: list[Attachment],
                        created_keys: list[str]) -> tuple[list[dict[str, Any]], list[str]]:
    """Add what can be added. Returns (outcomes, document ids); every stored object is appended to `created_keys` so the
    caller can delete them if it rolls back. Raises `_LimitHit` when the trial or the plan stops an addition; the caller
    rolls everything back and holds the message."""
    outcomes: list[dict[str, Any]] = []
    work_item_ids: list[str] = []
    for attachment in attachments:
        entry: dict[str, Any] = {"name": attachment.name, "content_type": attachment.content_type, "size": len(attachment.data)}
        outcomes.append(entry)
        if attachment.problem or not attachment.data:
            entry.update(outcome=UNREADABLE, note=attachment.problem or "The attachment is empty.")
            continue
        if _is_ignorable_inline(attachment):
            entry.update(outcome=IGNORED_INLINE, note="A small inline image (a signature or logo) is ignored.")
            continue
        try:
            if archive_intake.is_zip(attachment.name, attachment.data[:4]):
                batch = archive_intake.accept_archive(
                    db, organization_id=message.organization_id, workspace_id=message.workspace_id, user_id=None,
                    filename=attachment.name, data=attachment.data, source=_source(message),
                )
                entry.update(outcome=ZIP_QUEUED, batch_id=str(batch.id))
                key = getattr(batch, "archive_storage_key", None)
                if key:
                    created_keys.append(key)
                continue
            if attachment.name.lower().endswith(".json") or attachment.content_type.lower() == "application/json":
                if archive.looks_like_gstr2b(attachment.data):
                    entry.update(outcome=SKIPPED_GSTR2B, note=archive.GSTR2B_SKIP_MESSAGE)
                    continue
            import io

            spool = io.BytesIO(attachment.data)
            validated = file_validation_service.validate_spooled(
                spool, len(attachment.data), declared_mime=attachment.content_type, original_filename=attachment.name,
                allowed_mimes=file_validation_service.workspace_allowed_mimes(db, message.workspace_id, settings.ALLOWED_MIME_TYPES),
                max_pages=settings.MAX_DOCUMENT_PAGES, scrub_metadata=settings.SCRUB_UPLOAD_METADATA,
            )
            with validated:
                result = document_intake_service.ingest_validated(
                    db, validated, organization_id=message.organization_id, workspace_id=message.workspace_id, uploader_id=None,
                    enqueue_extraction=True, source=_source(message),
                )
            created_keys.append(result.storage_key)
            work_item_ids.append(str(result.work_item.id))
            entry.update(outcome=ADDED, work_item_id=str(result.work_item.id))
        except archive_intake.ArchiveNotAccepted as exc:
            entry.update(outcome=REFUSED, note=exc.message)
        except file_validation_service.FileValidationError as exc:
            entry.update(outcome=REFUSED, note=str(exc)[:300])
        except trial_service.TrialEndedError as exc:
            raise _LimitHit(HOLD_TRIAL_ENDED) from exc
        except Exception as exc:  # noqa: BLE001 - classified below
            from app.core.exceptions import SpendLimitExceededError

            if isinstance(exc, (plan_admission.PlanLimitExceededError, SpendLimitExceededError)):
                raise _LimitHit(HOLD_OVER_LIMIT) from exc
            raise
    return outcomes, work_item_ids


def _delete_objects(keys: list[str]) -> None:
    driver = get_storage_driver()
    for key in keys:
        try:
            driver.delete(key)
        except Exception:  # noqa: BLE001 - a leftover object is housekeeping
            logger.warning("inbound_email.object_not_deleted")


def _store_for_approval(message: InboundMessage, attachments: list[Attachment]) -> list[dict[str, Any]]:
    """Keep the attachments of a held message so an admin can approve it later (deleted on approval, discard or sweep)."""
    driver = get_storage_driver()
    out: list[dict[str, Any]] = []
    for attachment in attachments:
        entry: dict[str, Any] = {"name": attachment.name, "content_type": attachment.content_type, "size": len(attachment.data),
                                 "content_id": attachment.content_id, "outcome": HELD_FILE}
        if attachment.data and not attachment.problem and not _is_ignorable_inline(attachment):
            key = tenant_key(organization_id=message.organization_id, namespace=StorageNamespace.DERIVED, file_id=uuid.uuid4())
            driver.put(key, attachment.data, "application/octet-stream")
            entry["storage_key"] = key
        else:
            entry["outcome"] = IGNORED_INLINE if _is_ignorable_inline(attachment) else UNREADABLE
        out.append(entry)
    return out


def _notify_held(db: Session, message: InboundMessage) -> None:
    from app.models.notification import NotificationPriority, NotificationType
    from app.services import organization_notification_service as notices

    notices.emit_to_roles(
        db, organization_id=message.organization_id, roles=(OrganizationRole.OWNER, OrganizationRole.ADMIN),
        title="An email is waiting for approval" if message.hold_code in APPROVABLE else "An email was held",
        message=f"A message from {message.from_address} was held: {message.hold_message} Open Settings, Email-in, to see it.",
        notification_type=NotificationType.DOCUMENT, priority=NotificationPriority.WARNING, category="workflow",
    )


def _finish(db: Session, message: InboundMessage, outcomes: list[dict[str, Any]], work_item_ids: list[str]) -> Outcome:
    usable = [o for o in outcomes if o["outcome"] in (ADDED, ZIP_QUEUED)]
    message.attachments = outcomes
    message.work_item_ids = work_item_ids
    if usable:
        message.status, message.hold_code, message.hold_message = "ACCEPTED", None, None
        return Outcome("accepted", documents=len(work_item_ids), message=message)
    gstr = [o for o in outcomes if o["outcome"] == SKIPPED_GSTR2B]
    code = HOLD_GSTR2B if gstr and len(gstr) == len([o for o in outcomes if o["outcome"] not in (IGNORED_INLINE,)]) else HOLD_NO_ATTACHMENT
    message.status, message.hold_code, message.hold_message = "HELD", code, HOLD_TEXT[code]
    _notify_held(db, message)
    return Outcome("held", message=message, hold_code=code)


def _run(db: Session, message: InboundMessage, attachments: list[Attachment]) -> Outcome:
    """Add the attachments atomically: a plan or trial stop holds the whole message and leaves nothing behind."""
    created: list[str] = []
    savepoint = db.begin_nested()
    try:
        trial_service.assert_trial_active(db, organization_id=message.organization_id)
        outcomes, work_item_ids = _ingest_attachments(db, message, attachments, created)
    except trial_service.TrialEndedError:
        savepoint.rollback()
        return _hold(db, message, attachments, HOLD_TRIAL_ENDED, created)
    except _LimitHit as hit:
        savepoint.rollback()
        return _hold(db, message, attachments, hit.code, created)
    except Exception:
        savepoint.rollback()
        _delete_objects(created)
        raise
    savepoint.commit()
    return _finish(db, message, outcomes, work_item_ids)


def _hold(db: Session, message: InboundMessage, attachments: list[Attachment], code: str, created_keys: list[str]) -> Outcome:
    _delete_objects(created_keys)
    message.status, message.hold_code, message.hold_message = "HELD", code, HOLD_TEXT[code]
    message.attachments = _store_for_approval(message, attachments)
    message.work_item_ids = []
    _notify_held(db, message)
    return Outcome("held", message=message, hold_code=code)


def receive(db: Session, *, address: InboundEmailAddress, parsed: Parsed) -> Outcome:
    """One delivery, for the workspace its address belongs to. The caller commits."""
    message = InboundMessage(
        organization_id=address.organization_id, workspace_id=address.workspace_id, message_id=parsed.message_id,
        from_address=parsed.sender, from_name=parsed.sender_name or None, subject=parsed.subject or None,
        received_at=parsed.received_at, status="ACCEPTED",
    )
    try:
        with db.begin_nested():
            db.add(message)
            db.flush()
    except IntegrityError:
        return Outcome("duplicate")  # Postmark delivered it twice (a retry): the first one already counted

    if not sender_allowed(db, workspace_id=address.workspace_id, address=parsed.sender):
        return _hold(db, message, parsed.attachments, HOLD_SENDER, [])
    return _run(db, message, parsed.attachments)


def _load_stored(message: InboundMessage) -> list[Attachment]:
    driver = get_storage_driver()
    out: list[Attachment] = []
    for entry in message.attachments or []:
        key = entry.get("storage_key")
        if not key:
            continue
        try:
            data = driver.get(key)
        except Exception:  # noqa: BLE001 - the stored copy is gone; the admin is told in the list
            data = b""
        out.append(Attachment(name=entry.get("name") or "attachment", content_type=entry.get("content_type") or "application/octet-stream",
                              data=data, content_id=entry.get("content_id") or "", problem="" if data else "The stored copy is no longer available."))
    return out


def _forget_stored(message: InboundMessage) -> None:
    _delete_objects([e["storage_key"] for e in (message.attachments or []) if e.get("storage_key")])


def approve(db: Session, *, message: InboundMessage, user_id: Optional[uuid.UUID]) -> Outcome:
    """An admin accepts a held message: its stored attachments go through the same path a direct arrival takes (so the plan
    still applies). If the plan still stops it, it stays held with the reason and nothing is added."""
    if message.status != "HELD" or message.hold_code not in APPROVABLE:
        raise ValueError("This message cannot be approved.")
    previous = [e["storage_key"] for e in (message.attachments or []) if e.get("storage_key")]
    outcome = _run(db, message, _load_stored(message))
    _delete_objects(previous)  # a re-hold stored fresh copies; an acceptance no longer needs any
    if outcome.status == "accepted":
        message.decided_by_user_id, message.decided_at = user_id, datetime.now(timezone.utc)
    return outcome


def discard(db: Session, *, message: InboundMessage, user_id: Optional[uuid.UUID]) -> None:
    if message.status != "HELD":
        raise ValueError("Only a held message can be discarded.")
    _forget_stored(message)
    message.attachments = [{**{k: v for k, v in e.items() if k != "storage_key"}, "outcome": "DISCARDED"} for e in (message.attachments or [])]
    message.status = "DISCARDED"
    message.decided_by_user_id, message.decided_at = user_id, datetime.now(timezone.utc)


def sweep(db: Session, *, now: Optional[datetime] = None, days: Optional[int] = None) -> int:
    """Delete held and discarded messages (and the attachments kept for them) older than INBOUND_EMAIL_HELD_DAYS."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days if days is not None else int(settings.INBOUND_EMAIL_HELD_DAYS))
    rows = db.execute(
        sa.select(InboundMessage).where(InboundMessage.status.in_(("HELD", "DISCARDED")), InboundMessage.created_at < cutoff)
    ).scalars().all()
    for row in rows:
        _forget_stored(row)
        db.delete(row)
    return len(rows)


def fingerprint(value: str) -> str:
    """A short non-reversible tag for logs ("who sent this") that never reveals the address."""
    return hashlib.sha256(value.encode()).hexdigest()[:10]


def workspace_is_live(db: Session, workspace_id: uuid.UUID) -> bool:
    row = db.get(Workspace, workspace_id)
    return row is not None and row.status == WorkspaceStatus.ACTIVE


__all__ = [
    "APPROVABLE", "Attachment", "InboundRefused", "Outcome", "Parsed", "active_address", "address_for", "approve", "credentials_match",
    "discard", "fingerprint", "ip_allowed", "is_enabled", "new_token", "normalise_pattern", "parse", "receive", "resolve_token", "rotate",
    "sender_allowed", "sweep", "workspace_is_live",
]
