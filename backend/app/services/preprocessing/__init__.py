"""Local ZRDDS document preprocessing primitives.

This package deliberately stops at producing a local, validated document set.
It has no knowledge-base or Dify integration.
"""

from app.services.preprocessing.pdfplumber_parser import ParsedDocument, parse_pdf

__all__ = ["ParsedDocument", "parse_pdf"]
