"""Reads a GSTR-2B download (JSON, or a zip holding JSON) into plain records.

The shapes accepted are those GSTN documents for the GSTR-2B JSON: the statement may be wrapped as
`{status, data: {chksum, data: {...}}}`, as `{data: {...}}` or bare. **The format is unverified against a real
portal download**: the field names below follow GSTN's published API description as given to the build, and
the fixtures are invented. Anything unexpected is reported in words in `problems` and never silently dropped.

Limits (the file is untrusted): 25 MB, 50,000 records, JSON nested at most 12 deep, zip limits from
`ingestion.archive` (entries, expansion, compression ratio, safe names) and at most 24 JSON members.
"""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from dataclasses import dataclass, field
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any, Iterable, Mapping, Optional

from app.services.entities.normalize import _GSTIN, gstin_check_char
from app.services.gst import keys
from app.services.gst import vocabulary as v
from app.services.ingestion import archive

MICROS = Decimal(1_000_000)


class ReturnFileError(ValueError):
    """The file cannot be read as a GSTR-2B. `message` is a sentence a person can act on."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass
class ParsedRecord:
    section: str
    kind: str
    supplier_gstin: Optional[str]
    supplier_name: Optional[str]
    supplier_filed_on: Optional[date]
    supplier_period: Optional[str]
    number: Optional[str]
    number_key: Optional[str]
    doc_type: Optional[str]
    doc_date: Optional[date]
    value_micros: Optional[int]
    taxable_micros: Optional[int]
    igst_micros: int
    cgst_micros: int
    sgst_micros: int
    cess_micros: int
    place_of_supply: Optional[str]
    reverse_charge: bool
    itc_available: Optional[str]
    reason: Optional[str]
    diff_percent: Optional[str]
    source_type: Optional[str]
    irn: Optional[str]
    irn_date: Optional[date]
    original_number: Optional[str]
    original_key: Optional[str]
    original_date: Optional[date]
    raw: dict[str, Any]

    @property
    def tax_micros(self) -> int:
        return self.igst_micros + self.cgst_micros + self.sgst_micros + self.cess_micros


@dataclass
class Problem:
    code: str
    message: str
    count: int = 1
    examples: list[str] = field(default_factory=list)


@dataclass
class ParsedReturn:
    gstin: str
    period: str  # YYYY-MM
    rtnprd: str  # MMYYYY as given
    version: Optional[str]
    generated_on: Optional[date]
    itc_summary: dict[str, Any]
    records: list[ParsedRecord]
    problems: list[Problem]
    sha256: str
    file_name: str

    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for record in self.records:
            out[record.section] = out.get(record.section, 0) + 1
        return out


class _Problems:
    def __init__(self) -> None:
        self._by_code: dict[str, Problem] = {}

    def add(self, code: str, message: str, example: Optional[str] = None) -> None:
        problem = self._by_code.get(code)
        if problem is None:
            problem = self._by_code[code] = Problem(code, message, 0)
        problem.count += 1
        if example and len(problem.examples) < 5:
            problem.examples.append(example)

    def list(self) -> list[Problem]:
        return list(self._by_code.values())


# --------------------------------------------------------------------------------------------- scalars


def parse_date(raw: Any) -> Optional[date]:
    """dd-mm-yyyy (GSTN) or yyyy-mm-dd; anything else is None."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    try:
        if len(text) == 10 and text[4] == "-":
            return date(int(text[:4]), int(text[5:7]), int(text[8:10]))
        if len(text) == 10 and text[2] in "-/" and text[5] in "-/":
            return date(int(text[6:10]), int(text[3:5]), int(text[:2]))
    except ValueError:
        return None
    return None


def to_micros(raw: Any) -> Optional[int]:
    if raw is None or raw == "" or isinstance(raw, bool):
        return None
    try:
        value = Decimal(str(raw).replace(",", "").strip())
    except InvalidOperation:
        return None
    if not value.is_finite() or abs(value) > Decimal(10) ** 12:
        return None
    return int((value * MICROS).to_integral_value(rounding=ROUND_HALF_UP))


def _text(raw: Any, limit: int = 300) -> Optional[str]:
    if raw is None:
        return None
    text = str(raw).strip()
    return text[:limit] or None


def gstin_ok(value: Optional[str]) -> bool:
    if not value:
        return False
    upper = value.strip().upper()
    return bool(_GSTIN.match(upper)) and gstin_check_char(upper[:14]) == upper[14]


