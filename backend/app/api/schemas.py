from pydantic import BaseModel, EmailStr, Field, ConfigDict, model_validator
from typing import List, Optional, Literal
from datetime import datetime
from enum import Enum


class LevelEnum(str, Enum):
    beginner = "beginner"
    intermediate = "intermediate"
    advanced = "advanced"


class SourceEnum(str, Enum):
    pdf = "pdf"
    youtube = "youtube"
    web = "web"


class PedagogyEnum(str, Enum):
    video = "video"
    text = "text"
    quiz = "quiz"


# =========================
# USERS
# =========================
class UserCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=100)
    level: LevelEnum = LevelEnum.beginner
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "name": "John Doe",
            "email": "john@example.com",
            "password": "securepassword123",
            "level": "beginner"
        }
    })


class UserResponse(BaseModel):
    """User response with MongoDB ObjectId as string."""
    user_id: str = Field(..., description="MongoDB ObjectId as string")
    name: str
    email: EmailStr
    level: LevelEnum
    created_at: datetime
    
    model_config = ConfigDict(from_attributes=True)


# =========================
# LEARNER PROFILE
# =========================
class LearnerProfileCreate(BaseModel):
    user_id: str = Field(..., description="MongoDB ObjectId")
    learning_goal: str = Field(..., min_length=10, max_length=500)
    preferred_style: Optional[str] = None
    time_constraint: Optional[str] = None


# =========================
# COURSE
# =========================
class CourseCreate(BaseModel):
    course_name: str = Field(..., min_length=3, max_length=200)
    description: Optional[str] = None


class CourseResponse(CourseCreate):
    course_id: str = Field(..., description="MongoDB ObjectId")


# =========================
# CONCEPT
# =========================
class ConceptCreate(BaseModel):
    course_id: Optional[str] = None  # Optional, MongoDB ObjectId
    concept_name: str = Field(..., min_length=3, max_length=200)
    topic: str = Field(..., min_length=2, max_length=200)
    difficulty: int = Field(..., ge=1, le=10)


class ConceptResponse(ConceptCreate):
    concept_id: int = Field(..., description="Integer ID for concepts (can be auto-increment or ObjectId)")


# =========================
# PREREQUISITE (GRAPH)
# =========================
class PrerequisiteCreate(BaseModel):
    from_concept_id: int
    to_concept_id: int


# =========================
# RESOURCE
# =========================
class ResourceCreate(BaseModel):
    title: str = Field(..., min_length=3, max_length=500)
    content: str = Field(..., min_length=10)
    source: SourceEnum
    topic: str = Field(..., min_length=2, max_length=200)
    level: LevelEnum
    concept_id: int = Field(..., ge=1)
    url: Optional[str] = None


class ResourceResponse(ResourceCreate):
    resource_id: str = Field(..., description="MongoDB ObjectId")
    created_at: datetime


class ResourceMetadataCreate(BaseModel):
    pedagogy_type: Optional[PedagogyEnum] = None
    bloom_level: Optional[str] = None


# =========================
# RESOURCE IMPORT (BATCH)
# =========================
class ResourceImport(BaseModel):
    title: str = Field(..., min_length=3, max_length=500)
    content: str = Field(..., min_length=10)
    source: SourceEnum
    url: Optional[str] = None
    concept_id: int = Field(..., ge=1)
    pedagogy_type: Optional[PedagogyEnum] = None
    bloom_level: Optional[str] = None


class ResourceImportRequest(BaseModel):
    resources: List[ResourceImport] = Field(..., min_items=1, max_items=1000)


# =========================
# YOUTUBE IMPORT
# =========================
class YouTubeImportRequest(BaseModel):
    url: str = Field(..., min_length=10, max_length=500, description="YouTube video URL")
    title: str = Field(..., min_length=3, max_length=500, description="Resource title")
    topic: str = Field(..., min_length=2, max_length=200, description="Learning topic")
    level: LevelEnum = Field(default=LevelEnum.beginner, description="Difficulty level")
    concept_id: Optional[int] = Field(None, ge=1, description="Associated concept ID")
    
    model_config = ConfigDict(json_schema_extra={
        "example": {
            "url": "https://www.youtube.com/watch?v=rfscVS0vtbw",
            "title": "Learn Python - Full Course for Beginners",
            "topic": "python",
            "level": "beginner",
            "concept_id": 1
        }
    })


# =========================
# PROGRESS
# =========================
class ProgressUpdate(BaseModel):
    """Update learner progress on a concept."""
    user_id: str = Field(..., description="MongoDB ObjectId as string")
    concept_id: int = Field(..., ge=1)
    mastery: float = Field(..., ge=0, le=1)
    confidence: float = Field(..., ge=0, le=1)
    total_attempts: int = Field(default=1, ge=1)


