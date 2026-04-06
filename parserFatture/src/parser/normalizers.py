"""Normalization utilities for Italian invoices."""

from __future__ import annotations

import re
from datetime import date
from decimal import Decimal, InvalidOperation

from dateutil import parser as date_parser

MONTH_ALIASES = {
    "gennaio": "01",
    "gen": "01",
    "febbraio": "02",
    "feb": "02",
    "marzo": "03",
    "mar": "03",
    "aprile": "04",
    "apr": "04",
    "maggio": "05",
    "mag": "05",
    "giugno": "06",
    "giu": "06",
    "luglio": "07",
    "lug": "07",
    "agosto": "08",
    "ago": "08",
    "settembre": "09",
    "set": "09",
    "ottobre": "10",
    "ott": "10",
    "novembre": "11",
    "nov": "11",
    "dicembre": "12",
    "dic": "12",
}


def normalize_text(value: str) -> str:
    compact = re.sub(r"\s+", " ", value or "").strip()
    return compact


def normalize_vat_number(value: str | None) -> str | None:
    if not value:
        return None
    digits = re.sub(r"\D", "", value)
    if len(digits) == 11:
        return digits
    return None


def normalize_invoice_number(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"\s+", "", value)
    cleaned = re.sub(r"^[Nn][.]?", "", cleaned)
    return cleaned.strip("-:/") or None


def parse_italian_decimal(value: str | None) -> Decimal | None:
    if not value:
        return None

    raw = value.strip()
    if not raw:
        return None

    # Preserve minus sign while stripping currency and spacing variants.
    cleaned = re.sub(r"[^0-9,.'’\-]", "", raw)
    cleaned = cleaned.replace("’", "'")

    if not cleaned or cleaned in {"-", ",", "."}:
        return None

    cleaned = cleaned.replace("'", "")

    decimal_sep = None
    comma_idx = cleaned.rfind(",")
    dot_idx = cleaned.rfind(".")

    if comma_idx != -1 and dot_idx != -1:
        decimal_sep = "," if comma_idx > dot_idx else "."
    elif comma_idx != -1:
        decimal_sep = ","
    elif dot_idx != -1:
        decimal_sep = "."

    if decimal_sep is None:
        normalized = cleaned
    elif decimal_sep == ",":
        normalized = cleaned.replace(".", "")
        normalized = normalized.replace(",", ".")
    else:
        normalized = cleaned.replace(",", "")

    try:
        return Decimal(normalized)
    except InvalidOperation:
        return None


def parse_italian_date(value: str | None) -> date | None:
    if not value:
        return None

    text = normalize_text(value.lower())

    block_match = re.search(
        r"n[.]?\s*[a-z0-9\-/]+\s+del\s+(\d{1,2})\s+([a-z]+)\s+(\d{4})",
        text,
    )
    if block_match:
        day, month_token, year = block_match.groups()
        month = MONTH_ALIASES.get(month_token)
        if month:
            return date(int(year), int(month), int(day))

    named_month_match = re.search(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})", text)
    if named_month_match:
        day, month_token, year = named_month_match.groups()
        month = MONTH_ALIASES.get(month_token)
        if month:
            return date(int(year), int(month), int(day))

    numeric_match = re.search(r"(\d{1,2})[\-/](\d{1,2})[\-/](\d{2,4})", text)
    if numeric_match:
        day, month, year = numeric_match.groups()
        if len(year) == 2:
            year = f"20{year}"
        return date(int(year), int(month), int(day))

    try:
        parsed = date_parser.parse(text, dayfirst=True, fuzzy=True)
        return parsed.date()
    except (ValueError, OverflowError):
        return None


def find_decimal_candidates(text: str) -> list[str]:
    return re.findall(r"[-+]?\d[\d\s.,'’]*\d|[-+]?\d", text)


def find_percent_candidates(text: str) -> list[str]:
    return re.findall(r"(\d{1,2}(?:[.,]\d{1,2})?)\s*%", text)
