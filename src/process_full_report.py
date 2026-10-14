import json
import time
from pathlib import Path

from docling.datamodel.base_models import InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.document_converter import DocumentConverter, PdfFormatOption

PDF = Path("data/pdfs/tcs-annual-report-fy2025-26.pdf")
OUT = Path("data/processed/full_report")
BATCH_SIZE = 10
TOTAL_PAGES = 360


def main():
    if not PDF.exists():
        raise FileNotFoundError(f"PDF not found: {PDF}")

    OUT.mkdir(parents=True, exist_ok=True)

    options = PdfPipelineOptions()
    options.do_ocr = False
    options.do_table_structure = True

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(
                pipeline_options=options
            )
        }
    )

    started = time.time()
    completed = 0
    failed = []

    for start in range(1, TOTAL_PAGES + 1, BATCH_SIZE):
        end = min(start + BATCH_SIZE - 1, TOTAL_PAGES)
        json_path = OUT / f"pages-{start:03d}-{end:03d}.json"
        md_path = OUT / f"pages-{start:03d}-{end:03d}.md"

        if json_path.exists() and md_path.exists():
            try:
                existing = json.loads(
                    json_path.read_text(encoding="utf-8")
                )
                if existing.get("pages"):
                    print(f"SKIP pages {start}-{end}: already saved")
                    completed += end - start + 1
                    continue
            except (json.JSONDecodeError, OSError):
                pass

        print(f"\nProcessing PDF pages {start}-{end}...", flush=True)

        try:
            result = converter.convert(
                str(PDF),
                page_range=(start, end),
            )
            document = result.document
            structured = document.export_to_dict()
            markdown = document.export_to_markdown()

            if not structured.get("pages") or not markdown.strip():
                raise ValueError("Empty page or Markdown output")

            json_tmp = json_path.with_suffix(".json.tmp")
            md_tmp = md_path.with_suffix(".md.tmp")

            json_tmp.write_text(
                json.dumps(structured, ensure_ascii=False),
                encoding="utf-8",
            )
            md_tmp.write_text(markdown, encoding="utf-8")

            json_tmp.replace(json_path)
            md_tmp.replace(md_path)

            print(
                f"Saved pages {start}-{end} | "
                f"{len(structured.get('tables', []))} tables | "
                f"{len(structured.get('pictures', []))} pictures | "
                f"{json_path.stat().st_size:,} JSON bytes",
                flush=True,
            )
            completed += end - start + 1

        except Exception as exc:
            failed.append((start, end, str(exc)))
            print(f"FAILED pages {start}-{end}: {exc}", flush=True)

    print("\n=== PROCESSING SUMMARY ===")
    print(f"Pages accounted for: {completed}/{TOTAL_PAGES}")
    print(f"Failed batches: {len(failed)}")
    print(f"Output directory: {OUT}")
    print(f"Elapsed: {(time.time() - started) / 60:.1f} minutes")

    if failed:
        failure_path = OUT / "failed-batches.json"
        failure_path.write_text(
            json.dumps(
                [
                    {"start": s, "end": e, "error": err}
                    for s, e, err in failed
                ],
                indent=2,
            ),
            encoding="utf-8",
        )
        print(f"Failures recorded in: {failure_path}")
    else:
        print("PASS: All batches saved.")


if __name__ == "__main__":
    main()
