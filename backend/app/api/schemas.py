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


class TimeBudgetUnitEnum(str, Enum):
    daily = "daily"
    weekly = "weekly"


class PreferredResourceTypeEnum(str, Enum):
    video = "video"
    pdf = "pdf"
    practice = "practice"
    mixed = "mixed"


class LearningPaceEnum(str, Enum):
    light = "light"
    steady = "steady"
    intensive = "intensive"


class TimeBudgetPayload(BaseModel):
    value: int = Field(default=300, ge=30, le=10080)
    unit: TimeBudgetUnitEnum = TimeBudgetUnitEnum.weekly


# =========================
# LEARNER PROFILE
# =========================
class LearnerProfileCreate(BaseModel):
    user_id: str = Field(..., description="MongoDB ObjectId")
    learning_goal: str = Field(..., min_length=10, max_length=500)
    preferred_style: Optional[str] = None
    time_constraint: Optional[str] = None


class LearnerProfileUpsertRequest(BaseModel):
    level: Optional[LevelEnum] = None
    learning_goal: Optional[str] = Field(default=None, min_length=3, max_length=500)
    target_role: Optional[str] = Field(default=None, min_length=2, max_length=200)
    target_outcome: Optional[str] = Field(default=None, min_length=3, max_length=500)
    time_budget: Optional[TimeBudgetPayload] = None
    preferred_resource_type: Optional[PreferredResourceTypeEnum] = None
    learning_pace: Optional[LearningPaceEnum] = None
    desired_deadline: Optional[date] = None
    prior_knowledge_by_subject: Optional[Dict[str, str]] = None


class LearnerProfileResponse(BaseModel):
    user_id: str
    level: LevelEnum = LevelEnum.beginner
    learning_goal: Optional[str] = None
    target_role: Optional[str] = None
    target_outcome: Optional[str] = None
    time_budget: TimeBudgetPayload = Field(default_factory=TimeBudgetPayload)
    preferred_resource_type: PreferredResourceTypeEnum = (
        PreferredResourceTypeEnum.mixed
    )
    learning_pace: LearningPaceEnum = LearningPaceEnum.steady
    desired_deadline: Optional[str] = None
    prior_knowledge_by_subject: Dict[str, str] = Field(default_factory=dict)
    diagnostic_scores_by_subject: Dict[str, Dict[str, float]] = Field(
        default_factory=dict
    )
    diagnostic_summary_by_subject: Dict[str, Dict[str, Any]] = Field(
        default_factory=dict
    )
    onboarding_status: Dict[str, bool] = Field(default_factory=dict)
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class DiagnosticQuestionResponse(BaseModel):
    concept_key: str
    title: str
    prompt: str
    difficulty: Optional[int] = None
    subject_id: str


class DiagnosticStartRequest(BaseModel):
    subject_id: Optional[str] = None
    goal: Optional[str] = Field(default=None, min_length=3, max_length=500)
    max_questions: int = Field(default=5, ge=3, le=8)


class DiagnosticStartResponse(BaseModel):
    session_id: str
    subject_id: str
    questions: List[DiagnosticQuestionResponse] = Field(default_factory=list)
    prior_knowledge_level: Optional[str] = None
    message: str = ""


class DiagnosticAnswerPayload(BaseModel):
    concept_key: str = Field(..., min_length=2, max_length=200)
    score: float = Field(..., ge=0.0, le=100.0)


class DiagnosticSubmitRequest(BaseModel):
    session_id: str
    subject_id: Optional[str] = None
    answers: List[DiagnosticAnswerPayload] = Field(
        default_factory=list,
        min_length=1,
        max_length=12,
    )


class DiagnosticResultResponse(BaseModel):
    subject_id: str
    recommended_level: LevelEnum = LevelEnum.beginner
    average_score: float = Field(default=0.0, ge=0.0, le=1.0)
    concept_scores: Dict[str, float] = Field(default_factory=dict)
    prior_knowledge_level: Optional[str] = None
    completed: bool = False
    evaluated_at: Optional[datetime] = None
    message: str = ""


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
    metadata: "FlexibleMetadataPayload" = Field(
        default_factory=lambda: FlexibleMetadataPayload()
    )
    created_at: datetime
    updated_at: Optional[datetime] = None


class ResourceMetadataCreate(BaseModel):
    pedagogy_type: Optional[PedagogyEnum] = None
    bloom_level: Optional[str] = None


class FlexibleMetadataPayload(BaseModel):
    main_concept: Optional[str] = None
    covered_concepts: List[str] = Field(default_factory=list)
    keywords: List[str] = Field(default_factory=list)
    pedagogy_type: Optional[PedagogyEnum] = None
    bloom_level: Optional[str] = None
    estimated_read_time: Optional[int] = None

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "main_concept": "python_loops",
                "covered_concepts": ["python_loops", "iteration"],
                "keywords": ["for loop", "while loop"],
                "pedagogy_type": "text",
                "bloom_level": "understand",
                "estimated_read_time": 8,
            }
        },
    )


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
    metadata: FlexibleMetadataPayload = Field(
        default_factory=lambda: FlexibleMetadataPayload()
    )


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
    metadata: FlexibleMetadataPayload = Field(
        default_factory=lambda: FlexibleMetadataPayload()
    )


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
    metadata: FlexibleMetadataPayload = Field(
        default_factory=lambda: FlexibleMetadataPayload()
    )


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
    metadata: "LessonRecommendationMetadataRequest" = Field(
        default_factory=lambda: LessonRecommendationMetadataRequest()
    )


class LessonRecommendationMetadataRequest(BaseModel):
    mode: Optional[str] = None
    path_id: Optional[str] = None
    trigger: Optional[str] = None
    reason: Optional[str] = None
    required_concepts: List[str] = Field(default_factory=list)
    target_concepts: List[str] = Field(default_factory=list)
    current_focus_concepts: List[str] = Field(default_factory=list)
    avoid_resource_ids: List[str] = Field(default_factory=list)
    auto_refresh_disabled: Optional[bool] = None
    fallback: Optional[bool] = None

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "mode": "adaptive_review",
                "path_id": "lp_001",
                "trigger": "target_concept_refresh",
                "required_concepts": ["python_loops"],
                "target_concepts": ["python_loops"],
                "current_focus_concepts": ["python_loops"],
                "avoid_resource_ids": ["res_009"],
                "auto_refresh_disabled": False,
                "fallback": False,
            }
        },
    )

ResourceDetailResponse.model_rebuild()
LessonRecommendedChunksRequest.model_rebuild()


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
    covered_objectives: List[str] = Field(default_factory=list)
    covered_concepts: List[str] = Field(default_factory=list)
    matched_required_concepts: List[str] = Field(default_factory=list)
    estimated_read_time: Optional[int] = None
    sequence_position: Optional[int] = None
    questionability_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    anchor_match_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    index_like_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class LessonRecommendationSequenceMetadataResponse(BaseModel):
    has_introduction: bool = False
    has_explanation: bool = False
    has_example: bool = False
    has_summary: bool = False
    roles_present: List[str] = Field(default_factory=list)
    missing_roles: List[str] = Field(default_factory=list)
    required_concepts: List[str] = Field(default_factory=list)
    covered_required_concepts: List[str] = Field(default_factory=list)
    missing_required_concepts: List[str] = Field(default_factory=list)

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "has_introduction": True,
                "has_explanation": True,
                "has_example": True,
                "has_summary": False,
                "roles_present": ["introduction", "explanation", "worked_example"],
                "missing_roles": ["summary"],
                "required_concepts": ["python_loops"],
                "covered_required_concepts": ["python_loops"],
                "missing_required_concepts": [],
            }
        },
    )


class LessonRecommendationDiversityRerankingResponse(BaseModel):
    strategy: Optional[str] = None
    diversity_ratio: Optional[float] = Field(default=None, ge=0.0, le=1.0)

    model_config = ConfigDict(extra="allow")


