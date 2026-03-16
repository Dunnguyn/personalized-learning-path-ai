from __future__ import annotations

import logging
import os
import random
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, Iterable, List, Mapping, Optional

from backend.app.database.mongo import get_db
from backend.app.services.progress_tracking.confidence import (
    calculate_confidence_score,
    record_confidence_event,
    upsert_lesson_confidence_progress,
)
from backend.app.services.question_generation.generator import generate_questions_for_lesson
from backend.app.services.question_generation.pipeline import generate_lesson_questions_with_llm

logger = logging.getLogger(__name__)


# =====================================================
# ANALYSIS
# =====================================================
# - Each lesson needs a pre-generated bank of 20 questions.
# - Questions come from lesson concepts + rule-based NLP + Bloom templates.
# - When a learner starts a quiz, select 10 random questions from the 20 stored ones.
# - Each submission is recorded as a separate attempt.
# - If a learner does not pass, they can create another attempt and receive another random set.
# - This service focuses only on question bank, attempt creation, and grading.


# =====================================================
# CONFIG
# =====================================================
QUESTION_BANK_SIZE = int(os.getenv("LESSON_QUESTION_BANK_SIZE", "20"))
QUIZ_ATTEMPT_SIZE = int(os.getenv("LESSON_QUIZ_ATTEMPT_SIZE", "10"))
PASS_THRESHOLD_CORRECT_COUNT = os.getenv("PASS_THRESHOLD_CORRECT_COUNT")
PASS_THRESHOLD_SCORE_PERCENT = float(os.getenv("PASS_THRESHOLD_SCORE_PERCENT", "80"))
LESSON_QUESTION_GENERATION_MODE = os.getenv("LESSON_QUESTION_GENERATION_MODE", "hybrid").lower()


# =====================================================
# SCHEMA / DATA MODEL
# =====================================================
@dataclass
class Question:
    """
    Stored question inside the lesson question bank.

    Required business fields:
    - question_id
    - lesson_id
    - concept
    - relation_type
    - question_text
    - answer
    - template_id

    Extra fields (`related_concepts`, `options`, `correct_option`) help quiz delivery.
    """

    question_id: str
    lesson_id: str
    concept: str
    relation_type: str
    question_text: str
    answer: str
    template_id: str
    bloom_level: str = "remember"
    difficulty: int = 1
    related_concepts: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    source_excerpt: str = ""
    source_chunk_id: Optional[str] = None
    options: List[Dict[str, str]] = field(default_factory=list)
    correct_option: str = "A"


@dataclass
class LessonQuestionBank:
    lesson_id: str
    chapter_id: str
    concept_list: List[Dict[str, str]]
    total_questions: int
    questions: List[Question]
    created_at: datetime
    updated_at: datetime


@dataclass
class UserLessonAttempt:
    attempt_id: str
    user_id: str
    lesson_id: str
    attempt_number: int
    selected_question_ids: List[str]
    score: float
    correct_count: int
    is_passed: bool
    confidence_score: float
    created_at: datetime
    submitted_at: Optional[datetime] = None
    user_answers: Dict[str, str] = field(default_factory=dict)


# =====================================================
# PSEUDOCODE
# =====================================================
# generate_and_store_questions(lesson_id):
# 1. Resolve lesson context -> chapter_id, concept_list.
# 2. Call generate_questions_for_lesson(lesson_id) from the rule-based Bloom generator.
# 3. Convert generated items to question bank questions.
# 4. Remove duplicates and distribute across lesson concepts.
# 5. Keep up to 20 high-quality questions.
# 6. Store/replace lesson question bank in DB.
#
# create_lesson_quiz_attempt(user_id, lesson_id):
# 1. Load question bank for lesson_id.
# 2. Validate that bank has enough questions.
# 3. Randomly choose 10 question IDs from the stored 20 questions.
# 4. Create new attempt document.
# 5. Return attempt metadata + selected questions without answers.
#
# submit_lesson_quiz(attempt_id, user_answers):
# 1. Load attempt and the lesson question bank.
# 2. For each selected question, compare learner answer with correct answer.
# 3. Count correct answers and compute score.
# 4. Evaluate pass threshold.
# 5. Update attempt with score, correct_count, is_passed, submitted_at.
# 6. Return grading result.


# =====================================================
# HELPERS
# =====================================================
def _get_pass_threshold_count(total_questions: int) -> int:
    if PASS_THRESHOLD_CORRECT_COUNT:
        return max(1, min(total_questions, int(PASS_THRESHOLD_CORRECT_COUNT)))
    return max(1, min(total_questions, int(total_questions * (PASS_THRESHOLD_SCORE_PERCENT / 100.0) + 0.9999)))


def _sanitize_question_for_delivery(question: Question) -> Dict:
    payload = asdict(question)
    payload.pop("answer", None)
    payload.pop("correct_option", None)
    return payload


def _select_diverse_quiz_questions(questions: List[Question], attempt_size: int, rng: random.Random) -> List[Question]:
    bloom_buckets: Dict[str, List[Question]] = {}
    for question in questions:
        bloom_buckets.setdefault(question.bloom_level, []).append(question)

    selected: List[Question] = []
    selected_ids = set()

    for bloom_level in sorted(bloom_buckets.keys()):
        bucket = bloom_buckets[bloom_level][:]
        rng.shuffle(bucket)
        if not bucket:
            continue
        question = bucket.pop(0)
        selected.append(question)
        selected_ids.add(question.question_id)
        bloom_buckets[bloom_level] = bucket
        if len(selected) >= attempt_size:
            return selected[:attempt_size]

    remaining_pool = [item for bucket in bloom_buckets.values() for item in bucket]
    rng.shuffle(remaining_pool)
    for question in remaining_pool:
        if len(selected) >= attempt_size:
            break
        if question.question_id in selected_ids:
            continue
        selected.append(question)
        selected_ids.add(question.question_id)

    return selected[:attempt_size]


