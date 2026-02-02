from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime

# ===== USERS =====
class UserCreate(BaseModel):
    name: str
    email: str
    level: str

class UserResponse(BaseModel):
    user_id: int
    name: str
    email: str
    level: str
    created_at: datetime


# ===== LEARNER PROFILE =====
class LearnerProfileCreate(BaseModel):
    learning_goal: str
    preferred_style: Optional[str] = None
    time_constraint: Optional[str] = None


# ===== COURSE =====
class CourseCreate(BaseModel):
    course_name: str
    description: Optional[str] = None


# ===== CONCEPT =====
class ConceptCreate(BaseModel):
    course_id: int
    concept_name: str
    topic: str
    difficulty: int


# ===== PREREQUISITE =====
class PrerequisiteCreate(BaseModel):
    from_concept_id: int
    to_concept_id: int


# ===== RESOURCE =====
class ResourceCreate(BaseModel):
    title: str
    content: str
    source: str
    url: Optional[str] = None
    concept_id: int


class ResourceMetadataCreate(BaseModel):
    pedagogy_type: str
    bloom_level: str


# ===== PROGRESS =====
class ProgressUpdate(BaseModel):
    user_id: int
    concept_id: int
    success: bool


# ===== LEARNING PATH =====
class LearningPathResponse(BaseModel):
    path_id: int
    goal: str
    level: str
    generated_at: datetime
    items: List[dict]


# ===== ASK =====
class AskRequest(BaseModel):
    user_id: int
    question: str
    goal: str
    level: str

class AskResponse(BaseModel):
    answer: dict
    learning_path: List[dict]


# ===== RESOURCE IMPORT =====
class ResourceImport(BaseModel):
    title: str
    content: str
    source: str                # pdf / youtube / web
    url: Optional[str] = None
    concept_id: int
    pedagogy_type: Optional[str] = None
    bloom_level: Optional[str] = None


class ResourceImportRequest(BaseModel):
    resources: List[ResourceImport]
