from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from bson import ObjectId

from backend.app.database.mongo import get_db
from backend.app.services.question_generation.rules import detect_concept_type, normalize_concept
from backend.app.services.question_generation.templates import select_template

logger = logging.getLogger(__name__)


# =====================================================
# ANALYSIS
# =====================================================
# This generator is fully deterministic and does NOT use:
# - Knowledge Graph
# - LLM
#
# It only uses:
# - lesson concepts
# - rule-based NLP normalization and concept classification
# - Bloom's Taxonomy template selection


# =====================================================
# PSEUDOCODE
# =====================================================
# generate_questions_for_lesson(lesson_id):
# 1. load lesson and concept_list
# 2. normalize each concept
# 3. detect concept_type
# 4. for each bloom level:
#    - select concepts round-robin
#    - select templates for bloom level
#    - fill template with concept
#    - build metadata (bloom_level, difficulty, template_id)
# 5. deduplicate
# 6. rebalance until enough questions
# 7. return 20 questions


BLOOM_DISTRIBUTION: List[Tuple[str, int]] = [
    ("remember", 4),
    ("understand", 4),
    ("apply", 4),
    ("analyze", 3),
    ("evaluate", 3),
    ("create", 2),
]

BLOOM_DIFFICULTY = {
    "remember": 1,
    "understand": 2,
    "apply": 3,
    "analyze": 4,
    "evaluate": 5,
    "create": 6,
}

CONCEPT_TYPE_TEMPLATE_HINTS: Dict[str, Dict[str, List[str]]] = {
    "algorithm_concept": {
        "understand": ["cách hoạt động", "giải thích"],
        "apply": ["áp dụng", "ví dụ"],
        "analyze": ["quá trình xử lý", "yếu tố"],
        "evaluate": ["hiệu quả", "ưu điểm"],
        "create": ["cải tiến", "ứng dụng mới"],
    },
    "application_concept": {
        "understand": ["quan trọng", "giải thích"],
        "apply": ["thực tế", "sử dụng"],
        "analyze": ["vai trò", "hệ thống"],
        "evaluate": ["sử dụng", "hiệu quả"],
        "create": ["minh họa", "ứng dụng mới"],
    },
    "system_concept": {
        "understand": ["cách hoạt động", "quan trọng"],
        "apply": ["thực tế", "sử dụng"],
        "analyze": ["hệ thống", "xử lý"],
        "evaluate": ["ưu điểm", "hạn chế"],
        "create": ["cải tiến", "hệ thống thực tế"],
    },
    "definition_concept": {
        "understand": ["giải thích", "quan trọng"],
        "apply": ["ví dụ", "sử dụng"],
        "analyze": ["vai trò", "yếu tố"],
        "evaluate": ["đánh giá", "sử dụng"],
        "create": ["minh họa", "ứng dụng mới"],
    },
}


@dataclass(frozen=True)
class LessonConcept:
    concept_id: str
    name: str
    normalized_name: str
    concept_type: str


