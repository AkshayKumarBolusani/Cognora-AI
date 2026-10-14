
import json
import hashlib
import os
import re
import sqlite3
import uuid
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

from src.ui.providers import generate_answer
from src.ui.retrieval import delete_document_indexes, find_evidence_by_text, has_index, index_document, retrieve
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
UPLOADS = ROOT / "data" / "uploads"
TEXT_DIR = ROOT / "data" / "processed" / "user_documents"
REGISTRY = ROOT / "data" / "documents.json"
DB_PATH = ROOT / "data" / "app.db"
PROCESSING_EXECUTOR = ThreadPoolExecutor(max_workers=1, thread_name_prefix="cognora-processing")
_DOCLING_CONVERTER = None


def get_docling_converter():
    """Reuse Docling's initialized pipeline across sequential document jobs."""
    global _DOCLING_CONVERTER
    if _DOCLING_CONVERTER is None:
        from docling.document_converter import DocumentConverter
        _DOCLING_CONVERTER = DocumentConverter()
    return _DOCLING_CONVERTER

UPLOADS.mkdir(parents=True, exist_ok=True)
TEXT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Document AI API")

# Keep in sync with the upload controls in frontend/src/App.tsx.
SUPPORTED_DOCUMENT_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".rtf", ".pptx", ".ppt", ".xlsx", ".xls",
    ".csv", ".txt", ".md", ".html", ".htm", ".mhtml", ".odt", ".ods",
    ".odp", ".epub", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp",
}

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        *[origin.strip() for origin in os.getenv("CORS_ORIGINS", "").split(",") if origin.strip()],
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Accept-Ranges", "Content-Range", "Content-Length", "ETag"],
)


@contextmanager
def db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def load_docs():
    if not REGISTRY.exists():
        return []
    return json.loads(REGISTRY.read_text(encoding="utf-8"))


def save_docs(docs):
    REGISTRY.write_text(
        json.dumps(docs, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def now():
    return datetime.now().isoformat(timespec="seconds")


def ensure_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL,
                citations TEXT NOT NULL DEFAULT '[]'
            )
        """)
        columns = {row[1] for row in conn.execute("PRAGMA table_info(messages)")}
        if "citations" not in columns:
            conn.execute("ALTER TABLE messages ADD COLUMN citations TEXT NOT NULL DEFAULT '[]'")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS processing_jobs (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                status TEXT NOT NULL,
                stage TEXT NOT NULL,
                completed_stages INTEGER NOT NULL DEFAULT 0,
                total_stages INTEGER NOT NULL DEFAULT 3,
                error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            UPDATE processing_jobs SET status='failed', stage='interrupted',
                error='Processing was interrupted by a server restart.', updated_at=?
            WHERE status IN ('queued', 'running')
        """, (now(),))


ensure_db()


class ChatRequest(BaseModel):
    document_id: str


class MessageRequest(BaseModel):
    content: str
    document_ids: list[str] | None = None


