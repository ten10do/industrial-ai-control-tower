"""Frozen RAG v1 manifest and deterministic serialization tests."""

from pathlib import Path

from app.knowledge.contracts import IndexArtifact
from app.knowledge.embedding import DIMENSION, MODEL_VERSION, NORMALIZATION
from app.knowledge.reproduce import (
    DEFAULT_MANIFEST,
    _write_frozen_serialization,
    load_manifest,
    verify_tracked_inputs,
)


def test_frozen_manifest_matches_tracked_corpus_provenance() -> None:
    manifest = load_manifest(DEFAULT_MANIFEST)

    catalog_path, corpus_manifest_path = verify_tracked_inputs(manifest)

    assert catalog_path.name == "source_catalog.json"
    assert corpus_manifest_path.name == "knowledge_corpus_manifest.json"
    assert manifest["artifact"]["sha256"] == (
        "416f0781156ef4d7512274c1bbdda31cdad02aebe79b53262d2e8894cce6e947"
    )


def test_frozen_serialization_is_cross_platform_crlf(tmp_path: Path) -> None:
    artifact = IndexArtifact(
        index_version="knowledge-index-v1",
        corpus_version="test",
        corpus_manifest_sha256="a" * 64,
        embedding_model=MODEL_VERSION,
        embedding_dimension=DIMENSION,
        embedding_normalization=NORMALIZATION,
        created_at="not-frozen",
        documents=[],
        chunks=[],
    )
    output = tmp_path / "index.json"

    _write_frozen_serialization(artifact, output, "2026-09-20T00:00:00+00:00")

    content = output.read_bytes()
    assert b"\r\n" in content
    assert content.replace(b"\r\n", b"").find(b"\n") == -1
    assert b'"created_at": "2026-09-20T00:00:00+00:00"' in content
