"""Command-line entry point for Phase 7 scenario evaluation."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import subprocess
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from redis.asyncio import Redis
from sqlalchemy.exc import SQLAlchemyError

from app.config import Settings
from app.infrastructure.database.session import Database
from app.knowledge.retrieval import KnowledgeIndex
from app.ml.runtime import ModelCompatibilityError, ModelRuntime
from app.scenarios.contracts import (
    ComponentStatus,
    EvaluationArtifact,
    ReproducibilityMetadata,
    ResultStatus,
    ScenarioDefinition,
)
from app.scenarios.evaluator import ObservedScenario, evaluate
from app.scenarios.loader import load_scenario, load_suite
from app.scenarios.metrics import compute_metrics
from app.scenarios.runner import ScenarioRunner
from app.services.diagnosis import OnlineDiagnosisCoordinator
from app.workflow.provider import OpenAICompatibleProvider, TestProvider
from app.workflow.service import WorkflowService


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run industrial scenario validation")
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--scenario", type=Path, help="one YAML or JSON scenario")
    selection.add_argument("--suite", type=Path, help="directory containing scenario files")
    parser.add_argument("--output", type=Path, required=True, help="JSON artifact path")
    return parser


def _sha256(path: Path) -> str | None:
    return hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None


def _git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


async def _workflow(
    settings: Settings,
    database: Database,
    index: KnowledgeIndex | None,
    stack: AsyncExitStack,
) -> WorkflowService | None:
    if not settings.workflow_enabled:
        return None
    if settings.agent_provider == "test":
        if settings.environment not in {"development", "test", "ci"}:
            raise RuntimeError("test provider is forbidden outside non-production environments")
        provider: Any = TestProvider()
    elif settings.agent_provider == "openai_compatible":
        if settings.agent_api_key is None or not settings.agent_model.strip():
            return None
        provider = OpenAICompatibleProvider(
            api_key=settings.agent_api_key.get_secret_value(),
            base_url=settings.agent_base_url,
            model=settings.agent_model,
            temperature=settings.agent_temperature,
            timeout_seconds=settings.agent_timeout_seconds,
            schema_max_attempts=settings.agent_schema_max_attempts,
        )
    else:
        raise RuntimeError(f"unsupported agent provider: {settings.agent_provider}")
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

    checkpointer = await stack.enter_async_context(
        AsyncPostgresSaver.from_conn_string(settings.checkpoint_database_url)
    )
    return WorkflowService(
        sessions=database.sessions,
        knowledge_index=index,
        provider=provider,
        checkpointer=checkpointer,
        max_attempts=settings.agent_max_attempts,
        backoff_seconds=settings.agent_backoff_seconds,
        timeout_seconds=settings.agent_timeout_seconds,
    )


async def _run(definitions: list[ScenarioDefinition], output: Path, suite_version: str) -> int:
    settings = Settings()
    database = Database(settings)
    redis = Redis.from_url(settings.redis_url, decode_responses=False)
    database_mode = "postgresql"
    async with AsyncExitStack() as stack:
        stack.push_async_callback(database.close)
        stack.push_async_callback(redis.aclose)
        runtime: ModelRuntime | None = None
        index: KnowledgeIndex | None = None
        workflow: WorkflowService | None = None
        try:
            runtime = ModelRuntime.load(
                settings.diagnosis_artifact_path,
                settings.diagnosis_manifest_path,
            )
            diagnosis = OnlineDiagnosisCoordinator(runtime, database.sessions)
            await diagnosis.warmup()
            index = (
                KnowledgeIndex.load(settings.knowledge_index_path)
                if settings.knowledge_enabled
                else None
            )
            workflow = await _workflow(settings, database, index, stack)
            runner = ScenarioRunner(
                sessions=database.sessions,
                redis=redis,
                diagnosis=diagnosis,
                knowledge_index=index,
                workflow=workflow,
            )
            results = [await runner.run(definition) for definition in definitions]
        except (OSError, ConnectionError, SQLAlchemyError, ModelCompatibilityError) as exc:
            database_mode = "unavailable (postgresql configured)"
            reason = f"evaluation environment unavailable: {type(exc).__name__}"
            blocked = dict.fromkeys(
                (
                    "alarm",
                    "incident",
                    "diagnosis",
                    "evidence",
                    "workflow",
                    "safety",
                    "approval",
                    "workorder",
                ),
                reason,
            )
            now = datetime.now(UTC)
            results = [
                evaluate(
                    definition,
                    ObservedScenario(blocked=blocked),
                    started_at=now,
                    duration_ms=0.0,
                )
                for definition in definitions
            ]
        metadata = ReproducibilityMetadata(
            git_sha=_git_sha(),
            suite_version=suite_version,
            timestamp=datetime.now(UTC),
            python_version=platform.python_version(),
            ml_model_version=runtime.manifest.get("model_version") if runtime else None,
            ml_artifact_sha256=_sha256(settings.diagnosis_artifact_path),
            rag_corpus_version=index.artifact.corpus_version if index else None,
            rag_embedding_version=index.artifact.embedding_model if index else None,
            llm_provider=(workflow.provider.provider if workflow else None),
            llm_model=(workflow.provider.model if workflow else None),
            database_mode=database_mode,
            execution_environment=settings.environment,
        )
        artifact = EvaluationArtifact(
            metadata=metadata,
            scenarios=results,
            metrics=compute_metrics(results).model_dump(),
        )
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(artifact.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if any(item.status == ResultStatus.FAIL for item in results):
            return 1
        if any(
            component.status == ComponentStatus.BLOCKED
            for item in results
            for component in (
                item.alarm,
                item.incident,
                item.diagnosis,
                item.evidence,
                item.workflow,
                item.safety,
                item.approval,
                item.workorder,
            )
        ):
            return 2
        return 0


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.scenario is not None:
        definitions = [load_scenario(args.scenario)]
        suite_version = args.scenario.parent.name
    else:
        definitions = load_suite(args.suite)
        suite_version = args.suite.name
    return asyncio.run(_run(definitions, args.output, suite_version))


if __name__ == "__main__":
    raise SystemExit(main())
