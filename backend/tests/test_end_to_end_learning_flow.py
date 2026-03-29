from __future__ import annotations

from uuid import uuid4

from bson import ObjectId
from fastapi.testclient import TestClient

from backend.app.database.mongo import get_db
from backend.app.services.learning_path_service import learning_path_service
from backend.main import app


def test_seeded_end_to_end_learning_flow(monkeypatch):
    client = TestClient(app)
    db = get_db()
    run = uuid4().hex[:8]
    email = f"codex-e2e-{run}@example.com"
    password = "TestPass123!"

    created_user_id: str | None = None
    manual_subject_id: str | None = None
    manual_chapter_id: str | None = None
    manual_lesson_id: str | None = None
    resource_ids: list[ObjectId] = []
    job_ids: list[ObjectId] = []
    concept_ids: list[ObjectId] = []
    path_id: str | None = None

    # Keep the test local and deterministic even when outbound network is blocked.
    monkeypatch.setattr(learning_path_service.llm_client, "is_available", lambda: False)
    monkeypatch.setattr(
        learning_path_service.llm_client,
        "status",
        lambda: {
            "provider": "gemini",
            "enabled": False,
            "cooldown_active": False,
            "reason": "disabled in integration test",
            "model": None,
        },
    )

    try:
        signup = client.post(
            "/api/auth/signup",
            json={
                "email": email,
                "password": password,
                "fullName": "Codex E2E",
            },
        )
        assert signup.status_code == 201, signup.text
        created_user_id = signup.json()["user"]["user_id"]

        login = client.post(
            "/api/auth/login",
            json={"email": email, "password": password},
        )
        assert login.status_code == 200, login.text
        headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        inserted_concepts = db.concepts.insert_many(
            [
                {
                    "concept_id": 9101,
                    "concept_name": f"Python Variables {run}",
                    "topic": "python",
                    "difficulty": 1,
                },
                {
                    "concept_id": 9102,
                    "concept_name": f"Python Loops {run}",
                    "topic": "python",
                    "difficulty": 2,
                },
            ]
        )
        concept_ids.extend(inserted_concepts.inserted_ids)

        subject = client.post(
            "/api/subjects/",
            headers=headers,
            json={
                "title": f"E2E Subject {run}",
                "slug": f"e2e-{run}",
                "description": "Subject for end-to-end testing",
                "topic": "python",
                "level": "beginner",
                "metadata": {"e2e_run": run},
            },
        )
        assert subject.status_code == 201, subject.text
        manual_subject_id = subject.json()["subject_id"]

        chapter = client.post(
            "/api/chapters/",
            headers=headers,
            json={
                "subject_id": manual_subject_id,
                "title": f"E2E Chapter {run}",
                "description": "Chapter for end-to-end testing",
                "order": 1,
                "topic": "python",
                "metadata": {"e2e_run": run},
            },
        )
        assert chapter.status_code == 201, chapter.text
        manual_chapter_id = chapter.json()["chapter_id"]

        lesson = client.post(
            "/api/lessons/",
            headers=headers,
            json={
                "subject_id": manual_subject_id,
                "chapter_id": manual_chapter_id,
                "title": f"E2E Lesson {run}",
                "summary": "Learn Python variables and loops with simple examples.",
                "order": 1,
                "topic": "python",
                "level": "beginner",
                "learning_objectives": [
                    "Understand variables",
                    "Understand loops",
                ],
                "keywords": ["python", "variables", "loops"],
                "resource_ids": [],
                "metadata": {"e2e_run": run},
            },
        )
        assert lesson.status_code == 201, lesson.text
        manual_lesson_id = lesson.json()["lesson_id"]

        for title, content, concept_id in [
            (
                f"Python Basics {run}",
                (
                    "Python variables store values. Loops like for and while repeat "
                    "tasks. Variables can hold numbers and strings. Use for loops to "
                    "iterate through lists and while loops for repeated checks."
                ),
                9101,
            ),
            (
                f"Python Loops Deep Dive {run}",
                (
                    "A for loop iterates over items. A while loop repeats while a "
                    "condition stays true. Loop control with break and continue helps "
                    "manage flow. Practice loops with ranges and lists."
                ),
                9102,
            ),
        ]:
            resource = client.post(
                "/api/resources/",
                headers=headers,
                json={
                    "title": title,
                    "content": content,
                    "source": "manual",
                    "type": "text",
                    "topic": "python",
                    "level": "beginner",
                    "concept_id": concept_id,
                    "url": None,
                },
            )
            assert resource.status_code == 202, resource.text
            resource_ids.append(ObjectId(resource.json()["resource_id"]))
            if resource.json().get("job_id"):
                job_ids.append(ObjectId(resource.json()["job_id"]))

        resources_payload = client.get("/api/resources/", headers=headers)
        assert resources_payload.status_code == 200, resources_payload.text
        assert resources_payload.json()["total"] >= 2

        search_payload = client.get(
            "/api/resources/search",
            headers=headers,
            params={"q": "python loops", "topic": "python"},
        )
        assert search_payload.status_code == 200, search_payload.text
        assert search_payload.json()["total"] >= 1

        learning_path = client.post(
            "/api/learning-paths/generate",
            headers=headers,
            json={
                "subject_id": "python",
                "goal": "python",
                "level": "beginner",
            },
        )
        assert learning_path.status_code == 200, learning_path.text
        learning_path_json = learning_path.json()
        path_id = learning_path_json["path_id"]

        assert learning_path_json["chapters"], learning_path_json
        first_chapter = learning_path_json["chapters"][0]
        assert first_chapter["lessons"], learning_path_json
        first_lesson = first_chapter["lessons"][0]
        assert first_lesson["recommended_chunk_ids"], learning_path_json

        lesson_locks_before = client.get(
            f"/api/learning-paths/{path_id}/lesson-locks",
            headers=headers,
        )
        assert lesson_locks_before.status_code == 200, lesson_locks_before.text
        first_lesson_id = first_lesson["lesson_id"]
        second_lesson_id = first_chapter["lessons"][1]["lesson_id"]
        lock_map_before = lesson_locks_before.json()["lesson_locks"]
        assert lock_map_before[first_lesson_id]["is_locked"] is False
        assert lock_map_before[second_lesson_id]["is_locked"] is True

        progress = client.post(
            "/api/learning-paths/lesson-progress",
            headers=headers,
            json={
                "path_id": path_id,
                "lesson_id": first_lesson_id,
                "status": "completed",
                "confidence": 0.9,
                "questions_answered": [
                    {
                        "question_id": f"q-{run}",
                        "question": "What does a variable do?",
                        "question_type": "multiple_choice",
                        "user_answer": "Stores a value",
                        "correct_answer": "Stores a value",
                        "is_correct": True,
                        "difficulty": "beginner",
                        "bloom_level": "remember",
                        "chunk_id": None,
                        "concept_id": "9101",
                        "confidence_score": 0.9,
                    }
                ],
            },
        )
        assert progress.status_code == 200, progress.text
        progress_json = progress.json()
        assert progress_json["status"] == "completed"
        assert progress_json["auto_completed"] is True
        assert progress_json["attempt_id"]

        lesson_locks_after = client.get(
            f"/api/learning-paths/{path_id}/lesson-locks",
            headers=headers,
        )
        assert lesson_locks_after.status_code == 200, lesson_locks_after.text
        lock_map_after = lesson_locks_after.json()["lesson_locks"]
        assert lock_map_after[second_lesson_id]["is_locked"] is False

        recommendations = client.get(
            "/api/recommendations/resources",
            headers=headers,
            params={
                "goal": "python",
                "level": "beginner",
                "include_breakdown": "true",
                "enable_reranking": "true",
            },
        )
        assert recommendations.status_code == 200, recommendations.text
        recommendations_json = recommendations.json()
        assert len(recommendations_json["recommended_resources"]) >= 1

        history = client.get("/api/learning-paths/history", headers=headers)
        assert history.status_code == 200, history.text
        assert any(item["path_id"] == path_id for item in history.json())
    finally:
        if path_id:
            generated_lessons = list(
                db.lessons.find({"metadata.learning_path_id": path_id}, {"_id": 1})
            )
            generated_lesson_ids = [item["_id"] for item in generated_lessons]

            generated_chapters = list(
                db.chapters.find({"metadata.learning_path_id": path_id}, {"_id": 1})
            )
            generated_chapter_ids = [item["_id"] for item in generated_chapters]

            if generated_lesson_ids:
                db.lesson_recommended_chunks.delete_many(
                    {"lesson_id": {"$in": generated_lesson_ids}}
                )
                db.lessons.delete_many({"_id": {"$in": generated_lesson_ids}})
            if generated_chapter_ids:
                db.chapters.delete_many({"_id": {"$in": generated_chapter_ids}})
            db.learning_paths.delete_many({"path_id": path_id})

        if job_ids:
            db.ingestion_jobs.delete_many({"_id": {"$in": job_ids}})
        if resource_ids:
            db.resource_chunks.delete_many({"resource_id": {"$in": resource_ids}})
            db.resources.delete_many({"_id": {"$in": resource_ids}})

        if manual_lesson_id:
            db.lesson_recommended_chunks.delete_many(
                {"lesson_id": ObjectId(manual_lesson_id)}
            )
            db.lessons.delete_one({"_id": ObjectId(manual_lesson_id)})
        if manual_chapter_id:
            db.chapters.delete_one({"_id": ObjectId(manual_chapter_id)})
        if manual_subject_id:
            db.subjects.delete_one({"_id": ObjectId(manual_subject_id)})

        if concept_ids:
            db.concepts.delete_many({"_id": {"$in": concept_ids}})

        if created_user_id:
            for collection_name in [
                "adaptive_attempts",
                "adaptive_events",
                "concept_mastery_states",
                "event_logs",
                "exercise_attempts",
                "learner_signals",
                "lesson_study_time",
                "revoked_tokens",
                "user_learning_states",
            ]:
                db[collection_name].delete_many({"user_id": created_user_id})
            db.users.delete_one({"_id": ObjectId(created_user_id)})
