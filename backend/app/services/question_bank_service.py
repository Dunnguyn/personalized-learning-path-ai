from __future__ import annotations

import logging
import os
import random
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Mapping, Optional

from backend.app.database.mongo import get_db
from backend.app.services.confidence_service import (
    calculate_confidence_score,
    record_confidence_event,
    upsert_lesson_confidence_progress,
)
from backend.app.services.question_generator import QuestionGenerator

logger = logging.getLogger(__name__)


# =====================================================
# ANALYSIS
# =====================================================
# - Each lesson needs a pre-generated bank of 20 questions.
# - Questions must come from chapter concepts + knowledge graph + templates.
# - When a learner starts a quiz, select 10 random questions from the 20 stored ones.
# - Each submission is recorded as a separate attempt.
# - If a learner does not pass, they can create another attempt and receive another random set.
# - This service focuses only on question bank, attempt creation, and grading.


# =====================================================
# CONFIG
# =====================================================
QUESTION_BANK_SIZE = int(os.getenv("LESSON_QUESTION_BANK_SIZE", "20"))
QUIZ_ATTEMPT_SIZE = int(os.getenv("LESSON_QUIZ_ATTEMPT_SIZE", "10"))
PASS_THRESHOLD_CORRECT_COUNT = os.getenv("PASS_THRESHOLD_CORRECT_COUNT")
PASS_THRESHOLD_SCORE_PERCENT = float(os.getenv("PASS_THRESHOLD_SCORE_PERCENT", "80"))


# =====================================================
# SCHEMA / DATA MODEL
# =====================================================
@dataclass
class Question:
    """
    Stored question inside the lesson question bank.

    Required business fields:
    - question_id
    - lesson_id
    - concept
    - relation_type
    - question_text
    - answer
    - template_id

    Extra fields (`related_concepts`, `options`, `correct_option`) help quiz delivery.
    """

    question_id: str
    lesson_id: str
    concept: str
    relation_type: str
    question_text: str
    answer: str
    template_id: str
    related_concepts: List[str] = field(default_factory=list)
    options: List[Dict[str, str]] = field(default_factory=list)
    correct_option: str = "A"


@dataclass
class LessonQuestionBank:
    lesson_id: str
    chapter_id: str
    concept_list: List[Dict[str, str]]
    total_questions: int
    questions: List[Question]
    created_at: datetime
    updated_at: datetime


@dataclass
class UserLessonAttempt:
    attempt_id: str
    user_id: str
    lesson_id: str
    attempt_number: int
    selected_question_ids: List[str]
    score: float
    correct_count: int
    is_passed: bool
    confidence_score: float
    created_at: datetime
    submitted_at: Optional[datetime] = None
    user_answers: Dict[str, str] = field(default_factory=dict)


# =====================================================
# PSEUDOCODE
# =====================================================
# generate_and_store_questions(lesson_id):
# 1. Resolve lesson context -> chapter_id, concept_list.
# 2. Call QuestionGenerator.generate_questions(chapter_id, target_count * k).
# 3. Convert generated items to question bank questions.
# 4. Remove duplicates and distribute across lesson concepts.
# 5. Keep up to 20 high-quality questions.
# 6. Store/replace lesson question bank in DB.
#
# create_lesson_quiz_attempt(user_id, lesson_id):
# 1. Load question bank for lesson_id.
# 2. Validate that bank has enough questions.
# 3. Randomly choose 10 question IDs from the stored 20 questions.
# 4. Create new attempt document.
# 5. Return attempt metadata + selected questions without answers.
#
# submit_lesson_quiz(attempt_id, user_answers):
# 1. Load attempt and the lesson question bank.
# 2. For each selected question, compare learner answer with correct answer.
# 3. Count correct answers and compute score.
# 4. Evaluate pass threshold.
# 5. Update attempt with score, correct_count, is_passed, submitted_at.
# 6. Return grading result.


# =====================================================
# HELPERS
# =====================================================
def _get_pass_threshold_count(total_questions: int) -> int:
    if PASS_THRESHOLD_CORRECT_COUNT:
        return max(1, min(total_questions, int(PASS_THRESHOLD_CORRECT_COUNT)))
    return max(1, min(total_questions, int(total_questions * (PASS_THRESHOLD_SCORE_PERCENT / 100.0) + 0.9999)))


def _sanitize_question_for_delivery(question: Question) -> Dict:
    payload = asdict(question)
    payload.pop("answer", None)
    payload.pop("correct_option", None)
    return payload


