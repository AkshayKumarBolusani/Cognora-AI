
import csv
import json
from collections import defaultdict
from pathlib import Path

SOURCE = Path("data/processed/tcs-pages-166-167.json")
OUTPUT_DIR = Path("data/tables")


def main():
    if not SOURCE.exists():
        raise FileNotFoundError(f"Missing input: {SOURCE}")

    data = json.loads(SOURCE.read_text(encoding="utf-8"))
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    tables = data.get("tables", [])
    if not tables:
        raise ValueError("No tables found in the input JSON.")

    for table_index, table in enumerate(tables, start=1):
        provenance = table.get("prov", [])
        page_no = (
            provenance[0].get("page_no", "unknown")
            if provenance else "unknown"
        )

        cells = table.get("data", {}).get("table_cells", [])
        rows = defaultdict(dict)

        for cell in cells:
            row_index = cell.get("start_row_offset_idx", 0)
            col_index = cell.get("start_col_offset_idx", 0)
            rows[row_index][col_index] = cell.get("text", "")

        max_col = max(
            (col for row in rows.values() for col in row),
            default=-1,
        )

        output_path = OUTPUT_DIR / (
            f"tcs-pdf-page-{page_no}-table-{table_index}.csv"
        )

        with output_path.open(
            "w", newline="", encoding="utf-8-sig"
        ) as f:
            writer = csv.writer(f)
            writer.writerow(
                ["source_pdf_page", "table_index"]
                + [f"column_{i}" for i in range(max_col + 1)]
            )

            for row_index in sorted(rows):
                values = [
                    rows[row_index].get(col, "")
                    for col in range(max_col + 1)
                ]
                writer.writerow([page_no, table_index, *values])

        print(
            f"Saved {output_path} | "
            f"PDF page {page_no} | "
            f"{len(rows)} rows | {len(cells)} cells"
        )

    print("\nPASS: Table CSV exports completed.")


if __name__ == "__main__":
    main()

