"""CLI runner for offline adaptive recommendation jobs."""

from __future__ import annotations

import argparse
import json
from typing import Any, Dict

from backend.app.jobs.compute_expected_learning_gain_job import (
    compute_expected_learning_gain_job,
)
from backend.app.jobs.compute_learner_state_snapshot_job import (
    compute_learner_state_snapshot_job,
)
from backend.app.jobs.compute_resource_quality_job import compute_resource_quality_job


def run_job(args: argparse.Namespace) -> Dict[str, Any]:
    if args.job == "quality":
        return compute_resource_quality_job.run(
            full=args.full,
            incremental=args.incremental,
            resource_id=args.resource_id,
            dry_run=args.dry_run,
        )
    if args.job == "learner_state":
        return compute_learner_state_snapshot_job.run(
            user_id=args.user_id,
            dry_run=args.dry_run,
        )
    if args.job == "expected_gain":
        return compute_expected_learning_gain_job.run(
            resource_id=args.resource_id,
            incremental=args.incremental,
            dry_run=args.dry_run,
        )
    return {
        "job": "all",
        "results": [
            compute_resource_quality_job.run(
                full=args.full,
                incremental=args.incremental,
                resource_id=args.resource_id,
                dry_run=args.dry_run,
            ),
            compute_learner_state_snapshot_job.run(
                user_id=args.user_id,
                dry_run=args.dry_run,
            ),
            compute_expected_learning_gain_job.run(
                resource_id=args.resource_id,
                incremental=args.incremental,
                dry_run=args.dry_run,
            ),
        ],
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run adaptive recommendation batch jobs.")
    parser.add_argument(
        "--job",
        choices=["quality", "learner_state", "expected_gain", "all"],
        default="all",
    )
    parser.add_argument("--user-id", default=None)
    parser.add_argument("--resource-id", default=None)
    parser.add_argument("--full", action="store_true")
    parser.add_argument("--incremental", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result = run_job(args)
    print(json.dumps(result, default=str, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
