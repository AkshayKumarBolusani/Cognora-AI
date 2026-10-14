from pathlib import Path
from time import perf_counter

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

pdf = Path("data/pdfs/tcs-annual-report-fy2025-26.pdf")
assert pdf.exists(), f"PDF not found: {pdf}"

options = PdfPipelineOptions()
options.do_ocr = False
options.do_table_structure = True

converter = DocumentConverter(
    format_options={
        InputFormat.PDF: PdfFormatOption(
            pipeline_options=options,
        )
    }
)

print("Testing financial statements: PDF pages 166–167")
start = perf_counter()

result = converter.convert(str(pdf), page_range=(166, 167))
document = result.document
markdown = document.export_to_markdown()

elapsed = perf_counter() - start

output = Path("data/processed/financial-tables-test.md")
output.parent.mkdir(parents=True, exist_ok=True)
output.write_text(markdown, encoding="utf-8")

table_lines = [
    line for line in markdown.splitlines()
    if "|" in line
]

print(f"\nElapsed: {elapsed:.1f} seconds")
print(f"Pages represented: {len(document.pages)}")
print(f"Markdown characters: {len(markdown):,}")
print(f"Lines containing table separators: {len(table_lines)}")
print(f"Saved: {output.resolve()}")

print("\n--- Extracted Markdown preview ---")
print(markdown[:5000])

assert markdown.strip(), "Empty Markdown output"
print("\nPASS: Financial-page extraction completed.")