class LessonRecommendationQueryPayloadResponse(BaseModel):
    intent: Optional[str] = None
    english_terms: List[str] = Field(default_factory=list)
    vietnamese_terms: List[str] = Field(default_factory=list)
    bilingual_terms: List[str] = Field(default_factory=list)
    english_query: Optional[str] = None
    bilingual_query: Optional[str] = None

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "intent": "python loops iteration beginner",
                "english_terms": ["python loops", "iteration", "for loop"],
                "vietnamese_terms": ["vong lap python", "for loop"],
                "bilingual_terms": ["python loops", "iteration", "vong lap python"],
                "english_query": "python loops iteration for loop",
                "bilingual_query": "python loops iteration vong lap python",
            }
        },
    )


class LessonRecommendationMetadataResponse(BaseModel):
    query_text: Optional[str] = None
    lesson_query_payload: LessonRecommendationQueryPayloadResponse = Field(
        default_factory=LessonRecommendationQueryPayloadResponse
    )
    anchor_phrases: List[str] = Field(default_factory=list)
    required_concepts: List[str] = Field(default_factory=list)
    candidate_count: int = 0
    gated_candidate_count: int = 0
    strict_candidate_count: int = 0
    cluster_count: int = 0
    selected_count: int = 0
    scores: Dict[str, float] = Field(default_factory=dict)
    diversity_reranking: LessonRecommendationDiversityRerankingResponse = Field(
        default_factory=LessonRecommendationDiversityRerankingResponse
    )
    avoid_resource_ids: List[str] = Field(default_factory=list)
    selection_strategy: Optional[str] = None
    instructional_roles: List[str] = Field(default_factory=list)
    chunk_cluster_map: Dict[str, Optional[str]] = Field(default_factory=dict)
    sequence_metadata: LessonRecommendationSequenceMetadataResponse = Field(
        default_factory=LessonRecommendationSequenceMetadataResponse
    )

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "query_text": "python loops iteration beginner",
                "lesson_query_payload": {
                    "intent": "python loops iteration beginner",
                    "english_terms": ["python loops", "iteration"],
                    "vietnamese_terms": ["vong lap python"],
                    "bilingual_terms": ["python loops", "vong lap python"],
                    "english_query": "python loops iteration",
                    "bilingual_query": "python loops vong lap python",
                },
                "anchor_phrases": ["for loop", "iteration"],
                "required_concepts": ["python_loops"],
                "candidate_count": 12,
                "gated_candidate_count": 8,
                "strict_candidate_count": 5,
                "cluster_count": 4,
                "selected_count": 3,
                "scores": {"chunk_a": 0.91, "chunk_b": 0.87},
                "diversity_reranking": {
                    "strategy": "mmr",
                    "diversity_ratio": 0.42,
                },
                "avoid_resource_ids": [],
                "selection_strategy": "local_semantic_lesson_scope_v1",
                "instructional_roles": ["introduction", "explanation", "worked_example"],
                "chunk_cluster_map": {"chunk_a": "0", "chunk_b": "1"},
                "sequence_metadata": {
                    "has_introduction": True,
                    "has_explanation": True,
                    "has_example": True,
                    "has_summary": False,
                    "roles_present": [
                        "introduction",
                        "explanation",
                        "worked_example",
                    ],
                    "missing_roles": ["summary"],
                    "required_concepts": ["python_loops"],
                    "covered_required_concepts": ["python_loops"],
                    "missing_required_concepts": [],
                },
            }
        },
    )


class LessonRecommendedChunksResponse(BaseModel):
    recommendation_id: str
    subject_id: str
    chapter_id: str
    lesson_id: str
    chunk_ids: List[str]
    resource_ids: List[str]
    selection_strategy: str
    metadata: LessonRecommendationMetadataResponse = Field(
        default_factory=LessonRecommendationMetadataResponse
    )
    sequence_metadata: LessonRecommendationSequenceMetadataResponse = Field(
        default_factory=LessonRecommendationSequenceMetadataResponse
    )
    recommended_chunks: List[RecommendedChunkItem] = Field(default_factory=list)
    created_at: datetime


class LessonQuestionGenerationRequest(BaseModel):
    target_count: Optional[int] = Field(default=None, ge=1, le=20)
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
    metadata: "LessonQuestionGenerationMetadataRequest" = Field(
        default_factory=lambda: LessonQuestionGenerationMetadataRequest()
    )


class LessonQuestionGenerationStrategyRequest(BaseModel):
    template_first: Optional[bool] = None
    allow_llm: Optional[bool] = None
    prefer_template: Optional[bool] = None
    retry_strategy: Optional[
        Literal[
            "same_question",
            "paraphrase_question",
            "simplify_question",
            "explain_then_question",
        ]
    ] = None
    reuse_previous_question: Optional[bool] = None
    paraphrase_question: Optional[bool] = None
    add_explanation_before_question: Optional[bool] = None

    model_config = ConfigDict(extra="allow")


class LessonQuestionGenerationMetadataRequest(BaseModel):
    adaptive_quiz: Optional[bool] = None
    path_id: Optional[str] = None
    trigger: Optional[str] = None
    generation_reason: Optional[str] = None
    current_lesson_status: Optional[str] = None
    adaptive_explanation: Optional[str] = None
    retry_strategy: Optional[
        Literal[
            "same_question",
            "paraphrase_question",
            "simplify_question",
            "explain_then_question",
        ]
    ] = None
    prefer_template: Optional[bool] = None
    target_chunk_ids: List[str] = Field(default_factory=list)
    target_concepts: List[str] = Field(default_factory=list)
    required_concepts: List[str] = Field(default_factory=list)
    current_focus_concepts: List[str] = Field(default_factory=list)
    generation_strategy: LessonQuestionGenerationStrategyRequest = Field(
        default_factory=LessonQuestionGenerationStrategyRequest
    )

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "adaptive_quiz": True,
                "path_id": "lp_001",
                "target_chunk_ids": ["chunk_a", "chunk_b"],
                "target_concepts": ["python_loops"],
                "current_focus_concepts": ["python_loops"],
                "retry_strategy": "simplify_question",
                "adaptive_explanation": "Xem lai giai thich ngan gon truoc khi lam cau hoi.",
                "prefer_template": True,
                "generation_strategy": {
                    "template_first": True,
                    "allow_llm": False,
                    "prefer_template": True,
                    "retry_strategy": "simplify_question",
                    "reuse_previous_question": False,
                    "paraphrase_question": False,
                    "add_explanation_before_question": True,
                },
                "generation_reason": "reinforcement_quiz",
            }
        },
    )


class LessonQuestionResponse(BaseModel):
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
    metadata: "LessonQuestionMetadataResponse" = Field(
        default_factory=lambda: LessonQuestionMetadataResponse()
    )
    created_at: datetime


LessonQuestionGenerationRequest.model_rebuild()


class LessonQuestionMetadataResponse(BaseModel):
    generation_source: Optional[str] = None
    generation_mode: Optional[str] = None
    reasoning_note: Optional[str] = None
    source_excerpt: Optional[str] = None
    question_focus: Optional[str] = None
    instruction_role: Optional[str] = None
    covered_concepts: List[str] = Field(default_factory=list)
    target_concepts: List[str] = Field(default_factory=list)
    target_concept_match: Optional[bool] = None
    fallback_style: Optional[str] = None
    difficulty_transform: Optional[LevelEnum] = None
    fallback_attempt: Optional[int] = None
    fallback_chunk_score: Optional[float] = None
    fallback_priority_score: Optional[float] = None
    fallback_excerpt_score: Optional[float] = None
    quality_score: Optional[float] = None
    confidence_score: Optional[float] = None
    tracked_bloom_level: Optional[BloomLevelEnum] = None
    tracked_difficulty: Optional[LevelEnum] = None
    tracked_confidence_score: Optional[float] = None
    lesson_recommendation_id: Optional[str] = None
    allowed_resource_ids: List[str] = Field(default_factory=list)
    resolved_resource_ids: List[str] = Field(default_factory=list)
    resolved_page_numbers: List[int] = Field(default_factory=list)
    resolved_chunk_indexes: List[int] = Field(default_factory=list)
    coverage_chunk_count: Optional[int] = None

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "generation_source": "local_fallback",
                "generation_mode": "local_fallback",
                "reasoning_note": "Generated by deterministic local fallback from recommended chunk.",
                "source_excerpt": "A loop repeats a block of code for each item in a sequence.",
                "question_focus": "python_loops",
                "instruction_role": "worked_example",
                "covered_concepts": ["python_loops", "iteration"],
                "target_concepts": ["python_loops"],
                "target_concept_match": True,
                "fallback_style": "focus_from_description_mcq",
                "difficulty_transform": "beginner",
                "fallback_attempt": 0,
                "fallback_chunk_score": 5.72,
                "fallback_priority_score": 8.14,
                "fallback_excerpt_score": 2.35,
                "quality_score": 0.86,
                "confidence_score": 0.86,
                "tracked_bloom_level": "understand",
                "tracked_difficulty": "beginner",
                "tracked_confidence_score": 0.86,
                "lesson_recommendation_id": "rec_001",
                "allowed_resource_ids": ["res_001"],
                "resolved_resource_ids": ["res_001"],
                "resolved_page_numbers": [2],
                "resolved_chunk_indexes": [5],
                "coverage_chunk_count": 1,
            }
        },
    )


