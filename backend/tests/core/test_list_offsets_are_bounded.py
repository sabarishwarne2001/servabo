"""Every `offset` a list endpoint takes has an upper bound (Session B).

An `offset` with only `ge=0` accepts 10**30, which Postgres refuses as an out-of-range bigint: the
person got a 500. The API's own schema is the list of places to check, so a new list endpoint cannot
forget it.
"""

from __future__ import annotations

import pytest

from app.main import app

pytestmark = pytest.mark.no_db

#: What Postgres accepts as an OFFSET (bigint), and far more than any list is long.
LARGEST_OFFSET = 2**31 - 1


def test_every_offset_parameter_has_a_maximum() -> None:
    unbounded = []
    for path, operations in app.openapi()["paths"].items():
        for method, operation in operations.items():
            for parameter in operation.get("parameters", []):
                if parameter.get("name") == "offset" and parameter.get("in") == "query":
                    maximum = (parameter.get("schema") or {}).get("maximum")
                    if maximum is None or maximum > LARGEST_OFFSET:
                        unbounded.append(f"{method.upper()} {path}")
    assert not unbounded, "offset has no maximum on: " + ", ".join(sorted(unbounded))
