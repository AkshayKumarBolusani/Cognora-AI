import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

from src.ui import api


class ApiWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        self.patches = [
            patch.object(api, "DB_PATH", root / "app.db"),
            patch.object(api, "REGISTRY", root / "documents.json"),
            patch.object(api, "UPLOADS", root / "uploads"),
            patch.object(api, "TEXT_DIR", root / "text"),
        ]
        for item in self.patches:
            item.start()
        api.UPLOADS.mkdir()
        api.TEXT_DIR.mkdir()
        api.ensure_db()
        self.client = TestClient(api.app)

    def tearDown(self):
        self.client.close()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def add_document(self):
        document = {
            "id": "doc-123", "name": "sample.pdf", "stored_name": "sample.pdf",
            "status": "text_extracted", "uploaded_at": "2026-10-14T00:00:00",
        }
        api.save_docs([document])
        (api.TEXT_DIR / "doc-123.md").write_text("Example source passage.", encoding="utf-8")
        return document

    def test_docling_elements_keep_page_and_element_metadata(self):
        item = type("TextItem", (), {
            "label": type("Label", (), {"value": "text"})(),
            "text": "Evidence on page nine.",
            "self_ref": "#/texts/3",
            "prov": [type("Prov", (), {"page_no": 9})()],
        })()
        document = type("Doc", (), {"iterate_items": lambda self, **_kwargs: [(item, 0)]})()
        elements = api.extract_index_elements(document)
        self.assertEqual(elements, [{
            "text": "Evidence on page nine.", "page": 9,
            "type": "text", "element_id": "#/texts/3",
        }])

    def test_pdf_figure_image_is_saved_and_available_to_chat_clients(self):
        from PIL import Image

        item = type("PictureItem", (), {
            "label": type("Label", (), {"value": "picture"})(),
            "self_ref": "#/pictures/4",
            "prov": [type("Prov", (), {"page_no": 4})()],
            "caption_text": lambda self, _document: "",
            "get_image": lambda self, _document: Image.new("RGB", (3, 2), "red"),
        })()
        document = type("Doc", (), {"iterate_items": lambda self, **_kwargs: [(item, 0)]})()
        figure_dir = api.TEXT_DIR / "doc-123"
        with patch.dict("os.environ", {"VISION_PROVIDER": ""}):
            elements = api.extract_index_elements(document, figure_dir=figure_dir)
        self.assertEqual(elements[0]["type"], "figure")
        self.assertEqual(elements[0]["page"], 4)
        self.assertTrue(elements[0]["text"])
        self.assertTrue((figure_dir / f"{elements[0]['figure_id']}.png").is_file())

        api.save_docs([{
            "id": "doc-123", "name": "sample.pdf", "stored_name": "sample.pdf",
            "status": "text_extracted", "uploaded_at": "2026-10-14T00:00:00",
        }])
        response = self.client.get(f"/api/documents/doc-123/figures/{elements[0]['figure_id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["content-type"], "image/png")

    def test_highest_transaction_amount_scans_all_table_rows_and_excludes_balance(self):
        table = """| Date | Transaction Id | Remarks | Amount(₹) | Balance(₹) |
|---|---|---|---:|---:|
| 01-08-2026 | T1 | First | 9,300.00(Cr) | 69,200.29 |
| 03-08-2026 | T2 | Second | 6,000.00(Cr) | 10,102.00 |
| 20-08-2026 | T3 | Large debit | 12,65,701.00(Dr) | 14,74,743.08 |
| 01-09-2026 | T4 | Outside month | 99,00,000.00(Cr) | 9,900,000.00 |"""
        result = api.rank_table_amount(table, "what is the highest transaction amount in August")
        self.assertEqual(result["value"], 1265701.0)
        self.assertEqual(result["date"], "20-08-2026")
        self.assertEqual(result["transaction_id"], "T3")

    def test_highest_transaction_answer_uses_full_table_and_page_citation(self):
        doc = self.add_document()
        table = """| Date | Transaction Id | Remarks | Amount(₹) | Balance(₹) |
|---|---|---|---:|---:|
| 01-08-2026 | T1 | First | 9,300.00(Cr) | 69,200.29 |
| 20-08-2026 | T3 | Large debit | 12,65,701.00(Dr) | 14,74,743.08 |"""
        (api.TEXT_DIR / f"{doc['id']}.md").write_text(table, encoding="utf-8")
        chat = self.client.post("/api/chats", json={"document_id": doc["id"]}).json()
        source = {
            "element_id": "#/tables/5", "page": 3, "type": "table",
            "text": table, "document_name": doc["name"],
        }
        with patch.object(api, "has_index", return_value=True), \
             patch.object(api, "find_evidence_by_text", return_value=source), \
             patch.object(api, "retrieve", side_effect=AssertionError("extrema must scan full table")), \
             patch.object(api, "generate_answer", side_effect=AssertionError("deterministic result should not use LLM")):
            response = self.client.post(
                f"/api/chats/{chat['id']}/messages",
                json={"content": "what is the highest transaction amount in August"},
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn("₹1,265,701.00", response.json()["answer"])
        self.assertIn("20-08-2026", response.json()["answer"])
        self.assertEqual(response.json()["citations"][0]["page"], 3)

    def test_compare_mode_searches_selected_documents_and_keeps_citation_owners(self):
        first = self.add_document()
        second = {
            "id": "doc-456", "name": "second.pdf", "stored_name": "second.pdf",
            "status": "text_extracted", "uploaded_at": "2026-10-14T00:00:00",
        }
        api.save_docs([first, second])
        (api.TEXT_DIR / "doc-456.md").write_text("Second source passage.", encoding="utf-8")
        chat = self.client.post("/api/chats", json={"document_id": first["id"]}).json()
        answers = [
            [{"document_id": first["id"], "document_name": first["name"],
              "element_id": "first-source", "page": 2, "text": "First evidence."}],
            [{"document_id": second["id"], "document_name": second["name"],
              "element_id": "second-source", "page": 7, "text": "Second evidence."}],
        ]
        with patch.object(api, "has_index", return_value=True), \
             patch.object(api, "retrieve", side_effect=answers), \
             patch.object(api, "generate_answer", return_value="Both reports show the result [E1] [E2]."):
            response = self.client.post(
                f"/api/chats/{chat['id']}/messages",
                json={"content": "Compare these documents", "document_ids": [first["id"], second["id"]]},
            )
        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["document_id"] for item in response.json()["citations"]],
                         [first["id"], second["id"]])

    def test_document_without_index_is_not_reported_ready(self):
        self.add_document()
        with patch.object(api, "has_index", return_value=False):
            response = self.client.get("/api/documents")
        self.assertEqual(response.json()[0]["status"], "needs_indexing")

    def test_upload_validates_and_stores_supported_file(self):
        response = self.client.post(
            "/api/documents", files={"file": ("notes.txt", b"hello", "text/plain")}
        )
        self.assertEqual(response.status_code, 200)
        document = response.json()
        self.assertTrue((api.UPLOADS / document["stored_name"]).is_file())

        rejected = self.client.post(
            "/api/documents", files={"file": ("script.exe", b"no", "application/octet-stream")}
        )
        self.assertEqual(rejected.status_code, 400)

    def test_upload_strips_windows_path_components(self):
        response = self.client.post(
            "/api/documents",
            files={"file": (r"C:\Users\private\notes.md", b"safe text", "text/markdown")},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["name"], "notes.md")
        self.assertTrue((api.UPLOADS / response.json()["stored_name"]).is_file())

    def test_cors_rejects_wildcard_origins_with_credentials(self):
        for value in ("*", "https://*.example.com", "https://example.com/path"):
            with self.subTest(origin=value), patch.dict("os.environ", {"CORS_ORIGINS": value}):
                with self.assertRaisesRegex(RuntimeError, r"exact http\(s\) origins"):
                    api.cors_origins()

    def test_question_router_uses_structured_extrema_only_for_single_document(self):
        table = "| Date | Amount |\n|---|---:|\n| 01-08-2026 | 10(Cr) |"
        self.assertIsNotNone(api.route_question(table, "highest amount in August"))
        self.assertIsNone(api.route_question(
            table, "highest amount in August", multi_document=True
        ))

    def test_markdown_preview_is_available_before_processing(self):
        response = self.client.post(
            "/api/documents", files={"file": ("notes.md", b"# Notes\n\nPreview this.", "text/markdown")}
        )
        doc = response.json()
        preview = self.client.get(f"/api/documents/{doc['id']}/preview")
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["text"], "# Notes\n\nPreview this.")
        self.assertEqual(preview.json()["kind"], "text")

    def test_other_document_preview_uses_extracted_text(self):
        doc = self.add_document()
        doc["name"] = "sample.docx"
        api.save_docs([doc])
        (api.UPLOADS / doc["stored_name"]).write_bytes(b"sample")
        preview = self.client.get(f"/api/documents/{doc['id']}/preview")
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.json()["text"], "Example source passage.")
        self.assertTrue(preview.json()["processed"])

    def test_unprocessed_office_document_has_clear_preview_state(self):
        response = self.client.post(
            "/api/documents", files={"file": ("report.docx", b"not a real docx", "application/octet-stream")}
        )
        doc = response.json()
        preview = self.client.get(f"/api/documents/{doc['id']}/preview")
        self.assertEqual(preview.status_code, 409)

    def test_tiff_image_preview_converts_to_browser_displayable_png(self):
        from PIL import Image
        import io

        content = io.BytesIO()
        Image.new("RGB", (3, 2), color="red").save(content, format="TIFF")
        upload = self.client.post(
            "/api/documents",
            files={"file": ("scan.tiff", content.getvalue(), "image/tiff")},
        )
        doc = upload.json()
        preview = self.client.get(f"/api/documents/{doc['id']}/preview-image")
        self.assertEqual(preview.status_code, 200)
        self.assertEqual(preview.headers["content-type"], "image/png")
        self.assertTrue(preview.content.startswith(b"\x89PNG"))

    def test_upload_accepts_common_office_and_image_formats(self):
        for filename in ("slides.pptx", "ledger.xlsx", "scan.png", "book.epub"):
            with self.subTest(filename=filename):
                response = self.client.post(
                    "/api/documents", files={"file": (filename, b"sample", "application/octet-stream")}
                )
                self.assertEqual(response.status_code, 200)

    def test_markdown_is_read_directly_as_text_and_indexed(self):
        doc = {
            "id": "doc-md", "name": "notes.md", "stored_name": "notes.md",
            "status": "processing", "uploaded_at": "2026-10-14T00:00:00",
        }
        api.save_docs([doc])
        (api.UPLOADS / "notes.md").write_text("# Findings\n\nRevenue increased.", encoding="utf-8")
        job_id = "job-md"
        with api.db() as conn:
            conn.execute(
                "INSERT INTO processing_jobs (id, document_id, status, stage, created_at, updated_at) VALUES (?, ?, 'running', 'parsing', 'now', 'now')",
                (job_id, doc["id"]),
            )
        with patch.object(api, "index_document", return_value=2) as indexer:
            api._run_processing_job(job_id, doc["id"])
        self.assertEqual((api.TEXT_DIR / "doc-md.md").read_text(), "# Findings\n\nRevenue increased.")
        self.assertEqual(indexer.call_args.kwargs["elements"][0]["text"], "# Findings\n\nRevenue increased.")
        self.assertEqual(api.get_processing_job(job_id)["status"], "ready")

    def test_document_delete_removes_files_chats_jobs_and_indexes(self):
        doc = self.add_document()
        (api.UPLOADS / doc["stored_name"]).write_text("source", encoding="utf-8")
        chat = self.client.post("/api/chats", json={"document_id": doc["id"]}).json()
        with api.db() as conn:
            conn.execute(
                "INSERT INTO messages (conversation_id, role, content, created_at) VALUES (?, 'user', 'secret', 'now')",
                (chat["id"],),
            )
            conn.execute(
                "INSERT INTO processing_jobs (id, document_id, status, stage, created_at, updated_at) VALUES ('job-old', ?, 'ready', 'ready', 'now', 'now')",
                (doc["id"],),
            )
        with patch.object(api, "delete_document_indexes", return_value=["cognora_doc_v2_doc123_test"]):
            response = self.client.delete(f"/api/documents/{doc['id']}")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["deleted_indexes"], ["cognora_doc_v2_doc123_test"])
        self.assertEqual(api.load_docs(), [])
        self.assertFalse((api.UPLOADS / doc["stored_name"]).exists())
        self.assertFalse((api.TEXT_DIR / f"{doc['id']}.md").exists())
        self.assertEqual(self.client.get(f"/api/chats/{chat['id']}/messages").status_code, 404)
        with api.db() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0], 0)
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM processing_jobs").fetchone()[0], 0)

    def test_document_cannot_be_deleted_during_processing(self):
        doc = self.add_document()
        with api.db() as conn:
            conn.execute(
                "INSERT INTO processing_jobs (id, document_id, status, stage, created_at, updated_at) VALUES ('job-active', ?, 'running', 'parsing', 'now', 'now')",
                (doc["id"],),
            )
        with patch.object(api, "delete_document_indexes") as delete_indexes:
            response = self.client.delete(f"/api/documents/{doc['id']}")
        self.assertEqual(response.status_code, 409)
        delete_indexes.assert_not_called()

    def test_processing_job_is_persistent_and_duplicate_requests_reuse_it(self):
        document = self.add_document()
        with patch.object(api.PROCESSING_EXECUTOR, "submit") as submit:
            first = self.client.post(f"/api/documents/{document['id']}/process").json()
            second = self.client.post(f"/api/documents/{document['id']}/process").json()
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["status"], "queued")
        self.assertEqual(submit.call_count, 1)
        persisted = self.client.get(f"/api/processing-jobs/{first['id']}").json()
        self.assertEqual(persisted["document_id"], document["id"])

    def test_retrieval_citations_persist_and_chat_deletes(self):
        document = self.add_document()
        evidence = [{
            "document_id": document["id"], "document_name": document["name"],
            "element_id": "chunk-7", "page": None, "type": "text",
            "text": "Example source passage.",
        }]
        with patch.object(api, "has_index", return_value=True), \
             patch.object(api, "retrieve", return_value=evidence) as retrieval, \
             patch.object(api, "generate_answer", return_value="Supported answer [E1]."):
            chat = self.client.post("/api/chats", json={"document_id": document["id"]}).json()
            answer = self.client.post(
                f"/api/chats/{chat['id']}/messages", json={"content": "What is supported?"}
            )
            self.assertEqual(answer.status_code, 200)
            self.assertEqual(retrieval.call_args.args[0], document["id"])
            history = self.client.get(f"/api/chats/{chat['id']}/messages").json()
            self.assertEqual(len(history), 2)
            self.assertEqual(history[1]["citations"][0]["id"], "chunk-7")

            deleted = self.client.delete(f"/api/chats/{chat['id']}")
            self.assertTrue(deleted.json()["deleted"])
            self.assertEqual(self.client.get(f"/api/chats/{chat['id']}/messages").status_code, 404)

    def test_provider_failure_does_not_append_partial_turn(self):
        document = self.add_document()
        evidence = [{
            "document_id": document["id"], "document_name": document["name"],
            "element_id": "chunk-7", "page": None, "type": "text", "text": "Evidence",
        }]
        with patch.object(api, "has_index", return_value=True), \
             patch.object(api, "retrieve", return_value=evidence), \
             patch.object(api, "generate_answer", side_effect=RuntimeError("provider offline")):
            chat = self.client.post("/api/chats", json={"document_id": document["id"]}).json()
            failed = self.client.post(
                f"/api/chats/{chat['id']}/messages", json={"content": "Question"}
            )
        self.assertEqual(failed.status_code, 502)
        self.assertEqual(self.client.get(f"/api/chats/{chat['id']}/messages").json(), [])

    def test_chat_is_blocked_until_document_index_exists(self):
        document = self.add_document()
        chat = self.client.post("/api/chats", json={"document_id": document["id"]}).json()
        with patch.object(api, "has_index", return_value=False):
            response = self.client.post(
                f"/api/chats/{chat['id']}/messages", json={"content": "Ask"}
            )
        self.assertEqual(response.status_code, 409)


if __name__ == "__main__":
    unittest.main()
