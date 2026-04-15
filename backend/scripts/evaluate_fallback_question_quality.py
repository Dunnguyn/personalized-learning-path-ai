from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
import sys
from typing import Any, Dict, List, Sequence


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from backend.app.repositories.lesson_recommended_chunk_repository import (  # noqa: E402
    LessonRecommendedChunkRepository,
)
from backend.app.repositories.lesson_repository import LessonRepository  # noqa: E402
from backend.app.repositories.chunk_repository import ResourceChunkRepository  # noqa: E402
from backend.app.services.lesson_chunk_service import lesson_chunk_service  # noqa: E402
from backend.app.services.question_generation_service import (  # noqa: E402
    lesson_question_generation_service,
)


def _stringify(value: Any) -> str:
    return str(value or "").strip()


def _normalize_lesson_id(value: Any) -> str:
    return _stringify(value)


def _collect_target_concepts(
    recommendation: Dict[str, Any] | None,
    context: Dict[str, Any],
    chunks: Sequence[Dict[str, Any]],
) -> List[str]:
    sequence_metadata = (
        recommendation.get("sequence_metadata", {})
        if isinstance(recommendation, dict)
        else {}
    )
    raw_targets: List[str] = []
    for source in (
        sequence_metadata.get("covered_required_concepts"),
        sequence_metadata.get("required_concepts"),
        context.get("lesson", {}).get("keywords"),
        context.get("lesson", {}).get("learning_objectives"),
    ):
        values = source if isinstance(source, list) else [source] if source else []
        for item in values:
            token = _stringify(item)
            if token and token not in raw_targets:
                raw_targets.append(token)
    normalized = lesson_question_generation_service._normalize_generation_target_concepts(
        raw_target_concepts=raw_targets,
        context=context,
        chunks=list(chunks),
    )
    return list(normalized.get("valid_target_concepts", []))


def _select_lessons(
    *,
    lesson_ids: Sequence[str],
    limit: int,
) -> List[str]:
    if lesson_ids:
        return [_normalize_lesson_id(item) for item in lesson_ids if _stringify(item)]

    recommendation_repository = LessonRecommendedChunkRepository()
    cursor = recommendation_repository.collection.find(
        {"chunk_ids.0": {"$exists": True}},
        {"lesson_id": 1, "updated_at": 1},
    ).sort("updated_at", -1)

    selected: List[str] = []
    for doc in cursor:
        lesson_id = _normalize_lesson_id(doc.get("lesson_id"))
        if lesson_id and lesson_id not in selected:
            selected.append(lesson_id)
        if len(selected) >= max(1, int(limit or 1)):
            break

    if len(selected) >= max(1, int(limit or 1)):
        return selected

    lesson_repository = LessonRepository()
    for lesson in lesson_repository.list():
        recommended_chunk_ids = lesson.get("recommended_chunk_ids") or []
        lesson_id = _normalize_lesson_id(lesson.get("_id"))
        if not recommended_chunk_ids or not lesson_id or lesson_id in selected:
            continue
        selected.append(lesson_id)
        if len(selected) >= max(1, int(limit or 1)):
            break

    if len(selected) >= max(1, int(limit or 1)):
        return selected

    for lesson in lesson_repository.list():
        lesson_id = _normalize_lesson_id(lesson.get("_id"))
        resource_ids = lesson.get("resource_ids") or []
        if not lesson_id or lesson_id in selected or not resource_ids:
            continue
        selected.append(lesson_id)
        if len(selected) >= max(1, int(limit or 1)):
            break
    return selected


def collect_readiness_snapshot() -> Dict[str, Any]:
    lesson_repository = LessonRepository()
    recommendation_repository = LessonRecommendedChunkRepository()
    chunk_repository = ResourceChunkRepository()

    lessons = lesson_repository.list()
    lessons_with_resources = sum(1 for lesson in lessons if lesson.get("resource_ids"))
    lessons_with_recommended_chunks = sum(
        1 for lesson in lessons if lesson.get("recommended_chunk_ids")
    )
    return {
        "lesson_count": len(lessons),
        "lessons_with_resource_ids": lessons_with_resources,
        "lessons_with_recommended_chunk_ids": lessons_with_recommended_chunks,
        "recommendation_count": recommendation_repository.collection.count_documents({}),
        "resource_chunk_count": chunk_repository.count_total(),
    }


