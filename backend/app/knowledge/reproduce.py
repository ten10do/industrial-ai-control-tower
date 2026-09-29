"""Rebuild and verify the byte-exact frozen RAG v1 artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import tempfile
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast

from app.knowledge.contracts import IndexArtifact, KnowledgeQuery
from app.knowledge.corpus import build_corpus, download_document
from app.knowledge.query import build_query
from app.knowledge.retrieval import KnowledgeIndex

BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = BACKEND_ROOT.parent
DEFAULT_MANIFEST = BACKEND_ROOT / "knowledge" / "rag-v1-manifest.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalized_text_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def load_manifest(path: Path) -> dict[str, Any]:
    return cast(dict[str, Any], json.loads(path.read_text(encoding="utf-8")))


def _repo_path(value: str) -> Path:
    path = (REPOSITORY_ROOT / value).resolve()
    if REPOSITORY_ROOT.resolve() not in path.parents:
        raise ValueError(f"manifest path escapes repository: {value}")
    return path


def verify_build_environment(manifest: dict[str, Any]) -> None:
    expected_python = str(manifest["build"]["python"])
    actual_python = ".".join(platform.python_version_tuple()[:2])
    if actual_python != expected_python:
        raise RuntimeError(
            f"frozen RAG build requires Python {expected_python}, got {actual_python}"
        )
    expected = {
        "pydantic": "2.13.5",
        "pydantic-core": "2.46.5",
        "pypdf": "6.0.0",
    }
    actual = {package: version(package) for package in expected}
    if actual != expected:
        raise RuntimeError(
            f"frozen RAG build dependency mismatch: expected {expected}, got {actual}"
        )


def verify_tracked_inputs(manifest: dict[str, Any]) -> tuple[Path, Path]:
    corpus = cast(dict[str, Any], manifest["corpus"])
    catalog_path = _repo_path(str(corpus["source_catalog_path"]))
    corpus_manifest_path = _repo_path(str(corpus["manifest_path"]))
    if _normalized_text_sha256(catalog_path) != corpus["source_catalog_sha256"]:
        raise ValueError("source catalog hash does not match frozen RAG manifest")
    tracked_corpus = load_manifest(corpus_manifest_path)
    if tracked_corpus["manifest_sha256"] != corpus["manifest_sha256"]:
        raise ValueError("corpus manifest hash does not match frozen RAG manifest")

    catalog = load_manifest(catalog_path)
    catalog_ids = [str(item["document_id"]) for item in catalog["documents"]]
    frozen_ids = [str(item["document_id"]) for item in manifest["sources"]]
    if catalog_ids != frozen_ids:
        raise ValueError("source catalog order or identifiers differ from frozen RAG manifest")
    tracked_sources = {
        str(item["document_id"]): str(item["sha256"]) for item in tracked_corpus["documents"]
    }
    frozen_sources = {str(item["document_id"]): str(item["sha256"]) for item in manifest["sources"]}
    if tracked_sources != frozen_sources:
        raise ValueError("source hashes differ between corpus and frozen RAG manifests")
    return catalog_path, corpus_manifest_path


def _obtain_and_verify_sources(manifest: dict[str, Any], catalog_path: Path, raw_dir: Path) -> None:
    catalog = load_manifest(catalog_path)
    expected = {str(item["document_id"]): item for item in manifest["sources"]}
    for document in catalog["documents"]:
        document_id = str(document["document_id"])
        path, digest = download_document(document, raw_dir)
        frozen = expected[document_id]
        if digest != frozen["sha256"] or path.stat().st_size != frozen["size_bytes"]:
            path.unlink(missing_ok=True)
            raise ValueError(f"source integrity check failed: {document_id}")


def _write_frozen_serialization(artifact: IndexArtifact, path: Path, created_at: str) -> None:
    artifact.created_at = created_at
    payload = (artifact.model_dump_json(indent=2) + "\n").replace("\n", "\r\n")
    path.write_bytes(payload.encode("utf-8"))


def verify_artifact(manifest: dict[str, Any], artifact_path: Path) -> IndexArtifact:
    frozen = cast(dict[str, Any], manifest["artifact"])
    if artifact_path.stat().st_size != frozen["size_bytes"]:
        raise ValueError("frozen RAG artifact size mismatch")
    if _sha256(artifact_path) != frozen["sha256"]:
        raise ValueError("frozen RAG artifact SHA256 mismatch")
    artifact = IndexArtifact.model_validate_json(artifact_path.read_text(encoding="utf-8"))
    corpus = cast(dict[str, Any], manifest["corpus"])
    embedding = cast(dict[str, Any], manifest["embedding"])
    if artifact.index_version != frozen["version"]:
        raise ValueError("frozen RAG index version mismatch")
    if artifact.corpus_version != corpus["version"]:
        raise ValueError("frozen RAG corpus version mismatch")
    if artifact.corpus_manifest_sha256 != corpus["manifest_sha256"]:
        raise ValueError("frozen RAG corpus hash mismatch")
    if (
        artifact.embedding_model != embedding["model"]
        or artifact.embedding_dimension != embedding["dimension"]
        or artifact.embedding_normalization != embedding["normalization"]
    ):
        raise ValueError("frozen RAG embedding metadata mismatch")
    return artifact


def verify_production_retrieval(
    manifest: dict[str, Any], artifact_path: Path
) -> list[dict[str, Any]]:
    index = KnowledgeIndex.load(artifact_path)
    evidence: list[dict[str, Any]] = []
    for gate in manifest["retrieval_gates"]:
        result = index.search(
            build_query(
                KnowledgeQuery(
                    fault_type=str(gate["fault_type"]),
                    symptoms=[str(item) for item in gate["symptoms"]],
                )
            ),
            top_k=int(gate["top_k"]),
            pipeline=str(gate["pipeline"]),
        )
        actual = result.sufficiency.status.value
        if actual != gate["expected_sufficiency"]:
            raise ValueError(f"retrieval gate failed: {gate['name']} sufficiency={actual}")
        if (expected_document := gate.get("expected_first_document_id")) and (
            not result.evidence or result.evidence[0].document_id != expected_document
        ):
            raise ValueError(f"retrieval gate failed: {gate['name']} first document")
        if (expected_chunk := gate.get("expected_first_chunk_id")) and (
            not result.evidence or result.evidence[0].chunk_id != expected_chunk
        ):
            raise ValueError(f"retrieval gate failed: {gate['name']} first chunk")
        evidence.append(
            {
                "name": gate["name"],
                "sufficiency": actual,
                "first_document_id": result.evidence[0].document_id if result.evidence else None,
                "first_chunk_id": result.evidence[0].chunk_id if result.evidence else None,
            }
        )
    return evidence


def reproduce(manifest_path: Path, raw_dir: Path, artifact_path: Path) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    verify_build_environment(manifest)
    catalog_path, corpus_manifest_path = verify_tracked_inputs(manifest)
    _obtain_and_verify_sources(manifest, catalog_path, raw_dir)
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="rag-v1-manifest-") as temporary:
        build_manifest = Path(temporary) / "knowledge_corpus_manifest.json"
        shutil.copyfile(corpus_manifest_path, build_manifest)
        build_corpus(catalog_path, raw_dir, build_manifest, artifact_path)
        built_corpus = load_manifest(build_manifest)
        if built_corpus["manifest_sha256"] != manifest["corpus"]["manifest_sha256"]:
            raise ValueError("rebuilt corpus manifest hash mismatch")
    artifact = IndexArtifact.model_validate_json(artifact_path.read_text(encoding="utf-8"))
    _write_frozen_serialization(artifact, artifact_path, str(manifest["artifact"]["created_at"]))
    verify_artifact(manifest, artifact_path)
    gates = verify_production_retrieval(manifest, artifact_path)
    return {
        "status": "PASS",
        "strategy": manifest["build"]["strategy"],
        "artifact_path": str(artifact_path),
        "artifact_sha256": _sha256(artifact_path),
        "artifact_size_bytes": artifact_path.stat().st_size,
        "corpus_manifest_sha256": manifest["corpus"]["manifest_sha256"],
        "retrieval_gates": gates,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--raw", type=Path, default=BACKEND_ROOT / "knowledge" / "raw")
    parser.add_argument("--index", type=Path, default=BACKEND_ROOT / "knowledge" / "index-v1.json")
    args = parser.parse_args()
    print(json.dumps(reproduce(args.manifest, args.raw, args.index), indent=2))


if __name__ == "__main__":
    main()
