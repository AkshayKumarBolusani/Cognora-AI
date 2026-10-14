"""Document scoped indexing and retrieval for uploaded documents.

Each uploaded document gets its own collection. The existing TCS report
collection is intentionally left untouched because it has no upload IDs.
"""

import hashlib
import os
import re
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")
VECTOR_DIR = ROOT / "data" / "vector_db"
COLLECTION_PREFIX = "cognora_doc_v3_"


def _collection(document_id: str, text: str) -> str:
    safe_id = re.sub(r"[^a-zA-Z0-9]", "", document_id)
    model = os.getenv("EMBEDDING_MODEL", "nomic-embed-text").strip()
    provider = os.getenv("EMBEDDING_PROVIDER", "ollama").strip().lower()
    model_signature = hashlib.sha256(f"{provider}:{model}".encode()).hexdigest()[:8]
    content_signature = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return f"{COLLECTION_PREFIX}{safe_id}_{model_signature}_{content_signature}"


def _legacy_collection(document_id: str, text: str) -> str:
    """Name used by the previous text-only index schema, for read-only fallback."""
    safe_id = re.sub(r"[^a-zA-Z0-9]", "", document_id)
    model = os.getenv("EMBEDDING_MODEL", "nomic-embed-text").strip()
    provider = os.getenv("EMBEDDING_PROVIDER", "ollama").strip().lower()
    model_signature = hashlib.sha256(f"{provider}:{model}".encode()).hexdigest()[:8]
    content_signature = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return f"cognora_doc_{safe_id}_{model_signature}_{content_signature}"


def _v2_collection(document_id: str, text: str) -> str:
    """Previous vector-only index schema, retained for read-only migration fallback."""
    safe_id = re.sub(r"[^a-zA-Z0-9]", "", document_id)
    model = os.getenv("EMBEDDING_MODEL", "nomic-embed-text").strip()
    provider = os.getenv("EMBEDDING_PROVIDER", "ollama").strip().lower()
    model_signature = hashlib.sha256(f"{provider}:{model}".encode()).hexdigest()[:8]
    content_signature = hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]
    return f"cognora_doc_v2_{safe_id}_{model_signature}_{content_signature}"


def _chunks(text: str, max_chars: int = 1800, overlap: int = 250):
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    blocks = re.split(r"(?<=[.!?])\s+|\n\n+", text)
    chunks, current = [], ""
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if current and len(current) + len(block) + 1 > max_chars:
            chunks.append(current)
            current = current[-overlap:] + " " + block
        else:
            current = f"{current}\n{block}".strip()
    if current:
        chunks.append(current)
    return chunks


def _element_chunks(elements: list[dict], max_chars: int = 1800, overlap: int = 250):
    """Chunk extracted elements without losing their page/type/source identity."""
    chunks = []
    for element in elements:
        text = str(element.get("text") or "").strip()
        if not text:
            continue
        for part_index, chunk in enumerate(_chunks(text, max_chars, overlap)):
            chunks.append({
                **element,
                "text": chunk,
                # Keep the original table verbatim for answers/citations while
                # giving the embedding model its column names and row meaning.
                "embedding_text": _table_embedding_text(chunk)
                if str(element.get("type", "")).casefold() == "table" else chunk,
                "chunk_index": part_index,
            })
    return chunks


def _table_embedding_text(text: str) -> str:
    """Add a compact, deterministic table summary to the embedding input."""
    rows = [[cell.strip() for cell in line.strip().strip("|").split("|")]
            for line in text.splitlines() if "|" in line]
    if not rows:
        return text
    headers = rows[0]
    headers = [value for value in headers if value and not re.fullmatch(r"[-: ]+", value)]
    if not headers:
        return text
    summary = "Table with columns: " + ", ".join(headers) + "."
    return f"{summary}\n{text}"


