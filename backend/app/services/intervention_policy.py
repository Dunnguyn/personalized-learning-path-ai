"""Rule-based intervention policy for path refinement decisions."""

from __future__ import annotations

from typing import Any, Dict, List


class InterventionPolicy:
    """Evaluate learner state and return intervention candidates."""

    def evaluate(
        self,
        *,
        kt_states: List[Dict[str, Any]],
        signal_summary: Dict[str, Any],
        context: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        interventions: List[Dict[str, Any]] = []
        if not kt_states:
            return interventions

        mastery_values = [
            float(item.get("p_mastery", 0.0) or 0.0) for item in kt_states
        ]
        confidence_values = [
            float(item.get("confidence_score", 0.0) or 0.0) for item in kt_states
        ]
        correctness_values = [
            float(item.get("recent_correct_rate", 0.0) or 0.0) for item in kt_states
        ]
        time_values = [
            float(item.get("avg_time_spent", 0.0) or 0.0) for item in kt_states
        ]

        min_mastery = min(mastery_values) if mastery_values else 0.0
        avg_mastery = sum(mastery_values) / len(mastery_values)
        avg_confidence = sum(confidence_values) / max(1, len(confidence_values))
        avg_correct = sum(correctness_values) / max(1, len(correctness_values))
        avg_time = sum(time_values) / max(1, len(time_values))

        consecutive_failures = self._estimate_consecutive_failures(kt_states)
        prerequisite_weak = bool(context.get("prerequisite_weak", False))

        # Rule 1: reteach
        if min_mastery < 0.4 and consecutive_failures >= 2:
            interventions.append(
                self._pack(
                    intervention_type="reteach",
                    trigger_reason=f"p_mastery={min_mastery:.2f}, consecutive_failures={consecutive_failures}",
                    impact_scope="current_lesson",
                    action={"add": "remedial_resource", "priority": "high"},
                    priority=100,
                )
            )

        # Rule 2: reinforce
        if 0.4 <= avg_mastery < 0.7 and avg_correct < 0.7:
            interventions.append(
                self._pack(
                    intervention_type="reinforce",
                    trigger_reason=f"avg_mastery={avg_mastery:.2f}, avg_correct={avg_correct:.2f}",
                    impact_scope="current_and_next_lesson",
                    action={"add": "extra_practice", "count": 2},
                    priority=80,
                )
            )

        # Rule 3: accelerate
        completion_rate = float(signal_summary.get("completion_rate", 0.0) or 0.0)
        if avg_mastery > 0.85 and completion_rate >= 0.75:
            interventions.append(
                self._pack(
                    intervention_type="accelerate",
                    trigger_reason=f"avg_mastery={avg_mastery:.2f}, completion_rate={completion_rate:.2f}",
                    impact_scope="next_lessons",
                    action={"skip_easy_content": True},
                    priority=70,
                )
            )

        # Rule 4: format_shift
        if (
            avg_time > 900
            and float(signal_summary.get("confidence_gain", 0.0) or 0.0) <= 0.02
        ):
            interventions.append(
                self._pack(
                    intervention_type="format_shift",
                    trigger_reason=f"avg_time={avg_time:.1f}s with low confidence gain",
                    impact_scope="resource_recommendations",
                    action={"prefer_format": "video"},
                    priority=75,
                )
            )

        # Rule 5: prerequisite_bridge
        if prerequisite_weak:
            interventions.append(
                self._pack(
                    intervention_type="prerequisite_bridge",
                    trigger_reason="weak prerequisite concepts detected",
                    impact_scope="before_next_lesson",
                    action={"insert": "bridge_checkpoint"},
                    priority=90,
                )
            )

        # Rule 6: confidence mismatch diagnostic / reroute
        if avg_confidence >= 0.75 and avg_correct <= 0.45:
            interventions.append(
                self._pack(
                    intervention_type="reroute",
                    trigger_reason=f"confidence={avg_confidence:.2f}, accuracy={avg_correct:.2f}",
                    impact_scope="current_lesson",
                    action={"add": "diagnostic_quiz", "length": "short"},
                    priority=85,
                )
            )

        # Supplemental pace control
        if avg_time > 1200 and avg_mastery < 0.6:
            interventions.append(
                self._pack(
                    intervention_type="slow_down",
                    trigger_reason=f"avg_time={avg_time:.1f}s and avg_mastery={avg_mastery:.2f}",
                    impact_scope="next_lessons",
                    action={"pace": "slow"},
                    priority=60,
                )
            )

        interventions.sort(key=lambda item: int(item.get("priority", 0)), reverse=True)
        deduped: Dict[str, Dict[str, Any]] = {}
        for item in interventions:
            if item["intervention_type"] not in deduped:
                deduped[item["intervention_type"]] = item
        return list(deduped.values())

    @staticmethod
    def _estimate_consecutive_failures(kt_states: List[Dict[str, Any]]) -> int:
        max_failures = 0
        for state in kt_states:
            attempts = list(state.get("recent_attempts", []) or [])
            failures = 0
            for item in reversed(attempts):
                if item.get("correct") is False:
                    failures += 1
                elif item.get("correct") is True:
                    break
            max_failures = max(max_failures, failures)
        return max_failures

    @staticmethod
    def _pack(
        *,
        intervention_type: str,
        trigger_reason: str,
        impact_scope: str,
        action: Dict[str, Any],
        priority: int,
    ) -> Dict[str, Any]:
        return {
            "intervention_type": intervention_type,
            "trigger_reason": trigger_reason,
            "impact_scope": impact_scope,
            "action": action,
            "priority": priority,
        }


intervention_policy = InterventionPolicy()
