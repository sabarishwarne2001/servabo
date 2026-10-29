"""Bounded evidence dossiers using the platform spreadsheet escaping and audit trail."""

import csv
import html
import io
import json
from datetime import datetime, timezone
from decimal import Decimal
from openpyxl import Workbook
from app.models.trinetra import TrinetraDecision, TrinetraProfile, TrinetraStatement
from app.services.gst.export import safe, _sheet
from app.services.trinetra.service import summary

DISCLAIMER = "Evidence comparison only. Not tax advice, eligibility, a refund or cash recovery. Human transcription is not verified official-format parsing."
HEADER = [
    "Reference",
    "Customer",
    "Period",
    "Entity (masked)",
    "Expected INR",
    "Allocated INR",
    "Possible gap INR",
    "Status",
    "Revision",
    "Rule",
    "Invoice source",
    "Statement snapshot",
    "As of",
]


def build(db, workspace, format):
    figures = summary(db, workspace)
    profiles = {
        str(p.id): p.pan_masked
        for p in db.query(TrinetraProfile).filter_by(workspace_id=workspace.id)
    }
    rows = []
    for r in figures["items"]:
        values = [
            None if r[k] is None else str(Decimal(r[k]) / Decimal(1000000))
            for k in ("expected_micros", "posted_micros", "gap_micros")
        ]
        rows.append(
            [
                r["reference"],
                r["counterparty"],
                r["period"],
                profiles[r["profile_id"]],
                *values,
                r["status"],
                r["revision"],
                r["rule_version"],
                r["work_item_id"],
                r["snapshot_id"],
                r["as_of"],
            ]
        )
    if format == "csv":
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(HEADER)
        writer.writerows([[safe(c) for c in row] for row in rows])
        writer.writerow([DISCLAIMER])
        return output.getvalue().encode(), "text/csv"
    # Explicitly refuse truncating review histories in a dossier.
    events = (
        db.query(TrinetraDecision)
        .filter_by(workspace_id=workspace.id)
        .order_by(TrinetraDecision.created_at, TrinetraDecision.id)
        .limit(50001)
        .all()
    )
    if len(events) > 50000:
        from fastapi import HTTPException

        raise HTTPException(
            409,
            "The evidence history exceeds the dossier limit. Use the platform compliance export.",
        )
    history = [
        [
            str(e.credit_id),
            e.revision,
            e.action,
            e.reason,
            str(e.actor_id) if e.actor_id else "",
            e.created_at.isoformat(),
            json.dumps(e.allocations, sort_keys=True),
            e.review_minutes,
        ]
        for e in events
    ]
    history_header = [
        "Case",
        "Revision",
        "Action",
        "Reason",
        "Reviewer",
        "At",
        "Allocations (micros, exact)",
        "Recorded review minutes",
    ]
    snapshots = [
        [
            str(s.id),
            s.year,
            s.revision,
            s.active,
            s.parser_version,
            s.fingerprint,
            str(s.source_work_item_id) if s.source_work_item_id else "(uploaded file)",
            s.source_version,
            json.dumps(s.comparison, sort_keys=True),
        ]
        for s in db.query(TrinetraStatement)
        .filter_by(workspace_id=workspace.id)
        .order_by(TrinetraStatement.created_at)
    ]
    snapshot_header = [
        "Snapshot",
        "Year starting",
        "Revision",
        "Active selection",
        "Parser",
        "Fingerprint",
        "Source document",
        "Source version",
        "Previous import comparison (micros, exact)",
    ]
    if format == "xlsx":
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = "Evidence basis"
        sheet.append(
            ["TRINETRA evidence dossier", datetime.now(timezone.utc).isoformat()]
        )
        sheet.append([DISCLAIMER])
        sheet.append(
            [
                "Confirmed closure INR",
                str(
                    Decimal(figures["outcomes"]["confirmed_gap_closure_micros"])
                    / Decimal(1000000)
                ),
            ]
        )
        sheet.append(["Recorded review minutes", figures["outcomes"]["review_minutes"]])
        sheet.append([figures["outcomes"]["note"]])
        sheet.append(
            ["Amounts are exact decimal text in INR. No inferred rates or tax basis."]
        )
        _sheet(workbook, "Cases", HEADER, rows)
        _sheet(workbook, "Review history", history_header, history)
        _sheet(workbook, "Snapshots", snapshot_header, snapshots)
        output = io.BytesIO()
        workbook.save(output)
        return (
            output.getvalue(),
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    def table(headers, records):
        def cell(value):
            return html.escape("" if value is None else str(value))

        return (
            "<table><thead><tr>"
            + "".join('<th scope="col">' + cell(h) + "</th>" for h in headers)
            + "</tr></thead><tbody>"
            + "".join(
                "<tr>" + "".join("<td>" + cell(c) + "</td>" for c in row) + "</tr>"
                for row in records
            )
            + "</tbody></table>"
        )

    report = (
        '<!doctype html><html lang="en"><meta charset="utf-8"><title>TRINETRA evidence dossier</title><body><h1>TRINETRA evidence dossier</h1><p>'
        + DISCLAIMER
        + "</p><p>Generated "
        + datetime.now(timezone.utc).isoformat()
        + "</p><h2>Cases</h2>"
        + table(HEADER, rows)
        + "<h2>Snapshot provenance</h2>"
        + table(snapshot_header, snapshots)
        + "<h2>Review history</h2>"
        + table(history_header, history)
        + "</body></html>"
    )
    return report.encode(), "text/html"
