# Industrial Knowledge and Evidence Retrieval

## Scope

Phase 4 is a deterministic retrieval and evidence service over industrial motor, bearing, and
maintenance references. It consumes either free text or the structured output of the Phase 3
diagnosis engine. It does not use an LLM, generate maintenance plans, or execute industrial
actions.

## Runtime flow

```text
Diagnosis v1.1
  -> deterministic KnowledgeQuery
  -> metadata filters
  -> BM25 / dense / hybrid / hybrid+reranker
  -> cited EvidenceItem[]
  -> deterministic sufficiency gate
  -> retrieval_runs audit record
```

The query builder supports `BEARING`, `OVERLOAD`, `OVERHEATING`, `MISALIGNMENT`, and
`SENSOR_FAILURE`. It maps fault type, symptoms, severity, objective, equipment type, and optional
device model into stable lexical terms and a semantic query. Unknown fault types are marked
unsupported before scoring.

## Retrieval

Four pipelines remain callable for comparison:

- `bm25` — selected default after Frozen Eval v1.
- `dense` — exact cosine similarity over a deterministic, local 384-dimensional signed-hash
  embedding (`local-hash-embedding-v1`, L2 normalized).
- `hybrid` — reciprocal-rank fusion of the top lexical and dense candidates.
- `hybrid_rerank` — deterministic exact-term and coverage reranking over hybrid candidates.

Filters are exact matches for equipment type, document type, model, and revision. Empty results
are explicit and never bypass the sufficiency gate.

## Evidence and sufficiency

Each result includes document ID/title, stable chunk ID, page, section, heading, source URL,
revision, retrieval score, optional rerank score, text excerpt, and a citation object. The service
never converts a citation-free statement into evidence.

The deterministic gate returns:

- `SUFFICIENT` when relevance, term coverage, supporting-chunk count, and metadata match all pass.
- `PARTIAL` for a plausible but incomplete match.
- `INSUFFICIENT_EVIDENCE` for unsupported faults, no filter match, or weak evidence.

Unsupported fault types are rejected unconditionally, even if generic words happen to match a
document. This makes false sufficiency an explicit safety metric.

## Availability and failure semantics

Knowledge is an optional capability. If its index is missing, corrupt, or embedding-incompatible,
`/ready` reports knowledge as `unavailable`, but PostgreSQL/Redis readiness and Phase 3 diagnosis
continue independently. Knowledge search returns `503 INDEX_NOT_AVAILABLE`; invalid query shape
returns `422 UNSUPPORTED_QUERY`; an internal retrieval failure returns `500 SEARCH_FAILED`.

The corpus artifact is immutable for a running process. Reindex, validate, ingest, then restart to
activate a new version. Retrieval runs persist the built query, filters, pipeline/corpus/embedding
versions, candidates, selected evidence, sufficiency result, and latency.

## Evaluation discipline

The tracked `eval_queries_v1.json` contains a development group and a frozen set of exactly 60
queries: ten each for bearing, overload, overheating, misalignment, sensor failure, and unsupported
out-of-domain requests. Every query has document/section/chunk relevance labels and a support flag.
The frozen set was evaluated once after commit `242e872`; it must not be tuned against or rerun as
a development split. See `docs/evaluation/PHASE4_RAG_EVALUATION.md`.
