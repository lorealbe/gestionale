"""Table detection and parsing for line items and VAT rows."""

from __future__ import annotations

import re
from decimal import Decimal

from .layout_engine import line_text
from .models import LineItemResult, VATBreakdownRow
from .normalizers import (
    find_percent_candidates,
    normalize_text,
    parse_italian_decimal,
)
from .structure_reader import detect_section_indices


def extract_line_items(lines: list, header_aliases: dict[str, list[str]]) -> list[LineItemResult]:
    layout = _find_line_item_layout(lines, header_aliases)
    if layout is None:
        return []

    header_index, stop_index, anchors = layout

    parsed: list[LineItemResult] = []
    for line in lines[header_index + 1 : stop_index]:
        text = line_text(line)
        if not text:
            continue

        lowered = text.lower()
        if any(keyword in lowered for keyword in ("totale documento", "totale da pagare", "pagamento")):
            break
        if any(keyword in lowered for keyword in ("tipo dato", "valore testo", "esigibil")):
            continue

        item = _parse_line_item_geometric(line, anchors)
        if item and _is_material_row(item, lowered):
            parsed.append(item)

    return parsed


def extract_vat_breakdown(lines: list) -> list[VATBreakdownRow]:
    layout = _find_vat_layout(lines)
    if layout is None:
        return _extract_vat_breakdown_fallback(lines)

    header_index, stop_index, anchors = layout
    results: list[VATBreakdownRow] = []
    seen: set[tuple[str, str, str]] = set()

    for line in lines[header_index + 1 : stop_index]:
        text = line_text(line)
        if not text:
            continue

        vat_rate = _pick_decimal_near_x(line, anchors["vat_rate"], tolerance=0.08)
        taxable = _pick_decimal_near_x(line, anchors["taxable_amount"], tolerance=0.10)
        tax = _pick_decimal_near_x(line, anchors["tax_amount"], tolerance=0.10)

        if vat_rate is None or (taxable is None and tax is None):
            continue

        total_with_tax = taxable + tax if taxable is not None and tax is not None else None

        dedupe_key = (str(vat_rate), str(taxable), str(tax))
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)

        results.append(
            VATBreakdownRow(
                vat_rate=vat_rate,
                taxable_amount=taxable,
                tax_amount=tax,
                total_with_tax=total_with_tax,
                confidence=0.90 if taxable is not None and tax is not None else 0.76,
            )
        )

    return results


def _find_line_item_layout(
    lines: list,
    header_aliases: dict[str, list[str]],
) -> tuple[int, int, dict[str, float]] | None:
    section_indices = detect_section_indices(lines)
    items_header = section_indices.items_header
    if items_header is None:
        items_header = _find_header_index(lines, header_aliases)

    if items_header is None:
        return None

    header_line = lines[items_header]
    header_tokens = [
        (normalize_text(token.text.lower()).strip(".:;"), token.bbox.x0)
        for token in sorted(header_line.tokens, key=lambda token: token.bbox.x0)
    ]

    quantity_x = _find_column_x(header_tokens, header_aliases.get("quantity", []), fallback=0.52)
    unit_price_x = _find_column_x(header_tokens, header_aliases.get("unit_price", []), fallback=0.68)
    line_total_x = _find_column_x(header_tokens, header_aliases.get("line_total", []), fallback=0.82)
    vat_rate_x = _find_column_x(header_tokens, header_aliases.get("vat_rate", []), fallback=0.91)

    stop_index = section_indices.vat_header if section_indices.vat_header is not None else len(lines)
    anchors = {
        "quantity": quantity_x,
        "unit_price": unit_price_x,
        "line_total": line_total_x,
        "vat_rate": vat_rate_x,
    }
    return items_header, stop_index, anchors


def _find_vat_layout(lines: list) -> tuple[int, int, dict[str, float]] | None:
    section_indices = detect_section_indices(lines)
    if section_indices.vat_header is None:
        return None

    header_line = lines[section_indices.vat_header]
    header_tokens = [
        (normalize_text(token.text.lower()).strip(".:;"), token.bbox.x0)
        for token in sorted(header_line.tokens, key=lambda token: token.bbox.x0)
    ]

    anchors = {
        "vat_rate": _find_column_x(header_tokens, ["%iva", "iva"], fallback=0.24),
        "tax_amount": _find_column_x(header_tokens, ["imposta"], fallback=0.33),
        "taxable_amount": _find_column_x(header_tokens, ["imponibile"], fallback=0.43),
    }
    stop_index = section_indices.payment_header if section_indices.payment_header is not None else len(lines)
    return section_indices.vat_header, stop_index, anchors