LessonQuestionResponse.model_rebuild()


class LessonQuestionGenerationCacheStatsResponse(BaseModel):
    scope: str = "shared_template_claim_cache"
    entries: int = 0
    hits: int = 0
    misses: int = 0
    stores: int = 0
    requests: int = 0
    request_hit_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    lifetime_hit_rate: float = Field(default=0.0, ge=0.0, le=1.0)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "scope": "shared_template_claim_cache",
                "entries": 42,
                "hits": 6,
                "misses": 2,
                "stores": 2,
                "requests": 8,
                "request_hit_rate": 0.75,
                "lifetime_hit_rate": 0.68,
            }
        }
    )


class LessonQuestionGenerationSourcesResponse(BaseModel):
    template: int = 0
    llm: int = 0
    local_fallback: int = 0
    existing_reuse: int = 0

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "template": 2,
                "llm": 0,
                "local_fallback": 2,
                "existing_reuse": 0,
            }
        }
    )


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
    sources: LessonQuestionGenerationSourcesResponse = Field(
        default_factory=LessonQuestionGenerationSourcesResponse
    )
    fallback_used: bool = False
    cache_stats: LessonQuestionGenerationCacheStatsResponse = Field(
        default_factory=LessonQuestionGenerationCacheStatsResponse
    )
    filtered_count: int = 0
    lesson_size: Optional[Literal["small", "medium", "large"]] = None
    declared_lesson_size: Optional[Literal["small", "medium", "large"]] = None
    runtime_effective_lesson_size: Optional[Literal["small", "medium", "large"]] = None
    target_count: Optional[int] = Field(default=None, ge=1, le=20)
    target_count_auto: Optional[int] = Field(default=None, ge=1, le=20)
    original_target_count: Optional[int] = Field(default=None, ge=1, le=20)
    effective_target_count: Optional[int] = Field(default=None, ge=1, le=20)
    degraded_target_count: Optional[int] = Field(default=None, ge=1, le=20)
    degraded_mode: bool = False
    degraded_reason: Optional[str] = None
    llm_status: Optional[str] = None
    difficulty_mix: Dict[str, Any] = Field(default_factory=dict)
    bloom_mix: Dict[str, Any] = Field(default_factory=dict)
    concept_coverage_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    valid_target_concepts: List[str] = Field(default_factory=list)
    rejected_target_concepts: List[str] = Field(default_factory=list)
    concept_coverage_status: Optional[str] = None
    next_action: Dict[str, Any] = Field(default_factory=dict)
    message: str = ""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "lesson_id": "lesson_03",
                "status": "ok",
                "generated_count": 4,
                "saved_count": 4,
                "question_ids": ["q_001", "q_002", "q_003", "q_004"],
                "chunks_used": ["chunk_a", "chunk_b"],
                "insufficient_data": False,
                "reused_existing": False,
                "existing_count": 0,
                "sources": {
                    "template": 2,
                    "llm": 0,
                    "local_fallback": 2,
                    "existing_reuse": 0,
                },
                "fallback_used": True,
                "cache_stats": {
                    "scope": "shared_template_claim_cache",
                    "entries": 42,
                    "hits": 6,
                    "misses": 2,
                    "stores": 2,
                    "requests": 8,
                    "request_hit_rate": 0.75,
                    "lifetime_hit_rate": 0.68,
                },
                "filtered_count": 1,
                "message": "Generated 4 grounded questions from recommended chunks.",
            }
        }
    )


class LessonQuestionGenerationLLMStatusResponse(BaseModel):
    provider: str
    model: str
    provider_supported: bool = True
    api_key_configured: bool = False
    client_available: bool = False
    init_error: Optional[str] = None
    last_error: Optional[str] = None
    cooldown_active: bool = False
    cooldown_remaining_seconds: int = 0

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "provider": "gemini",
                "model": "models/gemini-2.5-flash",
                "provider_supported": True,
                "api_key_configured": False,
                "client_available": False,
                "init_error": "Gemini API key is not configured. Set GEMINI_API_KEY, GEMINI_API_KEYS, or GEMINI_API_KEY_1..N.",
                "last_error": None,
                "cooldown_active": False,
                "cooldown_remaining_seconds": 0,
            }
        }
    )


class LessonQuestionGenerationNLPStatusResponse(BaseModel):
    spacy_available: bool = False
    sentence_transformers_available: bool = False
    rank_bm25_available: bool = False
    fallback_backend: str = "tfidf_regex"

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "spacy_available": False,
                "sentence_transformers_available": False,
                "rank_bm25_available": False,
                "fallback_backend": "tfidf_regex",
            }
        }
    )


class LessonQuestionGenerationChunkDebugResponse(BaseModel):
    chunk_id: str
    instruction_role: str
    covered_concepts: List[str] = Field(default_factory=list)
    target_match: bool = False
    target_semantic_score: float = Field(default=0.0, ge=0.0, le=1.0)
    target_lexical_score: float = Field(default=0.0, ge=0.0, le=1.0)
    keyword_overlap_terms: List[str] = Field(default_factory=list)
    questionability_score: float = 0.0
    priority_score: float = 0.0
    claim_count: int = 0
    has_code: bool = False
    has_example: bool = False
    estimated_read_time: float = 0.0

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "chunk_id": "chunk_a",
                "instruction_role": "worked_example",
                "covered_concepts": ["python_loops", "iteration"],
                "target_match": True,
                "target_semantic_score": 0.71,
                "target_lexical_score": 0.58,
                "keyword_overlap_terms": ["python loops", "iteration"],
                "questionability_score": 0.84,
                "priority_score": 8.72,
                "claim_count": 3,
                "has_code": True,
                "has_example": True,
                "estimated_read_time": 2.4,
            }
        }
    )


