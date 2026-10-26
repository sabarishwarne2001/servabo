"""Exercise real populated TRINETRA collections in the shared IDOR sweep."""
from tests.trinetra.test_api import world  # noqa: F401
from tests.trinetra.test_workflows import setup_case
from tests.engines.isolation import assert_workspace_isolated


def test_reviewed_credit_isolated_through_every_collection(engines, world):
    setup_case(engines.client, engines.tenant, world)
    assert_workspace_isolated(engines, collections=("trinetra",))
