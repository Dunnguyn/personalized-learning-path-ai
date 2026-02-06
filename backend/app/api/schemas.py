from pydantic import BaseModel, EmailStr, Field, ConfigDict
from typing import List, Optional
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


class LearningPathResponse(BaseModel):
    path_id: str = Field(..., description="UUID")
    user_id: str = Field(..., description="MongoDB ObjectId")
    goal: str
    level: LevelEnum
    generated_at: datetime
    recommended_path: List[LearningPathItemResponse]
    message: str = ""


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