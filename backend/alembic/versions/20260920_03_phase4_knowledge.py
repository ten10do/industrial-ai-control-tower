"""Add Phase 4 knowledge corpus and retrieval audit storage.

Revision ID: 20260920_03
Revises: 20260917_02
"""

from collections.abc import Sequence

import pgvector.sqlalchemy
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "20260920_03"
down_revision: str | None = "20260917_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "knowledge_documents",
        sa.Column("document_id", sa.String(100), primary_key=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("vendor", sa.String(200), nullable=False),
        sa.Column("document_type", sa.String(100), nullable=False),
        sa.Column("equipment_type", sa.String(100), nullable=False),
        sa.Column("model", sa.String(200)),
        sa.Column("revision", sa.String(200)),
        sa.Column("publication_date", sa.String(40)),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_type", sa.String(80), nullable=False),
        sa.Column("license_note", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("corpus_version", sa.String(100), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("sha256", name="uq_knowledge_documents_sha256"),
    )
    for column in ("document_type", "equipment_type", "model", "corpus_version"):
        op.create_index(f"ix_knowledge_documents_{column}", "knowledge_documents", [column])
    op.create_table(
        "knowledge_chunks",
        sa.Column("chunk_id", sa.String(40), primary_key=True),
        sa.Column(
            "document_id",
            sa.String(100),
            sa.ForeignKey("knowledge_documents.document_id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("page", sa.Integer()),
        sa.Column("section", sa.String(500)),
        sa.Column("heading", sa.String(500)),
        sa.Column("document_type", sa.String(100), nullable=False),
        sa.Column("equipment_type", sa.String(100), nullable=False),
        sa.Column("model", sa.String(200)),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("revision", sa.String(200)),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("embedding", pgvector.sqlalchemy.VECTOR(dim=384), nullable=False),
    )
    op.create_index(
        "ix_knowledge_chunks_document_index", "knowledge_chunks", ["document_id", "chunk_index"]
    )
    for column in ("document_type", "equipment_type", "model"):
        op.create_index(f"ix_knowledge_chunks_{column}", "knowledge_chunks", [column])
    op.create_table(
        "retrieval_runs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("query", postgresql.JSONB(), nullable=False),
        sa.Column("filters", postgresql.JSONB(), nullable=False),
        sa.Column("pipeline_version", sa.String(100), nullable=False),
        sa.Column("corpus_version", sa.String(100), nullable=False),
        sa.Column("embedding_version", sa.String(100), nullable=False),
        sa.Column("candidate_chunks", postgresql.JSONB(), nullable=False),
        sa.Column("selected_evidence", postgresql.JSONB(), nullable=False),
        sa.Column("sufficiency_result", postgresql.JSONB(), nullable=False),
        sa.Column("latency_ms", sa.Float(), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_retrieval_runs_timestamp", "retrieval_runs", ["timestamp"])


def downgrade() -> None:
    op.drop_index("ix_retrieval_runs_timestamp", table_name="retrieval_runs")
    op.drop_table("retrieval_runs")
    op.drop_table("knowledge_chunks")
    op.drop_table("knowledge_documents")
    op.execute("DROP EXTENSION IF EXISTS vector")
