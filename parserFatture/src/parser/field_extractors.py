"""Field-level extraction logic using geometry-first matching."""

from __future__ import annotations

import re
from decimal import Decimal

from .config import ParserConfig
from .layout_engine import extract_document_text, find_labeled_value
from .models import AuditEvent, Block, ExtractionMethod, FieldResult
from .normalizers import (
    normalize_invoice_number,
    normalize_text,
    normalize_vat_number,
    parse_italian_date,
    parse_italian_decimal,
)
from .structure_reader import build_structure, line_slice_text


def extract_fields(
    lines: list[Block],
    config: ParserConfig,
    structure: dict[str, list[Block]] | None = None,
) -> tuple[dict[str, FieldResult], list[AuditEvent]]:
    fields: dict[str, FieldResult] = {}
    audit: list[AuditEvent] = []

    sections = structure or build_structure(lines)
    _extract_top_party_fields(sections.get("parties", []), fields, audit)
    _extract_document_data_fields(sections.get("document_data", []), fields, audit)
    _extract_total_amount_from_sections(sections, fields, audit)
    _extract_tax_totals_from_sections(sections, fields, audit)
    _extract_payment_fields(sections.get("payment", []), fields, audit)

    for field_name, labels in config.field_labels.items():
        if field_name in fields and fields[field_name].confidence >= config.thresholds.auto_accept:
            continue

        raw_value, confidence, source_block_id = find_labeled_value(
            lines=lines,
            labels=labels,
            max_horizontal_distance=config.layout.label_max_horizontal_distance,
            max_vertical_distance=config.layout.label_max_vertical_distance,
        )
        if not raw_value:
            continue

        normalized = _normalize_field_value(field_name, raw_value)
        _upsert_field(
            fields,
            FieldResult(
                name=field_name,
                raw_value=raw_value,
                normalized_value=normalized,
                confidence=confidence,
                method=ExtractionMethod.GEOMETRY,
                source_block_id=source_block_id,
            ),
        )
        audit.append(
            AuditEvent(
                field_name=field_name,
                method=ExtractionMethod.GEOMETRY,
                confidence=confidence,
                source_block_id=source_block_id,
                message=f"Field extracted by geometric label matching ({field_name})",
            )
        )

    full_text = extract_document_text(lines)
    _apply_regex_fallback(full_text, fields, audit)
    _fallback_customer_vat_from_global_pattern(full_text, fields, audit)

    return fields, audit


def _normalize_field_value(field_name: str, value: str) -> str | Decimal | None:
    if field_name in {"invoice_date", "due_date"}:
        parsed = parse_italian_date(value)
        return parsed.isoformat() if parsed else None

    if field_name in {"total_amount", "taxable_total", "vat_total"}:
        return parse_italian_decimal(value)

    if field_name in {"supplier_vat", "customer_vat"}:
        return normalize_vat_number(value)

    if field_name in {"invoice_number"}:
        return normalize_invoice_number(value)

    return normalize_text(value)


def _extract_top_party_fields(
    top_lines: list[Block],
    fields: dict[str, FieldResult],
    audit: list[AuditEvent],
) -> None:
    if not top_lines:
        return

    first_left = _clean_party_text(line_slice_text(top_lines[0], x_min=0.0, x_max=0.5))
    if first_left:
        _upsert_field(
            fields,
            FieldResult(
                name="supplier_name",
                raw_value=first_left,
                normalized_value=normalize_text(first_left),
                confidence=0.95,
                method=ExtractionMethod.GEOMETRY,
                source_block_id=top_lines[0].block_id,
            ),
        )
        audit.append(
            AuditEvent(
                field_name="supplier_name",
                method=ExtractionMethod.GEOMETRY,
                confidence=0.95,
                source_block_id=top_lines[0].block_id,
                message="Supplier extracted from top-left company block",
            )
        )

    supplier_vat, customer_vat = _extract_top_vat_numbers(top_lines)
    if supplier_vat:
        _upsert_field(
            fields,
            FieldResult(
                name="supplier_vat",
                raw_value=supplier_vat,
                normalized_value=normalize_vat_number(supplier_vat),
                confidence=0.94,
                method=ExtractionMethod.GEOMETRY,
                source_block_id=None,
            ),
        )
        audit.append(
            AuditEvent(
                field_name="supplier_vat",
                method=ExtractionMethod.GEOMETRY,
                confidence=0.94,
                source_block_id=None,
                message="Supplier VAT extracted from top-left fiscal identifier",
            )
        )

    if customer_vat:
        _upsert_field(
            fields,
            FieldResult(
                name="customer_vat",
                raw_value=customer_vat,
                normalized_value=normalize_vat_number(customer_vat),
                confidence=0.94,
                method=ExtractionMethod.GEOMETRY,
                source_block_id=None,
            ),
        )
        audit.append(
            AuditEvent(
                field_name="customer_vat",
                method=ExtractionMethod.GEOMETRY,
                confidence=0.94,
                source_block_id=None,
                message="Customer VAT extracted from top-right fiscal identifier",
            )
        )

    customer_name, source_block_id = _extract_top_customer_name(top_lines)
    if customer_name:
        _upsert_field(
            fields,
            FieldResult(
                name="customer_name",
                raw_value=customer_name,
                normalized_value=normalize_text(customer_name),
                confidence=0.93,
                method=ExtractionMethod.GEOMETRY,
                source_block_id=source_block_id,
            ),
        )
        audit.append(
            AuditEvent(
                field_name="customer_name",
                method=ExtractionMethod.GEOMETRY,
                confidence=0.93,
                source_block_id=source_block_id,
                message="Customer name extracted from top-right recipient block",
            )
        )


