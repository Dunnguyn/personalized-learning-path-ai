"""
Resource import feature package.

This package groups the learning-material ingestion flows used by the backend:
- manual and batch resource import
- PDF extraction and embedding
- YouTube transcript import
- YouTube fallback summarization
"""

from .batch import (
    create_resource_indexes,
    delete_duplicate_resources,
    import_resource,
    import_resources,
    validate_resource,
)
from .pdf import import_pdf
from .youtube import import_youtube, import_youtube_batch
from .youtube_summary import summarize_youtube_video, summarize_youtube_videos_batch

__all__ = [
    "create_resource_indexes",
    "delete_duplicate_resources",
    "import_pdf",
    "import_resource",
    "import_resources",
    "import_youtube",
    "import_youtube_batch",
    "summarize_youtube_video",
    "summarize_youtube_videos_batch",
    "validate_resource",
]