def rank_table_amount(source_text: str, question: str):
    """Calculate min/max directly over amount cells in extracted Markdown tables."""
    lowered = question.casefold()
    if re.search(r"\b(lowest|smallest|minimum|min)\b", lowered):
        operation = "min"
    elif re.search(r"\b(highest|largest|maximum|max|biggest|greatest)\b", lowered):
        operation = "max"
    else:
        return None

    months = {
        name.casefold(): number for number, name in enumerate((
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ), start=1)
    }
    selected_month = next((number for name, number in months.items() if re.search(rf"\b{name}\b", lowered)), None)
    selected_month = selected_month or next((number for name, number in months.items() if re.search(rf"\b{name[:3]}\b", lowered)), None)
    year_match = re.search(r"\b(20\d{2})\b", lowered)
    selected_year = year_match.group(1) if year_match else None
    requested_direction = "cr" if re.search(r"\b(credit|credited)\b", lowered) else "dr" if re.search(r"\b(debit|debited)\b", lowered) else None
    want_balance = "balance" in lowered

    headers = None
    candidates = []
    for line in source_text.splitlines():
        cells = [cell.strip() for cell in line.split("|")]
        normalized_headers = [re.sub(r"[^a-z]", "", cell.casefold()) for cell in cells]
        date_index = next((i for i, cell in enumerate(normalized_headers) if cell == "date"), None)
        amount_indices = [i for i, cell in enumerate(normalized_headers) if "amount" in cell and "balance" not in cell]
        balance_indices = [i for i, cell in enumerate(normalized_headers) if "balance" in cell]
        if date_index is not None and (amount_indices or balance_indices):
            chosen = balance_indices if want_balance else amount_indices
            if chosen:
                headers = (date_index, chosen[0], normalized_headers)
            continue
        if headers is None:
            continue
        date_index, amount_index, header_names = headers
        if len(cells) <= max(date_index, amount_index):
            continue
        date_value = re.sub(r"\s+", "", cells[date_index])
        date_match = re.fullmatch(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{4})", date_value)
        if not date_match:
            continue
        day, month, year = date_match.groups()
        if selected_month and int(month) != selected_month:
            continue
        if selected_year and year != selected_year:
            continue
        amount_cell = cells[amount_index]
        amount_match = re.search(r"(?<![A-Za-z])(-?\d[\d,]*(?:\.\d+)?)", amount_cell)
        if not amount_match:
            continue
        direction_match = re.search(r"\b(Cr|Dr)\b", amount_cell, re.I)
        direction = direction_match.group(1).upper() if direction_match else ""
        if requested_direction and direction.casefold() != requested_direction:
            continue
        transaction_id_index = next((i for i, name in enumerate(header_names) if "transactionid" in name), None)
        remarks_index = next((i for i, name in enumerate(header_names) if name in {"remarks", "description", "narration"}), None)
        candidates.append({
            "value": float(amount_match.group(1).replace(",", "")),
            "date": f"{day.zfill(2)}-{month.zfill(2)}-{year}",
            "period": next(name.title() for name, number in months.items() if number == int(month)) if selected_month else "",
            "direction": direction,
            "transaction_id": cells[transaction_id_index] if transaction_id_index is not None and transaction_id_index < len(cells) else "",
            "remarks": cells[remarks_index] if remarks_index is not None and remarks_index < len(cells) else "",
            "row": line.strip(),
            "kind": "balance" if want_balance else "transaction amount",
        })

    if not candidates:
        return None
    return (min if operation == "min" else max)(candidates, key=lambda row: row["value"])


def get_document(document_id):
    doc = next(
        (item for item in load_docs() if item["id"] == document_id),
        None,
    )
    if not doc:
        raise HTTPException(404, "Document not found")
    return doc


def get_conversation(chat_id):
    with db() as conn:
        row = conn.execute(
            "SELECT * FROM conversations WHERE id = ?",
            (chat_id,),
        ).fetchone()
    if not row:
        raise HTTPException(404, "Conversation not found")
    return dict(row)


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/documents/{document_id}/file")
def get_document_file(document_id: str):
    import mimetypes
    from fastapi.responses import FileResponse

    doc = get_document(document_id)
    source = UPLOADS / doc["stored_name"]

    if not source.is_file():
        raise HTTPException(404, "Uploaded document file not found")

    media_type = mimetypes.guess_type(doc["name"])[0] or "application/octet-stream"
    return FileResponse(
        path=source,
        media_type=media_type,
        filename=doc["name"],
        content_disposition_type="inline",
    )


@app.get("/api/documents/{document_id}/preview")
def get_document_preview(document_id: str):
    doc = get_document(document_id)
    extension = Path(doc["name"]).suffix.lower()
    source = UPLOADS / Path(doc["stored_name"]).name
    if not source.is_file():
        raise HTTPException(404, "Uploaded document file not found")

    # Plain-text formats can be previewed immediately and are never rendered as HTML.
    if extension in {".txt", ".md", ".csv"}:
        if source.stat().st_size > 10 * 1024 * 1024:
            raise HTTPException(413, "Text preview is limited to 10 MB. The document can still be analyzed.")
        try:
            return {"text": source.read_text(encoding="utf-8-sig"), "kind": "text", "processed": doc.get("status") == "text_extracted"}
        except UnicodeDecodeError as exc:
            raise HTTPException(422, "This file is not valid UTF-8 text.") from exc

    extracted = TEXT_DIR / f"{document_id}.md"
    if not extracted.is_file():
        raise HTTPException(409, "Process this document to preview its extracted content.")
    if extracted.stat().st_size > 10 * 1024 * 1024:
        raise HTTPException(413, "Extracted text preview is limited to 10 MB.")
    try:
        return {"text": extracted.read_text(encoding="utf-8"), "kind": "text", "processed": True}
    except UnicodeDecodeError as exc:
        raise HTTPException(422, "The extracted preview could not be decoded as text.") from exc


