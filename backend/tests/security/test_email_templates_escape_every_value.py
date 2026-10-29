"""Every email template escapes every value it is given (campaign session 3, security review).

Names that land in emails come from people: an organization's name, an inviter's display name, a
workspace, an address. An organization admin can put `<a href=…>` or `<script>` into any of them.
Each template is rendered here with hostile text in every text argument; the HTML must not carry
the markup through, and subjects must stay on one line (a newline in a subject is a header
injection). New templates are picked up automatically.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import typing
from datetime import datetime, timedelta, timezone

import pytest

import app.templates.emails as emails_pkg

HOSTILE = '<script>alert(1)</script><a href="https://evil.example/x" onclick="steal()">x</a>'
HEADER_BREAK = "Acme\r\nBcc: victim@example.com"


def _renderers():
    found = []
    for module_info in pkgutil.iter_modules(emails_pkg.__path__):
        module = importlib.import_module(f"{emails_pkg.__name__}.{module_info.name}")
        for name, func in inspect.getmembers(module, inspect.isfunction):
            if name.startswith("render_") and func.__module__ == module.__name__:
                found.append(func)
    return found


#: Arguments that are a fixed vocabulary, not text a person typed.
VOCABULARY = {"kind": "ENDING"}


def _row(cls, text: str):
    """A dataclass row (a workspace grant, an expired invitation) with hostile text in each field."""
    import dataclasses

    return cls(**{f.name: text for f in dataclasses.fields(cls)})


def _value_for(name: str, annotation, text: str):
    import dataclasses

    if name in VOCABULARY:
        return VOCABULARY[name]
    origin = typing.get_origin(annotation)
    args = typing.get_args(annotation)
    if origin is typing.Literal:
        return args[0]
    if args and dataclasses.is_dataclass(args[0]):
        return [_row(args[0], text), _row(args[0], "Second")]
    if "Sequence[str]" in str(annotation) or "list[str]" in str(annotation):
        return [text, "Second Organization"]
    args = typing.get_args(annotation)
    if annotation in (str, "str") or (origin is typing.Union and str in args) or "str" in str(annotation):
        if "url" in name or "link" in name or name.endswith("_href"):
            return f"https://app.servabo.app/x?{text}"
        if "email" in name:
            return f"person+{text[:20]}@example.com"
        return text
    if annotation in (int, "int") or "int" in str(annotation):
        return 3
    if "datetime" in str(annotation):
        return datetime.now(timezone.utc) + timedelta(days=2)
    if "bool" in str(annotation):
        return True
    return None


def _call(func, text: str):
    signature = inspect.signature(func)
    hints = typing.get_type_hints(func)
    kwargs = {}
    for name, parameter in signature.parameters.items():
        annotation = hints.get(name, parameter.annotation)
        value = _value_for(name, annotation, text)
        if value is None:
            if parameter.default is not inspect.Parameter.empty:
                continue
            pytest.skip(f"{func.__name__}: cannot build {name} ({annotation})")
        kwargs[name] = value
    return func(**kwargs)


RENDERERS = [f for f in _renderers() if f.__name__ not in {"render_table", "render_grant_table", "render_grant_lines_text"}]


def test_every_email_template_is_found() -> None:
    assert len(RENDERERS) >= 15, [f.__name__ for f in RENDERERS]


@pytest.mark.parametrize("render", RENDERERS, ids=lambda f: f.__name__)
def test_markup_in_any_value_is_escaped(render) -> None:
    rendered = _call(render, HOSTILE)
    subject, html_body = rendered[0], rendered[1]
    assert "<script>" not in html_body
    assert 'onclick="steal()"' not in html_body
    assert '<a href="https://evil.example' not in html_body
    assert "\n" not in subject and "\r" not in subject


@pytest.mark.parametrize("render", RENDERERS, ids=lambda f: f.__name__)
def test_a_line_break_cannot_add_a_mail_header(render) -> None:
    subject = _call(render, HEADER_BREAK)[0]
    assert "\r" not in subject and "\n" not in subject


# ------------------------------------------------------------------------------------------------------------------------
# Final session 2A (Phase 3, invariant (e) of docs/hardening/PROMPT-INJECTION.md): every value taken from a document is
# also TRUNCATED. A supplier name, an invoice number, a GSTR-2B trade name or a statement line can be any length a
# document prints; an outbound email must not carry a page of planted text. These are the templates that carry document
# values (Helm's supplier and customer emails, the GST supplier reminder, the GST digest); new ones are added here.
# ------------------------------------------------------------------------------------------------------------------------

#: Each template that carries values read from documents, and which of its parameters those are. The rest (the
#: organization's own name, the brand, links Servabo builds) are a person's or the platform's.
DOCUMENT_PARAMS = {
    "render_dispute": {"supplier_name", "invoice_number", "lines"},
    "render_reconciliation": {"supplier_name", "differences"},
    "render_reminder": {"customer_name", "invoice_number"},
    "render_document_request": {"supplier_name", "document_title"},
    "render_briefing": {"plan_lines", "risk_lines", "value_line"},
    "render_missing_invoices": {"supplier_name", "lines"},
    "render_gst_digest": {"headline", "findings", "unlock_line"},
    # Final session 2T: a customer's name and an invoice number reach the TDS inquiry and the Monday TDS line.
    "render_inquiry": {"customer_name", "invoice_number", "period_label", "document_label"},
    "render_trinetra_digest": {"headline", "lines"},
}
DOCUMENT_RENDERERS = set(DOCUMENT_PARAMS)
LONG = "Planted " + "Z" * 5000


def _call_with_document_values(func):
    import dataclasses

    signature = inspect.signature(func)
    hints = typing.get_type_hints(func)
    wanted = DOCUMENT_PARAMS[func.__name__]
    kwargs = {}
    for name, parameter in signature.parameters.items():
        annotation = hints.get(name, parameter.annotation)
        value = _value_for(name, annotation, LONG if name in wanted else "Acme")
        if isinstance(value, list) and value and dataclasses.is_dataclass(value[0]) and hasattr(value[0], "url"):
            value = [dataclasses.replace(v, url="https://app.example/gst") for v in value]  # links are Servabo's own
        if value is None:
            if parameter.default is not inspect.Parameter.empty:
                continue
            pytest.skip(f"{func.__name__}: cannot build {name} ({annotation})")
        kwargs[name] = value
    return func(**kwargs)


def test_the_document_carrying_templates_are_known() -> None:
    names = {f.__name__ for f in RENDERERS}
    assert DOCUMENT_RENDERERS <= names, DOCUMENT_RENDERERS - names


@pytest.mark.parametrize("render", [f for f in RENDERERS if f.__name__ in DOCUMENT_RENDERERS], ids=lambda f: f.__name__)
def test_a_value_from_a_document_is_truncated(render) -> None:
    subject, html_body, text_body = _call_with_document_values(render)[:3]
    for part in (subject, html_body, text_body):
        assert "Z" * 1000 not in part, f"{render.__name__} carries a 5,000-character value whole"


def test_the_gst_supplier_reminder_and_the_reconciliation_bound_their_lines() -> None:
    """The two templates above whose document values arrive in a list of dicts the generic builder cannot make."""
    from app.templates.emails.gst import render_missing_invoices
    from app.templates.emails.helm import render_reconciliation

    reminder = render_missing_invoices(organization_name="Acme", supplier_name="Sahyadri", period_text="September 2026",
                                       lines=[{"number": LONG, "date": LONG, "amount_micros": 1, "tax_micros": 1}])
    reconciliation = render_reconciliation(organization_name="Acme", supplier_name="Sahyadri", statement_date="2026-09-30",
                                           currency="INR", their_balance_micros=1, our_balance_micros=2, differences=[
                                               {"code": "MISSING_IN_OUR_BOOKS", "their_micros": 1,
                                                "evidence": [{"side": "theirs", "reference": LONG, "on": "2026-09-01"}]}])
    for subject, html_body, text_body in (reminder, reconciliation):
        for part in (subject, html_body, text_body):
            assert "Z" * 1000 not in part