class ProgressUpdateResponse(BaseModel):
    user_id: str
    concept_id: int
    mastery: float
    confidence: float
    total_attempts: int
    status: str  # "not_started" | "in_progress" | "proficient" | "complete"
    updated_at: datetime


# =========================
# LEARNING PATH
# =========================
class LearningPathItemResponse(BaseModel):
    concept_id: int
    concept_name: str
    difficulty: int
    bloom_level: Optional[str] = None
    mode: str
    priority_score: float
    resources: list = Field(default_factory=list)


class LessonAssessmentQuestionResponse(BaseModel):
    question_id: str
    question: str
    answer: str
    explanation: str
    difficulty: str
    concept: str
    options: List[dict] = Field(default_factory=list)
    correct_option: str = "A"


class LessonAssessmentResponse(BaseModel):
    required_questions: int = 10
    attempted_questions: int = 0
    completed: bool = False
    generation: int = 0
    correct_answers: int = 0
    min_correct_required: int = 7
    passed: bool = False
    score_percent: float = 0.0
    questions: List[LessonAssessmentQuestionResponse] = Field(default_factory=list)
    question_results: List[dict] = Field(default_factory=list)


class LessonResponse(BaseModel):
    lesson_id: str
    title: str
    summary: str
    resources: list = Field(default_factory=list)
    status: Optional[str] = None
    assessment: Optional[LessonAssessmentResponse] = None


class ChapterResponse(BaseModel):
    chapter_id: Optional[str] = None
    title: str
    lessons: List[LessonResponse]


class LearningPathResponse(BaseModel):
    path_id: str = Field(..., description="UUID")
    user_id: str = Field(..., description="MongoDB ObjectId")
    goal: str
    level: LevelEnum
    generated_at: datetime
    recommended_path: List[LearningPathItemResponse]
    curriculum: Optional[List[ChapterResponse]] = None
    curriculum_source: str = "fallback"
    curriculum_notice: Optional[str] = None
    message: str = ""


class LessonProgressUpdate(BaseModel):
    path_id: str = Field(..., description="Learning path UUID")
    lesson_id: str = Field(..., description="Lesson identifier")
    status: Literal["not_started", "in_progress", "complete"]
    answered_questions: Optional[List[str]] = None
    restart_assessment: bool = False


class LessonProgressResponse(BaseModel):
    path_id: str
    lesson_id: str
    status: str
    updated_at: datetime
    assessment_result: Optional[dict] = None


# =========================
# LESSON QUESTION BANK / QUIZ
# =========================
class QuestionBankOptionResponse(BaseModel):
    key: str
    text: str


class QuestionBankQuestionResponse(BaseModel):
    question_id: str
    lesson_id: str
    concept: str
    relation_type: str
    bloom_level: str = "remember"
    question_text: str
    answer: str
    template_id: str
    difficulty: int = 1
    related_concepts: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    source_excerpt: str = ""
    source_chunk_id: Optional[str] = None
    options: List[QuestionBankOptionResponse] = Field(default_factory=list)
    correct_option: str = "A"


class PublicQuestionBankQuestionResponse(BaseModel):
    question_id: str
    lesson_id: str
    concept: str
    relation_type: str
    bloom_level: str = "remember"
    question_text: str
    template_id: str
    difficulty: int = 1
    related_concepts: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    source_excerpt: str = ""
    source_chunk_id: Optional[str] = None
    options: List[QuestionBankOptionResponse] = Field(default_factory=list)


class GenerateLessonQuestionBankRequest(BaseModel):
    lesson_id: str = Field(..., min_length=1, description="Lesson identifier")


class LessonQuestionBankResponse(BaseModel):
    lesson_id: str
    chapter_id: str
    concept_list: List[dict] = Field(default_factory=list)
    total_questions: int
    questions: List[PublicQuestionBankQuestionResponse] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime


class LessonQuestionBankSummaryResponse(BaseModel):
    lesson_id: str
    chapter_id: str
    concept_list: List[dict] = Field(default_factory=list)
    total_questions: int
    created_at: datetime
    updated_at: datetime


class LessonQuestionBankListResponse(BaseModel):
    total: int
    items: List[LessonQuestionBankSummaryResponse] = Field(default_factory=list)


class LessonQuestionGenerationConceptResponse(BaseModel):
    concept_id: str
    name: str
    normalized_name: str
    concept_type: str
    keywords: List[str] = Field(default_factory=list)
    difficulty: Optional[int] = None


class LessonQuestionGenerationRelationResponse(BaseModel):
    source_concept: str
    target_concept: str
    relation_type: str


class LessonQuestionGenerationDebugResponse(BaseModel):
    lesson_id: str
    chapter_id: str
    target_question_count: int
    generated_question_count: int
    can_generate_quiz: bool
    can_fill_question_bank: bool
    concept_count: int
    concepts: List[LessonQuestionGenerationConceptResponse] = Field(default_factory=list)
    relation_counts: dict = Field(default_factory=dict)
    missing_relation_types: List[str] = Field(default_factory=list)
    sample_relations: List[LessonQuestionGenerationRelationResponse] = Field(default_factory=list)
    sample_questions: List[str] = Field(default_factory=list)