def _extract_document_data_fields(
    document_lines: list[Block],
    fields: dict[str, FieldResult],
    audit: list[AuditEvent],
) -> None:
    if not document_lines:
        return

    doc_pattern = re.compile(r"n[.]?\s*([A-Z0-9/-]+)\s+del\s+(.+?)(?:\s+causale:|$)", flags=re.IGNORECASE)
    for line in document_lines:
        text = normalize_text(" ".join(token.text for token in line.tokens))
        match = doc_pattern.search(text)
        if not match:
            continue

        number_raw = match.group(1)
        date_raw = match.group(2)
        _upsert_field(
            fields,
            FieldResult(
                name="invoice_number",
                raw_value=number_raw,
                normalized_value=normalize_invoice_number(number_raw),
                confidence=0.96,
                method=ExtractionMethod.GEOMETRY,
                source_block_id=line.block_id,
            ),
        )
        audit.append(
            AuditEvent(
                field_name="invoice_number",
                method=ExtractionMethod.GEOMETRY,
                confidence=0.96,
                source_block_id=line.block_id,
                message="Invoice number extracted from 'n. ... del ...' block",
            )
        )

        parsed_date = parse_italian_date(date_raw)
        _upsert_field(
            fields,
            FieldResult(
                name="invoice_date",
                raw_value=date_raw,
                normalized_value=parsed_date.isoformat() if parsed_date else None,
                confidence=0.96 if parsed_date else 0.70,
                method=ExtractionMethod.GEOMETRY,
                source_block_id=line.block_id,
            ),
        )
        audit.append(
            AuditEvent(
                field_name="invoice_date",
                method=ExtractionMethod.GEOMETRY,
                confidence=0.96 if parsed_date else 0.70,
                source_block_id=line.block_id,
                message="Invoice date extracted from 'n. ... del ...' block",
            )
        )
        return


def _extract_total_amount_from_sections(
    sections: dict[str, list[Block]],
    fields: dict[str, FieldResult],
    audit: list[AuditEvent],
) -> None:
    search_lines = sections.get("vat_summary", []) + sections.get("payment", [])
    if not search_lines:
        search_lines = [line for group in sections.values() for line in group]

    pattern = re.compile(r"totale\s+documento\s+([\d.,'’]+)", flags=re.IGNORECASE)
    for line in search_lines:
        text = normalize_text(" ".join(token.text for token in line.tokens))
        match = pattern.search(text)
        if not match:
            continue

        amount_raw = match.group(1)
        amount_value = parse_italian_decimal(amount_raw)
        _upsert_field(
            fields,
            FieldResult(
                name="total_amount",
                raw_value=amount_raw,
                normalized_value=amount_value,
                confidence=0.95,
                method=ExtractionMethod.GEOMETRY,
                source_block_id=line.block_id,
            ),
        )
        audit.append(
            AuditEvent(
                field_name="total_amount",
                method=ExtractionMethod.GEOMETRY,
                confidence=0.95,
                source_block_id=line.block_id,
                message="Total amount extracted from 'Totale documento' line",
            )
        )
        return