def _relation_answer_text(item: Dict) -> str:
    concept = item.get("concept", "")
    related = item.get("related_concepts", []) or [concept]
    relation_type = item.get("relation_type", "definition")

    if relation_type == "prerequisite" and len(related) >= 2:
        return f"{related[0]} la kien thuc can hoc truoc de hieu {related[1]}."
    if relation_type == "used_in" and len(related) >= 2:
        return f"{related[0]} duoc ung dung trong {related[1]}."
    if relation_type == "part_of" and len(related) >= 2:
        return f"{related[0]} la mot thanh phan cua {related[1]}."
    if relation_type == "related_to" and len(related) >= 2:
        return f"{related[0]} co moi lien he truc tiep voi {related[1]}."
    if relation_type == "comparison" and len(related) >= 2:
        return f"{related[0]} va {related[1]} khac nhau ve vai tro hoac cach ap dung."
    return f"{concept} la mot khai niem cot loi cua bai hoc."


def _relation_distractors(item: Dict) -> List[str]:
    concept = item.get("concept", "")
    related = item.get("related_concepts", []) or [concept]
    other = related[1] if len(related) > 1 else concept
    relation_type = item.get("relation_type", "definition")

    mapping = {
        "prerequisite": [
            f"{concept} khong anh huong den viec hoc {other}.",
            f"{other} can hoc truoc ma khong can biet {concept}.",
            f"{concept} chi la mot vi du phu, khong phai kien thuc nen tang.",
        ],
        "used_in": [
            f"{concept} khong duoc su dung trong {other}.",
            f"{other} khong can den {concept} de ap dung.",
            f"{concept} va {other} thuoc hai chu de tach biet.",
        ],
        "part_of": [
            f"{concept} khong nam trong cau truc cua {other}.",
            f"{other} co the hieu day du ma khong can {concept}.",
            f"{concept} la mot chu de ngoai le, khong phai thanh phan.",
        ],
        "related_to": [
            f"{concept} khong lien quan den {other}.",
            f"{concept} va {other} khong co diem chung trong bai hoc.",
            f"{other} thuoc mot noi dung khac, khong can xet {concept}.",
        ],
        "comparison": [
            f"{concept} va {other} hoan toan giong nhau, khong can phan biet.",
            f"{concept} va {other} khong the dat canh de so sanh.",
            f"Chi can hoc mot trong hai vi {concept} va {other} la mot.",
        ],
    }
    return mapping.get(
        relation_type,
        [
            f"{concept} khong xuat hien trong bai hoc nay.",
            f"{concept} chi can hoc thuoc ten goi, khong can hieu noi dung.",
            f"{concept} thuoc mot chu de khac, khong lien quan bai hoc.",
        ],
    )


def _build_mcq_payload(item: Dict, lesson_id: str, template_index: int, rng: random.Random) -> Question:
    answer_text = _relation_answer_text(item)
    distractors = _relation_distractors(item)
    option_payload = [
        {"is_correct": True, "text": answer_text},
        {"is_correct": False, "text": distractors[0]},
        {"is_correct": False, "text": distractors[1]},
        {"is_correct": False, "text": distractors[2]},
    ]
    rng.shuffle(option_payload)

    options: List[Dict[str, str]] = []
    correct_option = "A"
    for option_key, payload in zip(["A", "B", "C", "D"], option_payload):
        options.append({"key": option_key, "text": payload["text"]})
        if payload["is_correct"]:
            correct_option = option_key

    return Question(
        question_id=uuid.uuid4().hex,
        lesson_id=lesson_id,
        concept=str(item.get("concept", "")),
        relation_type=str(item.get("relation_type", "definition")),
        question_text=str(item.get("question", "")).strip(),
        answer=answer_text,
        template_id=f"{item.get('relation_type', 'definition')}_{template_index}",
        related_concepts=[str(value) for value in item.get("related_concepts", [])],
        options=options,
        correct_option=correct_option,
    )


def _extract_chapter_concepts(chapter: Dict) -> List[Dict[str, str]]:
    concepts: List[Dict[str, str]] = []
    seen = set()

    for raw_concept in chapter.get("concepts", []) or []:
        concept_id = raw_concept.get("id") or raw_concept.get("concept_id") or raw_concept.get("name")
        concept_name = raw_concept.get("name") or raw_concept.get("concept_name")
        if not concept_id or not concept_name:
            continue
        key = str(concept_id)
        if key in seen:
            continue
        seen.add(key)
        concepts.append({"id": str(concept_id), "name": str(concept_name)})

    for lesson in chapter.get("lessons", []) or []:
        concept_id = lesson.get("concept_id") or lesson.get("title")
        concept_name = lesson.get("concept_name") or lesson.get("title")
        if not concept_id or not concept_name:
            continue
        key = str(concept_id)
        if key in seen:
            continue
        seen.add(key)
        concepts.append({"id": str(concept_id), "name": str(concept_name)})

    return concepts


