"""The product is Servabo: the old name appears only in history and in refused secrets.

FlowPilot AI was renamed Servabo on 2026-10-16. This fails when the old name comes back anywhere
in the repository outside an explicit allowlist, in any spelling (FlowPilot, FLOWPILOT_, flowpilot),
in a file's content or in its path. Each allowed place says why:

* history: `archive/`, the Alembic migrations (a migration that ran must not change), the campaign
  records that keep the old name with a dated note at the top, and the one test that runs the
  historical rename migration;
* values that are evidence, not branding: the two leaked default peppers the production guard
  refuses (they were published once and stay refused forever), the backup key fingerprint's salt
  (changing it would change every fingerprint), the git-history scan's list of old development
  passwords, and the word the password policy will not let a password be built from.

The one-release compatibility (reading the old `FLOWPILOT_*` settings, old API-key prefixes,
old backup names, `--loop stripe`) was removed in Session B: no installation from before the
rename remains, and there is no longer a place in the code or the scripts that spells the old name.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.no_db

REPO = Path(__file__).resolve().parents[3]
OLD = re.compile("flow" + "pilot", re.IGNORECASE)  # split so this file does not match itself

ALLOWED_PREFIXES = (
    "archive/",
    "backend/alembic/versions/",
    "docs/hardening/e2e-screenshots/",
)
ALLOWED_FILES = {
    # History, each with "FlowPilot AI was renamed Servabo on 2026-10-16" at the top.
    "CHANGELOG.md",
    "docs/hardening/FINDINGS.md",
    "docs/hardening/NEEDS-OWNER.md",
    "docs/hardening/STATE.md",
    "docs/hardening/00-map.md",
    "docs/hardening/01-baseline.md",
    "docs/hardening/02-security-deploy.md",
    "docs/hardening/03-coverage.md",
    "docs/hardening/04-core-engines.md",
    "docs/hardening/05-production-readiness.md",
    "docs/hardening/05-release-readiness.md",
    "docs/hardening/06-launch-certification.md",
    "docs/hardening/CAMPAIGN-MAP.md",
    "docs/hardening/NEXT-SESSION-PROMPT.md",
    # The test that runs the historical rename migration (w1a1) against the old database setting.
    "backend/tests/scripts/test_database_names_say_servabo.py",
}
#: Lines allowed anywhere: evidence values, not the brand.
ALLOWED_LINES = (
    re.compile(r"flowpilot_default_(api_key_pepper_secret|redis_identity_pepper)_2026"),
    re.compile(r'b"flowpilot-backup-key-id\\x00"'),
    re.compile(r"KNOWN_DEV_PASSWORDS = \{"),
    # The old name stays a word passwords may not be built from, and the test that proves it.
    re.compile(r'^_PRODUCT_WORDS = \("servabo", "flowpilot", "flow pilot"\)$'),
    re.compile(r'"flowpilot2026"'),
    # The README says, once, what the product was called before (and where the renames are listed).
    re.compile("^The product was called Flow" "Pilot AI until 2026-10-16"),
)


def _tracked() -> list[str]:
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("not a git checkout")
    return [p for p in out.decode().split("\0") if p]


def _allowed_file(path: str) -> bool:
    return path in ALLOWED_FILES or path.startswith(ALLOWED_PREFIXES) or path == _THIS


_THIS = str(Path(__file__).resolve().relative_to(REPO))


def _offending_lines(text: str) -> list[tuple[int, str]]:
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        if not OLD.search(line):
            continue
        if any(pattern.search(line) for pattern in ALLOWED_LINES):
            continue
        found.append((number, line.strip()[:160]))
    return found


def test_no_tracked_path_carries_the_old_name() -> None:
    bad = [p for p in _tracked() if OLD.search(p) and not _allowed_file(p)]
    assert not bad, f"rename these files: {bad}"


def test_no_file_says_the_old_name_outside_the_allowlist() -> None:
    problems: list[str] = []
    for path in _tracked():
        if _allowed_file(path):
            continue
        full = REPO / path
        if not full.is_file():
            continue
        data = full.read_bytes()
        if b"\0" in data[:8192]:
            continue  # binary
        text = data.decode("utf-8", errors="replace")
        problems += [f"{path}:{n}: {line}" for n, line in _offending_lines(text)]
    assert not problems, "the old name is back:\n" + "\n".join(problems[:50])


def test_the_history_files_say_when_the_name_changed() -> None:
    for path in ALLOWED_FILES:
        if not path.endswith(".md"):
            continue
        head = "\n".join((REPO / path).read_text(encoding="utf-8").splitlines()[:6])
        assert "renamed Servabo on 2026-10-16" in head, f"{path} lacks the rename note at the top"


def test_the_guard_itself_catches_the_old_name() -> None:
    sample = "x\nFLOW" "PILOT_X\nFlow" "Pilot AI here\n"
    assert _offending_lines(sample) == [(2, "FLOW" "PILOT_X"), (3, "Flow" "Pilot AI here")]


def test_no_block_marks_a_place_where_the_old_name_is_tolerated() -> None:
    """The `one-release names` blocks are gone: nothing is exempt from the guard by a comment."""
    marker = ">>> one-release" + " names"
    holders = [p for p in _tracked() if (REPO / p).is_file() and not p.startswith(ALLOWED_PREFIXES)
               and p != _THIS and marker in (REPO / p).read_text(encoding="utf-8", errors="replace")
               and not p.startswith("docs/hardening/")]
    assert not holders, f"remove the one-release blocks from: {holders}"


def test_the_file_that_read_the_old_names_is_gone() -> None:
    assert not (REPO / "backend" / "app" / "core" / "legacy_names.py").exists()