def _lexical_score(query: str, text: str) -> float:
    """Small BM25-style term score, normalized for reciprocal-rank fusion."""
    terms = re.findall(r"[\w.%-]+", query.casefold())
    words = re.findall(r"[\w.%-]+", text.casefold())
    if not terms or not words:
        return 0.0
    counts = {}
    for word in words:
        counts[word] = counts.get(word, 0) + 1
    unique = set(terms)
    score = sum((1.0 + counts.get(term, 0)) / (1.0 + 0.35 * len(words) / 1000) for term in unique)
    return score


def _embed(texts: list[str]) -> list[list[float]]:
    """Embed configurable, bounded batches to reduce request overhead safely."""
    vectors = []
    try:
        batch_size = int(os.getenv("EMBEDDING_BATCH_SIZE", "16"))
    except ValueError:
        batch_size = 16
    batch_size = max(1, min(batch_size, 64))
    for start in range(0, len(texts), batch_size):
        batch = _embed_batch(texts[start:start + batch_size])
        if len(batch) != min(batch_size, len(texts) - start):
            raise ValueError("Embedding provider returned an unexpected number of vectors.")
        vectors.extend(batch)
    return vectors


def _embed_batch(texts: list[str]) -> list[list[float]]:
    import httpx

    provider = os.getenv("EMBEDDING_PROVIDER", "ollama").strip().lower()
    model = os.getenv("EMBEDDING_MODEL", "nomic-embed-text").strip()
    base = os.getenv("EMBEDDING_BASE_URL", "").strip().rstrip("/")
    timeout = httpx.Timeout(120, connect=10)

    if provider == "ollama":
        base = base or "http://localhost:11434"
        response = httpx.post(
            f"{base}/api/embed", json={"model": model, "input": texts}, timeout=timeout
        )
        # Older Ollama releases expose /api/embeddings (singular) instead of
        # /api/embed. Fall back only for endpoint/payload compatibility errors.
        if response.status_code in {404, 405} or (
            response.status_code == 400
            and any(term in response.text.lower() for term in ("unknown field", "invalid input", "cannot unmarshal"))
        ):
            legacy_results = []
            for text in texts:
                legacy = httpx.post(
                    f"{base}/api/embeddings",
                    json={"model": model, "prompt": text},
                    timeout=timeout,
                )
                if legacy.is_error:
                    break
                legacy_results.append(legacy.json().get("embedding", []))
            if len(legacy_results) == len(texts) and all(legacy_results):
                return legacy_results
        if response.is_error:
            detail = response.text.strip().replace("\n", " ")[:500]
            if "does not support embeddings" in detail.lower():
                raise RuntimeError(
                    f"Ollama model '{model}' cannot create embeddings. Configure an embedding model "
                    "such as nomic-embed-text in EMBEDDING_MODEL, then retry processing. "
                    f"Ollama said: {detail}"
                )
            if "not found" in detail.lower():
                raise RuntimeError(
                    f"Ollama embedding model '{model}' is not installed. Run `ollama pull {model}`, "
                    f"then retry processing. Ollama said: {detail}"
                )
            raise RuntimeError(f"Ollama embedding request failed ({response.status_code}): {detail}")
        return response.json().get("embeddings", [])
    if provider == "openai":
        key = os.getenv("EMBEDDING_API_KEY", "").strip()
        if not key:
            raise ValueError("EMBEDDING_API_KEY is required for OpenAI embeddings.")
        base = base if base and not base.startswith("http://localhost:11434") else "https://api.openai.com/v1"
        response = httpx.post(
            f"{base}/embeddings",
            headers={"Authorization": f"Bearer {key}"},
            json={"model": model, "input": texts}, timeout=timeout,
        )
        response.raise_for_status()
        return [item["embedding"] for item in response.json()["data"]]
    if provider == "gemini":
        key = os.getenv("EMBEDDING_API_KEY", "").strip()
        if not key:
            raise ValueError("EMBEDDING_API_KEY is required for Gemini embeddings.")
        base = base if base and not base.startswith("http://localhost:11434") else "https://generativelanguage.googleapis.com/v1beta"
        response = httpx.post(
            f"{base}/models/{model}:batchEmbedContents",
            headers={"x-goog-api-key": key},
            json={"requests": [{"model": f"models/{model}", "content": {"parts": [{"text": text}]}}
                  for text in texts]},
            timeout=timeout,
        )
        response.raise_for_status()
        return [item["embedding"]["values"] for item in response.json()["embeddings"]]
    raise ValueError(f"Unsupported embedding provider '{provider}'. Use ollama, openai, or gemini.")