def _fallback_answer_text(item: Dict) -> str:
    concept = item.get("concept", "")
    related = item.get("related_concepts", []) or [concept]
    relation_type = item.get("relation_type", "definition")
    bloom_level = str(item.get("bloom_level", "remember"))

    if bloom_level == "remember":
        return f"{concept} la khai niem can nho dung va nhan dien dung trong bai hoc."
    if bloom_level == "understand":
        return f"{concept} quan trong vi no giai thich duoc vai tro va y nghia trong bai hoc."
    if bloom_level == "apply":
        context = related[1] if len(related) > 1 else concept
        return f"{concept} duoc ap dung truc tiep khi giai quyet bai toan trong {context}."
    if bloom_level == "analyze" and len(related) >= 2:
        return f"Can phan tich cach {related[0]} tac dong den {related[1]} thong qua moi lien he kien thuc."
    if bloom_level == "evaluate" and len(related) >= 2:
        return f"Can chon {related[0]} hay {related[1]} dua tren boi canh, muc tieu va dieu kien ap dung."
    if bloom_level == "create":
        return f"Mot dap an tot can de xuat duoc vi du hoac cach cai tien hop ly cho {concept}."

    if relation_type == "prerequisite" and len(related) >= 2:
        return f"{related[0]} la kien thuc can hoc truoc de hieu {related[1]}."
    if relation_type == "used_in" and len(related) >= 2:
        return f"{related[0]} duoc ung dung trong {related[1]}."
    if relation_type == "part_of" and len(related) >= 2:
        return f"{related[0]} la mot thanh phan cua {related[1]}."
    if relation_type == "example_of" and len(related) >= 2:
        return f"{related[0]} la mot vi du tieu bieu cho {related[1]}."
    if relation_type == "related_to" and len(related) >= 2:
        return f"{related[0]} co moi lien he truc tiep voi {related[1]}."
    if relation_type == "comparison" and len(related) >= 2:
        return f"{related[0]} va {related[1]} khac nhau ve vai tro hoac cach ap dung."
    return f"{concept} la mot khai niem cot loi cua bai hoc."


def _fallback_distractors(item: Dict) -> List[str]:
    concept = item.get("concept", "")
    related = item.get("related_concepts", []) or [concept]
    other = related[1] if len(related) > 1 else concept
    relation_type = item.get("relation_type", "definition")
    bloom_level = str(item.get("bloom_level", "remember"))

    bloom_mapping = {
        "remember": [
            f"{concept} chi can nho ten ma khong can biet noi dung.",
            f"{concept} khong thuoc bai hoc nay.",
            f"{concept} khong co dac diem nao dang chu y.",
        ],
        "understand": [
            f"{concept} khong co vai tro nao ro rang trong bai hoc.",
            f"{concept} khong can giai thich vi y nghia cua no khong quan trong.",
            f"{concept} chi la ten goi, khong can mo ta cach hoat dong.",
        ],
        "apply": [
            f"{concept} khong the ap dung trong bat ky boi canh nao.",
            f"{other} hoan toan khong can den {concept}.",
            f"{concept} chi dung de hoc thuoc, khong dung de thuc hanh.",
        ],
        "analyze": [
            f"{concept} va {other} khong can phan tich moi lien he.",
            f"Chi can hoc rieng tung khai niem ma khong can xet tac dong qua lai.",
            f"{concept} khong anh huong gi den {other} trong moi truong nao.",
        ],
        "evaluate": [
            f"Luon chon {concept} trong moi tinh huong ma khong can so sanh.",
            f"{concept} va {other} giong nhau hoan toan nen khong can danh gia.",
            f"Khong can can nhac boi canh khi quyet dinh giua {concept} va {other}.",
        ],
        "create": [
            f"Khong the tao vi du hay cai tien nao lien quan den {concept}.",
            f"Chi can lap lai dung nguyen van ly thuyet ve {concept}.",
            f"{concept} khong the dua vao tinh huong moi hoac he thong thuc te.",
        ],
    }
    if bloom_level in bloom_mapping:
        return bloom_mapping[bloom_level]

    mapping = {
        "prerequisite": [
            f"{concept} khong anh huong den viec hoc {other}.",
            f"{other} can hoc truoc ma khong can biet {concept}.",
            f"{concept} chi la mot vi du phu, khong phai kien thuc nen tang.",
        ],
        "used_in": [
            f"{concept} khong duoc su dung trong {other}.",
            f"{other} khong can den {concept} de ap dung.",
            f"{concept} va {other} thuoc hai chu de tach biet.",
        ],
        "part_of": [
            f"{concept} khong nam trong cau truc cua {other}.",
            f"{other} co the hieu day du ma khong can {concept}.",
            f"{concept} la mot chu de ngoai le, khong phai thanh phan.",
        ],
        "related_to": [
            f"{concept} khong lien quan den {other}.",
            f"{concept} va {other} khong co diem chung trong bai hoc.",
            f"{other} thuoc mot noi dung khac, khong can xet {concept}.",
        ],
        "example_of": [
            f"{concept} khong phai vi du cua {other}.",
            f"{other} khong lien quan den cach minh hoa bang {concept}.",
            f"{concept} va {other} thuoc hai nhom hoan toan tach biet.",
        ],
        "comparison": [
            f"{concept} va {other} hoan toan giong nhau, khong can phan biet.",
            f"{concept} va {other} khong the dat canh de so sanh.",
            f"Chi can hoc mot trong hai vi {concept} va {other} la mot.",
        ],
    }
    return mapping.get(
        relation_type,
        [
            f"{concept} khong xuat hien trong bai hoc nay.",
            f"{concept} chi can hoc thuoc ten goi, khong can hieu noi dung.",
            f"{concept} thuoc mot chu de khac, khong lien quan bai hoc.",
        ],
    )