class CreateLessonQuizAttemptRequest(BaseModel):
    lesson_id: str = Field(..., min_length=1, description="Lesson identifier")


class LessonQuizAttemptQuestionResponse(BaseModel):
    question_id: str
    lesson_id: str
    concept: str
    relation_type: str
    bloom_level: str = "remember"
    question_text: str
    template_id: str
    difficulty: int = 1
    related_concepts: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    source_excerpt: str = ""
    source_chunk_id: Optional[str] = None
    options: List[QuestionBankOptionResponse] = Field(default_factory=list)


class LessonQuizAttemptResponse(BaseModel):
    attempt_id: str
    user_id: str
    lesson_id: str
    attempt_number: int
    selected_question_ids: List[str] = Field(default_factory=list)
    pass_threshold_count: int
    questions: List[LessonQuizAttemptQuestionResponse] = Field(default_factory=list)
    created_at: datetime


class SubmitLessonQuizRequest(BaseModel):
    attempt_id: str = Field(..., min_length=1, description="Quiz attempt identifier")
    user_answers: dict = Field(default_factory=dict, description="Mapping question_id -> selected option")


class LessonQuizResultItemResponse(BaseModel):
    question_id: str
    selected_answer: str
    correct_option: str
    is_correct: bool
    answer: str


class SubmitLessonQuizResponse(BaseModel):
    attempt_id: str
    lesson_id: str
    score: float
    correct_count: int
    total_questions: int
    attempt_number: int
    confidence_score: float
    pass_threshold_count: int
    is_passed: bool
    submitted_at: datetime
    results: List[LessonQuizResultItemResponse] = Field(default_factory=list)
    can_retry: bool


class AttemptConfidenceResponse(BaseModel):
    attempt_id: str
    lesson_id: str
    confidence_score: float
    correct_count: int
    total_questions: int
    attempt_number: int
    is_passed: bool
    score: float
    submitted_at: Optional[datetime] = None


class LessonConfidenceResponse(BaseModel):
    lesson_id: str
    confidence_score: float
    mastery_score: float
    best_confidence_score: float
    correct_count: int
    total_questions: int
    attempt_number: int
    is_passed: bool
    score: float
    band: str
    updated_at: Optional[datetime] = None


class UserConfidenceOverviewResponse(BaseModel):
    success: bool = True
    user_id: str
    confidence: float
    average_mastery: float
    lesson_count: int
    passed_lessons: int
    recent_average_confidence: float
    trend: str
    explanation: str
    details: List[dict] = Field(default_factory=list)


# =========================
# ASK (AI Q&A)
# =========================
class AskRequest(BaseModel):
    """Main Q&A request."""
    user_id: str = Field(..., description="MongoDB ObjectId as string")
    question: str = Field(..., min_length=5, max_length=2000)
    goal: str = Field(..., min_length=3, max_length=500)
    level: LevelEnum
    completed: Optional[List[str]] = None


class AskResponse(BaseModel):
    success: bool
    answer: dict
    learning_path: Optional[List[LearningPathItemResponse]] = None
    concept_detected: Optional[dict] = None
    adaptive_info: Optional[dict] = None
    progress_updated: bool = False


class AssessmentDifficultyEnum(str, Enum):
    easy = "easy"
    medium = "medium"
    hard = "hard"


class AssessmentQuestionItem(BaseModel):
    question: str
    answer: str
    explanation: str
    difficulty: AssessmentDifficultyEnum
    question_type: str
    concept: str
    source_excerpt: str


class GenerateAssessmentQuestionsRequest(BaseModel):
    user_id: str = Field(..., description="MongoDB ObjectId as string")
    lesson_title: Optional[str] = Field(default=None, min_length=1, max_length=300)
    concept: str = Field(..., min_length=2, max_length=200)
    difficulty: AssessmentDifficultyEnum
    question_type: str = Field(default="short_answer", min_length=2, max_length=100)
    num_questions: int = Field(..., ge=1, le=20)
    chapter_content: Optional[str] = Field(default=None, min_length=50, max_length=50000)
    retrieved_context: Optional[str] = Field(default=None, min_length=50, max_length=50000)

    @model_validator(mode="after")
    def validate_context(self):
        if not (self.chapter_content or self.retrieved_context):
            raise ValueError("Either chapter_content or retrieved_context is required")

        if not self.retrieved_context and self.chapter_content:
            self.retrieved_context = self.chapter_content
        if not self.chapter_content and self.retrieved_context:
            self.chapter_content = self.retrieved_context
        return self


class GenerateAssessmentQuestionsResponse(BaseModel):
    success: bool
    questions: List[AssessmentQuestionItem]
