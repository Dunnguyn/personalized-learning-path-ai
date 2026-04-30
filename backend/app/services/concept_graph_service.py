"""Concept-graph planning helpers for learning-path generation."""

from __future__ import annotations

from collections import defaultdict
import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from backend.app.database.mongo import get_db


def _normalize_string_list(values: Any, *, limit: int = 5) -> List[str]:
    if not isinstance(values, list):
        return []
    normalized: List[str] = []
    seen: set[str] = set()
    for item in values:
        text = str(item or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        normalized.append(text)
        if len(normalized) >= limit:
            break
    return normalized


def _coerce_difficulty(value: Any, *, default: int = 1) -> int:
    try:
        return max(1, min(int(value), 10))
    except Exception:
        return default


def _chapter_sort_key(lesson: Dict[str, Any]) -> Tuple[int, int, int]:
    return (
        int(lesson.get("_concept_rank", 10**6)),
        _coerce_difficulty(lesson.get("difficulty"), default=1),
        int(lesson.get("original_lesson_index") or lesson.get("original_index") or 0),
    )


class ConceptGraphService:
    """Build and enrich subject concept graphs for path generation."""

    def __init__(self) -> None:
        self.db = get_db()

    @staticmethod
    def normalize_concept_id(
        value: Any,
        *,
        fallback_text: Optional[str] = None,
    ) -> str:
        text = str(value or fallback_text or "").strip().lower()
        if not text:
            return ""
        if text.isdigit():
            return text
        text = re.sub(r"[^a-z0-9]+", "_", text)
        return text.strip("_")

    @staticmethod
    def concept_label(value: str) -> str:
        text = str(value or "").strip()
        if not text:
            return "Concept"
        if text.isdigit():
            return f"Concept {text}"
        return re.sub(r"[_\s]+", " ", text).strip().title()

    @classmethod
    def _normalize_concept_node(
        cls,
        *,
        concept_id: Any,
        subject_id: str,
        concept_name: Optional[str] = None,
        difficulty: Any = 1,
        prerequisites: Optional[Sequence[Any]] = None,
        source: str = "inferred",
    ) -> Dict[str, Any]:
        normalized_id = cls.normalize_concept_id(
            concept_id,
            fallback_text=concept_name,
        )
        return {
            "concept_id": normalized_id,
            "subject_id": str(subject_id or "").strip().lower(),
            "concept_name": str(concept_name or cls.concept_label(normalized_id)).strip()
            or cls.concept_label(normalized_id),
            "difficulty": _coerce_difficulty(difficulty),
            "prerequisites": [
                cls.normalize_concept_id(item)
                for item in (prerequisites or [])
                if cls.normalize_concept_id(item)
            ],
            "source": source,
        }

    def load_subject_graph(self, *, subject_id: str) -> Dict[str, Dict[str, Any]]:
        normalized_subject_id = str(subject_id or "").strip().lower()
        graph: Dict[str, Dict[str, Any]] = {}
        try:
            query = {
                "$or": [
                    {"subject_id": normalized_subject_id},
                    {"topic": normalized_subject_id},
                    {"metadata.subject_key": normalized_subject_id},
                    {"metadata.subject_id": normalized_subject_id},
                ]
            }
            concepts = list(
                self.db.concepts.find(
                    query,
                    {
                        "_id": 0,
                        "concept_id": 1,
                        "concept_name": 1,
                        "difficulty": 1,
                        "subject_id": 1,
                        "topic": 1,
                        "prerequisites": 1,
                    },
                )
            )
            prereq_pairs = list(
                self.db.prerequisites.find(
                    {},
                    {
                        "_id": 0,
                        "from_concept_id": 1,
                        "to_concept_id": 1,
                    },
                )
            )
        except Exception:
            return graph

        for row in concepts:
            node = self._normalize_concept_node(
                concept_id=row.get("concept_id"),
                subject_id=normalized_subject_id,
                concept_name=row.get("concept_name"),
                difficulty=row.get("difficulty"),
                prerequisites=row.get("prerequisites") or [],
                source="catalog",
            )
            if node["concept_id"]:
                graph[node["concept_id"]] = node

        for row in prereq_pairs:
            target_id = self.normalize_concept_id(row.get("to_concept_id"))
            prereq_id = self.normalize_concept_id(row.get("from_concept_id"))
            if not target_id or not prereq_id or target_id not in graph:
                continue
            graph[target_id]["prerequisites"] = _normalize_string_list(
                [*graph[target_id].get("prerequisites", []), prereq_id],
                limit=12,
            )

        return graph

    def enrich_curriculum(
        self,
        *,
        subject_id: str,
        goal: str,
        level: str,
        chapters: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        subject_graph = self.load_subject_graph(subject_id=subject_id)
        graph: Dict[str, Dict[str, Any]] = {
            key: dict(value) for key, value in subject_graph.items()
        }
        flat_lessons: List[Dict[str, Any]] = []
        original_chapter_titles = [
            str(chapter.get("title") or "").strip()
            for chapter in chapters or []
            if str(chapter.get("title") or "").strip()
        ]
        previous_targets: List[str] = []
        lesson_counter = 0

        for chapter_index, chapter in enumerate(chapters or [], start=1):
            chapter_title = str(chapter.get("title") or "").strip() or f"Chapter {chapter_index}"
            for lesson_index, lesson in enumerate(chapter.get("lessons", []) or [], start=1):
                lesson_counter += 1
                title = str(lesson.get("title") or "").strip()
                summary = str(lesson.get("summary") or "").strip()
                if not title:
                    continue
                target_concepts = _normalize_string_list(
                    lesson.get("target_concepts"),
                    limit=5,
                ) or self._infer_target_concepts(
                    subject_id=subject_id,
                    title=title,
                    summary=summary,
                    subject_graph=graph,
                )
                prerequisite_concepts = _normalize_string_list(
                    lesson.get("prerequisite_concepts"),
                    limit=5,
                )
                if not prerequisite_concepts:
                    prerequisite_concepts = self._prerequisites_for_targets(
                        target_concepts=target_concepts,
                        subject_graph=graph,
                    )
                if not prerequisite_concepts and previous_targets:
                    prerequisite_concepts = previous_targets[:1]

                difficulty = _coerce_difficulty(
                    lesson.get("difficulty"),
                    default=max(1, min(10, lesson_counter)),
                )
                lesson_kind = str(lesson.get("lesson_kind") or "core").strip().lower() or "core"

                for concept_id in target_concepts:
                    node = graph.get(concept_id) or self._normalize_concept_node(
                        concept_id=concept_id,
                        subject_id=subject_id,
                        concept_name=self.concept_label(concept_id),
                        difficulty=difficulty,
                    )
                    node["difficulty"] = min(node.get("difficulty", difficulty), difficulty)
                    node["prerequisites"] = _normalize_string_list(
                        [*node.get("prerequisites", []), *prerequisite_concepts],
                        limit=12,
                    )
                    graph[concept_id] = node

                for concept_id in prerequisite_concepts:
                    if concept_id not in graph:
                        graph[concept_id] = self._normalize_concept_node(
                            concept_id=concept_id,
                            subject_id=subject_id,
                            concept_name=self.concept_label(concept_id),
                            difficulty=max(1, difficulty - 1),
                        )

                flat_lessons.append(
                    {
                        "title": title,
                        "summary": summary or f"Study the key ideas in {title}.",
                        "objectives": list(lesson.get("objectives") or []),
                        "difficulty": difficulty,
                        "lesson_kind": lesson_kind,
                        "target_concepts": target_concepts,
                        "prerequisite_concepts": prerequisite_concepts,
                        "original_index": lesson_counter,
                        "original_chapter_title": chapter_title,
                        "original_chapter_index": chapter_index,
                        "original_lesson_index": lesson_index,
                    }
                )
                if target_concepts:
                    previous_targets = list(target_concepts)

        relevant_concepts = self._expand_relevant_concepts(
            graph=graph,
            target_concepts=[
                concept_id
                for lesson in flat_lessons
                for concept_id in lesson.get("target_concepts", [])
            ],
        )
        covered_concepts = {
            concept_id
            for lesson in flat_lessons
            for concept_id in lesson.get("target_concepts", [])
        }
        topo_order = self._topological_sort(
            graph=graph,
            relevant_concepts=relevant_concepts,
        )
        concept_rank = {concept_id: index for index, concept_id in enumerate(topo_order)}

        bridge_lessons: List[Dict[str, Any]] = []
        for concept_id in topo_order:
            if concept_id in covered_concepts:
                continue
            node = graph.get(concept_id) or self._normalize_concept_node(
                concept_id=concept_id,
                subject_id=subject_id,
            )
            bridge_lessons.append(
                {
                    "title": f"Bridge lesson: {node['concept_name']}",
                    "summary": (
                        f"Build the prerequisite concept {node['concept_name']} before progressing "
                        f"toward {goal}."
                    ),
                    "objectives": [
                        f"Reach working mastery in {node['concept_name']}.",
                        f"Prepare for dependent lessons in the {subject_id} path.",
                    ],
                    "difficulty": node["difficulty"],
                    "lesson_kind": "bridge",
                    "target_concepts": [concept_id],
                    "prerequisite_concepts": list(node.get("prerequisites") or []),
                    "original_index": lesson_counter + len(bridge_lessons) + 1,
                    "original_chapter_title": "Prerequisite Bridge",
                    "original_chapter_index": 0,
                    "original_lesson_index": len(bridge_lessons) + 1,
                }
            )

        ordered_lessons = sorted(
            [*flat_lessons, *bridge_lessons],
            key=lambda item: (
                min(
                    concept_rank.get(concept_id, len(concept_rank) + item["original_index"])
                    for concept_id in (item.get("target_concepts") or [""])
                ),
                0 if item.get("lesson_kind") == "bridge" else 1,
                item.get("difficulty", 1),
                item.get("original_index", 0),
            ),
        )

        chapter_titles_by_index: Dict[int, str] = {
            index: title
            for index, title in enumerate(original_chapter_titles, start=1)
            if title
        }
        chapter_buckets: Dict[int, List[Dict[str, Any]]] = defaultdict(list)
        lesson_concept_map: Dict[str, Dict[str, List[str]]] = {}
        for lesson in ordered_lessons:
            lesson_copy = dict(lesson)
            lesson_copy["_concept_rank"] = min(
                (
                    concept_rank.get(concept_id, len(concept_rank) + lesson["original_index"])
                    for concept_id in (lesson_copy.get("target_concepts") or [""])
                ),
                default=len(concept_rank) + lesson_copy["original_index"],
            )
            bucket_index = int(lesson_copy.get("original_chapter_index") or 0)
            if lesson_copy.get("lesson_kind") == "bridge":
                bucket_index = 0
            elif bucket_index <= 0:
                bucket_index = 1
            chapter_buckets[bucket_index].append(lesson_copy)

        ordered_chapter_indices: List[int] = []
        if chapter_buckets.get(0):
            ordered_chapter_indices.append(0)
        ordered_chapter_indices.extend(
            index
            for index in sorted(chapter_titles_by_index)
            if chapter_buckets.get(index)
        )
        for index in sorted(chapter_buckets):
            if index not in ordered_chapter_indices and chapter_buckets.get(index):
                ordered_chapter_indices.append(index)

        chapters_out: List[Dict[str, Any]] = []
        lesson_sequence = 0
        for chapter_index in ordered_chapter_indices:
            lesson_slice = sorted(chapter_buckets.get(chapter_index) or [], key=_chapter_sort_key)
            if not lesson_slice:
                continue
            lessons_out: List[Dict[str, Any]] = []
            for lesson in lesson_slice:
                lesson_sequence += 1
                prerequisite_labels = [
                    graph.get(concept_id, {}).get("concept_name") or self.concept_label(concept_id)
                    for concept_id in lesson.get("prerequisite_concepts", [])
                ]
                lessons_out.append(
                    {
                        "title": lesson["title"],
                        "summary": lesson["summary"],
                        "objectives": list(lesson.get("objectives") or []),
                        "prerequisites": prerequisite_labels[:4],
                        "target_concepts": list(lesson.get("target_concepts") or []),
                        "prerequisite_concepts": list(
                            lesson.get("prerequisite_concepts") or []
                        ),
                        "difficulty": _coerce_difficulty(
                            lesson.get("difficulty"),
                            default=min(10, chapter_index + lesson_sequence),
                        ),
                        "lesson_kind": str(lesson.get("lesson_kind") or "core"),
                    }
                )
                lesson_concept_map[lesson["title"]] = {
                    "target_concepts": list(lesson.get("target_concepts") or []),
                    "prerequisite_concepts": list(
                        lesson.get("prerequisite_concepts") or []
                    ),
                }
            chapters_out.append(
                {
                    "title": (
                        "Prerequisite Bridge"
                        if chapter_index == 0
                        else chapter_titles_by_index.get(chapter_index)
                        or f"Chapter {chapter_index}"
                    ),
                    "lessons": lessons_out,
                }
            )

        graph_out: List[Dict[str, Any]] = []
        for concept_id in topo_order:
            node = graph.get(concept_id)
            if not node:
                continue
            graph_out.append(
                {
                    "concept_id": concept_id,
                    "subject_id": subject_id,
                    "concept_name": node.get("concept_name") or self.concept_label(concept_id),
                    "difficulty": _coerce_difficulty(node.get("difficulty"), default=1),
                    "prerequisites": [
                        prereq
                        for prereq in node.get("prerequisites", [])
                        if prereq in relevant_concepts
                    ],
                    "unlock_strategy": "mastery_threshold",
                    "mastery_threshold": 0.7,
                }
            )

        return {
            "chapters": chapters_out,
            "concept_graph": graph_out,
            "lesson_concept_map": lesson_concept_map,
        }

    def _expand_relevant_concepts(
        self,
        *,
        graph: Dict[str, Dict[str, Any]],
        target_concepts: Iterable[str],
    ) -> List[str]:
        relevant: List[str] = []
        seen: set[str] = set()

        def visit(concept_id: str) -> None:
            if concept_id in seen or not concept_id:
                return
            seen.add(concept_id)
            node = graph.get(concept_id) or {}
            for prereq in node.get("prerequisites", []) or []:
                visit(prereq)
            relevant.append(concept_id)

        for concept_id in target_concepts:
            visit(concept_id)
        return relevant

    def _topological_sort(
        self,
        *,
        graph: Dict[str, Dict[str, Any]],
        relevant_concepts: Sequence[str],
    ) -> List[str]:
        relevant = [concept_id for concept_id in relevant_concepts if concept_id]
        indegree: Dict[str, int] = {concept_id: 0 for concept_id in relevant}
        outgoing: Dict[str, List[str]] = defaultdict(list)

        for concept_id in relevant:
            for prereq in graph.get(concept_id, {}).get("prerequisites", []) or []:
                if prereq not in indegree:
                    continue
                indegree[concept_id] += 1
                outgoing[prereq].append(concept_id)

        ready = sorted(
            [concept_id for concept_id, degree in indegree.items() if degree == 0],
            key=lambda item: (
                _coerce_difficulty(graph.get(item, {}).get("difficulty"), default=1),
                graph.get(item, {}).get("concept_name", item),
            ),
        )
        ordered: List[str] = []
        while ready:
            current = ready.pop(0)
            ordered.append(current)
            for neighbor in outgoing.get(current, []):
                indegree[neighbor] -= 1
                if indegree[neighbor] == 0:
                    ready.append(neighbor)
            ready.sort(
                key=lambda item: (
                    _coerce_difficulty(graph.get(item, {}).get("difficulty"), default=1),
                    graph.get(item, {}).get("concept_name", item),
                )
            )

        if len(ordered) == len(relevant):
            return ordered

        remaining = [concept_id for concept_id in relevant if concept_id not in ordered]
        remaining.sort(
            key=lambda item: (
                _coerce_difficulty(graph.get(item, {}).get("difficulty"), default=1),
                graph.get(item, {}).get("concept_name", item),
            )
        )
        return [*ordered, *remaining]

    def _prerequisites_for_targets(
        self,
        *,
        target_concepts: Sequence[str],
        subject_graph: Dict[str, Dict[str, Any]],
    ) -> List[str]:
        prerequisites: List[str] = []
        for concept_id in target_concepts:
            for prereq in (subject_graph.get(concept_id, {}) or {}).get("prerequisites", []):
                if prereq and prereq not in prerequisites:
                    prerequisites.append(prereq)
        return prerequisites[:5]

    def _infer_target_concepts(
        self,
        *,
        subject_id: str,
        title: str,
        summary: str,
        subject_graph: Dict[str, Dict[str, Any]],
    ) -> List[str]:
        haystack = f"{title} {summary}".lower()
        matches: List[Tuple[int, str]] = []
        for concept_id, node in subject_graph.items():
            tokens = [
                str(node.get("concept_name") or "").strip().lower(),
                concept_id.replace("_", " "),
            ]
            score = 0
            for token in tokens:
                if token and token in haystack:
                    score += len(token)
            if score:
                matches.append((score, concept_id))
        matches.sort(key=lambda item: (-item[0], item[1]))
        if matches:
            return [concept_id for _score, concept_id in matches[:2]]

        normalized = self.normalize_concept_id(
            title,
            fallback_text=f"{subject_id}_core_concept",
        )
        return [normalized]


concept_graph_service = ConceptGraphService()
