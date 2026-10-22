"""What `.github/workflows/ci.yml` must keep promising (Session H).

* The Frontend job blocks on the advisories that reach customers (`npm audit --omit=dev --audit-level=high`), as the
  Website job does. Build-tool advisories (a development dependency such as `braces` under Tailwind 3) are printed in
  a separate step that may not block: no fixed version exists, nothing in the shipped bundle is affected, and a
  blocking check on them turned a green pull request into a red `main` for something nobody could fix (N-119).
  Making the shipped-dependency check non-blocking, or removing it, would let a real customer-facing advisory through.
* Every job runs on a pinned runner image, not `ubuntu-latest`: when the label moves to a newer Ubuntu, a prebuilt
  Python can be missing and every backend job breaks without a code change.
* The Frontend job runs the unit tests (`npm run test:unit`, Session J); dropping the step would let the builder's model
  and the dialogs change with nothing watching them.
* The three setup actions run on Node.js 24 (GitHub is retiring Node.js 20 for actions).
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

pytestmark = pytest.mark.no_db

CI = Path(__file__).resolve().parents[3] / ".github" / "workflows" / "ci.yml"
PRODUCTION_AUDIT = "npm audit --omit=dev --audit-level=high"


@pytest.fixture(scope="module")
def jobs() -> dict:
    return yaml.safe_load(CI.read_text(encoding="utf-8"))["jobs"]


def _audit_steps(job: dict) -> list[dict]:
    return [s for s in job["steps"] if "npm audit" in s.get("run", "")]


@pytest.mark.parametrize("name", ["frontend", "website"])
def test_shipped_dependencies_are_audited_and_the_audit_blocks(jobs, name):
    blocking = [s for s in _audit_steps(jobs[name]) if PRODUCTION_AUDIT in s["run"]]
    assert blocking, f"the {name} job must run `{PRODUCTION_AUDIT}`"
    for step in blocking:
        assert not step.get("continue-on-error"), f"`{step['name']}` must fail the {name} job when it finds something"
        assert "|| true" not in step["run"] and "exit 0" not in step["run"]


def test_build_tool_advisories_are_reported_but_never_block(jobs):
    reports = [s for s in _audit_steps(jobs["frontend"]) if PRODUCTION_AUDIT not in s["run"]]
    assert reports, "the Frontend job should still print the full `npm audit` (development tools included)"
    assert all(s.get("continue-on-error") is True for s in reports)
    assert all("--omit=dev" not in s["run"] for s in reports), "the report is the one that includes development tools"


def test_every_job_runs_on_a_pinned_runner_image(jobs):
    runners = {name: job.get("runs-on") for name, job in jobs.items()}
    assert all(isinstance(r, str) and r.startswith("ubuntu-2") and r != "ubuntu-latest" for r in runners.values()), runners


#: the first major of each action whose `action.yml` says `using: node24` (checked against the tags, Session H)
FIRST_NODE_24 = {"actions/checkout": 5, "actions/setup-node": 5, "actions/setup-python": 6, "actions/upload-artifact": 6}


@pytest.mark.parametrize("action", sorted(FIRST_NODE_24))
def test_the_setup_actions_run_on_node_24(jobs, action):
    versions = {s["uses"] for job in jobs.values() for s in job["steps"] if s.get("uses", "").startswith(action + "@")}
    assert versions, f"{action} is used"
    assert all(int(v.split("@v")[1].split(".")[0]) >= FIRST_NODE_24[action] for v in versions), versions


def test_the_frontend_job_runs_the_unit_tests(jobs):
    runs = [s.get("run", "") for s in jobs["frontend"]["steps"]]
    assert "npm run test:unit" in runs
    step = next(s for s in jobs["frontend"]["steps"] if s.get("run") == "npm run test:unit")
    assert not step.get("continue-on-error"), "a failing unit test must fail the Frontend job"