def _period_from_rtnprd(rtnprd: str) -> Optional[str]:
    if len(rtnprd) == 6 and rtnprd.isdigit() and 1 <= int(rtnprd[:2]) <= 12 and int(rtnprd[2:]) >= 2017:
        return f"{rtnprd[2:]}-{rtnprd[:2]}"
    return None


# --------------------------------------------------------------------------------------------- shape


def _depth_ok(value: Any, limit: int) -> bool:
    stack: list[tuple[Any, int]] = [(value, 1)]
    while stack:
        item, depth = stack.pop()
        if depth > limit:
            return False
        if isinstance(item, Mapping):
            stack.extend((child, depth + 1) for child in item.values() if isinstance(child, (Mapping, list)))
        elif isinstance(item, list):
            stack.extend((child, depth + 1) for child in item if isinstance(child, (Mapping, list)))
    return True


def _unwrap(document: Any) -> Mapping[str, Any]:
    """`{status, data: {chksum, data: {...}}}`, `{data: {...}}` or bare: the object holding gstin/docdata."""
    current = document
    for _ in range(4):
        if not isinstance(current, Mapping):
            break
        if "docdata" in current or "gstin" in current:
            return current
        inner = current.get("data")
        if isinstance(inner, Mapping):
            current = inner
            continue
        break
    raise ReturnFileError("NOT_GSTR2B", "This does not look like a GSTR-2B file: there is no GSTIN or document data in it. "
                          "Download the JSON from Returns Dashboard, GSTR-2B, Download.")


def _items_total(items: Any, head: str) -> int:
    total = 0
    if isinstance(items, list):
        for item in items:
            if isinstance(item, Mapping):
                total += to_micros(item.get(head)) or 0
    return total


def _heads(source: Mapping[str, Any]) -> tuple[Optional[int], int, int, int, int]:
    """(taxable, igst, cgst, sgst, cess) from the document's own totals, else from its items."""
    items = source.get("items")
    out = []
    for head in ("txval", "igst", "cgst", "sgst", "cess"):
        own = to_micros(source.get(head))
        out.append(own if own is not None else (_items_total(items, head) if isinstance(items, list) and items else None))
    taxable = out[0]
    return taxable, out[1] or 0, out[2] or 0, out[3] or 0, out[4] or 0


def _bounded_raw(source: Mapping[str, Any]) -> dict[str, Any]:
    raw = {key: value for key, value in source.items() if key != "items"}
    if isinstance(source.get("items"), list):
        raw["items"] = source["items"][:20]
    text = json.dumps(raw, default=str)
    if len(text) > v.MAX_RAW_BYTES:
        return {"truncated": True, "preview": text[: v.MAX_RAW_BYTES]}
    return raw


def _record(section: str, supplier: Mapping[str, Any], doc: Mapping[str, Any], problems: _Problems, *,
            note: bool, amendment: bool) -> Optional[ParsedRecord]:
    number = _text(doc.get("ntnum") if note else doc.get("inum"), 64) or _text(doc.get("docnum"), 64)
    if number is None:
        problems.add("RECORD_WITHOUT_NUMBER", "Some records have no document number and were kept without one.",
                     _text(supplier.get("ctin")))
    supplier_gstin = (_text(supplier.get("ctin"), 15) or "").upper() or None
    if supplier_gstin and not gstin_ok(supplier_gstin):
        problems.add("SUPPLIER_GSTIN_INVALID", "Some supplier GSTINs fail their check character; those records "
                     "cannot be matched by GSTIN.", supplier_gstin)
    doc_date = parse_date(doc.get("dt") or doc.get("docdt"))
    if doc_date is None:
        problems.add("RECORD_DATE_UNREADABLE", "Some records have a date that could not be read.", number)
    taxable, igst, cgst, sgst, cess = _heads(doc)
    note_type = _text(doc.get("typ"), 2) if note else None
    if note:
        kind = v.KIND_DEBIT_NOTE if (note_type or "").upper() == "D" else v.KIND_CREDIT_NOTE
    else:
        kind = v.KIND_INVOICE
    original_number = _text(doc.get("oinum") or doc.get("ontnum") or doc.get("oinvnum"), 64) if amendment else None
    original_date = parse_date(doc.get("oidt") or doc.get("ontdt") or doc.get("oinvdt")) if amendment else None
    itc = _text(doc.get("itcavl"), 1)
    return ParsedRecord(
        section=section, kind=kind, supplier_gstin=supplier_gstin, supplier_name=_text(supplier.get("trdnm")),
        supplier_filed_on=parse_date(supplier.get("supfildt")), supplier_period=_text(supplier.get("supprd"), 12),
        number=number, number_key=keys.number_key(number), doc_type=_text(doc.get("typ"), 8),
        doc_date=doc_date, value_micros=to_micros(doc.get("val")), taxable_micros=taxable,
        igst_micros=igst, cgst_micros=cgst, sgst_micros=sgst, cess_micros=cess,
        place_of_supply=_text(doc.get("pos"), 2), reverse_charge=str(doc.get("rev", "N")).strip().upper() == "Y",
        itc_available=itc.upper() if itc else None, reason=_text(doc.get("rsn"), 16),
        diff_percent=_text(doc.get("diffprcnt"), 8), source_type=_text(doc.get("srctyp"), 16),
        irn=_text(doc.get("irn"), 64), irn_date=parse_date(doc.get("irngendate")),
        original_number=original_number, original_key=keys.number_key(original_number), original_date=original_date,
        raw=_bounded_raw(doc),
    )


