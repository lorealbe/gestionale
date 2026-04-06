"""Parser configuration objects."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ConfidenceThresholds:
    """Thresholds that define parser behavior."""

    auto_accept: float = 0.85
    review_required: float = 0.65


@dataclass(frozen=True)
class OCRConfig:
    """OCR runtime options."""

    enabled: bool = True
    language: str = "ita+eng"
    dpi: int = 220
    min_text_tokens_for_digital: int = 12
    tesseract_cmd: str | None = None


@dataclass(frozen=True)
class LayoutConfig:
    """Geometric matching options."""

    y_tolerance: float = 0.012
    block_vertical_gap: float = 0.02
    label_max_horizontal_distance: float = 0.35
    label_max_vertical_distance: float = 0.03


@dataclass(frozen=True)
class ParserConfig:
    """Main parser configuration."""

    thresholds: ConfidenceThresholds = field(default_factory=ConfidenceThresholds)
    ocr: OCRConfig = field(default_factory=OCRConfig)
    layout: LayoutConfig = field(default_factory=LayoutConfig)
    field_labels: dict[str, list[str]] = field(
        default_factory=lambda: {
            "supplier_name": ["fornitore", "cedente", "emittente", "ragione sociale"],
            "supplier_vat": ["p.iva", "partita iva", "p iva", "identificativo fiscale ai fini iva"],
            "customer_name": ["cliente", "cessionario", "destinatario"],
            "customer_vat": ["p.iva cliente", "partita iva cliente", "identificativo fiscale ai fini iva"],
            "invoice_number": ["fattura n", "numero fattura", "doc n", "n. fattura"],
            "invoice_date": ["data fattura", "data emissione", "data documento"],
            "due_date": ["scadenza", "data scadenza", "entro il", "pagamento entro"],
            "total_amount": ["totale documento", "importo totale", "totale da pagare", "totale fattura"],
            "taxable_total": ["totale imponibile", "imponibile totale"],
            "vat_total": ["totale iva", "totale imposta", "iva totale"],
            "payment_terms": ["modalita pagamento", "condizioni pagamento", "pagamento"],
        }
    )
    table_header_aliases: dict[str, list[str]] = field(
        default_factory=lambda: {
            "description": ["descrizione", "articolo", "servizio", "causale"],
            "quantity": ["qta", "quantita", "qty", "n."],
            "unit_price": ["prezzo", "prezzo unitario", "unit price", "importo unitario"],
            "vat_rate": ["iva", "aliquota"],
            "line_total": ["totale", "importo", "imponibile"],
        }
    )
