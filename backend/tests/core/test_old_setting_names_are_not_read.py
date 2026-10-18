"""The pre-rename setting names are gone (Session B, B1).

The product was called FlowPilot AI until 2026-10-16. For one release the old `FLOWPILOT_*` names
were still read, and old display values were shown as Servabo. There are no installations from
before the rename (CHANGELOG), so that compatibility was removed: the old names do nothing.
"""

from __future__ import annotations

import importlib

import pytest

from app.core.config import Settings

pytestmark = pytest.mark.no_db

OLD = "FLOW" + "PILOT_"  # split so the guard test does not match this file


def test_the_module_that_read_the_old_names_is_gone() -> None:
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module("app.core.legacy_names")


def test_the_edition_setting_ignores_the_old_names(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SERVABO_EDITION", raising=False)
    monkeypatch.delenv("SERVABO_DEPLOYMENT_ID", raising=False)
    monkeypatch.setenv(OLD + "EDITION", "sovereign")
    monkeypatch.setenv(OLD + "DEPLOYMENT_ID", "plant-7")
    s = Settings(_env_file=None)
    assert s.SERVABO_EDITION == "saas"
    assert s.SERVABO_DEPLOYMENT_ID == ""


def test_the_new_edition_names_are_read(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SERVABO_EDITION", "sovereign")
    monkeypatch.setenv("SERVABO_DEPLOYMENT_ID", "plant-7")
    s = Settings(_env_file=None)
    assert (s.SERVABO_EDITION, s.SERVABO_DEPLOYMENT_ID) == ("sovereign", "plant-7")


def test_a_display_setting_is_shown_as_it_was_written(monkeypatch: pytest.MonkeyPatch) -> None:
    """Nothing rewrites a setting's text any more: what the operator wrote is what people see."""
    for name in ("PROJECT_NAME", "API_TITLE", "PLATFORM_SMTP_FROM_NAME"):
        monkeypatch.delenv(name, raising=False)
    s = Settings(_env_file=None, PROJECT_NAME="Acme Docs", API_TITLE="Acme API", PLATFORM_SMTP_FROM_NAME="Acme")
    assert (s.PROJECT_NAME, s.API_TITLE, s.PLATFORM_SMTP_FROM_NAME) == ("Acme Docs", "Acme API", "Acme")
    old_product = "Flow" + "Pilot AI"
    assert Settings(_env_file=None, PROJECT_NAME=old_product).PROJECT_NAME == old_product


def test_the_scripts_read_only_the_new_names(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    from scripts import backup_floor

    monkeypatch.delenv("SERVABO_BACKUP_DIR", raising=False)
    monkeypatch.setenv(OLD + "BACKUP_DIR", str(tmp_path / "old"))
    assert backup_floor.backup_dir() != (tmp_path / "old").resolve()
    monkeypatch.setenv("SERVABO_BACKUP_DIR", str(tmp_path / "new"))
    assert backup_floor.backup_dir() == (tmp_path / "new").resolve()
