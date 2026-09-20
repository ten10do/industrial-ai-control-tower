# Phase 4 Knowledge Corpus

## Frozen corpus v1

`industrial-maintenance-corpus-v1` contains 13 documents, 769 parsed pages, and 2,149 parsed chunk
rows (2,146 unique stable chunk IDs). Three repeated SKF rows are byte-identical at the same
page/location and collapse to one row each at the persistence boundary. Any duplicate ID with
different content is rejected. Twelve documents are real public industrial references from the U.S. Department of
Energy/NREL, ABB, and SKF. One local maintenance record is synthetic and explicitly marked
`source_type=synthetic`; it exists only to cover the sensor-validation category and is never
presented as a vendor manual.

The tracked manifest is `backend/knowledge/knowledge_corpus_manifest.json`. The normalized
manifest digest embedded in the index is
`c352b01ddf2d6b3c868f6a4bd5269dbfa49651b12c98ec7601d67a5e36582a47`. The byte-level SHA-256 of
the pretty-printed tracked manifest is
`0a3d0fe293f57e108be679ac2a8fe7d623600894ac748d87112e2e4dde44ad61`.

## Provenance and redistribution

Every document record includes a stable ID, title, vendor, document type, equipment type, model,
revision, publication date, original HTTPS source, source type, license note, SHA-256, page count,
and chunk count. Raw third-party PDFs are downloaded for local indexing and intentionally excluded
from Git. ABB and SKF material is not redistributed by this repository. Operators must review the
source terms before redistributing any document.

`backend/knowledge/source_catalog.json` is the source allow-list. Downloads require HTTPS, reject
oversized files, verify the PDF signature, and reject duplicate document hashes. A local path is
accepted only for an entry explicitly labeled synthetic.

## Parsing and chunk identity

- PDF is parsed page by page; Markdown and text use their native headings.
- Repeated whitespace and control characters are normalized.
- Headings and page/section locations are retained.
- Table-like lines are kept intact so row/column labels stay with their values.
- Chunks target 220 tokens with 35-token overlap and respect structural boundaries.
- A stable chunk ID derives from document ID, page, heading, and content hash. Rebuilding an
  unchanged source preserves its chunk IDs.

## Reindexing

Build the corpus and local artifact from the backend environment:

```bash
python -m app.knowledge.corpus
alembic upgrade head
python -m app.knowledge.ingest --path knowledge/index-v1.json
```

Ingestion validates embedding compatibility before database writes. Identical duplicate stable IDs
are stored once and conflicting duplicates fail the transaction. Unchanged document hashes are
skipped, a changed document replaces only its affected chunks, stale documents are removed, and
all changes commit transactionally. The Docker backend runs the same ingestion with `--if-present`
before serving.

## Security boundary

Document text is untrusted data. Retrieval returns excerpts and citations; it does not execute
instructions found in documents, interpolate them into shell/SQL, or grant tool access. A future
LLM consumer must delimit evidence as untrusted quoted material and keep system policy, safety
rules, and execution authorization outside the retrieved context. Source URLs are provenance, not
instructions to fetch arbitrary runtime content.
