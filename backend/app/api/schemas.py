from pydantic import BaseModel, Field
from typing import List, Optional


# ===== USER =====
class UserCreate(BaseModel):
    name: str
    email: str
    level: str = Field(example="beginner")


# ===== LEARNING PATH =====
class LearningPathRequest(BaseModel):
    goal: str = Field(example="Python Backend")
    level: str = Field(example="beginner")
    completed_concepts: List[str] = []


class LearningPathResponse(BaseModel):
    goal: str
    level: str
    recommended_path: List[str]


# ===== PROGRESS =====
class ProgressUpdate(BaseModel):
    user_id: str
    concept: str
    status: str = Field(example="completed")


# ===== RESOURCE =====
class Resource(BaseModel):
    title: str
    url: str
    topic: str

class ResourceImport(BaseModel):
    title: str
    content: str
    topic: str
    level: str = "beginner"
    url: Optional[str] = None


class ResourceImportRequest(BaseModel):
    resources: List[ResourceImport]