# Phase 4 Retrieval Error Analysis

## Observed errors

BM25's frozen Hit@1 misses concentrate in overload and overheating queries, with one alignment
case. The strict expected document fell outside the top three for `overload-02`, `overload-09`,
`heat-02` (rank four), `heat-06`, `heat-09` (rank four), and `align-07`. Several apparent strict
document misses still returned another relevance-labeled document, which is why aggregate Hit@3
is 0.98 while exact expected-document inspection looks worse.

The common causes are:

- multiple authoritative manuals describe the same motor symptom with similar vocabulary;
- short fact sheets compete with broader handbooks for lexical terms;
- expected-document labels are sometimes narrower than the set of practically useful sources;
- the local signed-hash embedding does not add enough semantic separation to offset its latency.

No frozen failure was caused by a metadata-filter violation. All returned chunks honored their
equipment/document/model/revision filters. `sensor-09` returned the correct synthetic maintenance
record but only one sufficiently strong supporting passage, so the gate conservatively returned
`PARTIAL`.

## Safety errors

All ten unsupported/OOD queries returned `INSUFFICIENT_EVIDENCE`: false sufficient rate 0.00.
There were no false-insufficient supported results; the one non-sufficient supported result was
explicitly partial. This is the intended asymmetry: unsupported claims are rejected before generic
lexical overlap can create apparent authority.

## Reranker regression

The deterministic reranker increased Hit@1 from 0.76 to 0.84 and MRR from 0.8617 to 0.8833, but
reduced Recall@5 from 0.85 to 0.82. Its exact-term preference can pull a narrowly matching chunk
ahead while dropping a broader relevant source from the first five. Its p95 latency also increased
from 46.84 ms to 84.66 ms. It is therefore not the default.

## Follow-up, without frozen-set tuning

Future improvement should add a new versioned corpus and a newly held-out evaluation split, then
test section-aware relevance judgments, domain-trained embeddings, and diversity-aware reranking.
The Phase 4 frozen labels and thresholds must not be edited to make these reported numbers better.