def has_index(document_id: str, text: str) -> bool:
    """Read-only readiness check for current and legacy per-document indexes."""
    from qdrant_client import QdrantClient

    client = QdrantClient(path=str(VECTOR_DIR))
    try:
        for collection in (_collection(document_id, text), _v2_collection(document_id, text),
                           _legacy_collection(document_id, text)):
            if client.collection_exists(collection):
                return client.count(collection_name=collection, exact=True).count > 0
        return False
    finally:
        client.close()


def delete_document_indexes(document_id: str) -> list[str]:
    """Delete only collections whose names are scoped to this uploaded document."""
    from qdrant_client import QdrantClient

    safe_id = re.sub(r"[^a-zA-Z0-9]", "", document_id)
    prefixes = (f"{COLLECTION_PREFIX}{safe_id}_", f"cognora_doc_v2_{safe_id}_",
                f"cognora_doc_{safe_id}_", f"cognora_doc_{safe_id}")
    client = QdrantClient(path=str(VECTOR_DIR))
    removed = []
    try:
        for item in client.get_collections().collections:
            name = item.name
            if name.startswith(prefixes):
                client.delete_collection(collection_name=name)
                removed.append(name)
    finally:
        client.close()
    return removed


def index_document(
    document_id: str, document_name: str, text: str,
    elements: list[dict] | None = None,
) -> int:
    from qdrant_client import QdrantClient, models

    collection = _collection(document_id, text)
    chunks = _element_chunks(elements) if elements else [
        {"text": chunk, "page": None, "type": "text", "element_id": f"chunk-{i}", "chunk_index": 0}
        for i, chunk in enumerate(_chunks(text))
    ]
    if not chunks:
        raise ValueError("No readable text was available to index.")
    client = QdrantClient(path=str(VECTOR_DIR))
    try:
        if client.collection_exists(collection):
            # A matching immutable index already exists. Never recreate or delete it.
            existing_count = client.count(collection, exact=True).count
            if existing_count != len(chunks):
                raise RuntimeError(
                    f"An incomplete index already exists for this document ({existing_count} "
                    f"of {len(chunks)} chunks). It was preserved; choose a new index version "
                    "after inspecting the partial collection."
                )
            return existing_count
        # Qdrant payload chunks carry provenance metadata; embedding APIs accept
        # text values only. Keep metadata on the points, not in the model input.
        vectors = _embed([chunk.get("embedding_text", chunk["text"]) for chunk in chunks])
        if len(vectors) != len(chunks):
            raise ValueError(f"Embedding provider returned {len(vectors)} vectors for {len(chunks)} chunks.")
        if not vectors or not vectors[0]:
            raise ValueError("Embedding provider returned an empty vector.")
        dimension = len(vectors[0])
        if any(len(vector) != dimension for vector in vectors):
            raise ValueError("Embedding provider returned inconsistent vector dimensions.")
        client.create_collection(
            collection_name=collection,
            vectors_config=models.VectorParams(size=dimension, distance=models.Distance.COSINE),
        )
        points = []
        for index, (chunk, vector) in enumerate(zip(chunks, vectors)):
            element_id = str(chunk.get("element_id") or f"chunk-{index}")
            stable_id = int(hashlib.sha256(
                f"{document_id}:{element_id}:{chunk.get('chunk_index', 0)}:{index}".encode()
            ).hexdigest()[:15], 16)
            points.append(models.PointStruct(
                id=stable_id,
                vector=vector,
                payload={**chunk, "document_id": document_id,
                         "document_name": document_name, "element_id": element_id,
                         "page": chunk.get("page"), "type": chunk.get("type", "text"),
                         "text": chunk["text"], "chunk_index": index},
            ))
        client.upsert(collection_name=collection, points=points)
    finally:
        client.close()
    return len(chunks)