def _summarize_question(question: Any) -> Dict[str, Any]:
    metadata = question.metadata or {}
    return {
        "question_type": question.question_type,
        "question": question.question,
        "correct_answer": question.correct_answer,
        "distractors": list(question.distractors),
        "difficulty": question.difficulty,
        "bloom_level": question.bloom_level,
        "chunk_ids": list(question.chunk_ids),
        "focus": _stringify(metadata.get("question_focus") or metadata.get("concept_focus")),
        "matched_target_concepts": list(metadata.get("matched_target_concepts") or []),
        "target_concept_match": bool(metadata.get("target_concept_match")),
        "verification_score": float(metadata.get("verification_score", 0.0) or 0.0),
        "verification_pass": bool(metadata.get("verification_pass")),
        "verification_blockers": list(metadata.get("verification_blockers") or []),
        "fallback_excerpt_score": float(metadata.get("fallback_excerpt_score", 0.0) or 0.0),
        "fallback_priority_score": float(metadata.get("fallback_priority_score", 0.0) or 0.0),
        "generation_mode": _stringify(metadata.get("generation_mode")),
        "source_excerpt": _stringify(metadata.get("source_excerpt")),
    }


def evaluate_lesson(
    *,
    lesson_id: str,
    target_count: int,
    difficulty: str,
    bloom_levels: Sequence[str],
    bootstrap_recommendation: bool,
) -> Dict[str, Any]:
    context = lesson_question_generation_service.lesson_structure_service.get_lesson_context(
        lesson_id
    )
    recommendation = lesson_question_generation_service._peek_recommendation(
        lesson_id, context
    )
    if not recommendation and bootstrap_recommendation:
        lesson = context.get("lesson") or {}
        resource_ids = [str(item) for item in lesson.get("resource_ids") or [] if item]
        if resource_ids:
            try:
                recommendation = lesson_chunk_service.recommend_chunks(
                    lesson_id=lesson_id,
                    max_chunks=max(8, int(target_count or 5)),
                    selection_strategy="local_semantic_lesson_scope_v1",
                    enable_diversity_reranking=True,
                    diversity_lambda=None,
                    resource_ids=resource_ids,
                    metadata={
                        "mode": "fallback_quality_evaluation",
                        "trigger": "bootstrap_recommendation_for_fallback_eval",
                    },
                )
            except Exception as exc:
                return {
                    "lesson_id": lesson_id,
                    "lesson_title": _stringify((context.get("lesson") or {}).get("title")),
                    "status": "skipped",
                    "reason": f"bootstrap_recommendation_failed: {exc}",
                }
    if not recommendation:
        return {
            "lesson_id": lesson_id,
            "lesson_title": _stringify((context.get("lesson") or {}).get("title")),
            "status": "skipped",
            "reason": "missing_recommendation",
        }

    _recommendation, chunk_ids, chunks = (
        lesson_question_generation_service._load_generation_scope(
            lesson_id=lesson_id,
            context=context,
            recommendation=recommendation,
        )
    )
    chunks = lesson_question_generation_service._enrich_chunks_with_recommendation_metadata(
        chunks=chunks,
        recommendation=recommendation,
    )
    target_concepts = _collect_target_concepts(
        recommendation=recommendation,
        context=context,
        chunks=chunks,
    )
    fallback_context = {
        **context,
        "target_concepts": list(target_concepts),
    }
    raw_questions = lesson_question_generation_service._build_fallback_questions(
        context=fallback_context,
        chunks=chunks,
        target_count=target_count,
        question_types=["multiple_choice"],
        difficulty=difficulty,
        bloom_levels=list(bloom_levels),
        relaxed_mode=False,
    )
    chunk_map = {str(chunk["_id"]): chunk for chunk in chunks if chunk.get("_id")}
    verified_questions, verification_filtered_count = (
        lesson_question_generation_service._verify_candidate_questions(
            questions=raw_questions,
            target_concepts=target_concepts,
            requested_bloom_levels=list(bloom_levels),
            chunk_map=chunk_map,
        )
    )
    coverage = lesson_question_generation_service.compute_concept_coverage_rate(
        verified_questions,
        valid_target_concepts=target_concepts,
        chunk_map=chunk_map,
    )

    questions_payload = [_summarize_question(item) for item in verified_questions]
    multiple_choice_count = sum(
        1 for item in questions_payload if item["question_type"] == "multiple_choice"
    )
    target_match_count = sum(
        1 for item in questions_payload if item["target_concept_match"]
    )
    verification_scores = [float(item["verification_score"]) for item in questions_payload]
    unique_focuses = {
        _stringify(item["focus"]).lower()
        for item in questions_payload
        if _stringify(item["focus"])
    }

    lesson = context.get("lesson") or {}
    return {
        "lesson_id": lesson_id,
        "lesson_title": _stringify(lesson.get("title")),
        "status": "ok",
        "chunk_count": len(chunks),
        "target_count": int(target_count),
        "question_count": len(questions_payload),
        "multiple_choice_ratio": round(
            multiple_choice_count / max(len(questions_payload), 1), 4
        ),
        "target_concepts": list(target_concepts),
        "target_concept_match_count": target_match_count,
        "target_concept_match_rate": round(
            target_match_count / max(len(questions_payload), 1), 4
        ),
        "concept_coverage_rate": coverage.get("coverage_rate"),
        "missing_concepts": list(coverage.get("missing_concepts", [])),
        "verification_filtered_count": int(verification_filtered_count or 0),
        "average_verification_score": round(
            sum(verification_scores) / max(len(verification_scores), 1), 4
        ),
        "hard_fail_count": sum(
            1
            for item in questions_payload
            if any(
                blocker
                for blocker in item.get("verification_blockers", [])
            )
        ),
        "unique_focus_count": len(unique_focuses),
        "questions": questions_payload,
        "chunks_used": list(chunk_ids),
    }