def _build_answer_payload(item: Dict) -> tuple[str, List[str]]:
    concept = str(item.get("concept", "")).strip()
    bloom_level = str(item.get("bloom_level", "remember")).strip().lower()
    concept_type = str(item.get("concept_type", "definition_concept")).strip().lower()

    templates: Dict[str, Dict[str, Dict[str, List[str] | str]]] = {
        "definition_concept": {
            "remember": {
                "answer": f"{concept} la khai niem can duoc nhan dien dung ve y nghia co ban trong bai hoc.",
                "distractors": [
                    f"{concept} chi la mot tu khoa de nho ten, khong co dinh nghia cu the.",
                    f"{concept} khong can hieu noi dung ma chi can lap lai ten goi.",
                    f"{concept} la noi dung ben ngoai pham vi bai hoc nen khong can nhan dien.",
                ],
            },
            "understand": {
                "answer": f"{concept} can duoc giai thich thong qua vai tro, y nghia va cach no xuat hien trong bai hoc.",
                "distractors": [
                    f"{concept} khong can giai thich vi khong anh huong den viec hieu bai.",
                    f"{concept} chi la nhan de trang tri, khong can mo ta them.",
                    f"{concept} khong lien quan den bat ky noi dung nao can hieu sau hon.",
                ],
            },
            "apply": {
                "answer": f"{concept} co the duoc ap dung khi can nhan dien va su dung dung khai niem trong tinh huong thuc te.",
                "distractors": [
                    f"{concept} chi dung de hoc thuoc, khong dung trong tinh huong thuc te.",
                    f"{concept} khong the ap dung vao bat ky vi du nao.",
                    f"{concept} chi co gia tri trong ly thuyet tach biet khoi bai hoc.",
                ],
            },
            "analyze": {
                "answer": f"Can phan tich {concept} qua cac thanh phan y nghia, pham vi su dung va tac dong cua no trong bai hoc.",
                "distractors": [
                    f"{concept} khong can tach thanh cac mat de phan tich.",
                    f"{concept} chi can nho ten ma khong can xem xet vai tro chi tiet.",
                    f"{concept} khong anh huong den cach hieu tong the cua bai hoc.",
                ],
            },
            "evaluate": {
                "answer": f"Can danh gia {concept} dua tren muc do phu hop, tinh huu ich va gioi han khi dua vao su dung.",
                "distractors": [
                    f"{concept} luc nao cung phu hop nen khong can danh gia.",
                    f"{concept} khong co diem manh hay han che nao can xem xet.",
                    f"{concept} chi can chon ngay ma khong can can nhac boi canh.",
                ],
            },
            "create": {
                "answer": f"Mot dap an tot can de xuat duoc vi du moi hoac cach mo rong hop ly cho {concept}.",
                "distractors": [
                    f"{concept} khong the dung de tao ra vi du hoac cach mo rong moi.",
                    f"Chi can lap lai nguyen van dinh nghia cua {concept} la du cho muc sang tao.",
                    f"{concept} khong the dua vao bat ky tinh huong moi nao.",
                ],
            },
        },
        "algorithm_concept": {
            "remember": {
                "answer": f"{concept} la mot quy trinh hoac phuong phap gom cac buoc ro rang de xu ly bai toan.",
                "distractors": [
                    f"{concept} chi la ten goi cua mot chu de, khong phai quy trinh xu ly.",
                    f"{concept} khong co buoc hay quy tac nao can ghi nho.",
                    f"{concept} chi dung de mo ta ket qua, khong lien quan cach thuc hien.",
                ],
            },
            "understand": {
                "answer": f"De hieu {concept}, can mo ta duoc nguyen ly hoat dong va ly do cac buoc cua no duoc sap xep nhu vay.",
                "distractors": [
                    f"{concept} khong can giai thich nguyen ly ma chi can thuoc ten.",
                    f"{concept} hoat dong ngau nhien nen khong can mo ta cac buoc.",
                    f"{concept} khong co co che xu ly ro rang de can hieu.",
                ],
            },
            "apply": {
                "answer": f"{concept} duoc ap dung khi can xu ly bai toan co quy trinh ro rang va can cach giai co the lap lai.",
                "distractors": [
                    f"{concept} khong duoc dung trong bat ky bai toan thuc hanh nao.",
                    f"{concept} chi phu hop voi viec ghi chu ly thuyet, khong dung de giai bai toan.",
                    f"{concept} chi co y nghia khi khong can quy trinh hay buoc xu ly cu the.",
                ],
            },
            "analyze": {
                "answer": f"Can phan tich {concept} qua tung buoc xu ly, dieu kien dau vao va cach no tac dong den ket qua cuoi cung.",
                "distractors": [
                    f"{concept} khong can phan tich theo buoc vi cac buoc deu giong nhau.",
                    f"{concept} khong phu thuoc vao dau vao hay cach xu ly trung gian.",
                    f"{concept} chi can xem ket qua cuoi ma khong can xet cac buoc ben trong.",
                ],
            },
            "evaluate": {
                "answer": f"{concept} can duoc danh gia theo do chinh xac, hieu qua va muc do phu hop voi bai toan can giai.",
                "distractors": [
                    f"{concept} luc nao cung la lua chon tot nhat nen khong can danh gia.",
                    f"{concept} khong co tieu chi nao de so sanh ve hieu qua hay do phu hop.",
                    f"{concept} chi can dung duoc la du, khong can xem xet ket qua hay chi phi.",
                ],
            },
            "create": {
                "answer": f"Mot dap an tot can de xuat duoc cach cai tien, bien doi buoc hoac vi du ung dung moi cho {concept}.",
                "distractors": [
                    f"{concept} khong the cai tien vi cac buoc cua no phai giu nguyen tuyet doi.",
                    f"Chi can lap lai dung quy trinh co san cua {concept} la du cho muc sang tao.",
                    f"{concept} khong the dua vao mot bai toan moi hay boi canh moi.",
                ],
            },
        },
        "application_concept": {
            "remember": {
                "answer": f"{concept} la khai niem gan voi viec ung dung kien thuc vao tinh huong hoac bai toan cu the.",
                "distractors": [
                    f"{concept} chi la ten cua mot ly thuyet truu tuong, khong lien quan ung dung.",
                    f"{concept} khong dung trong bat ky truong hop thuc te nao.",
                    f"{concept} chi dung de minh hoa ten goi, khong lien quan su dung.",
                ],
            },
            "understand": {
                "answer": f"{concept} quan trong vi no cho thay cach kien thuc duoc dua vao boi canh thuc te va tao ra gia tri su dung.",
                "distractors": [
                    f"{concept} khong can hieu boi canh vi no khong lien quan thuc te.",
                    f"{concept} chi la mot nhan dan, khong can mo ta gia tri su dung.",
                    f"{concept} khong giup lien ket bai hoc voi tinh huong ap dung nao.",
                ],
            },
            "apply": {
                "answer": f"{concept} duoc su dung khi can dua kien thuc vao mot truong hop cu the de giai quyet nhu cau thuc te.",
                "distractors": [
                    f"{concept} khong nen dua vao tinh huong cu the nao khi thuc hanh.",
                    f"{concept} chi dung trong ly thuyet, khong phu hop voi bai toan thuc te.",
                    f"{concept} khong the tro thanh cach ap dung cua kien thuc da hoc.",
                ],
            },
            "analyze": {
                "answer": f"Can phan tich {concept} thong qua boi canh su dung, doi tuong tac dong va ket qua ma no tao ra.",
                "distractors": [
                    f"{concept} khong can xet boi canh hay doi tuong tac dong khi phan tich.",
                    f"{concept} khong tao ra ket qua nao nen khong can phan tich.",
                    f"{concept} chi can ghi nho ten ma khong can xem cach no van hanh trong thuc te.",
                ],
            },
            "evaluate": {
                "answer": f"{concept} can duoc danh gia dua tren muc do huu ich, tinh kha thi va hieu qua trong boi canh su dung.",
                "distractors": [
                    f"{concept} luc nao cung co gia tri giong nhau nen khong can danh gia.",
                    f"{concept} khong co tieu chi nao lien quan den tinh kha thi hay hieu qua.",
                    f"{concept} chi can ton tai la du, khong can xet muc tieu su dung.",
                ],
            },
            "create": {
                "answer": f"Mot dap an tot can de xuat duoc mot cach ung dung moi hoac mo rong {concept} cho tinh huong thuc te khac.",
                "distractors": [
                    f"{concept} khong the mo rong sang boi canh moi nao.",
                    f"Chi can lap lai mot vi du cu cua {concept} la du cho muc sang tao.",
                    f"{concept} khong the dung de de xuat giai phap hay tinh huong moi.",
                ],
            },
        },
        "system_concept": {
            "remember": {
                "answer": f"{concept} la khai niem mo ta cau truc, thanh phan hoac co che van hanh cua mot he thong.",
                "distractors": [
                    f"{concept} khong lien quan den cau truc hay thanh phan he thong nao.",
                    f"{concept} chi la ten goi mo ho, khong co bo phan hay co che ro rang.",
                    f"{concept} chi dung de mo ta mot hanh dong don le, khong phai he thong.",
                ],
            },
            "understand": {
                "answer": f"De hieu {concept}, can mo ta duoc cac thanh phan chinh va cach chung phoi hop de he thong hoat dong.",
                "distractors": [
                    f"{concept} khong can hieu thanh phan hay su phoi hop ben trong.",
                    f"{concept} hoat dong doc lap tung phan nen khong can mo ta tong the.",
                    f"{concept} chi la vo boc ben ngoai, khong co cach van hanh nao dang chu y.",
                ],
            },
            "apply": {
                "answer": f"{concept} duoc ap dung khi can to chuc, van hanh hoac trien khai mot he thong phu hop voi yeu cau thuc te.",
                "distractors": [
                    f"{concept} khong the dung trong bat ky tinh huong trien khai nao.",
                    f"{concept} chi dung de hoc ly thuyet ma khong lien quan van hanh he thong.",
                    f"{concept} khong anh huong den cach to chuc hay xay dung he thong thuc te.",
                ],
            },
            "analyze": {
                "answer": f"Can phan tich {concept} qua cac thanh phan, luong xu ly va moi lien he giua cac phan trong he thong.",
                "distractors": [
                    f"{concept} khong can xet cac thanh phan hay luong xu ly khi phan tich.",
                    f"{concept} khong co quan he giua cac phan nen khong can phan tich cau truc.",
                    f"{concept} chi can nhin mot thanh phan rieng le la du de hieu toan bo.",
                ],
            },
            "evaluate": {
                "answer": f"{concept} can duoc danh gia theo tinh on dinh, kha nang mo rong va muc do phu hop voi muc tieu he thong.",
                "distractors": [
                    f"{concept} luc nao cung tot nhu nhau trong moi he thong nen khong can danh gia.",
                    f"{concept} khong lien quan den on dinh hay kha nang mo rong.",
                    f"{concept} chi can ton tai trong tai lieu, khong can xet muc tieu van hanh.",
                ],
            },
            "create": {
                "answer": f"Mot dap an tot can de xuat duoc cach thiet ke, cai tien hoac mo rong {concept} cho mot he thong thuc te.",
                "distractors": [
                    f"{concept} khong the thiet ke lai hay cai tien trong he thong thuc te.",
                    f"Chi can lap lai cau truc co san cua {concept} la du cho muc sang tao.",
                    f"{concept} khong the mo rong cho yeu cau moi hay he thong moi.",
                ],
            },
        },
    }

    template_group = templates.get(concept_type)
    if template_group and bloom_level in template_group:
        payload = template_group[bloom_level]
        return str(payload["answer"]), list(payload["distractors"])[:3]

    return _fallback_answer_text(item), _fallback_distractors(item)[:3]


