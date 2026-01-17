def generate_learning_path(goal: str, level: str):
    if level == "Beginner":
        return [
            f"Giới thiệu {goal}",
            "Kiến thức nền tảng",
            "Thực hành cơ bản",
            "Bài tập ứng dụng",
            "Ôn tập & đánh giá"
        ]
    return ["Lộ trình nâng cao"]