def _extract_tax_totals_from_sections(
    sections: dict[str, list[Block]],
    fields: dict[str, FieldResult],
    audit: list[AuditEvent],
) -> None:
    vat_lines = sections.get("vat_summary", [])
    if not vat_lines:
        return

    imponibile_pattern = re.compile(r"totale\s+imponibile\s+([\d.,'’]+)", flags=re.IGNORECASE)
    iva_pattern = re.compile(r"totale\s+iva\s+([\d.,'’]+)", flags=re.IGNORECASE)

    for line in vat_lines:
        text = normalize_text(" ".join(token.text for token in line.tokens))

        imponibile_match = imponibile_pattern.search(text)
        if imponibile_match:
            imponibile_raw = imponibile_match.group(1)
            imponibile_value = parse_italian_decimal(imponibile_raw)
            _upsert_field(
                fields,
                FieldResult(
                    name="taxable_total",
                    raw_value=imponibile_raw,
                    normalized_value=imponibile_value,
                    confidence=0.92,
                    method=ExtractionMethod.GEOMETRY,
                    source_block_id=line.block_id,
                ),
            )
            audit.append(
                AuditEvent(
                    field_name="taxable_total",
                    method=ExtractionMethod.GEOMETRY,
                    confidence=0.92,
                    source_block_id=line.block_id,
                    message="Taxable total extracted from VAT summary line",
                )
            )

        iva_match = iva_pattern.search(text)
        if iva_match:
            iva_raw = iva_match.group(1)
            iva_value = parse_italian_decimal(iva_raw)
            _upsert_field(
                fields,
                FieldResult(
                    name="vat_total",
                    raw_value=iva_raw,
                    normalized_value=iva_value,
                    confidence=0.92,
                    method=ExtractionMethod.GEOMETRY,
                    source_block_id=line.block_id,
                ),
            )
            audit.append(
                AuditEvent(
                    field_name="vat_total",
                    method=ExtractionMethod.GEOMETRY,
                    confidence=0.92,
                    source_block_id=line.block_id,
                    message="VAT total extracted from VAT summary line",
                )
            )


def _extract_payment_fields(
    payment_lines: list[Block],
    fields: dict[str, FieldResult],
    audit: list[AuditEvent],
) -> None:
    if len(payment_lines) < 2:
        return

    header_line = payment_lines[0]
    value_line = payment_lines[1]

    header_positions = _find_header_positions(header_line)
    scadenza_x = header_positions.get("scadenza")
    importo_x = header_positions.get("importo")

    if scadenza_x is not None:
        due_raw = line_slice_text(
            value_line,
            x_min=max(0.0, scadenza_x - 0.02),
            x_max=(importo_x - 0.01) if importo_x is not None else 1.0,
        )
        if due_raw:
            due_date = parse_italian_date(due_raw)
            _upsert_field(
                fields,
                FieldResult(
                    name="due_date",
                    raw_value=due_raw,
                    normalized_value=due_date.isoformat() if due_date else None,
                    confidence=0.93 if due_date else 0.66,
                    method=ExtractionMethod.GEOMETRY,
                    source_block_id=value_line.block_id,
                ),
            )
            audit.append(
                AuditEvent(
                    field_name="due_date",
                    method=ExtractionMethod.GEOMETRY,
                    confidence=0.93 if due_date else 0.66,
                    source_block_id=value_line.block_id,
                    message="Due date extracted from payment schedule row",
                )
            )

    if scadenza_x is not None:
        payment_raw = line_slice_text(value_line, x_min=0.0, x_max=max(0.0, scadenza_x - 0.01))
        if payment_raw:
            _upsert_field(
                fields,
                FieldResult(
                    name="payment_terms",
                    raw_value=payment_raw,
                    normalized_value=normalize_text(payment_raw),
                    confidence=0.90,
                    method=ExtractionMethod.GEOMETRY,
                    source_block_id=value_line.block_id,
                ),
            )
            audit.append(
                AuditEvent(
                    field_name="payment_terms",
                    method=ExtractionMethod.GEOMETRY,
                    confidence=0.90,
                    source_block_id=value_line.block_id,
                    message="Payment terms extracted from payment schedule row",
                )
            )


def _find_header_positions(line: Block) -> dict[str, float]:
    mapping: dict[str, float] = {}
    for token in line.tokens:
        lowered = normalize_text(token.text.lower()).strip(".:;")
        if lowered in {"pagamento", "scadenza", "importo"}:
            mapping[lowered] = token.bbox.x0
    return mapping


def _clean_party_text(text: str) -> str | None:
    if not text:
        return None

    value = text
    separators = [
        "Codice Amministrazione destinataria",
        "Destinatario PEC",
        "Identificativo fiscale ai fini IVA",
    ]
    for separator in separators:
        if separator.lower() in value.lower():
            value = value.split(separator, maxsplit=1)[0]
    value = normalize_text(value)
    return value or None


def _extract_top_vat_numbers(top_lines: list[Block]) -> tuple[str | None, str | None]:
    supplier_vat: str | None = None
    customer_vat: str | None = None
    vat_pattern = re.compile(r"(?:IT)?\s*(\d{11})")

    for line in top_lines:
        for token in line.tokens:
            match = vat_pattern.search(token.text)
            if not match:
                continue

            vat = match.group(1)
            if token.bbox.center_x < 0.5 and supplier_vat is None:
                supplier_vat = vat
            elif token.bbox.center_x >= 0.5 and customer_vat is None:
                customer_vat = vat

    return supplier_vat, customer_vat