class LessonQuestionGenerationDebugResponse(BaseModel):
    lesson_id: str
    target_count: int
    question_types: List[LessonQuestionTypeEnum] = Field(default_factory=list)
    requested_difficulty: LevelEnum
    effective_difficulty: LevelEnum
    bloom_levels: List[BloomLevelEnum] = Field(default_factory=list)
    llm_requested: bool = False
    predicted_generation_path: str
    target_concepts: List[str] = Field(default_factory=list)
    existing_count: int = 0
    recommendation_available: bool = False
    recommendation_source: Optional[str] = None
    recommendation_selection_strategy: Optional[str] = None
    recommendation_chunk_count: int = 0
    recommendation_resource_count: int = 0
    recommendation_covers_target_concepts: bool = True
    scope_ready: bool = False
    scope_error: Optional[str] = None
    chunk_ids: List[str] = Field(default_factory=list)
    loaded_chunk_ids: List[str] = Field(default_factory=list)
    missing_chunk_ids: List[str] = Field(default_factory=list)
    nlp_status: LessonQuestionGenerationNLPStatusResponse = Field(
        default_factory=LessonQuestionGenerationNLPStatusResponse
    )
    chunk_debug: List[LessonQuestionGenerationChunkDebugResponse] = Field(
        default_factory=list
    )
    llm_status: LessonQuestionGenerationLLMStatusResponse
    blockers: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)
    message: str = ""

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "lesson_id": "lesson_03",
                "target_count": 5,
                "question_types": ["multiple_choice", "short_answer"],
                "requested_difficulty": "beginner",
                "effective_difficulty": "beginner",
                "bloom_levels": ["remember", "understand"],
                "llm_requested": True,
                "predicted_generation_path": "llm_requested_but_local_fallback_expected",
                "target_concepts": ["python_loops"],
                "existing_count": 4,
                "recommendation_available": True,
                "recommendation_source": "lesson_document_fallback",
                "recommendation_selection_strategy": "lesson_document_fallback_v1",
                "recommendation_chunk_count": 8,
                "recommendation_resource_count": 2,
                "recommendation_covers_target_concepts": True,
                "scope_ready": True,
                "scope_error": None,
                "chunk_ids": ["chunk_a", "chunk_b"],
                "loaded_chunk_ids": ["chunk_a", "chunk_b"],
                "missing_chunk_ids": [],
                "nlp_status": {
                    "spacy_available": False,
                    "sentence_transformers_available": False,
                    "rank_bm25_available": False,
                    "fallback_backend": "tfidf_regex",
                },
                "chunk_debug": [
                    {
                        "chunk_id": "chunk_a",
                        "instruction_role": "worked_example",
                        "covered_concepts": ["python_loops", "iteration"],
                        "target_match": True,
                        "target_semantic_score": 0.71,
                        "target_lexical_score": 0.58,
                        "keyword_overlap_terms": ["python loops", "iteration"],
                        "questionability_score": 0.84,
                        "priority_score": 8.72,
                        "claim_count": 3,
                        "has_code": True,
                        "has_example": True,
                        "estimated_read_time": 2.4,
                    }
                ],
                "llm_status": {
                    "provider": "gemini",
                    "model": "models/gemini-2.5-flash",
                    "provider_supported": True,
                    "api_key_configured": False,
                    "client_available": False,
                    "init_error": "Gemini API key is not configured. Set GEMINI_API_KEY, GEMINI_API_KEYS, or GEMINI_API_KEY_1..N.",
                    "last_error": None,
                    "cooldown_active": False,
                    "cooldown_remaining_seconds": 0,
                },
                "blockers": ["llm_client_unavailable"],
                "warnings": ["prefer_template_enabled"],
                "message": "Gemini API key is not configured. Set GEMINI_API_KEY, GEMINI_API_KEYS, or GEMINI_API_KEY_1..N.",
            }
        }
    )


class LessonQuestionsResponse(BaseModel):
    lesson_id: str
    total: int
    questions: List[LessonQuestionResponse]


class LessonAttemptStatisticsResponse(BaseModel):
    lesson_id: Optional[str] = None
    total_attempts: int = 0
    passed_attempts: int = 0
    best_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    best_bloom_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    best_attempt_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    best_attempt_bloom_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    best_attempt_mastery_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    avg_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    latest_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    improvement: Optional[float] = Field(default=None, ge=-1.0, le=1.0)
    success_rate: float = Field(default=0.0, ge=0.0, le=1.0)
    best_mastery_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    latest_mastery_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    best_attempt_number: Optional[int] = None
    best_attempt_completion_status: Optional[
        Literal["completed", "reinforce_required", "retry_required"]
    ] = None
    latest_completion_status: Optional[
        Literal["completed", "reinforce_required", "retry_required"]
    ] = None


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
    removed_lesson_questions: int = 0


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
    target_concepts: List[str] = Field(default_factory=list)
    prerequisite_concepts: List[str] = Field(default_factory=list)


class LLMStatusResponse(BaseModel):
    provider: str
    enabled: bool
    cooldown_active: bool = False
    reason: Optional[str] = None
    model: Optional[str] = None


class ConceptGraphNodeResponse(BaseModel):
    concept_id: str
    subject_id: Optional[str] = None
    concept_name: str
    difficulty: int = Field(default=1, ge=1, le=10)
    prerequisites: List[str] = Field(default_factory=list)
    unlock_strategy: Optional[str] = None
    mastery_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)


class GeneratedLearningPathLessonResponse(BaseModel):
    lesson_id: str
    title: str
    summary: Optional[str] = None
    objectives: List[str] = Field(default_factory=list)
    prerequisites: List[str] = Field(default_factory=list)
    target_concepts: List[str] = Field(default_factory=list)
    prerequisite_concepts: List[str] = Field(default_factory=list)
    difficulty: Optional[int] = Field(default=None, ge=1, le=10)
    lesson_kind: Optional[str] = None
    unlock_strategy: Optional[str] = None
    recommended_resources: List[Dict[str, Any]] = Field(default_factory=list)
    adaptation_metadata: Dict[str, Any] = Field(default_factory=dict)
    refinement: Dict[str, Any] = Field(default_factory=dict)
    recommended_chunk_ids: List[str] = Field(default_factory=list)
    status: Optional[str] = None
    last_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    confidence_updated_at: Optional[datetime] = None


class GeneratedLearningPathChapterResponse(BaseModel):
    chapter_id: str
    title: str
    lessons: List[GeneratedLearningPathLessonResponse]


class LearningPathGenerateRequest(BaseModel):
    subject_id: str
    goal: Optional[str] = Field(default=None, min_length=3, max_length=500)
    level: Optional[LevelEnum] = None


class GeneratedLearningPathResponse(BaseModel):
    path_id: str
    subject_id: str
    goal: str
    level: LevelEnum
    generated_at: Optional[datetime] = None
    chapters: List[GeneratedLearningPathChapterResponse]
    concept_graph: List[ConceptGraphNodeResponse] = Field(default_factory=list)
    concept_mastery: Dict[str, float] = Field(default_factory=dict)
    mastery_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    curriculum_source: str = "fallback"
    llm_status: Optional[LLMStatusResponse] = None
    message: str = ""


class LearningPathHistoryItemResponse(BaseModel):
    path_id: str
    subject_id: str
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


class AdaptiveLessonNextActionResponse(BaseModel):
    type: str
    recommended_difficulty: Optional[LevelEnum] = None
    recommended_bloom_levels: List[BloomLevelEnum] = Field(default_factory=list)
    target_chunk_ids: List[str] = Field(default_factory=list)
    target_concepts: List[str] = Field(default_factory=list)
    allow_llm: bool = False
    prefer_template: bool = True
    retry_strategy: Optional[
        Literal[
            "same_question",
            "paraphrase_question",
            "simplify_question",
            "explain_then_question",
        ]
    ] = None
    retry_count: int = 0
    weakest_concept: Optional[str] = None
    fail_streak: int = 0
    success_streak: int = 0
    reason: Optional[str] = None


class LessonProgressResponse(BaseModel):
    path_id: str
    lesson_id: str
    status: str
    is_locked: bool = False
    reason_locked: Optional[str] = None
    blocking_lesson_id: Optional[str] = None
    blocking_concepts: List[str] = Field(default_factory=list)
    missing_prerequisite_concepts: List[str] = Field(default_factory=list)
    prerequisite_mastery: Dict[str, float] = Field(default_factory=dict)
    bridge_recommendations: List[Dict[str, Any]] = Field(default_factory=list)
    mastery_threshold: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    auto_completed: bool = False
    last_confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    confidence_updated_at: Optional[datetime] = None
    attempt_id: Optional[str] = None
    accuracy: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    updated_mastery: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    mastery_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    completion_status: Optional[
        Literal["completed", "reinforce_required", "retry_required"]
    ] = None
    reinforce_required: bool = False
    retry_required: bool = False
    bloom_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    bloom_accuracy_by_level: Dict[str, float] = Field(default_factory=dict)
    concept_coverage_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    concept_coverage_rate: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    difficulty_weighted_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    confidence_score: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    weak_concepts: List[str] = Field(default_factory=list)
    next_action: Optional[AdaptiveLessonNextActionResponse] = None
    adaptive_next_quiz: Optional["AdaptiveQuizGenerationRequestResponse"] = None
    updated_at: datetime

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "path_id": "lp_001",
                "lesson_id": "lesson_03",
                "status": "in_progress",
                "is_locked": False,
                "reason_locked": "Cannot complete because quiz accuracy 40.00% < 75%. Please retry the quiz.",
                "blocking_lesson_id": None,
                "auto_completed": False,
                "last_confidence": 0.62,
                "attempt_id": "att_001",
                "accuracy": 0.4,
                "updated_mastery": 0.45,
                "mastery_score": 0.58,
                "completion_status": "reinforce_required",
                "reinforce_required": True,
                "retry_required": False,
                "bloom_score": 0.61,
                "bloom_accuracy_by_level": {
                    "remember": 1.0,
                    "understand": 0.5,
                    "apply": 0.33,
                },
                "concept_coverage_score": 0.5,
                "concept_coverage_rate": 0.5,
                "difficulty_weighted_score": 0.47,
                "confidence_score": 0.62,
                "weak_concepts": ["python_loops"],
                "next_action": {
                    "type": "review_same_chunk",
                    "recommended_difficulty": "beginner",
                    "recommended_bloom_levels": ["remember", "understand"],
                    "target_chunk_ids": ["chunk_a", "chunk_b"],
                    "target_concepts": ["python_loops"],
                    "allow_llm": False,
                    "prefer_template": True,
                    "retry_strategy": "simplify_question",
                    "retry_count": 3,
                    "weakest_concept": "python_loops",
                    "fail_streak": 3,
                    "success_streak": 0,
                    "reason": "Low accuracy; review weakest chunk(s)",
                },
                "adaptive_next_quiz": {
                    "lesson_id": "lesson_03",
                    "target_count": 4,
                    "recommended_difficulty": "beginner",
                    "recommended_bloom_levels": ["remember", "understand"],
                    "target_chunk_ids": ["chunk_a", "chunk_b"],
                    "target_concepts": ["python_loops"],
                    "retry_strategy": "simplify_question",
                    "retry_count": 3,
                    "explanation": "Xem lai giai thich ngan gon truoc khi lam cau hoi.",
                    "previous_question_ids": ["q_old_01", "q_old_02"],
                    "generation_strategy": {
                        "template_first": True,
                        "allow_llm": False,
                        "prefer_template": True,
                        "retry_strategy": "simplify_question",
                        "reuse_previous_question": False,
                        "paraphrase_question": False,
                        "add_explanation_before_question": False,
                    },
                    "attempt_accuracy": 0.4,
                },
                "updated_at": "2026-04-04T10:00:00Z",
            }
        }
    )


