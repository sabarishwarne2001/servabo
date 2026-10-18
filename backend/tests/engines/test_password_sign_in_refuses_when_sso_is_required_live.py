"""A password sign-in into an organization that requires single sign-on is refused at the door.

Before, `POST /auth/login` answered 200 and opened a session for a member of such an organization;
every later request into it then answered 403 `ORGANIZATION_SSO_REQUIRED`. The person was signed in
to a screen where nothing worked. The sign-in itself now refuses, after the password is proved (so
a wrong password still gets the same plain "Incorrect email or password" and discloses nothing),
and opens no session.

A person whose password is still useful somewhere (a member of another organization that does not
require SSO, or an owner whose break-glass is on) is not locked out: the per-request check stays
the guard for the organization that requires it.
"""

from __future__ import annotations

import uuid

from app.models.organization import (
    MembershipStatus,
    Organization,
    OrganizationMember,
    OrganizationRole,
)
from app.models.user_session import UserSession
from tests.engines.conftest import Engines
from tests.engines.test_require_sso_is_enforced_live import _require_sso

API = "/api/v1"


def _password_login(engines: Engines, email: str, password: str = "test-password"):
    return engines.client.post(
        f"{API}/auth/login", data={"username": email, "password": password}
    )


def _sessions_of(engines: Engines, user_id: uuid.UUID) -> int:
    return engines.db.query(UserSession).filter(UserSession.user_id == user_id).count()


def test_a_member_of_an_sso_required_organization_cannot_sign_in_with_a_password(engines: Engines) -> None:
    contributor = engines.tenant.contributor.user
    _require_sso(engines)
    before = _sessions_of(engines, contributor.id)

    refused = _password_login(engines, contributor.email)

    assert refused.status_code == 403, refused.text
    body = refused.json()
    assert body["code"] == "SSO_SIGN_IN_REQUIRED", body
    assert "single sign-on" in body["message"].lower(), body
    assert "access_token" not in refused.text
    assert "set-cookie" not in {key.lower() for key in refused.headers}, "no session cookie is set"
    assert _sessions_of(engines, contributor.id) == before, "no session was opened"


def test_a_wrong_password_still_gets_the_plain_refusal_and_learns_nothing_about_sso(engines: Engines) -> None:
    contributor = engines.tenant.contributor.user
    _require_sso(engines)

    refused = _password_login(engines, contributor.email, password="not-the-password")

    assert refused.status_code == 401, refused.text
    assert "SSO" not in refused.text and "single sign-on" not in refused.text.lower()


def test_an_owner_with_break_glass_on_can_still_sign_in_with_a_password(engines: Engines) -> None:
    owner = engines.tenant.owner.user
    _require_sso(engines)

    allowed = _password_login(engines, owner.email)

    assert allowed.status_code == 200, allowed.text
    assert allowed.json()["access_token"]


def test_an_organization_that_does_not_require_sso_signs_in_as_before(engines: Engines) -> None:
    engines.plan("enterprise")

    allowed = _password_login(engines, engines.tenant.contributor.user.email)

    assert allowed.status_code == 200, allowed.text


def test_a_member_who_also_belongs_to_an_organization_without_the_requirement_can_sign_in(engines: Engines) -> None:
    contributor = engines.tenant.contributor.user
    other = Organization(name="Password Ltd", slug=f"password-{uuid.uuid4().hex[:6]}")
    engines.db.add(other)
    engines.db.flush()
    engines.db.add(
        OrganizationMember(
            organization_id=other.id,
            user_id=contributor.id,
            role=OrganizationRole.MEMBER,
            status=MembershipStatus.ACTIVE,
        )
    )
    engines.db.commit()
    _require_sso(engines)

    allowed = _password_login(engines, contributor.email)

    assert allowed.status_code == 200, "the password still opens the organization that has no requirement"
    token = allowed.json()["access_token"]
    # ... and the organization that requires SSO still refuses that session, request by request.
    refused = engines.client.get(
        engines.url("/work-items"), headers={"Authorization": f"Bearer {token}"}
    )
    assert refused.status_code == 403, refused.text
    assert refused.json()["code"] == "ORGANIZATION_SSO_REQUIRED"
