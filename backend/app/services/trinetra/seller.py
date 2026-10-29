"""Is this invoice's seller the receiving entity? Compare every identity the invoice offers (Final 2T, Phase 1.3).

An Indian B2B invoice prints the seller's GSTIN, and characters 3 to 12 of a valid GSTIN are the seller's PAN. So the
entity's PAN is compared with each of: a printed PAN (normalized: upper case, no spaces or hyphens) and the PAN derived
from each valid seller GSTIN. Any disagreement refuses the case and names the field, never the value. With no PAN and no
valid GSTIN the seller can only be matched by name, which a reviewer must confirm explicitly. Comparison is over
validated ASCII, so odd input is a refusal (422), never an error (500)."""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass, field
from typing import Mapping, Optional

from app.services.helm import identity as ident

PAN_PATTERN = re.compile(r"[A-Z]{5}[0-9]{4}[A-Z]")
PAN_KEYS = ("vendor_pan", "seller_pan")

MATCH = "MATCH"
MISMATCH = "MISMATCH"
NAME_ONLY = "NAME_ONLY"


def normalize_pan(raw) -> Optional[str]:
    """A PAN as printed to the PAN it names, or None. ASCII letters and digits only; case and separators ignored."""
    if not isinstance(raw, str) or len(raw) > 64:
        return None
    compact = re.sub(r"[\s\-_.]", "", raw).upper()
    return compact if compact.isascii() and PAN_PATTERN.fullmatch(compact) else None


def pan_of_gstin(raw) -> Optional[str]:
    """The PAN inside a valid GSTIN (characters 3 to 12), or None when the GSTIN is not valid."""
    from app.services.gst.parse import gstin_ok

    if not isinstance(raw, str) or len(raw) > 64:
        return None
    compact = re.sub(r"[\s\-_.]", "", raw).upper()
    if not compact.isascii() or not gstin_ok(compact):
        return None
    return compact[2:12]


@dataclass
class SellerCheck:
    outcome: str
    agreeing: list[str] = field(default_factory=list)
    disagreeing: list[str] = field(default_factory=list)

    def message(self) -> str:
        if self.outcome == MISMATCH and self.disagreeing:
            return (
                "The invoice's seller does not match the selected receiving entity: "
                + ", ".join(self.disagreeing)
                + " disagree"
                + ("s" if len(self.disagreeing) == 1 else "")
                + " with the entity's PAN. Correct and review the invoice's canonical identity first."
            )
        return (
            "The invoice's seller does not match the selected receiving entity. Correct and review its canonical "
            "identity first."
        )


def _same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode("ascii"), b.encode("ascii"))


def check(entities: Optional[Mapping], entity_pan: str, entity_name: str) -> SellerCheck:
    values = entities if isinstance(entities, Mapping) else {}
    offered: list[tuple[str, str]] = []  # (field, PAN it names)
    for key in PAN_KEYS:
        pan = normalize_pan(values.get(key))
        if pan:
            offered.append((key, pan))
    for key in ident.SELLER_TAX_KEYS:
        pan = pan_of_gstin(values.get(key))
        if pan:
            offered.append((key, pan))
    if offered:
        agreeing = [k for k, pan in offered if _same(pan, entity_pan)]
        disagreeing = [k for k, pan in offered if not _same(pan, entity_pan)]
        return SellerCheck(MISMATCH if disagreeing else MATCH, agreeing, disagreeing)
    if ident.we_are_seller(values, ident.Identities.of([{"name": entity_name}])):
        return SellerCheck(NAME_ONLY, ["seller name"])
    return SellerCheck(MISMATCH, [], ["seller name"])
