"""Resource quality scoring with heuristics and lightweight history aggregation."""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from backend.app.repositories.recommendation_repository import RecommendationRepository
from backend.app.services.recommendation.normalization import extract_resource_keys


class ResourceQualityService:
    """Compute resource quality signals with graceful fallbacks."""

    def __init__(self, repository: RecommendationRepository | None = None) -> None:
        self.repository = repository or RecommendationRepository()
        self.collection = self.repository.db["resource_quality_stats"]
        self.collection.create_index([("resource_key", 1)], unique=True)
        self.collection.create_index([("updated_at", -1)])

    @staticmethod
    def _clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
        return max(minimum, min(maximum, float(value)))

    @staticmethod
    def _safe_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except Exception:
            return default

    @staticmethod
    def _resource_text(resource: Dict[str, Any]) -> str:
        metadata = resource.get("metadata") or {}
        return " ".join(
            [
                str(resource.get("title") or ""),
                str(resource.get("topic") or ""),
                str(resource.get("content_summary") or ""),
                str(metadata.get("summary") or ""),
                str(metadata.get("description") or ""),
            ]
        ).strip()

    def _content_completeness(self, resource: Dict[str, Any], chunk_count: int) -> float:
        summary = str(resource.get("content_summary") or "")
        text = self._resource_text(resource)
        score = 0.0
        score += min(chunk_count / 8.0, 1.0) * 0.65
        if len(summary) >= 120:
            score += 0.2
        if len(text) >= 240:
            score += 0.15
        return self._clamp(score)

    def _chunk_density(self, chunk_count: int, text: str) -> float:
        if not text:
            return self._clamp(chunk_count / 8.0)
        token_count = max(len(re.findall(r"\w+", text)), 1)
        density = chunk_count / max(token_count / 120.0, 1.0)
        return self._clamp(density / 4.0)

    def _clarity_readability(self, text: str) -> float:
        if not text:
            return 0.55
        sentences = [item.strip() for item in re.split(r"(?<=[.!?])\s+", text) if item.strip()]
        if not sentences:
            return 0.55
        avg_sentence_words = sum(len(re.findall(r"\w+", sentence)) for sentence in sentences) / max(len(sentences), 1)
        punctuation_bonus = 0.08 if ":" in text or "-" in text else 0.0
        readability = 1.0 - min(max(avg_sentence_words - 14.0, 0.0) / 24.0, 0.55)
        return self._clamp(readability + punctuation_bonus)

    def _source_credibility(self, resource: Dict[str, Any]) -> float:
        source = str(resource.get("source") or "").lower()
        metadata = resource.get("metadata") or {}
        url = str(metadata.get("url") or resource.get("url") or "").lower()
        if any(domain in url for domain in (".edu", ".gov", "docs.python.org", "developer.mozilla.org")):
            return 0.96
        if source == "pdf":
            return 0.9
        if source == "manual":
            return 0.86
        if source == "youtube":
            return 0.68
        if source == "web":
            return 0.74
        return 0.72

    def _engagement_stats(self, resource_keys: list[str]) -> Dict[str, float]:
        keys = [str(item) for item in resource_keys if str(item).strip()]
        if not keys:
            return {"engagement_rate": 0.45, "avg_completion_rate": 0.4, "avg_helpfulness": 0.6}
        since = datetime.now(timezone.utc) - timedelta(days=180)
        pipeline = [
            {
                "$match": {
                    "timestamp": {"$gte": since},
                    "resource_id": {"$exists": True, "$ne": None},
                    "event_type": {
                        "$in": [
                            "recommendation_shown",
                            "resource_clicked",
                            "resource_completed",
                            "recommendation_feedback",
                        ]
                    },
                }
            },
            {"$project": {"resource_key": {"$toString": "$resource_id"}, "event_type": 1, "metadata": 1}},
            {"$match": {"resource_key": {"$in": keys}}},
            {
                "$group": {
                    "_id": "$resource_key",
                    "shown": {"$sum": {"$cond": [{"$eq": ["$event_type", "recommendation_shown"]}, 1, 0]}},
                    "clicked": {"$sum": {"$cond": [{"$eq": ["$event_type", "resource_clicked"]}, 1, 0]}},
                    "completed": {"$sum": {"$cond": [{"$eq": ["$event_type", "resource_completed"]}, 1, 0]}},
                    "helpful": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$and": [
                                        {"$eq": ["$event_type", "recommendation_feedback"]},
                                        {"$eq": ["$metadata.feedback_type", "helpful"]},
                                    ]
                                },
                                1,
                                0,
                            ]
                        }
                    },
                    "negative": {
                        "$sum": {
                            "$cond": [
                                {
                                    "$and": [
                                        {"$eq": ["$event_type", "recommendation_feedback"]},
                                        {"$in": ["$metadata.feedback_type", ["not_helpful", "hide"]]},
                                    ]
                                },
                                1,
                                0,
                            ]
                        }
                    },
                }
            },
        ]
        rows = list(self.repository.event_logs.aggregate(pipeline))
        if not rows:
            return {"engagement_rate": 0.45, "avg_completion_rate": 0.4, "avg_helpfulness": 0.6}

        shown = max(sum(self._safe_float(row.get("shown"), 0.0) for row in rows), 1.0)
        clicked = sum(self._safe_float(row.get("clicked"), 0.0) for row in rows)
        completed = sum(self._safe_float(row.get("completed"), 0.0) for row in rows)
        helpful = sum(self._safe_float(row.get("helpful"), 0.0) for row in rows)
        negative = sum(self._safe_float(row.get("negative"), 0.0) for row in rows)
        engagement_rate = self._clamp((clicked + 1.5 * completed) / (shown + 2.0))
        avg_completion_rate = self._clamp(completed / max(clicked, 1.0))
        helpful_total = helpful + negative
        avg_helpfulness = (
            self._clamp((helpful + 0.5) / (helpful_total + 1.0)) if helpful_total >= 0 else 0.6
        )
        return {
            "engagement_rate": round(engagement_rate, 4),
            "avg_completion_rate": round(avg_completion_rate, 4),
            "avg_helpfulness": round(avg_helpfulness, 4),
        }

    def _assessment_uplift_rate(self, resource_key: str, quality_inputs: Dict[str, float]) -> float:
        blended = (
            0.45 * quality_inputs["avg_completion_rate"]
            + 0.35 * quality_inputs["avg_helpfulness"]
            + 0.20 * quality_inputs["engagement_rate"]
        )
        return round(self._clamp(blended), 4)

    def get_resource_quality(self, resource: Dict[str, Any]) -> Dict[str, Any]:
        resource_key = self.repository.get_resource_key(resource)
        cached = self.collection.find_one({"resource_key": str(resource_key)})
        if cached:
            cached_payload = {
                "resource_id": str(cached.get("resource_id") or resource_key),
                "content_completeness": round(self._safe_float(cached.get("content_completeness"), 0.0), 4),
                "chunk_density": round(self._safe_float(cached.get("chunk_density"), 0.0), 4),
                "clarity_readability": round(self._safe_float(cached.get("clarity_readability"), 0.0), 4),
                "source_credibility": round(self._safe_float(cached.get("source_credibility"), 0.0), 4),
                "engagement_rate": round(self._safe_float(cached.get("engagement_rate"), 0.0), 4),
                "avg_completion_rate": round(self._safe_float(cached.get("avg_completion_rate"), 0.0), 4),
                "avg_helpfulness": round(self._safe_float(cached.get("avg_helpfulness"), 0.0), 4),
                "assessment_uplift_rate": round(self._safe_float(cached.get("assessment_uplift_rate"), 0.0), 4),
                "quality_score": round(self._safe_float(cached.get("quality_score"), 0.0), 4),
                "sample_size": int(cached.get("sample_size") or 0),
            }
            if cached_payload["quality_score"] > 0:
                return cached_payload

        text = self._resource_text(resource)
        chunk_count = int(resource.get("chunks_count") or 0)
        metadata = resource.get("metadata") or {}
        if chunk_count <= 0:
            chunk_count = int(metadata.get("chunk_count") or 0)
        if chunk_count <= 0:
            chunk_count = 1 if text else 0

        engagement_stats = self._engagement_stats(
            sorted(extract_resource_keys(resource) or {resource_key})
        )
        payload = {
            "resource_id": str(resource_key),
            "content_completeness": round(
                self._content_completeness(resource, chunk_count), 4
            ),
            "chunk_density": round(self._chunk_density(chunk_count, text), 4),
            "clarity_readability": round(self._clarity_readability(text), 4),
            "source_credibility": round(self._source_credibility(resource), 4),
            "engagement_rate": engagement_stats["engagement_rate"],
            "avg_completion_rate": engagement_stats["avg_completion_rate"],
            "avg_helpfulness": engagement_stats["avg_helpfulness"],
            "assessment_uplift_rate": self._assessment_uplift_rate(
                resource_key, engagement_stats
            ),
        }
        payload["quality_score"] = round(
            self._clamp(
                0.18 * payload["content_completeness"]
                + 0.10 * payload["chunk_density"]
                + 0.14 * payload["clarity_readability"]
                + 0.16 * payload["source_credibility"]
                + 0.12 * payload["engagement_rate"]
                + 0.10 * payload["avg_completion_rate"]
                + 0.10 * payload["avg_helpfulness"]
                + 0.10 * payload["assessment_uplift_rate"]
            ),
            4,
        )

        self.collection.update_one(
            {"resource_key": str(resource_key)},
            {
                "$set": {
                    "resource_key": str(resource_key),
                    **payload,
                    "updated_at": datetime.now(timezone.utc),
                }
            },
            upsert=True,
        )
        return payload


resource_quality_service = ResourceQualityService()