def _supplier_documents(supplier: Mapping[str, Any]) -> Iterable[tuple[Mapping[str, Any], bool]]:
    for doc in supplier.get("inv") or ():
        if isinstance(doc, Mapping):
            yield doc, False
    for doc in supplier.get("nt") or ():
        if isinstance(doc, Mapping):
            yield doc, True
    for doc in supplier.get("doclist") or ():  # ISD
        if isinstance(doc, Mapping):
            yield doc, False


def _other_section_records(section: str, entries: Any, problems: _Problems) -> Iterable[ParsedRecord]:
    """Import of goods and SEZ (`impg`, `impgsez`): bills of entry. Kept for the totals, not matched to invoices."""
    if not isinstance(entries, list):
        return
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        if isinstance(entry.get("boe"), list):  # impgsez: a supplier with bills of entry
            for boe in entry["boe"]:
                if isinstance(boe, Mapping):
                    merged = {**boe, "ctin": entry.get("ctin"), "trdnm": entry.get("trdnm")}
                    yield from _other_section_records(section, [merged], problems)
            continue
        taxable, igst, cgst, sgst, cess = _heads(entry)
        number = _text(entry.get("boenum"), 64)
        yield ParsedRecord(
            section=section, kind=v.KIND_OTHER, supplier_gstin=(_text(entry.get("ctin"), 15) or "").upper() or None,
            supplier_name=_text(entry.get("trdnm")), supplier_filed_on=None, supplier_period=None,
            number=number, number_key=keys.number_key(number), doc_type=None, doc_date=parse_date(entry.get("boedt")),
            value_micros=None, taxable_micros=taxable, igst_micros=igst, cgst_micros=cgst, sgst_micros=sgst,
            cess_micros=cess, place_of_supply=None, reverse_charge=False, itc_available="Y", reason=None,
            diff_percent=None, source_type=None, irn=None, irn_date=None, original_number=None, original_key=None,
            original_date=None, raw=_bounded_raw(entry),
        )


def parse_document(document: Any, *, sha256: str, file_name: str) -> ParsedReturn:
    if not _depth_ok(document, v.MAX_JSON_DEPTH):
        raise ReturnFileError("TOO_DEEP", f"The file is nested more than {v.MAX_JSON_DEPTH} levels deep; it is not "
                              "a GSTR-2B download.")
    root = _unwrap(document)
    problems = _Problems()
    gstin = (_text(root.get("gstin"), 15) or "").upper()
    if not gstin_ok(gstin):
        raise ReturnFileError("GSTIN_INVALID", "The GSTIN in this file is missing or fails its check character, so "
                              "Servabo cannot tell whose statement it is.")
    rtnprd = _text(root.get("rtnprd"), 6) or ""
    period = _period_from_rtnprd(rtnprd)
    if period is None:
        raise ReturnFileError("PERIOD_INVALID", "The return period (rtnprd) in this file is missing or not in the "
                              "form MMYYYY.")
    docdata = root.get("docdata")
    if not isinstance(docdata, Mapping):
        raise ReturnFileError("NO_DOCDATA", "This GSTR-2B has no document data (docdata).")
    records: list[ParsedRecord] = []
    for section, body in docdata.items():
        name = str(section).lower()
        if name not in v.SECTIONS:
            problems.add("SECTION_UNKNOWN", f"Sections this version does not read were skipped: {section}.", name)
            continue
        if not isinstance(body, list):
            problems.add("SECTION_SHAPE", f"Section {name} is not a list and was skipped.", name)
            continue
        if name in (v.SECTION_IMPG, v.SECTION_IMPGSEZ):
            records.extend(_other_section_records(name, body, problems))
        else:
            for supplier in body:
                if not isinstance(supplier, Mapping):
                    continue
                for doc, is_note in _supplier_documents(supplier):
                    record = _record(name, supplier, doc, problems,
                                     note=is_note or name in v.NOTE_SECTIONS,
                                     amendment=name in v.AMENDMENT_SECTIONS)
                    if record is not None:
                        records.append(record)
        if len(records) > v.MAX_RECORDS:
            raise ReturnFileError("TOO_MANY_RECORDS", f"This file has more than {v.MAX_RECORDS:,} records; the "
                                  "limit is a protection. Split it or ask support.")
    summary = root.get("itcsumm")
    return ParsedReturn(
        gstin=gstin, period=period, rtnprd=rtnprd, version=_text(root.get("version"), 16),
        generated_on=parse_date(root.get("gendt")),
        itc_summary=summary if isinstance(summary, Mapping) and len(json.dumps(summary, default=str)) < 64_000 else {},
        records=records, problems=problems.list(), sha256=sha256, file_name=file_name[:255],
    )


