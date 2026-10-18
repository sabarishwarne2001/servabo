"""scripts/dodo_relay.py: bringing Dodo's test-mode webhooks to a laptop (Session C, C2).

The real tools (Dodo's CLI, cloudflared) are replaced by tiny programs that print what the real ones
print, so the whole flow runs here: which tool is chosen, the command it is given, the steps printed
for a person, that the live mode is refused, that no secret is ever written or shown, and that `stop`
really ends the process.
"""

from __future__ import annotations

import importlib.util
import json
import os
import stat
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "dodo_relay.py"
SECRET = "whsec_THIS_MUST_NEVER_BE_PRINTED"


def _module():
    spec = importlib.util.spec_from_file_location("dodo_relay_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _program(directory: Path, name: str, body: str) -> Path:
    path = directory / name
    path.write_text("#!/bin/sh\n" + body, encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IEXEC)
    return path


def fake_dodo_cli(directory: Path, *, flag_form: bool, exits_at_once: bool = False) -> Path:
    help_text = "Usage: dodo wh listen [options]\\n  --forward-to <url>" if flag_form else "Usage: dodo wh listen <url>"
    return _program(directory, "dodo", f"""
echo "$@" >> "{directory}/dodo-args.txt"
if [ "$3" = "--help" ]; then printf '{help_text}\\n'; exit 0; fi
{'echo "Not logged in. Run dodo login"; exit 1' if exits_at_once else 'echo "Listening for webhooks..."; exec /bin/sleep 300'}
""")


def fake_cloudflared(directory: Path, *, prints_url: bool = True) -> Path:
    url_line = ("echo '2026-10-18T10:00:01Z INF |  https://quiet-river-demo-1234.trycloudflare.com  |' >&2"
                if prints_url else "echo 'INF Requesting new quick Tunnel' >&2")
    return _program(directory, "cloudflared", f"""
echo "$@" >> "{directory}/cloudflared-args.txt"
{url_line}
exec /bin/sleep 300
""")


@pytest.fixture()
def bins(tmp_path):
    directory = tmp_path / "bin"
    directory.mkdir()
    return directory


@pytest.fixture()
def relay():
    module = _module()
    started: list[Path] = []

    def run(argv: list[str], path: Path, run_dir: Path, **env: str) -> int:
        full = ["start", "--run-dir", str(run_dir), "--wait", "6", *argv] if argv[:1] != ["stop"] else ["stop", "--run-dir", str(run_dir)]
        started.append(run_dir)
        return module.main(full, {"PATH": str(path), **env})

    yield run
    for run_dir in started:  # never leave a fake relay running
        if (run_dir / "dodo-relay.json").exists():
            module.main(["stop", "--run-dir", str(run_dir)], {})


def _running(run_dir: Path) -> bool:
    pid = json.loads((run_dir / "dodo-relay.json").read_text())["pid"]
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def test_live_mode_is_refused_before_anything_starts(bins, tmp_path, relay, capsys) -> None:
    fake_dodo_cli(bins, flag_form=True)
    run_dir = tmp_path / "run"
    assert relay([], bins, run_dir, DODO_LIVEMODE="true") == 2
    out = capsys.readouterr().out
    assert "TEST mode only" in out and "DODO_LIVEMODE=false" in out
    assert not (run_dir / "dodo-relay.json").exists() and not (bins / "dodo-args.txt").exists()


def test_live_mode_in_the_env_file_is_refused_too(bins, tmp_path, relay, capsys) -> None:
    fake_cloudflared(bins)
    env_file = tmp_path / ".env"
    env_file.write_text("DODO_LIVEMODE=true\n", encoding="utf-8")
    assert relay(["--env-file", str(env_file)], bins, tmp_path / "run") == 2
    assert "TEST mode only" in capsys.readouterr().out


def test_with_no_tool_installed_both_ways_are_explained(bins, tmp_path, relay, capsys) -> None:
    assert relay([], bins, tmp_path / "run") == 1
    out = capsys.readouterr().out
    assert "npm install -g dodopayments-cli" in out and "dodo login" in out and "cloudflared" in out


def test_dodo_cli_is_the_first_choice_and_gets_the_local_url(bins, tmp_path, relay, capsys) -> None:
    fake_dodo_cli(bins, flag_form=False)
    fake_cloudflared(bins)
    run_dir = tmp_path / "run"
    assert relay(["--api-port", "8123"], bins, run_dir) == 0
    out = capsys.readouterr().out
    assert "Dodo's own CLI (test mode only)" in out and "trycloudflare" not in out
    assert "http://localhost:8123/api/v1/billing/webhooks/dodo" in out
    assert "Developer > Webhooks" in out and "Signing secret" in out and "dodo login" in out
    args = (bins / "dodo-args.txt").read_text().splitlines()
    assert "wh listen http://localhost:8123/api/v1/billing/webhooks/dodo" in args  # the form this CLI accepts
    assert not (bins / "cloudflared-args.txt").exists()
    assert _running(run_dir)


def test_the_flag_form_is_used_when_the_cli_asks_for_it(bins, tmp_path, relay) -> None:
    fake_dodo_cli(bins, flag_form=True)
    assert relay([], bins, tmp_path / "run") == 0
    assert "wh listen --forward-to http://localhost:8000/api/v1/billing/webhooks/dodo" in (bins / "dodo-args.txt").read_text().splitlines()


def test_the_tunnel_is_the_fallback_and_its_address_is_printed_ready_to_paste(bins, tmp_path, relay, capsys) -> None:
    fake_cloudflared(bins)
    run_dir = tmp_path / "run"
    assert relay(["--api-port", "8123"], bins, run_dir) == 0
    out = capsys.readouterr().out
    assert "         https://quiet-river-demo-1234.trycloudflare.com/api/v1/billing/webhooks/dodo" in out
    assert "Test Mode" in out and "Signing secret" in out and "changes every time" in out
    assert "tunnel --no-autoupdate --url http://localhost:8123" in (bins / "cloudflared-args.txt").read_text()
    assert json.loads((run_dir / "dodo-relay.json").read_text())["public_url"] == "https://quiet-river-demo-1234.trycloudflare.com"


def test_prefer_tunnel_skips_the_cli(bins, tmp_path, relay, capsys) -> None:
    fake_dodo_cli(bins, flag_form=True)
    fake_cloudflared(bins)
    assert relay(["--prefer", "tunnel"], bins, tmp_path / "run") == 0
    assert "Cloudflare quick tunnel" in capsys.readouterr().out and not (bins / "dodo-args.txt").exists()


def test_a_second_start_does_not_start_a_second_relay(bins, tmp_path, relay, capsys) -> None:
    fake_cloudflared(bins)
    run_dir = tmp_path / "run"
    assert relay([], bins, run_dir) == 0
    first = json.loads((run_dir / "dodo-relay.json").read_text())["pid"]
    capsys.readouterr()
    assert relay([], bins, run_dir) == 0
    assert "already running" in capsys.readouterr().out
    assert json.loads((run_dir / "dodo-relay.json").read_text())["pid"] == first
    assert len((bins / "cloudflared-args.txt").read_text().splitlines()) == 1


def test_stop_ends_the_process_and_can_be_repeated(bins, tmp_path, relay, capsys) -> None:
    fake_cloudflared(bins)
    run_dir = tmp_path / "run"
    relay([], bins, run_dir)
    pid = json.loads((run_dir / "dodo-relay.json").read_text())["pid"]
    capsys.readouterr()
    assert relay(["stop"], bins, run_dir) == 0
    assert "stopped" in capsys.readouterr().out and not (run_dir / "dodo-relay.json").exists()
    assert not _module()._alive(pid)
    assert relay(["stop"], bins, run_dir) == 0
    assert "No webhook relay is running" in capsys.readouterr().out


def test_a_tunnel_that_never_gives_an_address_is_reported_and_cleaned_up(bins, tmp_path, capsys) -> None:
    fake_cloudflared(bins, prints_url=False)
    run_dir = tmp_path / "run"
    code = _module().main(["start", "--run-dir", str(run_dir), "--wait", "1"], {"PATH": str(bins)})
    assert code == 1
    assert "did not give an address" in capsys.readouterr().out and not (run_dir / "dodo-relay.json").exists()


def test_a_cli_that_is_not_logged_in_says_so(bins, tmp_path, capsys) -> None:
    fake_dodo_cli(bins, flag_form=True, exits_at_once=True)
    code = _module().main(["start", "--run-dir", str(tmp_path / "run"), "--wait", "2"], {"PATH": str(bins)})
    assert code == 1
    out = capsys.readouterr().out
    assert "Not logged in" in out and "dodo login" in out


def test_a_secret_is_never_printed_and_the_env_file_is_never_written(bins, tmp_path, relay, capsys) -> None:
    fake_cloudflared(bins)
    env_file = tmp_path / ".env"
    text = f"DODO_LIVEMODE=false\nDODO_WEBHOOK_SECRET={SECRET}\n"
    env_file.write_text(text, encoding="utf-8")
    assert relay(["--env-file", str(env_file)], bins, tmp_path / "run") == 0
    out = capsys.readouterr().out
    assert SECRET not in out and "already has a DODO_WEBHOOK_SECRET" in out
    assert env_file.read_text(encoding="utf-8") == text

    other = tmp_path / "other"
    other.mkdir()
    empty = tmp_path / "empty.env"
    empty.write_text("DODO_LIVEMODE=false\nDODO_WEBHOOK_SECRET=\n", encoding="utf-8")
    assert relay(["--env-file", str(empty)], bins, other / "run") == 0
    assert "has no DODO_WEBHOOK_SECRET yet" in capsys.readouterr().out
    assert empty.read_text(encoding="utf-8") == "DODO_LIVEMODE=false\nDODO_WEBHOOK_SECRET=\n"


def test_the_environment_variable_secret_is_not_printed_either(bins, tmp_path, relay, capsys) -> None:
    fake_cloudflared(bins)
    relay([], bins, tmp_path / "run", DODO_WEBHOOK_SECRET=SECRET)
    assert SECRET not in capsys.readouterr().out
