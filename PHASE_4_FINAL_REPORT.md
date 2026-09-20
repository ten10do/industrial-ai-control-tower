# Phase 4 Final Report — Industrial Knowledge & Evidence RAG

Date: 2026-09-20  
Branch: `main`  
Frozen evaluation commit: `242e872`  
Decision: **Phase 4 PASS**

## Delivered scope

- Independent deterministic industrial knowledge and evidence service; no LLM or agent workflow.
- Curated `industrial-maintenance-corpus-v1`: 13 documents, 769 parsed pages, 2,149 parsed chunk
  rows, and 2,146 unique stable chunk IDs.
- Twelve real public DOE/NREL, ABB, and SKF references plus one explicitly labeled synthetic
  sensor-maintenance record. Sources, revisions, license notes, SHA-256 hashes, and manifest are
  retained; third-party raw PDFs are not committed.
- PDF/Markdown/text parsing, cleaning, heading/page preservation, table-row preservation,
  220-token structure-aware chunks with 35-token overlap, stable IDs, exact duplicate collapse,
  and conflicting-ID rejection.
- PostgreSQL 16 + pgvector 0.8.1 canonical persistence for documents, `VECTOR(384)` chunks, and
  retrieval runs. The locally built Compose image pins and verifies the pgvector source SHA-256.
- Deterministic `KnowledgeQuery` builder for bearing wear, overload, overheating, misalignment,
  and sensor failure; exact equipment/document/model/revision filters.
- BM25, deterministic local dense retrieval, RRF hybrid, and configurable deterministic reranker.
- Traceable evidence with document, stable chunk, page, section, heading, revision, and source URL.
- Deterministic `SUFFICIENT`, `PARTIAL`, and `INSUFFICIENT_EVIDENCE` gate with unconditional
  unsupported-fault refusal.
- Search, document list/get, and Diagnosis v1.1 knowledge-context REST APIs.
- Incremental hash-based ingestion, transactional changed-document replacement, stale removal,
  embedding compatibility checks, and retrieval-run audit persistence.
- Explicit untrusted-document / prompt-injection boundary and failure isolation from diagnosis.

## Corpus integrity

| Property | Result |
|---|---|
| Corpus version | `industrial-maintenance-corpus-v1` |
| Documents | 13 (12 real public sources, 1 labeled synthetic) |
| Parsed pages | 769 |
| Parsed chunk rows | 2,149 |
| Unique persisted chunk IDs | 2,146 |
| Exact repeats collapsed | 3 identical SKF rows |
| Embedding | `local-hash-embedding-v1`, 384 dimensions, L2 normalized |
| Normalized manifest digest in index | `c352b01ddf2d6b3c868f6a4bd5269dbfa49651b12c98ec7601d67a5e36582a47` |
| Tracked manifest file SHA-256 | `0a3d0fe293f57e108be679ac2a8fe7d623600894ac748d87112e2e4dde44ad61` |

Incremental replay returned `inserted=0`, `replaced=0`, `skipped=13`, `chunks=0`,
`duplicates=3`, proving unchanged sources do not rewrite persisted chunks.

## Frozen Eval v1

The formal frozen split was executed once after commit `242e872`: 60 queries, with ten each for
bearing, overload, overheating, misalignment, sensor failure, and unsupported/OOD. It was not
rerun after observing the results.

| Pipeline | Hit@1 | Hit@3 | Recall@5 | MRR | nDCG@5 | p50 ms | p95 ms | Supported accept | OOD reject | FSR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 0.76 | 0.98 | 0.85 | 0.8617 | 0.8267 | 41.84 | 46.84 | 0.98 | 1.00 | 0.00 |
| Dense | 0.70 | 0.82 | 0.73 | 0.7550 | 0.7131 | 76.85 | 79.13 | 0.86 | 1.00 | 0.00 |
| Hybrid RRF | 0.76 | 0.94 | 0.83 | 0.8433 | 0.8232 | 76.57 | 79.77 | 0.98 | 1.00 | 0.00 |
| Hybrid + reranker | 0.84 | 0.94 | 0.82 | 0.8833 | 0.8332 | 80.84 | 84.66 | 0.98 | 1.00 | 0.00 |

