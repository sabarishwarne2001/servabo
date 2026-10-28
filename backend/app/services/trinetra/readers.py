"""The statement reader registry (Final 2T, Phase 3; N-203).

Every way a statement gets into TRINETRA is listed here with the parser version it records, where its layout was read
from (an official page and the date it was read) and whether it has been **verified** against a real file. An official
reader is "unverified" until Final session 2B proves it on the owner's own downloaded file and records the date in
`verified_on`. An unverified reader works in pilot mode with a visible "unverified reader" label on the snapshot; mode
"on" warns in `scripts/preflight.py` while any is unverified. The template and typed rows are the customer's own
transcription: never labelled an official format."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class Reader:
    key: str
    label: str
    #: True for a reader of a government download; False for the customer's own transcription.
    official: bool
    parser_version: str
    #: Where its layout was read from and when (a documentation page), or why none applies.
    source: str
    source_read_on: Optional[str]
    #: The date Final session 2B proved it on a real file. None until then.
    verified_on: Optional[str] = None

    @property
    def verified(self) -> bool:
        return self.verified_on is not None or not self.official


REGISTRY: dict[str, Reader] = {
    "human-transcription-v1": Reader(
        "human-transcription-v1", "Rows typed by hand", False, "human-transcription-v1",
        "Typed by a person from a statement they hold; not an official format.", None),
}


def get(key: str) -> Optional[Reader]:
    return REGISTRY.get(key)


def unverified() -> list[Reader]:
    """Official readers not yet proven on a real file."""
    return [r for r in REGISTRY.values() if r.official and r.verified_on is None]
