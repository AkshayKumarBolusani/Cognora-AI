import unittest
from types import SimpleNamespace
from unittest.mock import patch

from src.ui import retrieval


class FakeQdrant:
    def __init__(self, *_args, **_kwargs):
        self.deleted = False

    def collection_exists(self, _name):
        return True

    def count(self, _name, exact=True):
        return SimpleNamespace(count=1)

    def get_collection(self, _name):
        return SimpleNamespace(config=SimpleNamespace(
            params=SimpleNamespace(vectors=SimpleNamespace(size=3))
        ))

    def query_points(self, **_kwargs):
        return SimpleNamespace(points=[
            SimpleNamespace(payload={"document_id": "doc-a", "element_id": "a"}),
            SimpleNamespace(payload={"document_id": "doc-b", "element_id": "b"}),
        ])

    def delete_collection(self, _name):
        self.deleted = True
        raise AssertionError("Existing collections must never be deleted")

    def close(self):
        pass


class NewFakeQdrant:
    def __init__(self, *_args, **_kwargs):
        self.points = []

    def collection_exists(self, _name):
        return False

    def create_collection(self, **_kwargs):
        pass

    def upsert(self, **kwargs):
        self.points = kwargs["points"]

    def close(self):
        pass


class RetrievalTests(unittest.TestCase):
    def test_table_embedding_adds_headers_without_replacing_original_table(self):
        table = "| Date | Revenue |\n|---|---:|\n| FY26 | 42 |"
        result = retrieval._element_chunks([{
            "text": table, "page": 12, "type": "table", "element_id": "#/tables/2",
        }])[0]
        self.assertIn("Table with columns: Date, Revenue.", result["embedding_text"])
        self.assertEqual(result["text"], table)

    def test_element_chunking_preserves_page_and_kind(self):
        result = retrieval._element_chunks([{
            "text": "Quarterly revenue and costs.", "page": 12,
            "type": "table", "element_id": "#/tables/2",
        }])
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["page"], 12)
        self.assertEqual(result[0]["type"], "table")
        self.assertEqual(result[0]["element_id"], "#/tables/2")

    def test_collection_is_scoped_by_document_model_and_content(self):
        with patch.dict("os.environ", {"EMBEDDING_PROVIDER": "ollama", "EMBEDDING_MODEL": "nomic-embed-text"}):
            baseline = retrieval._collection("doc-a", "text one")
            self.assertNotEqual(baseline, retrieval._collection("doc-b", "text one"))
            self.assertNotEqual(baseline, retrieval._collection("doc-a", "text two"))
            with patch.dict("os.environ", {"EMBEDDING_PROVIDER": "openai", "EMBEDDING_MODEL": "text-embedding-3-small"}):
                self.assertNotEqual(baseline, retrieval._collection("doc-a", "text one"))

    def test_existing_index_is_reused_without_mutation(self):
        import qdrant_client

        with patch.object(qdrant_client, "QdrantClient", FakeQdrant), \
             patch.object(retrieval, "_embed", side_effect=AssertionError("should reuse index")):
            count = retrieval.index_document("doc-a", "file.pdf", "A short source passage.")
        self.assertEqual(count, 1)

    def test_retrieval_filters_evidence_to_selected_document(self):
        import qdrant_client

        with patch.object(qdrant_client, "QdrantClient", FakeQdrant), \
             patch.object(retrieval, "_embed", return_value=[[0.1, 0.2, 0.3]]):
            results = retrieval.retrieve("doc-a", "question", "source text", top_k=4, threshold=0.2)
        self.assertEqual(results, [{"document_id": "doc-a", "element_id": "a"}])

    def test_embedding_dimension_mismatch_fails_before_query(self):
        import qdrant_client

        with patch.object(qdrant_client, "QdrantClient", FakeQdrant), \
             patch.object(retrieval, "_embed", return_value=[[0.1, 0.2]]):
            with self.assertRaisesRegex(ValueError, "Embedding dimension mismatch"):
                retrieval.retrieve("doc-a", "question", "source text")

    def test_indexing_sends_text_only_to_embedding_provider(self):
        import qdrant_client

        with patch.object(qdrant_client, "QdrantClient", NewFakeQdrant), \
             patch.object(retrieval, "_embed", return_value=[[0.1, 0.2, 0.3]]) as embed:
            retrieval.index_document(
                "doc-new", "file.pdf", "A short source passage.",
                elements=[{"text": "A short source passage.", "page": 2, "type": "text", "element_id": "p2"}],
            )
        self.assertEqual(embed.call_args.args[0], ["A short source passage."])

    def test_embeddings_are_sent_in_bounded_batches(self):
        with patch.dict("os.environ", {"EMBEDDING_BATCH_SIZE": "16"}), patch.object(
            retrieval, "_embed_batch",
            side_effect=lambda batch: [[float(len(batch))] for _ in batch],
        ) as embed:
            vectors = retrieval._embed([f"text {i}" for i in range(35)])
        self.assertEqual(len(vectors), 35)
        self.assertEqual([len(call.args[0]) for call in embed.call_args_list], [16, 16, 3])


if __name__ == "__main__":
    unittest.main()
