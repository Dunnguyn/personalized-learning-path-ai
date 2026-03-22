from pydantic import BaseModel, EmailStr, Field, ConfigDict, model_validator
from typing import List, Optional, Literal
from datetime import datetime
from enum import Enum


class LevelEnum(str, Enum):
    beginner = "beginner"
    intermediate = "intermediate"
    advanced = "advanced"


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
    source: SourceEnum = SourceEnum.manual
    type: ResourceTypeEnum = ResourceTypeEnum.text
    topic: str = Field(..., min_length=2, max_length=200)
    level: LevelEnum
    concept_id: Optional[int] = Field(None, ge=1)
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


class LessonRecommendedChunksRequest(BaseModel):
    max_chunks: int = Field(default=8, ge=1, le=30)
    selection_strategy: str = Field(default="local_semantic_lesson_scope_v1", min_length=3, max_length=100)
    resource_ids: List[str] = Field(default_factory=list)
    metadata: dict = Field(default_factory=dict)


class RecommendedChunkItem(BaseModel):
    chunk_id: str
    resource_id: str
    chunk_index: int
    score: float
    preview: str


class LessonRecommendedChunksResponse(BaseModel):
    recommendation_id: str
    subject_id: str
    chapter_id: str
    lesson_id: str
    chunk_ids: List[str]
    resource_ids: List[str]
    selection_strategy: str
    metadata: dict = Field(default_factory=dict)
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
    is_ai_generated: bool = True
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
    created_at: datetime


class LessonQuestionGenerationResponse(BaseModel):
    lesson_id: str
    status: str
    generated_count: int
    question_ids: List[str] = Field(default_factory=list)
    chunks_used: List[str] = Field(default_factory=list)
    insufficient_data: bool = False
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


class LessonProgressUpdate(BaseModel):
    path_id: str = Field(..., description="Learning path UUID")
    lesson_id: str = Field(..., description="Lesson identifier")
    status: Literal["not_started", "in_progress", "complete"]


class LessonProgressResponse(BaseModel):
    path_id: str
    lesson_id: str
    status: str
    updated_at: datetime


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
