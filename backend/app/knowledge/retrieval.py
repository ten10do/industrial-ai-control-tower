"""BM25, local dense retrieval, reciprocal-rank fusion, reranking, and sufficiency."""

from __future__ import annotations

import math
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from app.knowledge.contracts import (
    BuiltQuery,
    Citation,
    EvidenceItem,
    IndexArtifact,
    IndexedChunk,
    KnowledgeSearchResponse,
    SufficiencyAssessment,
    SufficiencyStatus,
)
from app.knowledge.embedding import MODEL_VERSION, cosine, embed, tokenize

PIPELINE_VERSION = "hybrid-rrf-v1"
DEFAULT_PIPELINE = "hybrid"
RRF_K = 60


@dataclass(frozen=True)
class RankedChunk:
    chunk: IndexedChunk
    score: float
    rerank_score: float | None = None


class BM25:
    def __init__(self, chunks: list[IndexedChunk]) -> None:
        self.tokens = [tokenize(f"{chunk.heading or ''} {chunk.text}") for chunk in chunks]
        self.lengths = [len(row) for row in self.tokens]
        self.average_length = sum(self.lengths) / max(1, len(self.lengths))
        frequencies: Counter[str] = Counter()
        for row in self.tokens:
            frequencies.update(set(row))
        self.idf = {
            term: math.log(1.0 + (len(chunks) - count + 0.5) / (count + 0.5))
            for term, count in frequencies.items()
        }

    def score(self, query: str) -> list[float]:
        query_terms = tokenize(query)
        scores: list[float] = []
        for row, length in zip(self.tokens, self.lengths, strict=True):
            counts = Counter(row)
            score = 0.0
            for term in query_terms:
                frequency = counts[term]
                if not frequency:
                    continue
                denominator = frequency + 1.5 * (
                    1.0 - 0.75 + 0.75 * length / max(1.0, self.average_length)
                )
                score += self.idf.get(term, 0.0) * frequency * 2.5 / denominator
            scores.append(score)
        return scores


def _matches(chunk: IndexedChunk, query: BuiltQuery) -> bool:
    filters = query.filters
    if filters.equipment_type and chunk.equipment_type != filters.equipment_type:
        return False
    if filters.document_type and chunk.document_type != filters.document_type:
        return False
    if filters.model and chunk.model != filters.model:
        return False
    return not (filters.revision and chunk.revision != filters.revision)


def _normalized(scores: list[float]) -> list[float]:
    top = max(scores, default=0.0)
    return [max(0.0, value) / top if top > 0 else 0.0 for value in scores]


def _rank(scores: list[float], allowed: list[bool]) -> list[int]:
    return sorted(
        (index for index, accepted in enumerate(allowed) if accepted and scores[index] > 0),
        key=lambda index: (-scores[index], index),
    )


def _term_coverage(query: BuiltQuery, text: str) -> float:
    query_tokens = set(tokenize(" ".join(query.search_terms + query.exact_terms)))
    if not query_tokens:
        query_tokens = set(tokenize(query.semantic_query))
    text_tokens = set(tokenize(text))
    return len(query_tokens & text_tokens) / max(1, len(query_tokens))


