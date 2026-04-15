"""Learner profile and diagnostic orchestration."""

from __future__ import annotations

from datetime import date, datetime, timezone
import re
import uuid
from typing import Any, Dict, List, Optional

from bson import ObjectId

from backend.app.database.mongo import get_db
from backend.app.services.learning_path_prompt_builder import get_subject_label


class LearnerProfileService:
    """Own learner profile storage outside the users collection."""

    _LEVELS = {"beginner", "intermediate", "advanced"}
    _RESOURCE_TYPES = {"video", "pdf", "practice", "mixed"}
    _PACE_VALUES = {"light", "steady", "intensive"}
    _TIME_UNITS = {"daily", "weekly"}
    _SUBJECT_HINTS: Dict[str, tuple[str, ...]] = {
        "python": ("python", "fastapi", "django", "flask", "numpy", "pandas"),
        "cpp": ("c++", "cpp", "stl"),
        "csharp": ("c#", "csharp", ".net", "asp.net"),
        "java": ("java", "spring", "jvm"),
        "web": (
            "web",
            "frontend",
            "html",
            "css",
            "javascript",
            "typescript",
            "react",
        ),
    }
    _FALLBACK_DIAGNOSTIC_QUESTIONS: Dict[str, List[Dict[str, Any]]] = {
        "python": [
            {"concept_key": "syntax_basics", "title": "Python syntax basics", "difficulty": 1},
            {"concept_key": "data_structures", "title": "Lists, dicts, and sets", "difficulty": 2},
            {"concept_key": "control_flow", "title": "Conditionals and loops", "difficulty": 2},
            {"concept_key": "functions", "title": "Functions and modules", "difficulty": 3},
            {"concept_key": "practical_scripts", "title": "Building practical scripts", "difficulty": 4},
        ],
        "cpp": [
            {"concept_key": "cpp_syntax", "title": "C++ syntax and compilation", "difficulty": 1},
            {"concept_key": "memory_basics", "title": "Memory and pointers", "difficulty": 3},
            {"concept_key": "oop_cpp", "title": "Classes and OOP in C++", "difficulty": 3},
            {"concept_key": "stl", "title": "STL containers and algorithms", "difficulty": 4},
            {"concept_key": "problem_solving", "title": "Problem solving with C++", "difficulty": 4},
        ],
        "csharp": [
            {"concept_key": "dotnet_basics", "title": ".NET runtime basics", "difficulty": 1},
            {"concept_key": "csharp_syntax", "title": "C# syntax and types", "difficulty": 2},
            {"concept_key": "oop_csharp", "title": "Classes and interfaces", "difficulty": 3},
            {"concept_key": "linq", "title": "Collections and LINQ", "difficulty": 4},
            {"concept_key": "aspnet", "title": "Applied ASP.NET patterns", "difficulty": 4},
        ],
        "java": [
            {"concept_key": "jvm_basics", "title": "Java and the JVM", "difficulty": 1},
            {"concept_key": "java_syntax", "title": "Java syntax and types", "difficulty": 2},
            {"concept_key": "oop_java", "title": "Classes, interfaces, and packages", "difficulty": 3},
            {"concept_key": "collections", "title": "Collections framework", "difficulty": 3},
            {"concept_key": "spring_basics", "title": "Applied Java backend basics", "difficulty": 4},
        ],
        "web": [
            {"concept_key": "html_css", "title": "HTML and CSS foundations", "difficulty": 1},
            {"concept_key": "javascript_basics", "title": "JavaScript basics", "difficulty": 2},
            {"concept_key": "dom_events", "title": "DOM and browser events", "difficulty": 2},
            {"concept_key": "api_integration", "title": "Calling APIs from the frontend", "difficulty": 3},
            {"concept_key": "component_thinking", "title": "Component-based UI thinking", "difficulty": 4},
        ],
    }

    def __init__(self) -> None:
        self.db = get_db()
        self.collection = self.db["learner_profiles"]
        self.diagnostic_sessions = self.db["diagnostic_sessions"]
        self._ensure_indexes()

    @staticmethod
    def _utcnow() -> datetime:
        return datetime.now(timezone.utc)

    def _ensure_indexes(self) -> None:
        try:
            self.collection.create_index("user_id", unique=True)
            self.collection.create_index("updated_at")
            self.diagnostic_sessions.create_index(
                [("session_id", 1), ("user_id", 1)], unique=True
            )
            self.diagnostic_sessions.create_index("created_at")
        except Exception:
            # Index creation should never break request flow.
            pass

    @classmethod
    def _normalize_level(cls, value: Any, default: str = "beginner") -> str:
        normalized = str(value or "").strip().lower()
        return normalized if normalized in cls._LEVELS else default

    @classmethod
    def _normalize_resource_type(cls, value: Any) -> str:
        normalized = str(value or "").strip().lower()
        return normalized if normalized in cls._RESOURCE_TYPES else "mixed"

    @classmethod
    def _normalize_learning_pace(cls, value: Any) -> str:
        normalized = str(value or "").strip().lower()
        return normalized if normalized in cls._PACE_VALUES else "steady"

    @classmethod
    def _slugify(cls, value: Any) -> str:
        lowered = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower())
        return lowered.strip("_")

    @classmethod
    def _normalize_time_budget(cls, value: Any) -> Dict[str, Any]:
        raw = value if isinstance(value, dict) else {}
        unit = str(raw.get("unit") or "weekly").strip().lower()
        numeric_value = raw.get("value", 300)
        try:
            budget_value = int(float(numeric_value))
        except Exception:
            budget_value = 300
        if unit not in cls._TIME_UNITS:
            unit = "weekly"
        budget_value = max(30, min(budget_value, 10080))
        return {"value": budget_value, "unit": unit}

    @classmethod
    def _normalize_string(cls, value: Any, *, max_length: int = 500) -> Optional[str]:
        text = str(value or "").strip()
        if not text:
            return None
        return text[:max_length]

    @classmethod
    def _normalize_subject_level_map(cls, value: Any) -> Dict[str, str]:
        if not isinstance(value, dict):
            return {}
        normalized: Dict[str, str] = {}
        for subject_id, level in value.items():
            subject_key = cls._slugify(subject_id)
            if not subject_key:
                continue
            normalized[subject_key] = cls._normalize_level(level)
        return normalized

    @classmethod
    def _normalize_concept_scores(cls, value: Any) -> Dict[str, Dict[str, float]]:
        if not isinstance(value, dict):
            return {}
        normalized: Dict[str, Dict[str, float]] = {}
        for subject_id, scores in value.items():
            subject_key = cls._slugify(subject_id)
            if not subject_key or not isinstance(scores, dict):
                continue
            concept_scores: Dict[str, float] = {}
            for concept_key, score in scores.items():
                try:
                    concept_scores[cls._slugify(concept_key)] = max(
                        0.0, min(1.0, float(score))
                    )
                except Exception:
                    continue
            if concept_scores:
                normalized[subject_key] = concept_scores
        return normalized

    @classmethod
    def _infer_goal(cls, profile: Dict[str, Any]) -> Optional[str]:
        explicit_goal = cls._normalize_string(profile.get("learning_goal"))
        if explicit_goal:
            return explicit_goal
        outcome = cls._normalize_string(profile.get("target_outcome"))
        role = cls._normalize_string(profile.get("target_role"), max_length=200)
        if outcome and role:
            return f"{outcome} as a {role}"
        if outcome:
            return outcome
        if role:
            return f"Become job-ready for {role}"
        return None

    @staticmethod
    def _recommended_level_from_score(score: float) -> str:
        if score >= 0.7:
            return "advanced"
        if score >= 0.35:
            return "intermediate"
        return "beginner"

    @staticmethod
    def _average_score(scores: Dict[str, float]) -> float:
        if not scores:
            return 0.0
        return round(sum(scores.values()) / len(scores), 4)

    def _default_profile(
        self, user_id: str, *, user_doc: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        legacy_level = self._normalize_level((user_doc or {}).get("level"))
        legacy_goal = self._normalize_string((user_doc or {}).get("learning_goal"))
        now = self._utcnow()
        return {
            "user_id": user_id,
            "level": legacy_level,
            "learning_goal": legacy_goal,
            "target_role": None,
            "target_outcome": None,
            "time_budget": {"value": 300, "unit": "weekly"},
            "preferred_resource_type": "mixed",
            "learning_pace": "steady",
            "desired_deadline": None,
            "prior_knowledge_by_subject": {},
            "diagnostic_scores_by_subject": {},
            "diagnostic_summary_by_subject": {},
            "created_at": now,
            "updated_at": now,
        }

    def _load_user_doc(self, user_id: str) -> Dict[str, Any]:
        if not ObjectId.is_valid(user_id):
            return {}
        return self.db.users.find_one({"_id": ObjectId(user_id)}) or {}

    def _merge_profile(
        self, user_id: str, stored: Optional[Dict[str, Any]], user_doc: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        profile = self._default_profile(user_id, user_doc=user_doc)
        profile.update(stored or {})
        profile["level"] = self._normalize_level(
            profile.get("level") or (user_doc or {}).get("level")
        )
        profile["learning_goal"] = self._normalize_string(
            profile.get("learning_goal") or (user_doc or {}).get("learning_goal")
        )
        profile["target_role"] = self._normalize_string(
            profile.get("target_role"), max_length=200
        )
        profile["target_outcome"] = self._normalize_string(profile.get("target_outcome"))
        profile["time_budget"] = self._normalize_time_budget(profile.get("time_budget"))
        profile["preferred_resource_type"] = self._normalize_resource_type(
            profile.get("preferred_resource_type")
        )
        profile["learning_pace"] = self._normalize_learning_pace(
            profile.get("learning_pace")
        )
        profile["desired_deadline"] = profile.get("desired_deadline")
        profile["prior_knowledge_by_subject"] = self._normalize_subject_level_map(
            profile.get("prior_knowledge_by_subject")
        )
        profile["diagnostic_scores_by_subject"] = self._normalize_concept_scores(
            profile.get("diagnostic_scores_by_subject")
        )
        profile["diagnostic_summary_by_subject"] = dict(
            profile.get("diagnostic_summary_by_subject") or {}
        )
        profile["learning_goal"] = profile["learning_goal"] or self._infer_goal(profile)
        profile["onboarding_status"] = {
            "profile_completed": self._is_profile_completed(profile),
            "diagnostic_completed": self._is_diagnostic_completed(profile),
        }
        return profile

    @staticmethod
    def _is_profile_completed(profile: Dict[str, Any]) -> bool:
        return bool(
            profile.get("learning_goal")
            or profile.get("target_outcome")
            or profile.get("target_role")
        ) and bool(profile.get("time_budget", {}).get("value"))

    @staticmethod
    def _is_diagnostic_completed(profile: Dict[str, Any]) -> bool:
        return bool(profile.get("diagnostic_scores_by_subject"))

    def initialize_profile(self, user_id: str) -> Dict[str, Any]:
        profile = self.get_profile(user_id)
        stored = self.collection.find_one({"user_id": user_id})
        if stored:
            return profile

        persisted = dict(profile)
        persisted.pop("onboarding_status", None)
        self.collection.insert_one(persisted)
        return self.get_profile(user_id)

    def get_profile(self, user_id: str) -> Dict[str, Any]:
        stored = self.collection.find_one({"user_id": user_id}) or {}
        user_doc = self._load_user_doc(user_id)
        return self._merge_profile(user_id, stored, user_doc)

    def update_profile(self, user_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        current = self.get_profile(user_id)
        update_doc: Dict[str, Any] = {}

        if "level" in payload and payload.get("level") is not None:
            update_doc["level"] = self._normalize_level(payload.get("level"))
        if "learning_goal" in payload:
            update_doc["learning_goal"] = self._normalize_string(payload.get("learning_goal"))
        if "target_role" in payload:
            update_doc["target_role"] = self._normalize_string(
                payload.get("target_role"), max_length=200
            )
        if "target_outcome" in payload:
            update_doc["target_outcome"] = self._normalize_string(
                payload.get("target_outcome")
            )
        if "time_budget" in payload and payload.get("time_budget") is not None:
            update_doc["time_budget"] = self._normalize_time_budget(
                payload.get("time_budget")
            )
        if "preferred_resource_type" in payload and payload.get("preferred_resource_type"):
            update_doc["preferred_resource_type"] = self._normalize_resource_type(
                payload.get("preferred_resource_type")
            )
        if "learning_pace" in payload and payload.get("learning_pace"):
            update_doc["learning_pace"] = self._normalize_learning_pace(
                payload.get("learning_pace")
            )
        if "desired_deadline" in payload:
            deadline = payload.get("desired_deadline")
            update_doc["desired_deadline"] = deadline.isoformat() if isinstance(deadline, date) else deadline
        if "prior_knowledge_by_subject" in payload and payload.get(
            "prior_knowledge_by_subject"
        ) is not None:
            current_map = dict(current.get("prior_knowledge_by_subject") or {})
            current_map.update(
                self._normalize_subject_level_map(payload.get("prior_knowledge_by_subject"))
            )
            update_doc["prior_knowledge_by_subject"] = current_map
        if "diagnostic_scores_by_subject" in payload and payload.get(
            "diagnostic_scores_by_subject"
        ) is not None:
            current_scores = dict(current.get("diagnostic_scores_by_subject") or {})
            current_scores.update(
                self._normalize_concept_scores(payload.get("diagnostic_scores_by_subject"))
            )
            update_doc["diagnostic_scores_by_subject"] = current_scores
        if "diagnostic_summary_by_subject" in payload and payload.get(
            "diagnostic_summary_by_subject"
        ) is not None:
            current_summaries = dict(current.get("diagnostic_summary_by_subject") or {})
            current_summaries.update(dict(payload.get("diagnostic_summary_by_subject") or {}))
            update_doc["diagnostic_summary_by_subject"] = current_summaries

        if not update_doc:
            return current

        update_doc["updated_at"] = self._utcnow()
        self.collection.update_one(
            {"user_id": user_id},
            {
                "$set": update_doc,
                "$setOnInsert": {
                    "user_id": user_id,
                    "created_at": current.get("created_at") or self._utcnow(),
                },
            },
            upsert=True,
        )

        legacy_user_update: Dict[str, Any] = {}
        if "level" in update_doc:
            legacy_user_update["level"] = update_doc["level"]
        if "learning_goal" in update_doc:
            legacy_user_update["learning_goal"] = update_doc["learning_goal"]
        if legacy_user_update and ObjectId.is_valid(user_id):
            legacy_user_update["updated_at"] = self._utcnow()
            self.db.users.update_one({"_id": ObjectId(user_id)}, {"$set": legacy_user_update})

        return self.get_profile(user_id)

    def resolve_subject_id(
        self, *, subject_id: Optional[str], goal: Optional[str], profile: Dict[str, Any]
    ) -> str:
        normalized = self._slugify(subject_id)
        if get_subject_label(normalized):
            return normalized
        goal_text = " ".join(
            [
                str(goal or ""),
                str(profile.get("learning_goal") or ""),
                str(profile.get("target_role") or ""),
                str(profile.get("target_outcome") or ""),
            ]
        ).lower()
        for candidate, hints in self._SUBJECT_HINTS.items():
            if any(hint in goal_text for hint in hints):
                return candidate
        prior_knowledge_map = profile.get("prior_knowledge_by_subject") or {}
        if prior_knowledge_map:
            first_subject = next(iter(prior_knowledge_map.keys()), "")
            if get_subject_label(first_subject):
                return first_subject
        diagnostic_map = profile.get("diagnostic_summary_by_subject") or {}
        first_diagnostic_subject = next(iter(diagnostic_map.keys()), "")
        if get_subject_label(first_diagnostic_subject):
            return first_diagnostic_subject
        return "python"

    def personalization_context(
        self,
        *,
        user_id: Optional[str],
        subject_id: Optional[str] = None,
        goal: Optional[str] = None,
        level: Optional[str] = None,
    ) -> Dict[str, Any]:
        normalized_user_id = str(user_id or "").strip()
        if not normalized_user_id:
            return {
                "profile": {},
                "subject_id": subject_id or "python",
                "goal": goal or "",
                "level": self._normalize_level(level),
                "time_budget_minutes": 300,
                "preferred_resource_type": "mixed",
                "learning_pace": "steady",
                "diagnostic_scores": {},
                "diagnostic_summary": {},
            }

        profile = self.get_profile(normalized_user_id)
        resolved_subject = self.resolve_subject_id(
            subject_id=subject_id,
            goal=goal,
            profile=profile,
        )
        subject_prior_knowledge = (
            profile.get("prior_knowledge_by_subject") or {}
        ).get(resolved_subject)
        diagnostic_summary = (
            profile.get("diagnostic_summary_by_subject") or {}
        ).get(resolved_subject, {})
        diagnostic_scores = (
            profile.get("diagnostic_scores_by_subject") or {}
        ).get(resolved_subject, {})
        resolved_goal = (
            self._normalize_string(goal)
            or profile.get("learning_goal")
            or self._infer_goal(profile)
            or f"Learn {get_subject_label(resolved_subject) or 'this subject'}"
        )
        resolved_level = self._normalize_level(
            level
            or subject_prior_knowledge
            or diagnostic_summary.get("recommended_level")
            or profile.get("level")
        )

        time_budget = self._normalize_time_budget(profile.get("time_budget"))
        time_budget_minutes = int(time_budget["value"])
        if time_budget["unit"] == "daily":
            time_budget_minutes *= 5

        return {
            "profile": profile,
            "subject_id": resolved_subject,
            "goal": resolved_goal,
            "level": resolved_level,
            "time_budget_minutes": time_budget_minutes,
            "time_budget": time_budget,
            "preferred_resource_type": profile.get("preferred_resource_type") or "mixed",
            "learning_pace": profile.get("learning_pace") or "steady",
            "target_role": profile.get("target_role"),
            "target_outcome": profile.get("target_outcome"),
            "desired_deadline": profile.get("desired_deadline"),
            "prior_knowledge_level": self._normalize_level(
                subject_prior_knowledge, default=resolved_level
            ),
            "diagnostic_scores": diagnostic_scores,
            "diagnostic_summary": diagnostic_summary,
        }

    def _concepts_for_subject(self, subject_id: str, *, limit: int = 5) -> List[Dict[str, Any]]:
        subject_label = get_subject_label(subject_id) or subject_id
        query = {
            "$or": [
                {"topic": {"$regex": f"^{re.escape(subject_id)}$", "$options": "i"}},
                {"topic": {"$regex": re.escape(subject_label), "$options": "i"}},
            ]
        }
        docs = list(
            self.db.concepts.find(
                query,
                {"concept_name": 1, "difficulty": 1, "topic": 1},
            )
            .sort("difficulty", 1)
            .limit(limit)
        )
        if docs:
            return docs
        return self._FALLBACK_DIAGNOSTIC_QUESTIONS.get(
            subject_id, self._FALLBACK_DIAGNOSTIC_QUESTIONS["python"]
        )[:limit]

    def start_diagnostic(
        self,
        *,
        user_id: str,
        subject_id: Optional[str] = None,
        goal: Optional[str] = None,
        max_questions: int = 5,
    ) -> Dict[str, Any]:
        context = self.personalization_context(
            user_id=user_id,
            subject_id=subject_id,
            goal=goal,
        )
        resolved_subject = context["subject_id"]
        concept_docs = self._concepts_for_subject(resolved_subject, limit=max_questions)
        questions: List[Dict[str, Any]] = []
        for index, concept in enumerate(concept_docs, start=1):
            concept_title = str(
                concept.get("concept_name")
                or concept.get("title")
                or concept.get("concept_key")
                or f"Concept {index}"
            ).strip()
            concept_key = self._slugify(concept.get("concept_key") or concept_title)
            if not concept_key:
                concept_key = f"concept_{index}"
            questions.append(
                {
                    "concept_key": concept_key,
                    "title": concept_title,
                    "prompt": f"Bạn tự tin đến đâu với chủ đề '{concept_title}'?",
                    "difficulty": int(concept.get("difficulty") or index),
                    "subject_id": resolved_subject,
                }
            )

        session_id = uuid.uuid4().hex
        self.diagnostic_sessions.insert_one(
            {
                "session_id": session_id,
                "user_id": user_id,
                "subject_id": resolved_subject,
                "questions": questions,
                "created_at": self._utcnow(),
            }
        )

        return {
            "session_id": session_id,
            "subject_id": resolved_subject,
            "questions": questions,
            "prior_knowledge_level": context.get("prior_knowledge_level"),
            "message": "Đã tạo bài chẩn đoán đầu vào cho hồ sơ học tập hiện tại.",
        }

    def submit_diagnostic(
        self,
        *,
        user_id: str,
        session_id: str,
        answers: List[Dict[str, Any]],
        subject_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        session = self.diagnostic_sessions.find_one(
            {"session_id": session_id, "user_id": user_id}
        )
        if not session:
            raise ValueError("Diagnostic session not found.")

        resolved_subject = self._slugify(subject_id or session.get("subject_id")) or "python"
        valid_keys = {
            self._slugify(question.get("concept_key"))
            for question in (session.get("questions") or [])
            if question.get("concept_key")
        }

        concept_scores: Dict[str, float] = {}
        for item in answers:
            concept_key = self._slugify(item.get("concept_key"))
            if not concept_key or (valid_keys and concept_key not in valid_keys):
                continue
            raw_score = item.get("score", 0)
            try:
                numeric_score = float(raw_score)
            except Exception:
                numeric_score = 0.0
            if numeric_score > 1.0:
                numeric_score = numeric_score / 100.0
            concept_scores[concept_key] = max(0.0, min(1.0, numeric_score))

        if not concept_scores:
            raise ValueError("Diagnostic answers are empty.")

        average_score = self._average_score(concept_scores)
        recommended_level = self._recommended_level_from_score(average_score)
        evaluated_at = self._utcnow()
        summary = {
            "average_score": average_score,
            "recommended_level": recommended_level,
            "evaluated_at": evaluated_at,
            "question_count": len(concept_scores),
        }

        current = self.get_profile(user_id)
        prior_knowledge_map = dict(current.get("prior_knowledge_by_subject") or {})
        prior_knowledge_map[resolved_subject] = recommended_level

        diagnostic_scores_map = dict(current.get("diagnostic_scores_by_subject") or {})
        diagnostic_scores_map[resolved_subject] = concept_scores

        diagnostic_summary_map = dict(current.get("diagnostic_summary_by_subject") or {})
        diagnostic_summary_map[resolved_subject] = summary

        profile_payload = {
            "level": recommended_level,
            "prior_knowledge_by_subject": prior_knowledge_map,
            "diagnostic_scores_by_subject": diagnostic_scores_map,
            "diagnostic_summary_by_subject": diagnostic_summary_map,
        }
        self.update_profile(user_id, profile_payload)

        return {
            "subject_id": resolved_subject,
            "recommended_level": recommended_level,
            "average_score": average_score,
            "concept_scores": concept_scores,
            "prior_knowledge_level": prior_knowledge_map.get(resolved_subject),
            "completed": True,
            "evaluated_at": evaluated_at,
            "message": "Đã lưu kết quả chẩn đoán đầu vào vào learner profile.",
        }

    def get_diagnostic_result(
        self, *, user_id: str, subject_id: Optional[str] = None
    ) -> Dict[str, Any]:
        profile = self.get_profile(user_id)
        summaries = dict(profile.get("diagnostic_summary_by_subject") or {})
        scores_by_subject = dict(profile.get("diagnostic_scores_by_subject") or {})

        resolved_subject = self._slugify(subject_id)
        if not resolved_subject:
            resolved_subject = next(iter(summaries.keys()), "") or next(
                iter(scores_by_subject.keys()), ""
            )
        if not resolved_subject:
            resolved_subject = self.resolve_subject_id(
                subject_id=subject_id,
                goal=profile.get("learning_goal"),
                profile=profile,
            )

        summary = summaries.get(resolved_subject, {})
        concept_scores = scores_by_subject.get(resolved_subject, {})
        average_score = self._average_score(concept_scores)
        recommended_level = self._normalize_level(
            summary.get("recommended_level")
            or self._recommended_level_from_score(average_score)
        )
        return {
            "subject_id": resolved_subject,
            "recommended_level": recommended_level,
            "average_score": average_score,
            "concept_scores": concept_scores,
            "prior_knowledge_level": (
                profile.get("prior_knowledge_by_subject") or {}
            ).get(resolved_subject),
            "completed": bool(concept_scores),
            "evaluated_at": summary.get("evaluated_at"),
            "message": (
                "Đã có kết quả chẩn đoán cho môn học này."
                if concept_scores
                else "Chưa có kết quả chẩn đoán cho môn học này."
            ),
        }


learner_profile_service = LearnerProfileService()
