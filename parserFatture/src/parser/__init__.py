"""Core parser package used by the main gestionale app."""

from .pipeline import InvoiceParserPipeline

_PIPELINE: InvoiceParserPipeline | None = None


def get_pipeline() -> InvoiceParserPipeline:
	"""Return a shared pipeline instance for repeated parsing calls."""
	global _PIPELINE
	if _PIPELINE is None:
		_PIPELINE = InvoiceParserPipeline()
	return _PIPELINE


def parse_invoice_pdf(pdf_path: str):
	"""Headless API entrypoint used by the main application."""
	return get_pipeline().parse_pdf(pdf_path)


__all__ = ["InvoiceParserPipeline", "get_pipeline", "parse_invoice_pdf"]
