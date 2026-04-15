"""Batch job to backfill missing path_id fields for adaptive legacy data."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from backend.app.database.mongo import get_db


class BackfillAdaptivePathScopeJob:
    """Populate path-scoped adaptive state/attempt records when the path is unambiguous."""

    ATTEMPTS_COLLECTION = "lesson_quiz_attempts"
    LEARNING_STATE_COLLECTION = "user_learning_state"
    ALL_COLLECTIONS = "all"

    def __init__(self) -> None:
        self.db = get_db()
        self.learning_paths = self.db["learning_paths"]
        self.attempts = self.db["lesson_quiz_attempts"]
        self.learning_state = self.db["user_learning_state"]
        self._path_candidates_cache: dict[Tuple[str, str], List[str]] = {}

    def _base_query(
        self,
        *,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        query: Dict[str, Any] = {
            "$or": [{"path_id": None}, {"path_id": {"$exists": False}}],
        }
        if user_id:
            query["user_id"] = str(user_id)
        return query

    def _extract_lesson_ids(self, path_document: Dict[str, Any]) -> set[str]:
        lesson_ids = {
            str(lesson_id)
            for lesson_id in (path_document.get("lesson_progress") or {}).keys()
            if str(lesson_id).strip()
        }
        chapters = path_document.get("chapters") or path_document.get("curriculum") or []
        for chapter in chapters:
            for lesson in chapter.get("lessons", []) or []:
                lesson_id = str(lesson.get("lesson_id") or "").strip()
                if lesson_id:
                    lesson_ids.add(lesson_id)
        return lesson_ids

    def _path_candidates_from_learning_paths(self, *, user_id: str, lesson_id: str) -> List[str]:
        cache_key = (str(user_id), str(lesson_id))
        if cache_key in self._path_candidates_cache:
            return list(self._path_candidates_cache[cache_key])

        candidates: List[str] = []
        cursor = self.learning_paths.find({"user_id": str(user_id)}, {"path_id": 1, "lesson_progress": 1, "chapters": 1, "curriculum": 1})
        for path_document in cursor:
            path_id = str(path_document.get("path_id") or "").strip()
            if not path_id:
                continue
            if str(lesson_id) in self._extract_lesson_ids(path_document):
                candidates.append(path_id)
        deduped = sorted({item for item in candidates if item})
        self._path_candidates_cache[cache_key] = deduped
        return list(deduped)

    @staticmethod
    def _distinct_path_ids(collection, query: Dict[str, Any]) -> List[str]:
        return sorted(
            {
                str(item).strip()
                for item in collection.distinct("path_id", query)
                if str(item).strip()
            }
        )

    def _resolve_path_id(
        self,
        *,
        user_id: str,
        lesson_id: str,
        subject_id: Optional[str] = None,
    ) -> tuple[Optional[str], str]:
        attempt_candidates = self._distinct_path_ids(
            self.attempts,
            {
                "user_id": str(user_id),
                "lesson_id": str(lesson_id),
                "path_id": {"$exists": True, "$ne": None},
            },
        )
        if len(attempt_candidates) == 1:
            return attempt_candidates[0], "attempt_match"
        if len(attempt_candidates) > 1:
            return None, "ambiguous_attempt_match"

        state_query: Dict[str, Any] = {
            "user_id": str(user_id),
            "lesson_id": str(lesson_id),
            "path_id": {"$exists": True, "$ne": None},
        }
        if subject_id:
            state_query["subject_id"] = str(subject_id)
        state_candidates = self._distinct_path_ids(self.learning_state, state_query)
        if len(state_candidates) == 1:
            return state_candidates[0], "state_match"
        if len(state_candidates) > 1:
            return None, "ambiguous_state_match"

        path_candidates = self._path_candidates_from_learning_paths(
            user_id=str(user_id),
            lesson_id=str(lesson_id),
        )
        if len(path_candidates) == 1:
            return path_candidates[0], "learning_path_match"
        if len(path_candidates) > 1:
            return None, "ambiguous_learning_path_match"
        return None, "no_matching_path"

    def _backfill_attempts(
        self,
        *,
        user_id: Optional[str],
        dry_run: bool,
        limit: Optional[int],
    ) -> Dict[str, Any]:
        processed = 0
        updated = 0
        skipped = 0
        reasons: Dict[str, int] = {}
        samples: List[Dict[str, Any]] = []

        cursor = self.attempts.find(self._base_query(user_id=user_id)).sort("submitted_at", -1)
        if limit and limit > 0:
            cursor = cursor.limit(int(limit))

        for document in cursor:
            processed += 1
            resolved_path_id, reason = self._resolve_path_id(
                user_id=str(document.get("user_id") or ""),
                lesson_id=str(document.get("lesson_id") or ""),
            )
            reasons[reason] = reasons.get(reason, 0) + 1
            if not resolved_path_id:
                skipped += 1
            else:
                updated += 1
                if not dry_run:
                    self.attempts.update_one(
                        {"_id": document["_id"]},
                        {"$set": {"path_id": resolved_path_id}},
                    )
            if len(samples) < 5:
                samples.append(
                    {
                        "attempt_id": str(document.get("attempt_id") or ""),
                        "user_id": str(document.get("user_id") or ""),
                        "lesson_id": str(document.get("lesson_id") or ""),
                        "resolved_path_id": resolved_path_id,
                        "reason": reason,
                    }
                )

        return {
            "collection": "lesson_quiz_attempts",
            "processed": processed,
            "updated": 0 if dry_run else updated,
            "skipped": skipped,
            "dry_run": dry_run,
            "reasons": reasons,
            "items": samples,
        }

    def _backfill_learning_state(
        self,
        *,
        user_id: Optional[str],
        dry_run: bool,
        limit: Optional[int],
    ) -> Dict[str, Any]:
        processed = 0
        updated = 0
        skipped = 0
        reasons: Dict[str, int] = {}
        samples: List[Dict[str, Any]] = []

        cursor = self.learning_state.find(self._base_query(user_id=user_id)).sort("updated_at", -1)
        if limit and limit > 0:
            cursor = cursor.limit(int(limit))

        for document in cursor:
            processed += 1
            resolved_path_id, reason = self._resolve_path_id(
                user_id=str(document.get("user_id") or ""),
                lesson_id=str(document.get("lesson_id") or ""),
                subject_id=str(document.get("subject_id") or "").strip() or None,
            )
            reasons[reason] = reasons.get(reason, 0) + 1
            if not resolved_path_id:
                skipped += 1
            else:
                updated += 1
                if not dry_run:
                    self.learning_state.update_one(
                        {"_id": document["_id"]},
                        {"$set": {"path_id": resolved_path_id}},
                    )
            if len(samples) < 5:
                samples.append(
                    {
                        "user_id": str(document.get("user_id") or ""),
                        "lesson_id": str(document.get("lesson_id") or ""),
                        "subject_id": str(document.get("subject_id") or ""),
                        "resolved_path_id": resolved_path_id,
                        "reason": reason,
                    }
                )

        return {
            "collection": "user_learning_state",
            "processed": processed,
            "updated": 0 if dry_run else updated,
            "skipped": skipped,
            "dry_run": dry_run,
            "reasons": reasons,
            "items": samples,
        }

    def run(
        self,
        *,
        user_id: Optional[str] = None,
        dry_run: bool = False,
        limit: Optional[int] = None,
        collection: Optional[str] = None,
    ) -> Dict[str, Any]:
        selected = self._normalize_collection(collection)
        results: List[Dict[str, Any]] = []
        if selected in {self.ALL_COLLECTIONS, self.ATTEMPTS_COLLECTION}:
            results.append(
                self._backfill_attempts(
                    user_id=user_id,
                    dry_run=dry_run,
                    limit=limit,
                )
            )
        if selected in {self.ALL_COLLECTIONS, self.LEARNING_STATE_COLLECTION}:
            results.append(
                self._backfill_learning_state(
                    user_id=user_id,
                    dry_run=dry_run,
                    limit=limit,
                )
            )
        return {
            "job": "adaptive_path_scope",
            "dry_run": dry_run,
            "user_id": str(user_id) if user_id else None,
            "collection": selected,
            "summary": {
                "processed": sum(int(item.get("processed") or 0) for item in results),
                "updated": sum(int(item.get("updated") or 0) for item in results),
                "skipped": sum(int(item.get("skipped") or 0) for item in results),
            },
            "results": results,
        }

    def _audit_attempts(
        self,
        *,
        user_id: Optional[str],
        sample_limit: int,
    ) -> Dict[str, Any]:
        pending = 0
        resolvable = 0
        ambiguous = 0
        unmatched = 0
        reasons: Dict[str, int] = {}
        samples: List[Dict[str, Any]] = []

        cursor = self.attempts.find(self._base_query(user_id=user_id)).sort("submitted_at", -1)
        for document in cursor:
            pending += 1
            resolved_path_id, reason = self._resolve_path_id(
                user_id=str(document.get("user_id") or ""),
                lesson_id=str(document.get("lesson_id") or ""),
            )
            reasons[reason] = reasons.get(reason, 0) + 1
            if resolved_path_id:
                resolvable += 1
            elif reason.startswith("ambiguous_"):
                ambiguous += 1
            else:
                unmatched += 1

            if len(samples) < sample_limit:
                samples.append(
                    {
                        "attempt_id": str(document.get("attempt_id") or ""),
                        "user_id": str(document.get("user_id") or ""),
                        "lesson_id": str(document.get("lesson_id") or ""),
                        "resolved_path_id": resolved_path_id,
                        "reason": reason,
                    }
                )

        return {
            "collection": "lesson_quiz_attempts",
            "pending": pending,
            "resolvable": resolvable,
            "ambiguous": ambiguous,
            "unmatched": unmatched,
            "reasons": reasons,
            "items": samples,
        }

    def _audit_learning_state(
        self,
        *,
        user_id: Optional[str],
        sample_limit: int,
    ) -> Dict[str, Any]:
        pending = 0
        resolvable = 0
        ambiguous = 0
        unmatched = 0
        reasons: Dict[str, int] = {}
        samples: List[Dict[str, Any]] = []

        cursor = self.learning_state.find(self._base_query(user_id=user_id)).sort("updated_at", -1)
        for document in cursor:
            pending += 1
            resolved_path_id, reason = self._resolve_path_id(
                user_id=str(document.get("user_id") or ""),
                lesson_id=str(document.get("lesson_id") or ""),
                subject_id=str(document.get("subject_id") or "").strip() or None,
            )
            reasons[reason] = reasons.get(reason, 0) + 1
            if resolved_path_id:
                resolvable += 1
            elif reason.startswith("ambiguous_"):
                ambiguous += 1
            else:
                unmatched += 1

            if len(samples) < sample_limit:
                samples.append(
                    {
                        "user_id": str(document.get("user_id") or ""),
                        "lesson_id": str(document.get("lesson_id") or ""),
                        "subject_id": str(document.get("subject_id") or ""),
                        "resolved_path_id": resolved_path_id,
                        "reason": reason,
                    }
                )

        return {
            "collection": "user_learning_state",
            "pending": pending,
            "resolvable": resolvable,
            "ambiguous": ambiguous,
            "unmatched": unmatched,
            "reasons": reasons,
            "items": samples,
        }

    def audit(
        self,
        *,
        user_id: Optional[str] = None,
        sample_limit: int = 5,
        collection: Optional[str] = None,
    ) -> Dict[str, Any]:
        safe_sample_limit = max(1, min(int(sample_limit), 20))
        selected = self._normalize_collection(collection)
        results: List[Dict[str, Any]] = []
        if selected in {self.ALL_COLLECTIONS, self.ATTEMPTS_COLLECTION}:
            results.append(
                self._audit_attempts(user_id=user_id, sample_limit=safe_sample_limit)
            )
        if selected in {self.ALL_COLLECTIONS, self.LEARNING_STATE_COLLECTION}:
            results.append(
                self._audit_learning_state(
                    user_id=user_id,
                    sample_limit=safe_sample_limit,
                )
            )
        return {
            "job": "adaptive_path_scope_audit",
            "user_id": str(user_id) if user_id else None,
            "collection": selected,
            "summary": {
                "pending": sum(int(item.get("pending") or 0) for item in results),
                "resolvable": sum(int(item.get("resolvable") or 0) for item in results),
                "ambiguous": sum(int(item.get("ambiguous") or 0) for item in results),
                "unmatched": sum(int(item.get("unmatched") or 0) for item in results),
            },
            "results": results,
        }

    def _normalize_collection(self, collection: Optional[str]) -> str:
        normalized = str(collection or self.ALL_COLLECTIONS).strip().lower()
        if normalized not in {
            self.ALL_COLLECTIONS,
            self.ATTEMPTS_COLLECTION,
            self.LEARNING_STATE_COLLECTION,
        }:
            raise ValueError(
                "collection must be one of: all, lesson_quiz_attempts, user_learning_state"
            )
        return normalized


backfill_adaptive_path_scope_job = BackfillAdaptivePathScopeJob()
