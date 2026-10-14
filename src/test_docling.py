from pathlib import Path
from time import perf_counter

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

pdf = Path("data/pdfs/tcs-annual-report-fy2025-26.pdf")
assert pdf.exists(), f"PDF not found: {pdf}"

options = PdfPipelineOptions()
options.do_ocr = False
options.do_table_structure = False

converter = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(
            pipeline_options=options,
        )
    }
)

print("Starting OCR-free test on pages 3–5...")
start = perf_counter()

result = converter.convert(
    str(pdf),
    page_range=(3, 5),
)

elapsed = perf_counter() - start
document = result.document
markdown = document.export_to_markdown()

print(f"Elapsed: {elapsed:.1f} seconds")
print(f"Pages represented in output: {len(document.pages)}")
print(f"Markdown characters: {len(markdown):,}")
print("\nPreview:")
print(markdown[:1200])

assert markdown.strip(), "Docling returned empty Markdown"

out = Path("data/processed/docling-test-pages-3-5.md")
out.parent.mkdir(parents=True, exist_ok=True)
out.write_text(markdown, encoding="utf-8")

print(f"\nPASS: Saved test output to {out}")
