"""End-to-end parser pipeline."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from .config import ParserConfig
from .field_extractors import extract_fields
from .layout_engine import group_lines_into_blocks, group_tokens_into_lines
from .models import AuditEvent, DocumentType, ExtractionMethod, FieldResult, InvoiceResult, Token
from .ocr_engine import OfflineOCREngine
from .pdf_extractor import PDFTokenExtractor
from .structure_reader import build_structure, serialize_structure
from .table_engine import extract_line_items, extract_vat_breakdown
from .validators import (
    mark_confirmation_required,
    validate_document_total,
    validate_line_item_totals,
    validate_vat_rows,
)

REQUIRED_FIELDS = [
    "supplier_name",
    "supplier_vat",
    "customer_name",
    "customer_vat",
    "invoice_number",
    "invoice_date",
    "due_date",
    "total_amount",
]


class InvoiceParserPipeline:
    """Coordinates extraction, geometric reasoning and validation."""

    def __init__(self, config: ParserConfig | None = None):
        self.config = config or ParserConfig()
        self.pdf_extractor = PDFTokenExtractor()
        self.ocr_engine = OfflineOCREngine(self.config.ocr)

    def parse_pdf(self, pdf_path: str) -> InvoiceResult:
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"Input file not found: {pdf_path}")

        tokens = self.pdf_extractor.extract_tokens(str(path))
        document_type = DocumentType.DIGITAL_PDF

        if self.config.ocr.enabled and len(tokens) < self.config.ocr.min_text_tokens_for_digital:
            ocr_tokens = self.ocr_engine.extract_tokens_from_pdf(str(path))
            if len(ocr_tokens) > len(tokens):
                tokens = ocr_tokens
                document_type = DocumentType.SCANNED_DOCUMENT

        return self.parse_tokens(
            tokens=tokens,
            document_path=str(path),
            original_filename=path.name,
            document_type=document_type,
        )

    def parse_tokens(
        self,
        tokens: list[Token],
        document_path: str,
        original_filename: str,
        document_type: DocumentType = DocumentType.DIGITAL_PDF,
    ) -> InvoiceResult:
        lines = group_tokens_into_lines(tokens=tokens, y_tolerance=self.config.layout.y_tolerance)
        _blocks = group_lines_into_blocks(lines=lines, vertical_gap=self.config.layout.block_vertical_gap)
        structure = build_structure(lines)
        serialized_structure = serialize_structure(structure)

        fields, audit_trail = extract_fields(lines=lines, config=self.config, structure=structure)
        line_items = extract_line_items(lines=lines, header_aliases=self.config.table_header_aliases)
        vat_breakdown = extract_vat_breakdown(lines=lines)
        self._ensure_tax_totals_from_breakdown(fields=fields, vat_breakdown=vat_breakdown, audit_trail=audit_trail)

        warnings: list[str] = []
        warnings.extend(validate_line_item_totals(line_items))
        warnings.extend(validate_vat_rows(vat_breakdown))
        warnings.extend(validate_document_total(fields.get("total_amount"), line_items, vat_breakdown))

        self._ensure_required_fields(fields, warnings)
        mark_confirmation_required(fields, threshold=self.config.thresholds.review_required)

        return InvoiceResult(
            document_path=document_path,
            original_filename=original_filename,
            document_type=document_type,
            fields=fields,
            structure=serialized_structure,
            line_items=line_items,
            vat_breakdown=vat_breakdown,
            warnings=warnings,
            audit_trail=audit_trail,
        )

    def _ensure_required_fields(self, fields: dict[str, FieldResult], warnings: list[str]) -> None:
        for field_name in REQUIRED_FIELDS:
            if field_name in fields:
                continue

            fields[field_name] = FieldResult(
                name=field_name,
                raw_value=None,
                normalized_value=None,
                confidence=0.0,
                method=None,
                source_block_id=None,
                requires_confirmation=True,
            )
            warnings.append(f"Campo obbligatorio mancante: {field_name}")

    def _ensure_tax_totals_from_breakdown(
        self,
        fields: dict[str, FieldResult],
        vat_breakdown: list,
        audit_trail: list[AuditEvent],
    ) -> None:
        if not vat_breakdown:
            return

        taxable_sum = sum((row.taxable_amount or Decimal("0")) for row in vat_breakdown)
        vat_sum = sum((row.tax_amount or Decimal("0")) for row in vat_breakdown)

        taxable_existing = fields.get("taxable_total")
        taxable_existing_value = _safe_decimal(
            taxable_existing.normalized_value if taxable_existing is not None else None
        )
        taxable_missing_or_empty = (
            taxable_existing is None
            or taxable_existing.normalized_value is None
            or taxable_existing_value is None
            or taxable_existing_value <= Decimal("0")
        )
        if taxable_missing_or_empty and taxable_sum > Decimal("0"):
            fields["taxable_total"] = FieldResult(
                name="taxable_total",
                raw_value=str(taxable_sum),
                normalized_value=taxable_sum.quantize(Decimal("0.01")),
                confidence=0.88,
                method=ExtractionMethod.GEOMETRY,
                source_block_id=None,
            )
            audit_trail.append(
                AuditEvent(
                    field_name="taxable_total",
                    method=ExtractionMethod.GEOMETRY,
                    confidence=0.88,
                    source_block_id=None,
                    message="Taxable total derived from VAT breakdown rows",
                )
            )

        vat_existing = fields.get("vat_total")
        vat_existing_value = _safe_decimal(vat_existing.normalized_value if vat_existing is not None else None)
        vat_missing_or_empty = (
            vat_existing is None
            or vat_existing.normalized_value is None
            or vat_existing_value is None
            or vat_existing_value <= Decimal("0")
        )
        if vat_missing_or_empty and vat_sum > Decimal("0"):
            fields["vat_total"] = FieldResult(
                name="vat_total",
                raw_value=str(vat_sum),
                normalized_value=vat_sum.quantize(Decimal("0.01")),
                confidence=0.88,
                method=ExtractionMethod.GEOMETRY,
                source_block_id=None,
            )
            audit_trail.append(
                AuditEvent(
                    field_name="vat_total",
                    method=ExtractionMethod.GEOMETRY,
                    confidence=0.88,
                    source_block_id=None,
                    message="VAT total derived from VAT breakdown rows",
                )
            )


def _safe_decimal(value) -> Decimal | None:
    if value is None:
        return None

    try:
        return Decimal(str(value))
    except Exception:
        return None