def _build_mcq_payload(item: Dict, lesson_id: str, template_index: int, rng: random.Random) -> Question:
    options: List[Dict[str, str]] = []
    correct_option = str(item.get("correct_option", "") or "").strip().upper()
    answer_text = str(item.get("answer", "") or "").strip()

    raw_options = item.get("options")
    if isinstance(raw_options, list) and len(raw_options) == 4 and correct_option in {"A", "B", "C", "D"}:
        normalized_options: List[Dict[str, str]] = []
        for index, option in enumerate(raw_options):
            if not isinstance(option, dict):
                normalized_options = []
                break
            key = str(option.get("key") or chr(ord("A") + index)).strip().upper()
            text = str(option.get("text") or "").strip()
            if key not in {"A", "B", "C", "D"} or not text:
                normalized_options = []
                break
            normalized_options.append({"key": key, "text": text})

        if normalized_options:
            normalized_options.sort(key=lambda payload: payload["key"])
            options = normalized_options
            if not answer_text:
                for option in options:
                    if option["key"] == correct_option:
                        answer_text = option["text"]
                        break

    if not options:
        answer_text, distractors = _build_answer_payload(item)
        option_payload = [
            {"is_correct": True, "text": answer_text},
            {"is_correct": False, "text": distractors[0]},
            {"is_correct": False, "text": distractors[1]},
            {"is_correct": False, "text": distractors[2]},
        ]
        rng.shuffle(option_payload)

        correct_option = "A"
        for option_key, payload in zip(["A", "B", "C", "D"], option_payload):
            options.append({"key": option_key, "text": payload["text"]})
            if payload["is_correct"]:
                correct_option = option_key

    return Question(
        question_id=uuid.uuid4().hex,
        lesson_id=lesson_id,
        concept=str(item.get("concept", "")),
        relation_type=str(item.get("relation_type", "definition")),
        question_text=str(item.get("question", "")).strip(),
        answer=answer_text,
        template_id=str(item.get("template_id") or f"{item.get('relation_type', 'definition')}_{template_index}"),
        bloom_level=str(item.get("bloom_level", "remember")),
        difficulty=int(item.get("difficulty", 1) or 1),
        related_concepts=[str(value) for value in item.get("related_concepts", [])],
        keywords=[str(value).strip() for value in item.get("keywords", []) if str(value).strip()],
        source_excerpt=str(item.get("source_excerpt", "") or ""),
        source_chunk_id=str(item["source_chunk_id"]) if item.get("source_chunk_id") else None,
        options=options,
        correct_option=correct_option,
    )


