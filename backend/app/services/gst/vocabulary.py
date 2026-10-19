"""GST Credit's fixed vocabulary: statuses, sections, IMS actions and the words that explain them.

Everything a person reads is decision support, never tax advice. The law links are the official pages;
they were not opened from the build sandbox (see docs/product/GST-CREDIT.md, "What is unverified").
"""

from __future__ import annotations

from typing import Final

# --- the statuses of one reconciled line ---------------------------------------------------------------
MATCHED: Final = "MATCHED"
MATCHED_WITH_DIFFERENCES: Final = "MATCHED_WITH_DIFFERENCES"
SUGGESTED: Final = "SUGGESTED"
WAITING_FOR_SUPPLIER: Final = "WAITING_FOR_SUPPLIER"
NOT_IN_BOOKS: Final = "NOT_IN_BOOKS"
NOT_ELIGIBLE: Final = "NOT_ELIGIBLE"
REVERSE_CHARGE: Final = "REVERSE_CHARGE"
NOTE: Final = "NOTE"
STATUSES: Final = (MATCHED, MATCHED_WITH_DIFFERENCES, SUGGESTED, WAITING_FOR_SUPPLIER, NOT_IN_BOOKS,
                   NOT_ELIGIBLE, REVERSE_CHARGE, NOTE)

STATUS_EXPLANATIONS: Final = {
    MATCHED: "The supplier reported this invoice and it agrees with your books. The credit can be claimed.",
    MATCHED_WITH_DIFFERENCES: (
        "The supplier reported this invoice but an amount differs from your books. Claim the lower figure "
        "and ask the supplier to amend."
    ),
    SUGGESTED: (
        "This looks like one of your invoices but the number or date is not an exact match. It waits for a "
        "person to confirm it; Servabo never confirms it by itself."
    ),
    WAITING_FOR_SUPPLIER: (
        "In your books but not in any GSTR-2B you imported. The credit is deferred until the supplier "
        "reports it, and it is at risk as the time limit in Section 16(4) nears."
    ),
    NOT_IN_BOOKS: (
        "The supplier reported this to you but Servabo has not seen the invoice. Upload it, or act on it in "
        "the Invoice Management System (IMS)."
    ),
    NOT_ELIGIBLE: "GSTR-2B marks the credit on this record as not available.",
    REVERSE_CHARGE: "Reverse charge: you pay this tax yourself. It is not credit to claim from the supplier.",
    NOTE: "A credit or debit note. A credit note lowers the credit you can claim; a debit note adds to it.",
}

# --- decisions a person takes -------------------------------------------------------------------------
DECISION_CONFIRM: Final = "CONFIRM"
DECISION_NOT_OURS: Final = "NOT_OURS"
DECISION_LINK: Final = "LINK"
DECISIONS: Final = (DECISION_CONFIRM, DECISION_NOT_OURS, DECISION_LINK)

# --- how a pair was matched ---------------------------------------------------------------------------
METHOD_IRN: Final = "IRN"
METHOD_NUMBER: Final = "NUMBER"
METHOD_SUGGESTED: Final = "SUGGESTED"
METHOD_PERSON: Final = "PERSON"
METHODS: Final = (METHOD_IRN, METHOD_NUMBER, METHOD_SUGGESTED, METHOD_PERSON)

# --- IMS (the portal's Invoice Management System) ------------------------------------------------------
IMS_ACCEPT: Final = "ACCEPT"
IMS_PENDING: Final = "PENDING"
IMS_REJECT: Final = "REJECT"
IMS_ACTIONS: Final = (IMS_ACCEPT, IMS_PENDING, IMS_REJECT)

# --- GSTR-2B sections ---------------------------------------------------------------------------------
SECTION_B2B: Final = "b2b"
SECTION_B2BA: Final = "b2ba"
SECTION_CDNR: Final = "cdnr"
SECTION_CDNRA: Final = "cdnra"
SECTION_ISD: Final = "isd"
SECTION_ISDA: Final = "isda"
SECTION_IMPG: Final = "impg"
SECTION_IMPGSEZ: Final = "impgsez"
SECTION_ECOM: Final = "ecom"
SECTION_ECOMA: Final = "ecoma"
SECTIONS: Final = (SECTION_B2B, SECTION_B2BA, SECTION_CDNR, SECTION_CDNRA, SECTION_ISD, SECTION_ISDA, SECTION_IMPG,
                   SECTION_IMPGSEZ, SECTION_ECOM, SECTION_ECOMA)
