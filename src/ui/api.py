
import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

import ollama
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[2]
UPLOADS = ROOT / "data" / "uploads"
TEXT_DIR = ROOT / "data" / "processed" / "user_documents"
REGISTRY = ROOT / "data" / "documents.json"
DB_PATH = ROOT / "data" / "app.db"

UPLOADS.mkdir(parents=True, exist_ok=True)
TEXT_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Document AI API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def db():
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    return connection


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
                created_at TEXT NOT NULL
            )
        """)


ensure_db()


class ChatRequest(BaseModel):
    document_id: str


class MessageRequest(BaseModel):
    content: str


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


@app.get("/api/documents")
def list_documents():
    return load_docs()


@app.post("/api/documents")
async def upload_document(file: UploadFile = File(...)):
    allowed = {".pdf", ".txt", ".md", ".docx"}
    name = Path(file.filename or "document").name

    if Path(name).suffix.lower() not in allowed:
        raise HTTPException(400, "Unsupported file type")

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


@app.post("/api/documents/{document_id}/process")
def process_document(document_id: str):
    from docling.document_converter import DocumentConverter

    doc = get_document(document_id)
    source = UPLOADS / doc["stored_name"]
    output = TEXT_DIR / f"{document_id}.md"

    try:
        converter = DocumentConverter()
        result = converter.convert(str(source))
        text = result.document.export_to_markdown()
    except Exception as exc:
        raise HTTPException(500, f"Document extraction failed: {exc}")

    if not text.strip():
        raise HTTPException(422, "No readable text was extracted")

    output.write_text(text, encoding="utf-8")
    docs = load_docs()
    for item in docs:
        if item["id"] == document_id:
            item["status"] = "text_extracted"
    save_docs(docs)

    return {"status": "text_extracted", "characters": len(text)}


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
            SELECT id, role, content, created_at
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id
        """, (chat_id,)).fetchall()
    return [dict(row) for row in rows]


@app.post("/api/chats/{chat_id}/messages")
def send_message(chat_id: str, request: MessageRequest):
    question = request.content.strip()
    if not question:
        raise HTTPException(400, "Message cannot be empty")

    chat = get_conversation(chat_id)
    doc = get_document(chat["document_id"])
    text_path = TEXT_DIR / f"{doc['id']}.md"

    if not text_path.exists():
        raise HTTPException(
            409,
            "This document has not been processed yet. Process it first.",
        )

    # Save the user's message before generating the answer.
    with db() as conn:
        conn.execute("""
            INSERT INTO messages
            (conversation_id, role, content, created_at)
            VALUES (?, 'user', ?, ?)
        """, (chat_id, question, now()))

        if chat["title"] == "New chat":
            title = question[:42] + ("…" if len(question) > 42 else "")
            conn.execute(
                "UPDATE conversations SET title = ? WHERE id = ?",
                (title, chat_id),
            )

    document_text = text_path.read_text(encoding="utf-8")

    try:
        # Initial version: text-window QA. Qdrant retrieval comes next.
        response = ollama.chat(
            model="qwen2.5vl:7b",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Answer only from the supplied document. "
                        "Be accurate and concise. If the answer is not "
                        "supported by the document, say you could not find it. "
                        "Do not invent page numbers."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        "DOCUMENT:\n" + document_text[:40000]
                        + "\n\nQUESTION:\n" + question
                    ),
                },
            ],
        )
        answer = response["message"]["content"]
    except Exception as exc:
        answer = f"Local AI error: {exc}"

    with db() as conn:
        conn.execute("""
            INSERT INTO messages
            (conversation_id, role, content, created_at)
            VALUES (?, 'assistant', ?, ?)
        """, (chat_id, answer, now()))

    return {"answer": answer, "chat_id": chat_id}

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
