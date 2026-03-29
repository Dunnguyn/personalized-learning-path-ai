from pydantic import BaseModel, EmailStr, Field, ConfigDict, model_validator
from typing import Any, Dict, List, Optional, Literal
from datetime import date, datetime
from enum import Enum


class LevelEnum(str, Enum):
    beginner = "beginner"
    intermediate = "intermediate"
    advanced = "advanced"


class UserRoleEnum(str, Enum):
    learner = "learner"
    admin = "admin"


class SubjectIdEnum(str, Enum):
    python = "python"
    cpp = "cpp"
    csharp = "csharp"
    java = "java"
    web = "web"


class SourceEnum(str, Enum):
    pdf = "pdf"
    youtube = "youtube"
    web = "web"
    manual = "manual"


class ResourceTypeEnum(str, Enum):
    pdf = "pdf"
    youtube = "youtube"
    text = "text"


class PedagogyEnum(str, Enum):
    video = "video"
    text = "text"
    quiz = "quiz"


class BloomLevelEnum(str, Enum):
    remember = "remember"
    understand = "understand"
    apply = "apply"
    analyze = "analyze"
    evaluate = "evaluate"
    create = "create"


class LessonQuestionTypeEnum(str, Enum):
    multiple_choice = "multiple_choice"
    short_answer = "short_answer"
    true_false = "true_false"


# =========================
# USERS
# =========================
class UserCreate(BaseModel):
    name: str = Field(..., min_length=2, max_length=200)
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=100)
    level: LevelEnum = LevelEnum.beginner

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "name": "John Doe",
                "email": "john@example.com",
                "password": "securepassword123",
                "level": "beginner",
            }
        }
    )


class UserResponse(BaseModel):
    """User response with MongoDB ObjectId as string."""

    user_id: str = Field(..., description="MongoDB ObjectId as string")
    name: str
    email: EmailStr
    level: LevelEnum
    role: UserRoleEnum = UserRoleEnum.learner
    learning_goal: Optional[str] = None
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
    concept_id: int = Field(
        ..., description="Integer ID for concepts (can be auto-increment or ObjectId)"
    )


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
    source: SourceEnum = SourceEnum.manual
    type: ResourceTypeEnum = ResourceTypeEnum.text
    topic: str = Field(..., min_length=2, max_length=200)
    level: LevelEnum
    concept_id: Optional[int] = Field(None, ge=1)
    url: Optional[str] = None


class ResourceResponse(ResourceCreate):
    resource_id: str = Field(..., description="MongoDB ObjectId")
    created_at: datetime


class ResourceDetailResponse(BaseModel):
    resource_id: str
    title: str
    source: SourceEnum
    type: ResourceTypeEnum
    topic: str
    level: Optional[LevelEnum] = None
    concept_id: Optional[int] = None
    url: Optional[str] = None
    content_summary: Optional[str] = None
    status: Optional[str] = None
    chunks_count: int = 0
    processing_time: float = 0.0
    metadata: dict = Field(default_factory=dict)
    created_at: datetime
    updated_at: Optional[datetime] = None


class ResourceMetadataCreate(BaseModel):
    pedagogy_type: Optional[PedagogyEnum] = None
    bloom_level: Optional[str] = None


# =========================
# RESOURCE IMPORT (BATCH)
# =========================
class ResourceImport(BaseModel):
    title: str = Field(..., min_length=3, max_length=500)
    content: str = Field(..., min_length=10)
    source: SourceEnum = SourceEnum.manual
    type: ResourceTypeEnum = ResourceTypeEnum.text
    topic: str = Field(..., min_length=2, max_length=200)
    level: LevelEnum = LevelEnum.beginner
    url: Optional[str] = None
    concept_id: Optional[int] = Field(None, ge=1)
    pedagogy_type: Optional[PedagogyEnum] = None
    bloom_level: Optional[str] = None


class ResourceImportRequest(BaseModel):
    resources: List[ResourceImport] = Field(..., min_length=1, max_length=1000)


