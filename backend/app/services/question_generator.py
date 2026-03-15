from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from bson import ObjectId

from backend.app.database.mongo import get_db

logger = logging.getLogger(__name__)


# =====================================================
# PSEUDOCODE
# =====================================================
# INPUT: chapter_id, num_questions
# 1. Load chapter by chapter_id.
# 2. Extract chapter concepts.
# 3. Load knowledge graph relations for these concepts.
# 4. For each concept:
#    - create a definition question from template
#    - find related concepts in the knowledge graph
#    - map relation_type to one or more templates
#    - fill template placeholders with concept names
#    - build metadata: concept, relation_type, related_concepts
# 5. Remove duplicate questions.
# 6. Prioritize relation-based questions, then definition questions.
# 7. Return at most num_questions items.


SUPPORTED_RELATIONS = {"prerequisite", "related_to", "used_in", "part_of"}
RELATION_PRIORITY = {
    "prerequisite": 1,
    "used_in": 2,
    "part_of": 3,
    "related_to": 4,
    "comparison": 5,
    "definition": 6,
}

DEFAULT_TEMPLATES: Dict[str, List[str]] = {
    "definition": [
        "{concept} là gì?",
        "Hãy giải thích khái niệm {concept}.",
        "Khái niệm cốt lõi của {concept} là gì?",
    ],
    "prerequisite": [
        "Vì sao cần học {concept1} trước {concept2}?",
        "{concept1} đóng vai trò nền tảng như thế nào cho {concept2}?",
        "Nếu chưa hiểu {concept1} thì sẽ gặp khó khăn gì khi học {concept2}?",
    ],
    "related_to": [
        "{concept1} liên quan như thế nào đến {concept2}?",
        "Mối liên hệ giữa {concept1} và {concept2} là gì?",
        "{concept1} hỗ trợ việc hiểu {concept2} ra sao?",
    ],
    "used_in": [
        "{concept1} được sử dụng như thế nào trong {concept2}?",
        "Vai trò của {concept1} trong {concept2} là gì?",
        "Khi áp dụng {concept2}, {concept1} xuất hiện ở bước nào?",
    ],
    "part_of": [
        "{concept1} là một phần của {concept2} như thế nào?",
        "{concept1} đóng góp gì trong cấu trúc của {concept2}?",
        "Trong tổng thể {concept2}, {concept1} giữ vai trò gì?",
    ],
    "comparison": [
        "Sự khác nhau giữa {concept1} và {concept2} là gì?",
        "Hãy so sánh {concept1} và {concept2}.",
        "Điểm giống và khác giữa {concept1} với {concept2} là gì?",
    ],
}


@dataclass(frozen=True)
class ConceptNode:
    concept_id: str
    name: str


@dataclass(frozen=True)
class KnowledgeRelation:
    source_concept: str
    target_concept: str
    relation_type: str


