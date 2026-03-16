import argparse
from datetime import datetime

from backend.app.database.mongo import get_db
from backend.app.services.embedding_service import store_resource


def seed_concepts(db, reset: bool) -> None:
    concepts = [
        {
            "concept_id": 1,
            "concept_name": "Python Basics",
            "topic": "python",
            "difficulty": 2,
            "bloom_level": "remember",
        },
        {
            "concept_id": 2,
            "concept_name": "Control Flow",
            "topic": "python",
            "difficulty": 3,
            "bloom_level": "understand",
        },
        {
            "concept_id": 3,
            "concept_name": "Functions",
            "topic": "python",
            "difficulty": 3,
            "bloom_level": "apply",
        },
        {
            "concept_id": 4,
            "concept_name": "Data Structures",
            "topic": "python",
            "difficulty": 4,
            "bloom_level": "apply",
        },
        {
            "concept_id": 5,
            "concept_name": "Modules and Packages",
            "topic": "python",
            "difficulty": 4,
            "bloom_level": "understand",
        },
        {
            "concept_id": 6,
            "concept_name": "Backend Basics",
            "topic": "python",
            "difficulty": 5,
            "bloom_level": "apply",
        },
    ]

    if reset:
        db.concepts.delete_many({"concept_id": {"$in": [c["concept_id"] for c in concepts]}})

    for concept in concepts:
        db.concepts.update_one(
            {"concept_id": concept["concept_id"]},
            {"$set": {**concept, "updated_at": datetime.utcnow()}},
            upsert=True,
        )

    prerequisites = [
        {"from_concept_id": 1, "to_concept_id": 2},
        {"from_concept_id": 2, "to_concept_id": 3},
        {"from_concept_id": 3, "to_concept_id": 4},
        {"from_concept_id": 4, "to_concept_id": 5},
        {"from_concept_id": 5, "to_concept_id": 6},
    ]

    if reset:
        db.prerequisites.delete_many({})

    for prereq in prerequisites:
        db.prerequisites.update_one(
            prereq,
            {"$set": prereq},
            upsert=True,
        )

    knowledge_relations = [
        {
            "source_concept": "1",
            "target_concept": "2",
            "relation_type": "related_to",
        },
        {
            "source_concept": "2",
            "target_concept": "3",
            "relation_type": "used_in",
        },
        {
            "source_concept": "3",
            "target_concept": "5",
            "relation_type": "part_of",
        },
        {
            "source_concept": "4",
            "target_concept": "6",
            "relation_type": "used_in",
        },
        {
            "source_concept": "4",
            "target_concept": "6",
            "relation_type": "part_of",
        },
        {
            "source_concept": "1",
            "target_concept": "4",
            "relation_type": "example_of",
        },
        {
            "source_concept": "3",
            "target_concept": "6",
            "relation_type": "example_of",
        },
        {
            "source_concept": "5",
            "target_concept": "6",
            "relation_type": "related_to",
        },
    ]

    if reset:
        db.knowledge_relations.delete_many(
            {
                "$or": [
                    {"source_concept": {"$in": [str(c["concept_id"]) for c in concepts]}},
                    {"target_concept": {"$in": [str(c["concept_id"]) for c in concepts]}},
                ]
            }
        )

    for relation in knowledge_relations:
        db.knowledge_relations.update_one(
            relation,
            {"$set": relation},
            upsert=True,
        )


def seed_resources(db, reset: bool) -> None:
    resources = [
        {
            "title": "Python Syntax Overview",
            "content": "Learn basic syntax, variables, and indentation in Python.",
            "topic": "python",
            "level": "beginner",
            "source": "manual",
            "concept_id": 1,
            "pedagogy_type": "text",
            "bloom_level": "remember",
        },
        {
            "title": "If Statements and Loops",
            "content": "Practice conditional statements and loops with examples.",
            "topic": "python",
            "level": "beginner",
            "source": "manual",
            "concept_id": 2,
            "pedagogy_type": "text",
            "bloom_level": "understand",
        },
        {
            "title": "Writing Functions",
            "content": "Define functions, parameters, return values, and docstrings.",
            "topic": "python",
            "level": "beginner",
            "source": "manual",
            "concept_id": 3,
            "pedagogy_type": "text",
            "bloom_level": "apply",
        },
        {
            "title": "Lists and Dictionaries",
            "content": "Use lists, tuples, sets, and dictionaries in Python projects.",
            "topic": "python",
            "level": "beginner",
            "source": "manual",
            "concept_id": 4,
            "pedagogy_type": "text",
            "bloom_level": "apply",
        },
        {
            "title": "Working with Modules",
            "content": "Import modules, build packages, and manage dependencies.",
            "topic": "python",
            "level": "beginner",
            "source": "manual",
            "concept_id": 5,
            "pedagogy_type": "text",
            "bloom_level": "understand",
        },
        {
            "title": "FastAPI Fundamentals",
            "content": "Build a simple API with FastAPI, routing, and request handling.",
            "topic": "python",
            "level": "beginner",
            "source": "manual",
            "concept_id": 6,
            "pedagogy_type": "text",
            "bloom_level": "apply",
        },
    ]

    if reset:
        db.resources.delete_many({"topic": "python", "source": "manual"})

    for resource in resources:
        store_resource(
            title=resource["title"],
            content=resource["content"],
            topic=resource["topic"],
            level=resource["level"],
            source=resource["source"],
            concept_id=resource["concept_id"],
            pedagogy_type=resource["pedagogy_type"],
            bloom_level=resource["bloom_level"],
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed sample concepts and resources")
    parser.add_argument("--reset", action="store_true", help="Reset sample data before seeding")
    args = parser.parse_args()

    db = get_db()
    seed_concepts(db, args.reset)
    seed_resources(db, args.reset)
    print("Seed completed.")


if __name__ == "__main__":
    main()