# =========================
# YOUTUBE IMPORT
# =========================
class YouTubeImportRequest(BaseModel):
    url: str = Field(
        ..., min_length=10, max_length=500, description="YouTube video URL"
    )
    title: str = Field(..., min_length=3, max_length=500, description="Resource title")
    topic: str = Field(..., min_length=2, max_length=200, description="Learning topic")
    level: LevelEnum = Field(default=LevelEnum.beginner, description="Difficulty level")
    concept_id: Optional[int] = Field(None, ge=1, description="Associated concept ID")

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "url": "https://www.youtube.com/watch?v=rfscVS0vtbw",
                "title": "Learn Python - Full Course for Beginners",
                "topic": "python",
                "level": "beginner",
                "concept_id": 1,
            }
        }
    )


class SubjectCreate(BaseModel):
    title: str = Field(..., min_length=2, max_length=200)
    slug: Optional[str] = Field(default=None, min_length=2, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    topic: Optional[str] = Field(default=None, max_length=200)
    level: LevelEnum = LevelEnum.beginner
    metadata: dict = Field(default_factory=dict)


class SubjectResponse(SubjectCreate):
    subject_id: str
    created_at: datetime


class SubjectListResponse(BaseModel):
    items: List[SubjectResponse]
    total: int
    page: int
    size: int
    pages: int


class ChapterCreate(BaseModel):
    subject_id: str = Field(..., description="MongoDB ObjectId")
    title: str = Field(..., min_length=2, max_length=200)
    description: Optional[str] = Field(default=None, max_length=2000)
    order: int = Field(default=1, ge=1)
    topic: Optional[str] = Field(default=None, max_length=200)
    metadata: dict = Field(default_factory=dict)


class ChapterResponse(ChapterCreate):
    chapter_id: str
    created_at: datetime


class ChapterListResponse(BaseModel):
    items: List[ChapterResponse]
    total: int
    page: int
    size: int
    pages: int


class LessonCreate(BaseModel):
    subject_id: str = Field(..., description="MongoDB ObjectId")
    chapter_id: str = Field(..., description="MongoDB ObjectId")
    title: str = Field(..., min_length=2, max_length=200)
    summary: Optional[str] = Field(default=None, max_length=4000)
    order: int = Field(default=1, ge=1)
    topic: Optional[str] = Field(default=None, max_length=200)
    level: LevelEnum = LevelEnum.beginner
    learning_objectives: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    resource_ids: List[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class LessonNodeResponse(LessonCreate):
    lesson_id: str
    created_at: datetime


class LessonListResponse(BaseModel):
    items: List[LessonNodeResponse]
    total: int
    page: int
    size: int
    pages: int


class LessonRecommendedChunksRequest(BaseModel):
    max_chunks: int = Field(default=8, ge=1, le=30)
    selection_strategy: str = Field(
        default="local_semantic_lesson_scope_v1", min_length=3, max_length=100
    )
    enable_diversity_reranking: bool = Field(
        default=True,
        description="Enable diversity-aware reranking after initial semantic/lexical scoring",
    )
    diversity_lambda: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=1.0,
        description="MMR relevance weight for diversity reranking (0..1). If omitted, service default is used.",
    )
    resource_ids: List[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class RecommendedChunkItem(BaseModel):
    chunk_id: str
    resource_id: str
    chunk_index: int
    page_number: Optional[int] = None
    score: float
    preview: str
    resource_title: Optional[str] = None
    resource_source: Optional[str] = None
    resource_url: Optional[str] = None
    instruction_role: Optional[str] = None
    difficulty: Optional[str] = None
    covered_objectives: List[str] = Field(default_factory=list)
    covered_concepts: List[str] = Field(default_factory=list)
    estimated_read_time: Optional[int] = None
    sequence_position: Optional[int] = None
    questionability_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    fact_density_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    concept_explicitness_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    example_presence_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    score_breakdown: dict = Field(default_factory=dict)
    cluster_id: Optional[str] = None
    selected_as_representative: Optional[bool] = None


class LessonRecommendedChunksResponse(BaseModel):
    recommendation_id: str
    subject_id: str
    chapter_id: str
    lesson_id: str
    chunk_ids: List[str]
    resource_ids: List[str]
    selection_strategy: str
    metadata: dict = Field(default_factory=dict)
    sequence_metadata: dict = Field(default_factory=dict)
    recommended_chunks: List[RecommendedChunkItem] = Field(default_factory=list)
    created_at: datetime


class LessonQuestionGenerationRequest(BaseModel):
    target_count: int = Field(default=5, ge=1, le=20)
    question_types: List[LessonQuestionTypeEnum] = Field(
        default_factory=lambda: [LessonQuestionTypeEnum.multiple_choice]
    )
    difficulty: LevelEnum = LevelEnum.beginner
    bloom_levels: List[BloomLevelEnum] = Field(
        default_factory=lambda: [BloomLevelEnum.remember, BloomLevelEnum.understand]
    )
    allow_llm: bool = True
    mastery: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    success_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    overwrite: bool = False
    metadata: dict = Field(default_factory=dict)


class QuestionBankItemResponse(BaseModel):
    question_id: str
    subject_id: str
    chapter_id: str
    lesson_id: str
    chunk_ids: List[str]
    resource_ids: List[str]
    question_type: LessonQuestionTypeEnum
    question: str
    correct_answer: str
    distractors: List[str] = Field(default_factory=list)
    explanation: str
    difficulty: LevelEnum
    bloom_level: BloomLevelEnum
    concept_id: Optional[str] = None
    retry_strategy: Optional[str] = None
    is_ai_generated: bool = True
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    generation_source: Optional[str] = None
    confidence_score: Optional[float] = None
    metadata: dict = Field(default_factory=dict)
    created_at: datetime


class LessonQuestionGenerationResponse(BaseModel):
    lesson_id: str
    status: str
    generated_count: int
    saved_count: int = 0
    question_ids: List[str] = Field(default_factory=list)
    chunks_used: List[str] = Field(default_factory=list)
    insufficient_data: bool = False
    reused_existing: bool = False
    existing_count: int = 0
    sources: dict = Field(default_factory=dict)
    filtered_count: int = 0
    message: str = ""


class LessonQuestionBankResponse(BaseModel):
    lesson_id: str
    total: int
    questions: List[QuestionBankItemResponse]


class ResourceIngestionResponse(BaseModel):
    resource_id: str
    job_id: Optional[str] = None
    status: str
    chunks_count: int
    processing_time: float
    duplicate: bool = False


class BatchResourceIngestionResponse(BaseModel):
    total: int
    submitted: int
    items: List[ResourceIngestionResponse]


class ResourceDeleteResponse(BaseModel):
    resource_id: str
    deleted: bool
    removed_chunks: int = 0
    removed_recommendations: int = 0
    removed_question_bank_entries: int = 0


class IngestionJobStatusResponse(BaseModel):
    job_id: str
    resource_id: str
    status: str
    chunks_count: int
    processing_time: float
    error: Optional[str] = None
    resource_status: Optional[str] = None


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


class CurriculumLessonResponse(BaseModel):
    lesson_id: str
    title: str
    summary: str
    resources: list = Field(default_factory=list)
    status: Optional[str] = None


class CurriculumChapterResponse(BaseModel):
    chapter_id: Optional[str] = None
    title: str
    lessons: List[CurriculumLessonResponse]


class LLMStatusResponse(BaseModel):
    provider: str
    enabled: bool
    cooldown_active: bool = False
    reason: Optional[str] = None
    model: Optional[str] = None


class LearningPathResponse(BaseModel):
    path_id: str = Field(..., description="UUID")
    user_id: str = Field(..., description="MongoDB ObjectId")
    goal: str
    level: LevelEnum
    generated_at: datetime
    recommended_path: List[LearningPathItemResponse]
    curriculum: Optional[List[CurriculumChapterResponse]] = None
    curriculum_source: str = "fallback"
    curriculum_notice: Optional[str] = None
    llm_status: Optional[LLMStatusResponse] = None
    message: str = ""


class GeneratedLearningPathLessonResponse(BaseModel):
    lesson_id: str
    title: str
    summary: Optional[str] = None
    recommended_chunk_ids: List[str] = Field(default_factory=list)
    status: Optional[str] = None
    last_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    confidence_updated_at: Optional[datetime] = None


class GeneratedLearningPathChapterResponse(BaseModel):
    chapter_id: str
    title: str
    lessons: List[GeneratedLearningPathLessonResponse]


class LearningPathGenerateRequest(BaseModel):
    subject_id: SubjectIdEnum
    goal: str = Field(..., min_length=3, max_length=500)
    level: LevelEnum


class GeneratedLearningPathResponse(BaseModel):
    path_id: str
    subject_id: SubjectIdEnum
    goal: str
    level: LevelEnum
    generated_at: Optional[datetime] = None
    chapters: List[GeneratedLearningPathChapterResponse]
    curriculum_source: str = "fallback"
    llm_status: Optional[LLMStatusResponse] = None
    message: str = ""


class LearningPathHistoryItemResponse(BaseModel):
    path_id: str
    subject_id: SubjectIdEnum
    goal: str
    level: LevelEnum
    generated_at: datetime
    chapter_count: int = 0
    lesson_count: int = 0


class LearningPathDeleteResponse(BaseModel):
    path_id: str
    deleted: bool = True
    removed_lessons: int = 0
    removed_chapters: int = 0
    removed_recommendations: int = 0
    removed_questions: int = 0


class LessonAnsweredQuestion(BaseModel):
    question_id: str
    question: str
    question_type: LessonQuestionTypeEnum
    user_answer: str
    correct_answer: str
    is_correct: bool
    difficulty: LevelEnum
    bloom_level: BloomLevelEnum
    chunk_id: Optional[str] = None
    concept_id: Optional[str] = None
    confidence_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class LessonProgressUpdate(BaseModel):
    path_id: str = Field(..., description="Learning path UUID")
    lesson_id: str = Field(..., description="Lesson identifier")
    status: Literal["not_started", "in_progress", "completed"] = Field(
        ..., description="Desired lesson status"
    )
    confidence: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Confidence score (0.0-1.0). If >= 0.75, auto-completes lesson; if < 0.75, blocks completion",
    )
    questions_answered: Optional[List[LessonAnsweredQuestion]] = Field(
        default=None,
        description="Array of answered questions with details for attempt logging",
    )


class LessonProgressResponse(BaseModel):
    path_id: str
    lesson_id: str
    status: str
    is_locked: bool = False
    reason_locked: Optional[str] = None
    blocking_lesson_id: Optional[str] = None
    auto_completed: bool = False
    last_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    confidence_updated_at: Optional[datetime] = None
    attempt_id: Optional[str] = None
    accuracy: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    updated_mastery: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    next_action: Optional[dict] = None
    adaptive_next_quiz: Optional[dict] = None
    updated_at: datetime


class AdaptiveQuizNextRequest(BaseModel):
    path_id: Optional[str] = None
    target_count: int = Field(default=6, ge=1, le=20)


class AdaptiveQuizNextResponse(BaseModel):
    lesson_id: str
    next_action: dict = Field(default_factory=dict)
    generation_request: dict = Field(default_factory=dict)
    generated: dict = Field(default_factory=dict)


class LessonStudyTimeUpdate(BaseModel):
    path_id: str = Field(..., description="Learning path UUID")
    lesson_id: str = Field(..., description="Lesson identifier")
    seconds_spent: int = Field(
        ..., ge=1, le=86400, description="Accumulated study time in seconds"
    )


class LessonStudyTimeResponse(BaseModel):
    path_id: str
    lesson_id: str
    seconds_spent: int
    total_seconds: int
    tracked_date: date
    updated_at: datetime


class StudySummaryDayItem(BaseModel):
    date: date
    seconds: int
    hours: float


class StudySummaryResponse(BaseModel):
    user_id: str
    total_seconds: int
    total_hours: float
    last_7_days: List[StudySummaryDayItem] = Field(default_factory=list)
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
    options: List[str] = Field(default_factory=list)


class GenerateAssessmentQuestionsRequest(BaseModel):
    user_id: str = Field(..., description="MongoDB ObjectId as string")
    lesson_title: Optional[str] = Field(default=None, min_length=1, max_length=300)
    concept: str = Field(..., min_length=2, max_length=200)
    difficulty: AssessmentDifficultyEnum
    question_type: str = Field(default="short_answer", min_length=2, max_length=100)
    num_questions: int = Field(..., ge=1, le=20)
    chapter_content: Optional[str] = Field(
        default=None, min_length=50, max_length=50000
    )
    retrieved_context: Optional[str] = Field(
        default=None, min_length=50, max_length=50000
    )

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


# =========================
# ADAPTIVE LEARNING LOOP
# =========================
class LearningEventTypeEnum(str, Enum):
    resource_opened = "resource_opened"
    resource_completed = "resource_completed"
    resource_abandoned = "resource_abandoned"
    resource_feedback_submitted = "resource_feedback_submitted"
    quiz_started = "quiz_started"
    quiz_submitted = "quiz_submitted"
    lesson_started = "lesson_started"
    lesson_completed = "lesson_completed"
    lesson_retried = "lesson_retried"
    recommendation_clicked = "recommendation_clicked"


class AdaptiveActionEnum(str, Enum):
    continue_resource = "continue_resource"
    resume_unfinished = "resume_unfinished"
    review_summary = "review_summary"
    practice_quiz = "practice_quiz"
    retry_with_easier_resource = "retry_with_easier_resource"
    study_worked_example = "study_worked_example"
    study_misconception_fix = "study_misconception_fix"
    reinforce_weak_concept = "reinforce_weak_concept"
    move_to_next_lesson = "move_to_next_lesson"
    return_to_prerequisite = "return_to_prerequisite"
    switch_format_to_video = "switch_format_to_video"
    switch_format_to_text = "switch_format_to_text"
    quick_review_session = "quick_review_session"


class AdaptivePriorityEnum(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class AdaptiveRiskLevelEnum(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class AdaptiveRecommendationTypeEnum(str, Enum):
    resource = "resource"
    chunk = "chunk"
    lesson = "lesson"


class LearningEventIngestRequest(BaseModel):
    event_type: LearningEventTypeEnum
    resource_id: Optional[str] = None
    lesson_id: Optional[str] = None
    path_id: Optional[str] = None
    concept_ids: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class LearningEventResponse(BaseModel):
    event_id: str
    user_id: str
    event_type: LearningEventTypeEnum
    resource_id: Optional[str] = None
    lesson_id: Optional[str] = None
    path_id: Optional[str] = None
    concept_ids: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime


class LearnerStateSnapshotResponse(BaseModel):
    user_id: str
    snapshot_time: datetime
    mastery_by_concept: Dict[str, float] = Field(default_factory=dict)
    confidence_by_concept: Dict[str, float] = Field(default_factory=dict)
    recent_active_days: int = 0
    avg_session_duration: float = 0.0
    unfinished_resources: int = 0
    quiz_fail_streak: int = 0
    retry_count: int = 0
    learning_velocity: float = 0.0
    preferred_time_window: str = "evening"
    current_focus_concepts: List[str] = Field(default_factory=list)
    frustration_score: float = 0.0
    recovery_need_flag: bool = False
    risk_level: AdaptiveRiskLevelEnum = AdaptiveRiskLevelEnum.low
    last_event_type: Optional[str] = None
    last_recommended_action: Optional[str] = None


class AdaptiveNextActionResponse(BaseModel):
    user_id: str
    next_best_action: AdaptiveActionEnum
    reason: str
    priority: AdaptivePriorityEnum
    recommended_mode: Literal[
        "continue_learning",
        "reinforce_weaknesses",
        "learn_new",
        "quick_review",
    ]
    target_concepts: List[str] = Field(default_factory=list)
    lesson_id: Optional[str] = None
    resource_id: Optional[str] = None
    estimated_total_time: Optional[int] = None


class AdaptiveRecommendationResponse(BaseModel):
    user_id: str
    action: AdaptiveActionEnum
    recommendation_type: AdaptiveRecommendationTypeEnum
    recommendation_mode: Optional[
        Literal[
            "continue_learning",
            "reinforce_weaknesses",
            "learn_new",
            "quick_review",
        ]
    ] = None
    items: List[Dict[str, Any]] = Field(default_factory=list)
    reason: str
    target_concepts: List[str] = Field(default_factory=list)
    estimated_total_time: int = 0
    lesson_id: Optional[str] = None
    resource_id: Optional[str] = None


class AdaptiveRecomputeRequest(BaseModel):
    user_id: Optional[str] = None
    event_id: Optional[str] = None


class AdaptiveRecomputeResponse(BaseModel):
    user_id: str
    snapshot: LearnerStateSnapshotResponse
    next_action: AdaptiveNextActionResponse