def _resolve_lesson_context(lesson_id: str) -> Dict:
    db = get_db()

    lessons_collection = getattr(db, "lessons", None)
    if lessons_collection is not None:
        lesson = lessons_collection.find_one({"lesson_id": lesson_id}, {"_id": 0})
        if lesson:
            chapter_id = lesson.get("chapter_id")
            concept_list = lesson.get("concept_list", []) or []
            return {
                "lesson_id": lesson_id,
                "lesson_title": lesson.get("title") or lesson.get("lesson_name") or "Lesson",
                "chapter_id": str(chapter_id),
                "concept_list": concept_list,
            }

    path = db.learning_paths.find_one({"curriculum.lessons.lesson_id": lesson_id}, {"curriculum": 1, "_id": 0})
    if not path:
        raise ValueError(f"Lesson not found: {lesson_id}")

    for chapter in path.get("curriculum", []) or []:
        for lesson in chapter.get("lessons", []) or []:
            if lesson.get("lesson_id") != lesson_id:
                continue

            concept_list = lesson.get("concept_list") or _extract_chapter_concepts(chapter)
            return {
                "lesson_id": lesson_id,
                "lesson_title": lesson.get("title") or "Lesson",
                "chapter_id": str(chapter.get("chapter_id") or chapter.get("id") or chapter.get("title")),
                "concept_list": concept_list,
            }

    raise ValueError(f"Lesson not found: {lesson_id}")


def _compose_balanced_question_set(candidates: Iterable[Question], target_size: int) -> List[Question]:
    concept_buckets: Dict[str, List[Question]] = {}
    seen_questions = set()

    for item in candidates:
        key = item.question_text.strip().lower()
        if not key or key in seen_questions:
            continue
        seen_questions.add(key)
        concept_buckets.setdefault(item.concept.lower() or "unknown", []).append(item)

    ordered: List[Question] = []
    while len(ordered) < target_size:
        added = False
        for concept_name in sorted(concept_buckets.keys()):
            bucket = concept_buckets[concept_name]
            if not bucket:
                continue
            ordered.append(bucket.pop(0))
            added = True
            if len(ordered) >= target_size:
                break
        if not added:
            break

    return ordered


def _load_lesson_question_bank(lesson_id: str) -> Optional[LessonQuestionBank]:
    db = get_db()
    document = db.lesson_question_banks.find_one({"lesson_id": lesson_id}, {"_id": 0})
    if not document:
        return None

    return LessonQuestionBank(
        lesson_id=document["lesson_id"],
        chapter_id=document["chapter_id"],
        concept_list=document.get("concept_list", []),
        total_questions=int(document.get("total_questions", 0)),
        questions=[Question(**item) for item in document.get("questions", [])],
        created_at=document.get("created_at", datetime.utcnow()),
        updated_at=document.get("updated_at", datetime.utcnow()),
    )


def get_lesson_question_bank(lesson_id: str) -> LessonQuestionBank:
    bank = _load_lesson_question_bank(lesson_id)
    if bank is None:
        raise ValueError(f"Question bank not found for lesson_id={lesson_id}")
    return bank


def list_lesson_question_banks(limit: int = 50) -> List[LessonQuestionBank]:
    db = get_db()
    documents = db.lesson_question_banks.find({}, {"_id": 0}).sort("updated_at", -1).limit(max(1, limit))
    banks: List[LessonQuestionBank] = []
    for document in documents:
        banks.append(
            LessonQuestionBank(
                lesson_id=document["lesson_id"],
                chapter_id=document["chapter_id"],
                concept_list=document.get("concept_list", []),
                total_questions=int(document.get("total_questions", 0)),
                questions=[Question(**item) for item in document.get("questions", [])],
                created_at=document.get("created_at", datetime.utcnow()),
                updated_at=document.get("updated_at", datetime.utcnow()),
            )
        )
    return banks


def _mark_lesson_complete_for_user(user_id: str, lesson_id: str) -> None:
    """
    Best-effort progress update when a learner passes the lesson quiz.
    """
    if not user_id or not lesson_id:
        return

    db = get_db()
    db.learning_paths.update_many(
        {
            "user_id": user_id,
            "curriculum.lessons.lesson_id": lesson_id,
        },
        {
            "$set": {
                f"lesson_progress.{lesson_id}": "complete",
                "updated_at": datetime.utcnow(),
            }
        },
    )