class AdaptiveQuizNextRequest(BaseModel):
    path_id: Optional[str] = None
    target_count: Optional[int] = Field(default=None, ge=1, le=20)


class AdaptiveQuizGenerationStrategyResponse(
    LessonQuestionGenerationStrategyRequest
):
    pass


class AdaptiveQuizNextActionPlanResponse(BaseModel):
    type: Literal["adaptive_quiz_next"] = "adaptive_quiz_next"
    recommended_difficulty: Optional[LevelEnum] = None
    recommended_bloom_levels: List[BloomLevelEnum] = Field(default_factory=list)
    target_chunk_ids: List[str] = Field(default_factory=list)
    target_concepts: List[str] = Field(default_factory=list)
    question_types: List[LessonQuestionTypeEnum] = Field(default_factory=list)
    policy_version: Optional[str] = None
    policy_bucket: Optional[str] = None
    why_this_quiz: Optional[str] = None


class AdaptiveQuizGenerationRequestResponse(BaseModel):
    lesson_id: str
    target_count: int = 0
    recommended_difficulty: Optional[LevelEnum] = None
    recommended_bloom_levels: List[BloomLevelEnum] = Field(default_factory=list)
    target_chunk_ids: List[str] = Field(default_factory=list)
    target_concepts: List[str] = Field(default_factory=list)
    retry_strategy: Optional[
        Literal[
            "same_question",
            "paraphrase_question",
            "simplify_question",
            "explain_then_question",
        ]
    ] = None
    retry_count: int = 0
    explanation: Optional[str] = None
    question_types: List[LessonQuestionTypeEnum] = Field(default_factory=list)
    allow_llm: bool = False
    prefer_template: bool = True
    policy_version: Optional[str] = None
    policy_bucket: Optional[str] = None
    why_this_quiz: Optional[str] = None
    previous_question_ids: List[str] = Field(default_factory=list)
    metadata: LessonQuestionGenerationMetadataRequest = Field(
        default_factory=LessonQuestionGenerationMetadataRequest
    )
    generation_strategy: AdaptiveQuizGenerationStrategyResponse = Field(
        default_factory=AdaptiveQuizGenerationStrategyResponse
    )
    attempt_accuracy: float = 0.0


class AdaptiveQuizNextResponse(BaseModel):
    lesson_id: str
    next_action: AdaptiveQuizNextActionPlanResponse
    generation_request: AdaptiveQuizGenerationRequestResponse
    generated: LessonQuestionGenerationResponse

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "lesson_id": "lesson_03",
                "next_action": {
                    "type": "adaptive_quiz_next",
                    "recommended_difficulty": "beginner",
                    "recommended_bloom_levels": ["remember", "understand"],
                    "target_chunk_ids": ["chunk_a", "chunk_b"],
                    "target_concepts": ["python_loops"],
                },
                "generation_request": {
                    "lesson_id": "lesson_03",
                    "target_count": 4,
                    "recommended_difficulty": "beginner",
                    "recommended_bloom_levels": ["remember", "understand"],
                    "target_chunk_ids": ["chunk_a", "chunk_b"],
                    "target_concepts": ["python_loops"],
                    "retry_strategy": "simplify_question",
                    "retry_count": 3,
                    "explanation": "Xem lai giai thich ngan gon truoc khi lam cau hoi.",
                    "previous_question_ids": ["q_old_01", "q_old_02"],
                    "metadata": {
                        "adaptive_quiz": True,
                        "path_id": "lp_001",
                        "target_chunk_ids": ["chunk_a", "chunk_b"],
                        "target_concepts": ["python_loops"],
                        "retry_strategy": "simplify_question",
                        "adaptive_explanation": "Xem lai giai thich ngan gon truoc khi lam cau hoi.",
                        "prefer_template": True,
                        "generation_reason": "adaptive_quiz_next",
                        "generation_strategy": {
                            "template_first": True,
                            "allow_llm": False,
                            "prefer_template": True,
                            "retry_strategy": "simplify_question",
                            "reuse_previous_question": False,
                            "paraphrase_question": False,
                            "add_explanation_before_question": False,
                        },
                    },
                    "generation_strategy": {
                        "template_first": True,
                        "allow_llm": False,
                        "prefer_template": True,
                        "retry_strategy": "simplify_question",
                        "reuse_previous_question": False,
                        "paraphrase_question": False,
                        "add_explanation_before_question": False,
                    },
                    "attempt_accuracy": 0.4,
                },
                "generated": {
                    "lesson_id": "lesson_03",
                    "status": "ok",
                    "generated_count": 4,
                    "saved_count": 4,
                    "question_ids": ["q_101", "q_102", "q_103", "q_104"],
                    "chunks_used": ["chunk_a", "chunk_b"],
                    "insufficient_data": False,
                    "reused_existing": False,
                    "existing_count": 0,
                    "sources": {
                        "template": 2,
                        "llm": 0,
                        "local_fallback": 2,
                        "existing_reuse": 0,
                    },
                    "fallback_used": True,
                    "cache_stats": {
                        "scope": "shared_template_claim_cache",
                        "entries": 42,
                        "hits": 6,
                        "misses": 2,
                        "stores": 2,
                        "requests": 8,
                        "request_hit_rate": 0.75,
                        "lifetime_hit_rate": 0.68,
                    },
                    "filtered_count": 1,
                    "message": "Generated adaptive quiz for the current weak concept.",
                },
            }
        }
    )


class AdaptiveQuizPlanResponse(BaseModel):
    generated: bool = False
    lesson_id: str
    question_ids: List[str] = Field(default_factory=list)
    question_count: int = 0
    target_concepts: List[str] = Field(default_factory=list)
    reused_targeted_questions: bool = False
    recommended_difficulty: Optional[LevelEnum] = None
    recommended_bloom_levels: List[BloomLevelEnum] = Field(default_factory=list)
    retry_strategy: Optional[
        Literal[
            "same_question",
            "paraphrase_question",
            "simplify_question",
            "explain_then_question",
        ]
    ] = None
    question_types: List[LessonQuestionTypeEnum] = Field(default_factory=list)
    adaptive_explanation: Optional[str] = None
    status: Optional[str] = None
    error: Optional[str] = None
    todo: Optional[str] = None

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "generated": True,
                "lesson_id": "lesson_03",
                "question_ids": ["q_101", "q_102", "q_103", "q_104"],
                "question_count": 4,
                "target_concepts": ["python_loops"],
                "reused_targeted_questions": False,
                "recommended_difficulty": "beginner",
                "recommended_bloom_levels": ["remember", "understand"],
                "retry_strategy": "simplify_question",
                "question_types": ["multiple_choice"],
                "adaptive_explanation": "Quiz adapted from learner state: target mastery=42%, accuracy=40%, fail streak=3.",
                "status": "ok",
            }
        }
    )


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