def _extract_top_customer_name(top_lines: list[Block]) -> tuple[str | None, str | None]:
    best_candidate: tuple[int, str, str] | None = None

    for line in top_lines:
        right_text = normalize_text(line_slice_text(line, x_min=0.5, x_max=1.0))
        if not right_text:
            continue

        lowered = right_text.lower()
        if any(prefix in lowered for prefix in ("destinatario pec", "codice fiscale", "identificativo fiscale")):
            continue
        if "@" in right_text or any(char.isdigit() for char in right_text):
            continue
        if any(keyword in lowered for keyword in ("via", "viale", "piazza", "italia", "cap")):
            continue

        words = re.findall(r"[A-Za-zÀ-ÖØ-öø-ÿ]+", right_text)
        if len(words) < 2:
            continue

        score = sum(1 for word in words if word.isupper())
        score += len(words)
        if best_candidate is None or score > best_candidate[0]:
            best_candidate = (score, right_text, line.block_id)

    if best_candidate is None:
        return None, None
    return best_candidate[1], best_candidate[2]


def _upsert_field(fields: dict[str, FieldResult], candidate: FieldResult) -> None:
    existing = fields.get(candidate.name)
    if existing is None or candidate.confidence >= existing.confidence:
        fields[candidate.name] = candidate


def _apply_regex_fallback(
    full_text: str,
    fields: dict[str, FieldResult],
    audit: list[AuditEvent],
) -> None:
    fallback_patterns = {
        "invoice_number": [
            r"\bn[.]?\s*([A-Z0-9][A-Z0-9/.-]+)\s+del\b",
            r"(?:fattura|invoice|doc(?:umento)?)\s*(?:n(?:umero)?[.]?)?\s*[:#-]?\s*([A-Z0-9/.-]+)",
        ],
        "invoice_date": [
            r"n[.]?\s*[A-Z0-9/.-]+\s+del\s+([^\n]+)",
            r"(?:data\s*(?:fattura|emissione|documento))\s*[:\-]?\s*([^\n]+)",
        ],
        "due_date": [
            r"(?:scadenza|pagamento\s+entro|data\s+scadenza)\s*[:\-]?\s*([^\n]+)",
        ],
        "total_amount": [
            r"(?:totale\s*documento|totale\s*da\s*pagare)\s*[:\-]?\s*([\d\s.,'’]+)",
        ],
        "taxable_total": [
            r"(?:totale\s*imponibile|imponibile\s*totale)\s*[:\-]?\s*([\d\s.,'’]+)",
        ],
        "vat_total": [
            r"(?:totale\s*iva|iva\s*totale|totale\s*imposta)\s*[:\-]?\s*([\d\s.,'’]+)",
        ],
        "supplier_vat": [
            r"(?:identificativo\s+fiscale\s+ai\s+fini\s+iva|p[.]?\s*iva|partita\s+iva)\s*[:\-]?\s*(?:it)?\s*(\d{11})",
        ],
    }

    lowered_text = full_text.lower()
    for field_name, patterns in fallback_patterns.items():
        if field_name in fields:
            continue

        for pattern in patterns:
            match = re.search(pattern, lowered_text, flags=re.IGNORECASE)
            if not match:
                continue

            raw_value = normalize_text(match.group(1))
            normalized = _normalize_field_value(field_name, raw_value)
            fields[field_name] = FieldResult(
                name=field_name,
                raw_value=raw_value,
                normalized_value=normalized,
                confidence=0.62,
                method=ExtractionMethod.REGEX,
                source_block_id=None,
            )
            audit.append(
                AuditEvent(
                    field_name=field_name,
                    method=ExtractionMethod.REGEX,
                    confidence=0.62,
                    source_block_id=None,
                    message=f"Field extracted by regex fallback ({field_name})",
                )
            )
            break


def _fallback_customer_vat_from_global_pattern(
    full_text: str,
    fields: dict[str, FieldResult],
    audit: list[AuditEvent],
) -> None:
    if "customer_vat" in fields:
        return

    vat_candidates = re.findall(r"\b\d{11}\b", full_text)
    if len(vat_candidates) < 2:
        return

    fields["customer_vat"] = FieldResult(
        name="customer_vat",
        raw_value=vat_candidates[1],
        normalized_value=vat_candidates[1],
        confidence=0.52,
        method=ExtractionMethod.REGEX,
        source_block_id=None,
    )
    audit.append(
        AuditEvent(
            field_name="customer_vat",
            method=ExtractionMethod.REGEX,
            confidence=0.52,
            source_block_id=None,
            message="Customer VAT inferred from second VAT-like token",
        )
    )
