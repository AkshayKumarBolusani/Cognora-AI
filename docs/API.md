# API reference

The running service's interactive OpenAPI specification at `/docs` is authoritative. Routes below are relative to `/api`.

| Method | Route | Purpose |
| --- | --- | --- |
| `GET` | `/health` | Service health. |
| `GET` | `/documents` | List documents and effective processing readiness. |
| `POST` | `/documents` | Upload a supported file. |
| `GET` | `/documents/{id}/file` | Stream the original document. |
| `GET` | `/documents/{id}/preview` | Return a supported preview. |
| `POST` | `/documents/{id}/process` | Queue or reuse a processing job. `?force=true` refreshes analysis. |
| `GET` | `/processing-jobs/{id}` | Read persistent processing progress. |
| `DELETE` | `/documents/{id}` | Permanently delete the document and associated app data. |
| `GET` | `/documents/{id}/chats` | List conversations for a document. |
| `POST` | `/chats` | Create a conversation with `{ "document_id": "…" }`. |
| `GET` | `/chats/{id}/messages` | Read conversation messages and citations. |
| `POST` | `/chats/{id}/messages` | Ask a question with `{ "content": "…", "document_ids": ["…"] }`. `document_ids` is optional; at most ten processed documents can be selected. |
| `DELETE` | `/chats/{id}` | Permanently delete a conversation and messages. |
| `GET` | `/documents/{id}/figures/{figure_id}` | Retrieve an extracted PDF figure image. |

Uploads are limited to 200 MB and validated against the supported filename extensions. Document processing is asynchronous; poll the returned job ID until its status is `completed` or `failed`. Chat requests are rejected until extraction and indexing succeed. Citation objects include the document ID/name, page when available, source element ID, and source type.

The API currently has no authentication or user accounts. Bind it to localhost for personal use; a shared or public deployment needs authentication, authorization, rate limits, and a deployment-specific security review.
