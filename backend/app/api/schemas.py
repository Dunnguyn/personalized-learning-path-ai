from pydantic import BaseModel, EmailStr, Field
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
    name: str
    email: EmailStr
    password: str
    level: LevelEnum


class UserResponse(BaseModel):
    user_id: int
    name: str
    email: EmailStr
    level: LevelEnum
    created_at: datetime

# =========================
# LEARNER PROFILE
# =========================
class LearnerProfileCreate(BaseModel):
    learning_goal: str
    preferred_style: Optional[str] = None
    time_constraint: Optional[str] = None


# =========================
# COURSE
# =========================
class CourseCreate(BaseModel):
    course_name: str
    description: Optional[str] = None


class CourseResponse(CourseCreate):
    course_id: int


# =========================
# CONCEPT
# =========================
class ConceptCreate(BaseModel):
    course_id: int
    concept_name: str
    topic: str
    difficulty: int


class ConceptResponse(ConceptCreate):
    concept_id: int


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
    title: str
    content: str
    source: SourceEnum              # pdf / youtube / web
    topic: str                      # python / fastapi / database
    level: LevelEnum                # beginner / intermediate / advanced
    concept_id: int
    url: Optional[str] = None


class ResourceResponse(ResourceCreate):
    resource_id: int
    created_at: datetime


class ResourceMetadataCreate(BaseModel):
    pedagogy_type: Optional[PedagogyEnum] = None   # video / text / quiz
    bloom_level: Optional[str] = None     # remember / apply / analyze


# =========================
# RESOURCE IMPORT (BATCH)
# =========================
class ResourceImport(BaseModel):
    title: str
    content: str
    source: SourceEnum
    url: Optional[str] = None
    concept_id: int
    pedagogy_type: Optional[PedagogyEnum] = None
    bloom_level: Optional[str] = None


class ResourceImportRequest(BaseModel):
    resources: List[ResourceImport]


# =========================
# PROGRESS
# =========================
class ProgressUpdate(BaseModel):
    user_id: int
    concept_id: int
    mastery: float = Field(ge=0, le=1)
    confidence: float = Field(ge=0, le=1)
    total_attempts: int = Field(ge=0)


class ProgressUpdateResponse(BaseModel):
    user_id: int
    concept_id: int
    mastery: float
    confidence: float
    total_attempts: int
    updated_at: datetime


# =========================
# LEARNING PATH
# =========================
class LearningPathItemResponse(BaseModel):
    concept_id: int
    concept_name: str
    difficulty: int
    bloom_level: Optional[str]
    mode: str
    priority_score: float
    resources: list


class LearningPathResponse(BaseModel):
    path_id: str
    user_id: int
    goal: str
    level: LevelEnum
    generated_at: datetime
    recommended_path: List[LearningPathItemResponse]


# =========================
# ASK (AI Q&A)
# =========================
class AskRequest(BaseModel):
    user_id: int
    question: str
    goal: str
    level: LevelEnum
    completed: Optional[List[str]] = None


class AskResponse(BaseModel):
    answer: dict
    learning_path: List[LearningPathItemResponse]