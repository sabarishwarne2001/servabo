"""Session B (B1) — the dev stack's databases are reachable from this computer only.

`ports: ["5432:5432"]` publishes a port on every network interface, so on café Wi-Fi anyone could
reach the local Postgres (default password `servabo`), Redis (no password) and MinIO with its
console (`minioadmin`). The four are published on 127.0.0.1 only; the browser and the API on the
same computer reach them as before, and the containers reach each other over Docker's own network.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

BACKEND = Path(__file__).resolve().parents[2]
COMPOSE = BACKEND / "docker-compose.yml"

pytestmark = pytest.mark.no_db

#: The services that hold data or credentials, and the container ports they publish.
DATA_SERVICES = {"db": {"5432"}, "redis": {"6379"}, "minio": {"9000", "9001"}}


def _services() -> dict:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))["services"]


def _published(service: dict) -> list[tuple[str, str, str]]:
    """(host address, host port, container port) for each `ports:` entry."""
    found = []
    for entry in service.get("ports", []):
        parts = str(entry).split(":")
        if len(parts) == 2:
            parts = ["", *parts]
        address, host_port, container_port = parts[-3] if len(parts) == 3 else "", parts[-2], parts[-1]
        found.append((address, host_port, container_port.split("/")[0]))
    return found


@pytest.mark.parametrize("name", sorted(DATA_SERVICES))
def test_a_data_service_is_published_on_127_0_0_1_only(name: str) -> None:
    published = _published(_services()[name])
    assert {container for _, _, container in published} == DATA_SERVICES[name]
    open_to_the_network = [entry for entry in published if entry[0] != "127.0.0.1"]
    assert not open_to_the_network, f"{name} is reachable from other computers: {open_to_the_network}"


def test_the_parser_sees_an_open_port_as_open() -> None:
    assert _published({"ports": ["5432:5432"]}) == [("", "5432", "5432")]
    assert _published({"ports": ["127.0.0.1:5432:5432"]}) == [("127.0.0.1", "5432", "5432")]


def test_the_start_scripts_and_the_runbook_still_use_localhost() -> None:
    """The launchers wait on localhost ports, which 127.0.0.1 publishing keeps working."""
    root = BACKEND.parent
    for script in ("start_dev.sh", "start_dev.ps1"):
        text = (root / script).read_text(encoding="utf-8")
        assert "5432" in text and "6379" in text
        assert "0.0.0.0" not in text
