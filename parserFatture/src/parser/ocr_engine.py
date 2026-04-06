"""Offline OCR extraction for scanned documents."""

from __future__ import annotations

from pathlib import Path

import pytesseract
from pytesseract import Output

from .config import OCRConfig
from .models import BBox, SourceType, Token

try:
    import pypdfium2 as pdfium
except ImportError:  # pragma: no cover - dependency availability is environment-specific
    pdfium = None


class OfflineOCREngine:
    """Extract OCR tokens from PDFs using local Tesseract."""

    def __init__(self, config: OCRConfig):
        self._config = config
        if config.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = config.tesseract_cmd

    def extract_tokens_from_pdf(self, pdf_path: str) -> list[Token]:
        path = Path(pdf_path)
        if not path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        if pdfium is None:
            return []

        tokens: list[Token] = []
        document = pdfium.PdfDocument(str(path))
        scale = self._config.dpi / 72.0

        for page_index in range(len(document)):
            page = document[page_index]
            pil_image = page.render(scale=scale).to_pil()
            width, height = pil_image.size
            if width == 0 or height == 0:
                continue

            data = pytesseract.image_to_data(
                pil_image,
                lang=self._config.language,
                output_type=Output.DICT,
                config="--oem 3 --psm 6",
            )

            total = len(data.get("text", []))
            for i in range(total):
                raw_text = (data["text"][i] or "").strip()
                if not raw_text:
                    continue

                conf = _safe_confidence(data["conf"][i])
                if conf is not None and conf < 0:
                    continue

                x = float(data["left"][i])
                y = float(data["top"][i])
                w = float(data["width"][i])
                h = float(data["height"][i])

                tokens.append(
                    Token(
                        text=raw_text,
                        bbox=BBox(
                            page=page_index + 1,
                            x0=x / width,
                            y0=y / height,
                            x1=(x + w) / width,
                            y1=(y + h) / height,
                        ),
                        source=SourceType.OCR,
                        confidence=(conf / 100.0) if conf is not None else None,
                    )
                )

        return tokens


def _safe_confidence(value: str | int | float) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
