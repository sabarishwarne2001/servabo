"""Bring Dodo's webhooks to a laptop (Session C, C2): the relay behind `start_dev.ps1 -DodoWebhooks`.

    python scripts/dodo_relay.py start --api-port 8000 --run-dir ../.dev
    python scripts/dodo_relay.py stop  --run-dir ../.dev

Dodo cannot reach `localhost`, so something has to carry its events to this machine. Two ways, the
first one preferred:

1. Dodo's own CLI, `dodo wh listen` (npm install -g dodopayments-cli, then `dodo login` in Test Mode).
   It keeps a connection open to Dodo and forwards each event, with its original `webhook-id`,
   `webhook-signature` and `webhook-timestamp` headers, to the local URL. The first time it runs it
   creates an endpoint in Dodo's dashboard (Developer > Webhooks) whose signing secret is the value for
   DODO_WEBHOOK_SECRET. Test mode only.
2. A Cloudflare quick tunnel, `cloudflared tunnel --url http://localhost:8000`. It prints a public
   https://….trycloudflare.com address; you register
   https://….trycloudflare.com/api/v1/billing/webhooks/dodo as a test-mode endpoint in Dodo's
   dashboard. It forwards the bytes unchanged, so signatures verify. The address changes on every start.

This script detects which tool is installed, starts it in the background (log and process id under
`--run-dir`), and prints, in plain words, what to click in Dodo's dashboard. It never writes a secret
anywhere: the signing secret goes into backend/.env by hand, and it only reports whether that line is
filled in (never its value). `stop` ends the relay. It refuses to run with DODO_LIVEMODE=true.

Exit status: 0 running (or stopped); 1 no tool installed / the relay did not start; 2 refused (live mode).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence

WEBHOOK_PATH = "/api/v1/billing/webhooks/dodo"
STATE_FILE = "dodo-relay.json"
LOG_FILE = "dodo-relay.log"
TUNNEL_URL = re.compile(r"https://[a-z0-9][a-z0-9-]*\.trycloudflare\.com")
CLI_HELP = "https://docs.dodopayments.com/developer-resources/sdks/cli"


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=value lines of a .env file (no quoting rules beyond stripping quotes)."""
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8-sig").splitlines()
    except OSError:
        return values
    for line in lines:
        match = re.match(r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if match and not line.lstrip().startswith("#"):
            values[match.group(1)] = match.group(2).strip().strip('"').strip("'")
    return values


def live_mode_refusal(environ: Mapping[str, str], env_file: Optional[Path] = None) -> Optional[str]:
    """The message to print when DODO_LIVEMODE is on (in the environment or backend/.env), else None."""
    value = environ.get("DODO_LIVEMODE")
    if value is None and env_file is not None:
        value = read_env_file(env_file).get("DODO_LIVEMODE")
    if str(value or "").strip().lower() in ("1", "true", "yes", "on"):
        return ("Refused: DODO_LIVEMODE is true. The webhook relay is for Dodo's TEST mode only. Set "
                "DODO_LIVEMODE=false in backend/.env (and turn on Test Mode in Dodo's dashboard), then run this again.")
    return None


def detect_tool(path: Optional[str] = None, prefer: str = "auto") -> Optional[str]:
    """'dodo' (Dodo's CLI) or 'cloudflared', whichever is installed; the CLI first unless `prefer` says otherwise."""
    have = {"dodo": shutil.which("dodo", path=path), "cloudflared": shutil.which("cloudflared", path=path)}
    order = {"auto": ("dodo", "cloudflared"), "cli": ("dodo",), "tunnel": ("cloudflared",)}[prefer]
    return next((name for name in order if have[name]), None)


def cli_command(local_url: str, path: Optional[str] = None) -> list[str]:
    """`dodo wh listen` with the local URL, in the form this CLI version accepts (asked of its own --help)."""
    exe = shutil.which("dodo", path=path) or "dodo"
    flag_form = False
    try:
        helped = subprocess.run([exe, "wh", "listen", "--help"], capture_output=True, text=True, timeout=30,
                                env={**os.environ, "PATH": path} if path else None)
        flag_form = "--forward-to" in (helped.stdout + helped.stderr)
    except (OSError, subprocess.SubprocessError):
        pass
    return [exe, "wh", "listen", *(["--forward-to", local_url] if flag_form else [local_url])]


def tunnel_command(api_port: int, path: Optional[str] = None) -> list[str]:
    return [shutil.which("cloudflared", path=path) or "cloudflared", "tunnel", "--no-autoupdate",
            "--url", f"http://localhost:{api_port}"]


def install_help() -> list[str]:
    return [
        "Neither relay tool is installed. Install one of these, then run this again:",
        "  Dodo's CLI (first choice, test mode only):",
        "      npm install -g dodopayments-cli",
        "      dodo login            (choose Test Mode)",
        f"      docs: {CLI_HELP}",
        "  Cloudflare quick tunnel (fallback):",
        "      Windows:  winget install --id Cloudflare.cloudflared",
        "      macOS:    brew install cloudflared",
        "      Linux:    https://developers.cloudflare.com/cloudflare-one/connections/connect-networks/downloads/",
    ]


def steps(tool: str, local_url: str, public_url: Optional[str], secret_is_set: bool, restart_hint: str) -> list[str]:
    """What to do in Dodo's dashboard, in plain words."""
    lines: list[str] = []
    if tool == "dodo":
        lines += [
            "Webhook relay running: Dodo's own CLI (test mode only).",
            f"  It forwards each event Dodo sends to {local_url}, with Dodo's original signature headers.",
            "",
            "What to do:",
            "  1. Once only, in a terminal: run  dodo login  and choose Test Mode. If the relay printed a login",
            "     error in .dev/dodo-relay.log, log in, then run this script again.",
            "  2. In Dodo's dashboard switch Test Mode on, open Developer > Webhooks. The first time the relay",
            "     runs, the CLI creates an endpoint there for you.",
            "  3. Open that endpoint and reveal its Signing secret (it starts with whsec_).",
        ]
    else:
        endpoint = f"{public_url}{WEBHOOK_PATH}"
        lines += [
            "Webhook relay running: a Cloudflare quick tunnel.",
            f"  It carries Dodo's events, bytes unchanged, from {public_url} to {local_url}.",
            "",
            "What to do:",
            "  1. In Dodo's dashboard switch Test Mode on, open Developer > Webhooks and add an endpoint.",
            "  2. Endpoint URL (copy this line exactly):",
            f"         {endpoint}",
            "  3. Subscribe it to every subscription, payment, refund and dispute event (or all events).",
            "  4. Save, open the endpoint and reveal its Signing secret (it starts with whsec_).",
            "  This address changes every time the relay starts: edit the endpoint's URL in Dodo (or delete the",
            "  old endpoint and add a new one) after each start.",
        ]
    step = 5 if tool == "cloudflared" else 4
    if secret_is_set:
        lines += [f"  {step}. backend/.env already has a DODO_WEBHOOK_SECRET. If it is not this endpoint's secret, replace it:"]
    else:
        lines += [f"  {step}. backend/.env has no DODO_WEBHOOK_SECRET yet. Add this line (with the secret you just copied):"]
    lines += [
        "         DODO_WEBHOOK_SECRET=whsec_...",
        "     Keep it in backend/.env only: never paste it into a chat, a commit or a screenshot.",
        f"  {step + 1}. Restart so the API reads it:  {restart_hint}",
        "  Dodo's dashboard labels may differ a little from these words; the Webhooks page is under Developer.",
        "",
        "To stop the relay later: the same script with its stop switch (-Stop / --stop) ends it with everything else.",
    ]
    return lines


# ---------------------------------------------------------------------------- state and processes


def _state_path(run_dir: Path) -> Path:
    return run_dir / STATE_FILE


def _alive(pid: int) -> bool:
    if sys.platform == "win32":
        done = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True)
        return str(pid) in done.stdout
    try:
        os.waitpid(pid, os.WNOHANG)  # reaps the process if it is our own child and has ended
    except ChildProcessError:
        pass
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _kill_tree(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        return
    try:
        os.killpg(pid, signal.SIGTERM)
    except OSError:
        try:
            os.kill(pid, signal.SIGTERM)
        except OSError:
            return
    for _ in range(20):
        if not _alive(pid):
            return
        time.sleep(0.25)
    try:
        os.killpg(pid, signal.SIGKILL)
    except OSError:
        pass


def _launch(command: Sequence[str], log: Path) -> subprocess.Popen[Any]:
    handle = open(log, "wb")
    options: dict[str, Any] = {"stdin": subprocess.DEVNULL, "stdout": handle, "stderr": subprocess.STDOUT}
    if sys.platform == "win32":
        options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | 0x08000000  # no console window
    else:
        options["start_new_session"] = True
    return subprocess.Popen(list(command), **options)


def _wait_for_url(log: Path, process: subprocess.Popen[Any], timeout: float) -> Optional[str]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = TUNNEL_URL.findall(log.read_text(encoding="utf-8", errors="replace")) if log.exists() else []
        if found:
            return found[-1]
        if process.poll() is not None:
            return None
        time.sleep(0.3)
    return None


def _tail(log: Path, lines: int = 15) -> str:
    try:
        return "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


def start(args: argparse.Namespace, environ: Mapping[str, str]) -> int:
    env_file = Path(args.env_file) if args.env_file else None
    refusal = live_mode_refusal(environ, env_file)
    if refusal:
        print(refusal)
        return 2
    run_dir = Path(args.run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)
    local_url = f"http://localhost:{args.api_port}{WEBHOOK_PATH}"
    secret = (environ.get("DODO_WEBHOOK_SECRET") or (read_env_file(env_file).get("DODO_WEBHOOK_SECRET") if env_file else "") or "").strip()

    existing = _state_path(run_dir)
    if existing.exists():
        state = json.loads(existing.read_text(encoding="utf-8"))
        if _alive(int(state["pid"])):
            print("The webhook relay is already running.\n")
            print("\n".join(steps(state["tool"], local_url, state.get("public_url"), bool(secret), args.restart_hint)))
            return 0
        existing.unlink()

    path = environ.get("PATH")
    tool = detect_tool(path, args.prefer)
    if tool is None:
        print("\n".join(install_help()))
        return 1
    command = cli_command(local_url, path) if tool == "dodo" else tunnel_command(args.api_port, path)
    log = run_dir / LOG_FILE
    process = _launch(command, log)
    public_url: Optional[str] = None
    if tool == "cloudflared":
        public_url = _wait_for_url(log, process, args.wait)
        if public_url is None:
            _kill_tree(process.pid)
            print("The tunnel did not give an address. Last lines of its log:\n" + _tail(log))
            return 1
    else:
        time.sleep(min(args.wait, 3))
        if process.poll() is not None:
            print("Dodo's CLI stopped straight away. Last lines of its log:\n" + _tail(log))
            print("\nIf it asks you to log in: run  dodo login  (Test Mode), then run this again.")
            return 1
    _state_path(run_dir).write_text(json.dumps({"tool": tool, "pid": process.pid, "public_url": public_url,
                                                "command": [Path(command[0]).name, *command[1:]]}), encoding="utf-8")
    print("\n".join(steps(tool, local_url, public_url, bool(secret), args.restart_hint)))
    return 0


def stop(args: argparse.Namespace) -> int:
    state_file = _state_path(Path(args.run_dir))
    if not state_file.exists():
        print("No webhook relay is running.")
        return 0
    state = json.loads(state_file.read_text(encoding="utf-8"))
    if _alive(int(state["pid"])):
        _kill_tree(int(state["pid"]))
        print(f"Webhook relay stopped ({state['tool']}).")
    else:
        print("The webhook relay had already stopped.")
    state_file.unlink()
    return 0


def main(argv: Optional[list[str]] = None, environ: Optional[Mapping[str, str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Bring Dodo's test-mode webhooks to this machine.")
    sub = parser.add_subparsers(dest="command", required=True)
    go = sub.add_parser("start", help="start the relay and print what to click in Dodo's dashboard")
    go.add_argument("--api-port", type=int, default=8000)
    go.add_argument("--run-dir", default=".dev", help="where the log and process id are kept")
    go.add_argument("--env-file", default=".env", help="backend/.env (read to see whether the secret is set; never written)")
    go.add_argument("--prefer", choices=("auto", "cli", "tunnel"), default="auto")
    go.add_argument("--wait", type=float, default=45.0, help="seconds to wait for the relay to come up")
    go.add_argument("--restart-hint", default=r".\start_dev.ps1 -Stop  then  .\start_dev.ps1 -DodoWebhooks")
    end = sub.add_parser("stop", help="stop the relay")
    end.add_argument("--run-dir", default=".dev")
    args = parser.parse_args(argv)
    env = dict(os.environ if environ is None else environ)
    return start(args, env) if args.command == "start" else stop(args)


if __name__ == "__main__":
    sys.exit(main())