# --------------------------------------------------------------------------------------------- files


def _load_json(data: bytes, name: str) -> Any:
    try:
        return json.loads(data.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError):
        raise ReturnFileError("NOT_JSON", f"{name} is not a readable JSON file.") from None


def _zip_members(data: bytes) -> list[tuple[str, bytes]]:
    try:
        infos = archive.inspect(data)
    except archive.ArchiveRejected as error:
        raise ReturnFileError(error.code, error.message) from None
    members: list[tuple[str, bytes]] = []
    total = 0
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        for info in infos:
            try:
                name = archive.safe_member_name(info.filename)
            except archive.ArchiveRejected as error:
                raise ReturnFileError(error.code, error.message) from None
            if not name.lower().endswith(".json"):
                continue
            if info.file_size > v.MAX_FILE_BYTES:
                raise ReturnFileError("ARCHIVE_ENTRY_TOO_LARGE", f"{name} is larger than 25 MB.")
            if info.compress_size and info.file_size / info.compress_size > archive.MAX_COMPRESSION_RATIO:
                raise ReturnFileError("ARCHIVE_COMPRESSION_RATIO", f"{name} is compressed suspiciously well and was refused.")
            with zf.open(info) as member:
                payload = member.read(v.MAX_FILE_BYTES + 1)
            if len(payload) > v.MAX_FILE_BYTES:
                raise ReturnFileError("ARCHIVE_ENTRY_TOO_LARGE", f"{name} is larger than 25 MB.")
            total += len(payload)
            if total > 4 * v.MAX_FILE_BYTES:
                raise ReturnFileError("ARCHIVE_TOO_LARGE", "The zip expands to more than 100 MB.")
            members.append((name, payload))
    if not members:
        raise ReturnFileError("ZIP_HAS_NO_JSON", "The zip has no .json file in it. Put the GSTR-2B JSON downloaded "
                              "from the portal in the zip.")
    if len(members) > v.MAX_ZIP_JSON_MEMBERS:
        raise ReturnFileError("ZIP_TOO_MANY", f"The zip holds more than {v.MAX_ZIP_JSON_MEMBERS} JSON files.")
    return members


def parse_file(file_name: str, data: bytes) -> list[ParsedReturn]:
    """A `.json` or `.zip` upload -> the returns in it (one per JSON file)."""
    if len(data) > v.MAX_FILE_BYTES:
        raise ReturnFileError("FILE_TOO_LARGE", "The file is larger than 25 MB.")
    if not data:
        raise ReturnFileError("FILE_EMPTY", "The file is empty.")
    lower = file_name.lower()
    if data[:4] == b"PK\x03\x04" or lower.endswith(".zip"):
        members = _zip_members(data)
    elif lower.endswith(".json") or data.lstrip()[:1] in (b"{", b"["):
        members = [(file_name, data)]
    else:
        raise ReturnFileError("FILE_TYPE", "Upload the GSTR-2B as a .json file, or a .zip holding it.")
    parsed: list[ParsedReturn] = []
    total_records = 0
    for name, payload in members:
        result = parse_document(_load_json(payload, name), sha256=hashlib.sha256(payload).hexdigest(), file_name=name)
        total_records += len(result.records)
        if total_records > v.MAX_RECORDS:
            raise ReturnFileError("TOO_MANY_RECORDS", f"More than {v.MAX_RECORDS:,} records in one upload.")
        parsed.append(result)
    return parsed


__all__ = ["ParsedRecord", "ParsedReturn", "Problem", "ReturnFileError", "gstin_ok", "parse_date", "parse_document",
           "parse_file", "to_micros"]