BM25 is the selected default because it leads Recall@5, beats hybrid on MRR and nDCG@5, and has
the lowest p95. The reranker improves Hit@1/MRR but loses three Recall@5 points versus BM25 and
adds about 37.8 ms p95, so it remains disabled by default. All pipelines had false-insufficient
rate 0.00; one supported BM25 sensor query was `PARTIAL`, not insufficient. All ten OOD queries
were rejected and False Sufficient Rate was 0.00.

## Real Compose integration

The isolated `iact-phase4-live` stack used PostgreSQL+pgvector, Redis, Mosquitto, backend, and the
real Phase 3 model artifact.

1. Simulator/MQTT produced 470 persisted telemetry rows.
2. Diagnosis v1.1 produced 91 persisted diagnosis rows.
3. Fault contexts were retrieved for `BEARING_WEAR`, `OVERLOAD`, and `MISALIGNMENT`.
4. Each returned cited evidence from an expected real industrial reference. Bearing evidence was
   conservatively `PARTIAL`; overload and misalignment were `SUFFICIENT`.
5. A `QUANTUM_TELEPORT` fault returned `INSUFFICIENT_EVIDENCE` before scoring.
6. Exactly four new `retrieval_runs` records persisted the three contexts and one refusal.

Runtime checks:

- `/ready`: PostgreSQL `ok`, Redis `ok`, MQTT `connected`, diagnosis `loaded`, knowledge `indexed`.
- pgvector extension: `0.8.1`.
- Alembic: `20260920_03 (head)`; `alembic check` reported no new operations.
- Database: 13 documents, 2,146 chunks.
- Missing-index instance: `/ready` remained HTTP 200 with diagnosis `loaded` and knowledge
  `unavailable`; latest diagnosis remained readable; knowledge search returned HTTP 503
  `INDEX_NOT_AVAILABLE`.

## Regression evidence

| Area | Result |
|---|---|
| Backend | Ruff + format + strict mypy; 16 tests passed |
| ML | Ruff + format + strict mypy; 16 tests passed |
| Simulator | Ruff + format + strict mypy; 24 tests passed |
| Frontend | ESLint; 1 test passed; TypeScript/Vite production build passed |
| Phase 3 live gate | PASS: 470 telemetry / 91 diagnoses with three target fault classes |
| Phase 4 live gate | PASS: three cited contexts + deterministic unsupported refusal |
| Docker | PostgreSQL/pgvector, backend, and simulator images built; live stack healthy |
| Python container dependencies | `pip check`: no broken requirements |

The final all-service Docker build reached and passed the frontend application build, but the
Docker registry stalled while downloading the nginx runtime base layer. This external pull did
not affect the already-running Phase 4 stack or the standalone frontend production build.

## Known limitations

- The corpus is intentionally small and dominated by public English references; facility-specific
  manuals, revision governance, multilingual queries, OCR, and access control need later work.
- The signed-hash embedding is deterministic and local, not a domain-trained semantic model.
- Retrieval runs in process over a bounded immutable artifact while pgvector is canonical durable
  storage; ANN/server-side vector search should be introduced only after corpus/load measurements.
- Phase 3 fault data is synthetic, so end-to-end success is an engineering validation rather than
  field accuracy evidence.
- The frontend dependency tree reports four existing npm audit findings (2 moderate, 1 high,
  1 critical); resolving them may require breaking dependency upgrades and is outside Phase 4.
- No LLM answer synthesis, multi-agent planning, safety-agent decision, human approval, or work
  order execution was added.

## Exit decision

All Phase 4 functional, evaluation, refusal, persistence, traceability, integration, degradation,
and regression gates are satisfied. Remaining limitations are explicitly bounded and do not
invalidate the Phase 4 evidence-service contract.

**Phase 5: READY**

