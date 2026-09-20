"""Stable Phase 4 query, evidence, citation, and sufficiency contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SufficiencyStatus(StrEnum):
    SUFFICIENT = "SUFFICIENT"
    PARTIAL = "PARTIAL"
    INSUFFICIENT = "INSUFFICIENT_EVIDENCE"


class KnowledgeFilters(BaseModel):
    equipment_type: str | None = None
    document_type: str | None = None
    model: str | None = None
    revision: str | None = None


class KnowledgeQuery(BaseModel):
    device_type: str = "industrial_motor"
    fault_type: str
    severity: str | None = None
    symptoms: list[str] = Field(default_factory=list, max_length=20)
    objective: str = "troubleshooting"
    device_model: str | None = None


class BuiltQuery(BaseModel):
    search_terms: list[str]
    exact_terms: list[str]
    semantic_query: str
    filters: KnowledgeFilters
    supported_fault: bool


class KnowledgeSearchRequest(BaseModel):
    query: str | None = Field(default=None, min_length=3, max_length=2_000)
    knowledge_query: KnowledgeQuery | None = None
    filters: KnowledgeFilters = Field(default_factory=KnowledgeFilters)
    top_k: int = Field(default=5, ge=1, le=20)
    pipeline: Literal["bm25", "dense", "hybrid", "hybrid_rerank"] | None = None


class Citation(BaseModel):
    document: str
    page: int | None
    section: str | None
    source: str


class EvidenceItem(BaseModel):
    evidence_id: str
    document_id: str
    chunk_id: str
    document_title: str
    page: int | None
    section: str | None
    heading: str | None
    text: str
    retrieval_score: float
    rerank_score: float | None
    source: str
    revision: str | None
    citation: Citation


class SufficiencyAssessment(BaseModel):
    status: SufficiencyStatus
    reasons: list[str]
    top_score: float
    score_margin: float
    supporting_chunks: int
    source_diversity: int
    query_coverage: float
    metadata_match: bool


class KnowledgeSearchResponse(BaseModel):
    retrieval_run_id: UUID | None
    pipeline: str
    corpus_version: str
    embedding_version: str
    query: BuiltQuery
    evidence: list[EvidenceItem]
    sufficiency: SufficiencyAssessment
    latency_ms: float


class KnowledgeContextRequest(BaseModel):
    diagnosis_id: UUID | None = None
    top_k: int = Field(default=5, ge=1, le=20)


class KnowledgeContextResponse(KnowledgeSearchResponse):
    diagnosis_id: UUID
    device_id: str


class KnowledgeDocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_id: str
    title: str
    vendor: str
    document_type: str
    equipment_type: str
    model: str | None
    revision: str | None
    publication_date: str | None
    source: str
    source_type: str
    license_note: str
    sha256: str
    corpus_version: str
    page_count: int
    chunk_count: int
    ingested_at: datetime


class IndexedChunk(BaseModel):
    chunk_id: str
    document_id: str
    document_title: str
    text: str
    page: int | None
    section: str | None
    heading: str | None
    document_type: str
    equipment_type: str
    model: str | None
    source: str
    revision: str | None
    chunk_index: int
    content_hash: str
    embedding: list[float]


class IndexArtifact(BaseModel):
    index_version: str
    corpus_version: str
    corpus_manifest_sha256: str
    embedding_model: str
    embedding_dimension: int
    embedding_normalization: str
    created_at: str
    documents: list[dict[str, Any]]
    chunks: list[IndexedChunk]
