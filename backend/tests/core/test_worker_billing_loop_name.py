"""The billing worker loop is called `billing`; the old name `stripe` is gone (Session B, B1).

It reconciles every gateway's inbound events (Dodo's first). `--loop stripe` was accepted for one
release after the rename; no deployment still starts the worker that way, so the alias was removed.
"""

from __future__ import annotations

import pytest

from app import worker

pytestmark = pytest.mark.no_db


def test_billing_is_a_loop_and_all_runs_it() -> None:
    parser = worker.build_parser()
    assert parser.parse_args(["--loop", "billing"]).loop == "billing"
    assert "billing" in worker.ALL_LOOPS and "stripe" not in worker.ALL_LOOPS


def test_the_old_name_is_not_a_loop(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit):
        worker.build_parser().parse_args(["--loop", "stripe"])
    assert "invalid choice" in capsys.readouterr().err


def test_no_alias_machinery_is_left() -> None:
    assert not hasattr(worker, "LOOP_ALIASES")
    assert not hasattr(worker, "canonical_loop")
