import csv
import json
import re
from pathlib import Path

REFERENCE = Path("data/tables/verified-financial-values.json")
TABLE_DIR = Path("data/tables")
OUTPUT = Path("data/processed/table-validation-report.json")

TABLE_FILES = {
    166: TABLE_DIR / "tcs-pdf-page-166-table-1.csv",
    167: TABLE_DIR / "tcs-pdf-page-167-table-3.csv",
}

# Only reviewed label aliases belong here.
ALIASES = {
    "total non-current assets": ["Total non- current assets"],
    "total income": ["TOTAL IN COME"],
    "total expenses": ["TOTAL EX PEN SES"],
    "profit before tax": ["PROFIT BEFORE TAX"],
}


def normalize_label(value):
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def normalize_number(value):
    """Normalize separators only; never infer missing digits."""
    if value is None:
        return None

    text = str(value).strip().replace(",", "").replace(" ", "")

    if not re.fullmatch(r"-?\d+", text):
        return None

    return int(text)


def read_rows(path):
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file))


def find_row(rows, metric):
    target = normalize_label(metric)

    exact = [
        row for row in rows
        if normalize_label(row.get("column_0", "")) == target
    ]
    if exact:
        return exact[0], "EXACT_LABEL"

    for alias in ALIASES.get(metric, []):
        alias_target = normalize_label(alias)
        matches = [
            row for row in rows
            if normalize_label(row.get("column_0", "")) == alias_target
        ]
        if matches:
            return matches[0], "APPROVED_ALIAS"

    # The extracted label merges two distinct balance-sheet rows.
    if metric == "Total assets":
        for row in rows:
            label = normalize_label(row.get("column_0", ""))
            if label == normalize_label("Total current assets TOTAL ASSETS"):
                return row, "MERGED_LABEL_REQUIRES_REVIEW"

    # The profit total is an unlabelled row after the two attribution rows.
    if metric == "Profit for the year":
        for index, row in enumerate(rows):
            label = normalize_label(row.get("column_0", ""))
            if label == normalize_label("Non-controlling interests"):
                if index + 1 < len(rows):
                    candidate = rows[index + 1]
                    if not candidate.get("column_0", "").strip():
                        return candidate, "UNLABELLED_TOTAL_REQUIRES_REVIEW"

    return None, "LABEL_NOT_FOUND"


def main():
    if not REFERENCE.exists():
        raise FileNotFoundError(f"Reference not found: {REFERENCE}")

    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    results = []

    for item in reference["values"]:
        page = item["pdf_page"]
        metric = item["metric"]
        path = TABLE_FILES.get(page)

        if path is None or not path.exists():
            for period in ("fy_2025_26", "fy_2024_25"):
                results.append({
                    "pdf_page": page,
                    "metric": metric,
                    "period": period,
                    "status": "MISSING_TABLE",
                })
            continue

        rows = read_rows(path)
        matched_row, match_method = find_row(rows, metric)

        for period, column in (
            ("fy_2025_26", "column_2"),
            ("fy_2024_25", "column_3"),
        ):
            expected = item[period]
            extracted = (
                normalize_number(matched_row.get(column))
                if matched_row else None
            )

            if match_method in {
                "MERGED_LABEL_REQUIRES_REVIEW",
                "UNLABELLED_TOTAL_REQUIRES_REVIEW",
            }:
                status = match_method
            elif matched_row is None:
                status = "LABEL_NOT_FOUND"
            elif extracted is None:
                status = "VALUE_NOT_NUMERIC"
            elif extracted == expected:
                status = "MATCH"
            else:
                status = "MISMATCH"

            results.append({
                "pdf_page": page,
                "metric": metric,
                "period": period,
                "expected": expected,
                "extracted": extracted,
                "status": status,
                "match_method": match_method,
                "raw_label": (
                    matched_row.get("column_0", "")
                    if matched_row else None
                ),
                "raw_value": (
                    matched_row.get(column, "")
                    if matched_row else None
                ),
            })

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    counts = {}
    for result in results:
        status = result["status"]
        counts[status] = counts.get(status, 0) + 1

    print("=== TABLE VALIDATION SUMMARY ===")
    print(f"Reference metrics: {len(reference['values'])}")
    print(f"Comparisons: {len(results)}")
    for status, count in sorted(counts.items()):
        print(f"{status}: {count}")

    print(f"\nReport saved: {OUTPUT}")
    print("\n=== REVIEW DETAILS ===")
    for result in results:
        if result["status"] != "MATCH":
            print(
                f"Page {result['pdf_page']} | {result['metric']} | "
                f"{result['period']} | {result['status']} | "
                f"raw_label={result.get('raw_label')!r} | "
                f"raw_value={result.get('raw_value')!r}"
            )


if __name__ == "__main__":
    main()
