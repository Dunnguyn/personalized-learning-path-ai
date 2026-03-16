from __future__ import annotations

from collections import defaultdict
from typing import Dict, Iterable, List, Sequence, Tuple

from backend.app.services.question_generation.generator import LessonConcept, QuestionGenerator


# =====================================================
# ANALYSIS
# =====================================================
# This module upgrades lesson question generation with Bloom's Taxonomy.
# It keeps the system deterministic by using:
# - lesson concepts
# - knowledge graph relations
# - rule-based NLP concept metadata
# - fixed templates per Bloom level
#
# Target distribution for 20 questions:
# Remember: 4
# Understand: 4
# Apply: 4
# Analyze: 3
# Evaluate: 3
# Create: 2


# =====================================================
# PSEUDOCODE
# =====================================================
# generate_questions_for_lesson(lesson_id):
# 1. Resolve lesson context and normalize lesson concepts.
# 2. Collect explicit + soft relations from the knowledge graph.
# 3. For each Bloom level:
#    - choose the concept or relation source pool
#    - fill fixed templates
#    - stop when the target count for that level is reached
# 4. Deduplicate questions across all levels.
# 5. Rebalance if some levels are short by using fallback templates.
# 6. Return up to 20 final questions with bloom_level + difficulty.


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

BLOOM_TEMPLATES: Dict[str, List[Tuple[str, str]]] = {
    "remember": [
        ("remember_1", "{concept} là gì?"),
        ("remember_2", "Định nghĩa của {concept} là gì?"),
        ("remember_3", "Liệt kê các đặc điểm chính của {concept}."),
    ],
    "understand": [
        ("understand_1", "Giải thích khái niệm {concept}."),
        ("understand_2", "Tại sao {concept} lại quan trọng?"),
        ("understand_3", "Mô tả cách hoạt động của {concept}."),
    ],
    "apply": [
        ("apply_1", "Làm thế nào để áp dụng {concept} trong {context}?"),
        ("apply_2", "{concept} có thể được sử dụng trong trường hợp nào?"),
        ("apply_3", "Khi triển khai {context}, {concept} được dùng ở bước nào?"),
    ],
    "analyze": [
        ("analyze_1", "Phân tích mối quan hệ giữa {concept1} và {concept2}."),
        ("analyze_2", "Tại sao {concept1} lại ảnh hưởng đến {concept2}?"),
        ("analyze_3", "{concept1} và {concept2} tác động qua lại ra sao trong bài học này?"),
    ],
    "evaluate": [
        ("evaluate_1", "So sánh {concept1} và {concept2}."),
        ("evaluate_2", "Trong trường hợp nào nên sử dụng {concept1} thay vì {concept2}?"),
        ("evaluate_3", "Theo bạn, khi nào {concept1} phù hợp hơn {concept2}?"),
    ],
    "create": [
        ("create_1", "Thiết kế một ví dụ minh họa cho {concept}."),
        ("create_2", "Làm thế nào bạn có thể cải tiến {concept} trong hệ thống thực tế?"),
        ("create_3", "Hãy đề xuất một tình huống mới để áp dụng {concept}."),
    ],
}


