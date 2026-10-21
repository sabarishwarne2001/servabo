"""Session J — every trigger in the catalog has an emitter in `app/`.

A trigger nothing emits is a rule that silently never runs: the defect ARCH-37 set out to remove. The archived
`verify_arch37.py` once checked this; no active test did. This one reads the code (no database): it finds every call
to `emit_trigger`, `emit_internal`, `emit_public_with_twin` and `emit` under `app/` and works out which event types
the call can send.

How an emitter is recognised
----------------------------
1. DIRECT: the `event_type` argument is a string, or a module constant whose value is the event.
2. TWIN: `emit_public_with_twin(event_type="document.completed")` also sends `trigger.document.completed`.
3. INDIRECT: the call passes a variable (`event_type=event`), and the same module reads the event's name, or a
   constant or table holding it (for example `v.TRIGGER_EVENT_OF_STATE[state]`). Weaker, so it is only accepted in a
   module that has a call whose event is a variable.

It guards every trigger added later: a new catalog entry whose event nobody emits fails here, before it ships.
"""

from __future__ import annotations

import ast
import pathlib
from typing import Iterable

import pytest

from app.services.automation.triggers import CATALOG_EVENT_TYPES, TRIGGER_PREFIX

APP = pathlib.Path(__file__).resolve().parents[2] / "app"
EMIT_FUNCTIONS = frozenset({"emit_trigger", "emit_internal", "emit_public_with_twin", "emit"})
#: Files that LIST events (the catalog, the vocabulary) are not emitters.
LISTING_FILES = frozenset({"automation_events.py", "triggers.py"})


def _name(func: ast.expr) -> str | None:
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


class _Index:
    """Module constants (name -> every string reachable from its value) and the emit calls."""

    def __init__(self) -> None:
        self.reach: dict[str, set[str]] = {}
        self.calls: list[tuple[pathlib.Path, str, ast.expr | None]] = []
        self.file_refs: dict[pathlib.Path, tuple[set[str], set[str]]] = {}
        trees: dict[pathlib.Path, ast.AST] = {}
        for path in sorted(APP.rglob("*.py")):
            try:
                trees[path] = ast.parse(path.read_text())
            except SyntaxError:  # a file that does not parse is not an emitter
                continue
        for path, tree in trees.items():
            # Module-level constants only: a local variable called `event_type` in some other file says nothing.
            for node in tree.body:  # type: ignore[attr-defined]
                target: str | None = None
                value: ast.expr | None = None
                if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    target, value = node.targets[0].id, node.value
                elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                    target, value = node.target.id, node.value
                if target and value is not None:
                    self.reach.setdefault(target, set()).update(self._strings(value))
        for path, tree in trees.items():
            names: set[str] = set()
            literals: set[str] = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    names.add(node.id)
                elif isinstance(node, ast.Attribute):
                    names.add(node.attr)
                elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                    literals.add(node.value)
                if isinstance(node, ast.Call) and _name(node.func) in EMIT_FUNCTIONS:
                    fn = str(_name(node.func))
                    event: ast.expr | None = None
                    for keyword in node.keywords:
                        if keyword.arg == "event_type":
                            event = keyword.value
                    if event is None and fn != "emit" and len(node.args) >= 2:
                        event = node.args[1]
                    self.calls.append((path, fn, event))
            self.file_refs[path] = (names, literals)

    def _strings(self, node: ast.expr) -> set[str]:
        found: set[str] = set()
        for part in ast.walk(node):
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                found.add(part.value)
            elif isinstance(part, ast.Name):
                found |= self.reach.get(part.id, set())
        return found

    def resolve(self, node: ast.expr) -> set[str]:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            return {node.value}
        if isinstance(node, ast.Name):
            return set(self.reach.get(node.id, set()))
        if isinstance(node, ast.Attribute):
            return set(self.reach.get(node.attr, set()))
        return set()


_INDEX: _Index | None = None


def _index() -> _Index:
    global _INDEX
    if _INDEX is None:
        _INDEX = _Index()
    return _INDEX


def emitters_of(event_type: str, *, index: _Index | None = None) -> list[str]:
    """Where an event is sent from, as `path (how)`. Empty when nothing sends it."""
    idx = index or _index()
    public = event_type[len(TRIGGER_PREFIX):] if event_type.startswith(TRIGGER_PREFIX) else None
    found: list[str] = []
    for path, fn, event in idx.calls:
        if path.name in LISTING_FILES or path.name == "outbox_service.py":
            continue
        where = str(path.relative_to(APP.parent))
        if event is not None:
            resolved = idx.resolve(event)
            if event_type in resolved and fn != "emit_public_with_twin":
                found.append(f"{where} (direct)")
            elif fn == "emit_public_with_twin" and public is not None and public in resolved:
                found.append(f"{where} (twin of {public})")
        if event is None or not idx.resolve(event):
            names, literals = idx.file_refs[path]
            reads_it = event_type in literals or any(event_type in idx.reach.get(n, set()) for n in names)
            reads_twin = fn == "emit_public_with_twin" and public is not None and public in literals
            if reads_it or reads_twin:
                found.append(f"{where} (indirect, a variable event)")
    return sorted(set(found))


def missing_emitters(event_types: Iterable[str]) -> list[str]:
    return sorted(event for event in event_types if not emitters_of(event))


@pytest.mark.no_db
@pytest.mark.parametrize("event_type", sorted(CATALOG_EVENT_TYPES))
def test_every_catalog_event_has_an_emitter(event_type: str) -> None:
    where = emitters_of(event_type)
    assert where, (
        f"{event_type} is in the trigger catalog but nothing under app/ emits it, so a rule on it would never run. "
        "Emit it where the thing happens (outbox_service.emit_trigger), once and idempotently."
    )


@pytest.mark.no_db
def test_the_scan_notices_an_event_nothing_emits() -> None:
    # The guard is only useful if it fires: an invented event, and a catalog event with its emitter hidden.
    assert missing_emitters(["trigger.invented.never_emitted"]) == ["trigger.invented.never_emitted"]
    index = _index()
    hidden = _Index.__new__(_Index)
    hidden.reach, hidden.file_refs = index.reach, index.file_refs
    hidden.calls = [call for call in index.calls if "obligations" not in str(call[0])]
    assert missing_emitters(["trigger.obligation.due_soon"], ) == []
    assert emitters_of("trigger.obligation.due_soon", index=hidden) == []