class ProgressSummaryPayloadResponse(BaseModel):
    average_confidence: Optional[float] = None
    average_mastery: Optional[float] = None
    total_concepts_started: Optional[int] = None
    total_concepts_completed: Optional[int] = None
    passed_lessons: Optional[int] = None
    lesson_count: Optional[int] = None

    model_config = ConfigDict(extra="allow")


class ProgressSummaryResponse(BaseModel):
    success: bool = True
    user_id: str
    summary: ProgressSummaryPayloadResponse = Field(
        default_factory=ProgressSummaryPayloadResponse
    )


class ProgressOverviewResponse(BaseModel):
    success: bool = True
    user_id: str
    overall_progress_percent: float = 0.0
    progress_bar: float = 0.0
    weekly_comparison_percent: float = 0.0
    summary: ProgressSummaryPayloadResponse = Field(
        default_factory=ProgressSummaryPayloadResponse
    )


class UserConfidenceOverviewDetailsResponse(BaseModel):
    base_confidence: float = 0.0
    recent_event_count: int = 0
    previous_event_count: int = 0
    recent_period_confidence: float = 0.0
    previous_period_confidence: float = 0.0

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "base_confidence": 0.62,
                "recent_event_count": 14,
                "previous_event_count": 11,
                "recent_period_confidence": 0.64,
                "previous_period_confidence": 0.58,
            }
        },
    )


class UserConfidenceOverviewResponse(BaseModel):
    success: bool = True
    user_id: str
    confidence: float
    level: Optional[LevelEnum] = None
    average_mastery: float = 0.0
    lesson_count: int = 0
    passed_lessons: int = 0
    recent_average_confidence: float = 0.0
    trend: str
    explanation: str
    details: UserConfidenceOverviewDetailsResponse = Field(
        default_factory=UserConfidenceOverviewDetailsResponse
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "success": True,
                "user_id": "u_001",
                "confidence": 0.62,
                "level": "beginner",
                "average_mastery": 0.0,
                "lesson_count": 0,
                "passed_lessons": 0,
                "recent_average_confidence": 0.64,
                "trend": "stable",
                "explanation": "Confidence duoc tong hop tu tien do hoc tap theo concept.",
                "details": {
                    "base_confidence": 0.62,
                    "recent_event_count": 14,
                    "previous_event_count": 11,
                    "recent_period_confidence": 0.64,
                    "previous_period_confidence": 0.58,
                },
            }
        }
    )


class ConceptProgressPayloadResponse(BaseModel):
    concept_id: Optional[int] = None
    mastery: Optional[float] = None
    confidence: Optional[float] = None
    success_rate: Optional[float] = None
    total_attempts: Optional[int] = None
    status: Optional[str] = None
    last_updated: Optional[datetime] = None

    model_config = ConfigDict(extra="allow")


class ConceptProgressResponse(BaseModel):
    success: bool = True
    user_id: str
    concept_id: int
    progress: Optional[ConceptProgressPayloadResponse] = None


class AskAnswerSourceResponse(BaseModel):
    resource_id: Optional[str] = None
    title: Optional[str] = None
    score: Optional[float] = None
    source: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class AskAnswerPayloadResponse(BaseModel):
    answer_text: str = ""
    answer_method: Optional[str] = None
    confidence: float = 0.0
    latency_ms: Optional[float] = None
    sources: List[AskAnswerSourceResponse] = Field(default_factory=list)

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "answer_text": "Vong lap for duyet qua tung phan tu trong mot sequence.",
                "answer_method": "direct_from_context",
                "confidence": 0.84,
                "latency_ms": 412.5,
                "sources": [
                    {
                        "resource_id": "res_001",
                        "title": "Python Loops Basics",
                        "score": 0.93,
                        "source": "manual",
                    }
                ],
            }
        },
    )


class AskConceptDetectedResponse(BaseModel):
    concept_id: Optional[int] = None
    concept_name: Optional[str] = None
    score: Optional[float] = None

    model_config = ConfigDict(extra="allow")


class AskAdaptivePracticeRecommendationResponse(BaseModel):
    practice_type: Optional[str] = None
    intensity: Optional[int] = None
    urgency: Optional[str] = None
    description: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class AskAdaptiveInfoResponse(BaseModel):
    mode: Optional[str] = None
    mastery: Optional[float] = None
    confidence: Optional[float] = None
    attempts: Optional[int] = None
    combined_score: Optional[float] = None
    can_unlock_next: Optional[bool] = None
    recommended_difficulty: Optional[int] = None
    practice_recommendation: Optional[AskAdaptivePracticeRecommendationResponse] = None
    timestamp: Optional[str] = None

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "mode": "normal",
                "mastery": 0.62,
                "confidence": 0.68,
                "attempts": 4,
                "combined_score": 0.65,
                "can_unlock_next": False,
                "recommended_difficulty": 5,
                "practice_recommendation": {
                    "practice_type": "spaced_review",
                    "intensity": 2,
                    "urgency": "optional",
                    "description": "Periodic review to maintain mastery",
                },
                "timestamp": "2026-04-04T10:00:00Z",
            }
        },
    )


class AskAdaptiveStatusResponse(BaseModel):
    success: bool
    user_id: str
    concept_id: int
    message: Optional[str] = None
    progress: Optional[ConceptProgressPayloadResponse] = None
    adaptive_summary: Optional[AskAdaptiveInfoResponse] = None


class AskConceptDetectionItemResponse(BaseModel):
    concept_id: Optional[int] = None
    concept_name: Optional[str] = None
    score: Optional[float] = None

    model_config = ConfigDict(extra="allow")


class AskDetectConceptsResponse(BaseModel):
    success: bool = True
    total: int = 0
    detected: List[AskConceptDetectionItemResponse] = Field(default_factory=list)


class AskDetectConceptsRequest(BaseModel):
    questions: List[str] = Field(default_factory=list, min_length=1, max_length=100)

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "questions": [
                    "For loop trong Python hoat dong nhu the nao?",
                    "Khi nao nen dung while loop?",
                ]
            }
        }
    )


class AskRecommendedConceptItemResponse(BaseModel):
    concept_id: Optional[int] = None
    concept_name: Optional[str] = None
    difficulty: Optional[int] = None
    topic: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class AskRecommendedConceptsResponse(BaseModel):
    success: bool = True
    user_id: str
    recommended: List[AskRecommendedConceptItemResponse] = Field(default_factory=list)


class AskHistoryItemResponse(BaseModel):
    id: Optional[str] = Field(default=None, alias="_id")
    question: str = ""
    answer: str = ""
    goal: Optional[str] = None
    level: Optional[str] = None
    concept_id: Optional[int] = None
    concept_name: Optional[str] = None
    confidence: Optional[float] = None
    timestamp: Optional[str] = None

    model_config = ConfigDict(populate_by_name=True, extra="allow")


class AskHistoryResponse(BaseModel):
    success: bool = True
    history: List[AskHistoryItemResponse] = Field(default_factory=list)
    total: int = 0
    limit: int = 0
    skip: int = 0


class BasicMessageResponse(BaseModel):
    success: bool = True
    message: str


# =========================
# ASK (AI Q&A)
# =========================
class AskRequest(BaseModel):
    """Main Q&A request."""

    user_id: str = Field(..., description="MongoDB ObjectId as string")
    question: str = Field(..., min_length=5, max_length=2000)
    goal: str = Field(..., min_length=3, max_length=500)
    level: LevelEnum
    subject_id: Optional[str] = None
    completed: Optional[List[str]] = None


class AskResponse(BaseModel):
    success: bool
    answer: AskAnswerPayloadResponse
    learning_path: Optional[List[LearningPathItemResponse]] = None
    concept_detected: Optional[AskConceptDetectedResponse] = None
    adaptive_info: Optional[AskAdaptiveInfoResponse] = None
    progress_updated: bool = False


