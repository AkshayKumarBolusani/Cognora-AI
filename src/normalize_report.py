
import json
from pathlib import Path
from collections import Counter

INPUT_DIR = Path("data/processed/full_report")
OUTPUT_DIR = Path("data/processed/normalized")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

OUTPUT_FILE = OUTPUT_DIR / "elements.jsonl"
SUMMARY_FILE = OUTPUT_DIR / "normalization_summary.json"

stats = Counter()
pages_seen = set()
errors = []

with OUTPUT_FILE.open("w", encoding="utf-8") as out:
    for json_path in sorted(INPUT_DIR.glob("pages-*.json")):
        try:
            document = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append({"file": json_path.name, "error": str(exc)})
            continue

        source_name = document.get("name", json_path.stem)

        for element_type in ("texts", "tables", "pictures"):
            elements = document.get(element_type, [])

            for index, element in enumerate(elements):
                provenance = element.get("prov") or []

                page_numbers = sorted({
                    p["page_no"]
                    for p in provenance
                    if isinstance(p, dict) and p.get("page_no") is not None
                })

                for page_no in page_numbers:
                    pages_seen.add(page_no)

                record = {
                    "id": f"{json_path.stem}:{element_type}:{index}",
                    "element_type": element_type.rstrip("s"),
                    "source_file": source_name,
                    "batch_file": json_path.name,
                    "page_numbers": page_numbers,
                    "page_number": page_numbers[0] if page_numbers else None,
                    "text": element.get("text", ""),
                    "provenance": provenance,
                    "element": element,
                }

                out.write(
                    json.dumps(record, ensure_ascii=False) + "\n"
                )
                stats[element_type] += 1

        for page_id, page_info in document.get("pages", {}).items():
            page_no = page_info.get("page_no")
            if page_no is not None:
                pages_seen.add(page_no)

summary = {
    "input_directory": str(INPUT_DIR),
    "output_file": str(OUTPUT_FILE),
    "batches_found": len(list(INPUT_DIR.glob("pages-*.json"))),
    "pages_seen": len(pages_seen),
    "page_numbers": sorted(pages_seen),
    "elements_by_type": dict(stats),
    "total_elements": sum(stats.values()),
    "errors": errors,
}

SUMMARY_FILE.write_text(
    json.dumps(summary, indent=2, ensure_ascii=False),
    encoding="utf-8",
)

print("=== NORMALIZATION SUMMARY ===")
print(json.dumps(summary, indent=2, ensure_ascii=False))
print(f"\nSaved records to: {OUTPUT_FILE}")
print(f"Saved summary to: {SUMMARY_FILE}")

if not errors and len(pages_seen) == 360:
    print("PASS: All 360 pages accounted for.")
elif errors:
    print("WARNING: Some input files could not be processed.")
else:
    print("WARNING: Expected 360 pages; verify page coverage.")
