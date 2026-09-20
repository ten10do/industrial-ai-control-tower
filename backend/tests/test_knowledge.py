"""Phase 4 deterministic retrieval, traceability, and refusal tests."""

from pathlib import Path

from app.knowledge.contracts import IndexArtifact, IndexedChunk, KnowledgeQuery, SufficiencyStatus
from app.knowledge.corpus import chunk_blocks, parse_document
from app.knowledge.embedding import DIMENSION, MODEL_VERSION, NORMALIZATION, embed
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