def _extract_chapter_concepts(chapter: Dict) -> List[Dict[str, str]]:
    concepts: List[Dict[str, str]] = []
    seen = set()

    for raw_concept in chapter.get("concepts", []) or []:
        concept_id = raw_concept.get("id") or raw_concept.get("concept_id") or raw_concept.get("name")
        concept_name = raw_concept.get("name") or raw_concept.get("concept_name")
        if not concept_id or not concept_name:
            continue
        key = str(concept_id)
        if key in seen:
            continue
        seen.add(key)
        concepts.append({"id": str(concept_id), "name": str(concept_name)})

    for lesson in chapter.get("lessons", []) or []:
        concept_id = lesson.get("concept_id") or lesson.get("title")
        concept_name = lesson.get("concept_name") or lesson.get("title")
        if not concept_id or not concept_name:
            continue
        key = str(concept_id)
        if key in seen:
            continue
        seen.add(key)
        concepts.append({"id": str(concept_id), "name": str(concept_name)})

    return concepts


def _resolve_lesson_context(lesson_id: str) -> Dict:
    db = get_db()

    lessons_collection = getattr(db, "lessons", None)
    if lessons_collection is not None:
        lesson = lessons_collection.find_one({"lesson_id": lesson_id}, {"_id": 0})
        if lesson:
            chapter_id = lesson.get("chapter_id")
            concept_list = lesson.get("concept_list", []) or []
            return {
                "lesson_id": lesson_id,
                "lesson_title": lesson.get("title") or lesson.get("lesson_name") or "Lesson",
                "chapter_id": str(chapter_id),
                "concept_list": concept_list,
            }

    path = db.learning_paths.find_one({"curriculum.lessons.lesson_id": lesson_id}, {"curriculum": 1, "_id": 0})
    if not path:
        raise ValueError(f"Lesson not found: {lesson_id}")

    for chapter in path.get("curriculum", []) or []:
        for lesson in chapter.get("lessons", []) or []:
            if lesson.get("lesson_id") != lesson_id:
                continue

            concept_list = lesson.get("concept_list") or _extract_chapter_concepts(chapter)
            return {
                "lesson_id": lesson_id,
                "lesson_title": lesson.get("title") or "Lesson",
                "chapter_id": str(chapter.get("chapter_id") or chapter.get("id") or chapter.get("title")),
                "concept_list": concept_list,
            }

    raise ValueError(f"Lesson not found: {lesson_id}")


