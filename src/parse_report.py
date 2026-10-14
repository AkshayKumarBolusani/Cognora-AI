import json
from pathlib import Path
from time import perf_counter

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

PDF = Path("data/pdfs/tcs-annual-report-fy2025-26.pdf")
OUT = Path("data/processed")

# Initial validation run: only the two financial statement pages.
START_PAGE = 166
END_PAGE = 167


def main():
    if not PDF.exists():
        raise FileNotFoundError(f"Source PDF not found: {PDF}")

    OUT.mkdir(parents=True, exist_ok=True)

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

    print(f"Parsing PDF pages {START_PAGE}–{END_PAGE}...")
    started = perf_counter()

    result = converter.convert(
        str(PDF),
        page_range=(START_PAGE, END_PAGE),
    )

    document = result.document
    markdown = document.export_to_markdown()
    structured = document.export_to_dict()

    elapsed = perf_counter() - started

    md_path = OUT / f"tcs-pages-{START_PAGE}-{END_PAGE}.md"
    json_path = OUT / f"tcs-pages-{START_PAGE}-{END_PAGE}.json"

    md_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(
        json.dumps(structured, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print("\n--- Verification ---")
    print(f"Elapsed: {elapsed:.1f} seconds")
    print(f"Pages represented: {len(document.pages)}")
    print(f"Markdown characters: {len(markdown):,}")
    print(f"Structured JSON top-level keys: {list(structured.keys())}")
    print(f"Markdown file: {md_path} ({md_path.stat().st_size:,} bytes)")
    print(f"JSON file: {json_path} ({json_path.stat().st_size:,} bytes)")

    assert markdown.strip(), "Markdown output is empty"
    assert len(document.pages) == END_PAGE - START_PAGE + 1, (
        "Unexpected number of pages in output"
    )
    assert json_path.stat().st_size > 0, "Structured JSON is empty"

    print("\nPASS: Markdown and structured JSON saved.")


if __name__ == "__main__":
    main()