# =====================================================
# MAIN FUNCTIONS
# =====================================================
def generate_and_store_questions(lesson_id: str) -> LessonQuestionBank:
    """
    Generate 20 rule-based + knowledge-graph questions and store them as a lesson bank.
    """
    context = _resolve_lesson_context(lesson_id)
    chapter_id = context["chapter_id"]
    concept_list = context.get("concept_list", [])

    generator = QuestionGenerator()
    raw_questions = generator.generate_questions(
        chapter_id=chapter_id,
        num_questions=max(QUESTION_BANK_SIZE * 4, QUESTION_BANK_SIZE)
    )
    if not raw_questions:
        raise ValueError(f"Could not generate questions for lesson_id={lesson_id}")

    rng = random.Random(f"bank:{lesson_id}:{chapter_id}")
    candidates = [
        _build_mcq_payload(item, lesson_id=lesson_id, template_index=index, rng=rng)
        for index, item in enumerate(raw_questions, start=1)
        if item.get("question")
    ]
    selected_questions = _compose_balanced_question_set(candidates, QUESTION_BANK_SIZE)
    if len(selected_questions) < QUESTION_BANK_SIZE:
        raise ValueError(
            f"Question bank generation produced only {len(selected_questions)}/{QUESTION_BANK_SIZE} questions for lesson_id={lesson_id}"
        )

    now = datetime.utcnow()
    bank = LessonQuestionBank(
        lesson_id=lesson_id,
        chapter_id=chapter_id,
        concept_list=concept_list,
        total_questions=len(selected_questions),
        questions=selected_questions,
        created_at=now,
        updated_at=now,
    )

    db = get_db()
    db.lesson_question_banks.update_one(
        {"lesson_id": lesson_id},
        {
            "$set": {
                "lesson_id": bank.lesson_id,
                "chapter_id": bank.chapter_id,
                "concept_list": bank.concept_list,
                "total_questions": bank.total_questions,
                "questions": [asdict(question) for question in bank.questions],
                "updated_at": bank.updated_at,
            },
            "$setOnInsert": {"created_at": bank.created_at},
        },
        upsert=True,
    )

    logger.info("Stored lesson question bank: lesson_id=%s, total_questions=%s", lesson_id, bank.total_questions)
    return bank


def create_lesson_quiz_attempt(user_id: str, lesson_id: str) -> Dict:
    """
    Create a new attempt by selecting 10 random questions from the stored bank.
    """
    if not user_id:
        raise ValueError("user_id cannot be empty")

    bank = _load_lesson_question_bank(lesson_id)
    if bank is None:
        bank = generate_and_store_questions(lesson_id)

    if bank.total_questions < QUIZ_ATTEMPT_SIZE:
        raise ValueError(
            f"Lesson question bank has only {bank.total_questions} questions, fewer than required attempt size {QUIZ_ATTEMPT_SIZE}"
        )

    rng = random.Random(f"attempt:{user_id}:{lesson_id}:{uuid.uuid4().hex}")
    selected_questions = rng.sample(bank.questions, QUIZ_ATTEMPT_SIZE)
    selected_ids = [question.question_id for question in selected_questions]
    db = get_db()
    attempt_number = db.lesson_quiz_attempts.count_documents({
        "user_id": user_id,
        "lesson_id": lesson_id,
    }) + 1

    attempt = UserLessonAttempt(
        attempt_id=uuid.uuid4().hex,
        user_id=user_id,
        lesson_id=lesson_id,
        attempt_number=attempt_number,
        selected_question_ids=selected_ids,
        score=0.0,
        correct_count=0,
        is_passed=False,
        confidence_score=0.0,
        created_at=datetime.utcnow(),
    )

    db.lesson_quiz_attempts.insert_one({
        "attempt_id": attempt.attempt_id,
        "user_id": attempt.user_id,
        "lesson_id": attempt.lesson_id,
        "attempt_number": attempt.attempt_number,
        "selected_question_ids": attempt.selected_question_ids,
        "score": attempt.score,
        "correct_count": attempt.correct_count,
        "is_passed": attempt.is_passed,
        "confidence_score": attempt.confidence_score,
        "created_at": attempt.created_at,
        "submitted_at": attempt.submitted_at,
        "user_answers": attempt.user_answers,
    })

    return {
        "attempt_id": attempt.attempt_id,
        "user_id": attempt.user_id,
        "lesson_id": attempt.lesson_id,
        "attempt_number": attempt.attempt_number,
        "selected_question_ids": selected_ids,
        "pass_threshold_count": _get_pass_threshold_count(QUIZ_ATTEMPT_SIZE),
        "questions": [_sanitize_question_for_delivery(question) for question in selected_questions],
        "created_at": attempt.created_at,
    }