@app.get("/api/documents/{document_id}/preview-image")
def get_document_preview_image(document_id: str):
    import io
    from fastapi.responses import Response

    doc = get_document(document_id)
    extension = Path(doc["name"]).suffix.lower()
    source = UPLOADS / Path(doc["stored_name"]).name
    if extension not in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}:
        raise HTTPException(415, "This document is not an image.")
    if not source.is_file():
        raise HTTPException(404, "Uploaded image not found.")
    if extension in {".tif", ".tiff"}:
        try:
            from PIL import Image
            with Image.open(source) as image:
                image.seek(0)
                output = io.BytesIO()
                image.convert("RGB").save(output, format="PNG")
            return Response(content=output.getvalue(), media_type="image/png")
        except Exception as exc:
            raise HTTPException(422, f"Could not render this TIFF image: {exc}") from exc

    import mimetypes
    from fastapi.responses import FileResponse
    return FileResponse(
        source,
        media_type=mimetypes.guess_type(doc["name"])[0] or "application/octet-stream",
        content_disposition_type="inline",
    )


@app.get("/api/documents")
def list_documents():
    documents = []
    for original in load_docs():
        doc = dict(original)
        if doc.get("status") == "text_extracted":
            text_path = TEXT_DIR / f"{doc['id']}.md"
            try:
                indexed = text_path.is_file() and has_index(
                    doc["id"], text_path.read_text(encoding="utf-8")
                )
            except Exception:
                indexed = False
            if not indexed:
                doc["status"] = "needs_indexing" if text_path.is_file() else "needs_processing"
        documents.append(doc)
    return documents


@app.post("/api/documents")
async def upload_document(file: UploadFile = File(...)):
    name = Path(file.filename or "document").name

    if Path(name).suffix.lower() not in SUPPORTED_DOCUMENT_EXTENSIONS:
        supported = ", ".join(sorted(SUPPORTED_DOCUMENT_EXTENSIONS))
        raise HTTPException(400, f"Unsupported file type. Supported formats: {supported}")

    docs = load_docs()
    doc_id = str(uuid.uuid4())
    stored_name = f"{doc_id}_{name}"
    destination = UPLOADS / stored_name

    # Avoid unbounded uploads.
    content = await file.read(200 * 1024 * 1024 + 1)
    if len(content) > 200 * 1024 * 1024:
        raise HTTPException(413, "File exceeds 200 MB")

    destination.write_bytes(content)

    doc = {
        "id": doc_id,
        "name": name,
        "stored_name": stored_name,
        "uploaded_at": now(),
        "status": "uploaded",
    }
    docs.append(doc)
    save_docs(docs)
    return doc


@app.delete("/api/documents/{document_id}")
def delete_document(document_id: str):
    doc = get_document(document_id)
    with db() as conn:
        running = conn.execute(
            "SELECT 1 FROM processing_jobs WHERE document_id=? AND status IN ('queued', 'running') LIMIT 1",
            (document_id,),
        ).fetchone()
    if running:
        raise HTTPException(409, "Wait for document processing to finish before deleting it.")

    # Remove document-scoped vectors first. If Qdrant is unavailable, preserve
    # the registry, chats, and source files so deletion can be retried safely.
    try:
        deleted_indexes = delete_document_indexes(document_id)
    except Exception as exc:
        raise HTTPException(503, f"Could not remove this document's search index: {exc}") from exc

    source = UPLOADS / Path(doc["stored_name"]).name
    extracted = TEXT_DIR / f"{document_id}.md"
    figure_dir = TEXT_DIR / document_id
    for path in (source, extracted):
        try:
            path.unlink(missing_ok=True)
        except OSError as exc:
            raise HTTPException(500, f"Could not remove stored document data: {exc}") from exc
    try:
        import shutil
        shutil.rmtree(figure_dir, ignore_errors=False)
    except FileNotFoundError:
        pass
    except OSError as exc:
        raise HTTPException(500, f"Could not remove stored document figures: {exc}") from exc

    with db() as conn:
        conn.execute("DELETE FROM messages WHERE conversation_id IN (SELECT id FROM conversations WHERE document_id=?)", (document_id,))
        conn.execute("DELETE FROM conversations WHERE document_id=?", (document_id,))
        conn.execute("DELETE FROM processing_jobs WHERE document_id=?", (document_id,))

    save_docs([item for item in load_docs() if item["id"] != document_id])
    return {
        "deleted": True,
        "document_id": document_id,
        "deleted_indexes": deleted_indexes,
    }


