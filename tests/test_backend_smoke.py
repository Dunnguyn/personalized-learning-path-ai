from datetime import datetime, timedelta, timezone
from pathlib import Path

from bson import ObjectId

from backend.main import app
from backend.app.api import ask, chapters, concepts, learning_path, learning_paths, lessons, progress, recommendations, resources, subjects, users
from backend.app.database import mongo as mongo_module

from conftest import FakeDatabase, TEST_USER_ID, TEST_USER_INT_ID


def test_health_and_docs_endpoints(client):
    root = client.get("/")
    assert root.status_code == 200
    assert root.json()["status"] == "running"

    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json()["status"] == "healthy"

    ready = client.get("/api/ready")
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"

    docs = client.get("/docs", follow_redirects=False)
    assert docs.status_code == 307
    assert docs.headers["location"] == "/api/docs"

    schema = client.get("/api/openapi.json")
    assert schema.status_code == 200
    assert "paths" in schema.json()


def test_route_registry_contains_all_backend_areas():
    route_map = {
        (method, route.path)
        for route in app.routes
        for method in getattr(route, "methods", [])
        if method in {"GET", "POST", "PUT", "DELETE"}
    }

    expected = {
        ("POST", "/api/auth/login"),
        ("GET", "/api/users/me"),
        ("POST", "/api/subjects/"),
        ("POST", "/api/chapters/"),
        ("POST", "/api/lessons/"),
        ("GET", "/api/resources/"),
        ("POST", "/api/learning-path/generate"),
        ("POST", "/api/learning-paths/generate"),
        ("POST", "/api/progress/update"),
        ("POST", "/api/ask/"),
        ("GET", "/api/recommendations/resources"),
        ("GET", "/api/concepts"),
    }
    assert expected.issubset(route_map)


def test_protected_endpoints_require_authentication(client):
    cases = [
        ("get", "/api/users/me", {}),
        ("post", "/api/subjects/", {"json": {"title": "Python Basics"}}),
        ("post", "/api/resources/", {"json": {
            "title": "Intro Resource",
            "content": "abcdefghij resource content",
            "topic": "python",
            "level": "beginner",
        }}),
        ("post", "/api/learning-path/generate", {"json": {
            "user_id": TEST_USER_ID,
            "goal": "Learn Python",
            "level": "beginner",
        }}),
        ("post", "/api/learning-paths/generate", {"json": {
            "subject_id": "python",
            "goal": "Learn Python",
            "level": "beginner",
        }}),
        ("post", "/api/progress/update", {"json": {
            "user_id": TEST_USER_ID,
            "concept_id": 1,
            "mastery": 0.5,
            "confidence": 0.6,
        }}),
        ("post", "/api/ask/", {"json": {
            "user_id": TEST_USER_ID,
            "question": "What is a variable?",
            "goal": "Learn Python",
            "level": "beginner",
        }}),
    ]

    for method, path, kwargs in cases:
        response = getattr(client, method)(path, **kwargs)
        assert response.status_code == 401, f"{method.upper()} {path} should require auth"


