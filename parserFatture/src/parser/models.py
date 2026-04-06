"""Typed models used across the parser pipeline."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class SourceType(str, Enum):
    PDF_TEXT = "pdf_text"
    OCR = "ocr"


class BlockType(str, Enum):
    TEXT_LINE = "text_line"
    TEXT_BLOCK = "text_block"
    TABLE_ROW = "table_row"
    TABLE_BLOCK = "table_block"


class ExtractionMethod(str, Enum):
    GEOMETRY = "geometry"
    REGEX = "regex"
    MANUAL = "manual"


class DocumentType(str, Enum):
    DIGITAL_PDF = "digital_pdf"
    SCANNED_DOCUMENT = "scanned_document"


class BBox(BaseModel):
    model_config = ConfigDict(extra="forbid")

    page: int
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    @property
    def center_x(self) -> float:
        return self.x0 + (self.width / 2.0)

    @property
    def center_y(self) -> float:
        return self.y0 + (self.height / 2.0)


class Token(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str
    bbox: BBox
    source: SourceType
    confidence: float | None = None


class Block(BaseModel):
    model_config = ConfigDict(extra="forbid")

    block_id: str
    block_type: BlockType
    bbox: BBox
    tokens: list[Token] = Field(default_factory=list)
    confidence: float = 1.0

    def text(self) -> str:
        return " ".join(token.text for token in self.tokens).strip()


class AuditEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_name: str
    method: ExtractionMethod
    confidence: float
    message: str
    source_block_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class FieldResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    raw_value: str | None = None
    normalized_value: Any = None
    confidence: float = 0.0
    method: ExtractionMethod | None = None
    source_block_id: str | None = None
    requires_confirmation: bool = False


class LineItemResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    description: str
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    vat_rate: Decimal | None = None
    line_total: Decimal | None = None
    confidence: float = 0.0


class VATBreakdownRow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    vat_rate: Decimal
    taxable_amount: Decimal | None = None
    tax_amount: Decimal | None = None
    total_with_tax: Decimal | None = None
    confidence: float = 0.0


class InvoiceResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    document_path: str
    original_filename: str
    document_type: DocumentType
    fields: dict[str, FieldResult] = Field(default_factory=dict)
    structure: dict[str, list[str]] = Field(default_factory=dict)
    line_items: list[LineItemResult] = Field(default_factory=list)
    vat_breakdown: list[VATBreakdownRow] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    audit_trail: list[AuditEvent] = Field(default_factory=list)

    def as_export_dict(self) -> dict[str, Any]:
        """Flatten key fields for quick JSON/CSV export."""
        payload: dict[str, Any] = {
            "document_path": self.document_path,
            "original_filename": self.original_filename,
            "document_type": self.document_type.value,
            "structure": self.structure,
            "warnings": self.warnings,
        }
        for key, field in self.fields.items():
            payload[key] = field.normalized_value if field.normalized_value is not None else field.raw_value
            payload[f"{key}_confidence"] = field.confidence
            payload[f"{key}_requires_confirmation"] = field.requires_confirmation

        payload["purchased_products"] = [
            {
                "description": line.description,
                "quantity": str(line.quantity),
                "total_price": str(line.line_total),
            }
            for line in self.line_items
            if _is_positive_decimal(line.quantity) and _is_positive_decimal(line.line_total)
        ]
        payload["line_items"] = [line.model_dump(mode="json") for line in self.line_items]
        payload["vat_breakdown"] = [row.model_dump(mode="json") for row in self.vat_breakdown]
        payload["audit_trail"] = [event.model_dump(mode="json") for event in self.audit_trail]
        return payload


def _is_positive_decimal(value: Decimal | None) -> bool:
    return value is not None and value > Decimal("0")