class QuestionGenerator:
    """
    Deterministic question generator using:
    1. Template-based question generation
    2. Knowledge graph-based question generation

    This module does not use AI/LLM.
    """

    def __init__(
        self,
        templates: Optional[Dict[str, List[str]]] = None
    ) -> None:
        self.db = get_db()
        self.templates = templates or DEFAULT_TEMPLATES

    def generate_questions(self, chapter_id: str, num_questions: int) -> List[Dict]:
        """
        Generate questions for a chapter using concept list + knowledge graph.

        Returns:
            [
                {
                    "question": "...",
                    "concept": "...",
                    "relation_type": "...",
                    "related_concepts": [...]
                }
            ]
        """
        if not chapter_id or not chapter_id.strip():
            raise ValueError("chapter_id cannot be empty")
        if num_questions <= 0:
            raise ValueError("num_questions must be greater than 0")

        chapter = self._get_chapter(chapter_id.strip())
        if not chapter:
            raise ValueError(f"Chapter not found: {chapter_id}")

        concepts = self._extract_chapter_concepts(chapter)
        if not concepts:
            logger.warning("Chapter '%s' has no concepts", chapter_id)
            return []

        relations = self._get_knowledge_relations(concepts)
        concept_ids = {concept.concept_id for concept in concepts}

        relation_questions = self._build_relation_questions(concepts, relations, concept_ids)
        definition_questions = self._build_definition_questions(concepts)
        comparison_questions = self._build_comparison_questions(concepts)

        all_questions = relation_questions + comparison_questions + definition_questions
        deduplicated = self._deduplicate_questions(all_questions)
        ordered = self._prioritize_questions(deduplicated)

        return ordered[:num_questions]

    def _get_chapter(self, chapter_id: str) -> Optional[Dict]:
        """
        Chapter lookup strategy:
        - `chapters` collection by chapter_id/id/_id/title
        - embedded curriculum chapter inside `learning_paths`
        """
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

        return None

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

    def _extract_chapter_concepts(self, chapter: Dict) -> List[ConceptNode]:
        """
        Support multiple chapter shapes:
        - {"concepts": [{"id": "...", "name": "..."}]}
        - {"lessons": [{"concept_id": 1, "title": "Functions"}]}
        - {"lessons": [{"concept": {"id": "...", "name": "..."}}]}
        """
        results: List[ConceptNode] = []
        seen: set[str] = set()

        for raw_concept in chapter.get("concepts", []) or []:
            concept = self._normalize_concept(raw_concept)
            if concept and concept.concept_id not in seen:
                seen.add(concept.concept_id)
                results.append(concept)

        for lesson in chapter.get("lessons", []) or []:
            nested = lesson.get("concept")
            if nested:
                concept = self._normalize_concept(nested)
            else:
                concept = self._normalize_concept({
                    "id": lesson.get("concept_id") or lesson.get("title"),
                    "name": lesson.get("concept_name") or lesson.get("title"),
                })

            if concept and concept.concept_id not in seen:
                seen.add(concept.concept_id)
                results.append(concept)

        return results

    def _normalize_concept(self, raw_concept: Dict) -> Optional[ConceptNode]:
        if not isinstance(raw_concept, dict):
            return None

        concept_id = raw_concept.get("id")
        if concept_id is None:
            concept_id = raw_concept.get("concept_id")
        if concept_id is None:
            concept_id = raw_concept.get("name") or raw_concept.get("concept_name")

        name = raw_concept.get("name") or raw_concept.get("concept_name")
        if not concept_id or not name:
            return None

        return ConceptNode(concept_id=str(concept_id), name=str(name).strip())

    def _get_knowledge_relations(self, concepts: Sequence[ConceptNode]) -> List[KnowledgeRelation]:
        """
        Load relations from:
        - `knowledge_relations` collection if available
        - `prerequisites` collection as prerequisite edges
        """
        concept_ids = {concept.concept_id for concept in concepts}
        relations: List[KnowledgeRelation] = []

        knowledge_relations = getattr(self.db, "knowledge_relations", None)
        if knowledge_relations is not None:
            query = {
                "$or": [
                    {"source_concept": {"$in": list(concept_ids)}},
                    {"target_concept": {"$in": list(concept_ids)}},
                ]
            }
            for item in knowledge_relations.find(query, {"_id": 0}):
                relation = self._normalize_relation(item)
                if relation:
                    relations.append(relation)

        for item in self.db.prerequisites.find({}, {"_id": 0}):
            source = item.get("from_concept_id")
            target = item.get("to_concept_id")
            if source is None or target is None:
                continue
            relations.append(
                KnowledgeRelation(
                    source_concept=str(source),
                    target_concept=str(target),
                    relation_type="prerequisite"
                )
            )

        return relations

    def _normalize_relation(self, item: Dict) -> Optional[KnowledgeRelation]:
        if not isinstance(item, dict):
            return None

        source = item.get("source_concept")
        target = item.get("target_concept")
        relation_type = str(item.get("relation_type", "")).strip()

        if source is None or target is None or relation_type not in SUPPORTED_RELATIONS:
            return None

        return KnowledgeRelation(
            source_concept=str(source),
            target_concept=str(target),
            relation_type=relation_type
        )

    def _build_relation_questions(
        self,
        concepts: Sequence[ConceptNode],
        relations: Sequence[KnowledgeRelation],
        chapter_concept_ids: set[str]
    ) -> List[Dict]:
        concept_map = {concept.concept_id: concept.name for concept in concepts}
        results: List[Dict] = []

        for relation in relations:
            if relation.source_concept not in chapter_concept_ids and relation.target_concept not in chapter_concept_ids:
                continue

            source_name = concept_map.get(relation.source_concept) or self._lookup_concept_name(relation.source_concept)
            target_name = concept_map.get(relation.target_concept) or self._lookup_concept_name(relation.target_concept)

            if not source_name or not target_name:
                continue

            templates = self.templates.get(relation.relation_type, [])
            for template in templates:
                focus_concept = target_name if relation.relation_type == "prerequisite" else source_name
                results.append({
                    "question": template.format(concept1=source_name, concept2=target_name),
                    "concept": focus_concept,
                    "relation_type": relation.relation_type,
                    "related_concepts": [source_name, target_name]
                })

        return results

    def _build_definition_questions(self, concepts: Sequence[ConceptNode]) -> List[Dict]:
        results: List[Dict] = []
        for concept in concepts:
            for template in self.templates.get("definition", []):
                results.append({
                    "question": template.format(concept=concept.name),
                    "concept": concept.name,
                    "relation_type": "definition",
                    "related_concepts": [concept.name]
                })
        return results

    def _build_comparison_questions(self, concepts: Sequence[ConceptNode]) -> List[Dict]:
        if len(concepts) < 2:
            return []

        results: List[Dict] = []
        related_pairs = self._related_concept_pairs(concepts)
        for left, right in related_pairs:
            for template in self.templates.get("comparison", []):
                results.append({
                    "question": template.format(concept1=left.name, concept2=right.name),
                    "concept": left.name,
                    "relation_type": "comparison",
                    "related_concepts": [left.name, right.name]
                })
        return results

    @staticmethod
    def _pairwise(concepts: Sequence[ConceptNode]) -> Iterable[Tuple[ConceptNode, ConceptNode]]:
        for index, left in enumerate(concepts):
            for right in concepts[index + 1:]:
                yield left, right

    def _related_concept_pairs(self, concepts: Sequence[ConceptNode]) -> List[Tuple[ConceptNode, ConceptNode]]:
        pairs = list(self._pairwise(concepts))
        if len(pairs) <= 3:
            return pairs
        return pairs[:3]

    def _lookup_concept_name(self, concept_id: str) -> Optional[str]:
        query_options = []
        if concept_id.isdigit():
            query_options.append({"concept_id": int(concept_id)})
        query_options.append({"concept_id": concept_id})

        for query in query_options:
            concept = self.db.concepts.find_one(query, {"_id": 0, "concept_name": 1, "name": 1})
            if concept:
                return concept.get("concept_name") or concept.get("name")
        return None

    @staticmethod
    def _deduplicate_questions(questions: Sequence[Dict]) -> List[Dict]:
        results: List[Dict] = []
        seen = set()

        for item in questions:
            key = (
                item.get("question", "").strip().lower(),
                item.get("concept", "").strip().lower(),
                item.get("relation_type", "").strip().lower(),
            )
            if key in seen:
                continue
            seen.add(key)
            results.append(item)

        return results

    def _prioritize_questions(self, questions: Sequence[Dict]) -> List[Dict]:
        buckets: Dict[str, List[Dict]] = {}
        for item in questions:
            concept_name = str(item.get("concept", "")).strip().lower() or "unknown"
            buckets.setdefault(concept_name, []).append(item)

        for concept_name in buckets:
            buckets[concept_name].sort(
                key=lambda item: (
                    RELATION_PRIORITY.get(str(item.get("relation_type", "")), 99),
                    len(item.get("related_concepts", [])) * -1,
                    item.get("question", "")
                )
            )

        ordered: List[Dict] = []
        while True:
            added = False
            for concept_name in sorted(buckets.keys()):
                if not buckets[concept_name]:
                    continue
                ordered.append(buckets[concept_name].pop(0))
                added = True
            if not added:
                break

        return ordered


def generate_questions(chapter_id: str, num_questions: int) -> List[Dict]:
    """
    Convenience function requested by the assignment.
    """
    generator = QuestionGenerator()
    return generator.generate_questions(chapter_id=chapter_id, num_questions=num_questions)