class KnowledgeIndex:
    def __init__(self, artifact: IndexArtifact) -> None:
        if artifact.embedding_model != MODEL_VERSION:
            raise ValueError("embedding model does not match the runtime")
        self.artifact = artifact
        self.chunks = artifact.chunks
        self.bm25 = BM25(self.chunks)

    @classmethod
    def load(cls, path: Path) -> KnowledgeIndex:
        return cls(IndexArtifact.model_validate_json(path.read_text(encoding="utf-8")))

    def _ranked(self, query: BuiltQuery, pipeline: str) -> list[RankedChunk]:
        allowed = [_matches(chunk, query) for chunk in self.chunks]
        lexical_raw = self.bm25.score(query.semantic_query)
        lexical = _normalized(lexical_raw)
        query_vector = embed(query.semantic_query)
        dense_raw = [max(0.0, cosine(query_vector, chunk.embedding)) for chunk in self.chunks]
        dense = _normalized(dense_raw)
        if pipeline == "bm25":
            return [
                RankedChunk(self.chunks[index], lexical[index]) for index in _rank(lexical, allowed)
            ]
        if pipeline == "dense":
            return [
                RankedChunk(self.chunks[index], dense[index]) for index in _rank(dense, allowed)
            ]

        fused: defaultdict[int, float] = defaultdict(float)
        for ranking in (_rank(lexical, allowed), _rank(dense, allowed)):
            for position, index in enumerate(ranking[:50], start=1):
                fused[index] += 1.0 / (RRF_K + position)
        ranking = sorted(fused, key=lambda index: (-fused[index], index))
        top_fused = max(fused.values(), default=1.0)
        hybrid = [RankedChunk(self.chunks[index], fused[index] / top_fused) for index in ranking]
        if pipeline != "hybrid_rerank":
            return hybrid
        reranked: list[RankedChunk] = []
        exact_terms = [term for term in query.exact_terms if term]
        for item in hybrid[:30]:
            text = f"{item.chunk.heading or ''} {item.chunk.text}".lower()
            exact = sum(term in text for term in exact_terms) / max(1, len(exact_terms))
            coverage = _term_coverage(query, text)
            score = 0.72 * item.score + 0.20 * coverage + 0.08 * exact
            reranked.append(RankedChunk(item.chunk, item.score, min(1.0, score)))
        return sorted(reranked, key=lambda item: (-(item.rerank_score or 0.0), item.chunk.chunk_id))

    def search(
        self,
        query: BuiltQuery,
        *,
        top_k: int = 5,
        pipeline: str = DEFAULT_PIPELINE,
        run_id: UUID | None = None,
    ) -> KnowledgeSearchResponse:
        started = time.perf_counter()
        ranked = self._ranked(query, pipeline)[:top_k]
        evidence = [self._evidence(item) for item in ranked]
        sufficiency = self._sufficiency(query, ranked)
        return KnowledgeSearchResponse(
            retrieval_run_id=run_id,
            pipeline=pipeline,
            corpus_version=self.artifact.corpus_version,
            embedding_version=self.artifact.embedding_model,
            query=query,
            evidence=evidence,
            sufficiency=sufficiency,
            latency_ms=(time.perf_counter() - started) * 1000.0,
        )

    @staticmethod
    def _evidence(item: RankedChunk) -> EvidenceItem:
        chunk = item.chunk
        return EvidenceItem(
            evidence_id=f"ev-{chunk.chunk_id}",
            document_id=chunk.document_id,
            chunk_id=chunk.chunk_id,
            document_title=chunk.document_title,
            page=chunk.page,
            section=chunk.section,
            heading=chunk.heading,
            text=chunk.text,
            retrieval_score=round(item.score, 6),
            rerank_score=round(item.rerank_score, 6) if item.rerank_score is not None else None,
            source=chunk.source,
            revision=chunk.revision,
            citation=Citation(
                document=chunk.document_title,
                page=chunk.page,
                section=chunk.section,
                source=chunk.source,
            ),
        )

    @staticmethod
    def _sufficiency(query: BuiltQuery, ranked: list[RankedChunk]) -> SufficiencyAssessment:
        if not query.supported_fault:
            return SufficiencyAssessment(
                status=SufficiencyStatus.INSUFFICIENT,
                reasons=["fault type is outside the supported knowledge domain"],
                top_score=0.0,
                score_margin=0.0,
                supporting_chunks=0,
                source_diversity=0,
                query_coverage=0.0,
                metadata_match=False,
            )
        if not ranked:
            return SufficiencyAssessment(
                status=SufficiencyStatus.INSUFFICIENT,
                reasons=["no chunks matched the query and metadata filters"],
                top_score=0.0,
                score_margin=0.0,
                supporting_chunks=0,
                source_diversity=0,
                query_coverage=0.0,
                metadata_match=False,
            )
        coverages = [_term_coverage(query, item.chunk.text) for item in ranked]
        coverage = max(coverages)
        dense_relevance = max(
            max(0.0, cosine(embed(query.semantic_query), item.chunk.embedding)) for item in ranked
        )
        top_score = min(1.0, 0.70 * coverage + 0.30 * dense_relevance)
        supporting = sum(value >= 0.16 for value in coverages)
        sources = len(
            {
                item.chunk.document_id
                for item in ranked
                if _term_coverage(query, item.chunk.text) >= 0.16
            }
        )
        margin = ranked[0].score - (ranked[1].score if len(ranked) > 1 else 0.0)
        metadata_match = all(_matches(item.chunk, query) for item in ranked)
        reasons = [
            f"top relevance={top_score:.3f}",
            f"query coverage={coverage:.3f}",
            f"supporting chunks={supporting}",
            f"source diversity={sources}",
        ]
        if top_score >= 0.38 and coverage >= 0.30 and supporting >= 2 and metadata_match:
            status = SufficiencyStatus.SUFFICIENT
        elif top_score >= 0.28 and coverage >= 0.18 and supporting >= 1 and metadata_match:
            status = SufficiencyStatus.PARTIAL
        else:
            status = SufficiencyStatus.INSUFFICIENT
        return SufficiencyAssessment(
            status=status,
            reasons=reasons,
            top_score=round(top_score, 6),
            score_margin=round(margin, 6),
            supporting_chunks=supporting,
            source_diversity=sources,
            query_coverage=round(coverage, 6),
            metadata_match=metadata_match,
        )
