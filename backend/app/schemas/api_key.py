"""API Key validation and serialization contracts (ARCH-08 §9.6)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.core.scopes import ApiKeyScope


def clean_key_name(value: str) -> str:
    """A key's name is what is left after the spaces around it are removed, and it cannot be empty (F-588).

    Without this a key could be issued with a name of spaces (blank in the list, impossible to tell from another)
    and two keys could differ only by a space.
    """
    cleaned = value.strip()
    if not cleaned:
        raise ValueError("The name cannot be empty or only spaces.")
    return cleaned


def unique_scopes(value: list[ApiKeyScope]) -> list[ApiKeyScope]:
    """Each scope once, in the order given."""
    return list(dict.fromkeys(value))


def future_expiry(value: Optional[datetime]) -> Optional[datetime]:
    """An expiry that has already passed would issue a key that never works (F-589)."""
    if value is None:
        return None
    moment = value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)
    if moment <= datetime.now(timezone.utc):
        raise ValueError("The expiry must be in the future.")
    return value


class ApiKeyCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    scopes: list[ApiKeyScope] = Field(..., min_length=1)
    expires_at: Optional[datetime] = None

    _name = field_validator("name")(clean_key_name)
    _scopes = field_validator("scopes")(unique_scopes)
    _expiry = field_validator("expires_at")(future_expiry)


class ApiKeyRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    organization_id: uuid.UUID
    user_id: Optional[uuid.UUID] = None
    name: str
    scopes: list[str]
    last_used_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    deactivated_at: Optional[datetime] = None
    deactivated_reason: Optional[str] = None
    previous_secret_expires_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class ApiKeyResponse(BaseModel):
    """Returned ONCE upon issuance. Contains the full token string."""
    api_key: ApiKeyRead
    token: str = Field(description="Full token string. Shown ONCE. Never stored or logged.")


class ApiKeyRotateRequest(BaseModel):
    force: bool = Field(default=False, description="Force rotation even if a dual-secret overlap is currently active.")