class BloomQuestionGenerator:
    def __init__(self) -> None:
        self.base_generator = QuestionGenerator()

    def generate_questions_for_lesson(self, lesson_id: str, target_count: int = 20) -> List[Dict]:
        lesson_context = self.base_generator._resolve_lesson_context(lesson_id)
        concepts = self.base_generator._extract_lesson_concepts(lesson_context)
        if not concepts:
            raise ValueError(f"Lesson has no concepts: {lesson_id}")

        relations = self.base_generator._collect_relations(concepts)
        relation_pairs = self._build_relation_pairs(concepts, relations)

        questions: List[Dict] = []
        for bloom_level, required in BLOOM_DISTRIBUTION:
            questions.extend(
                self._generate_for_level(
                    bloom_level=bloom_level,
                    required=required,
                    concepts=concepts,
                    relation_pairs=relation_pairs,
                )
            )

        deduplicated = self.base_generator._deduplicate_questions(questions)
        balanced = self._rebalance_shortfall(
            deduplicated=deduplicated,
            concepts=concepts,
            relation_pairs=relation_pairs,
            target_count=target_count,
        )
        return balanced[:target_count]

    def analyze_generation(self, lesson_id: str, target_count: int = 20) -> Dict:
        questions = self.generate_questions_for_lesson(lesson_id=lesson_id, target_count=target_count)
        bloom_counts = defaultdict(int)
        for question in questions:
            bloom_counts[str(question.get("bloom_level", "remember"))] += 1
        return {
            "generated_question_count": len(questions),
            "bloom_distribution": dict(bloom_counts),
            "sample_questions": questions[:10],
        }

    def _generate_for_level(
        self,
        *,
        bloom_level: str,
        required: int,
        concepts: Sequence[LessonConcept],
        relation_pairs: Sequence[Tuple[LessonConcept, LessonConcept, str]],
    ) -> List[Dict]:
        items: List[Dict] = []
        templates = BLOOM_TEMPLATES[bloom_level]

        if bloom_level in {"remember", "understand", "create"}:
            for concept in concepts:
                for template_id, template_text in templates:
                    if bloom_level == "create" and concept.concept_type == "definition":
                        continue
                    items.append(
                        self._build_record(
                            question_text=template_text.format(concept=concept.name),
                            concept=concept,
                            bloom_level=bloom_level,
                            template_id=template_id,
                            relation_type="definition" if bloom_level == "remember" else "explanation",
                            related_concepts=[concept.name],
                        )
                    )
                    if len(items) >= required:
                        return items

        if bloom_level == "apply":
            for concept in concepts:
                contexts = self._contexts_for_concept(concept, relation_pairs)
                if not contexts:
                    contexts = [concept.name]
                for context in contexts:
                    for template_id, template_text in templates:
                        items.append(
                            self._build_record(
                                question_text=template_text.format(concept=concept.name, context=context),
                                concept=concept,
                                bloom_level=bloom_level,
                                template_id=template_id,
                                relation_type="used_in",
                                related_concepts=[concept.name, context],
                            )
                        )
                        if len(items) >= required:
                            return items

        if bloom_level in {"analyze", "evaluate"}:
            for left, right, relation_type in relation_pairs:
                for template_id, template_text in templates:
                    items.append(
                        self._build_record(
                            question_text=template_text.format(concept1=left.name, concept2=right.name),
                            concept=left,
                            bloom_level=bloom_level,
                            template_id=template_id,
                            relation_type=relation_type,
                            related_concepts=[left.name, right.name],
                        )
                    )
                    if len(items) >= required:
                        return items

        return items[:required]

    def _build_relation_pairs(
        self,
        concepts: Sequence[LessonConcept],
        relations: Iterable,
    ) -> List[Tuple[LessonConcept, LessonConcept, str]]:
        concept_map = {concept.concept_id: concept for concept in concepts}
        pairs: List[Tuple[LessonConcept, LessonConcept, str]] = []
        seen = set()

        for relation in relations:
            left = concept_map.get(relation.source_concept) or self.base_generator._load_external_concept(relation.source_concept)
            right = concept_map.get(relation.target_concept) or self.base_generator._load_external_concept(relation.target_concept)
            if not left or not right:
                continue
            key = (left.concept_id, right.concept_id, relation.relation_type)
            if key in seen:
                continue
            seen.add(key)
            pairs.append((left, right, relation.relation_type))

        if not pairs:
            for left, right in self.base_generator._pairwise(concepts):
                pairs.append((left, right, "related_to"))

        return pairs

    @staticmethod
    def _contexts_for_concept(
        concept: LessonConcept,
        relation_pairs: Sequence[Tuple[LessonConcept, LessonConcept, str]],
    ) -> List[str]:
        contexts: List[str] = []
        for left, right, _ in relation_pairs:
            if left.concept_id == concept.concept_id:
                contexts.append(right.name)
            elif right.concept_id == concept.concept_id:
                contexts.append(left.name)
        return list(dict.fromkeys(contexts))

    def _rebalance_shortfall(
        self,
        *,
        deduplicated: Sequence[Dict],
        concepts: Sequence[LessonConcept],
        relation_pairs: Sequence[Tuple[LessonConcept, LessonConcept, str]],
        target_count: int,
    ) -> List[Dict]:
        ordered: List[Dict] = list(deduplicated)
        if len(ordered) >= target_count:
            return ordered

        counts = defaultdict(int)
        for item in ordered:
            counts[str(item.get("bloom_level", ""))] += 1

        for bloom_level, required in BLOOM_DISTRIBUTION:
            if counts[bloom_level] >= required:
                continue
            additional = self._generate_for_level(
                bloom_level=bloom_level,
                required=required * 2,
                concepts=concepts,
                relation_pairs=relation_pairs,
            )
            for item in additional:
                key = (
                    item.get("question", "").strip().lower(),
                    item.get("bloom_level", ""),
                )
                existing_keys = {
                    (
                        existing.get("question", "").strip().lower(),
                        existing.get("bloom_level", ""),
                    )
                    for existing in ordered
                }
                if key in existing_keys:
                    continue
                ordered.append(item)
                counts[bloom_level] += 1
                if len(ordered) >= target_count:
                    return ordered
                if counts[bloom_level] >= required:
                    break

        return ordered

    @staticmethod
    def _build_record(
        *,
        question_text: str,
        concept: LessonConcept,
        bloom_level: str,
        template_id: str,
        relation_type: str,
        related_concepts: List[str],
    ) -> Dict:
        return {
            "question": question_text.strip(),
            "concept": concept.name,
            "related_concepts": related_concepts,
            "bloom_level": bloom_level,
            "relation_type": relation_type,
            "template_id": template_id,
            "difficulty": BLOOM_DIFFICULTY[bloom_level],
            "concept_type": concept.concept_type,
            "keywords": list(concept.keywords),
        }


def generate_questions_for_lesson(lesson_id: str, target_count: int = 20) -> List[Dict]:
    generator = BloomQuestionGenerator()
    return generator.generate_questions_for_lesson(lesson_id=lesson_id, target_count=target_count)
