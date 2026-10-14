
import json
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path

import ollama
import streamlit as st
from process_document import extract_document_text

ROOT = Path(__file__).resolve().parents[2]
UPLOADS = ROOT / "data" / "uploads"
TEXT_DIR = ROOT / "data" / "processed" / "user_documents"
REGISTRY = ROOT / "data" / "documents.json"
DB_PATH = ROOT / "data" / "app.db"

for folder in (UPLOADS, TEXT_DIR):
    folder.mkdir(parents=True, exist_ok=True)

st.set_page_config(
    page_title="Document AI",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .block-container {
        max-width: 1100px;
        padding-top: 2rem;
        padding-bottom: 7rem;
    }
    [data-testid="stSidebar"] {
        border-right: 1px solid rgba(128,128,128,.18);
    }
    [data-testid="stSidebar"] .block-container {
        padding-top: 1.5rem;
    }
    .doc-status {
        color: var(--text-color);
        opacity: .65;
        font-size: .85rem;
    }
    div[data-testid="stChatMessage"] {
        border-radius: 12px;
        padding: .8rem 1rem;
    }
    .app-subtitle {
        opacity: .65;
        font-size: .9rem;
        margin-top: -.6rem;
        margin-bottom: 1.5rem;
    }
</style>
""", unsafe_allow_html=True)


def db_connect():
    return sqlite3.connect(DB_PATH)


def init_db():
    with db_connect() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY,
                document_id TEXT NOT NULL,
                title TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)
        db.execute("""
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                conversation_id TEXT NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        """)

        # Remove the exact placeholder from the earlier UI version.
        db.execute("""
            DELETE FROM messages
            WHERE content = ?
        """, (
            "Your question is saved. Connecting the local AI answer engine "
            "is our next step.",
        ))


def load_docs():
    if not REGISTRY.exists():
        return []
    try:
        return json.loads(REGISTRY.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        st.error("Could not read the document registry.")
        return []


def save_docs(docs):
    REGISTRY.write_text(
        json.dumps(docs, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def get_chats(doc_id):
    with db_connect() as db:
        return db.execute("""
            SELECT id, title, created_at
            FROM conversations
            WHERE document_id = ?
            ORDER BY created_at DESC
        """, (doc_id,)).fetchall()


def create_chat(doc_id):
    chat_id = str(uuid.uuid4())
    with db_connect() as db:
        db.execute("""
            INSERT INTO conversations
            (id, document_id, title, created_at)
            VALUES (?, ?, ?, ?)
        """, (
            chat_id,
            doc_id,
            "New chat",
            datetime.now().isoformat(timespec="seconds"),
        ))
    return chat_id


def get_messages(chat_id):
    with db_connect() as db:
        return db.execute("""
            SELECT role, content
            FROM messages
            WHERE conversation_id = ?
            ORDER BY id
        """, (chat_id,)).fetchall()


def save_message(chat_id, role, content):
    with db_connect() as db:
        db.execute("""
            INSERT INTO messages
            (conversation_id, role, content, created_at)
            VALUES (?, ?, ?, ?)
        """, (
            chat_id,
            role,
            content,
            datetime.now().isoformat(timespec="seconds"),
        ))

        if role == "user":
            row = db.execute(
                "SELECT title FROM conversations WHERE id = ?",
                (chat_id,),
            ).fetchone()

            if row and row[0] == "New chat":
                title = content[:42] + ("…" if len(content) > 42 else "")
                db.execute(
                    "UPDATE conversations SET title = ? WHERE id = ?",
                    (title, chat_id),
                )


init_db()
docs = load_docs()

if "active_document" not in st.session_state:
    st.session_state.active_document = None
if "active_chat_id" not in st.session_state:
    st.session_state.active_chat_id = None

# ----- Sidebar -----
with st.sidebar:
    st.markdown("## 📚 Document AI")
    st.caption("Your private document workspace")

    if st.button("＋  New chat", use_container_width=True, type="primary"):
        if st.session_state.active_document:
            st.session_state.active_chat_id = create_chat(
                st.session_state.active_document
            )
            st.rerun()
        elif docs:
            st.session_state.active_document = docs[0]["id"]
            st.session_state.active_chat_id = create_chat(docs[0]["id"])
            st.rerun()
        else:
            st.info("Upload a document first.")

    with st.expander("＋ Add a document", expanded=not bool(docs)):
        uploaded = st.file_uploader(
            "Choose a file",
            type=["pdf", "txt", "md", "docx"],
            key="document_upload",
        )

        if uploaded and st.button("Save document", use_container_width=True):
            if any(d["name"] == uploaded.name for d in docs):
                st.warning("That filename already exists. Rename it to add another copy.")
            else:
                doc_id = str(uuid.uuid4())
                stored_name = f"{doc_id}_{Path(uploaded.name).name}"
                (UPLOADS / stored_name).write_bytes(uploaded.getvalue())

                docs.append({
                    "id": doc_id,
                    "name": Path(uploaded.name).name,
                    "stored_name": stored_name,
                    "uploaded_at": datetime.now().isoformat(timespec="seconds"),
                    "status": "uploaded",
                })
                save_docs(docs)
                st.session_state.active_document = doc_id
                st.session_state.active_chat_id = None
                st.rerun()

    st.divider()
    st.markdown("#### Documents & chats")

    if not docs:
        st.caption("Your documents will appear here.")

    for doc in docs:
        is_active = doc["id"] == st.session_state.active_document

        with st.container(border=is_active):
            if st.button(
                f"📄  {doc['name']}",
                key=f"doc_{doc['id']}",
                use_container_width=True,
                type="primary" if is_active else "secondary",
            ):
                st.session_state.active_document = doc["id"]
                chats = get_chats(doc["id"])
                st.session_state.active_chat_id = chats[0][0] if chats else None
                st.rerun()

            chats = get_chats(doc["id"])

            if chats:
                with st.expander(f"Chats ({len(chats)})", expanded=is_active):
                    for chat_id, title, created in chats:
                        selected = chat_id == st.session_state.active_chat_id
                        if st.button(
                            f"{'● ' if selected else '  '}{title}",
                            key=f"chat_{chat_id}",
                            use_container_width=True,
                            type="primary" if selected else "secondary",
                        ):
                            st.session_state.active_document = doc["id"]
                            st.session_state.active_chat_id = chat_id
                            st.rerun()

    st.divider()
    st.caption("Local files · Local AI")


# ----- Main chat -----
active_doc = next(
    (d for d in docs if d["id"] == st.session_state.active_document),
    None,
)

if not active_doc:
    st.title("Your documents, one conversation at a time")
    st.markdown(
        '<div class="app-subtitle">'
        'Upload a document to start asking questions about it.'
        '</div>',
        unsafe_allow_html=True,
    )
    st.info("Use **Add a document** in the sidebar to get started.")
    st.stop()

st.title(active_doc["name"])

text_path = TEXT_DIR / f"{active_doc['id']}.md"

if text_path.exists():
    st.caption("● Text extracted")
else:
    st.caption("○ Not processed yet")
    if st.button("Process document", type="primary"):
        try:
            source_path = UPLOADS / active_doc["stored_name"]
            with st.spinner("Extracting document text..."):
                extracted = extract_document_text(source_path)

            if not extracted.strip():
                st.warning("No readable text was extracted.")
            else:
                text_path.write_text(extracted, encoding="utf-8")
                active_doc["status"] = "text_extracted"
                save_docs(docs)
                st.rerun()
        except Exception as exc:
            st.error(f"Processing failed: {exc}")

chat_id = st.session_state.active_chat_id

if not chat_id:
    if st.button("＋ Start a conversation", type="primary"):
        st.session_state.active_chat_id = create_chat(active_doc["id"])
        st.rerun()

    st.stop()

# Guard against accidentally opening a chat belonging to another document.
with db_connect() as db:
    owner = db.execute(
        "SELECT document_id FROM conversations WHERE id = ?",
        (chat_id,),
    ).fetchone()

if not owner or owner[0] != active_doc["id"]:
    st.session_state.active_chat_id = None
    st.rerun()

for role, content in get_messages(chat_id):
    with st.chat_message(role):
        st.markdown(content)

question = st.chat_input(
    "Message about this document...",
    disabled=not text_path.exists(),
)

if question:
    save_message(chat_id, "user", question)

    try:
        document_text = text_path.read_text(encoding="utf-8")

        with st.spinner("Thinking..."):
            response = ollama.chat(
                model="qwen2.5vl:7b",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Answer questions using only the supplied document. "
                            "Be accurate and concise. If the document does not "
                            "support an answer, say so. Do not invent page numbers."
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            "DOCUMENT:\n"
                            + document_text[:40000]
                            + "\n\nQUESTION:\n"
                            + question
                        ),
                    },
                ],
            )
        answer = response["message"]["content"]
    except Exception as exc:
        answer = f"Local AI error: {exc}"

    save_message(chat_id, "assistant", answer)
    st.rerun()
