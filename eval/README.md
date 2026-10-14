# TCS document QA evaluation

`tcs_questions.jsonl` is a fixed, checked-in set of 30 questions based on the public TCS Integrated Annual Report FY2025-26 retained at `data/pdfs/tcs-annual-report-fy2025-26.pdf`. It contains 10 prose questions, 10 financial table questions, and 10 chart questions. Each row includes an expected-answer pattern, expected PDF page, and a short gold-evidence description. Table facts on pages 166–167 were visually checked against the tracked page images and `data/tables/verified-financial-values.json`; chart answers on pages 6 and 59 were checked against the original extracted figure images. Prose facts are labeled from extracted report text and corresponding source pages.

## Run

Start the API and frontend provider first, then run from the repository root:

```bash
.venv/bin/python scripts/run_evaluation.py
```

The default run uploads and processes the public TCS report, runs each question in a fresh chat, deletes each chat, writes `eval/latest-results.csv`, and deletes the temporary document when it finishes. The generated CSV is ignored by Git. If you already have a processed copy, pass `--document-id ID`; it will not be deleted. Pass `--keep-document` only if you want to inspect the temporary uploaded report in the app.

The initial Docling parse and embedding/index job can take a while. The answer provider and embedding provider must be configured and reachable. Use the same provider/model configuration when comparing retrieval settings.

## Scoring

- **Answer match:** the generated answer contains a question-specific regular-expression pattern. This is a lightweight automatic check, not a semantic judge.
- **Citation page:** at least one citation points to a labeled source page.
- **Citation evidence anchor:** at least one citation's underlying source text contains the expected answer pattern. This checks the citation's evidence content, not visual bounding-box accuracy or exact PDF text highlight placement.

The script reports each metric separately overall and by question category. Keep the question set fixed and record the commit, answer/embedding/vision model names, `RETRIEVAL_*` values, and `RERANKER_MODEL` when publishing a run. The score is specific to this sample, parser configuration, model, and matching rule; it should not be presented as general product accuracy.

## Results status

No model score is checked in yet. An end-to-end run was attempted, but the local API became unreachable during full-report parsing while another document job was already active. The run ended before any question was scored, and its temporary public-report upload was removed. No accuracy number can be reported from this attempt. Do not publish a score until the script completes successfully; include the commit and exact configuration with that run.

## Repository hygiene

The evaluation report is public sample data, but the local workspace can also contain private documents, extracted text, indexes, databases, screenshots, and secrets. Before pushing changes, scan every reachable Git commit without printing matched secret values. If a secret is found, remove it from history and rotate it. For example, use `gitleaks git --redact --verbose .` or `trufflehog git file://. --only-verified`; inspect findings before publication. A scan of the current working tree alone does not cover Git history.