def _find_header_index(lines: list, header_aliases: dict[str, list[str]]) -> int | None:
    for index, line in enumerate(lines):
        text = line_text(line).lower()
        if not text:
            continue

        matched_groups = 0
        for aliases in header_aliases.values():
            if any(alias in text for alias in aliases):
                matched_groups += 1

        if matched_groups >= 2:
            return index

    return None


def _parse_line_item_geometric(line, anchors: dict[str, float]) -> LineItemResult | None:
    ordered_tokens = sorted(line.tokens, key=lambda token: token.bbox.x0)
    quantity_x = anchors["quantity"]
    unit_price_x = anchors["unit_price"]
    line_total_x = anchors["line_total"]
    vat_rate_x = anchors["vat_rate"]

    description_tokens = [token.text for token in ordered_tokens if token.bbox.center_x < quantity_x - 0.03]
    if description_tokens and re.fullmatch(r"\d+", description_tokens[0]):
        description_tokens = description_tokens[1:]
    description = normalize_text(" ".join(description_tokens))

    quantity = _pick_decimal_near_x(line, quantity_x, tolerance=0.08)
    unit_price = _pick_decimal_near_x(line, unit_price_x, tolerance=0.08)
    line_total = _pick_decimal_near_x(line, line_total_x, tolerance=0.08)
    vat_rate = _pick_decimal_near_x(line, vat_rate_x, tolerance=0.06)

    if not description and quantity is None and line_total is None:
        return None

    confidence = 0.55
    if description:
        confidence += 0.15
    if quantity is not None:
        confidence += 0.1
    if unit_price is not None:
        confidence += 0.1
    if line_total is not None:
        confidence += 0.1

    return LineItemResult(
        description=description,
        quantity=_normalize_quantity(quantity),
        unit_price=unit_price,
        vat_rate=vat_rate,
        line_total=line_total,
        confidence=min(confidence, 0.95),
    )


def _strip_numeric_components(text: str) -> str:
    cleaned = re.sub(r"\d+[\d\s.,'’]*%?", " ", text)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" -:;")
    return cleaned


def _normalize_quantity(quantity: Decimal | None) -> Decimal | None:
    if quantity is None:
        return None
    if quantity < 0:
        return None
    return quantity


def _pick_decimal_near_x(line, target_x: float, tolerance: float) -> Decimal | None:
    best_value: Decimal | None = None
    best_distance: float | None = None

    for token in line.tokens:
        parsed = parse_italian_decimal(token.text)
        if parsed is None:
            continue

        distance = abs(token.bbox.x0 - target_x)
        if distance > tolerance:
            continue

        if best_distance is None or distance < best_distance:
            best_distance = distance
            best_value = parsed

    return best_value


def _find_column_x(header_tokens: list[tuple[str, float]], aliases: list[str], fallback: float) -> float:
    for alias in aliases:
        alias_norm = normalize_text(alias.lower()).strip(".:;")
        for token_text, token_x in header_tokens:
            if alias_norm in token_text:
                return token_x
    return fallback


def _is_material_row(item: LineItemResult, lowered_text: str) -> bool:
    if any(keyword in lowered_text for keyword in ("documento n.", "sede di consegna", "riga ausiliaria")):
        return False
    if not item.description:
        return False
    if item.quantity is None or item.quantity <= Decimal("0"):
        return False
    if item.line_total is None or item.line_total <= Decimal("0"):
        return False
    if item.unit_price is not None and item.unit_price <= Decimal("0"):
        return False
    return True


def _extract_vat_breakdown_fallback(lines: list) -> list[VATBreakdownRow]:
    rows: list[VATBreakdownRow] = []
    seen: set[tuple[str, str, str]] = set()

    for line in lines:
        text = line_text(line)
        lowered = text.lower()
        if "iva" not in lowered:
            continue

        percents = [token.text for token in line.tokens if "%" in token.text]
        if not percents:
            percents = find_percent_candidates(text)
        if not percents:
            continue

        numbers = [
            value
            for token in line.tokens
            if "%" not in token.text and (value := parse_italian_decimal(token.text)) is not None
        ]
        if len(numbers) < 2:
            continue

        vat_rate = parse_italian_decimal(percents[0])
        if vat_rate is None:
            continue

        taxable = numbers[-2] if len(numbers) >= 2 else None
        tax = numbers[-1] if len(numbers) >= 1 else None
        if taxable is None:
            continue

        key = (str(vat_rate), str(taxable), str(tax))
        if key in seen:
            continue
        seen.add(key)

        rows.append(
            VATBreakdownRow(
                vat_rate=vat_rate,
                taxable_amount=taxable,
                tax_amount=tax,
                total_with_tax=(taxable + tax) if tax is not None else None,
                confidence=0.72,
            )
        )

    return rows
