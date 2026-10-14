#!/usr/bin/env python3
"""Run the checked-in TCS QA set against a running Cognora API."""

import argparse
import csv
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ROOT / "eval" / "tcs_questions.jsonl"
REPORT = ROOT / "data" / "pdfs" / "tcs-annual-report-fy2025-26.pdf"


def request(base, path, *, method="GET", data=None, headers=None, timeout=60):
    body = data
    if isinstance(data, (dict, list)):
        body = json.dumps(data).encode()
        headers = {**(headers or {}), "Content-Type": "application/json"}
    req = urllib.request.Request(base.rstrip("/") + path, data=body, headers=headers or {}, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = response.read()
            return json.loads(payload) if payload else {}
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace")[:1000]
        raise RuntimeError(f"API {method} {path} returned {error.code}: {detail}") from error


def upload(base):
    boundary = "----CognoraEvaluationBoundary7MA4YWxkTrZu0gW"
    filename = REPORT.name
    prefix = (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; "
        f"filename=\"{filename}\"\r\nContent-Type: application/pdf\r\n\r\n"
    ).encode()
    content = REPORT.read_bytes()
    body = prefix + content + f"\r\n--{boundary}--\r\n".encode()
    return request(
        base, "/api/documents", method="POST", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"}, timeout=180,
    )


def pages_for(result):
    pages = set()
    for citation in result.get("citations", []):
        try:
            if citation.get("page") is not None:
                pages.add(int(citation["page"]))
        except (TypeError, ValueError):
            continue
    return pages


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000", help="Cognora API origin")
    parser.add_argument("--document-id", help="Use an already processed TCS document ID")
    parser.add_argument("--output", type=Path, default=ROOT / "eval" / "latest-results.csv")
    parser.add_argument("--keep-document", action="store_true", help="Keep the temporary upload after evaluation")
    args = parser.parse_args()

    if not args.document_id and not REPORT.is_file():
        parser.error(f"Public TCS report not found at {REPORT}")
    questions = [json.loads(line) for line in QUESTIONS.read_text(encoding="utf-8").splitlines() if line.strip()]
    document_id = args.document_id
    temporary_document = None
    rows = []
    try:
        if not document_id:
            temporary_document = upload(args.api)
            document_id = temporary_document["id"]
            job = request(args.api, f"/api/documents/{document_id}/process", method="POST")
            deadline = time.monotonic() + 60 * 60
            while True:
                job = request(args.api, f"/api/processing-jobs/{job['id']}")
                status = job.get("status")
                stage = job.get("stage", "")
                print(f"Processing: {status} / {stage}", file=sys.stderr)
                if status == "completed":
                    break
                if status == "failed":
                    raise RuntimeError(f"Document processing failed: {job.get('error')}")
                if time.monotonic() >= deadline:
                    raise TimeoutError("Timed out waiting for document processing")
                time.sleep(3)

        for index, item in enumerate(questions, 1):
            chat = request(args.api, "/api/chats", method="POST", data={"document_id": document_id})
            try:
                result = request(
                    args.api, f"/api/chats/{chat['id']}/messages", method="POST",
                    data={"content": item["question"]}, timeout=300,
                )
            finally:
                request(args.api, f"/api/chats/{chat['id']}", method="DELETE")
            answer = result.get("answer", "")
            answer_ok = bool(re.search(item["answer_regex"], answer, re.I | re.S))
            citation_pages = pages_for(result)
            expected_pages = set(item["pages"])
            citation_ok = bool(citation_pages & expected_pages)
            citation_text = "\n".join(str(c.get("text", "")) for c in result.get("citations", []))
            evidence_ok = bool(re.search(item["answer_regex"], citation_text, re.I | re.S))
            rows.append({
                "id": item["id"], "category": item["category"],
                "answer_correct": answer_ok, "citation_page_correct": citation_ok,
                "citation_evidence_correct": evidence_ok,
                "expected_pages": ";".join(map(str, sorted(expected_pages))),
                "cited_pages": ";".join(map(str, sorted(citation_pages))),
                "answer": answer.replace("\n", " "),
            })
            print(f"[{index:02}/{len(questions)}] {item['id']}: answer={'ok' if answer_ok else 'miss'}, page={'ok' if citation_ok else 'miss'}, evidence={'ok' if evidence_ok else 'miss'}")

        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

        print("\nEvaluation scores (answer regex match; citation page and evidence-anchor coverage)")
        for category in ("text", "table", "chart", "overall"):
            subset = rows if category == "overall" else [r for r in rows if r["category"] == category]
            if not subset:
                continue
            answer_score = sum(r["answer_correct"] for r in subset) / len(subset)
            citation_score = sum(r["citation_page_correct"] for r in subset) / len(subset)
            evidence_score = sum(r["citation_evidence_correct"] for r in subset) / len(subset)
            print(f"{category}: {len(subset)} questions; answer {answer_score:.1%}; citation page {citation_score:.1%}; evidence anchor {evidence_score:.1%}")
        print(f"Detailed results: {args.output}")
    finally:
        if temporary_document and not args.keep_document:
            try:
                request(args.api, f"/api/documents/{temporary_document['id']}", method="DELETE")
                print("Removed temporary evaluation document.", file=sys.stderr)
            except Exception as error:
                print(f"Could not remove temporary evaluation document {temporary_document['id']}: {error}", file=sys.stderr)


if __name__ == "__main__":
    main()