@app.post("/api/documents/{document_id}/process")
def process_document(document_id: str, force: bool = False):
    doc = get_document(document_id)
    with db() as conn:
        existing = conn.execute("""
            SELECT * FROM processing_jobs
            WHERE document_id=? AND status IN ('queued', 'running')
            ORDER BY created_at DESC LIMIT 1
        """, (document_id,)).fetchone()
        if existing:
            return dict(existing)
        job_id = str(uuid.uuid4())
        conn.execute("""
            INSERT INTO processing_jobs
            (id, document_id, status, stage, completed_stages, total_stages, created_at, updated_at)
            VALUES (?, ?, 'queued', 'queued', 0, 3, ?, ?)
        """, (job_id, document_id, now(), now()))
    docs = load_docs()
    for item in docs:
        if item["id"] == document_id:
            item["status"] = "processing"
    save_docs(docs)
    PROCESSING_EXECUTOR.submit(_run_processing_job, job_id, document_id, force)
    return get_processing_job(job_id)


def get_processing_job(job_id: str):
    with db() as conn:
        row = conn.execute("SELECT * FROM processing_jobs WHERE id=?", (job_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Processing job not found")
    return dict(row)


def _run_processing_job(job_id: str, document_id: str, force: bool = False):
    def update(stage: str, completed: int, status: str = "running", error: str | None = None):
        with db() as conn:
            conn.execute("""
                UPDATE processing_jobs SET status=?, stage=?, completed_stages=?, error=?, updated_at=?
                WHERE id=?
            """, (status, stage, completed, error, now(), job_id))

    try:
        update("parsing", 0)
        doc = get_document(document_id)
        source = UPLOADS / doc["stored_name"]
        output = TEXT_DIR / f"{document_id}.md"
        if source.suffix.lower() in {".txt", ".md"}:
            text = source.read_text(encoding="utf-8-sig")
            elements = [{
                "text": text, "page": None, "type": "text", "element_id": "text-0",
            }]
        else:
            result = get_docling_converter().convert(str(source))
            text = result.document.export_to_markdown()
            import shutil
            figure_dir = TEXT_DIR / document_id
            shutil.rmtree(figure_dir, ignore_errors=True)
            figure_dir.mkdir(parents=True, exist_ok=True)
            elements = extract_index_elements(result.document, figure_dir=figure_dir)
        if not text.strip():
            raise ValueError("No readable text was extracted from this document.")
        output.write_text(text, encoding="utf-8")

        update("element_extraction", 1)
        if not elements:
            elements = [{"text": text, "page": None, "type": "text", "element_id": "text-0"}]
        update("embedding_and_indexing", 2)
        if force:
            delete_document_indexes(document_id)
        index_document(document_id, doc["name"], text, elements=elements)

        docs = load_docs()
        for item in docs:
            if item["id"] == document_id:
                item["status"] = "text_extracted"
        save_docs(docs)
        update("ready", 3, status="ready")
    except Exception as exc:
        try:
            docs = load_docs()
            for item in docs:
                if item["id"] == document_id:
                    item["status"] = "processing_failed"
            save_docs(docs)
        except Exception:
            pass
        update("failed", 0, status="failed", error=str(exc)[:1000])


def extract_index_elements(document, figure_dir: Path | None = None):
    """Extract searchable text while retaining Docling page and element provenance."""
    elements = []
    if figure_dir is not None:
        figure_dir.mkdir(parents=True, exist_ok=True)
    for item, _level in document.iterate_items(traverse_pictures=True):
        label = getattr(item, "label", None)
        source_type = getattr(label, "value", str(label or "text")).lower()
        if source_type in {"table", "document_index"}:
            source_type = "table"
            try:
                text = item.export_to_dataframe(doc=document).to_markdown(index=False)
            except Exception:
                text = ""
        elif source_type in {"picture", "chart"}:
            source_type = "figure"
            text = item.caption_text(document) if hasattr(item, "caption_text") else ""
            meta = getattr(item, "meta", None)
            description = getattr(getattr(meta, "description", None), "text", "")
            if description:
                text = f"{text}\n{description}".strip()
            figure_id = hashlib.sha256(str(getattr(item, "self_ref", f"figure-{len(elements)}")).encode()).hexdigest()
            image_bytes = None
            vision_enabled = bool(os.getenv("VISION_PROVIDER", "").strip())
            if (figure_dir is not None or vision_enabled) and hasattr(item, "get_image"):
                try:
                    import io
                    image = item.get_image(document)
                    if image is not None:
                        buffer = io.BytesIO()
                        image.save(buffer, format="PNG")
                        image_bytes = buffer.getvalue()
                        if figure_dir is not None:
                            (figure_dir / f"{figure_id}.png").write_bytes(image_bytes)
                except Exception:
                    pass
            if vision_enabled and image_bytes:
                try:
                    from src.ui.providers import describe_image
                    generated = describe_image(
                        image_bytes,
                        "Describe this figure from a document. Capture the chart or diagram type, labels, values, relationships, and key takeaway. Do not guess unreadable details.",
                    )
                    if generated:
                        text = f"{text}\nVisual description: {generated}".strip()
                except Exception:
                    # Vision improves figure retrieval but must not make text extraction fail.
                    pass
        else:
            text = getattr(item, "text", "")
            source_type = "text"
        text = str(text or "").strip()
        if source_type == "figure" and not text:
            page_hint = " on page " + str(getattr((getattr(item, "prov", None) or [None])[0], "page_no", "")) if getattr(item, "prov", None) else ""
            text = f"Figure{page_hint} in the document."
        if not text:
            continue
        provenance = getattr(item, "prov", None) or []
        first_provenance = provenance[0] if provenance else None
        page = getattr(first_provenance, "page_no", None)
        element = {
            "text": text,
            "page": page,
            "type": source_type,
            "element_id": str(getattr(item, "self_ref", f"element-{len(elements)}")),
        }
        if source_type == "figure" and figure_dir is not None and (figure_dir / f"{figure_id}.png").is_file():
            element["figure_id"] = figure_id
        elements.append(element)
    return elements


@app.get("/api/documents/{document_id}/figures/{figure_id}")
def get_document_figure(document_id: str, figure_id: str):
    from fastapi.responses import FileResponse

    get_document(document_id)
    if not re.fullmatch(r"[a-f0-9]{64}", figure_id):
        raise HTTPException(404, "Figure not found")
    image_path = TEXT_DIR / document_id / f"{figure_id}.png"
    if not image_path.is_file():
        raise HTTPException(404, "Figure image not found")
    return FileResponse(image_path, media_type="image/png", content_disposition_type="inline")


@app.get("/api/processing-jobs/{job_id}")
def processing_job_status(job_id: str):
    return get_processing_job(job_id)


@app.get("/api/documents/{document_id}/processing-job")
def latest_processing_job(document_id: str):
    get_document(document_id)
    with db() as conn:
        row = conn.execute("""
            SELECT * FROM processing_jobs WHERE document_id=?
            ORDER BY created_at DESC LIMIT 1
        """, (document_id,)).fetchone()
    if not row:
        raise HTTPException(404, "No processing job for this document")
    return dict(row)


@app.get("/api/documents/{document_id}/chats")
def list_chats(document_id: str):
    get_document(document_id)
    with db() as conn:
        rows = conn.execute("""
            SELECT id, document_id, title, created_at
            FROM conversations
            WHERE document_id = ?
            ORDER BY created_at DESC
        """, (document_id,)).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/chats")
def create_chat(request: ChatRequest):
    get_document(request.document_id)
    chat_id = str(uuid.uuid4())
    with db() as conn:
        conn.execute("""
            INSERT INTO conversations
            (id, document_id, title, created_at)
            VALUES (?, ?, ?, ?)
        """, (chat_id, request.document_id, "New chat", now()))
    return get_conversation(chat_id)


@app.get("/api/chats/{chat_id}/messages")
def list_messages(chat_id: str):
    get_conversation(chat_id)
    with db() as conn:
        rows = conn.execute("""
            SELECT id, role, content, created_at, citations
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id
        """, (chat_id,)).fetchall()
    messages = []
    for row in rows:
        item = dict(row)
        try:
            item["citations"] = json.loads(item.get("citations") or "[]")
        except json.JSONDecodeError:
            item["citations"] = []
        messages.append(item)
    return messages


@app.post("/api/chats/{chat_id}/messages")
def send_message(chat_id: str, request: MessageRequest):
    question = request.content.strip()
    if not question:
        raise HTTPException(400, "Message cannot be empty")

    chat = get_conversation(chat_id)
    doc = get_document(chat["document_id"])
    selected_ids = list(dict.fromkeys(request.document_ids or [doc["id"]]))
    if not selected_ids or len(selected_ids) > 10:
        raise HTTPException(400, "Select between 1 and 10 documents.")
    if doc["id"] not in selected_ids:
        selected_ids.insert(0, doc["id"])
    selected_docs = [get_document(document_id) for document_id in selected_ids]
    source_by_id = {}
    for selected in selected_docs:
        path = TEXT_DIR / f"{selected['id']}.md"
        if not path.exists() or selected.get("status") != "text_extracted":
            raise HTTPException(409, f"{selected['name']} is not processed and ready for chat.")
        source_by_id[selected["id"]] = path.read_text(encoding="utf-8")
        if not has_index(selected["id"], source_by_id[selected["id"]]):
            raise HTTPException(409, f"{selected['name']} is not indexed. Process it before asking questions.")

    # Keep prior turns for follow-up questions, scoped to this conversation.
    with db() as conn:
        previous = conn.execute(
            "SELECT role, content FROM messages WHERE conversation_id = ? ORDER BY id DESC LIMIT 8",
            (chat_id,),
        ).fetchall()
    history = list(reversed([dict(row) for row in previous]))
    retrieval_query = "\n".join(
        [row["content"] for row in history if row["role"] == "user"] + [question]
    )

    source_text = source_by_id[doc["id"]]
    ranked_row = rank_table_amount(source_text, question) if len(selected_docs) == 1 else None
    if ranked_row:
        try:
            source = find_evidence_by_text(doc["id"], source_text, ranked_row["row"])
        except Exception:
            source = None
        citation = {
            "id": (source or {}).get("element_id") or f"table-row-{ranked_row['date']}",
            "label": "E1",
            "document_id": doc["id"],
            "document_name": doc["name"],
            "page": (source or {}).get("page"),
            "text": (source or {}).get("text") or ranked_row["row"],
            "type": "table",
        }
        display_amount = f"₹{ranked_row['value']:,.2f}"
        direction = f" ({ranked_row['direction']})" if ranked_row["direction"] else ""
        period = f" in {ranked_row['period']}" if ranked_row["period"] else ""
        answer = f"The {ranked_row['kind']} is {display_amount}{direction}{period}, dated {ranked_row['date']}."
        if ranked_row["transaction_id"]:
            answer += f" Transaction ID: {ranked_row['transaction_id']}."
        if ranked_row["remarks"]:
            answer += f" Remarks: {ranked_row['remarks']}."
        answer += " [E1]"
        with db() as conn:
            conn.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, 'user', ?, ?)",
                (chat_id, question, now()),
            )
            if chat["title"] == "New chat":
                title = question[:42] + ("…" if len(question) > 42 else "")
                conn.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, chat_id))
            conn.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at, citations) VALUES (?, 'assistant', ?, ?, ?)",
                (chat_id, answer, now(), json.dumps([citation])),
            )
        return {"answer": answer, "chat_id": chat_id, "citations": [citation]}

    try:
        top_k = max(1, min(int(os.getenv("RETRIEVAL_TOP_K", "5")), 20))
        threshold = max(0.0, min(float(os.getenv("RETRIEVAL_SCORE_THRESHOLD", "0.15")), 1.0))
        per_document_k = max(1, min(5, (top_k + len(selected_docs) - 1) // len(selected_docs)))
        evidence_by_document = [retrieve(
            selected["id"], retrieval_query,
            source_text=source_by_id[selected["id"]],
            top_k=per_document_k, threshold=threshold,
        ) for selected in selected_docs]
        evidence = []
        for rank in range(per_document_k):
            for candidates in evidence_by_document:
                if rank < len(candidates) and len(evidence) < top_k:
                    evidence.append(candidates[rank])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Document retrieval failed: {exc}") from exc

    if not evidence:
        answer = "I could not find relevant evidence for that question in this document."
        with db() as conn:
            conn.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, 'user', ?, ?)",
                (chat_id, question, now()),
            )
            conn.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, 'assistant', ?, ?)",
                (chat_id, answer, now()),
            )
            if chat["title"] == "New chat":
                title = question[:42] + ("…" if len(question) > 42 else "")
                conn.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, chat_id))
        return {"answer": answer, "chat_id": chat_id, "citations": []}

    context = "\n\n".join(
        f"[E{i}] document={item['document_name']} page={item.get('page') or 'not available'} "
        f"element={item['element_id']} type={item.get('type', 'text')}\n{item['text']}"
        for i, item in enumerate(evidence, start=1)
    )
    history_text = "\n".join(f"{item['role']}: {item['content']}" for item in history)

    try:
        answer = generate_answer(
            system_prompt=(
                "Answer only from the supplied document evidence. "
                "Be accurate and concise. If the answer is not "
                "supported by the document, say you could not find it. "
                "Conversation history may clarify the question, but previous answers "
                "are not evidence and must not override the retrieved passages. "
                "Cite each supported claim using its evidence marker, for example [E1]. "
                "Never invent a citation or page number."
            ),
            user_prompt=(
                f"CONVERSATION HISTORY:\n{history_text or '(no prior turns)'}"
                f"\n\nRETRIEVED EVIDENCE:\n{context}"
                f"\n\nQUESTION:\n{question}"
            ),
        )
    except Exception as exc:
        raise HTTPException(
            status_code=502,
            detail=f"AI provider request failed: {exc}",
        ) from exc

    # Ensure every retrieved source is reachable even if the model omits markers.
    available_labels = [f"[E{i}]" for i in range(1, len(evidence) + 1)]
    missing_labels = [label for label in available_labels if label not in answer]
    if missing_labels:
        answer += "\n\nSources: " + ", ".join(missing_labels)

    citations = [
        {"id": item["element_id"], "label": f"E{i}", "document_id": item["document_id"],
         "document_name": item["document_name"], "page": item.get("page"),
         "text": item["text"], "type": item.get("type", "text"),
         "figure_id": item.get("figure_id")}
        for i, item in enumerate(evidence, start=1)
    ]
    with db() as conn:
        conn.execute("""
            INSERT INTO messages (conversation_id, role, content, created_at)
            VALUES (?, 'user', ?, ?)
        """, (chat_id, question, now()))
        if chat["title"] == "New chat":
            title = question[:42] + ("…" if len(question) > 42 else "")
            conn.execute("UPDATE conversations SET title = ? WHERE id = ?", (title, chat_id))
        conn.execute("""
            INSERT INTO messages
            (conversation_id, role, content, created_at, citations)
            VALUES (?, 'assistant', ?, ?, ?)
        """, (chat_id, answer, now(), json.dumps(citations)))

    return {
        "answer": answer,
        "chat_id": chat_id,
        "citations": citations,
    }

@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: str):
    get_conversation(chat_id)

    with db() as conn:
        conn.execute(
            "DELETE FROM messages WHERE conversation_id = ?",
            (chat_id,),
        )
        conn.execute(
            "DELETE FROM conversations WHERE id = ?",
            (chat_id,),
        )

    return {"deleted": True, "chat_id": chat_id}
