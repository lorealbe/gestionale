"""PDF text extraction with token-level geometry."""

from __future__ import annotations

from pathlib import Path

import pdfplumber

from .models import BBox, SourceType, Token


class PDFTokenExtractor:
    """Extract words and their normalized bounding boxes from digital PDFs."""

    def extract_tokens(self, pdf_path: str) -> list[Token]:
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        extracted: list[Token] = []
        with pdfplumber.open(path) as pdf:
            for page_number, page in enumerate(pdf.pages, start=1):
                width = float(page.width) or 1.0
                height = float(page.height) or 1.0
                words = page.extract_words(
                    keep_blank_chars=False,
                    use_text_flow=True,
                    x_tolerance=2,
                    y_tolerance=2,
                )
                for word in words:
                    text = (word.get("text") or "").strip()
                    if not text:
                        continue

                    x0 = float(word.get("x0", 0.0)) / width
                    x1 = float(word.get("x1", 0.0)) / width
                    y0 = float(word.get("top", 0.0)) / height
                    y1 = float(word.get("bottom", 0.0)) / height

                    extracted.append(
                        Token(
                            text=text,
                            bbox=BBox(page=page_number, x0=x0, y0=y0, x1=x1, y1=y1),
                            source=SourceType.PDF_TEXT,
                            confidence=None,
                        )
                    )

        return extracted
