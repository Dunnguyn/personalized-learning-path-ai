"""Fallback question generation service when LLM is unavailable or disabled."""

from __future__ import annotations

from collections import defaultdict
import re
from typing import Any, Dict, List, Sequence

from backend.app.services.concept_normalization_service import (
    concept_normalization_service,
)
from backend.app.services.question_nlp_service import question_nlp_service
from backend.app.services.question_template_service import QuestionTemplateService


class QuestionFallbackService:
    """Create robust local fallback candidates from lesson chunks."""

    def __init__(self) -> None:
        self.template_service = QuestionTemplateService()
        self.question_nlp_service = question_nlp_service

    def get_claim_cache_stats(self) -> Dict[str, int | float]:
        return self.template_service.get_claim_cache_stats()

    def build_candidates(
        self,
        *,
        lesson_title: str,
        lesson_summary: str = "",
        chunks: List[Dict[str, Any]],
        target_count: int,
        question_types: List[str],
        difficulty: str,
        bloom_levels: List[str],
        retry_attempts: int = 2,
        target_concepts: Sequence[str] | None = None,
        lesson_concepts: Sequence[str] | None = None,
    ) -> List[Dict[str, Any]]:
        candidates: List[Dict[str, Any]] = []
        seen: set[str] = set()
        attempts = max(1, retry_attempts + 1)
        normalized_targets = self._normalize_target_concepts(target_concepts)
        normalized_lesson_concepts = self._normalize_target_concepts(lesson_concepts)
        if not normalized_targets and normalized_lesson_concepts:
            normalized_targets = normalized_lesson_concepts[:3]
        if not normalized_targets:
            normalized_targets = concept_normalization_service.extract_fallback_target_concepts(
                {"chunks": chunks},
                limit=3,
            )
        summary_keywords = self.question_nlp_service.extract_keyphrases(
            lesson_summary,
            top_k=8,
        )
        scoring_targets = self._normalize_target_concepts(
            [*normalized_targets, *summary_keywords]
        )
        chunk_profiles = self._build_chunk_profiles(
            chunks=chunks,
            target_concepts=scoring_targets,
        )

        for attempt in range(attempts):
            if len(candidates) >= target_count:
                break

            retry_chunks = self._select_retry_chunks(chunks=chunks, attempt=attempt)
            retry_chunks = self._prioritize_retry_chunks(
                chunks=retry_chunks,
                attempt=attempt,
                chunk_profiles=chunk_profiles,
                target_concepts=normalized_targets,
            )
            retry_types = self._select_retry_types(
                question_types=question_types,
                attempt=attempt,
            )
            retry_bloom = self._select_retry_bloom_levels(
                bloom_levels=bloom_levels,
                attempt=attempt,
            )
            batch = self.template_service.build_candidates(
                lesson_title=lesson_title,
                lesson_summary=lesson_summary,
                lesson_keywords=summary_keywords,
                chunks=retry_chunks,
                target_count=max(target_count * 2, target_count + 2),
                question_types=retry_types,
                difficulty=difficulty,
                bloom_levels=retry_bloom,
                max_per_chunk=2,
            )
            for item in batch:
                signature = self._signature(item)
                if not signature or signature in seen:
                    continue

                metadata = (
                    item.get("metadata")
                    if isinstance(item.get("metadata"), dict)
                    else {}
                )
                metadata["fallback_attempt"] = attempt
                metadata["fallback_chunk_score"] = round(
                    self._candidate_chunk_score(
                        candidate=item,
                        chunk_profiles=chunk_profiles,
                    ),
                    4,
                )
                matched_target_concepts = self._resolve_candidate_target_matches(
                    candidate=item,
                    target_concepts=normalized_targets,
                )
                metadata["matched_target_concepts"] = list(matched_target_concepts)
                metadata["target_concept_match"] = bool(matched_target_concepts)
                metadata["target_semantic_score"] = round(
                    self._candidate_target_semantic_score(
                        candidate=item,
                        target_concepts=scoring_targets,
                    ),
                    4,
                )
                if normalized_targets:
                    metadata.setdefault("target_concepts", list(normalized_targets))
                if summary_keywords:
                    metadata["lesson_summary_keywords"] = list(summary_keywords)
                metadata["concept_focus"] = str(
                    next((item for item in matched_target_concepts if str(item).strip()), "")
                    or metadata.get("question_focus")
                    or next(
                        (
                            item
                            for item in metadata.get("covered_concepts") or []
                            if str(item).strip()
                        ),
                        "",
                    )
                ).strip()
                metadata["evidence_excerpt"] = str(
                    metadata.get("source_excerpt") or metadata.get("evidence_excerpt") or ""
                ).strip()
                item["metadata"] = metadata

                seen.add(signature)
                candidates.append(item)
                if len(candidates) >= target_count:
                    break

        for item in candidates:
            metadata = (
                item.get("metadata") if isinstance(item.get("metadata"), dict) else {}
            )
            metadata["generation_mode"] = "local_fallback"
            metadata["generation_source"] = "local_fallback"
            metadata["fallback_priority_score"] = round(
                self._score_candidate(
                    candidate=item,
                    chunk_profiles=chunk_profiles,
                    target_concepts=scoring_targets,
                ),
                4,
            )
            metadata.setdefault(
                "reasoning_note",
                "Generated by local fallback due to unavailable or disabled LLM.",
            )
            item["metadata"] = metadata

        return self._rebalance_candidates(
            candidates=candidates,
            target_count=target_count,
            requested_question_types=question_types,
            target_concepts=scoring_targets,
            chunk_profiles=chunk_profiles,
        )

    @staticmethod
    def _signature(candidate: Dict[str, Any]) -> str:
        question = " ".join(str(candidate.get("question") or "").lower().split())
        answer = " ".join(str(candidate.get("correct_answer") or "").lower().split())
        return f"{question}|{answer}"

    @staticmethod
    def _select_retry_chunks(
        *,
        chunks: List[Dict[str, Any]],
        attempt: int,
    ) -> List[Dict[str, Any]]:
        if attempt <= 0:
            return list(chunks)
        if attempt % 2 == 1:
            return list(reversed(chunks))
        filtered = [
            chunk
            for index, chunk in enumerate(chunks)
            if index % 2 == attempt % 2
        ]
        return filtered or list(chunks)

    def _prioritize_retry_chunks(
        self,
        *,
        chunks: List[Dict[str, Any]],
        attempt: int,
        chunk_profiles: Dict[str, Dict[str, Any]],
        target_concepts: Sequence[str],
    ) -> List[Dict[str, Any]]:
        role_bias = self._attempt_role_bias(attempt)

        def sort_key(chunk: Dict[str, Any]) -> tuple[float, float]:
            chunk_id = str(chunk.get("_id") or "").strip()
            profile = chunk_profiles.get(chunk_id, {})
            score = float(profile.get("priority_score", 0.0) or 0.0)
            role = str(profile.get("instruction_role") or "explanation").strip().lower()
            score += role_bias.get(role, 0.0)
            if target_concepts and profile.get("target_match"):
                score += 0.35
            if profile.get("has_code") and attempt % 2 == 0:
                score += 0.25
            if profile.get("has_example") and attempt <= 1:
                score += 0.2
            return (score, float(profile.get("questionability_score", 0.0) or 0.0))

        return sorted(chunks, key=sort_key, reverse=True)

    @staticmethod
    def _select_retry_types(*, question_types: List[str], attempt: int) -> List[str]:
        selected = list(dict.fromkeys(question_types or ["multiple_choice"]))
        if attempt == 0:
            return selected
        preferred_orders = (
            ["multiple_choice", "short_answer", "true_false"],
            ["short_answer", "multiple_choice", "true_false"],
        )
        preferred = preferred_orders[attempt % 2]
        reordered = [item for item in preferred if item in selected]
        return reordered or selected

    @staticmethod
    def _select_retry_bloom_levels(
        *, bloom_levels: List[str], attempt: int
    ) -> List[str]:
        selected = bloom_levels or ["remember", "understand"]
        if attempt == 0:
            ordered = [item for item in ["understand", "apply", "remember", "analyze"] if item in selected]
            return ordered or selected
        if attempt % 2 == 1:
            return ["understand", "apply", "remember", "analyze"]
        return ["apply", "analyze", "understand", "remember"]

    def _rebalance_candidates(
        self,
        *,
        candidates: List[Dict[str, Any]],
        target_count: int,
        requested_question_types: List[str],
        target_concepts: Sequence[str],
        chunk_profiles: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if target_count <= 0 or not candidates:
            return []

        ranked_candidates = sorted(
            candidates,
            key=lambda candidate: self._score_candidate(
                candidate=candidate,
                chunk_profiles=chunk_profiles,
                target_concepts=target_concepts,
            ),
            reverse=True,
        )
        preferred_styles = self._build_style_plan(
            target_count=target_count,
            requested_question_types=requested_question_types,
            candidates=ranked_candidates,
        )
        selected: List[Dict[str, Any]] = []
        used_indexes: set[int] = set()
        focus_usage: dict[str, int] = defaultdict(int)
        role_usage: dict[str, int] = defaultdict(int)

        coverage_seed = self._seed_target_coverage_candidates(
            candidates=ranked_candidates,
            target_concepts=target_concepts,
            chunk_profiles=chunk_profiles,
            used_indexes=used_indexes,
            focus_usage=focus_usage,
            role_usage=role_usage,
        )
        selected.extend(coverage_seed)

        for style in preferred_styles:
            if len(selected) >= target_count:
                break
            match_index = self._find_candidate_index(
                candidates=ranked_candidates,
                target_style=style,
                used_indexes=used_indexes,
                focus_usage=focus_usage,
                role_usage=role_usage,
                allow_repeat_focus=False,
            )
            if match_index is None:
                continue
            used_indexes.add(match_index)
            self._record_focus(ranked_candidates[match_index], focus_usage)
            self._record_role(ranked_candidates[match_index], role_usage)
            selected.append(ranked_candidates[match_index])

        for question_type in self._preferred_question_type_order(
            requested_question_types=requested_question_types
        ):
            if len(selected) >= target_count:
                break
            match_index = self._find_candidate_index(
                candidates=ranked_candidates,
                target_question_type=question_type,
                used_indexes=used_indexes,
                focus_usage=focus_usage,
                role_usage=role_usage,
                allow_repeat_focus=False,
            )
            if match_index is None:
                continue
            used_indexes.add(match_index)
            self._record_focus(ranked_candidates[match_index], focus_usage)
            self._record_role(ranked_candidates[match_index], role_usage)
            selected.append(ranked_candidates[match_index])

        for allow_repeat_focus in (False, True):
            for index, candidate in enumerate(ranked_candidates):
                if len(selected) >= target_count:
                    break
                if index in used_indexes:
                    continue
                if (
                    not allow_repeat_focus
                    and self._candidate_focus_used(candidate, focus_usage)
                ):
                    continue
                if (
                    not allow_repeat_focus
                    and self._candidate_role_saturated(candidate, role_usage)
                ):
                    continue
                used_indexes.add(index)
                self._record_focus(candidate, focus_usage)
                self._record_role(candidate, role_usage)
                selected.append(candidate)
            if len(selected) >= target_count:
                break

        return selected[:target_count]

    def _seed_target_coverage_candidates(
        self,
        *,
        candidates: List[Dict[str, Any]],
        target_concepts: Sequence[str],
        chunk_profiles: Dict[str, Dict[str, Any]],
        used_indexes: set[int],
        focus_usage: dict[str, int],
        role_usage: dict[str, int],
    ) -> List[Dict[str, Any]]:
        normalized_targets = self._normalize_target_concepts(target_concepts)
        if not normalized_targets:
            return []

        selected: List[Dict[str, Any]] = []
        covered_targets: set[str] = set()
        for allow_repeat_focus in (False, True):
            progress = False
            for target in normalized_targets:
                if target in covered_targets:
                    continue
                best_index: int | None = None
                best_score = -1e9
                for index, candidate in enumerate(candidates):
                    if index in used_indexes:
                        continue
                    matches = self._resolve_candidate_target_matches(
                        candidate=candidate,
                        target_concepts=[target],
                    )
                    if target not in matches:
                        continue
                    if (
                        not allow_repeat_focus
                        and self._candidate_focus_used(candidate, focus_usage)
                    ):
                        continue
                    if (
                        not allow_repeat_focus
                        and self._candidate_role_saturated(candidate, role_usage)
                    ):
                        continue
                    score = self._score_candidate(
                        candidate=candidate,
                        chunk_profiles=chunk_profiles,
                        target_concepts=[target],
                    )
                    if score > best_score:
                        best_score = score
                        best_index = index
                if best_index is None:
                    continue
                picked = candidates[best_index]
                used_indexes.add(best_index)
                self._record_focus(picked, focus_usage)
                self._record_role(picked, role_usage)
                selected.append(picked)
                covered_targets.add(target)
                progress = True
            if len(covered_targets) >= len(normalized_targets) or not progress:
                break
        return selected

    @staticmethod
    def _preferred_question_type_order(
        *, requested_question_types: List[str]
    ) -> List[str]:
        requested = list(dict.fromkeys(requested_question_types or ["multiple_choice"]))
        ordered = [
            item
            for item in ["multiple_choice", "short_answer", "true_false"]
            if item in requested
        ]
        for fallback in ["multiple_choice", "short_answer", "true_false"]:
            if fallback not in ordered:
                ordered.append(fallback)
        return ordered

    def _build_style_plan(
        self,
        *,
        target_count: int,
        requested_question_types: List[str],
        candidates: List[Dict[str, Any]],
    ) -> List[str]:
        available_styles = {
            self._candidate_style(candidate)
            for candidate in candidates
            if self._candidate_style(candidate)
        }
        requested = set(requested_question_types or ["multiple_choice"])
        preferred = self._style_quota_plan(
            target_count=target_count,
            requested_question_types=requested,
        )

        result: List[str] = []
        seen: set[str] = set()
        for style in preferred:
            if style in available_styles and style not in seen:
                seen.add(style)
                result.append(style)
        return result

    @staticmethod
    def _style_quota_plan(
        *,
        target_count: int,
        requested_question_types: set[str],
    ) -> List[str]:
        plan: List[str] = []
        include_mcq = (
            "multiple_choice" in requested_question_types
            or not requested_question_types
        )
        include_short = "short_answer" in requested_question_types
        include_tf = "true_false" in requested_question_types

        if include_mcq:
            plan.extend(["focus_from_description_mcq", "describe_focus_mcq"])
            if target_count >= 4:
                plan.append("fill_blank_mcq")
            if target_count >= 6:
                plan.append("complete_concept_mcq")
            if target_count >= 8:
                plan.append("describe_focus_mcq")

        if include_short and target_count >= 4:
            plan.append("describe_focus_short")
        if include_short and target_count >= 7:
            plan.append("complete_statement_short")
        if include_tf and target_count >= 8:
            plan.append("true_false_statement")

        return plan

    def _find_candidate_index(
        self,
        *,
        candidates: List[Dict[str, Any]],
        used_indexes: set[int],
        focus_usage: dict[str, int],
        role_usage: dict[str, int],
        target_style: str | None = None,
        target_question_type: str | None = None,
        allow_repeat_focus: bool,
    ) -> int | None:
        for index, candidate in enumerate(candidates):
            if index in used_indexes:
                continue
            if target_style and self._candidate_style(candidate) != target_style:
                continue
            if (
                target_question_type
                and str(candidate.get("question_type") or "").strip()
                != target_question_type
            ):
                continue
            if (
                not allow_repeat_focus
                and self._candidate_focus_used(candidate, focus_usage)
            ):
                continue
            if (
                not allow_repeat_focus
                and self._candidate_role_saturated(candidate, role_usage)
            ):
                continue
            return index
        return None

    @staticmethod
    def _candidate_style(candidate: Dict[str, Any]) -> str:
        metadata = (
            candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        )
        return str(metadata.get("fallback_style") or "").strip()

    @staticmethod
    def _candidate_focus(candidate: Dict[str, Any]) -> str:
        metadata = (
            candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        )
        return " ".join(str(metadata.get("question_focus") or "").lower().split())

    @staticmethod
    def _candidate_role(candidate: Dict[str, Any]) -> str:
        metadata = (
            candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        )
        return str(metadata.get("instruction_role") or "explanation").strip().lower()

    def _candidate_focus_used(
        self, candidate: Dict[str, Any], focus_usage: dict[str, int]
    ) -> bool:
        focus = self._candidate_focus(candidate)
        return bool(focus and focus_usage.get(focus, 0) >= 1)

    def _record_focus(
        self, candidate: Dict[str, Any], focus_usage: dict[str, int]
    ) -> None:
        focus = self._candidate_focus(candidate)
        if focus:
            focus_usage[focus] = focus_usage.get(focus, 0) + 1

    def _candidate_role_saturated(
        self, candidate: Dict[str, Any], role_usage: dict[str, int]
    ) -> bool:
        role = self._candidate_role(candidate)
        if not role:
            return False
        limit = 1 if role in {"worked_example", "definition", "summary"} else 2
        return role_usage.get(role, 0) >= limit

    def _record_role(
        self, candidate: Dict[str, Any], role_usage: dict[str, int]
    ) -> None:
        role = self._candidate_role(candidate)
        if role:
            role_usage[role] = role_usage.get(role, 0) + 1

    def _build_chunk_profiles(
        self,
        *,
        chunks: List[Dict[str, Any]],
        target_concepts: Sequence[str],
    ) -> Dict[str, Dict[str, Any]]:
        claim_units = self.template_service._build_claim_units(chunks)
        claims_by_chunk: dict[str, list[Dict[str, Any]]] = defaultdict(list)
        for claim in claim_units:
            chunk_id = str(claim.get("chunk_id") or "").strip()
            if chunk_id:
                claims_by_chunk[chunk_id].append(claim)

        profiles: Dict[str, Dict[str, Any]] = {}
        for chunk in chunks:
            chunk_id = str(chunk.get("_id") or "").strip()
            if not chunk_id:
                continue

            metadata = (
                chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
            )
            role = str(
                chunk.get("instruction_role")
                or metadata.get("instruction_role")
                or "explanation"
            ).strip().lower()
            covered_concepts = self._extract_chunk_concepts(chunk)
            content = str(chunk.get("content") or "")
            questionability_score = self._safe_float(
                chunk.get("questionability_score")
                or metadata.get("questionability_score")
                or 0.0
            )
            estimated_read_time = self._safe_float(
                chunk.get("estimated_read_time")
                or metadata.get("estimated_read_time")
                or 0.0
            )
            has_code = bool(
                metadata.get("has_code")
                or chunk.get("has_code")
                or self._looks_like_code(content)
            )
            has_example = role == "worked_example" or bool(
                re.search(
                    r"\b(example|vi du|for example)\b",
                    content,
                    flags=re.IGNORECASE,
                )
            )
            claim_scores = [
                self._score_claim(
                    claim=claim,
                    questionability_score=questionability_score,
                    target_concepts=target_concepts,
                    has_code=has_code,
                    has_example=has_example,
                )
                for claim in claims_by_chunk.get(chunk_id, [])
            ]
            target_match = self._chunk_matches_targets(
                chunk=chunk,
                target_concepts=target_concepts,
            )
            target_text = " ".join(
                item for item in [content, *covered_concepts] if str(item or "").strip()
            )
            target_semantic_score = self.question_nlp_service.semantic_similarity(
                target_text,
                target_concepts,
            )
            target_lexical_score = self.question_nlp_service.lexical_relevance(
                target_text,
                target_concepts,
            )
            keyword_overlap_terms = self.question_nlp_service.keyword_overlap_terms(
                target_text,
                target_concepts,
                top_k=4,
            )

            priority_score = self._role_priority(role)
            priority_score += questionability_score * 2.2
            priority_score += max(claim_scores or [0.0])
            if claim_scores:
                priority_score += (sum(claim_scores) / len(claim_scores)) * 0.35
            else:
                priority_score -= 0.35
            if covered_concepts:
                priority_score += 0.45
            if target_match:
                priority_score += 2.7
            priority_score += target_semantic_score * 1.65
            priority_score += target_lexical_score * 0.95
            if has_example:
                priority_score += 0.75
            if has_code:
                priority_score += 0.65
            if 0 < estimated_read_time <= 3:
                priority_score += 0.2
            elif estimated_read_time >= 8:
                priority_score -= 0.1

            profiles[chunk_id] = {
                "chunk_id": chunk_id,
                "instruction_role": role,
                "covered_concepts": covered_concepts,
                "questionability_score": questionability_score,
                "estimated_read_time": estimated_read_time,
                "has_code": has_code,
                "has_example": has_example,
                "target_match": target_match,
                "target_semantic_score": round(target_semantic_score, 4),
                "target_lexical_score": round(target_lexical_score, 4),
                "keyword_overlap_terms": list(keyword_overlap_terms),
                "claim_count": len(claim_scores),
                "priority_score": priority_score,
            }

        return profiles

    def _score_claim(
        self,
        *,
        claim: Dict[str, Any],
        questionability_score: float,
        target_concepts: Sequence[str],
        has_code: bool,
        has_example: bool,
    ) -> float:
        excerpt = str(claim.get("excerpt") or "").strip()
        answer_text = str(claim.get("answer_text") or "").strip()
        predicate = str(claim.get("predicate") or "").strip()
        role = str(claim.get("instruction_role") or "explanation").strip().lower()
        score = self._role_priority(role)
        claim_target_terms = [
            str(claim.get("focus") or ""),
            str(claim.get("statement") or ""),
            str(claim.get("answer_text") or ""),
            *[str(item) for item in claim.get("covered_concepts") or []],
        ]
        semantic_score = self.question_nlp_service.semantic_similarity(
            " ".join(item for item in claim_target_terms if item),
            target_concepts,
        )
        lexical_score = self.question_nlp_service.lexical_relevance(
            " ".join(item for item in claim_target_terms if item),
            target_concepts,
        )
        if answer_text:
            score += 1.0
        if predicate:
            score += 0.35
        if 8 <= len(excerpt.split()) <= 36:
            score += 0.45
        if claim.get("covered_concepts"):
            score += 0.3
        if self._claim_matches_targets(
            claim=claim,
            target_concepts=target_concepts,
        ):
            score += 2.4
        score += semantic_score * 1.35
        score += lexical_score * 0.85
        if has_example or role == "worked_example":
            score += 0.55
        if has_code and (role == "worked_example" or "`" in excerpt):
            score += 0.45
        score += max(0.0, questionability_score) * 0.9
        return score

    def _score_candidate(
        self,
        *,
        candidate: Dict[str, Any],
        chunk_profiles: Dict[str, Dict[str, Any]],
        target_concepts: Sequence[str],
    ) -> float:
        metadata = (
            candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        )
        score = self._candidate_chunk_score(
            candidate=candidate,
            chunk_profiles=chunk_profiles,
        )
        score += self._role_priority(self._candidate_role(candidate))
        score += self._style_priority(self._candidate_style(candidate))
        if self._candidate_target_match(
            candidate=candidate,
            target_concepts=target_concepts,
        ):
            score += 2.6
        score += self._candidate_target_semantic_score(
            candidate=candidate,
            target_concepts=target_concepts,
        ) * 1.25
        if metadata.get("target_concept_match"):
            score += 0.5
        score += float(len(metadata.get("matched_target_concepts") or [])) * 0.85
        if str(candidate.get("question_type") or "").strip() == "multiple_choice":
            distractors = candidate.get("distractors")
            if isinstance(distractors, list) and len(distractors) == 3:
                score += 0.4
        focus = self._candidate_focus(candidate)
        if len(focus.split()) >= 2:
            score += 0.2
        return score

    def _candidate_chunk_score(
        self,
        *,
        candidate: Dict[str, Any],
        chunk_profiles: Dict[str, Dict[str, Any]],
    ) -> float:
        chunk_ids = candidate.get("chunk_ids")
        if not isinstance(chunk_ids, list) or not chunk_ids:
            return 0.0
        chunk_id = str(chunk_ids[0] or "").strip()
        return float(chunk_profiles.get(chunk_id, {}).get("priority_score", 0.0) or 0.0)

    def _candidate_target_match(
        self,
        *,
        candidate: Dict[str, Any],
        target_concepts: Sequence[str],
    ) -> bool:
        return bool(
            self._resolve_candidate_target_matches(
                candidate=candidate,
                target_concepts=target_concepts,
            )
        )

    def _candidate_target_semantic_score(
        self,
        *,
        candidate: Dict[str, Any],
        target_concepts: Sequence[str],
    ) -> float:
        normalized_targets = self._normalize_target_concepts(target_concepts)
        if not normalized_targets:
            return 0.0

        metadata = (
            candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        )
        values: List[str] = [
            str(metadata.get("question_focus") or ""),
            str(metadata.get("source_excerpt") or ""),
        ]
        for concept in metadata.get("covered_concepts") or []:
            values.append(str(concept))
        combined = " ".join(value for value in values if value).strip()
        if not combined:
            return 0.0
        return self.question_nlp_service.semantic_similarity(combined, normalized_targets)

    def _resolve_candidate_target_matches(
        self,
        *,
        candidate: Dict[str, Any],
        target_concepts: Sequence[str],
    ) -> List[str]:
        normalized_targets = self._normalize_target_concepts(target_concepts)
        if not normalized_targets:
            return []

        metadata = (
            candidate.get("metadata") if isinstance(candidate.get("metadata"), dict) else {}
        )
        values: List[str] = [
            str(metadata.get("concept_focus") or ""),
            str(metadata.get("question_focus") or ""),
            str(metadata.get("source_excerpt") or ""),
            str(candidate.get("question") or ""),
            str(candidate.get("correct_answer") or ""),
        ]
        for concept in metadata.get("covered_concepts") or []:
            values.append(str(concept))

        matched: List[str] = []
        for target in normalized_targets:
            if any(self._candidate_matches_target_value(value, target) for value in values):
                matched.append(target)
        return matched

    def _candidate_matches_target_value(self, value: str, target: str) -> bool:
        normalized_value = self._normalize_text(value)
        normalized_target = self._normalize_text(target)
        if not normalized_value or not normalized_target:
            return False
        if normalized_value == normalized_target:
            return True
        if (
            normalized_target in normalized_value
            or normalized_value in normalized_target
        ) and (len(normalized_target) >= 4 or len(normalized_target.split()) >= 2):
            return True

        value_tokens = self._token_set(normalized_value)
        target_tokens = self._token_set(normalized_target)
        if not value_tokens or not target_tokens:
            return False
        if target_tokens.issubset(value_tokens):
            return True
        overlap = len(value_tokens.intersection(target_tokens)) / max(len(target_tokens), 1)
        return overlap >= 0.6

    def _claim_matches_targets(
        self,
        *,
        claim: Dict[str, Any],
        target_concepts: Sequence[str],
    ) -> bool:
        normalized_targets = self._normalize_target_concepts(target_concepts)
        if not normalized_targets:
            return False
        values: List[str] = [
            str(claim.get("focus") or ""),
            str(claim.get("statement") or ""),
            str(claim.get("answer_text") or ""),
            str(claim.get("predicate") or ""),
        ]
        for concept in claim.get("covered_concepts") or []:
            values.append(str(concept))
        combined = " ".join(
            self._normalize_text(value) for value in values if value
        ).strip()
        return bool(combined and any(target in combined for target in normalized_targets))

    def _chunk_matches_targets(
        self,
        *,
        chunk: Dict[str, Any],
        target_concepts: Sequence[str],
    ) -> bool:
        normalized_targets = self._normalize_target_concepts(target_concepts)
        if not normalized_targets:
            return False
        content = self._normalize_text(str(chunk.get("content") or ""))
        concept_text = " ".join(
            self._normalize_text(item) for item in self._extract_chunk_concepts(chunk)
        )
        combined = f"{content} {concept_text}".strip()
        if combined and any(target in combined for target in normalized_targets):
            return True
        semantic_score = self.question_nlp_service.semantic_similarity(
            combined,
            normalized_targets,
        )
        lexical_score = self.question_nlp_service.lexical_relevance(
            combined,
            normalized_targets,
        )
        return semantic_score >= 0.3 or lexical_score >= 0.2

    def _extract_chunk_concepts(self, chunk: Dict[str, Any]) -> List[str]:
        metadata = (
            chunk.get("metadata") if isinstance(chunk.get("metadata"), dict) else {}
        )
        concepts: List[str] = []
        seen: set[str] = set()
        for source in (chunk.get("covered_concepts"), metadata.get("covered_concepts")):
            values = (
                source
                if isinstance(source, list)
                else [source] if isinstance(source, str) else []
            )
            for value in values:
                cleaned = str(value or "").strip()
                normalized = self._normalize_text(cleaned)
                if not cleaned or not normalized or normalized in seen:
                    continue
                seen.add(normalized)
                concepts.append(cleaned)
        return concepts

    @staticmethod
    def _attempt_role_bias(attempt: int) -> Dict[str, float]:
        plans = (
            {
                "worked_example": 0.75,
                "definition": 0.55,
                "explanation": 0.45,
                "summary": 0.35,
                "introduction": 0.2,
            },
            {
                "definition": 0.8,
                "explanation": 0.65,
                "summary": 0.45,
                "worked_example": 0.35,
                "introduction": 0.2,
            },
            {
                "explanation": 0.7,
                "summary": 0.6,
                "worked_example": 0.55,
                "definition": 0.45,
                "introduction": 0.2,
            },
        )
        return plans[min(max(attempt, 0), len(plans) - 1)]

    @staticmethod
    def _style_priority(style: str) -> float:
        return {
            "focus_from_description_mcq": 0.8,
            "describe_focus_mcq": 0.65,
            "complete_concept_mcq": 0.6,
            "fill_blank_mcq": 0.55,
            "worked_example_short": 0.55,
            "complete_statement_short": 0.5,
            "describe_focus_short": 0.45,
            "true_false_statement": 0.25,
        }.get(style, 0.0)

    @staticmethod
    def _role_priority(role: str) -> float:
        return {
            "worked_example": 0.95,
            "definition": 0.85,
            "explanation": 0.7,
            "summary": 0.55,
            "introduction": 0.3,
        }.get(str(role or "").strip().lower(), 0.2)

    def _normalize_target_concepts(
        self, values: Sequence[str] | None
    ) -> List[str]:
        normalized: List[str] = []
        seen: set[str] = set()
        for value in values or []:
            token = self._normalize_text(value)
            if token and token not in seen:
                seen.add(token)
                normalized.append(token)
        return normalized

    @staticmethod
    def _token_set(value: str) -> set[str]:
        tokens: set[str] = set()
        for token in re.findall(r"\b[a-z0-9_]{3,}\b", str(value or "")):
            singular = concept_normalization_service._singularize(token)
            if singular:
                tokens.add(singular)
        return tokens

    def _normalize_text(self, value: Any) -> str:
        return self.template_service._normalize_text(str(value or ""))

    @staticmethod
    def _safe_float(value: Any) -> float:
        try:
            return float(value)
        except Exception:
            return 0.0

    @staticmethod
    def _looks_like_code(content: str) -> bool:
        text = str(content or "")
        if "```" in text or "`" in text:
            return True
        return bool(
            re.search(
                r"\b(def|class|return|import|for|while|if|elif|else|print)\b|[{}();=]",
                text,
            )
        )


question_fallback_service = QuestionFallbackService()