def build_markdown_report(results: Sequence[Dict[str, Any]]) -> str:
    generated_at = datetime.now().isoformat(timespec="seconds")
    lines: List[str] = [
        "# Fallback Question Quality Report",
        "",
        f"- Generated at: `{generated_at}`",
        f"- Lessons evaluated: `{len(results)}`",
        "",
    ]
    for result in results:
        lines.append(
            f"## {result.get('lesson_title') or result.get('lesson_id')} ({result.get('lesson_id')})"
        )
        if result.get("status") != "ok":
            lines.append("")
            lines.append(f"- Status: `{result.get('status')}`")
            lines.append(f"- Reason: `{result.get('reason')}`")
            lines.append("")
            continue

        lines.extend(
            [
                "",
                f"- Questions: `{result['question_count']}/{result['target_count']}`",
                f"- Multiple-choice ratio: `{result['multiple_choice_ratio']:.0%}`",
                f"- Target concept match rate: `{result['target_concept_match_rate']:.0%}`",
                f"- Concept coverage rate: `{(result['concept_coverage_rate'] or 0.0):.0%}`",
                f"- Average verification score: `{result['average_verification_score']}`",
                f"- Missing concepts: `{', '.join(result['missing_concepts']) or 'none'}`",
                "",
                "| # | Focus | Match | Verification | Question | Answer |",
                "|---|---|---:|---:|---|---|",
            ]
        )
        for index, question in enumerate(result.get("questions", []), start=1):
            lines.append(
                "| {index} | {focus} | {match} | {score} | {question_text} | {answer} |".format(
                    index=index,
                    focus=question.get("focus") or "-",
                    match="yes" if question.get("target_concept_match") else "no",
                    score=question.get("verification_score", 0.0),
                    question_text=_stringify(question.get("question")).replace("|", "\\|"),
                    answer=_stringify(question.get("correct_answer")).replace("|", "\\|"),
                )
            )
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def build_blocker_report(snapshot: Dict[str, Any]) -> str:
    generated_at = datetime.now().isoformat(timespec="seconds")
    lines = [
        "# Fallback Question Quality Report",
        "",
        f"- Generated at: `{generated_at}`",
        "- Status: `blocked_no_real_lesson_scope`",
        "",
        "## Readiness",
        "",
        f"- Lessons: `{snapshot['lesson_count']}`",
        f"- Lessons with resource_ids: `{snapshot['lessons_with_resource_ids']}`",
        f"- Lessons with recommended_chunk_ids: `{snapshot['lessons_with_recommended_chunk_ids']}`",
        f"- Stored lesson recommendations: `{snapshot['recommendation_count']}`",
        f"- Resource chunks: `{snapshot['resource_chunk_count']}`",
        "",
        "## Blockers",
        "",
        "- Khong co lesson nao du dieu kien de chay fallback tren du lieu that.",
        "- Script can it nhat mot lesson co `resource_ids`, hoac `recommended_chunk_ids`, hoac recommendation da duoc sinh truoc do.",
        "- Hien tai cung chua co `resource_chunks`, nen ngay ca bootstrap recommendation cung khong co nguon chunk de danh gia.",
        "",
    ]
    return "\n".join(lines).strip() + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate local fallback question quality on real lessons."
    )
    parser.add_argument(
        "--lesson-id",
        action="append",
        default=[],
        help="Lesson id to evaluate. Can be passed multiple times.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=3,
        help="How many recommended lessons to sample when lesson ids are not provided.",
    )
    parser.add_argument(
        "--target-count",
        type=int,
        default=5,
        help="Number of fallback questions to request per lesson.",
    )
    parser.add_argument(
        "--difficulty",
        default="beginner",
        choices=["beginner", "intermediate", "advanced"],
    )
    parser.add_argument(
        "--bloom-level",
        action="append",
        dest="bloom_levels",
        default=[],
        help="Bloom level to request. Can be passed multiple times.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(REPO_ROOT / "docs" / "reports"),
        help="Directory for generated markdown/json reports.",
    )
    parser.add_argument(
        "--no-bootstrap-recommendation",
        action="store_true",
        help="Do not auto-create recommendations from lesson resources when missing.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    bloom_levels = list(args.bloom_levels or ["understand", "apply"])
    lesson_ids = _select_lessons(
        lesson_ids=list(args.lesson_id or []),
        limit=args.limit,
    )
    if not lesson_ids:
        snapshot = collect_readiness_snapshot()
        output_dir = Path(args.output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        markdown_path = output_dir / f"fallback_question_quality_{timestamp}.md"
        json_path = output_dir / f"fallback_question_quality_{timestamp}.json"
        blocker_payload = {
            "status": "blocked_no_real_lesson_scope",
            "readiness": snapshot,
        }
        markdown_path.write_text(build_blocker_report(snapshot), encoding="utf-8")
        json_path.write_text(
            json.dumps(blocker_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"Markdown report: {markdown_path}")
        print(f"JSON report: {json_path}")
        return 1

    results = [
        evaluate_lesson(
            lesson_id=lesson_id,
            target_count=args.target_count,
            difficulty=args.difficulty,
            bloom_levels=bloom_levels,
            bootstrap_recommendation=not bool(args.no_bootstrap_recommendation),
        )
        for lesson_id in lesson_ids
    ]

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    markdown_path = output_dir / f"fallback_question_quality_{timestamp}.md"
    json_path = output_dir / f"fallback_question_quality_{timestamp}.json"

    markdown_path.write_text(build_markdown_report(results), encoding="utf-8")
    json_path.write_text(
        json.dumps(results, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"Markdown report: {markdown_path}")
    print(f"JSON report: {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
