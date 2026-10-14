# Security notes

## Intended deployment

The current API has no authentication or user authorization. It is designed for a local, single-user workspace. Keep Uvicorn bound to localhost. Do not expose it through a router, public tunnel, or reverse proxy without adding authentication, authorization, rate limits, and a deployment-specific security review.

## Existing controls

- Upload names are reduced to a basename for both POSIX and Windows-style paths; files are stored beneath a UUID-prefixed path.
- Upload reads are capped at 200 MB and extensions are checked against the supported list. Client-provided MIME types are not treated as trusted evidence of file contents.
- CORS allows the local development origins and optional exact HTTP(S) origins from `CORS_ORIGINS`; wildcard origins are rejected because credentials are enabled.
- Provider credentials are read server-side from `.env`; `.env` and generated user data are ignored by Git.
- Document-specific Qdrant collections, extracted text, uploads, chats, and citations are removed on document deletion. The standalone public TCS experiment index is outside the upload registry.

These controls are not a substitute for hostile-file sandboxing or network-facing security controls. Parsers and model libraries process user-supplied content. Keep dependencies current and only process files you are willing to send to configured providers. Cloud provider configurations transmit questions or extracted evidence to those services.

## Before publishing

Run the full-history secret scan described in [the evaluation and maintenance guide](../eval/README.md#repository-hygiene). Remove real credentials from the repository and rotate them; deleting a secret in a later commit does not remove it from Git history. Keep personal documents, screenshots, local databases, extracted content, and vector indexes out of commits.
