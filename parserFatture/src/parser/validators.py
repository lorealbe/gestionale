"""Validation helpers for invoice consistency and review routing."""

from __future__ import annotations

from decimal import Decimal

from .models import FieldResult, LineItemResult, VATBreakdownRow


def mark_confirmation_required(fields: dict[str, FieldResult], threshold: float) -> None:
    for field in fields.values():
        field.requires_confirmation = field.confidence < threshold


def validate_line_item_totals(line_items: list[LineItemResult]) -> list[str]:
    warnings: list[str] = []

    for index, item in enumerate(line_items, start=1):
        if item.quantity is None or item.unit_price is None or item.line_total is None:
            continue

        expected = (item.quantity * item.unit_price).quantize(Decimal("0.01"))
        observed = item.line_total.quantize(Decimal("0.01"))
        if abs(expected - observed) > Decimal("0.05"):
            warnings.append(
                f"Riga {index}: qty*unit_price={expected} differisce dal totale riga={observed}"
            )

    return warnings


def validate_vat_rows(vat_rows: list[VATBreakdownRow]) -> list[str]:
    warnings: list[str] = []

    for row in vat_rows:
        if row.taxable_amount is None or row.tax_amount is None or row.total_with_tax is None:
            continue

        expected_total = (row.taxable_amount + row.tax_amount).quantize(Decimal("0.01"))
        observed_total = row.total_with_tax.quantize(Decimal("0.01"))
        if abs(expected_total - observed_total) > Decimal("0.05"):
            warnings.append(
                f"Breakdown IVA {row.vat_rate}% non coerente: {expected_total} vs {observed_total}"
            )

    return warnings


def validate_document_total(
    total_field: FieldResult | None,
    line_items: list[LineItemResult],
    vat_rows: list[VATBreakdownRow],
) -> list[str]:
    if total_field is None or total_field.normalized_value is None:
        return []

    try:
        total_document = Decimal(str(total_field.normalized_value)).quantize(Decimal("0.01"))
    except Exception:
        return ["Totale documento non interpretabile come valore numerico"]

    warnings: list[str] = []

    taxable_sum = None
    if vat_rows:
        taxable_sum = sum((row.taxable_amount or Decimal("0")) for row in vat_rows).quantize(Decimal("0.01"))

    if line_items:
        line_sum = sum((item.line_total or Decimal("0")) for item in line_items)
        line_sum = line_sum.quantize(Decimal("0.01"))
        if taxable_sum is not None:
            if abs(taxable_sum - line_sum) > Decimal("0.10"):
                warnings.append(
                    f"Somma righe ({line_sum}) non allineata con imponibile IVA ({taxable_sum})"
                )
        elif abs(total_document - line_sum) > Decimal("0.10"):
            warnings.append(
                f"Totale documento ({total_document}) non allineato con somma righe ({line_sum})"
            )

    if vat_rows:
        taxable_sum = sum((row.taxable_amount or Decimal("0")) for row in vat_rows)
        tax_sum = sum((row.tax_amount or Decimal("0")) for row in vat_rows)
        computed = (taxable_sum + tax_sum).quantize(Decimal("0.01"))
        if abs(total_document - computed) > Decimal("0.10"):
            warnings.append(
                f"Totale documento ({total_document}) non allineato con imponibile+IVA ({computed})"
            )

    return warnings
