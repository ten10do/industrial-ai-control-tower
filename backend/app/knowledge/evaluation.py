"""Frozen retrieval and evidence-sufficiency evaluation."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from pathlib import Path
from typing import Any, cast

from app.knowledge.contracts import KnowledgeQuery, SufficiencyStatus
from app.knowledge.query import build_query
from app.knowledge.retrieval import KnowledgeIndex

PIPELINES = ("bm25", "dense", "hybrid", "hybrid_rerank")


def _dcg(labels: list[int]) -> float:
    return float(sum((2**label - 1) / math.log2(index + 2) for index, label in enumerate(labels)))


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    position = (len(ordered) - 1) * percentile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def evaluate(index: KnowledgeIndex, queries: list[dict[str, Any]]) -> dict[str, Any]:
    results: dict[str, Any] = {}
    for pipeline in PIPELINES:
        hit1: list[float] = []
        hit3: list[float] = []
        recall5: list[float] = []
        reciprocal_ranks: list[float] = []
        ndcg5: list[float] = []
        latencies: list[float] = []
        supported_accepted = 0
        unsupported_rejected = 0
        false_sufficient = 0
        false_insufficient = 0
        details: list[dict[str, Any]] = []
        for item in queries:
            built = build_query(
                KnowledgeQuery(
                    fault_type=str(item["fault_type"]),
                    symptoms=[str(item["query"])],
                    objective="troubleshooting",
                )
            )
            started = time.perf_counter()
            response = index.search(built, top_k=5, pipeline=pipeline)
            latency = (time.perf_counter() - started) * 1000.0
            latencies.append(latency)
            labels = cast(dict[str, int], item["relevance_labels"])
            relevant = {document_id for document_id, label in labels.items() if label > 0}
            ranked_documents = list(
                dict.fromkeys(evidence.document_id for evidence in response.evidence)
            )
            if bool(item["supported"]):
                relevance = [labels.get(document_id, 0) for document_id in ranked_documents]
                first = next(
                    (index + 1 for index, label in enumerate(relevance) if label > 0), None
                )
                hit1.append(float(bool(relevance[:1] and relevance[0] > 0)))
                hit3.append(float(any(label > 0 for label in relevance[:3])))
                recall5.append(len(set(ranked_documents[:5]) & relevant) / max(1, len(relevant)))
                reciprocal_ranks.append(1.0 / first if first else 0.0)
                ideal = sorted(labels.values(), reverse=True)[:5]
                ndcg5.append(_dcg(relevance[:5]) / max(_dcg(ideal), 1e-12))
                if response.sufficiency.status == SufficiencyStatus.SUFFICIENT:
                    supported_accepted += 1
                if response.sufficiency.status == SufficiencyStatus.INSUFFICIENT:
                    false_insufficient += 1
            else:
                if response.sufficiency.status == SufficiencyStatus.INSUFFICIENT:
                    unsupported_rejected += 1
                if response.sufficiency.status == SufficiencyStatus.SUFFICIENT:
                    false_sufficient += 1
            details.append(
                {
                    "query_id": item["query_id"],
                    "supported": item["supported"],
                    "expected_document": item["expected_document"],
                    "top_documents": ranked_documents,
                    "sufficiency": response.sufficiency.status,
                    "latency_ms": latency,
                }
            )
        supported_count = sum(bool(item["supported"]) for item in queries)
        unsupported_count = len(queries) - supported_count
        results[pipeline] = {
            "hit_at_1": statistics.fmean(hit1) if hit1 else 0.0,
            "hit_at_3": statistics.fmean(hit3) if hit3 else 0.0,
            "recall_at_5": statistics.fmean(recall5) if recall5 else 0.0,
            "mrr": statistics.fmean(reciprocal_ranks) if reciprocal_ranks else 0.0,
            "ndcg_at_5": statistics.fmean(ndcg5) if ndcg5 else 0.0,
            "latency_p50_ms": _percentile(latencies, 0.50),
            "latency_p95_ms": _percentile(latencies, 0.95),
            "supported_acceptance": supported_accepted / max(1, supported_count),
            "unsupported_rejection": unsupported_rejected / max(1, unsupported_count),
            "false_sufficient_rate": false_sufficient / max(1, unsupported_count),
            "false_insufficient_rate": false_insufficient / max(1, supported_count),
            "details": details,
        }
    return results


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", type=Path, default=Path("knowledge/index-v1.json"))
    parser.add_argument("--queries", type=Path, default=Path("knowledge/eval_queries_v1.json"))
    parser.add_argument("--split", choices=("dev", "frozen_eval"), default="dev")
    parser.add_argument("--output", type=Path, default=Path("knowledge/evaluation-results.json"))
    args = parser.parse_args()
    dataset = cast(dict[str, Any], json.loads(args.queries.read_text(encoding="utf-8")))
    queries = cast(list[dict[str, Any]], dataset[args.split])
    payload = {
        "eval_dataset_version": dataset["eval_dataset_version"],
        "split": args.split,
        "query_count": len(queries),
        "corpus_version": dataset["corpus_version"],
        "results": evaluate(KnowledgeIndex.load(args.index), queries),
    }
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    summary = {
        pipeline: {key: value for key, value in metrics.items() if key != "details"}
        for pipeline, metrics in payload["results"].items()
    }
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