def _concept_names(concept_list: Iterable[Dict[str, str]]) -> List[str]:
    names: List[str] = []
    for item in concept_list:
        name = str(item.get("name") or item.get("concept_name") or "").strip()
        if name:
            names.append(name)
    return names


def _generate_raw_lesson_questions(context: Dict) -> List[Dict]:
    lesson_id = str(context["lesson_id"])
    lesson_title = str(context.get("lesson_title") or "Lesson")
    concepts = _concept_names(context.get("concept_list", []))

    llm_questions: List[Dict] = []
    if LESSON_QUESTION_GENERATION_MODE in {"llm", "hybrid"}:
        try:
            pipeline_result = generate_lesson_questions_with_llm(
                lesson_id=lesson_id,
                lesson_title=lesson_title,
                concepts=concepts,
                target_count=QUESTION_BANK_SIZE,
            )
            llm_questions = list(pipeline_result.questions)
            if llm_questions:
                logger.info(
                    "Generated %s validated LLM-grounded lesson questions for lesson_id=%s",
                    len(llm_questions),
                    lesson_id,
                )
        except Exception as exc:
            logger.warning("LLM lesson question generation failed for lesson_id=%s: %s", lesson_id, exc)
            if LESSON_QUESTION_GENERATION_MODE == "llm":
                raise

    if LESSON_QUESTION_GENERATION_MODE == "llm":
        return llm_questions

    fallback_questions = generate_questions_for_lesson(lesson_id)
    if not llm_questions:
        return fallback_questions

    if len(llm_questions) >= QUESTION_BANK_SIZE:
        return llm_questions[:QUESTION_BANK_SIZE]

    existing_keys = {str(item.get("question", "")).strip().lower() for item in llm_questions}
    for item in fallback_questions:
        key = str(item.get("question", "")).strip().lower()
        if not key or key in existing_keys:
            continue
        llm_questions.append(item)
        existing_keys.add(key)
        if len(llm_questions) >= QUESTION_BANK_SIZE:
            break
    return llm_questions


def _compose_balanced_question_set(candidates: Iterable[Question], target_size: int) -> List[Question]:
    concept_buckets: Dict[str, List[Question]] = {}
    seen_questions = set()

    for item in candidates:
        key = item.question_text.strip().lower()
        if not key or key in seen_questions:
            continue
        seen_questions.add(key)
        concept_buckets.setdefault(item.concept.lower() or "unknown", []).append(item)

    ordered: List[Question] = []
    while len(ordered) < target_size:
        added = False
        for concept_name in sorted(concept_buckets.keys()):
            bucket = concept_buckets[concept_name]
            if not bucket:
                continue
            ordered.append(bucket.pop(0))
            added = True
            if len(ordered) >= target_size:
                break
        if not added:
            break

    return ordered


def _load_lesson_question_bank(lesson_id: str) -> Optional[LessonQuestionBank]:
    db = get_db()
    document = db.lesson_question_banks.find_one({"lesson_id": lesson_id}, {"_id": 0})
    if not document:
        return None

    return LessonQuestionBank(
        lesson_id=document["lesson_id"],
        chapter_id=document["chapter_id"],
        concept_list=document.get("concept_list", []),
        total_questions=int(document.get("total_questions", 0)),
        questions=[Question(**item) for item in document.get("questions", [])],
        created_at=document.get("created_at", datetime.utcnow()),
        updated_at=document.get("updated_at", datetime.utcnow()),
    )


def get_lesson_question_bank(lesson_id: str) -> LessonQuestionBank:
    bank = _load_lesson_question_bank(lesson_id)
    if bank is None:
        raise ValueError(f"Question bank not found for lesson_id={lesson_id}")
    return bank


def list_lesson_question_banks(limit: int = 50) -> List[LessonQuestionBank]:
    db = get_db()
    documents = db.lesson_question_banks.find({}, {"_id": 0}).sort("updated_at", -1).limit(max(1, limit))
    banks: List[LessonQuestionBank] = []
    for document in documents:
        banks.append(
            LessonQuestionBank(
                lesson_id=document["lesson_id"],
                chapter_id=document["chapter_id"],
                concept_list=document.get("concept_list", []),
                total_questions=int(document.get("total_questions", 0)),
                questions=[Question(**item) for item in document.get("questions", [])],
                created_at=document.get("created_at", datetime.utcnow()),
                updated_at=document.get("updated_at", datetime.utcnow()),
            )
        )
    return banks


def _mark_lesson_complete_for_user(user_id: str, lesson_id: str) -> None:
    """
    Best-effort progress update when a learner passes the lesson quiz.
    """
    if not user_id or not lesson_id:
        return

    db = get_db()
    db.learning_paths.update_many(
        {
            "user_id": user_id,
            "curriculum.lessons.lesson_id": lesson_id,
        },
        {
            "$set": {
                f"lesson_progress.{lesson_id}": "complete",
                "updated_at": datetime.utcnow(),
            }
        },
    )


