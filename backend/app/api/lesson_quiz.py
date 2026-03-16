from dataclasses import asdict
import logging

from fastapi import APIRouter, Depends, HTTPException, Query, status

from backend.app.api.auth import get_current_user
from backend.app.api.schemas import (
    CreateLessonQuizAttemptRequest,
    GenerateLessonQuestionBankRequest,
    LessonQuestionBankListResponse,
    LessonQuestionBankResponse,
    LessonQuestionGenerationDebugResponse,
    LessonQuestionBankSummaryResponse,
    LessonQuizAttemptResponse,
    SubmitLessonQuizRequest,
    SubmitLessonQuizResponse,
)
from backend.app.services.lesson_quiz.bank_service import (
    create_lesson_quiz_attempt,
    generate_and_store_questions,
    get_lesson_question_bank,
    list_lesson_question_banks,
    submit_lesson_quiz,
)
from backend.app.services.question_generation.generator import debug_lesson_question_generation

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Lesson Quiz"])


def _serialize_question_bank(bank) -> LessonQuestionBankResponse:
    payload = asdict(bank)
    for question in payload.get("questions", []):
        question.pop("answer", None)
        question.pop("correct_option", None)
    return LessonQuestionBankResponse(**payload)


@router.get(
    "/lesson-question-banks",
    response_model=LessonQuestionBankListResponse,
    status_code=status.HTTP_200_OK,
)
def list_question_banks(
    limit: int = Query(default=50, ge=1, le=200),
    current_user: dict = Depends(get_current_user),
):
    _ = current_user

    try:
        banks = list_lesson_question_banks(limit=limit)
        return LessonQuestionBankListResponse(
            total=len(banks),
            items=[
                LessonQuestionBankSummaryResponse(
                    lesson_id=bank.lesson_id,
                    chapter_id=bank.chapter_id,
                    concept_list=bank.concept_list,
                    total_questions=bank.total_questions,
                    created_at=bank.created_at,
                    updated_at=bank.updated_at,
                )
                for bank in banks
            ],
        )
    except Exception as exc:
        logger.exception("Error listing lesson question banks: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not list lesson question banks",
        ) from exc


@router.get(
    "/lesson-question-bank/{lesson_id}",
    response_model=LessonQuestionBankResponse,
    status_code=status.HTTP_200_OK,
)
def get_question_bank(
    lesson_id: str,
    current_user: dict = Depends(get_current_user),
):
    _ = current_user

    try:
        bank = get_lesson_question_bank(lesson_id)
        return _serialize_question_bank(bank)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Error fetching lesson question bank: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not fetch lesson question bank",
        ) from exc


@router.post(
    "/lesson-question-bank/generate",
    response_model=LessonQuestionBankResponse,
    status_code=status.HTTP_200_OK,
)
def generate_lesson_question_bank(
    payload: GenerateLessonQuestionBankRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Generate and store the 20-question bank for a lesson.
    """
    _ = current_user

    try:
        bank = generate_and_store_questions(payload.lesson_id)
        return _serialize_question_bank(bank)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Error generating lesson question bank: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not generate lesson question bank",
        ) from exc


@router.get(
    "/lesson-question-bank/debug/{lesson_id}",
    response_model=LessonQuestionGenerationDebugResponse,
    status_code=status.HTTP_200_OK,
)
def debug_question_generation(
    lesson_id: str,
    current_user: dict = Depends(get_current_user),
):
    _ = current_user

    try:
        debug_payload = debug_lesson_question_generation(lesson_id)
        return LessonQuestionGenerationDebugResponse(**debug_payload)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Error debugging lesson question generation: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not debug lesson question generation",
        ) from exc


@router.post(
    "/lesson-quiz/attempt",
    response_model=LessonQuizAttemptResponse,
    status_code=status.HTTP_200_OK,
)
def create_attempt(
    payload: CreateLessonQuizAttemptRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Create a new quiz attempt by randomly selecting 10 questions from the stored lesson bank.
    """
    user_id = str(current_user.get("_id", ""))

    try:
        result = create_lesson_quiz_attempt(user_id=user_id, lesson_id=payload.lesson_id)
        return LessonQuizAttemptResponse(**result)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.exception("Error creating lesson quiz attempt: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not create lesson quiz attempt",
        ) from exc


@router.post(
    "/lesson-quiz/submit",
    response_model=SubmitLessonQuizResponse,
    status_code=status.HTTP_200_OK,
)
@router.post(
    "/quiz/submit",
    response_model=SubmitLessonQuizResponse,
    status_code=status.HTTP_200_OK,
)
def submit_attempt(
    payload: SubmitLessonQuizRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    Submit answers for an attempt, calculate score, and determine pass/fail.
    """
    user_id = str(current_user.get("_id", ""))

    try:
        result = submit_lesson_quiz(
            attempt_id=payload.attempt_id,
            user_answers=payload.user_answers,
            user_id=user_id,
        )
        return SubmitLessonQuizResponse(**result)
    except ValueError as exc:
        message = str(exc)
        status_code = status.HTTP_404_NOT_FOUND if "not found" in message.lower() else status.HTTP_400_BAD_REQUEST
        raise HTTPException(
            status_code=status_code,
            detail=message,
        ) from exc
    except Exception as exc:
        logger.exception("Error submitting lesson quiz: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Could not submit lesson quiz",
        ) from exc
