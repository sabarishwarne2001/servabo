"""The data map: one decision per table about a customer's data (Final session 1, 1A).

WHY THIS FILE EXISTS
--------------------
Servabo keeps three kinds of data a customer cares about: the *content of their documents*, *people's own data*
(names, emails, credentials, comments) and *money records* (GST books, payment ledger, invoices). Before this file,
four separate pieces of code decided what happens to each table's rows:

  * erasing a person (`erasure_service.erase_subject`),
  * the retention sweep (`scripts/sweep_compliance.py`),
  * deleting a workspace or an organization (`compliance/purge_service.py`),
  * the organization's data export (`export_service.build_bundle`),

and each kept its own hand-written list. Every session that added tables (GST, Helm, automation) added them to none of
the four. `tests/services/test_data_map.py` compares THIS registry with the database's real tables, so a table added
without a decision fails the build.

HOW TO READ AN ENTRY
--------------------
`kind`       what the rows are (see `Kind`).
`erasure`    what erasing a person's documents does to rows linked to those documents. The document row itself is KEPT
             (blanked), so foreign keys never cascade: every copy of the content needs a rule of its own.
`sweep`      what the retention sweep does when it DELETES the document row (so foreign keys DO act).
`org_purge`  what the archived-organization purge does (see `purge_service`).
`export`     the section of the tenant export that carries the table, or None with `export_note` saying why not.
`links`      how the rows name a document (so the rules above can find them).
`scrub`      for SCRUB and DETACH: the columns blanked, and with what.

THE DECISIONS (also N-161 to N-165 in NEEDS-OWNER.md)
-----------------------------------------------------
* Copies of a document's content go with the document: traces, notices, event payloads, proposals, findings.
* Money records the law makes the customer keep stay. Indian GST law: Section 36 of the CGST Act, 2017 requires
  books of account to be kept until 72 months after the due date of the annual return for their year (read on
  2026-10-22 in practitioner copies of the text, taxguru.in and knowyourgst.com; indiacode.nic.in, the official
  copy, could not be reached from the build environment). The DPDP Act 2023 does not override a retention duty set by
  another law: Section 8(7) (erase unless retention is required by law) and Section 12(3) (an individual's erasure
  request is subject to the same exception); both come into force in the eighteen-month tranche, about May 2027
  (secondary sources, 2026-10-22). A lawyer should confirm both before a customer relies on them (N-163).
* A kept money record loses every person's name and every free-text field that came from the erased content; it keeps
  amounts, dates, statuses and the identifiers the books need (document number, GSTIN).
* A GSTIN embeds the holder's PAN. For a sole proprietor that is personal data, but it is also the identifier the books
  must carry. Decision: GST rows KEEP the supplier GSTIN, because the legal duty to keep the books outranks the
  erasure of an identifier the law itself requires; the supplier's NAME (free text) is scrubbed.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

__all__ = [
    "Erasure",
    "Kind",
    "Link",
    "OrgPurge",
    "REGISTRY",
    "Sweep",
    "TableRule",
    "col",
    "json_array",
    "json_key",
    "via",
]


class Kind(str, enum.Enum):
    CONTENT = "CONTENT"    # a copy or summary of a document's content
    PERSON = "PERSON"      # a person's own data: name, email, credentials, comments, sessions
    MONEY = "MONEY"        # a money record the organization (or Servabo) must keep
    CONFIG = "CONFIG"      # the customer's settings, rules and endpoints
    AUDIT = "AUDIT"        # append-only trail; kept by design
    DERIVED = "DERIVED"    # rebuildable from other tables
    PLATFORM = "PLATFORM"  # Servabo's own operation; holds no customer content


class Erasure(str, enum.Enum):
    SERVICE = "SERVICE"  # an existing service handles it (named in the note)
    DELETE = "DELETE"    # the rows linked to the erased documents are deleted
    SCRUB = "SCRUB"      # the rows stay; the columns in `scrub` are blanked
    KEEP = "KEEP"        # not document content or person data; the rows stay as they are
    NONE = "NONE"        # the table has no link to a document or a person


class Sweep(str, enum.Enum):
    CASCADE = "CASCADE"  # the foreign key deletes the rows with the document
    DELETE = "DELETE"    # no foreign key: the sweep deletes the linked rows itself
    DETACH = "DETACH"    # the row stays: its document link is cleared and `scrub` columns blanked
    SCRUB = "SCRUB"      # the row stays linked (its parent is detached); `scrub` columns blanked
    SERVICE = "SERVICE"  # an existing service handles it
    KEEP = "KEEP"
    NONE = "NONE"


class OrgPurge(str, enum.Enum):
    DELETE = "DELETE"    # deleted when an archived organization's content is purged (needs an organization or workspace column)
    CASCADE = "CASCADE"  # removed with its parent row
    KEEP = "KEEP"        # kept until the final deletion (72 months after archiving): money record or audit trail
    NONE = "NONE"        # not the customer's data


@dataclass(frozen=True)
class Link:
    """How a row names a document."""

    kind: str                      # "col" | "json_key" | "json_array" | "via"
    column: str
    key: Optional[str] = None      # json_key: the key inside the JSON column
    parent: Optional[str] = None   # via: the table holding the document link
    parent_pk: Optional[str] = None
    parent_link: Optional["Link"] = None


def col(column: str) -> Link:
    """The column holds a work item id."""
    return Link("col", column)


def json_key(column: str, key: str) -> Link:
    """The JSON column carries the work item id under `key`."""
    return Link("json_key", column, key=key)


def json_array(column: str) -> Link:
    """The JSON column is a list of work item ids."""
    return Link("json_array", column)


def via(column: str, parent: str, parent_pk: str, parent_link: Link) -> Link:
    """The row points at a parent row (by `column`); the parent names the document."""
    return Link("via", column, parent=parent, parent_pk=parent_pk, parent_link=parent_link)


@dataclass(frozen=True)
class TableRule:
    kind: Kind
    erasure: Erasure
    sweep: Sweep
    org_purge: OrgPurge
    export: Optional[str] = None
    export_note: str = ""
    links: tuple[Link, ...] = ()
    scrub: Mapping[str, Any] = field(default_factory=dict)
    note: str = ""
    # DETACH only: columns that must still hold a value once the document link is cleared (a check constraint says a
    # row needs at least one side). Rows without them have nothing left to keep and are deleted instead.
    detach_needs: tuple[str, ...] = ()


def _r(kind, erasure, sweep, org_purge, *, export=None, why="", links=(), scrub=None, note="", detach_needs=()) -> TableRule:
    return TableRule(kind, erasure, sweep, org_purge, export, why, tuple(links), dict(scrub or {}), note, tuple(detach_needs))


# Short names for the repeated shapes -------------------------------------------------------------------------------

_NO = "not exported: "
_PLATFORM_WHY = _NO + "Servabo's own operation, not the customer's data"
_DERIVED_WHY = _NO + "rebuilt from exported tables"
_SECRET_WHY = _NO + "a credential or key; the customer re-creates it"
_WI = col("work_item_id")


def _platform(note: str = "") -> TableRule:
    return _r(Kind.PLATFORM, Erasure.NONE, Sweep.NONE, OrgPurge.NONE, why=_PLATFORM_WHY, note=note)


def _derived_cascade(note: str = "", *, links=(), purge: OrgPurge = OrgPurge.CASCADE) -> TableRule:
    """Rows rebuilt from other tables and removed with their parent."""
    return _r(Kind.DERIVED, Erasure.KEEP, Sweep.CASCADE, purge, why=_DERIVED_WHY, links=links, note=note)


def _config(*, export=None, why=_NO + "settings the customer re-enters", purge=OrgPurge.DELETE, note="") -> TableRule:
    return _r(Kind.CONFIG, Erasure.NONE, Sweep.NONE, purge, export=export, why=why if export is None else "", note=note)


def _secret(note: str = "") -> TableRule:
    return _r(Kind.CONFIG, Erasure.NONE, Sweep.NONE, OrgPurge.DELETE, why=_SECRET_WHY, note=note)


def _billing(note: str = "", *, export=None) -> TableRule:
    return _r(Kind.MONEY, Erasure.KEEP, Sweep.NONE, OrgPurge.KEEP, export=export,
              why="" if export else _NO + "Servabo's billing record, summarized by the exported invoices", note=note)


def _person(note: str = "", *, export=None, purge=OrgPurge.DELETE, erasure=Erasure.SERVICE) -> TableRule:
    return _r(Kind.PERSON, erasure, Sweep.NONE, purge, export=export,
              why="" if export else _NO + "credentials or security records", note=note)


# The registry -----------------------------------------------------------------------------------------------------

REGISTRY: dict[str, TableRule] = {
    # ----------------------------------------------------------------- documents and what is read from them
    "work_items": _r(
        Kind.CONTENT, Erasure.SERVICE, Sweep.SERVICE, OrgPurge.DELETE, export="work_items",
        note="Erasure blanks text, summary, entities, metadata and the file name and keeps the row (so counts, "
             "audit and money records still point at something). The sweep deletes the row. Exported as metadata "
             "only: the files themselves are in the original uploads.",
    ),
    "document_chunks": _r(Kind.CONTENT, Erasure.SERVICE, Sweep.CASCADE, OrgPurge.CASCADE, why=_NO + "the text read from a document is derived from the original file",
                          links=(_WI,), note="Erasure: `delete_chunks_for_work_item`."),
    "document_fingerprints": _r(Kind.CONTENT, Erasure.DELETE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY, links=(_WI,),
                                note="A MinHash and an embedding of the text: the content in another form."),
    "document_roles": _r(Kind.CONTENT, Erasure.DELETE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY, links=(_WI,),
                         note="Vendor key, document number and total read from a document."),
    "document_verifications": _r(Kind.CONTENT, Erasure.DELETE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY, links=(_WI,)),
    "document_verification_fields": _r(Kind.CONTENT, Erasure.DELETE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY,
                                       links=(via("verification_id", "document_verifications", "id", _WI),)),
    "work_item_field_corrections": _r(Kind.CONTENT, Erasure.SERVICE, Sweep.CASCADE, OrgPurge.CASCADE, export="field_corrections",
                                      links=(_WI,), note="Erasure deletes a correction's before and after values (N-020)."),
    "work_item_tags": _r(Kind.DERIVED, Erasure.DELETE, Sweep.CASCADE, OrgPurge.CASCADE, why=_NO + "tags are labels the customer re-applies", links=(_WI,)),
    "extraction_exemplars": _r(Kind.CONTENT, Erasure.SERVICE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY, links=(_WI,),
                               note="Erasure deletes the document's exemplars (ARCH41)."),
    "extraction_memory_applications": _r(Kind.CONTENT, Erasure.DELETE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY, links=(_WI,)),
    "extraction_template_members": _r(Kind.DERIVED, Erasure.DELETE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY, links=(_WI,)),
    "extraction_templates": _derived_cascade("Learned templates; carry no document text.", purge=OrgPurge.DELETE),
    "extraction_anchor_rules": _derived_cascade("Learned anchor rules.", purge=OrgPurge.DELETE),
    "extraction_memory_trials": _derived_cascade("Trial statistics.", purge=OrgPurge.DELETE),
    "extraction_memory_settings": _config(),
    "schema_healing_events": _r(Kind.CONTENT, Erasure.DELETE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY, links=(_WI,),
                                note="`original_entities` is the document's extracted content before a repair."),
    "extracted_tables": _r(Kind.CONTENT, Erasure.SERVICE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY, links=(_WI,),
                           note="Erasure: `tables.service.erase_for_work_items` (ARCH44)."),
    "extracted_table_cells": _r(Kind.CONTENT, Erasure.SERVICE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY, note="Cascades from the table row."),
    "table_validations": _r(Kind.CONTENT, Erasure.SERVICE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY, note="Cascades from the table row."),
    "table_column_mappings": _config(),
    "document_schema_presets": _config(),
    "workspace_schema_presets": _config(),
    "document_settings": _config(),
    "packet_splits": _r(Kind.CONTENT, Erasure.DELETE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY, links=(_WI,),
                        note="A split proposal: page scores and a failure reason that can quote the document."),
    "packet_split_segments": _r(Kind.CONTENT, Erasure.DELETE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY,
                                links=(col("child_work_item_id"),), note="Titles read from the pages."),
    "redaction_jobs": _r(Kind.CONTENT, Erasure.DELETE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY, links=(_WI,),
                         note="The job's files are uploads owned by the person; erasure releases them."),
    "redaction_regions": _r(Kind.CONTENT, Erasure.DELETE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY,
                            links=(via("job_id", "redaction_jobs", "id", _WI),)),
    "retention_holds": _r(Kind.CONFIG, Erasure.KEEP, Sweep.CASCADE, OrgPurge.DELETE, why=_NO + "a hold is an instruction, not content",
                          links=(_WI,), note="Erasure and the sweep are REFUSED while a hold is active (F-108)."),
    "retention_policies": _config(export="retention_policy"),
    "uploaded_files": _r(Kind.CONTENT, Erasure.SERVICE, Sweep.SERVICE, OrgPurge.DELETE, why=_NO + "the files themselves are the customer's originals",
                         note="Erasure marks the person's files deleted and queues their storage objects; the sweep does the same."),
    "upload_sessions": _r(Kind.CONTENT, Erasure.NONE, Sweep.NONE, OrgPurge.DELETE, why=_NO + "temporary upload bookkeeping",
                          note="Swept by `ingestion.sweep_sessions`."),
    "ingestion_batches": _config(why=_NO + "batch bookkeeping", purge=OrgPurge.DELETE),
    "ingestion_batch_items": _r(Kind.CONTENT, Erasure.SCRUB, Sweep.DETACH, OrgPurge.CASCADE, why=_NO + "batch bookkeeping", links=(_WI,),
                                scrub={"filename": "erased-document", "error_detail": None, "sha256": None},
                                note="The file name and a hash of the file are the document's content."),
    "processing_batches": _config(why=_NO + "batch bookkeeping"),
    "processing_batch_items": _r(Kind.CONTENT, Erasure.DELETE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY, links=(_WI,)),
    "export_packages": _r(Kind.CONTENT, Erasure.DELETE, Sweep.DELETE, OrgPurge.DELETE, why=_NO + "a package is a copy the customer already downloaded",
                          links=(json_array("work_item_ids"),),
                          note="A generated package of documents with its manifest: the content in another form."),
    "export_schedules": _config(), "export_sync_runs": _derived_cascade("Run history.", purge=OrgPurge.DELETE),
    "warehouse_destinations": _secret("Holds a destination and its credentials."),

    # ----------------------------------------------------------------- what is found in documents
    "entities": _r(Kind.CONTENT, Erasure.SERVICE, Sweep.SERVICE, OrgPurge.DELETE, export="entities",
                   note="Erasure: `entities.erasure` (mentions, edges, identifiers, the subject's own record)."),
    "entity_mentions": _r(Kind.CONTENT, Erasure.SERVICE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY, links=(_WI,)),
    "entity_edges": _r(Kind.CONTENT, Erasure.SERVICE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY, links=(col("evidence_work_item_id"),)),
    "entity_identifiers": _r(Kind.CONTENT, Erasure.SERVICE, Sweep.CASCADE, OrgPurge.CASCADE, why=_NO + "values are kept as HMACs only"),
    "entity_merge_candidates": _r(Kind.CONTENT, Erasure.SERVICE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY, links=(_WI,)),
    "entity_match_models": _derived_cascade("Learned matching weights.", purge=OrgPurge.DELETE),
    "mesh_nodes": _r(Kind.CONTENT, Erasure.SERVICE, Sweep.SERVICE, OrgPurge.CASCADE, why=_DERIVED_WHY, links=(_WI,), note="TruthMesh `forget_documents`."),
    "mesh_links": _r(Kind.CONTENT, Erasure.SERVICE, Sweep.SERVICE, OrgPurge.CASCADE, why=_DERIVED_WHY, links=(col("source_work_item_id"), col("target_work_item_id"))),
    "mesh_conflicts": _r(Kind.CONTENT, Erasure.SERVICE, Sweep.SERVICE, OrgPurge.DELETE, why=_DERIVED_WHY, links=(json_array("work_item_ids"),)),
    "mesh_simulations": _r(Kind.CONTENT, Erasure.SERVICE, Sweep.SERVICE, OrgPurge.CASCADE, why=_DERIVED_WHY, links=(col("origin_work_item_id"),)),
    "mesh_states": _derived_cascade("Per-workspace mesh counters.", purge=OrgPurge.DELETE),
    "corroboration_runs": _r(Kind.CONTENT, Erasure.SERVICE, Sweep.CASCADE, OrgPurge.DELETE, why=_DERIVED_WHY, note="`corroboration.service.erase_for_work_items`."),
    "corroboration_documents": _r(Kind.CONTENT, Erasure.SERVICE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY, links=(_WI,)),
    "corroboration_pairs": _r(Kind.CONTENT, Erasure.SERVICE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY,
                              links=(col("left_work_item_id"), col("right_work_item_id"))),
    "obligations": _r(Kind.CONTENT, Erasure.SERVICE, Sweep.CASCADE, OrgPurge.DELETE, export="obligations", links=(_WI,),
                      note="`obligations.service.erase_for_work_items` (ARCH46)."),
    "obligation_events": _r(Kind.CONTENT, Erasure.SERVICE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY),
    "holiday_calendars": _config(),
    "calendar_feed_tokens": _secret("A secret link to the obligations feed."),
    "anomaly_findings": _r(Kind.CONTENT, Erasure.DELETE, Sweep.CASCADE, OrgPurge.DELETE, why=_DERIVED_WHY,
                           links=(col("subject_work_item_id"), col("counterpart_work_item_id")),
                           note="Evidence is quoted document text."),
    "anomaly_suppressions": _r(Kind.CONFIG, Erasure.DELETE, Sweep.CASCADE, OrgPurge.DELETE, why=_NO + "a suppression is a decision, not content",
                               links=(col("item_a_id"), col("item_b_id")), note="`reason` is free text about two documents."),
    "payment_risk_flags": _r(Kind.CONTENT, Erasure.SERVICE, Sweep.CASCADE, OrgPurge.DELETE, why=_DERIVED_WHY, links=(_WI, col("counterpart_work_item_id")),
                             note="Erasure deletes flags (they quote the vendor and the masked accounts)."),
    "procurement_cases": _r(Kind.CONTENT, Erasure.DELETE, Sweep.CASCADE, OrgPurge.DELETE, why=_DERIVED_WHY,
                            links=(col("po_work_item_id"), col("receipt_work_item_id"), col("invoice_work_item_id"))),
    "procurement_case_lines": _r(Kind.CONTENT, Erasure.DELETE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY,
                                 links=(via("case_id", "procurement_cases", "id", col("invoice_work_item_id")),)),
    "procurement_tolerance_policies": _config(),
    "discrepancies": _r(Kind.CONTENT, Erasure.SERVICE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY, note="Cascades from a corroboration run."),
    "case_documents": _r(Kind.DERIVED, Erasure.DELETE, Sweep.CASCADE, OrgPurge.CASCADE, export="case_documents", links=(_WI,)),
    "case_rule_results": _r(Kind.CONTENT, Erasure.KEEP, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY,
                            note="Left and right values come from the case's documents"),
    "cases": _r(Kind.CONTENT, Erasure.KEEP, Sweep.KEEP, OrgPurge.DELETE, export="cases", note="A case is the customer's own folder; its documents are unlinked."),
    "case_templates": _config(export="case_templates"),
    "document_requests": _r(Kind.CONTENT, Erasure.KEEP, Sweep.KEEP, OrgPurge.DELETE, why=_NO + "a request link, not content",
                            note="`recipient_label` is a name the customer typed; expires by itself."),
    "assertion_definitions": _config(export="assertion_definitions"),
    "assertion_evaluations": _r(Kind.CONTENT, Erasure.DELETE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY, links=(_WI,)),
    "assertion_retrieval_phrases": _derived_cascade("Phrases used to find evidence.", purge=OrgPurge.DELETE),
    "calibration_labels": _derived_cascade("Reviewer verdict labels; carry no text.", purge=OrgPurge.DELETE),
    "calibration_models": _derived_cascade("Fitted calibration curves.", purge=OrgPurge.DELETE),
    "agent_policies": _config(), "agent_tool_calls": _r(Kind.CONTENT, Erasure.KEEP, Sweep.NONE, OrgPurge.DELETE, why=_NO + "internal trace of the assistant's tool use",
                                                         note="Holds arguments the assistant used; deleted with the conversation's workspace."),
    "agent_proposals": _r(Kind.CONTENT, Erasure.DELETE, Sweep.CASCADE, OrgPurge.DELETE, why=_DERIVED_WHY, links=(_WI,),
                          note="Evidence and rationale quote the document."),
    "review_threads": _r(Kind.CONTENT, Erasure.SERVICE, Sweep.CASCADE, OrgPurge.DELETE, why=_NO + "discussion about a document", links=(_WI,)),
    "review_comments": _r(Kind.PERSON, Erasure.SERVICE, Sweep.CASCADE, OrgPurge.CASCADE, why=_NO + "discussion about a document",
                          note="The subject's own comments lose their body (`erase_author`)."),
    "review_assignments": _person("Who reviews what.", purge=OrgPurge.DELETE, erasure=Erasure.KEEP),
    "review_locks": _person("Soft locks; released on erasure.", purge=OrgPurge.DELETE),
    "review_item_versions": _derived_cascade("Version counters.", purge=OrgPurge.DELETE),
    "process_events": _r(Kind.DERIVED, Erasure.KEEP, Sweep.NONE, OrgPurge.DELETE, why=_DERIVED_WHY,
                         note="Event-log attributes hold ids and activity names, not document text (process intelligence)."),
    "process_event_objects": _derived_cascade("Object ids for events.", purge=OrgPurge.DELETE),
    "process_ingest_cursors": _derived_cascade("Cursors.", purge=OrgPurge.DELETE),
    "process_model_runs": _derived_cascade("Mined models.", purge=OrgPurge.DELETE),
    "process_predictions": _derived_cascade("Predictions.", purge=OrgPurge.DELETE),
    "process_sla_policies": _config(),

    # ----------------------------------------------------------------- conversations
    "conversations": _r(Kind.PERSON, Erasure.SERVICE, Sweep.CASCADE, OrgPurge.DELETE, export="conversations", links=(_WI,),
                        note="Erasure deletes the subject's conversations."),
    "conversation_messages": _r(Kind.PERSON, Erasure.SERVICE, Sweep.CASCADE, OrgPurge.CASCADE, export="conversation_messages"),
    "conversation_scope_items": _r(Kind.DERIVED, Erasure.DELETE, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY, links=(_WI,)),
    "prompt_templates": _config(export="prompt_templates"),
    "ai_settings": _config(), "tenant_model_routes": _config(), "tenant_provider_credentials": _secret("BYOK keys, encrypted."),
    "egress_policies": _config(), "egress_allow_rules": _config(), "egress_refusals": _derived_cascade("Refusals log.", purge=OrgPurge.DELETE),
    "dispatch_policies": _config(), "tenant_queue_weights": _config(),

    # ----------------------------------------------------------------- GST Credit
    "gst_returns": _r(Kind.MONEY, Erasure.KEEP, Sweep.KEEP, OrgPurge.KEEP, export="gst_returns",
                      note="The imported GSTR-2B files' summaries: the books (CGST Act s.36, 72 months)."),
    "gst_return_records": _r(Kind.MONEY, Erasure.KEEP, Sweep.KEEP, OrgPurge.KEEP, export="gst_book_records",
                             note="The books themselves, from the portal, not from the erased document. Kept whole, supplier GSTIN included (N-163)."),
    "gst_matches": _r(Kind.MONEY, Erasure.SCRUB, Sweep.DETACH, OrgPurge.KEEP, export="gst_matches", links=(_WI,),
                      scrub={"supplier_name": None, "notes": [], "differences": [], "ims_reason": None}, detach_needs=("record_id",),
                      note="Amounts, dates, status, method and the supplier GSTIN stay; names and the document's own values go (N-162). A match that "
                           "has no book record (the invoice was missing from GSTR-2B) has nothing left once the document goes and is deleted."),
    "gst_decisions": _r(Kind.MONEY, Erasure.SCRUB, Sweep.CASCADE, OrgPurge.KEEP, export="gst_decisions", links=(_WI,),
                        scrub={"note": None},
                        note="Erasure: a person's confirm stays, their free-text note goes. Sweep: a CONFIRM or LINK decision is about "
                             "one document (a check constraint requires it), so it goes with the document; NOT_OURS decisions have none."),
    "gst_settings": _config(export="gst_settings", purge=OrgPurge.KEEP),

    # ----------------------------------------------------------------- Helm
    "helm_books": _r(Kind.MONEY, Erasure.KEEP, Sweep.KEEP, OrgPurge.KEEP, export="helm_books"),
    "helm_counterparties": _r(Kind.MONEY, Erasure.KEEP, Sweep.KEEP, OrgPurge.KEEP, export="helm_counterparties",
                              note="A supplier or customer of the organization; the organization's own address book."),
    "helm_promises": _r(Kind.DERIVED, Erasure.SCRUB, Sweep.CASCADE, OrgPurge.KEEP, export="helm_promises", links=(_WI,),
                        scrub={"title": "Erased document", "counterparty_name": None, "terms": {}, "evidence": {}, "details": {}},
                        note="Rebuilt from documents by the projector, which also drops it when the document goes."),
    "helm_settlements": _r(Kind.MONEY, Erasure.SCRUB, Sweep.DETACH, OrgPurge.KEEP, export="helm_settlements", links=(_WI,),
                           scrub={"hold_reason": None, "paid_reference": None, "evidence": {}},
                           note="Whether an invoice was paid cannot be rebuilt from documents, so it stays when the document goes."),
    "helm_actions": _r(Kind.MONEY, Erasure.SCRUB, Sweep.DETACH, OrgPurge.KEEP, export="helm_actions", links=(_WI,),
                       scrub={"title": "Erased document", "explanation": "", "params": {}, "result": {}, "rejected_reason": ""},
                       note="The record of what Helm proposed, who approved it and the amount."),
    "helm_value_events": _r(Kind.MONEY, Erasure.SCRUB, Sweep.DETACH, OrgPurge.KEEP, export="helm_value_events", links=(_WI,),
                            scrub={"evidence": {}}, note="The receipt's ledger of value found."),
    "helm_tasks": _r(Kind.CONTENT, Erasure.SCRUB, Sweep.CASCADE, OrgPurge.CASCADE, why=_DERIVED_WHY, links=(_WI,),
                     scrub={"title": "Erased document", "body": "", "decision_note": None},
                     note="Helm's to-do notes quote the document."),
    "helm_cash_positions": _r(Kind.MONEY, Erasure.SCRUB, Sweep.CASCADE, OrgPurge.KEEP, export="helm_cash_positions", links=(_WI,),
                              scrub={"note": None}, note="A statement's closing balance goes with the statement on a sweep (the row requires it)."),
    "helm_bank_lines": _r(Kind.MONEY, Erasure.SCRUB, Sweep.DETACH, OrgPurge.KEEP, export="helm_bank_lines", links=(_WI,),
                          scrub={"match": {}, "note": None}, note="Bank statement lines are the customer's own money records."),
    "helm_bank_imports": _r(Kind.MONEY, Erasure.KEEP, Sweep.KEEP, OrgPurge.KEEP, why=_NO + "import bookkeeping for the exported bank lines"),
    "helm_bank_accounts": _r(Kind.MONEY, Erasure.KEEP, Sweep.KEEP, OrgPurge.KEEP, export="helm_bank_accounts", note="Masked account numbers only."),
    "helm_certificates": _r(Kind.AUDIT, Erasure.KEEP, Sweep.KEEP, OrgPurge.KEEP, why=_NO + "a signed record of a Guard check; proof, not content"),
    "helm_plans": _derived_cascade("Computed payment plans.", purge=OrgPurge.KEEP),
    "helm_mandates": _config(export="helm_mandates", purge=OrgPurge.KEEP),
    "helm_mandate_versions": _config(export="helm_mandate_versions", purge=OrgPurge.KEEP),
    "helm_settings": _config(export="helm_settings", purge=OrgPurge.KEEP),
    "helm_backtests": _derived_cascade("Backtest reports.", purge=OrgPurge.DELETE),
    "helm_ledger_dirty": _derived_cascade("Projector queue.", links=(_WI,), purge=OrgPurge.DELETE),
    "helm_ledger_state": _derived_cascade("Projector state.", purge=OrgPurge.DELETE),

    # ----------------------------------------------------------------- automation, notices, events
    "automation_rules": _config(export="automation_rules", why=""),
    "automation_rule_versions": _config(export="automation_rules", why=""),
    "automation_rule_triggers": _config(why=_NO + "index of the exported rule's triggers"),
    "automation_nodes": _config(why=_NO + "the rule's steps are in the exported rule JSON", purge=OrgPurge.CASCADE),
    "automation_edges": _config(why=_NO + "the rule's links are in the exported rule JSON", purge=OrgPurge.CASCADE),
    "automation_event_marks": _derived_cascade("Marks that an event was announced once.", purge=OrgPurge.DELETE),
    "automation_executions": _r(Kind.CONTENT, Erasure.SCRUB, Sweep.DETACH, OrgPurge.DELETE, why=_NO + "run history", links=(_WI,),
                                scrub={"details": {}, "error": None},
                                note="`details` is the trace: the value each condition read. Status and times stay (an audit of what ran)."),
    "automation_node_runs": _r(Kind.CONTENT, Erasure.SCRUB, Sweep.SCRUB, OrgPurge.CASCADE, why=_NO + "run history",
                               links=(via("execution_id", "automation_executions", "id", _WI),),
                               scrub={"details": {}, "error": None}, note="Each step's own trace."),
    "automation_logs": _r(Kind.CONTENT, Erasure.DELETE, Sweep.CASCADE, OrgPurge.DELETE, why=_NO + "run history", links=(_WI,),
                          note="`log_message` quotes the document."),
    "notifications": _r(Kind.CONTENT, Erasure.DELETE, Sweep.CASCADE, OrgPurge.DELETE, why=_NO + "in-app notices", links=(_WI,),
                        note="The body quotes the document (a name, an amount)."),
    "notification_deliveries": _r(Kind.CONTENT, Erasure.DELETE, Sweep.DELETE, OrgPurge.DELETE, why=_NO + "delivery bookkeeping",
                                  links=(via("notification_id", "notifications", "id", _WI),),
                                  note="`payload` is a copy of the notice."),
    "user_notification_preferences": _person("A person's own notice settings.", purge=OrgPurge.NONE, erasure=Erasure.KEEP),
    "outbox_events": _r(Kind.CONTENT, Erasure.DELETE, Sweep.DELETE, OrgPurge.DELETE, why=_NO + "the event queue",
                        links=(col("resource_id"), json_key("payload", "work_item_id")),
                        note="Event payloads carry the supplier name and amounts of the document they announce."),
    "webhook_endpoints": _r(Kind.CONFIG, Erasure.NONE, Sweep.NONE, OrgPurge.DELETE, why=_SECRET_WHY),
    "webhook_deliveries": _r(Kind.CONTENT, Erasure.DELETE, Sweep.DELETE, OrgPurge.DELETE, why=_NO + "delivery history",
                             links=(via("outbox_event_id", "outbox_events", "id", col("resource_id")),
                                    json_key("payload", "work_item_id")),
                             note="`payload` is a copy of the event body sent to the customer's endpoint."),
    "webhook_delivery_attempts": _r(Kind.CONTENT, Erasure.DELETE, Sweep.DELETE, OrgPurge.CASCADE, why=_NO + "delivery history",
                                    links=(via("webhook_delivery_id", "webhook_deliveries", "id", json_key("payload", "work_item_id")),),
                                    note="Holds the response excerpt the endpoint returned."),
    "jobs": _r(Kind.DERIVED, Erasure.KEEP, Sweep.NONE, OrgPurge.NONE, why=_PLATFORM_WHY,
               note="Job payloads carry ids and the stored file key, not document text; finished jobs age out."),
    "monthly_receipt_sends": _r(Kind.MONEY, Erasure.KEEP, Sweep.NONE, OrgPurge.KEEP, why=_NO + "a send record: a period, a count"),
    "gst_notice_sends": _r(Kind.MONEY, Erasure.KEEP, Sweep.NONE, OrgPurge.KEEP, why=_NO + "a send record: a kind, a key, a count"),

    # ----------------------------------------------------------------- ERP
    "erp_targets": _secret("Holds the connection and its credentials."),
    "erp_oauth_states": _config(why=_NO + "a short-lived sign-in state for connecting an accounting system"),
    "erp_mappings": _config(export="erp_mappings"), "erp_lookup_tables": _config(export="erp_lookup_tables"),
    "erp_postings": _r(Kind.MONEY, Erasure.SERVICE, Sweep.CASCADE, OrgPurge.KEEP, why=_NO + "the postings are in the customer's accounting system", links=(_WI,),
                       note="`erp.service.erase_for_work_items`: the ledger row stays (a posting that happened is a fact), its content goes."),
    "erp_posting_attempts": _r(Kind.MONEY, Erasure.SERVICE, Sweep.CASCADE, OrgPurge.CASCADE, why=_NO + "delivery history"),

    # ----------------------------------------------------------------- email-in (Final session 1, 2B)
    "inbound_email_addresses": _secret("The workspace's receiving address token; a rotated token is kept only to refuse mail sent to it."),
    "inbound_email_senders": _config(export="inbound_email_senders", why=""),
    "inbound_messages": _r(Kind.CONTENT, Erasure.DELETE, Sweep.DELETE, OrgPurge.DELETE, export="inbound_messages",
                           links=(json_array("work_item_ids"),),
                           note="Sender address and subject of a message that brought documents in: erased with those documents. "
                                "Held and discarded messages (no document) are swept after 30 days by `inbound_email.sweep`."),
    "work_item_sources": _r(Kind.CONTENT, Erasure.DELETE, Sweep.CASCADE, OrgPurge.CASCADE, export="work_item_sources", links=(_WI,),
                            note="'Arrived by email from ...': the sender and subject belong to the document."),

    # ----------------------------------------------------------------- people, organizations, security
    "users": _r(Kind.PERSON, Erasure.SERVICE, Sweep.NONE, OrgPurge.NONE, export="members",
                note="Anonymized in place on erasure (a user may belong to other organizations, so the row is never purged with one)."),
    "organizations": _r(Kind.CONFIG, Erasure.NONE, Sweep.NONE, OrgPurge.KEEP, export="organization", note="Deleted at the final stage."),
    "organization_members": _person("Membership.", export="members", erasure=Erasure.SERVICE),
    "organization_invitations": _person("Invited emails.", purge=OrgPurge.DELETE, erasure=Erasure.KEEP),
    "invitation_workspace_grants": _person("What an invitation grants.", purge=OrgPurge.CASCADE, erasure=Erasure.KEEP),
    "workspaces": _r(Kind.CONFIG, Erasure.NONE, Sweep.NONE, OrgPurge.KEEP, export="workspaces", note="Archived with the organization; deleted at the final stage."),
    "workspace_members": _person("Workspace membership.", export="members", purge=OrgPurge.DELETE, erasure=Erasure.KEEP),
    "workspace_email_overrides": _config(),
    "organization_email_settings": _secret("Holds the organization's own SMTP credentials."),
    "auth_tokens": _person("Reset and verification tokens; deleted on erasure.", purge=OrgPurge.NONE),
    "sessions": _person("Sign-in sessions; revoked on erasure.", purge=OrgPurge.NONE),
    "user_mfa_factors": _person("Second factors.", purge=OrgPurge.NONE),
    "email_change_requests": _person("Pending email changes.", purge=OrgPurge.NONE),
    "api_keys": _r(Kind.CONFIG, Erasure.NONE, Sweep.NONE, OrgPurge.DELETE, why=_SECRET_WHY),
    "api_key_usage_daily": _derived_cascade("Counters per key.", purge=OrgPurge.DELETE),
    "tenant_security_policies": _config(), "tenant_branding": _config(),
    "custom_domains": _config(), "verified_domains": _config(),
    "enterprise_idp_configs": _secret("SSO configuration."), "idp_role_mappings": _config(why=_NO + "SSO configuration", purge=OrgPurge.CASCADE),
    "idp_signing_certificates": _r(Kind.CONFIG, Erasure.NONE, Sweep.NONE, OrgPurge.CASCADE, why=_SECRET_WHY, note="Public certificates."), "directory_identities": _person("Directory entries for SCIM/SSO.", purge=OrgPurge.DELETE, erasure=Erasure.KEEP),
    "scim_api_keys": _secret(), "scim_groups": _config(), "scim_group_members": _person("Group membership.", purge=OrgPurge.CASCADE, erasure=Erasure.KEEP),
    "sso_assertions": _r(Kind.PERSON, Erasure.KEEP, Sweep.NONE, OrgPurge.DELETE, why=_NO + "sign-in evidence, short-lived"),
    "sso_auth_requests": _platform("Short-lived sign-in state."), "saml_assertion_replay_guard": _platform("Replay guard; short-lived."),
    "erased_subjects": _r(Kind.AUDIT, Erasure.KEEP, Sweep.KEEP, OrgPurge.KEEP, export="erased_subjects", note="The proof that an erasure happened: a hash of the email, never the email."),
    "compliance_exports": _r(Kind.CONTENT, Erasure.KEEP, Sweep.KEEP, OrgPurge.DELETE, why=_NO + "the export bundle itself", note="Expires after 72 hours."),
    "audit_logs": _r(Kind.AUDIT, Erasure.KEEP, Sweep.KEEP, OrgPurge.KEEP, export="audit_logs",
                     note="Append-only by design. Details hold ids, counts and setting names, not document text."),
    "ownership_transfers": _person("Ownership hand-over records.", purge=OrgPurge.KEEP, erasure=Erasure.KEEP),

    # ----------------------------------------------------------------- billing and usage
    "billing_accounts": _billing("The organization's billing customer."),
    "subscriptions": _billing(), "organization_addons": _billing(),
    "invoices": _billing("Servabo's invoices to the customer: kept for the tax period.", export="invoices"),
    "invoice_line_items": _billing(), "billing_disputes": _billing(), "dunning_actions": _billing(), "checkout_selections": _billing(),
    "contract_invoices": _billing(), "enterprise_contracts": _billing(), "revenue_schedules": _billing(), "recognized_revenue_ledger": _billing(),
    "usage_events": _r(Kind.MONEY, Erasure.KEEP, Sweep.NONE, OrgPurge.KEEP, why=_NO + "metering ledger; invoices summarize it",
                       note="Append-only usage ledger: quantities and costs, no document text."),
    "usage_rollups": _derived_cascade("Rolled-up usage.", purge=OrgPurge.KEEP), "usage_limit_alerts": _billing("Alert history."),
    "billable_seats": _billing(), "spend_limits": _config(purge=OrgPurge.KEEP), "partner_rev_share_ledger": _billing("Partner commission ledger."),
    "stripe_inbound_events": _r(Kind.MONEY, Erasure.KEEP, Sweep.NONE, OrgPurge.KEEP, why=_NO + "the payment provider's webhook payloads (billing evidence)"),
    "promo_redemptions": _billing(),

    # ----------------------------------------------------------------- Servabo's own operation
    "operator_alerts": _platform(), "server_error_minutes": _platform(), "dr_drills": _platform(), "dr_heartbeats": _platform(),
    "safety_job_runs": _platform("Final session 2A: what the host's cron jobs last reported; no tenant data."),
    "slo_definitions": _platform(), "slo_measurements": _platform(), "slo_observations": _platform(),
    "price_books": _platform(), "price_book_entries": _platform(), "plan_price_books": _platform(), "plan_price_book_entries": _platform(),
    "quota_tiers": _platform(), "quota_tier_entries": _platform(), "platform_licences": _platform(), "promo_codes": _platform(),
    "partners": _platform(), "partner_members": _platform(), "partner_organizations": _platform(), "partner_payout_periods": _platform(),
    "partner_rev_share_agreements": _platform(), "partner_signing_keys": _platform(),
    "marketplace_items": _platform(), "marketplace_installations": _config(), "marketplace_manifests": _platform(), "marketplace_signatures": _platform(),
    "revenue_snapshots": _platform(), "rollup_windows": _platform(),
    "provider_statements": _platform(), "provider_statement_lines": _platform(), "reconciliation_runs": _platform(), "reconciliation_findings": _platform(),
    "supplier_invoices": _platform("Servabo's own supplier invoices (its costs)."), "supplier_reconciliations": _platform(),
    "settings_migration_archive": _platform("One-off archive of settings from an old migration."),
}

# TRINETRA is evidence content, not a statutory ledger. No GST retention exemption is inferred.
REGISTRY.update({
    "trinetra_profiles": _config(export="trinetra_profiles", note="Encrypted PAN; ciphertext excluded from export."),
    "trinetra_statements": _r(Kind.CONTENT, Erasure.DELETE, Sweep.DELETE, OrgPurge.DELETE,
        export="trinetra_statements", links=(col("source_work_item_id"), json_array("evidence_work_item_ids"))),
    "trinetra_credits": _r(Kind.CONTENT, Erasure.DELETE, Sweep.DELETE, OrgPurge.DELETE,
        export="trinetra_credits", links=(col("work_item_id"), json_array("evidence_work_item_ids"))),
    "trinetra_decisions": _r(Kind.CONTENT, Erasure.DELETE, Sweep.DELETE, OrgPurge.DELETE,
        export="trinetra_decisions", links=(via("credit_id", "trinetra_credits", "id", col("work_item_id")), json_array("evidence_work_item_ids"))),
})
