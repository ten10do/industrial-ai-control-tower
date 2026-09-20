"""Transactional pgvector corpus ingestion with unchanged-document skipping."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import delete, select

from app.config import get_settings
from app.infrastructure.database.session import Database
from app.knowledge.contracts import IndexArtifact
from app.knowledge.embedding import DIMENSION, MODEL_VERSION
from app.models import KnowledgeChunk, KnowledgeDocument


def _document_values(document: dict[str, Any], corpus_version: str) -> dict[str, Any]:
    return {
        "title": document["title"],
        "vendor": document["vendor"],
        "document_type": document["document_type"],
        "equipment_type": document["equipment_type"],
        "model": document.get("model"),
        "revision": document.get("revision"),
        "publication_date": document.get("publication_date"),
        "source": document["source"],
        "source_type": document["source_type"],
        "license_note": document["license_note"],
        "sha256": document["sha256"],
        "corpus_version": corpus_version,
        "page_count": document["page_count"],
        "chunk_count": document["chunk_count"],
        "ingested_at": datetime.fromisoformat(document["ingested_at"]),
    }


async def ingest(path: Path) -> dict[str, int]:
    artifact = IndexArtifact.model_validate_json(path.read_text(encoding="utf-8"))
    if artifact.embedding_model != MODEL_VERSION or artifact.embedding_dimension != DIMENSION:
        raise ValueError("index embedding metadata is incompatible with this runtime")
    hashes = [str(document["sha256"]) for document in artifact.documents]
    if len(hashes) != len(set(hashes)):
        raise ValueError("duplicate document hashes in index")
    chunks_by_document: dict[str, list[Any]] = {}
    for chunk in artifact.chunks:
        chunks_by_document.setdefault(chunk.document_id, []).append(chunk)
    database = Database(get_settings())
    stats = {"inserted": 0, "replaced": 0, "skipped": 0, "chunks": 0}
    try:
        async with database.sessions() as session:
            existing_rows = list(await session.scalars(select(KnowledgeDocument)))
            existing = {row.document_id: row for row in existing_rows}
            incoming_ids: set[str] = set()
            for document in artifact.documents:
                document_id = str(document["document_id"])
                incoming_ids.add(document_id)
                current = existing.get(document_id)
                if current is not None and current.sha256 == document["sha256"]:
                    stats["skipped"] += 1
                    continue
                values = _document_values(document, artifact.corpus_version)
                if current is None:
                    current = KnowledgeDocument(document_id=document_id, **values)
                    session.add(current)
                    stats["inserted"] += 1
                else:
                    await session.execute(
                        delete(KnowledgeChunk).where(KnowledgeChunk.document_id == document_id)
                    )
                    for key, value in values.items():
                        setattr(current, key, value)
                    stats["replaced"] += 1
                await session.flush()
                for chunk in chunks_by_document.get(document_id, []):
                    session.add(
                        KnowledgeChunk(
                            chunk_id=chunk.chunk_id,
                            document_id=chunk.document_id,
                            text=chunk.text,
                            page=chunk.page,
                            section=chunk.section,
                            heading=chunk.heading,
                            document_type=chunk.document_type,
                            equipment_type=chunk.equipment_type,
                            model=chunk.model,
                            source=chunk.source,
                            revision=chunk.revision,
                            chunk_index=chunk.chunk_index,
                            content_hash=chunk.content_hash,
                            embedding=chunk.embedding,
                        )
                    )
                    stats["chunks"] += 1
            stale = set(existing) - incoming_ids
            if stale:
                await session.execute(
                    delete(KnowledgeDocument).where(KnowledgeDocument.document_id.in_(stale))
                )
            await session.commit()
    finally:
        await database.close()
    return stats


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", type=Path, default=get_settings().knowledge_index_path)
    parser.add_argument("--if-present", action="store_true")
    args = parser.parse_args()
    if not args.path.exists():
        if args.if_present:
            print("knowledge index not present; ingestion skipped")
            return
        raise FileNotFoundError(args.path)
    print(asyncio.run(ingest(args.path)))


if __name__ == "__main__":
    main()
