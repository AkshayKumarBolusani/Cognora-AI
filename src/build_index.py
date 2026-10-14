
import hashlib
import json
import os
import re
import time
from collections import defaultdict
from pathlib import Path

import ollama
import tiktoken
from qdrant_client import QdrantClient, models

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data/processed/normalized/elements.jsonl"
DB_PATH = ROOT / "data/vector_db"

COLLECTION = "tcs_annual_report_v1"
EMBED_MODEL = "nomic-embed-text"
BATCH_SIZE = 32
CHUNK_TOKENS = 450
OVERLAP = 60

tokenizer = tiktoken.get_encoding("cl100k_base")


def clean(text):
    return re.sub(r"\s+", " ", text or "").strip()


def extract_strings(value, output):
    """Collect text-like fields from nested table structures."""
    if isinstance(value, dict):
        for key, item in value.items():
            if key.lower() in {"text", "content", "label"}:
                if isinstance(item, str) and item.strip():
                    output.append(item.strip())
                elif isinstance(item, (dict, list)):
                    extract_strings(item, output)
            elif isinstance(item, (dict, list)):
                extract_strings(item, output)
    elif isinstance(value, list):
        for item in value:
            extract_strings(item, output)


def table_to_text(element):
    parts = []
    extract_strings(element, parts)
    # Preserve order but remove repeated strings.
    return " | ".join(dict.fromkeys(parts))


def split_chunks(text):
    tokens = tokenizer.encode(text)
    chunks = []
    start = 0

    while start < len(tokens):
        end = min(start + CHUNK_TOKENS, len(tokens))
        chunk = tokenizer.decode(tokens[start:end]).strip()

        if chunk:
            chunks.append(chunk)

        if end >= len(tokens):
            break

        start = end - OVERLAP

    return chunks


def load_documents():
    by_page = defaultdict(list)
    standalone = []

    with INPUT.open(encoding="utf-8") as file:
        for line in file:
            record = json.loads(line)
            kind = record.get("element_type")
            element = record.get("element", {})
            page = record.get("page_number")

            if kind == "text":
                text = clean(record.get("text", ""))
            elif kind == "table":
                text = clean(table_to_text(element))
            elif kind == "picture":
                captions = element.get("captions", [])
                caption_text = []
                for caption in captions:
                    if isinstance(caption, str):
                        caption_text.append(caption)
                    elif isinstance(caption, dict):
                        caption_text.append(caption.get("text", ""))
                text = clean(" ".join(caption_text))
            else:
                continue

            if len(text) < 20:
                continue

            provenance = record.get("provenance", [])
            bbox = provenance[0].get("bbox", {}) if provenance else {}

            doc = {
                "text": text,
                "page": page,
                "type": kind,
                "source": record.get("source_file", "TCS Annual Report"),
                "element_id": record.get("id"),
                "bbox": bbox,
            }

            if kind == "text" and page is not None:
                # Docling coordinates originate at bottom-left.
                # Sort top-to-bottom, then left-to-right.
                by_page[page].append(doc)
            else:
                standalone.append(doc)

    documents = []

    for page, elements in sorted(by_page.items()):
        elements.sort(
            key=lambda item: (
                -item["bbox"].get("t", 0),
                item["bbox"].get("l", 0),
            )
        )
        page_text = "\n".join(item["text"] for item in elements)

        for index, chunk in enumerate(split_chunks(page_text)):
            documents.append({
                "text": chunk,
                "page": page,
                "type": "text",
                "source": "TCS Integrated Annual Report FY2025-26",
                "element_id": f"page-{page}-chunk-{index}",
            })

    for doc in standalone:
        for index, chunk in enumerate(split_chunks(doc["text"])):
            documents.append({**doc, "text": chunk, "chunk_index": index})

    # Stable integer IDs allow safe upserts on a rerun.
    for doc in documents:
        key = (
            f'{doc.get("page")}:{doc.get("type")}:'
            f'{doc.get("element_id")}:{doc.get("chunk_index", 0)}:'
            f'{doc["text"]}'
        )
        doc["id"] = int(
            hashlib.sha256(key.encode()).hexdigest()[:15], 16
        )

    return documents


def main():
    if not INPUT.exists():
        raise SystemExit(f"Missing input: {INPUT}")

    print("Preparing documents...")
    documents = load_documents()
    print(f"Prepared {len(documents)} chunks")

    if not documents:
        raise SystemExit("No chunks found.")

    db = QdrantClient(path=str(DB_PATH))

    if db.collection_exists(COLLECTION):
        print(
            f"Collection {COLLECTION!r} already exists. "
            "Use the existing index or change COLLECTION to build a new one."
        )
        db.close()
        return

    print("Checking local embedding model...")
    test = ollama.embed(model=EMBED_MODEL, input=["test"])
    dimension = len(test["embeddings"][0])
    print(f"Embedding dimension: {dimension}")

    db.create_collection(
        collection_name=COLLECTION,
        vectors_config=models.VectorParams(
            size=dimension,
            distance=models.Distance.COSINE,
        ),
    )

    started = time.time()

    for start in range(0, len(documents), BATCH_SIZE):
        batch = documents[start:start + BATCH_SIZE]

        response = ollama.embed(
            model=EMBED_MODEL,
            input=[doc["text"] for doc in batch],
        )

        points = []
        for doc, vector in zip(batch, response["embeddings"]):
            points.append(
                models.PointStruct(
                    id=doc["id"],
                    vector=vector,
                    payload=doc,
                )
            )

        db.upsert(collection_name=COLLECTION, points=points)

        print(
            f"Indexed {min(start + len(batch), len(documents))}"
            f"/{len(documents)}"
        )

    print("\nINDEX COMPLETE")
    print(f"Chunks: {len(documents)}")
    print(f"Collection: {COLLECTION}")
    print(f"Database: {DB_PATH}")
    print(f"Elapsed: {(time.time() - started) / 60:.1f} minutes")
    print("Note: figure images without captions are not yet searchable.")

    db.close()


if __name__ == "__main__":
    main()