# =====================================================
# MAIN FUNCTIONS
# =====================================================
def generate_and_store_questions(lesson_id: str) -> LessonQuestionBank:
    """
    Generate 20 lesson-grounded questions and store them as a lesson bank.
    """
    context = _resolve_lesson_context(lesson_id)
    chapter_id = context["chapter_id"]
    concept_list = context.get("concept_list", [])

    raw_questions = _generate_raw_lesson_questions(context)
    if not raw_questions:
        raise ValueError(f"Could not generate questions for lesson_id={lesson_id}")

    rng = random.Random(f"bank:{lesson_id}:{chapter_id}")
    candidates = [
        _build_mcq_payload(item, lesson_id=lesson_id, template_index=index, rng=rng)
        for index, item in enumerate(raw_questions, start=1)
        if item.get("question")
    ]
    selected_questions = _compose_balanced_question_set(candidates, QUESTION_BANK_SIZE)
    if len(selected_questions) < QUIZ_ATTEMPT_SIZE:
        raise ValueError(
            f"Question bank generation produced only {len(selected_questions)} questions for lesson_id={lesson_id}, fewer than required attempt size {QUIZ_ATTEMPT_SIZE}"
        )
    if len(selected_questions) < QUESTION_BANK_SIZE:
        logger.warning(
            "Question bank for lesson_id=%s has %s/%s questions; allowing quiz attempts because it still meets attempt size %s",
            lesson_id,
            len(selected_questions),
            QUESTION_BANK_SIZE,
            QUIZ_ATTEMPT_SIZE,
        )

    now = datetime.utcnow()
    bank = LessonQuestionBank(
        lesson_id=lesson_id,
        chapter_id=chapter_id,
        concept_list=concept_list,
        total_questions=len(selected_questions),
        questions=selected_questions,
        created_at=now,
        updated_at=now,
    )

    db = get_db()
    db.lesson_question_banks.update_one(
        {"lesson_id": lesson_id},
        {
            "$set": {
                "lesson_id": bank.lesson_id,
                "chapter_id": bank.chapter_id,
                "concept_list": bank.concept_list,
                "total_questions": bank.total_questions,
                "questions": [asdict(question) for question in bank.questions],
                "generation_mode": LESSON_QUESTION_GENERATION_MODE,
                "updated_at": bank.updated_at,
            },
            "$setOnInsert": {"created_at": bank.created_at},
        },
        upsert=True,
    )

    db.questions.delete_many({"lesson_id": lesson_id})
    if bank.questions:
        db.questions.insert_many([
            {
                "question_id": question.question_id,
                "lesson_id": question.lesson_id,
                "concept": question.concept,
                "relation_type": question.relation_type,
                "bloom_level": question.bloom_level,
                "template_id": question.template_id,
                "question_text": question.question_text,
                "answer": question.answer,
                "difficulty": question.difficulty,
                "related_concepts": question.related_concepts,
                "keywords": question.keywords,
                "source_excerpt": question.source_excerpt,
                "source_chunk_id": question.source_chunk_id,
                "options": question.options,
                "correct_option": question.correct_option,
                "created_at": now,
                "updated_at": now,
            }
            for question in bank.questions
        ])

    logger.info("Stored lesson question bank: lesson_id=%s, total_questions=%s", lesson_id, bank.total_questions)
    return bank


def generate_quiz(lesson_id: str) -> List[Dict]:
    bank = _load_lesson_question_bank(lesson_id)
    if bank is None:
        bank = generate_and_store_questions(lesson_id)

    if bank.total_questions < QUIZ_ATTEMPT_SIZE:
        raise ValueError(
            f"Lesson question bank has only {bank.total_questions} questions, fewer than required attempt size {QUIZ_ATTEMPT_SIZE}"
        )

    rng = random.Random(f"quiz:{lesson_id}:{uuid.uuid4().hex}")
    selected_questions = _select_diverse_quiz_questions(bank.questions, QUIZ_ATTEMPT_SIZE, rng)
    return [_sanitize_question_for_delivery(question) for question in selected_questions]


def create_lesson_quiz_attempt(user_id: str, lesson_id: str) -> Dict:
    """
    Create a new attempt by selecting 10 random questions from the stored bank.
    """
    if not user_id:
        raise ValueError("user_id cannot be empty")

    bank = _load_lesson_question_bank(lesson_id)
    if bank is None:
        bank = generate_and_store_questions(lesson_id)

    if bank.total_questions < QUIZ_ATTEMPT_SIZE:
        raise ValueError(
            f"Lesson question bank has only {bank.total_questions} questions, fewer than required attempt size {QUIZ_ATTEMPT_SIZE}"
        )

    rng = random.Random(f"attempt:{user_id}:{lesson_id}:{uuid.uuid4().hex}")
    selected_questions = _select_diverse_quiz_questions(bank.questions, QUIZ_ATTEMPT_SIZE, rng)
    selected_ids = [question.question_id for question in selected_questions]
    db = get_db()
    attempt_number = db.lesson_quiz_attempts.count_documents({
        "user_id": user_id,
        "lesson_id": lesson_id,
    }) + 1

    attempt = UserLessonAttempt(
        attempt_id=uuid.uuid4().hex,
        user_id=user_id,
        lesson_id=lesson_id,
        attempt_number=attempt_number,
        selected_question_ids=selected_ids,
        score=0.0,
        correct_count=0,
        is_passed=False,
        confidence_score=0.0,
        created_at=datetime.utcnow(),
    )

    db.lesson_quiz_attempts.insert_one({
        "attempt_id": attempt.attempt_id,
        "user_id": attempt.user_id,
        "lesson_id": attempt.lesson_id,
        "attempt_number": attempt.attempt_number,
        "selected_question_ids": attempt.selected_question_ids,
        "score": attempt.score,
        "correct_count": attempt.correct_count,
        "is_passed": attempt.is_passed,
        "confidence_score": attempt.confidence_score,
        "created_at": attempt.created_at,
        "submitted_at": attempt.submitted_at,
        "user_answers": attempt.user_answers,
    })

    return {
        "attempt_id": attempt.attempt_id,
        "user_id": attempt.user_id,
        "lesson_id": attempt.lesson_id,
        "attempt_number": attempt.attempt_number,
        "selected_question_ids": selected_ids,
        "pass_threshold_count": _get_pass_threshold_count(QUIZ_ATTEMPT_SIZE),
        "questions": [_sanitize_question_for_delivery(question) for question in selected_questions],
        "created_at": attempt.created_at,
    }


