"""Knowledge corpus, evidence search, and diagnosis-context APIs."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.core.errors import AppError
from app.knowledge.contracts import (
    KnowledgeContextRequest,
    KnowledgeContextResponse,
    KnowledgeDocumentRead,
    KnowledgeQuery,
    KnowledgeSearchRequest,
    KnowledgeSearchResponse,
)
from app.knowledge.query import build_free_text, build_query
from app.knowledge.retrieval import DEFAULT_PIPELINE, PIPELINE_VERSION, KnowledgeIndex
from app.models import KnowledgeDocument, RetrievalRun
from app.repositories.device import DeviceRepository
from app.repositories.diagnosis import DiagnosisRepository

router = APIRouter(tags=["knowledge"])


def _index(request: Request) -> KnowledgeIndex:
    index = cast(KnowledgeIndex | None, request.app.state.knowledge_index)
    if index is None:
        raise AppError("INDEX_NOT_AVAILABLE", "Knowledge index is not available.", 503)
    return index


async def _execute_search(
    request: Request,
    session: AsyncSession,
    payload: KnowledgeSearchRequest,
) -> KnowledgeSearchResponse:
    if (payload.query is None) == (payload.knowledge_query is None):
        raise AppError(
            "UNSUPPORTED_QUERY", "Provide exactly one of 'query' or 'knowledge_query'.", 422
        )
    built = (
        build_query(payload.knowledge_query)
        if payload.knowledge_query is not None
        else build_free_text(payload.query or "", payload.filters)
    )
    run_id = uuid4()
    try:
        result = _index(request).search(
            built,
            top_k=payload.top_k,
            pipeline=payload.pipeline or DEFAULT_PIPELINE,
            run_id=run_id,
        )
    except AppError:
        raise
    except Exception as exc:
        raise AppError("SEARCH_FAILED", "Knowledge retrieval failed.", 500) from exc
    dumped_evidence = [item.model_dump(mode="json") for item in result.evidence]
    session.add(
        RetrievalRun(
            id=run_id,
            query=built.model_dump(mode="json"),
            filters=built.filters.model_dump(mode="json"),
            pipeline_version=PIPELINE_VERSION,
            corpus_version=result.corpus_version,
            embedding_version=result.embedding_version,
            candidate_chunks=dumped_evidence,
            selected_evidence=dumped_evidence,
            sufficiency_result=result.sufficiency.model_dump(mode="json"),
            latency_ms=result.latency_ms,
        )
    )
    await session.commit()
    return result


@router.post("/api/v1/knowledge/search", response_model=KnowledgeSearchResponse)
async def search_knowledge(
    request: Request,
    payload: KnowledgeSearchRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> KnowledgeSearchResponse:
    return await _execute_search(request, session, payload)


@router.get("/api/v1/knowledge/documents", response_model=list[KnowledgeDocumentRead])
async def list_knowledge_documents(
    session: Annotated[AsyncSession, Depends(get_session)],
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[KnowledgeDocumentRead]:
    rows = list(
        await session.scalars(
            select(KnowledgeDocument).order_by(KnowledgeDocument.document_id).limit(limit)
        )
    )
    return [KnowledgeDocumentRead.model_validate(row) for row in rows]


@router.get("/api/v1/knowledge/documents/{document_id}", response_model=KnowledgeDocumentRead)
async def get_knowledge_document(
    document_id: str, session: Annotated[AsyncSession, Depends(get_session)]
) -> KnowledgeDocumentRead:
    document = await session.get(KnowledgeDocument, document_id)
    if document is None:
        raise AppError("CORPUS_NOT_AVAILABLE", f"Document '{document_id}' was not found.", 404)
    return KnowledgeDocumentRead.model_validate(document)


@router.post(
    "/api/v1/devices/{device_id}/knowledge-context", response_model=KnowledgeContextResponse
)
async def diagnosis_knowledge_context(
    request: Request,
    device_id: str,
    payload: KnowledgeContextRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> KnowledgeContextResponse:
    device = await DeviceRepository(session).get(device_id)
    if device is None:
        raise AppError("DEVICE_NOT_FOUND", f"Device '{device_id}' was not found.", 404)
    repository = DiagnosisRepository(session)
    diagnosis = (
        await repository.get(payload.diagnosis_id, device_id)
        if payload.diagnosis_id is not None
        else await repository.latest(device_id)
    )
    if diagnosis is None:
        raise AppError("DIAGNOSIS_NOT_FOUND", "No matching diagnosis is available.", 404)
    symptoms = [
        f"{item.get('signal', '')} {item.get('trend', '')}".strip()
        for item in diagnosis.evidence
        if item.get("signal")
    ]
    device_type = (
        "industrial_motor" if "motor" in device.device_type.lower() else device.device_type
    )
    knowledge_query = KnowledgeQuery(
        device_type=device_type,
        fault_type=diagnosis.fault_type or "UNSUPPORTED",
        severity=diagnosis.severity,
        symptoms=symptoms,
        objective="troubleshooting",
        device_model=cast(str | None, device.device_metadata.get("model")),
    )
    result = await _execute_search(
        request,
        session,
        KnowledgeSearchRequest(knowledge_query=knowledge_query, top_k=payload.top_k),
    )
    return KnowledgeContextResponse(
        **result.model_dump(), diagnosis_id=diagnosis.id, device_id=device_id
    )