#: Sections whose records are supplier documents that can be matched to the books.
MATCHABLE_SECTIONS: Final = (SECTION_B2B, SECTION_B2BA, SECTION_CDNR, SECTION_CDNRA, SECTION_ECOM, SECTION_ECOMA)
AMENDMENT_SECTIONS: Final = (SECTION_B2BA, SECTION_CDNRA, SECTION_ECOMA, SECTION_ISDA)
NOTE_SECTIONS: Final = (SECTION_CDNR, SECTION_CDNRA)

KIND_INVOICE: Final = "INVOICE"
KIND_CREDIT_NOTE: Final = "CREDIT_NOTE"
KIND_DEBIT_NOTE: Final = "DEBIT_NOTE"
KIND_OTHER: Final = "OTHER"
KINDS: Final = (KIND_INVOICE, KIND_CREDIT_NOTE, KIND_DEBIT_NOTE, KIND_OTHER)

RETURN_ACTIVE: Final = "ACTIVE"
RETURN_SUPERSEDED: Final = "SUPERSEDED"
RETURN_STATUSES: Final = (RETURN_ACTIVE, RETURN_SUPERSEDED)

# --- limits (input files are untrusted) ---------------------------------------------------------------
MAX_FILE_BYTES: Final = 25 * 1024 * 1024
MAX_RECORDS: Final = 50_000
MAX_JSON_DEPTH: Final = 12
MAX_ZIP_JSON_MEMBERS: Final = 24
MAX_RAW_BYTES: Final = 4_000

#: Default tolerance per amount head: one rupee (rounding), in micros.
DEFAULT_TOLERANCE_MICROS: Final = 1_000_000
MAX_TOLERANCE_MICROS: Final = 1_000 * 1_000_000

#: The 180-day rule shows an invoice as "near" once it is this many days old and unpaid.
RISK_NEAR_DAYS: Final = 150
RISK_LIMIT_DAYS: Final = 180

# --- the law (sections and official pages) --------------------------------------------------------------
LAW_ITC_2B: Final = {
    "section": "Section 16(2)(aa), CGST Act, 2017",
    "url": "https://cbic-gst.gov.in/pdf/CGST-Act-2017-amended-01012022.pdf",
    "says": "Credit is allowed only on invoices the supplier has reported, which appear in your GSTR-2B.",
}
LAW_180_DAYS: Final = {
    "section": "Second proviso to Section 16(2) and Rule 37, CGST Act and Rules; interest under Section 50",
    "url": "https://cbic-gst.gov.in/input-tax-credit-rules.html",
    "says": ("If the supplier is not paid within 180 days of the invoice date, the credit taken has to be added "
             "back to your output tax with interest. It can be claimed again once paid."),
}
LAW_TIME_LIMIT: Final = {
    "section": "Section 16(4), CGST Act, 2017",
    "url": "https://cbic-gst.gov.in/pdf/CGST-Act-2017-amended-01012022.pdf",
    "says": ("Credit for an invoice of one financial year cannot be claimed after 30 November following that "
             "year, or the filing of the annual return if earlier. Some cases have special rules."),
}
LAW_IMS: Final = {
    "section": "Invoice Management System (GST portal)",
    "url": "https://tutorial.gst.gov.in",
    "says": ("On the portal you can Accept, Reject or keep Pending each supplier record before you file GSTR-3B; "
             "a record you do nothing about is treated as accepted. Servabo only recommends: you act on the portal."),
}
LAW_GSTR2B: Final = {
    "section": "GSTR-2B (GST portal)",
    "url": "https://tutorial.gst.gov.in",
    "says": ("GSTR-2B is a monthly statement generated after the month ends (the 14th for monthly filers). "
             "Returns Dashboard, GSTR-2B, Download, JSON."),
}
NOT_ADVICE: Final = "A recommendation, not tax advice. Check with your chartered accountant."

#: Reason codes (`rsn`) GSTN documents; any other code is shown as given.
REASON_WORDS: Final[dict[str, str]] = {}

#: The law links Helm's GST mandates show (same shape as Helm's MSME links).
HELM_LAW_LINKS: Final = (
    {"title": "Section 16(2), second proviso, CGST Act, 2017, and Rule 37, CGST Rules, 2017 (CBIC)",
     "url": "https://cbic-gst.gov.in/input-tax-credit-rules.html"},
    {"title": "Section 16(2)(aa) and Section 16(4), CGST Act, 2017 (CBIC)",
     "url": "https://cbic-gst.gov.in/pdf/CGST-Act-2017-amended-01012022.pdf"},
)
HELM_NOT_ADVICE: Final = ("Helm gives recommendations, not legal or tax advice. Check the 180-day rule and your "
                          "input tax credit with your chartered accountant.")