# =========================
# ADAPTIVE LEARNING LOOP
# =========================
class LearningEventTypeEnum(str, Enum):
    lesson_opened = "lesson_opened"
    lesson_completed = "lesson_completed"
    resource_viewed = "resource_viewed"
    resource_finished = "resource_finished"
    quiz_started = "quiz_started"
    question_answered = "question_answered"
    quiz_submitted = "quiz_submitted"
    lesson_abandoned = "lesson_abandoned"
    retry_requested = "retry_requested"
    resource_opened = "resource_opened"
    resource_completed = "resource_completed"
    resource_abandoned = "resource_abandoned"
    resource_feedback_submitted = "resource_feedback_submitted"
    lesson_started = "lesson_started"
    lesson_retried = "lesson_retried"
    recommendation_clicked = "recommendation_clicked"


class AdaptiveActionEnum(str, Enum):
    resume_unfinished = "resume_unfinished"
    review_summary = "review_summary"
    reinforce_weak_concept = "reinforce_weak_concept"
    move_to_next_lesson = "move_to_next_lesson"


class AdaptivePriorityEnum(str, Enum):
    low = "low"
    medium = "medium"
    high = "high"


class AdaptiveRecommendationTypeEnum(str, Enum):
    resource = "resource"
    chunk = "chunk"
    lesson = "lesson"


class AdaptiveLoopActionEnum(str, Enum):
    UNLOCK_NEXT_LESSON = "UNLOCK_NEXT_LESSON"
    ASSIGN_REMEDIAL_RESOURCE = "ASSIGN_REMEDIAL_RESOURCE"
    GENERATE_REINFORCEMENT_QUIZ = "GENERATE_REINFORCEMENT_QUIZ"
    RECOMMEND_SHORT_RESOURCE = "RECOMMEND_SHORT_RESOURCE"
    REVIEW_WEAK_CONCEPT = "REVIEW_WEAK_CONCEPT"
    NO_ACTION = "NO_ACTION"


class LearningEventPayloadData(BaseModel):
    concept_id: Optional[str] = None
    concept: Optional[str] = None
    concept_ids: List[str] = Field(default_factory=list)
    question_id: Optional[str] = None
    resource_type: Optional[str] = None
    session_id: Optional[str] = None
    attempt_id: Optional[str] = None
    is_correct: Optional[bool] = None
    correct: Optional[bool] = None
    score: Optional[float] = None
    accuracy: Optional[float] = None
    question_count: Optional[int] = None
    total_questions: Optional[int] = None
    duration_minutes: Optional[float] = None
    session_duration_minutes: Optional[float] = None
    duration_seconds: Optional[float] = None
    duration_ms: Optional[float] = None

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "concept_ids": ["python_loops"],
                "question_id": "q_001",
                "resource_type": "text",
                "is_correct": False,
                "score": 0.4,
                "accuracy": 0.4,
                "question_count": 5,
                "duration_minutes": 8.5,
            }
        },
    )


class LearningEventIngestRequest(BaseModel):
    event_type: LearningEventTypeEnum
    user_id: Optional[str] = None
    path_id: Optional[str] = None
    lesson_id: Optional[str] = None
    resource_id: Optional[str] = None
    question_id: Optional[str] = None
    payload: LearningEventPayloadData = Field(
        default_factory=lambda: LearningEventPayloadData()
    )
    concept_ids: List[str] = Field(default_factory=list)
    metadata: LearningEventPayloadData = Field(
        default_factory=lambda: LearningEventPayloadData()
    )

    @model_validator(mode="after")
    def normalize_payload(self):
        payload_data = self.payload.model_dump(exclude_none=True)
        metadata_data = self.metadata.model_dump(exclude_none=True)
        if not payload_data and metadata_data:
            merged = dict(metadata_data)
        elif payload_data and not metadata_data:
            merged = dict(payload_data)
        else:
            merged = dict(metadata_data)
            merged.update(payload_data)
        self.payload = LearningEventPayloadData(**merged)
        self.metadata = LearningEventPayloadData(**merged)
        return self


class LearningEventResponse(BaseModel):
    event_id: str
    user_id: str
    event_type: LearningEventTypeEnum
    path_id: Optional[str] = None
    lesson_id: Optional[str] = None
    resource_id: Optional[str] = None
    question_id: Optional[str] = None
    payload: LearningEventPayloadData = Field(
        default_factory=lambda: LearningEventPayloadData()
    )
    concept_ids: List[str] = Field(default_factory=list)
    metadata: LearningEventPayloadData = Field(
        default_factory=lambda: LearningEventPayloadData()
    )
    created_at: datetime


class LearnerStateSnapshotResponse(BaseModel):
    snapshot_id: Optional[str] = None
    user_id: str
    path_id: Optional[str] = None
    current_lesson_id: Optional[str] = None
    mastery_by_concept: Dict[str, float] = Field(default_factory=dict)
    engagement_score: float = 0.0
    quiz_accuracy: float = 0.0
    completion_rate: float = 0.0
    avg_session_duration: float = 0.0
    retry_count: int = 0
    fail_streak: int = 0
    fatigue_score: float = 0.0
    risk_level: str = "low"
    preferred_resource_type: Optional[str] = None
    updated_at: Optional[datetime] = None
    snapshot_time: Optional[datetime] = None
    confidence_by_concept: Dict[str, float] = Field(default_factory=dict)
    unfinished_resources: int = 0
    quiz_fail_streak: int = 0
    learning_velocity: float = 0.0
    recent_active_days: int = 0
    preferred_time_window: str = "evening"
    frustration_score: float = 0.0
    recovery_need_flag: bool = False
    current_focus_concepts: List[str] = Field(default_factory=list)
    needs_reinforcement: bool = False
    last_event_type: Optional[str] = None
    last_recommended_action: Optional[str] = None


class AdaptiveRecommendationItemResponse(BaseModel):
    resource_id: Optional[str] = None
    lesson_id: Optional[str] = None
    title: str = ""
    summary: Optional[str] = None
    type: Optional[str] = None
    topic: Optional[str] = None
    level: Optional[str] = None
    url: Optional[str] = None
    estimated_time: Optional[int] = None
    estimated_read_time: Optional[int] = None
    reason: Optional[str] = None

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "resource_id": "res_001",
                "title": "Python Loops Refresher",
                "type": "text",
                "topic": "python_loops",
                "level": "beginner",
                "url": "https://example.com/python-loops",
                "estimated_time": 8,
                "reason": "Review material for the weakest concept before continuing.",
            }
        },
    )


class AdaptiveNextStepMetadataResponse(BaseModel):
    quiz: Optional["AdaptiveQuizPlanResponse"] = None
    next_lesson_id: Optional[str] = None
    next_lesson_title: Optional[str] = None
    unlock_supported: Optional[bool] = None
    current_lesson_status: Optional[str] = None
    next_lesson_unlocked: Optional[bool] = None
    todo: Optional[str] = None

    model_config = ConfigDict(extra="allow")


class AdaptiveNextActionResponse(BaseModel):
    user_id: str
    next_best_action: AdaptiveActionEnum
    reason: str
    priority: AdaptivePriorityEnum
    recommended_mode: Literal[
        "continue_learning",
        "reinforce_weaknesses",
        "learn_new",
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
        ]
    ] = None
    items: List[AdaptiveRecommendationItemResponse] = Field(default_factory=list)
    reason: str
    target_concepts: List[str] = Field(default_factory=list)
    estimated_total_time: int = 0
    lesson_id: Optional[str] = None
    resource_id: Optional[str] = None


class AdaptivePathScopeBackfillRequest(BaseModel):
    user_id: Optional[str] = None
    dry_run: bool = True
    limit: Optional[int] = Field(default=None, ge=1)
    collection: Literal[
        "all",
        "lesson_quiz_attempts",
        "user_learning_state",
    ] = "all"

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": "u_001",
                "dry_run": True,
                "limit": 100,
                "collection": "lesson_quiz_attempts",
            }
        }
    )


