# Phase 4 Frozen Retrieval Evaluation

## Protocol

The corpus and evaluator were frozen at commit `242e872`. The formal `frozen_eval` split was run
once: 60 queries, comprising ten queries for each of five supported fault categories and ten
unsupported/OOD queries. The selected metrics are document/chunk relevance Hit@1, Hit@3,
Recall@5, MRR, nDCG@5, process-local latency, supported acceptance, unsupported rejection, and
False Sufficient Rate (FSR).

## Results

| Pipeline | Hit@1 | Hit@3 | Recall@5 | MRR | nDCG@5 | p50 ms | p95 ms | Supported acceptance | OOD rejection | FSR |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| BM25 | 0.76 | 0.98 | 0.85 | 0.8617 | 0.8267 | 41.84 | 46.84 | 0.98 | 1.00 | 0.00 |
| Dense | 0.70 | 0.82 | 0.73 | 0.7550 | 0.7131 | 76.85 | 79.13 | 0.86 | 1.00 | 0.00 |
| Hybrid RRF | 0.76 | 0.94 | 0.83 | 0.8433 | 0.8232 | 76.57 | 79.77 | 0.98 | 1.00 | 0.00 |
| Hybrid + reranker | 0.84 | 0.94 | 0.82 | 0.8833 | 0.8332 | 80.84 | 84.66 | 0.98 | 1.00 | 0.00 |

False insufficient rate was 0.00 for all pipelines. One supported BM25 query (`sensor-09`) was
`PARTIAL`, not `INSUFFICIENT_EVIDENCE`; all ten OOD queries were rejected.

## Selection

BM25 is the Phase 4 default. It has the best Recall@5 (0.85), lower p95 latency by at least 32 ms,
and better MRR and nDCG@5 than hybrid RRF. The reranker improves Hit@1 and MRR, but reduces
Recall@5 to 0.82 and adds about 37.8 ms p95 over BM25, so it remains configurable and disabled by
default. Dense and hybrid are retained as measured alternatives rather than removed after losing
the benchmark.

These results measure a small, curated corpus and deterministic local embedding on one development
host. They are not claims about production throughput, multilingual retrieval, or accuracy on a
facility's private manuals.