class QuestionGenerator:
    def __init__(self) -> None:
        self.db = get_db()

    def generate_questions(self, chapter_id: str, num_questions: int) -> List[Dict]:
        chapter_context = self._resolve_chapter_context(chapter_id)
        concepts = self._extract_chapter_concepts(chapter_context)
        if not concepts:
            raise ValueError(f"Chapter has no concepts: {chapter_id}")

        questions: List[Dict] = []
        concept_usage = self._initialize_usage(concepts)
        for bloom_level, required in BLOOM_DISTRIBUTION:
            questions.extend(
                self._generate_for_bloom_level(
                    concepts=concepts,
                    bloom_level=bloom_level,
                    required=required,
                    concept_usage=concept_usage,
                )
            )

        deduplicated = self._deduplicate_questions(questions)
        balanced = self._fill_shortfall(concepts, deduplicated, num_questions, concept_usage)
        return balanced[:num_questions]

    def generate_questions_for_lesson(self, lesson_id: str, target_count: int = 20) -> List[Dict]:
        lesson_context = self._resolve_lesson_context(lesson_id)
        concepts = self._extract_lesson_concepts(lesson_context)
        if not concepts:
            raise ValueError(f"Lesson has no concepts: {lesson_id}")

        questions: List[Dict] = []
        concept_usage = self._initialize_usage(concepts)
        for bloom_level, required in BLOOM_DISTRIBUTION:
            generated = self._generate_for_bloom_level(
                concepts=concepts,
                bloom_level=bloom_level,
                required=required,
                concept_usage=concept_usage,
            )
            questions.extend(generated)

        deduplicated = self._deduplicate_questions(questions)
        balanced = self._fill_shortfall(concepts, deduplicated, target_count, concept_usage)
        return balanced[:target_count]

    def analyze_lesson_generation(self, lesson_id: str, target_question_count: int = 20) -> Dict:
        lesson_context = self._resolve_lesson_context(lesson_id)
        concepts = self._extract_lesson_concepts(lesson_context)
        if not concepts:
            raise ValueError(f"Lesson has no concepts: {lesson_id}")

        questions = self.generate_questions_for_lesson(lesson_id, target_question_count)
        bloom_counts: Dict[str, int] = {}
        concept_type_counts: Dict[str, int] = {}
        for question in questions:
            bloom_level = str(question.get("bloom_level", "remember"))
            bloom_counts[bloom_level] = bloom_counts.get(bloom_level, 0) + 1
        for concept in concepts:
            concept_type_counts[concept.concept_type] = concept_type_counts.get(concept.concept_type, 0) + 1

        return {
            "lesson_id": lesson_id,
            "chapter_id": str(lesson_context.get("chapter_id") or ""),
            "target_question_count": target_question_count,
            "generated_question_count": len(questions),
            "can_generate_quiz": len(questions) >= 10,
            "can_fill_question_bank": len(questions) >= target_question_count,
            "concept_count": len(concepts),
            "concepts": [
                {
                    "concept_id": concept.concept_id,
                    "name": concept.name,
                    "normalized_name": concept.normalized_name,
                    "concept_type": concept.concept_type,
                }
                for concept in concepts
            ],
            "relation_counts": {},
            "missing_relation_types": [],
            "bloom_distribution": bloom_counts,
            "concept_type_distribution": concept_type_counts,
            "sample_relations": [],
            "sample_questions": [item.get("question", "") for item in questions[:10]],
        }

    def _generate_for_bloom_level(
        self,
        *,
        concepts: Sequence[LessonConcept],
        bloom_level: str,
        required: int,
        concept_usage: Dict[str, int],
    ) -> List[Dict]:
        templates = select_template(bloom_level)
        if not templates:
            return []

        questions: List[Dict] = []
        concept_sequence = self._select_concept_sequence(concepts, bloom_level, required, concept_usage)
        template_cursors: Dict[str, int] = {}

        while len(questions) < required and concept_sequence:
            concept = concept_sequence[len(questions) % len(concept_sequence)]
            selected_templates = self._select_templates_for_concept(templates, bloom_level, concept)
            cursor_key = f"{bloom_level}:{concept.concept_id}"
            template_index = template_cursors.get(cursor_key, 0)
            template_id, template_text = selected_templates[template_index % len(selected_templates)]
            questions.append(
                self._build_question_record(
                    concept=concept,
                    bloom_level=bloom_level,
                    template_id=template_id,
                    question_text=template_text.format(concept=concept.name),
                )
            )
            template_cursors[cursor_key] = template_index + 1
            concept_usage[concept.concept_id] = concept_usage.get(concept.concept_id, 0) + 1

        return questions

    def _fill_shortfall(
        self,
        concepts: Sequence[LessonConcept],
        existing_questions: Sequence[Dict],
        target_count: int,
        concept_usage: Dict[str, int],
    ) -> List[Dict]:
        results = list(existing_questions)
        if len(results) >= target_count:
            return results

        extra_order = ["understand", "apply", "analyze", "evaluate", "create", "remember"]
        bloom_offsets = {level: 10 for level in extra_order}

        while len(results) < target_count:
            added = False
            seen_keys = {
                (item.get("question", "").strip().lower(), item.get("bloom_level", ""))
                for item in results
            }
            for bloom_level in extra_order:
                templates = select_template(bloom_level)
                if not templates:
                    continue
                offset = bloom_offsets[bloom_level]
                concept_sequence = self._select_concept_sequence(concepts, bloom_level, len(concepts), concept_usage)
                for concept in concept_sequence:
                    selected_templates = self._select_templates_for_concept(templates, bloom_level, concept)
                    template_id, template_text = selected_templates[offset % len(selected_templates)]
                    candidate = self._build_question_record(
                        concept=concept,
                        bloom_level=bloom_level,
                        template_id=f"{template_id}_extra_{offset}",
                        question_text=template_text.format(concept=concept.name),
                    )
                    key = (
                        candidate.get("question", "").strip().lower(),
                        candidate.get("bloom_level", ""),
                    )
                    offset += 1
                    if key in seen_keys:
                        continue
                    results.append(candidate)
                    concept_usage[concept.concept_id] = concept_usage.get(concept.concept_id, 0) + 1
                    bloom_offsets[bloom_level] = offset
                    added = True
                    break
                if len(results) >= target_count:
                    break
            if not added:
                break
        return results

    def _build_question_record(
        self,
        *,
        concept: LessonConcept,
        bloom_level: str,
        template_id: str,
        question_text: str,
    ) -> Dict:
        return {
            "question": question_text.strip(),
            "concept": concept.name,
            "bloom_level": bloom_level,
            "relation_type": "standalone",
            "template_id": template_id,
            "difficulty": BLOOM_DIFFICULTY[bloom_level],
            "related_concepts": [],
            "concept_type": concept.concept_type,
        }

    @staticmethod
    def _initialize_usage(concepts: Sequence[LessonConcept]) -> Dict[str, int]:
        return {concept.concept_id: 0 for concept in concepts}

    def _select_concept_sequence(
        self,
        concepts: Sequence[LessonConcept],
        bloom_level: str,
        required: int,
        concept_usage: Dict[str, int],
    ) -> List[LessonConcept]:
        ranked = sorted(
            concepts,
            key=lambda concept: (
                concept_usage.get(concept.concept_id, 0),
                self._concept_bloom_priority(concept, bloom_level),
                len(concept.normalized_name),
                concept.name.lower(),
            ),
        )
        if not ranked:
            return []
        if required <= len(ranked):
            return ranked[:required]
        return ranked

    def _concept_bloom_priority(self, concept: LessonConcept, bloom_level: str) -> int:
        if bloom_level == "remember":
            return 0
        if bloom_level == "understand":
            return 0 if concept.concept_type == "definition_concept" else 1
        if bloom_level == "apply":
            return 0 if concept.concept_type in {"algorithm_concept", "application_concept"} else 1
        if bloom_level == "analyze":
            return 0 if concept.concept_type in {"algorithm_concept", "system_concept"} else 1
        if bloom_level == "evaluate":
            return 0 if concept.concept_type in {"system_concept", "application_concept"} else 1
        if bloom_level == "create":
            return 0 if concept.concept_type in {"system_concept", "application_concept", "algorithm_concept"} else 1
        return 2

    def _select_templates_for_concept(
        self,
        templates: Sequence[Tuple[str, str]],
        bloom_level: str,
        concept: LessonConcept,
    ) -> List[Tuple[str, str]]:
        hints = CONCEPT_TYPE_TEMPLATE_HINTS.get(concept.concept_type, {}).get(bloom_level, [])
        if not hints:
            return list(templates)

        matched: List[Tuple[str, str]] = []
        unmatched: List[Tuple[str, str]] = []
        lowered_hints = [hint.lower() for hint in hints]
        for template in templates:
            template_text = template[1].lower()
            if any(hint in template_text for hint in lowered_hints):
                matched.append(template)
            else:
                unmatched.append(template)
        return matched + unmatched if matched else list(templates)

    def _resolve_lesson_context(self, lesson_id: str) -> Dict:
        lessons_collection = getattr(self.db, "lessons", None)
        if lessons_collection is not None:
            lesson = lessons_collection.find_one({"lesson_id": lesson_id}, {"_id": 0})
            if lesson:
                return lesson

        path = self.db.learning_paths.find_one(
            {"curriculum.lessons.lesson_id": lesson_id},
            {"curriculum": 1, "_id": 0},
        )
        if not path:
            raise ValueError(f"Lesson not found: {lesson_id}")

        for chapter in path.get("curriculum", []) or []:
            for lesson in chapter.get("lessons", []) or []:
                if lesson.get("lesson_id") == lesson_id:
                    lesson_copy = dict(lesson)
                    lesson_copy["chapter_id"] = chapter.get("chapter_id") or chapter.get("id") or chapter.get("title")
                    lesson_copy["chapter_concepts"] = chapter.get("concepts", [])
                    return lesson_copy

        raise ValueError(f"Lesson not found: {lesson_id}")

    def _resolve_chapter_context(self, chapter_id: str) -> Dict:
        chapters_collection = getattr(self.db, "chapters", None)
        if chapters_collection is not None:
            for query in self._build_chapter_queries(chapter_id):
                chapter = chapters_collection.find_one(query, {"_id": 0})
                if chapter:
                    return chapter

        for query in self._build_chapter_queries(chapter_id, embedded=True):
            path = self.db.learning_paths.find_one(query, {"curriculum": 1, "_id": 0})
            if not path:
                continue
            for chapter in path.get("curriculum", []) or []:
                if self._chapter_matches(chapter, chapter_id):
                    return chapter

        raise ValueError(f"Chapter not found: {chapter_id}")

    def _build_chapter_queries(self, chapter_id: str, embedded: bool = False) -> List[Dict]:
        field_prefix = "curriculum." if embedded else ""
        queries = [
            {f"{field_prefix}chapter_id": chapter_id},
            {f"{field_prefix}id": chapter_id},
            {f"{field_prefix}title": chapter_id},
        ]
        if ObjectId.is_valid(chapter_id):
            queries.append({f"{field_prefix}_id": ObjectId(chapter_id)})
        return queries

    @staticmethod
    def _chapter_matches(chapter: Dict, chapter_id: str) -> bool:
        return chapter_id in {
            str(chapter.get("chapter_id", "")),
            str(chapter.get("id", "")),
            str(chapter.get("title", "")),
        }

    def _extract_chapter_concepts(self, chapter: Dict) -> List[LessonConcept]:
        raw_concepts = list(chapter.get("concepts", []) or [])
        raw_concepts.extend(chapter.get("lessons", []) or [])
        return self._normalize_concepts(raw_concepts)

    def _extract_lesson_concepts(self, lesson: Dict) -> List[LessonConcept]:
        raw_concepts = list(lesson.get("concept_list") or [])
        raw_concepts.extend(lesson.get("chapter_concepts") or [])
        if not raw_concepts and lesson.get("title"):
            raw_concepts.append({
                "id": lesson.get("concept_id") or lesson.get("lesson_id") or lesson.get("title"),
                "name": lesson.get("concept_name") or lesson.get("title"),
            })
        return self._normalize_concepts(raw_concepts)

    def _normalize_concepts(self, raw_concepts: Iterable[Dict]) -> List[LessonConcept]:
        concepts: List[LessonConcept] = []
        seen = set()
        for raw in raw_concepts:
            concept_id = raw.get("id") or raw.get("concept_id") or raw.get("lesson_id") or raw.get("title")
            concept_name = raw.get("name") or raw.get("concept_name") or raw.get("title")
            if not concept_id or not concept_name:
                continue
            key = str(concept_id)
            if key in seen:
                continue
            seen.add(key)
            concepts.append(
                LessonConcept(
                    concept_id=str(concept_id),
                    name=str(concept_name).strip(),
                    normalized_name=normalize_concept(str(concept_name)),
                    concept_type=detect_concept_type(str(concept_name)),
                )
            )
        return concepts

    @staticmethod
    def _deduplicate_questions(questions: Sequence[Dict]) -> List[Dict]:
        results: List[Dict] = []
        seen = set()
        for item in questions:
            key = (
                item.get("question", "").strip().lower(),
                item.get("concept", "").strip().lower(),
                item.get("bloom_level", "").strip().lower(),
            )
            if key in seen:
                continue
            seen.add(key)
            results.append(item)
        return results


def generate_questions_for_lesson(lesson_id: str, target_count: int = 20) -> List[Dict]:
    generator = QuestionGenerator()
    return generator.generate_questions_for_lesson(lesson_id=lesson_id, target_count=target_count)


def generate_questions(chapter_id: str, num_questions: int) -> List[Dict]:
    generator = QuestionGenerator()
    return generator.generate_questions(chapter_id=chapter_id, num_questions=num_questions)


def debug_lesson_question_generation(lesson_id: str, target_question_count: int = 20) -> Dict:
    generator = QuestionGenerator()
    return generator.analyze_lesson_generation(
        lesson_id=lesson_id,
        target_question_count=target_question_count,
    )
