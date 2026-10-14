
from pathlib import Path
from docling.document_converter import DocumentConverter


def extract_document_text(file_path: str | Path) -> str:
    """Extract readable text from a PDF or supported document."""
    converter = DocumentConverter()
    result = converter.convert(str(file_path))
    return result.document.export_to_markdown()
