"""The owner's Windows scripts still match the stack (campaign session 4, §C.8).

    pytest tests/infra/test_windows_dev_scripts.py -q

The owner develops on Windows 11 with `start_dev.ps1` and `reset_dev.ps1`. They cannot run here
(they start `cmd.exe` and Docker Desktop), and nothing else would notice when the stack moves under
them: a renamed compose service, a seed script that loses a flag, a worker option that changes, a
setting that no longer exists. This reads what each script names and checks it against the code.
Both scripts parse with PowerShell 7.4's own parser (checked in session 4; run
`pwsh -NoProfile -Command "[System.Management.Automation.Language.Parser]::ParseFile(...)"`).
"""

from __future__ import annotations

import os
import pathlib
import re
import subprocess
import sys

import pytest
import yaml

from app.core.config import Settings

pytestmark = pytest.mark.no_db

BACKEND = pathlib.Path(__file__).resolve().parents[2]
REPO = BACKEND.parent
START = (REPO / "start_dev.ps1").read_text(encoding="utf-8")
START_SH = (REPO / "start_dev.sh").read_text(encoding="utf-8")
RESET = (REPO / "reset_dev.ps1").read_text(encoding="utf-8")
DEV_COMPOSE = yaml.safe_load((BACKEND / "docker-compose.yml").read_text())

#: Read from the environment, not through Settings: the AWS SDK's own variables, and the process
#: role, which `app/db/session.py` reads before Settings exist (it picks the connection pool).
NOT_SETTINGS = {"AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "SERVICE_ROLE"}


def _help(*argv: str) -> str:
    done = subprocess.run([sys.executable, *argv, "--help"], cwd=BACKEND, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr[-1500:]
    return done.stdout


def test_the_compose_services_they_start_exist() -> None:
    for script in (START, RESET):
        for match in re.finditer(r"docker compose up -d ([a-z\- ]+)", script):
            for service in match.group(1).split():
                assert service in DEV_COMPOSE["services"], service


def test_the_settings_they_write_are_real_settings() -> None:
    written = set(re.findall(r"'([A-Z][A-Z0-9_]+)'\s*=", START))
    written |= set(re.findall(r"@\('([A-Z_', ]+)'\)", START)[0].replace("'", "").replace(" ", "").split(","))
    written |= {"EMAIL_ENCRYPTION_KEYS"}
    assert written - NOT_SETTINGS <= set(Settings.model_fields), sorted(written - NOT_SETTINGS - set(Settings.model_fields))
    assert "STORAGE_BACKEND" in written and "'STORAGE_BACKEND'       = 'minio'" in START


def test_the_ports_they_assume_are_the_compose_ports() -> None:
    assert "'POSTGRES_PORT'         = '5432'" in START and "127.0.0.1:5432:5432" in DEV_COMPOSE["services"]["db"]["ports"]
    assert "redis://localhost:6379/0" in START and "127.0.0.1:6379:6379" in DEV_COMPOSE["services"]["redis"]["ports"]
    assert "http://localhost:9000" in START and "127.0.0.1:9000:9000" in DEV_COMPOSE["services"]["minio"]["ports"]


def test_the_scripts_and_flags_they_call_exist() -> None:
    assert "--version auto" in START and "--version" in _help("scripts/seed_price_book.py")
    assert "--allow-unpriced" in START and "--allow-unpriced" in _help("scripts/seed_quota_tiers.py")
    assert "seed_admin.py --json" in START and "--json" in _help("scripts/seed_admin.py")
    reset = _help("scripts/reset_dev_environment.py")
    for flag in re.findall(r"\$resetArgs \+= '(--[a-z\-]+)'", RESET):
        assert flag in reset, flag
    worker = _help("-m", "app.worker")
    for flag in ("--loop", "--profile", "--log-level"):
        assert flag in START and flag in worker, flag


def test_they_ask_for_the_python_the_images_use() -> None:
    dockerfile = (BACKEND / "Dockerfile").read_text()
    assert "python:3.12" in dockerfile
    assert "'py -3.12', 'python3.12'" in START


def _without_strings_and_comments(script: str) -> str:
    """PowerShell with its quoted strings and comments removed, so only the code's own braces remain."""
    script = re.sub(r"(?s)<#.*?#>", "", script)
    script = re.sub(r"'(?:''|[^'\n])*'", "''", script)
    script = re.sub(r'"(?:`.|[^"`\n])*"', '""', script)
    return re.sub(r"(?m)#.*$", "", script)


def test_the_powershell_script_is_balanced() -> None:
    """A cheap parse check where PowerShell itself is not installed: every bracket closes."""
    code = _without_strings_and_comments(START)
    for opening, closing in ("{}", "()", "[]"):
        assert code.count(opening) == code.count(closing), (opening, code.count(opening), code.count(closing))


def test_the_website_switch_is_not_inside_the_api_failure_branch() -> None:
    """The -Website block once sat inside `if the API did not bind`, so -Website ran only when the API failed."""
    failed = START.index("The API did not bind")
    leaves = START.index("exit 1", failed)
    website = START.index("if ($Website) {", failed)
    assert leaves < website, "-Website is started only on the path that exits"
    assert START.index("if (-not $NoFrontend) {", failed) > website


def test_dodo_webhooks_switch_refuses_live_mode_before_anything_starts_in_both_scripts() -> None:
    assert "[switch]$DodoWebhooks" in START
    assert "--dodo-webhooks)" in START_SH
    for script, first_step in ((START, "Write-Step '1/8"), (START_SH, "step '1/8")):
        refusal = script.index("TEST mode only")
        assert refusal < script.index(first_step), "the refusal comes after the script began to start the stack"
        assert "DODO_LIVEMODE" in script[:refusal]


def test_the_relay_is_started_and_stopped_by_the_scripts_with_flags_the_helper_has() -> None:
    start_help, stop_help = _help("scripts/dodo_relay.py", "start"), _help("scripts/dodo_relay.py", "stop")
    for script in (START, START_SH):
        assert "scripts/dodo_relay.py start" in script and "scripts/dodo_relay.py stop" in script
        for flag in ("--api-port", "--run-dir", "--env-file"):
            assert flag in script and flag in start_help, flag
    assert "--run-dir" in stop_help


def test_the_shell_script_parses_and_refuses_live_mode_without_touching_docker() -> None:
    assert subprocess.run(["bash", "-n", str(REPO / "start_dev.sh")], capture_output=True).returncode == 0
    done = subprocess.run(["bash", str(REPO / "start_dev.sh"), "--dodo-webhooks"], capture_output=True, text=True,
                          timeout=60, env={**os.environ, "DODO_LIVEMODE": "true"})
    assert done.returncode == 1
    assert "TEST mode only" in done.stdout + done.stderr
    assert "Verifying prerequisites" not in done.stdout
    assert not (REPO / ".dev").exists() or not (REPO / ".dev" / "dodo-relay.json").exists()


def test_the_shell_script_names_the_new_switch_in_its_help() -> None:
    help_text = subprocess.run(["bash", str(REPO / "start_dev.sh"), "--help"], capture_output=True, text=True, timeout=60).stdout
    assert "--dodo-webhooks" in help_text
