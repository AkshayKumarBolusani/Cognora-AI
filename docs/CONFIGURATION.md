# Configuration

Copy `.env.example` to `.env` at the repository root. Keep credentials server-side; never place provider keys in `VITE_` variables or commit `.env`.

| Variable | Purpose |
| --- | --- |
| `LLM_PROVIDER`, `LLM_MODEL` | Answer provider (`ollama`, `openai`, or `gemini`) and model. |
| `LLM_API_KEY`, `LLM_BASE_URL` | Server-side answer provider key and optional endpoint. Ollama defaults to `http://localhost:11434`. |
| `EMBEDDING_PROVIDER`, `EMBEDDING_MODEL` | Embedding provider and model. The model must support embeddings. |
| `EMBEDDING_API_KEY`, `EMBEDDING_BASE_URL` | Server-side embedding key and optional endpoint. |
| `EMBEDDING_BATCH_SIZE` | Embedding texts per request, clamped to 1–64 (default 16). Lower for memory constrained systems. |
| `VISION_PROVIDER`, `VISION_MODEL` | Optional figure description provider and model. Empty provider disables descriptions. |
| `VISION_API_KEY`, `VISION_BASE_URL` | Server-side vision key and optional endpoint. |
| `RETRIEVAL_TOP_K` | Maximum evidence passages (clamped to 1–20). |
| `RETRIEVAL_SCORE_THRESHOLD` | Minimum vector similarity (clamped to 0–1). |
| `RERANKER_MODEL` | Optional Hugging Face Transformers sequence-classification model used as a local cross-encoder. Empty disables reranking. Example: `cross-encoder/ms-marco-MiniLM-L-6-v2`. |
| `RERANKER_BATCH_SIZE` | Cross-encoder inference batch size (clamped to 1–32; default 8). |
| `CORS_ORIGINS` | Comma-separated exact HTTP(S) frontend origins. Wildcards and URL paths are rejected. |
| `VITE_API_BASE_URL` | Frontend API URL at build/dev time; defaults to `http://localhost:8000/api`. Not a secret. |

Changing the embedding provider or model creates a separate document index namespace; process documents again to populate that namespace. The first parse initializes Docling; its converter remains warm while the API runs. The first reranker use downloads and initializes its model, so the first request can be slower. Choose a model compatible with the installed Transformers version and check its model license before use.

## Provider notes

The default Ollama setup uses `nomic-embed-text` for embeddings and `qwen2.5vl:7b` for answers and optional vision. OpenAI and Gemini can be configured independently for answer, embedding, and vision calls. Cloud providers receive the questions or extracted passages needed for the selected task.