def submit_lesson_quiz(
    attempt_id: str,
    user_answers: Mapping[str, str],
    user_id: Optional[str] = None,
) -> Dict:
    """
    Grade an attempt and return score + pass/fail result.
    """
    if not attempt_id:
        raise ValueError("attempt_id cannot be empty")

    db = get_db()
    attempt = db.lesson_quiz_attempts.find_one({"attempt_id": attempt_id}, {"_id": 0})
    if not attempt:
        raise ValueError(f"Attempt not found: {attempt_id}")
    if user_id and str(attempt.get("user_id", "")) != str(user_id):
        raise ValueError(f"Attempt does not belong to user: {attempt_id}")
    if attempt.get("submitted_at"):
        raise ValueError(f"Attempt already submitted: {attempt_id}")

    lesson_id = str(attempt["lesson_id"])
    bank = _load_lesson_question_bank(lesson_id)
    if bank is None:
        raise ValueError(f"Question bank not found for lesson_id={lesson_id}")

    question_map = {question.question_id: question for question in bank.questions}
    selected_question_ids = [str(question_id) for question_id in attempt.get("selected_question_ids", [])]

    correct_count = 0
    results = []
    for question_id in selected_question_ids:
        question = question_map.get(question_id)
        if question is None:
            continue

        selected_answer = str(user_answers.get(question_id, "")).strip()
        is_correct = selected_answer.upper() == question.correct_option.upper()
        if is_correct:
            correct_count += 1

        results.append({
            "question_id": question.question_id,
            "selected_answer": selected_answer,
            "correct_option": question.correct_option,
            "is_correct": is_correct,
            "answer": question.answer,
        })

    total_questions = len(selected_question_ids)
    score = round((correct_count / max(total_questions, 1)) * 100, 2)
    threshold_count = _get_pass_threshold_count(total_questions)
    is_passed = correct_count >= threshold_count or score >= PASS_THRESHOLD_SCORE_PERCENT
    attempt_number = int(attempt.get("attempt_number", 1) or 1)
    confidence_score = calculate_confidence_score(correct_count, total_questions, attempt_number)
    submitted_at = datetime.utcnow()

    db.lesson_quiz_attempts.update_one(
        {"attempt_id": attempt_id},
        {
            "$set": {
                "score": score,
                "correct_count": correct_count,
                "is_passed": is_passed,
                "confidence_score": confidence_score,
                "total_questions": total_questions,
                "submitted_at": submitted_at,
                "user_answers": dict(user_answers),
            }
        }
    )

    upsert_lesson_confidence_progress(
        user_id=str(attempt.get("user_id", "")),
        lesson_id=lesson_id,
        attempt_id=attempt_id,
        attempt_number=attempt_number,
        correct_count=correct_count,
        total_questions=total_questions,
        score=score,
        confidence_score=confidence_score,
        is_passed=is_passed,
    )
    record_confidence_event(
        user_id=str(attempt.get("user_id", "")),
        lesson_id=lesson_id,
        attempt_id=attempt_id,
        confidence_score=confidence_score,
        score=score,
        correct_count=correct_count,
        total_questions=total_questions,
        attempt_number=attempt_number,
        is_passed=is_passed,
    )

    if is_passed:
        _mark_lesson_complete_for_user(str(attempt.get("user_id", "")), lesson_id)

    return {
        "attempt_id": attempt_id,
        "lesson_id": lesson_id,
        "score": score,
        "correct_count": correct_count,
        "total_questions": total_questions,
        "attempt_number": attempt_number,
        "confidence_score": confidence_score,
        "pass_threshold_count": threshold_count,
        "is_passed": is_passed,
        "submitted_at": submitted_at,
        "results": results,
        "can_retry": not is_passed,
    }


# =====================================================
# SAMPLE DATA
# =====================================================
SAMPLE_QUESTION = {
    "question_id": "q_001",
    "lesson_id": "lesson_python_intro",
    "concept": "Python Basics",
    "relation_type": "definition",
    "question_text": "Python Basics la gi?",
    "answer": "Python Basics la nen tang de hoc cac khai niem Python tiep theo.",
    "template_id": "definition_1",
}

SAMPLE_ATTEMPT = {
    "attempt_id": "attempt_001",
    "user_id": "user_123",
    "lesson_id": "lesson_python_intro",
    "selected_question_ids": ["q_001", "q_002"],
    "score": 80.0,
    "correct_count": 8,
    "is_passed": True,
    "created_at": datetime.utcnow(),
}