class AdaptivePathScopeBackfillCollectionResult(BaseModel):
    collection: str
    processed: int = 0
    updated: int = 0
    skipped: int = 0
    dry_run: bool = True
    reasons: Dict[str, int] = Field(default_factory=dict)
    items: List[Dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class AdaptivePathScopeBackfillSummaryResponse(BaseModel):
    processed: int = 0
    updated: int = 0
    skipped: int = 0


class AdaptivePathScopeBackfillResponse(BaseModel):
    job: Literal["adaptive_path_scope"] = "adaptive_path_scope"
    dry_run: bool = True
    user_id: Optional[str] = None
    collection: Literal[
        "all",
        "lesson_quiz_attempts",
        "user_learning_state",
    ] = "all"
    summary: AdaptivePathScopeBackfillSummaryResponse = Field(
        default_factory=AdaptivePathScopeBackfillSummaryResponse
    )
    results: List[AdaptivePathScopeBackfillCollectionResult] = Field(
        default_factory=list
    )


class AdaptivePathScopeAuditCollectionResult(BaseModel):
    collection: str
    pending: int = 0
    resolvable: int = 0
    ambiguous: int = 0
    unmatched: int = 0
    reasons: Dict[str, int] = Field(default_factory=dict)
    items: List[Dict[str, Any]] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")


class AdaptivePathScopeAuditSummaryResponse(BaseModel):
    pending: int = 0
    resolvable: int = 0
    ambiguous: int = 0
    unmatched: int = 0


class AdaptivePathScopeAuditResponse(BaseModel):
    job: Literal["adaptive_path_scope_audit"] = "adaptive_path_scope_audit"
    user_id: Optional[str] = None
    collection: Literal[
        "all",
        "lesson_quiz_attempts",
        "user_learning_state",
    ] = "all"
    summary: AdaptivePathScopeAuditSummaryResponse = Field(
        default_factory=AdaptivePathScopeAuditSummaryResponse
    )
    results: List[AdaptivePathScopeAuditCollectionResult] = Field(
        default_factory=list
    )

class AdaptiveRecomputeRequest(BaseModel):
    user_id: Optional[str] = None
    event_id: Optional[str] = None


class AdaptiveRecomputeResponse(BaseModel):
    user_id: str
    snapshot: LearnerStateSnapshotResponse
    next_action: AdaptiveNextActionResponse


class AdaptiveNextStepRequest(BaseModel):
    user_id: str
    path_id: str
    lesson_id: str


class AdaptiveNextStepResponse(BaseModel):
    action: AdaptiveLoopActionEnum
    reason: str
    target_concepts: List[str] = Field(default_factory=list)
    resources: List[AdaptiveRecommendationItemResponse] = Field(default_factory=list)
    should_generate_quiz: bool = False
    should_unlock_next: bool = False
    recommended_difficulty: Optional[LevelEnum] = None
    recommended_bloom_levels: List[BloomLevelEnum] = Field(default_factory=list)
    retry_strategy: Optional[
        Literal[
            "same_question",
            "paraphrase_question",
            "simplify_question",
            "explain_then_question",
        ]
    ] = None
    question_types: List[LessonQuestionTypeEnum] = Field(default_factory=list)
    adaptive_explanation: Optional[str] = None
    quiz: Optional[AdaptiveQuizPlanResponse] = None
    snapshot: LearnerStateSnapshotResponse
    metadata: AdaptiveNextStepMetadataResponse = Field(
        default_factory=AdaptiveNextStepMetadataResponse
    )

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "action": "GENERATE_REINFORCEMENT_QUIZ",
                "reason": "The lesson is not mastered yet, so a reinforcement quiz should come next.",
                "target_concepts": ["python_loops"],
                "resources": [],
                "should_generate_quiz": True,
                "should_unlock_next": False,
                "recommended_difficulty": "beginner",
                "recommended_bloom_levels": ["remember", "understand"],
                "retry_strategy": "simplify_question",
                "question_types": ["multiple_choice"],
                "adaptive_explanation": "Quiz adapted from learner state: target mastery=42%, accuracy=40%, fail streak=3.",
                "quiz": {
                    "generated": True,
                    "lesson_id": "lesson_03",
                    "question_ids": ["q_101", "q_102", "q_103", "q_104"],
                    "question_count": 4,
                    "target_concepts": ["python_loops"],
                    "reused_targeted_questions": False,
                    "recommended_difficulty": "beginner",
                    "recommended_bloom_levels": ["remember", "understand"],
                    "retry_strategy": "simplify_question",
                    "question_types": ["multiple_choice"],
                    "adaptive_explanation": "Quiz adapted from learner state: target mastery=42%, accuracy=40%, fail streak=3.",
                    "status": "ok",
                },
                "snapshot": {
                    "user_id": "u_001",
                    "path_id": "lp_001",
                    "current_lesson_id": "lesson_03",
                    "mastery_by_concept": {"python_loops": 0.42},
                    "engagement_score": 0.58,
                    "quiz_accuracy": 0.4,
                    "completion_rate": 0.67,
                    "avg_session_duration": 8.5,
                    "retry_count": 2,
                    "fail_streak": 3,
                    "fatigue_score": 0.44,
                    "risk_level": "medium",
                    "preferred_resource_type": "text",
                    "current_focus_concepts": ["python_loops"],
                    "needs_reinforcement": True,
                },
                "metadata": {},
            }
        }
    )


class AdaptiveExplanationResponse(BaseModel):
    user_id: str
    path_id: str
    lesson_id: str
    action: AdaptiveLoopActionEnum
    reason: str
    target_concepts: List[str] = Field(default_factory=list)
    explanation: str
    recommended_difficulty: Optional[LevelEnum] = None
    recommended_bloom_levels: List[BloomLevelEnum] = Field(default_factory=list)
    retry_strategy: Optional[
        Literal[
            "same_question",
            "paraphrase_question",
            "simplify_question",
            "explain_then_question",
        ]
    ] = None
    question_types: List[LessonQuestionTypeEnum] = Field(default_factory=list)
    adaptive_explanation: Optional[str] = None
    quiz: Optional[AdaptiveQuizPlanResponse] = None
    snapshot: LearnerStateSnapshotResponse

    model_config = ConfigDict(
        json_schema_extra={
            "example": {
                "user_id": "u_001",
                "path_id": "lp_001",
                "lesson_id": "lesson_03",
                "action": "GENERATE_REINFORCEMENT_QUIZ",
                "reason": "The lesson is not mastered yet, so a reinforcement quiz should come next.",
                "target_concepts": ["python_loops"],
                "explanation": "The system chose GENERATE_REINFORCEMENT_QUIZ because the lesson is not mastered yet. Current accuracy is 40%, engagement is 58%, and fatigue is 44%. Focus concept: python_loops. Quiz adapted from learner state: target mastery=42%, accuracy=40%, fail streak=3.",
                "recommended_difficulty": "beginner",
                "recommended_bloom_levels": ["remember", "understand"],
                "retry_strategy": "simplify_question",
                "question_types": ["multiple_choice"],
                "adaptive_explanation": "Quiz adapted from learner state: target mastery=42%, accuracy=40%, fail streak=3.",
                "quiz": {
                    "generated": True,
                    "lesson_id": "lesson_03",
                    "question_ids": ["q_101", "q_102", "q_103", "q_104"],
                    "question_count": 4,
                    "target_concepts": ["python_loops"],
                    "reused_targeted_questions": False,
                    "recommended_difficulty": "beginner",
                    "recommended_bloom_levels": ["remember", "understand"],
                    "retry_strategy": "simplify_question",
                    "question_types": ["multiple_choice"],
                    "adaptive_explanation": "Quiz adapted from learner state: target mastery=42%, accuracy=40%, fail streak=3.",
                    "status": "ok",
                },
                "snapshot": {
                    "user_id": "u_001",
                    "path_id": "lp_001",
                    "current_lesson_id": "lesson_03",
                    "mastery_by_concept": {"python_loops": 0.42},
                    "engagement_score": 0.58,
                    "quiz_accuracy": 0.4,
                    "completion_rate": 0.67,
                    "avg_session_duration": 8.5,
                    "retry_count": 2,
                    "fail_streak": 3,
                    "fatigue_score": 0.44,
                    "risk_level": "medium",
                    "preferred_resource_type": "text",
                    "current_focus_concepts": ["python_loops"],
                    "needs_reinforcement": True,
                },
            }
        }
    )


LessonProgressResponse.model_rebuild()
