"""Reproducible download, parsing, structure-aware chunking, and index build pipeline."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

from pypdf import PdfReader

from app.knowledge.contracts import IndexArtifact, IndexedChunk
from app.knowledge.embedding import DIMENSION, MODEL_VERSION, NORMALIZATION, embed, tokenize

MAX_FILE_BYTES = 20 * 1024 * 1024
MAX_CHUNK_TOKENS = 220
OVERLAP_TOKENS = 35
ALLOWED_SUFFIXES = {".pdf", ".md", ".txt"}
HEADING_RE = re.compile(r"^(?:\d+(?:\.\d+)*\s+)?[A-Z][A-Za-z0-9 /&()\-,]{3,80}$")


@dataclass(frozen=True)
class Block:
    text: str
    page: int | None
    heading: str | None
    kind: str


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _safe_name(document_id: str, source: str, local_path: str | None = None) -> str:
    suffix = Path(local_path or urllib.parse.urlparse(source).path).suffix.lower()
    if suffix not in ALLOWED_SUFFIXES:
        suffix = ".pdf"
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{2,80}", document_id):
        raise ValueError(f"unsafe document_id: {document_id}")
    return document_id + suffix


def download_document(document: dict[str, Any], raw_dir: Path) -> tuple[Path, str]:
    source = str(document["source"])
    parsed = urllib.parse.urlparse(source)
    raw_dir.mkdir(parents=True, exist_ok=True)
    local_path = cast(str | None, document.get("local_path"))
    destination = (raw_dir / _safe_name(str(document["document_id"]), source, local_path)).resolve()
    if raw_dir.resolve() not in destination.parents:
        raise ValueError("corpus path escaped raw directory")
    if document.get("source_type") == "synthetic":
        if not local_path:
            raise ValueError("synthetic documents require local_path")
        relative = Path(local_path)
        if relative.is_absolute() or ".." in relative.parts:
            raise ValueError("unsafe synthetic document path")
        local_source = (raw_dir.parent / relative).resolve()
        if raw_dir.parent.resolve() not in local_source.parents:
            raise ValueError("synthetic source escaped knowledge directory")
        content = local_source.read_bytes()
        if len(content) > MAX_FILE_BYTES:
            raise ValueError(f"document exceeds {MAX_FILE_BYTES} bytes: {source}")
        destination.write_bytes(content)
        return destination, sha256_bytes(content)
    if parsed.scheme != "https" or not parsed.hostname:
        raise ValueError(f"only HTTPS corpus sources are accepted: {source}")
    if destination.exists():
        content = destination.read_bytes()
        if len(content) > MAX_FILE_BYTES:
            raise ValueError(f"document exceeds {MAX_FILE_BYTES} bytes: {source}")
        return destination, sha256_bytes(content)
    request = urllib.request.Request(source, headers={"User-Agent": "industrial-rag-corpus/1.0"})
    with urllib.request.urlopen(request, timeout=60) as response:  # noqa: S310
        announced = int(response.headers.get("Content-Length", "0"))
        if announced > MAX_FILE_BYTES:
            raise ValueError(f"document exceeds {MAX_FILE_BYTES} bytes: {source}")
        content = response.read(MAX_FILE_BYTES + 1)
    if len(content) > MAX_FILE_BYTES:
        raise ValueError(f"document exceeds {MAX_FILE_BYTES} bytes: {source}")
    if destination.suffix == ".pdf" and not content.startswith(b"%PDF"):
        raise ValueError(f"source did not return a PDF: {source}")
    destination.write_bytes(content)
    return destination, sha256_bytes(content)


def _is_heading(line: str) -> bool:
    stripped = line.strip()
    if len(stripped) < 4 or len(stripped) > 90 or stripped.endswith((".", ";", ",")):
        return False
    letters = [char for char in stripped if char.isalpha()]
    uppercase_ratio = sum(char.isupper() for char in letters) / max(1, len(letters))
    return uppercase_ratio > 0.75 or bool(HEADING_RE.fullmatch(stripped))


def _text_blocks(text: str, page: int | None) -> list[Block]:
    blocks: list[Block] = []
    heading: str | None = None
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text)]
    for paragraph in paragraphs:
        if not paragraph:
            continue
        first_line = paragraph.splitlines()[0].strip().lstrip("#").strip()
        if _is_heading(first_line) and len(paragraph) < 120:
            heading = first_line
            continue
        lines = [line.strip() for line in paragraph.splitlines() if line.strip()]
        is_table = sum("|" in line for line in lines) >= 2
        normalized = "\n".join(lines) if is_table else " ".join(lines)
        blocks.append(Block(normalized, page, heading, "table" if is_table else "paragraph"))
    return blocks


def parse_document(path: Path) -> tuple[list[Block], int]:
    if path.suffix.lower() == ".pdf":
        try:
            reader = PdfReader(path)
            blocks: list[Block] = []
            for page_number, page in enumerate(reader.pages, start=1):
                text = page.extract_text(extraction_mode="layout") or ""
                blocks.extend(_text_blocks(text, page_number))
            return blocks, len(reader.pages)
        except Exception as exc:
            raise ValueError(f"malformed PDF: {path.name}") from exc
    text = path.read_text(encoding="utf-8")
    return _text_blocks(text, None), 0


def _tail_words(text: str, limit: int) -> str:
    words = text.split()
    return " ".join(words[-limit:])


def chunk_blocks(document: dict[str, Any], blocks: list[Block]) -> list[IndexedChunk]:
    groups: list[tuple[str, int | None, str | None]] = []
    current: list[str] = []
    current_page: int | None = None
    current_heading: str | None = None
    token_count = 0
    for block in blocks:
        block_tokens = len(tokenize(block.text))
        boundary = current and (
            token_count + block_tokens > MAX_CHUNK_TOKENS
            or (block.heading and block.heading != current_heading and token_count >= 80)
            or (block.kind == "table" and token_count >= 80)
        )
        if boundary:
            combined = "\n\n".join(current)
            groups.append((combined, current_page, current_heading))
            overlap = _tail_words(combined, OVERLAP_TOKENS)
            current = [overlap] if overlap else []
            token_count = len(tokenize(overlap))
        if not current:
            current_page = block.page
            current_heading = block.heading
        current.append(block.text)
        token_count += block_tokens
    if current:
        groups.append(("\n\n".join(current), current_page, current_heading))

    chunks: list[IndexedChunk] = []
    for index, (text, page, heading) in enumerate(groups):
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        identity = f"{document['document_id']}\0{page}\0{heading}\0{content_hash}"
        chunk_id = "kc-" + hashlib.sha256(identity.encode()).hexdigest()[:24]
        chunks.append(
            IndexedChunk(
                chunk_id=chunk_id,
                document_id=str(document["document_id"]),
                document_title=str(document["title"]),
                text=text,
                page=page,
                section=heading,
                heading=heading,
                document_type=str(document["document_type"]),
                equipment_type=str(document["equipment_type"]),
                model=cast(str | None, document.get("model")),
                source=str(document["source"]),
                revision=cast(str | None, document.get("revision")),
                chunk_index=index,
                content_hash=content_hash,
                embedding=embed(f"{heading or ''} {text}"),
            )
        )
    return chunks


def _canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_corpus(catalog_path: Path, raw_dir: Path, manifest_path: Path, index_path: Path) -> None:
    catalog = cast(dict[str, Any], json.loads(catalog_path.read_text(encoding="utf-8")))
    existing_manifest: dict[str, Any] = {}
    if manifest_path.exists():
        existing_manifest = cast(
            dict[str, Any], json.loads(manifest_path.read_text(encoding="utf-8"))
        )
    existing_documents = {
        str(document["document_id"]): document
        for document in existing_manifest.get("documents", [])
    }
    built_documents: list[dict[str, Any]] = []
    all_chunks: list[IndexedChunk] = []
    seen_hashes: set[str] = set()
    for source_document in catalog["documents"]:
        path, digest = download_document(source_document, raw_dir)
        if digest in seen_hashes:
            raise ValueError(f"duplicate document content: {source_document['document_id']}")
        seen_hashes.add(digest)
        blocks, page_count = parse_document(path)
        chunks = chunk_blocks(source_document, blocks)
        if not chunks:
            raise ValueError(f"no chunks parsed from {path.name}")
        previous = existing_documents.get(str(source_document["document_id"]), {})
        ingested_at = (
            previous.get("ingested_at")
            if previous.get("sha256") == digest
            else datetime.now(UTC).isoformat()
        )
        built = {
            **source_document,
            "sha256": digest,
            "page_count": page_count,
            "chunk_count": len(chunks),
            "ingested_at": ingested_at,
        }
        built_documents.append(built)
        all_chunks.extend(chunks)
    hash_documents = [
        {key: value for key, value in document.items() if key != "ingested_at"}
        for document in built_documents
    ]
    hash_payload = {
        "corpus_version": catalog["corpus_version"],
        "document_count": len(built_documents),
        "page_count": sum(int(doc["page_count"]) for doc in built_documents),
        "chunk_count": len(all_chunks),
        "documents": hash_documents,
    }
    manifest_hash = _canonical_hash(hash_payload)
    created_at = (
        existing_manifest.get("created_at")
        if existing_manifest.get("manifest_sha256") == manifest_hash
        else datetime.now(UTC).isoformat()
    )
    manifest_without_hash = {
        "corpus_version": catalog["corpus_version"],
        "created_at": created_at,
        "document_count": len(built_documents),
        "page_count": sum(int(doc["page_count"]) for doc in built_documents),
        "chunk_count": len(all_chunks),
        "documents": built_documents,
    }
    manifest = {**manifest_without_hash, "manifest_sha256": manifest_hash}
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    artifact = IndexArtifact(
        index_version="knowledge-index-v1",
        corpus_version=str(catalog["corpus_version"]),
        corpus_manifest_sha256=str(manifest["manifest_sha256"]),
        embedding_model=MODEL_VERSION,
        embedding_dimension=DIMENSION,
        embedding_normalization=NORMALIZATION,
        created_at=datetime.now(UTC).isoformat(),
        documents=built_documents,
        chunks=all_chunks,
    )
    index_path.write_text(artifact.model_dump_json(indent=2) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--catalog", type=Path, default=Path("knowledge/source_catalog.json"))
    parser.add_argument("--raw", type=Path, default=Path("knowledge/raw"))
    parser.add_argument(
        "--manifest", type=Path, default=Path("knowledge/knowledge_corpus_manifest.json")
    )
    parser.add_argument("--index", type=Path, default=Path("knowledge/index-v1.json"))
    args = parser.parse_args()
    build_corpus(args.catalog, args.raw, args.manifest, args.index)


if __name__ == "__main__":
    main()
