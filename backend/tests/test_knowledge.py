"""Phase 4 deterministic retrieval, traceability, and refusal tests."""

from pathlib import Path

from app.knowledge.contracts import (
    BuiltQuery,
    IndexArtifact,
    IndexedChunk,
    KnowledgeFilters,
    KnowledgeQuery,
    SufficiencyStatus,
)
from app.knowledge.corpus import chunk_blocks, parse_document
from app.knowledge.embedding import DIMENSION, MODEL_VERSION, NORMALIZATION, embed
from app.knowledge.ingest import deduplicate_chunks
from app.knowledge.query import build_query
from app.knowledge.retrieval import KnowledgeIndex


def _document() -> dict[str, str | None]:
    return {
        "document_id": "manual-1",
        "title": "Motor Troubleshooting",
        "document_type": "equipment_manual",
        "equipment_type": "industrial_motor",
        "model": None,
        "source": "https://example.test/manual.pdf",
        "revision": "R1",
    }


def _chunk(chunk_id: str, document_id: str, text: str) -> IndexedChunk:
    return IndexedChunk(
        chunk_id=chunk_id,
        document_id=document_id,
        document_title=document_id,
        text=text,
        page=4,
        section="Troubleshooting",
        heading="Troubleshooting",
        document_type="equipment_manual",
        equipment_type="industrial_motor",
        model=None,
        source=f"https://example.test/{document_id}.pdf",
        revision="R1",
        chunk_index=0,
        content_hash="a" * 64,
        embedding=embed(text),
    )


def test_chunk_ids_are_stable_and_tables_keep_rows(tmp_path: Path) -> None:
    source = tmp_path / "manual.md"
    source.write_text(
        "# Troubleshooting\n\n| Fault | Cause | Corrective Action |\n"
        "|---|---|---|\n| High vibration | Misalignment | Align shafts |\n",
        encoding="utf-8",
    )
    blocks, _ = parse_document(source)
    first = chunk_blocks(_document(), blocks)
    second = chunk_blocks(_document(), blocks)
    assert [chunk.chunk_id for chunk in first] == [chunk.chunk_id for chunk in second]
    assert "High vibration | Misalignment | Align shafts" in first[0].text
    assert first[0].section == "Troubleshooting"


def test_hybrid_retrieval_returns_traceable_citation() -> None:
    chunks = [
        _chunk("kc-bearing", "bearing-manual", "bearing wear vibration lubrication inspection"),
        _chunk("kc-align", "alignment-guide", "shaft misalignment coupling vibration alignment"),
    ]
    artifact = IndexArtifact(
        index_version="test",
        corpus_version="test-corpus",
        corpus_manifest_sha256="b" * 64,
        embedding_model=MODEL_VERSION,
        embedding_dimension=DIMENSION,
        embedding_normalization=NORMALIZATION,
        created_at="2026-09-20T00:00:00+00:00",
        documents=[],
        chunks=chunks,
    )
    result = KnowledgeIndex(artifact).search(
        build_query(KnowledgeQuery(fault_type="BEARING_WEAR", symptoms=["high vibration"])),
        pipeline="hybrid",
        top_k=2,
    )
    assert result.evidence[0].document_id == "bearing-manual"
    assert result.evidence[0].citation.page == 4
    assert result.evidence[0].citation.section == "Troubleshooting"
    assert result.evidence[0].source.startswith("https://")


def test_unknown_fault_is_never_declared_sufficient() -> None:
    chunk = _chunk("kc-motor", "motor-manual", "motor bearing maintenance troubleshooting")
    artifact = IndexArtifact(
        index_version="test",
        corpus_version="test-corpus",
        corpus_manifest_sha256="c" * 64,
        embedding_model=MODEL_VERSION,
        embedding_dimension=DIMENSION,
        embedding_normalization=NORMALIZATION,
        created_at="2026-09-20T00:00:00+00:00",
        documents=[],
        chunks=[chunk],
    )
    result = KnowledgeIndex(artifact).search(
        build_query(KnowledgeQuery(fault_type="QUANTUM_TELEPORT")), pipeline="hybrid"
    )
    assert result.sufficiency.status == SufficiencyStatus.INSUFFICIENT


def test_metadata_filters_are_enforced_before_ranking() -> None:
    chunks = [
        _chunk("kc-r1", "manual-r1", "bearing lubrication vibration inspection"),
        _chunk("kc-r2", "manual-r2", "bearing lubrication vibration inspection"),
    ]
    chunks[1].revision = "R2"
    artifact = IndexArtifact(
        index_version="test",
        corpus_version="test-corpus",
        corpus_manifest_sha256="d" * 64,
        embedding_model=MODEL_VERSION,
        embedding_dimension=DIMENSION,
        embedding_normalization=NORMALIZATION,
        created_at="2026-09-20T00:00:00+00:00",
        documents=[],
        chunks=chunks,
    )
    query = BuiltQuery(
        search_terms=["bearing", "lubrication"],
        exact_terms=[],
        semantic_query="bearing lubrication",
        filters=KnowledgeFilters(equipment_type="industrial_motor", revision="R2"),
        supported_fault=True,
    )
    result = KnowledgeIndex(artifact).search(query, pipeline="bm25", top_k=5)
    assert [item.document_id for item in result.evidence] == ["manual-r2"]
    assert result.sufficiency.metadata_match is True


def test_filter_without_matching_chunks_is_insufficient() -> None:
    chunk = _chunk("kc-r1", "manual-r1", "bearing lubrication vibration inspection")
    artifact = IndexArtifact(
        index_version="test",
        corpus_version="test-corpus",
        corpus_manifest_sha256="e" * 64,
        embedding_model=MODEL_VERSION,
        embedding_dimension=DIMENSION,
        embedding_normalization=NORMALIZATION,
        created_at="2026-09-20T00:00:00+00:00",
        documents=[],
        chunks=[chunk],
    )
    query = BuiltQuery(
        search_terms=["bearing"],
        exact_terms=[],
        semantic_query="bearing",
        filters=KnowledgeFilters(model="NONEXISTENT"),
        supported_fault=True,
    )
    result = KnowledgeIndex(artifact).search(query, pipeline="bm25")
    assert result.evidence == []
    assert result.sufficiency.status == SufficiencyStatus.INSUFFICIENT


def test_ingestion_collapses_only_identical_duplicate_chunk_ids() -> None:
    first = _chunk("kc-duplicate", "manual-1", "same stable content")
    repeated = first.model_copy(update={"chunk_index": 99})
    unique, duplicate_count = deduplicate_chunks([first, repeated])
    assert [item.chunk_id for item in unique] == ["kc-duplicate"]
    assert duplicate_count == 1

    conflicting = first.model_copy(update={"text": "different content"})
    try:
        deduplicate_chunks([first, conflicting])
    except ValueError as exc:
        assert "conflicting duplicate chunk id" in str(exc)
    else:
        raise AssertionError("conflicting duplicate chunk ids must be rejected")
