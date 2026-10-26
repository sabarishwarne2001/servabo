"""Read-only receivable explanation. Withholding is never bank cash or a settlement."""


def reviewed_withholding(row, value):
    review = row.review or {}
    required = [
        e
        for e in value.get("review", {}).get("evidence", [])
        if e["kind"] in ("DEDUCTOR_ADVICE", "ACCOUNTING_RECORD")
    ]
    amount = value.get("advice_micros")
    if (
        review.get("withholding_confirmed")
        and review.get("invoice_version") == row.source_version
        and value.get("source_current")
        and row.state not in ("WITHDRAWN", "DISPUTED")
        and required
        and all(e.get("current") for e in required)
        and amount is not None
        and 0 < amount <= row.expected_micros
        and amount == value.get("booked_micros")
    ):
        return amount
    return None


def receivable(gross: int | None, bank: int | None, withholding: int | None) -> dict:
    result = {
        "gross_micros": gross,
        "cash_received_micros": bank,
        "reviewed_withholding_micros": withholding,
        "unexplained_micros": None,
        "overexplained_micros": None,
        "status": "UNKNOWN",
        "note": "Documentary projection only. It does not mark an invoice paid or establish tax eligibility.",
    }
    if any(value is None for value in (gross, bank, withholding)):
        return result
    if any(type(value) is not int or value < 0 for value in (gross, bank, withholding)):
        raise ValueError("Signed adjustments require a separately reviewed source.")
    difference = gross - bank - withholding
    result.update(
        unexplained_micros=max(0, difference),
        overexplained_micros=max(0, -difference),
        status=(
            "CONFLICT"
            if difference < 0
            else "EXPLAINED" if difference == 0 else "OPEN_DIFFERENCE"
        ),
    )
    return result
