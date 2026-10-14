import json
from pathlib import Path

import pymupdf

ROOT = Path.cwd()
PDF = ROOT / "data/pdfs/tcs-annual-report-fy2025-26.pdf"
JSON_DIR = ROOT / "data/processed/full_report"
OUT_DIR = ROOT / "data/processed/figure_crops"
OUT_DIR.mkdir(parents=True, exist_ok=True)

doc = pymupdf.open(PDF)
count = 0
skipped = 0

for json_file in sorted(JSON_DIR.glob("*.json")):
    try:
        data = json.loads(json_file.read_text())
    except Exception as exc:
        print(f"Skipping {json_file.name}: {exc}")
        continue

    for idx, picture in enumerate(data.get("pictures", [])):
        prov = picture.get("prov") or []
        if not prov:
            skipped += 1
            continue

        p = prov[0]
        page_no = p.get("page_no")
        bbox = p.get("bbox", {})

        if page_no is None:
            skipped += 1
            continue

        # Docling page numbers are 1-based; PyMuPDF is 0-based.
        page_idx = int(page_no) - 1
        if not 0 <= page_idx < len(doc):
            skipped += 1
            continue

        page = doc[page_idx]
        rect = pymupdf.Rect(
            bbox["l"],
            page.rect.height - bbox["t"],
            bbox["r"],
            page.rect.height - bbox["b"],
        )
        rect = rect & page.rect

        if rect.is_empty or rect.width < 2 or rect.height < 2:
            skipped += 1
            continue

        pix = page.get_pixmap(
            matrix=pymupdf.Matrix(2, 2),
            clip=rect,
            alpha=False,
        )

        out = OUT_DIR / f"page_{page_no:03d}_picture_{idx:03d}.png"
        pix.save(out)
        count += 1

doc.close()
print(f"Extracted: {count} crops")
print(f"Skipped: {skipped}")
print(f"Output: {OUT_DIR}")
