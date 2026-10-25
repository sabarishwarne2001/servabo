"""Read-only receivable explanation. Withholding is never bank cash or a settlement."""


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
