def generate_learning_path(goal: str, level: str):
    if level.lower() == "beginner":
        return [
            f"Giới thiệu về {goal}",
            f"Kiến thức nền tảng {goal}",
            "Thực hành cơ bản",
            "Bài tập ứng dụng",
            "Ôn tập và đánh giá"
        ]
    else:
        return [
            f"{goal} nâng cao",
            "Dự án thực tế",
            "Tối ưu và mở rộng"
        ]


def recommend_resources(concept: str):
    return [
        f"Video học {concept}",
        f"Tài liệu PDF về {concept}",
        f"Bài viết chuyên sâu {concept}"
    ]
