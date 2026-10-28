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


_SECONDARY = (
    "The official TRACES / e-filing pages could not be reached from the build environment (their hosts are outside the "
    "session's allowed network). The layout was written from secondary sources found by web search on 2026-10-28 "
    "(a KDK Software support article on the Form 26AS text download and import, taxheal.com's text-to-Excel guide, "
    "tdsman.com's 2014 conversion guide) and is checked only against synthetic fixtures of the same shape. Final session "
    "2B must compare it with the owner's own downloaded file. See docs/trinetra/LEGAL-SOURCES.md."
)

REGISTRY: dict[str, Reader] = {
    "human-transcription-v1": Reader(
        "human-transcription-v1", "Rows typed by hand", False, "human-transcription-v1",
        "Typed by a person from a statement they hold; not an official format.", None),
    "servabo-template-v1": Reader(
        "servabo-template-v1", "Servabo template (your transcription)", False, "servabo-template-v1",
        "Servabo's own CSV / Excel template, filled in by the customer; not an official format.", None),
    "form26as-text-v1": Reader(
        "form26as-text-v1", "Form 26AS text download (financial year / assessment year)", True, "form26as-text-v1",
        _SECONDARY, "2026-10-28"),
    "form168-text-v1": Reader(
        "form168-text-v1", "Form 168 text download (Tax Year, Income-tax Act 2025)", True, "form26as-text-v1",
        _SECONDARY + " Form 168's text layout was assumed to follow Form 26AS's; the reader refuses any difference.",
        "2026-10-28"),
    "ais-csv-v1": Reader(
        "ais-csv-v1", "AIS TDS/TCS information CSV (TDS rows only)", True, "ais-csv-v1",
        "AIS user guide and FAQ (incometax.gov.in) could not be reached; only the on-screen field names (information code, "
        "description, value, source) were confirmed by web search on 2026-10-28. Columns are found by heading and "
        "confirmed by the reviewer in a mapping preview.", "2026-10-28"),
}


def get(key: str) -> Optional[Reader]:
    return REGISTRY.get(key)


def unverified() -> list[Reader]:
    """Official readers not yet proven on a real file."""
    return [r for r in REGISTRY.values() if r.official and r.verified_on is None]
