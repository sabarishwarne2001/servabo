"""The whole TRINETRA migration chain, down and up again, with every table the chain adds holding a row (Final 2T, finish line).

Down to the revision before `tr1a1`, then back to the one head. The canonical workspace survives; the TRINETRA rows do not (each
migration's docstring says what its downgrade deletes), and a second upgrade recreates empty tables. Run after the isolation
sweep's seed, which fills the cases, statement, inquiry, suggestion, deductor, pairing and approval tables; this adds the
policy and the notice claim."""


from sqlalchemy import text

from app.models.trinetra import TrinetraCredit, TrinetraInquiry, TrinetraNoticeSend, TrinetraPolicy
from app.models.workspace import Workspace
from tests.conftest import TEST_DB_URL
from tests.trinetra.test_isolation_sweep import seeded  # noqa: F401
from tests.trinetra.test_api import world  # noqa: F401
from tests.trinetra.test_resolution import mailbox  # noqa: F401


def test_the_whole_chain_goes_down_and_up_with_every_table_populated(client, tenant, world, seeded, db_session):  # noqa: F811
    from alembic import command
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    db_session.add(TrinetraPolicy(organization_id=tenant.organization.id, threshold_micros=1_000_000_000, actions=["CA_REVIEWED"],
                                  approver_role="OWNER"))
    db_session.add(TrinetraNoticeSend(organization_id=tenant.organization.id, kind="stale", key="case:1", recipients=1))
    db_session.commit()
    assert db_session.query(TrinetraInquiry).count() == 1
    workspace_id = tenant.workspace.id
    db_session.close()

    config = Config("alembic.ini")
    config.set_main_option("sqlalchemy.url", TEST_DB_URL)
    command.downgrade(config, "k1a7_pack_check_dismissals")
    command.upgrade(config, "head")
    command.downgrade(config, "k1a7_pack_check_dismissals")
    command.upgrade(config, "head")

    head = ScriptDirectory.from_config(config).get_current_head()
    assert db_session.execute(text("select version_num from alembic_version")).scalar() == head
    assert len(ScriptDirectory.from_config(config).get_heads()) == 1
    for model in (TrinetraCredit, TrinetraInquiry, TrinetraPolicy, TrinetraNoticeSend):
        assert db_session.query(model).count() == 0, model.__name__
    assert db_session.get(Workspace, workspace_id) is not None