def test_user_creation_smoke(client, monkeypatch):
    fake_db = FakeDatabase({"users": []})
    monkeypatch.setattr(users, "get_db", lambda: fake_db)

    response = client.post(
        "/api/users/",
        json={
            "name": "New User",
            "email": "NEW@Example.com",
            "password": "securepass123",
            "level": "beginner",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["email"] == "new@example.com"
    stored = fake_db.users.items[0]
    assert stored["email"] == "new@example.com"
    assert stored["password"] != "securepass123"


def test_subject_chapter_and_lesson_endpoints(authed_client, monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(subjects.lesson_structure_service, "create_subject", lambda payload: {
        "subject_id": "sub-1",
        "title": payload.title,
        "slug": payload.slug,
        "description": payload.description,
        "topic": payload.topic,
        "level": payload.level,
        "metadata": payload.metadata,
        "created_at": now,
    })
    monkeypatch.setattr(chapters.lesson_structure_service, "create_chapter", lambda payload: {
        "chapter_id": "chap-1",
        "subject_id": payload.subject_id,
        "title": payload.title,
        "description": payload.description,
        "order": payload.order,
        "topic": payload.topic,
        "metadata": payload.metadata,
        "created_at": now,
    })
    monkeypatch.setattr(lessons.lesson_structure_service, "create_lesson", lambda payload: {
        "lesson_id": "lesson-1",
        "subject_id": payload.subject_id,
        "chapter_id": payload.chapter_id,
        "title": payload.title,
        "summary": payload.summary,
        "order": payload.order,
        "topic": payload.topic,
        "level": payload.level,
        "learning_objectives": payload.learning_objectives,
        "keywords": payload.keywords,
        "resource_ids": payload.resource_ids,
        "metadata": payload.metadata,
        "created_at": now,
    })

    subject_response = authed_client.post("/api/subjects/", json={"title": "Python Basics"})
    chapter_response = authed_client.post(
        "/api/chapters/",
        json={"subject_id": "sub-1", "title": "Variables", "order": 1},
    )
    lesson_response = authed_client.post(
        "/api/lessons/",
        json={
            "subject_id": "sub-1",
            "chapter_id": "chap-1",
            "title": "What Is a Variable?",
            "summary": "Short lesson",
        },
    )

    assert subject_response.status_code == 201
    assert chapter_response.status_code == 201
    assert lesson_response.status_code == 201
    assert lesson_response.json()["lesson_id"] == "lesson-1"


def test_lesson_chunk_and_question_bank_endpoints(authed_client, monkeypatch):
    created_at = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(lessons.lesson_chunk_service, "recommend_chunks", lambda **kwargs: {
        "recommendation_id": "rec-1",
        "subject_id": "sub-1",
        "chapter_id": "chap-1",
        "lesson_id": kwargs["lesson_id"],
        "chunk_ids": ["chunk-1"],
        "resource_ids": ["res-1"],
        "selection_strategy": kwargs["selection_strategy"],
        "metadata": kwargs["metadata"],
        "recommended_chunks": [{
            "chunk_id": "chunk-1",
            "resource_id": "res-1",
            "chunk_index": 0,
            "score": 0.95,
            "preview": "Chunk preview",
        }],
        "created_at": created_at,
    })
    monkeypatch.setattr(lessons.lesson_chunk_service, "get_recommendation", lambda lesson_id: {
        "recommendation_id": "rec-1",
        "subject_id": "sub-1",
        "chapter_id": "chap-1",
        "lesson_id": lesson_id,
        "chunk_ids": ["chunk-1"],
        "resource_ids": ["res-1"],
        "selection_strategy": "local_semantic_lesson_scope_v1",
        "metadata": {},
        "recommended_chunks": [{
            "chunk_id": "chunk-1",
            "resource_id": "res-1",
            "chunk_index": 0,
            "score": 0.95,
            "preview": "Chunk preview",
        }],
        "created_at": created_at,
    })
    monkeypatch.setattr(lessons.lesson_question_generation_service, "generate_questions_for_lesson", lambda **kwargs: {
        "lesson_id": kwargs["lesson_id"],
        "status": "generated",
        "generated_count": 2,
        "question_ids": ["q-1", "q-2"],
        "chunks_used": ["chunk-1"],
        "insufficient_data": False,
        "message": "ok",
    })
    monkeypatch.setattr(lessons.lesson_question_generation_service, "get_questions_for_lesson", lambda lesson_id: {
        "lesson_id": lesson_id,
        "total": 1,
        "questions": [{
            "question_id": "q-1",
            "subject_id": "sub-1",
            "chapter_id": "chap-1",
            "lesson_id": lesson_id,
            "chunk_ids": ["chunk-1"],
            "resource_ids": ["res-1"],
            "question_type": "multiple_choice",
            "question": "What is Python?",
            "correct_answer": "A programming language",
            "distractors": ["A snake", "A car"],
            "explanation": "Python is a programming language.",
            "difficulty": "beginner",
            "bloom_level": "remember",
            "created_at": created_at,
        }],
    })

    recommend_response = authed_client.post("/api/lessons/lesson-1/recommended-chunks", json={})
    fetch_response = authed_client.get("/api/lessons/lesson-1/recommended-chunks")
    generate_response = authed_client.post(
        "/api/lessons/lesson-1/generate-questions",
        json={"target_count": 2, "difficulty": "beginner"},
    )
    bank_response = authed_client.get("/api/lessons/lesson-1/questions")

    assert recommend_response.status_code == 200
    assert fetch_response.status_code == 200
    assert generate_response.status_code == 200
    assert bank_response.status_code == 200
    assert bank_response.json()["total"] == 1


def test_resources_endpoints_smoke(authed_client, monkeypatch):
    monkeypatch.setattr(resources, "get_resources_service", lambda **kwargs: {"items": [], "page": kwargs["page"], "size": kwargs["size"]})
    monkeypatch.setattr(resources, "search_resources_service", lambda **kwargs: {"items": [{"resource_id": "res-1"}], "query": kwargs["q"]})
    monkeypatch.setattr(resources, "add_resource_service", lambda resource, background_tasks, user_id: {
        "resource_id": "res-1",
        "job_id": "job-1",
        "status": "queued",
        "chunks_count": 0,
        "processing_time": 0.0,
        "duplicate": False,
    })
    monkeypatch.setattr(resources, "import_resources_service", lambda payload, background_tasks, user_id: {
        "total": len(payload.resources),
        "submitted": len(payload.resources),
        "items": [{
            "resource_id": "res-batch-1",
            "job_id": "job-batch-1",
            "status": "queued",
            "chunks_count": 0,
            "processing_time": 0.0,
            "duplicate": False,
        }],
    })
    monkeypatch.setattr(resources, "import_youtube_service", lambda *args, **kwargs: {
        "resource_id": "yt-1",
        "job_id": "job-yt-1",
        "status": "queued",
        "chunks_count": 0,
        "processing_time": 0.0,
        "duplicate": False,
    })
    monkeypatch.setattr(resources, "get_ingestion_job_status_service", lambda job_id: {
        "job_id": job_id,
        "resource_id": "res-1",
        "status": "completed",
        "chunks_count": 5,
        "processing_time": 0.5,
        "error": None,
        "resource_status": "ready",
    })
    monkeypatch.setattr(resources, "get_pdf_file_path", lambda resource_id: (_ for _ in ()).throw(ValueError("PDF not found")))

    list_response = authed_client.get("/api/resources/")
    search_response = authed_client.get("/api/resources/search", params={"q": "python"})
    add_response = authed_client.post(
        "/api/resources/",
        json={
            "title": "Intro Resource",
            "content": "abcdefghij resource content",
            "topic": "python",
            "level": "beginner",
        },
    )
    batch_response = authed_client.post(
        "/api/resources/import",
        json={"resources": [{"title": "Batch Resource", "content": "abcdefghij batch content", "topic": "python"}]},
    )
    youtube_response = authed_client.post(
        "/api/resources/import-youtube",
        json={"url": "https://youtube.com/watch?v=abc12345678", "title": "Video", "topic": "python"},
    )
    job_response = authed_client.get("/api/resources/jobs/job-1")
    pdf_response = authed_client.get("/api/resources/pdf/missing")
    invalid_pdf_response = authed_client.post(
        "/api/resources/import-pdf",
        data={"topic": "python", "level": "beginner"},
        files={"file": ("notes.txt", b"not-a-pdf", "text/plain")},
    )

    assert list_response.status_code == 200
    assert search_response.status_code == 200
    assert add_response.status_code == 202
    assert batch_response.status_code == 202
    assert youtube_response.status_code == 202
    assert job_response.status_code == 200
    assert pdf_response.status_code == 404
    assert invalid_pdf_response.status_code == 400


def test_learning_path_routes_smoke(authed_client, monkeypatch):
    fake_db = FakeDatabase({"learning_paths": []})
    monkeypatch.setattr(mongo_module, "get_db", lambda: fake_db)
    monkeypatch.setattr(learning_path, "generate_learning_path", lambda **kwargs: {
        "path_id": "path-1",
        "recommended_path": [{
            "concept_id": 1,
            "concept_name": "Variables",
            "difficulty": 1,
            "mode": "normal",
            "priority_score": 0.9,
            "resources": [],
        }],
        "curriculum": [{
            "chapter_id": "chap-1",
            "title": "Chapter 1",
            "lessons": [{
                "lesson_id": "lesson-1",
                "title": "Variables",
                "summary": "Learn variables",
                "resources": [],
            }],
        }],
        "curriculum_source": "fallback",
        "message": "generated",
    })

    generate_response = authed_client.post(
        "/api/learning-path/generate",
        json={"user_id": TEST_USER_ID, "goal": "Learn Python", "level": "beginner"},
    )
    history_response = authed_client.get("/api/learning-path/history")
    detail_response = authed_client.get("/api/learning-path/path-1")
    progress_response = authed_client.post(
        "/api/learning-path/lesson-progress",
        json={"path_id": "path-1", "lesson_id": "lesson-1", "status": "complete"},
    )

    assert generate_response.status_code == 200
    assert history_response.status_code == 200
    assert detail_response.status_code == 200
    assert progress_response.status_code == 200
    assert progress_response.json()["status"] == "complete"


def test_learning_paths_routes_smoke(authed_client, monkeypatch):
    timestamp = datetime.now(timezone.utc).isoformat()
    monkeypatch.setattr(learning_paths.learning_path_service, "generate_learning_path", lambda **kwargs: {
        "path_id": "hybrid-1",
        "goal": kwargs["goal"],
        "generated_at": timestamp,
        "chapters": [{
            "chapter_id": "chap-1",
            "title": "Python Foundations",
            "lessons": [{"lesson_id": "lesson-1", "title": "Variables"}],
        }],
        "curriculum_source": "fallback",
        "message": "ok",
    })
    monkeypatch.setattr(learning_paths.learning_path_service, "list_learning_paths", lambda user_id: [{
        "path_id": "hybrid-1",
        "subject_id": "python",
        "goal": "Learn Python",
        "level": "beginner",
        "generated_at": timestamp,
        "chapters": [{
            "chapter_id": "chap-1",
            "title": "Python Foundations",
            "lessons": [{"lesson_id": "lesson-1", "title": "Variables"}],
        }],
    }])
    monkeypatch.setattr(learning_paths.learning_path_service, "update_lesson_progress", lambda **kwargs: {
        "path_id": kwargs["path_id"],
        "lesson_id": kwargs["lesson_id"],
        "status": kwargs["status"],
        "updated_at": timestamp,
    })
    monkeypatch.setattr(learning_paths.learning_path_service, "get_learning_path", lambda **kwargs: {
        "path_id": kwargs["path_id"],
        "subject_id": "python",
        "goal": "Learn Python",
        "level": "beginner",
        "generated_at": timestamp,
        "chapters": [{
            "chapter_id": "chap-1",
            "title": "Python Foundations",
            "lessons": [{"lesson_id": "lesson-1", "title": "Variables"}],
        }],
        "curriculum_source": "fallback",
        "message": "ok",
    })

    generate_response = authed_client.post(
        "/api/learning-paths/generate",
        json={"subject_id": "python", "goal": "Learn Python", "level": "beginner"},
    )
    history_response = authed_client.get("/api/learning-paths/history")
    progress_response = authed_client.post(
        "/api/learning-paths/lesson-progress",
        json={"path_id": "hybrid-1", "lesson_id": "lesson-1", "status": "in_progress"},
    )
    detail_response = authed_client.get("/api/learning-paths/hybrid-1")

    assert generate_response.status_code == 200
    assert history_response.status_code == 200
    assert progress_response.status_code == 200
    assert detail_response.status_code == 200


def test_progress_routes_smoke(authed_client, monkeypatch):
    now = datetime.now(timezone.utc)
    fake_db = FakeDatabase({
        "users": [{"_id": ObjectId(TEST_USER_ID), "level": "beginner"}],
        "progress": [
            {"user_id": TEST_USER_ID, "concept_id": 1, "mastery": 0.85, "confidence": 0.7, "last_updated": now - timedelta(days=1)},
            {"user_id": TEST_USER_ID, "concept_id": 2, "mastery": 0.35, "confidence": 0.5, "last_updated": now - timedelta(days=9)},
        ],
    })
    monkeypatch.setattr(progress, "get_db", lambda: fake_db)
    monkeypatch.setattr(progress, "update_progress_with_confidence", lambda **kwargs: {
        "user_id": kwargs["user_id"],
        "concept_id": kwargs["concept_id"],
        "mastery": 0.75,
        "confidence": kwargs["confidence"],
        "total_attempts": 3,
        "status": "proficient",
    })
    monkeypatch.setattr(progress, "get_user_progress_summary", lambda user_id: {
        "total_concepts_started": 2,
        "total_concepts_completed": 1,
        "average_confidence": 0.6,
    })
    monkeypatch.setattr(progress, "get_progress", lambda user_id, concept_id: {
        "concept_id": concept_id,
        "mastery": 0.75,
        "confidence": 0.6,
        "success_rate": 0.8,
    })

    update_response = authed_client.post(
        "/api/progress/update",
        json={"user_id": TEST_USER_ID, "concept_id": 1, "mastery": 0.7, "confidence": 0.6},
    )
    summary_response = authed_client.get("/api/progress/summary")
    overview_response = authed_client.get("/api/progress/overview")
    confidence_response = authed_client.get("/api/progress/confidence")
    concept_response = authed_client.get("/api/progress/concept/1")

    assert update_response.status_code == 200
    assert summary_response.status_code == 200
    assert overview_response.status_code == 200
    assert confidence_response.status_code == 200
    assert concept_response.status_code == 200


def test_ask_routes_smoke(authed_client, monkeypatch):
    now = datetime.now(timezone.utc)
    fake_db = FakeDatabase({
        "ask_history": [],
        "progress": [{"user_id": TEST_USER_ID, "concept_id": 1, "mastery": 0.9}],
        "concepts": [
            {"concept_id": 1, "concept_name": "Variables", "difficulty": 1, "topic": "python"},
            {"concept_id": 2, "concept_name": "Loops", "difficulty": 2, "topic": "python"},
        ],
    })
    monkeypatch.setattr(ask, "get_db", lambda: fake_db)
    monkeypatch.setattr(ask.ai_tutor, "ask_ai", lambda **kwargs: {
        "success": True,
        "answer": {"answer_text": "A variable stores a value.", "confidence": 0.91},
        "learning_path": [{
            "concept_id": 2,
            "concept_name": "Loops",
            "difficulty": 2,
            "mode": "normal",
            "priority_score": 0.8,
            "resources": [],
        }],
        "concept_detected": {"concept_id": 1, "concept_name": "Variables"},
        "adaptive_info": {"mode": "normal"},
        "progress_updated": True,
    })
    monkeypatch.setattr(
        ask.ai_tutor,
        "detect_concepts_batch",
        lambda questions: [{"question": question, "concept_id": 1, "concept_name": "Variables"} for question in questions],
        raising=False,
    )
    monkeypatch.setattr(
        ask.ai_tutor,
        "generate_assessment_questions",
        lambda **kwargs: [{
            "question": "What is a variable?",
            "answer": "A named storage location",
            "explanation": "Variables store data.",
            "difficulty": "easy",
            "question_type": kwargs["question_type"],
            "concept": kwargs["concept"],
            "source_excerpt": "Variables store values.",
        }],
        raising=False,
    )
    monkeypatch.setattr(ask, "get_progress", lambda user_id, concept_id: {
        "mastery": 0.8,
        "confidence": 0.7,
        "success_rate": 0.9,
    })
    monkeypatch.setattr(ask, "adaptive_decision_summary", lambda mastery, confidence, success_rate: {
        "mode": "normal",
        "difficulty_boost": 0.0,
    })

    ask_response = authed_client.post(
        "/api/ask/",
        json={
            "user_id": TEST_USER_ID,
            "question": "What is a variable?",
            "goal": "Learn Python",
            "level": "beginner",
        },
    )
    adaptive_response = authed_client.get(
        "/api/ask/adaptive-status",
        params={"user_id": TEST_USER_ID, "concept_id": 1},
    )
    detect_response = authed_client.post(
        "/api/ask/detect-concepts",
        params=[("questions", "What is a variable?"), ("questions", "What is a loop?")],
    )
    recommend_response = authed_client.get("/api/ask/recommend-concepts", params={"user_id": TEST_USER_ID, "limit": 2})
    history_response = authed_client.get("/api/ask/history")
    history_id = history_response.json()["history"][0]["_id"]
    delete_response = authed_client.delete(f"/api/ask/history/{history_id}")
    assessment_response = authed_client.post(
        "/api/ask/generate-assessment",
        json={
            "user_id": TEST_USER_ID,
            "lesson_title": "Variables",
            "concept": "Variables",
            "difficulty": "easy",
            "question_type": "short_answer",
            "num_questions": 1,
            "chapter_content": "Variables are names that point to values in memory. " * 2,
        },
    )

    assert ask_response.status_code == 200
    assert adaptive_response.status_code == 200
    assert detect_response.status_code == 200
    assert recommend_response.status_code == 200
    assert history_response.status_code == 200
    assert delete_response.status_code == 200
    assert assessment_response.status_code == 200


def test_recommendations_and_concepts_routes_smoke(authed_client, monkeypatch):
    fake_db = FakeDatabase({
        "progress": [{"user_id": TEST_USER_INT_ID, "concept_id": 1, "mastery": 0.9}],
        "concepts": [
            {"concept_id": 1, "concept_name": "Variables", "difficulty": 1, "topic": "python"},
            {"concept_id": 2, "concept_name": "Loops", "difficulty": 2, "topic": "python"},
        ],
        "resources": [
            {"resource_id": 1, "concept_id": 2, "title": "Loops Intro", "source": "manual", "level": "beginner", "topic": "python", "pedagogy_type": "video"},
        ],
        "prerequisites": [{"from_concept_id": 1, "to_concept_id": 2}],
    })
    monkeypatch.setattr(recommendations, "db", fake_db)
    monkeypatch.setattr(concepts, "get_db", lambda: fake_db)

    recommendations_response = authed_client.get(
        "/api/recommendations/resources",
        params={"user_id": TEST_USER_INT_ID, "goal": "python", "level": "beginner", "limit": 5},
    )
    progress_response = authed_client.get(
        "/api/recommendations/progress",
        params={"user_id": TEST_USER_INT_ID, "goal": "python"},
    )
    concepts_response = authed_client.get("/api/concepts")
    concept_detail_response = authed_client.get("/api/concepts/2")

    assert recommendations_response.status_code == 200
    assert progress_response.status_code == 200
    assert concepts_response.status_code == 200
    assert concept_detail_response.status_code == 200
    assert concept_detail_response.json()["concept"]["prerequisites"] == [1]
