"""`servabo-install-host-jobs` installs the cron files and proves every job can report (Final session 2A, Phase 2).

It runs here as on a Compose server, with the cron folder, the settings file and the app replaced: a temporary
folder for /etc/cron.d, a sweepers.env written by the test, a stand-in that plays the app (readiness, and the
report path with its token), and `cron`/`pgrep` stand-ins on PATH so "cron is installed and running" is true.
"""

from __future__ import annotations

import http.server
import json
import os
import pathlib
import re
import secrets
import stat
import subprocess
import threading
from typing import Iterator

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = BACKEND / "deploy" / "bin" / "servabo-install-host-jobs"
TOKEN = secrets.token_urlsafe(32)
REPORT_PATH = re.compile(r"^/api/v1/ops/safety-jobs/(?P<job>[^/]+)/runs$")

pytestmark = pytest.mark.no_db


class _App(http.server.BaseHTTPRequestHandler):
    reports: list[tuple[str, str, str]] = []

    def do_GET(self) -> None:  # noqa: N802
        self.send_response(200 if self.path == "/api/v1/health/ready" else 404)
        self.end_headers()

    def do_POST(self) -> None:  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        match = REPORT_PATH.match(self.path)
        if not match:
            self.send_response(404)
        elif self.headers.get("X-Servabo-Report-Token") != TOKEN:
            self.send_response(401)
        else:
            type(self).reports.append((match["job"], body["outcome"], body.get("detail", "")))
            self.send_response(202)
        self.end_headers()

    def log_message(self, *args: object) -> None:
        return


@pytest.fixture()
def app() -> Iterator[str]:
    _App.reports = []
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _App)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


def _server(tmp: pathlib.Path, app: str, token: str = TOKEN) -> dict[str, str]:
    fake_bin = tmp / "bin"
    fake_bin.mkdir()
    for tool in ("cron", "pgrep"):
        (fake_bin / tool).write_text("#!/bin/sh\nexit 0\n")
        (fake_bin / tool).chmod(stat.S_IRWXU)
    (tmp / "cron.d").mkdir()
    config = tmp / "sweepers.env"
    config.write_text(f'SERVABO_PUBLIC_URL={app}\nSAFETY_JOB_REPORT_TOKEN="{token}"\nSERVABO_LOG_DIR={tmp}/logs\n'
                      f"LOCK_DIR={tmp}/locks\nSERVABO_BACKUP_DIR={tmp}/backups\n")
    import getpass

    return {**os.environ, "PATH": f"{fake_bin}:{os.environ['PATH']}", "SERVABO_SWEEPER_ENV": str(config),
            "SERVABO_CRON_TARGET": str(tmp / "cron.d"), "SERVABO_DEPLOY_DIR": str(BACKEND / "deploy"),
            "SERVABO_JOB_USER": getpass.getuser(), "SERVABO_INSTALL_UNPRIVILEGED": "1", "SERVABO_ROOT": str(tmp)}


def _run(env: dict[str, str], *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run([str(SCRIPT), *args], env=env, capture_output=True, text=True, timeout=120)


def test_a_compose_server_gets_both_files_and_every_job_reports(app: str, tmp_path: pathlib.Path) -> None:
    done = _run(_server(tmp_path, app))
    assert done.returncode == 0, done.stdout + done.stderr
    installed = sorted(p.name for p in (tmp_path / "cron.d").iterdir())
    assert installed == ["servabo-compose-backups", "servabo-sweepers"]
    sweepers = (tmp_path / "cron.d" / "servabo-sweepers").read_text()
    for name in ("dr-heartbeat", "base-backup", "pitr-drill"):  # N-012: no WAL archiving on Compose
        assert re.search(rf"^# .*servabo-sweep {name}\b", sweepers, re.M), name
    started = sorted(job for job, outcome, detail in _App.reports if outcome == "started" and "install check" in detail)
    assert len(started) == 15 and {"compliance", "erp_postings", "backup", "restore-drill"} <= set(started)
    assert not {"dr-heartbeat", "base-backup", "pitr-drill"} & set(started)
    assert ("uptime", "succeeded", "ready") in _App.reports  # the one job safe to run for real
    assert not [r for r in _App.reports if r[1] == "succeeded" and r[0] != "uptime"], "an install check must not count as a run"
    assert "OK   compliance: the app accepted" in done.stdout and "FIX" not in done.stdout


def test_a_wrong_token_is_named_with_its_fix(app: str, tmp_path: pathlib.Path) -> None:
    done = _run(_server(tmp_path, app, token="x" * 40))
    assert done.returncode == 1
    assert "refused the token: SAFETY_JOB_REPORT_TOKEN differs from .env.production" in done.stdout


def test_check_changes_nothing_and_says_what_is_missing(app: str, tmp_path: pathlib.Path) -> None:
    env = _server(tmp_path, app)
    pathlib.Path(env["SERVABO_SWEEPER_ENV"]).write_text("")  # no address, no token
    done = _run(env, "--check")
    assert done.returncode == 1 and list((tmp_path / "cron.d").iterdir()) == []
    assert "set SERVABO_PUBLIC_URL" in done.stdout and "set SAFETY_JOB_REPORT_TOKEN" in done.stdout
    assert "servabo-sweepers is not installed" in done.stdout


def test_two_backup_schedules_are_refused(app: str, tmp_path: pathlib.Path) -> None:
    env = _server(tmp_path, app)
    (tmp_path / "cron.d" / "servabo-backups").write_text("# an older install\n")
    done = _run(env)
    assert done.returncode == 1 and "two backup schedules" in done.stdout
