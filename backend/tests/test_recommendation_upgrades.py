from __future__ import annotations

import unittest

from backend.app.services.hybrid_recommendation_service import (
    HybridRecommendationService,
    ResourceRecommendationWeights,
)
from backend.app.services.lesson_chunk_service import (
    ChunkScoringWeights,
    LessonChunkService,
)
from backend.app.services.recommendation_explanation_service import (
    RecommendationExplanationService,
)


class RecommendationUpgradeTests(unittest.TestCase):
    def test_resource_scoring_components_reward_learning_gain_and_penalize_fatigue(self):
        service = HybridRecommendationService.__new__(HybridRecommendationService)
        service.expected_learning_gain_service = type(
            "ExpectedGainStub",
            (),
            {
                "get_expected_gain": staticmethod(
                    lambda **_: {"expected_learning_gain": 0.78}
                )
            },
        )()
        high_gain = service._expected_learning_gain(
            resource_key="resource-1",
            concept_id="loops",
            mastery=0.25,
            confidence=0.35,
            quality={"assessment_uplift_rate": 0.8, "quality_score": 0.84},
            concept_gap_fit=0.86,
            mode="reinforce_weaknesses",
        )
        low_gain = service._expected_learning_gain(
            resource_key="resource-2",
            concept_id="variables",
            mastery=0.82,
            confidence=0.88,
            quality={"assessment_uplift_rate": 0.3, "quality_score": 0.45},
            concept_gap_fit=0.22,
            mode="continue_learning",
        )
        fatigue = service._fatigue_penalty(
            learner_state={
                "frustration_score": 0.8,
                "avg_session_duration": 8,
                "unfinished_resources": 7,
                "recovery_need_flag": True,
            },
            resource={"type": "text"},
            explanation_time=28,
            mode="quick_review",
        )
        final_score = service._compute_final_score(
            components={
                "semantic_match": 0.82,
                "concept_gap_fit": 0.86,
                "difficulty_fit": 0.78,
                "goal_fit": 0.8,
                "collaborative_score": 0.42,
                "pedagogical_fit": 0.75,
                "format_fit": 0.7,
                "engagement_fit": 0.68,
                "quality_score": 0.84,
                "expected_learning_gain": high_gain,
                "fatigue_penalty": 0.12,
                "redundancy_penalty": 0.08,
            },
            weights=ResourceRecommendationWeights(),
        )

        self.assertGreater(high_gain, low_gain)
        self.assertGreater(fatigue, 0.5)
        self.assertGreater(final_score, 0.0)
        self.assertLessEqual(final_score, 1.0)

    def test_recommendation_explanation_includes_mode_tags_and_session_fit(self):
        service = RecommendationExplanationService()
        explanation = service.build_explanation(
            resource={
                "topic": "python loops",
                "metadata": {
                    "primary_concepts": ["loops", "conditions"],
                    "estimated_time": 12,
                },
            },
            mode="reinforce_weaknesses",
            learner_state={"current_focus_concepts": ["loops"], "avg_session_duration": 15},
            score_breakdown={"difficulty_fit": 0.9, "concept_gap_fit": 0.82},
            goal="Learn Python fundamentals",
            level="beginner",
            quality_score=0.78,
            expected_learning_gain=0.83,
        )

        self.assertEqual(explanation["recommendation_mode"], "reinforce_weaknesses")
        self.assertIn("weak_concept", explanation["reason_tags"])
        self.assertEqual(explanation["estimated_time"], 12)
        self.assertEqual(explanation["primary_concepts"][:2], ["loops", "conditions"])

    def test_sequence_builder_orders_chunks_into_instructional_flow(self):
        service = LessonChunkService.__new__(LessonChunkService)
        candidates = [
            {
                "chunk_id": "a",
                "instruction_role": "worked_example",
                "base_score": 0.82,
                "score_breakdown": {
                    "semantic_score": 0.8,
                    "lexical_score": 0.7,
                    "objective_coverage": 0.6,
                    "concept_coverage": 0.8,
                    "difficulty_fit": 0.9,
                    "instructional_role_fit": 0.94,
                    "questionability_score": 0.88,
                    "novelty_score": 1.0,
                },
                "embedding": [0.2, 0.8],
                "preview": "",
            },
            {
                "chunk_id": "b",
                "instruction_role": "introduction",
                "base_score": 0.7,
                "score_breakdown": {
                    "semantic_score": 0.75,
                    "lexical_score": 0.74,
                    "objective_coverage": 0.55,
                    "concept_coverage": 0.72,
                    "difficulty_fit": 0.9,
                    "instructional_role_fit": 0.86,
                    "questionability_score": 0.62,
                    "novelty_score": 1.0,
                },
                "embedding": [1.0, 0.0],
                "preview": "",
            },
            {
                "chunk_id": "c",
                "instruction_role": "summary",
                "base_score": 0.68,
                "score_breakdown": {
                    "semantic_score": 0.72,
                    "lexical_score": 0.62,
                    "objective_coverage": 0.5,
                    "concept_coverage": 0.6,
                    "difficulty_fit": 0.84,
                    "instructional_role_fit": 0.8,
                    "questionability_score": 0.56,
                    "novelty_score": 1.0,
                },
                "embedding": [0.0, 1.0],
                "preview": "",
            },
        ]

        sequence, metadata = service._build_sequence(
            candidates=candidates,
            max_chunks=3,
            weights=ChunkScoringWeights(),
        )

        self.assertEqual(
            [item["instruction_role"] for item in sequence][:2],
            ["introduction", "worked_example"],
        )
        self.assertTrue(metadata["has_introduction"])
        self.assertEqual(sequence[0]["sequence_position"], 1)

    def test_clustering_keeps_one_representative_per_semantic_group(self):
        service = LessonChunkService.__new__(LessonChunkService)
        candidates = [
            {"chunk_id": "c1", "base_score": 0.9, "embedding": [1.0, 0.0]},
            {"chunk_id": "c2", "base_score": 0.8, "embedding": [0.99, 0.01]},
            {"chunk_id": "c3", "base_score": 0.7, "embedding": [0.0, 1.0]},
        ]

        representatives = service._cluster_candidates(candidates)

        self.assertEqual(len(representatives), 2)
        self.assertTrue(all(item["selected_as_representative"] for item in representatives))
        self.assertEqual(len({item["cluster_id"] for item in representatives}), 2)


if __name__ == "__main__":
    unittest.main()
