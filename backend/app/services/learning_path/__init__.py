"""Learning-path package."""

__all__ = [
    "UnifiedLearningPathService",
    "learning_path_service",
]


def __getattr__(name: str):
    if name in __all__:
        from .generator import UnifiedLearningPathService, learning_path_service

        return {
            "UnifiedLearningPathService": UnifiedLearningPathService,
            "learning_path_service": learning_path_service,
        }[name]
    raise AttributeError(name)