def submit_lesson_quiz(
    attempt_id: str,
    user_answers: Mapping[str, str],
    user_id: Optional[str] = None,
) -> Dict:
    """
    Grade an attempt and return score + pass/fail result.
    """
    if not attempt_id:
        raise ValueError("attempt_id cannot be empty")

    db = get_db()
    attempt = db.lesson_quiz_attempts.find_one({"attempt_id": attempt_id}, {"_id": 0})
    if not attempt:
        raise ValueError(f"Attempt not found: {attempt_id}")
    if user_id and str(attempt.get("user_id", "")) != str(user_id):
        raise ValueError(f"Attempt does not belong to user: {attempt_id}")

    lesson_id = str(attempt["lesson_id"])
    bank = _load_lesson_question_bank(lesson_id)
    if bank is None:
        raise ValueError(f"Question bank not found for lesson_id={lesson_id}")

    question_map = {question.question_id: question for question in bank.questions}
    selected_question_ids = [str(question_id) for question_id in attempt.get("selected_question_ids", [])]

    correct_count = 0
    results = []
    for question_id in selected_question_ids:
        question = question_map.get(question_id)
        if question is None:
            continue

        selected_answer = str(user_answers.get(question_id, "")).strip()
        is_correct = selected_answer.upper() == question.correct_option.upper()
        if is_correct:
            correct_count += 1

        results.append({
            "question_id": question.question_id,
            "selected_answer": selected_answer,
            "correct_option": question.correct_option,
            "is_correct": is_correct,
            "answer": question.answer,
        })

    total_questions = len(selected_question_ids)
    score = round((correct_count / max(total_questions, 1)) * 100, 2)
    threshold_count = _get_pass_threshold_count(total_questions)
    is_passed = correct_count >= threshold_count or score >= PASS_THRESHOLD_SCORE_PERCENT
    attempt_number = int(attempt.get("attempt_number", 1) or 1)
    confidence_score = calculate_confidence_score(correct_count, total_questions, attempt_number)
    submitted_at = datetime.utcnow()

    db.lesson_quiz_attempts.update_one(
        {"attempt_id": attempt_id},
        {
            "$set": {
                "score": score,
                "correct_count": correct_count,
                "is_passed": is_passed,
                "confidence_score": confidence_score,
                "total_questions": total_questions,
                "submitted_at": submitted_at,
                "user_answers": dict(user_answers),
            }
        }
    )

    upsert_lesson_confidence_progress(
        user_id=str(attempt.get("user_id", "")),
        lesson_id=lesson_id,
        attempt_id=attempt_id,
        attempt_number=attempt_number,
        correct_count=correct_count,
        total_questions=total_questions,
        score=score,
        confidence_score=confidence_score,
        is_passed=is_passed,
    )
    record_confidence_event(
        user_id=str(attempt.get("user_id", "")),
        lesson_id=lesson_id,
        attempt_id=attempt_id,
        confidence_score=confidence_score,
        score=score,
        correct_count=correct_count,
        total_questions=total_questions,
        attempt_number=attempt_number,
        is_passed=is_passed,
    )

    if is_passed:
        _mark_lesson_complete_for_user(str(attempt.get("user_id", "")), lesson_id)

    return {
        "attempt_id": attempt_id,
        "lesson_id": lesson_id,
        "score": score,
        "correct_count": correct_count,
        "total_questions": total_questions,
        "attempt_number": attempt_number,
        "confidence_score": confidence_score,
        "pass_threshold_count": threshold_count,
        "is_passed": is_passed,
        "submitted_at": submitted_at,
        "results": results,
        "can_retry": not is_passed,
    }


# =====================================================
# SAMPLE DATA
# =====================================================
SAMPLE_QUESTION = {
    "question_id": "q_001",
    "lesson_id": "lesson_python_intro",
    "concept": "Python Basics",
    "relation_type": "definition",
    "question_text": "Python Basics la gi?",
    "answer": "Python Basics la nen tang de hoc cac khai niem Python tiep theo.",
    "template_id": "definition_1",
}

SAMPLE_ATTEMPT = {
    "attempt_id": "attempt_001",
    "user_id": "user_123",
    "lesson_id": "lesson_python_intro",
    "selected_question_ids": ["q_001", "q_002"],
    "score": 80.0,
    "correct_count": 8,
    "is_passed": True,
    "created_at": datetime.utcnow(),
}