def retrieve(
    document_id: str, question: str, source_text: str,
    top_k: int = 5, threshold: float = 0.15,
):
    from qdrant_client import QdrantClient

    collection = _collection(document_id, source_text)
    client = QdrantClient(path=str(VECTOR_DIR)
    )
    try:
        if not client.collection_exists(collection):
            collection = next((candidate for candidate in (
                _v2_collection(document_id, source_text),
                _legacy_collection(document_id, source_text),
            ) if client.collection_exists(candidate)), None)
            if collection is None:
                return []
        query_vector = _embed([question])[0]
        expected_size = client.get_collection(collection).config.params.vectors.size
        if len(query_vector) != expected_size:
            raise ValueError(
                f"Embedding dimension mismatch: configured model returns {len(query_vector)} "
                f"values but this document index requires {expected_size}. Reprocess it "
                "with the configured embedding model."
            )
        vector_results = client.query_points(
            collection_name=collection, query=query_vector, limit=max(top_k * 4, 20),
            with_payload=True,
        ).points
        # Compatibility for older Qdrant client shims that only expose vector search.
        if not hasattr(client, "scroll"):
            return [point.payload for point in vector_results
                    if point.payload.get("document_id") == document_id][:top_k]
        # BM25-style lexical candidates catch exact names, dates, and amounts
        # that vector similarity can rank poorly. RRF combines both lists.
        points, _ = client.scroll(collection_name=collection, limit=10000,
                                  with_payload=True, with_vectors=False)
        point_by_key = {}
        vector_rank = {}
        for rank, point in enumerate(vector_results, start=1):
            payload = point.payload or {}
            if payload.get("document_id") == document_id:
                key = (payload.get("element_id"), payload.get("chunk_index"))
                point_by_key[key] = payload
                similarity = getattr(point, "score", None)
                if similarity is None or similarity >= threshold:
                    vector_rank[key] = rank
        lexical_rank = {}
        lexical_candidates = []
        for point in points:
            payload = point.payload or {}
            if payload.get("document_id") != document_id:
                continue
            key = (payload.get("element_id"), payload.get("chunk_index"))
            point_by_key[key] = payload
            lexical_candidates.append((key, _lexical_score(question, payload.get("text", ""))))
        lexical_candidates.sort(key=lambda item: item[1], reverse=True)
        for rank, (key, score) in enumerate(lexical_candidates[:max(top_k * 4, 20)], start=1):
            if score > 0:
                lexical_rank[key] = rank
        fused = []
        for key, payload in point_by_key.items():
            score = (1 / (60 + vector_rank[key]) if key in vector_rank else 0) + \
                    (1 / (60 + lexical_rank[key]) if key in lexical_rank else 0)
            if key in vector_rank or key in lexical_rank:
                fused.append((score, payload))
        fused.sort(key=lambda item: item[0], reverse=True)
        return [payload for _, payload in fused[:top_k]]
    finally:
        client.close()


def find_evidence_by_text(document_id: str, source_text: str, phrase: str):
    """Find page provenance for a known table row without semantic top-k truncation."""
    from qdrant_client import QdrantClient

    collections = (_collection(document_id, source_text), _v2_collection(document_id, source_text),
                   _legacy_collection(document_id, source_text))
    client = QdrantClient(path=str(VECTOR_DIR))
    normalize = lambda value: re.sub(r"\s+", " ", str(value or "")).strip().casefold()
    needle = normalize(phrase)
    try:
        for collection in collections:
            if not client.collection_exists(collection):
                continue
            offset = None
            while True:
                points, offset = client.scroll(
                    collection_name=collection, limit=256, offset=offset, with_payload=True,
                )
                for point in points:
                    payload = point.payload or {}
                    if payload.get("type") == "table" and needle in normalize(payload.get("text")):
                        return payload
                if offset is None:
                    break
        return None
    finally:
        client.close()
