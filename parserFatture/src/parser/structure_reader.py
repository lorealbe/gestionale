"""Detects high-level invoice sections from geometric lines."""

from __future__ import annotations

from dataclasses import dataclass

from .layout_engine import line_text
from .models import Block


@dataclass(frozen=True)
class SectionIndices:
    document_header: int | None
    items_header: int | None
    vat_header: int | None
    payment_header: int | None
    footer: int | None


def detect_section_indices(lines: list[Block]) -> SectionIndices:
    document_header = _find_line_index(lines, lambda t: "dati documento" in t)
    items_header = _find_line_index(
        lines,
        lambda t: ("articolo" in t or "descrizione" in t)
        and ("quantita" in t or "quantita'" in t or "qta" in t or "qty" in t)
        and ("prezzo" in t or "importo" in t or "totale" in t),
        start=(document_header + 1) if document_header is not None else 0,
    )
    vat_header = _find_line_index(
        lines,
        lambda t: "esigibil" in t and "%iva" in t and "imposta" in t,
        start=(items_header + 1) if items_header is not None else 0,
    )
    payment_header = _find_line_index(
        lines,
        lambda t: "pagamento" in t and "scadenza" in t and "importo" in t,
        start=(vat_header + 1) if vat_header is not None else 0,
    )
    footer = _find_line_index(
        lines,
        lambda t: "documento non valido ai fini fiscali" in t,
        start=(payment_header + 1) if payment_header is not None else 0,
    )

    return SectionIndices(
        document_header=document_header,
        items_header=items_header,
        vat_header=vat_header,
        payment_header=payment_header,
        footer=footer,
    )


def build_structure(lines: list[Block]) -> dict[str, list[Block]]:
    indices = detect_section_indices(lines)
    length = len(lines)

    document_start = indices.document_header if indices.document_header is not None else 0
    items_start = indices.items_header if indices.items_header is not None else length
    vat_start = indices.vat_header if indices.vat_header is not None else length
    payment_start = indices.payment_header if indices.payment_header is not None else length
    footer_start = indices.footer if indices.footer is not None else length

    parties = lines[:document_start] if document_start > 0 else []
    document_data = lines[document_start:items_start] if document_start < items_start else []
    line_items = lines[items_start:vat_start] if items_start < vat_start else []
    vat_summary = lines[vat_start:payment_start] if vat_start < payment_start else []
    payment = lines[payment_start:footer_start] if payment_start < footer_start else []
    footer = lines[footer_start:] if footer_start < length else []

    return {
        "parties": parties,
        "document_data": document_data,
        "line_items": line_items,
        "vat_summary": vat_summary,
        "payment": payment,
        "footer": footer,
    }


def serialize_structure(structure: dict[str, list[Block]]) -> dict[str, list[str]]:
    output: dict[str, list[str]] = {}
    for key, section_lines in structure.items():
        output[key] = [line_text(line) for line in section_lines if line.tokens]
    return output


def line_slice_text(line: Block, x_min: float = 0.0, x_max: float = 1.0) -> str:
    tokens = [
        token.text
        for token in sorted(line.tokens, key=lambda t: t.bbox.x0)
        if x_min <= token.bbox.center_x <= x_max
    ]
    return " ".join(tokens).strip()


def _find_line_index(lines: list[Block], predicate, start: int = 0) -> int | None:
    for index in range(start, len(lines)):
        text = line_text(lines[index]).lower()
        if predicate(text):
            return index
    return None
