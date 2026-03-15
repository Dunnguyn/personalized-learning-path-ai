
# Personalized Learning Path AI

Hệ thống cá nhân hóa lộ trình học tập dựa trên AI, kết hợp `FastAPI + MongoDB + React + RAG + Adaptive Learning`.

Mục tiêu của dự án là trả lời câu hỏi học tập thông minh, theo dõi mức độ nắm vững kiến thức theo từng concept, và tự động đề xuất lộ trình tiếp theo phù hợp với năng lực hiện tại của từng người học.

## 1. Tổng Quan Bài Toán

Nền tảng giải quyết 4 bài toán chính:

1. Trả lời câu hỏi học tập có ngữ cảnh (`RAG`), ưu tiên tài liệu nội bộ trước khi gọi LLM.
2. Đo tiến độ học tập theo concept bằng điểm `mastery` và `confidence`.
3. Điều chỉnh chiến lược học (`remedial`, `normal`, `advanced`) theo năng lực thực tế.
4. Sinh lộ trình học mới theo đồ thị tiên quyết (`prerequisite graph`) và đề xuất tài nguyên phù hợp.

## 2. Kiến Trúc Hệ Thống

```text
Frontend (React + TypeScript + Vite)
   |
   | HTTP/REST
   v
Backend API (FastAPI)
  - API Layer (auth, ask, learning-path, resources, progress, ...)
  - Service Layer (RAG, adaptive, progress, recommendations, importers)
  - Data Layer (MongoDB collections + embedding utilities)
   |
   v
MongoDB (users, concepts, resources, progress, learning_paths, ...)
```

### 2.1 Backend kiến trúc theo lớp

- `backend/main.py`: bootstrap app, middleware logging, CORS, health/readiness, router registration.
- `backend/app/api/*.py`: định nghĩa REST endpoints và validate request/response.
- `backend/app/services/*.py`: xử lý nghiệp vụ và thuật toán.
- `backend/app/database/mongo.py`: kết nối MongoDB và cung cấp `get_db()`.

### 2.2 Frontend kiến trúc

- Router chính trong `frontend/src/App.tsx`.
- State xác thực trong `frontend/src/contexts/AuthContext.tsx`.
- Tách service gọi API trong `frontend/src/services/*`.
- Các trang chính: Dashboard, LearningPath, LearningPathDetail, Resources, AITutor, Settings, RagSimple.

## 3. Chức Năng Cốt Lõi

### 3.1 Authentication và Authorization

- JWT (`python-jose`) với `HS256`.
- Hash mật khẩu bằng `Argon2` (`passlib[argon2]`).
- `Depends(get_current_user)` bảo vệ endpoint.
- Kiểm tra user đang gọi có đúng `user_id` mục tiêu hay không.

### 3.2 AI Tutor (Q&A)

Endpoint chính: `POST /api/ask/`

Luồng xử lý:

1. Xác thực JWT và quyền truy cập.
2. Validate `question`, `goal`, `level`.
3. Gọi `AITutorService.ask_ai(...)`.
4. Bên trong service:
 - Chạy RAG lấy câu trả lời.
 - Chấm confidence.
 - Detect concept.
 - Cập nhật progress.
 - Tính adaptive mode.
 - Sinh learning path mới.
5. Lưu lịch sử hỏi đáp (`ask_history`).

### 3.3 Quản lý tài nguyên học

- Thêm thủ công: `POST /api/resources/`
- Import batch: `POST /api/resources/import`
- Import PDF: `POST /api/resources/import-pdf`
- Import YouTube: `POST /api/resources/import-youtube`
- Search semantic: `GET /api/resources/search`
- Tải PDF: `GET /api/resources/pdf/{resource_id}`

### 3.4 Learning Path cá nhân hóa

- Sinh lộ trình: `POST /api/learning-path/generate`
- Lịch sử lộ trình: `GET /api/learning-path/history`
- Cập nhật trạng thái lesson: `POST /api/learning-path/lesson-progress`
- Xem chi tiết path: `GET /api/learning-path/{path_id}`

### 3.5 Progress Tracking

- Cập nhật tiến độ: `POST /api/progress/update`
- Tổng quan: `GET /api/progress/overview`
- Summary: `GET /api/progress/summary`
- Confidence analytics: `GET /api/progress/confidence`

## 4. Thuật Toán Và Logic Nghiệp Vụ (Chi Tiết)

### 4.1 RAG Pipeline (`backend/app/services/rag_pipeline.py`)

Pipeline chính:

1. `retrieve_context`: semantic search tài nguyên liên quan.
2. `build_context`: ghép context có giới hạn ký tự (`RAG_MAX_CONTEXT_CHARS`).
3. `build_prompt`: prompt theo ngữ cảnh có/không có tài liệu thực.
4. Quyết định chiến lược trả lời:
 - Trả lời trực tiếp từ context nếu đủ mạnh.
 - Hoặc gọi Gemini nếu context chưa đủ.
5. Fallback khi LLM lỗi hoặc quota exhausted.

Điều kiện trả lời trực tiếp từ tài liệu:

- Tài liệu phải là tài liệu thật từ DB (`is_real_resource = True`).
- Số tài liệu chất lượng cao `>= RAG_MIN_HIGH_QUALITY_RESOURCES`.
- Mỗi tài liệu chất lượng cao có `score >= RAG_DIRECT_ANSWER_THRESHOLD`.

Tư duy thiết kế:

- Nếu context đủ tốt thì không cần gọi LLM để giảm latency/cost.
- Nếu context chưa đủ thì gọi AI để tăng độ đầy đủ và chính xác.
- Nếu AI unavailable/quota hết thì trả lời fallback từ knowledge base để không fail cứng.

### 4.2 Concept Detection đa chiến lược (`ai_service.py`)

`ConceptDetector.detect()` chạy theo thứ tự:

1. `detect_semantic`: embedding câu hỏi, so cosine similarity với embedding concept.
2. `detect_rule_based`: match keyword theo `concept_name/topic` + biến thể từ đồng nghĩa.
3. `detect_fallback`: chọn concept dễ nhất nếu 2 bước trên không tìm được.

Điều này giúp hệ thống vừa có độ phủ cao (fallback) vừa có độ chính xác tốt hơn ở câu hỏi rõ ngữ nghĩa (semantic).

### 4.3 Confidence Scoring (`confidence_scorer.py`)

Input: `question`, `answer`, optional `context`.

Luồng:

1. Prompt LLM yêu cầu trả về duy nhất số từ `0.0 -> 1.0`.
2. Parse output theo nhiều shape response SDK.
3. Parse số bằng regex robust.
4. Lỗi hoặc parse thất bại thì fallback `0.5`.

Mục tiêu: ổn định scoring dù SDK response khác nhau hoặc AI trả về format không chuẩn.

### 4.4 Progress bằng EMA (`progress_service.py`)

Mỗi lần learner hỏi và hệ thống detect được concept, tiến độ concept được cập nhật bằng EMA:

```text
new_mastery = old_mastery * (1 - alpha) + confidence * alpha
```

Trong đó:

- `alpha = PROGRESS_ALPHA` (mặc định `0.3`)
- `confidence` trong `[0, 1]`

Các chỉ số cập nhật đồng thời:

- `total_attempts += 1`
- `successful_attempts += 1` nếu `confidence >= PROGRESS_MIN_CONFIDENCE`
- `success_rate = successful_attempts / total_attempts`
- `status` theo mastery:
 - `complete` nếu `mastery >= 0.8`
 - `proficient` nếu `mastery >= 0.6`
 - `in_progress` nếu `mastery > 0`
 - `not_started` nếu `mastery = 0`

### 4.5 Adaptive Engine (`adaptive_engine.py`)

Decision tree `decide_learning_mode(mastery, confidence, total_attempts)`:

1. Nếu `mastery < MASTERY_LOW` hoặc `confidence < CONFIDENCE_LOW` -> `REMEDIAL`.
2. Nếu `mastery >= MASTERY_HIGH` và `confidence >= CONFIDENCE_HIGH` và `attempts <= MAX_ATTEMPTS_FOR_ADVANCE` -> `ADVANCED`.
3. Ngược lại -> `NORMAL`.

Adaptive mode được dùng để:

- Lọc tài nguyên theo Bloom levels (`filter_resources_by_mode`).
- Gợi ý mức độ luyện tập (`get_practice_recommendations`).
- Đề xuất tăng/giảm difficulty (`recommend_difficulty_boost`).

### 4.6 Sinh Learning Path bằng đồ thị tiên quyết (`learning_path_service.py`)

Các bước:

1. Lấy progress hiện tại của user.
2. Xác định concept đã hoàn thành (`mastery >= 0.8`).
3. Xây graph `concept -> prerequisites` từ collection `prerequisites`.
4. Kiểm tra cycle bằng DFS (`_has_cycle`).
5. Topological sort (`_topological_sort`) để có thứ tự học an toàn.
6. Lọc theo level bằng difficulty range:
 - beginner: 1-4
 - intermediate: 3-7
 - advanced: 6-10
7. Chỉ giữ concept chưa hoàn thành và đã thỏa prerequisites.
8. Tính `priority_score` dựa trên level factor, difficulty và trạng thái đã học.
9. Recommend resource cho từng concept.
10. Tạo curriculum (qua LLM nếu khả dụng, fallback sang build rule-based nếu không).

### 4.7 Resource Recommendation (`recommendations.py`)

`GET /api/recommendations/resources`:

- Lấy concept theo `goal`.
- Tìm concept chưa completed.
- Lấy resource theo level tương ứng, fallback level cao hơn nếu thiếu.
- Chấm điểm `relevance_score` theo:
 - base score
 - level match bonus
 - pedagogy bonus (ví dụ beginner ưu tiên video)

## 5. Công Nghệ Sử Dụng

### 5.1 Backend

- Python 3.12
- FastAPI + Uvicorn
- Pydantic v2
- MongoDB (`pymongo`, `motor`)
- Auth: `python-jose`, `passlib[argon2]`
- AI: `google-genai` (Gemini)
- Scientific: `numpy`, `scipy`, `scikit-learn`
- Importers: `pypdf`, `PyMuPDF`, `pytube`, `youtube-transcript-api`, `yt-dlp`

### 5.2 Frontend

- React 18
- TypeScript
- Vite
- TailwindCSS
- Axios
- React Router DOM

### 5.3 Dev Tooling

- Backend: `pytest`, `black`, `flake8`, `mypy`, `isort`, `pylint`, `bandit`
- Frontend: `eslint`, `prettier`, `tsc`
- Docker: `docker-compose` cho local stack

## 6. Cấu Trúc Thư Mục (Giải Thích Theo Module)

```text
personalized-learning-path-ai/
├── backend/
│   ├── main.py
│   ├── app/
│   │   ├── api/
│   │   │   ├── auth.py
│   │   │   ├── users.py
│   │   │   ├── ask.py
│   │   │   ├── learning_path.py
│   │   │   ├── progress.py
│   │   │   ├── resources.py
│   │   │   ├── recommendations.py
│   │   │   ├── concepts.py
│   │   │   └── rag.py
│   │   ├── services/
│   │   │   ├── ai_service.py
│   │   │   ├── rag_pipeline.py
│   │   │   ├── learning_path_service.py
│   │   │   ├── adaptive_engine.py
│   │   │   ├── progress_service.py
│   │   │   ├── confidence_scorer.py
│   │   │   ├── embedding_service.py
│   │   │   ├── resource_service.py
│   │   │   ├── pdf_importer.py
│   │   │   └── youtube_importer.py
│   │   └── database/
│   │       └── mongo.py
│   └── uploads/
├── frontend/
│   ├── src/
│   │   ├── pages/
│   │   ├── components/
│   │   ├── contexts/
│   │   ├── services/
│   │   ├── types/
│   │   └── utils/
│   └── package.json
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── README.md
```

## 7. API Endpoints (Theo Router Hiện Tại)

Tất cả router backend được mount dưới prefix `/api`.

### 7.1 Auth

- `POST /api/auth/signup`
- `POST /api/auth/login`

### 7.2 Users

- `POST /api/users/`
- `GET /api/users/me`
- `PUT /api/users/{user_id}`

### 7.3 Ask / AI Tutor

- `POST /api/ask/`
- `GET /api/ask/adaptive-status`
- `POST /api/ask/detect-concepts`
- `GET /api/ask/recommend-concepts`
- `GET /api/ask/history`
- `DELETE /api/ask/history/{history_id}`

### 7.4 Learning Path

- `POST /api/learning-path/generate`
- `GET /api/learning-path/history`
- `POST /api/learning-path/lesson-progress`
- `GET /api/learning-path/{path_id}`

### 7.5 Progress

- `POST /api/progress/update`
- `GET /api/progress/summary`
- `GET /api/progress/overview`
- `GET /api/progress/confidence`

### 7.6 Resources

- `GET /api/resources/`
- `POST /api/resources/`
- `POST /api/resources/import`
- `GET /api/resources/search`
- `POST /api/resources/import-pdf`
- `POST /api/resources/import-youtube`
- `GET /api/resources/pdf/{resource_id}`

### 7.7 Recommendations

- `GET /api/recommendations/resources`
- `GET /api/recommendations/progress`

### 7.8 Concepts

- `GET /api/concepts`
- `GET /api/concepts/{concept_id}`

### 7.9 RAG Utilities

- `POST /api/rag/upload-pdf`
- `POST /api/rag/chat`

## 8. Cài Đặt Và Chạy Local

### 8.1 Yêu cầu hệ thống

- Python `3.11+` (khuyến nghị `3.12`)
- Node.js `18+`
- MongoDB `6+` (hoặc Atlas)

### 8.2 Backend

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
python -m uvicorn backend.main:app --reload
```

Backend chạy tại `http://localhost:8000`.
Swagger docs: `http://localhost:8000/api/docs`

### 8.3 Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend chạy tại `http://localhost:5173`.

### 8.4 Biến môi trường quan trọng

Trong file `.env`:

```env
MONGODB_URI=mongodb://localhost:27017/learning_path_ai
DB_NAME=learning_path_ai
SECRET_KEY=your-secret-key-min-32-chars
ACCESS_TOKEN_EXPIRE_MINUTES=60
GEMINI_API_KEY=your-gemini-api-key
VITE_API_URL=http://localhost:8000
VITE_API_BASE_PATH=/api
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

Riêng AI/RAG có thể tinh chỉnh thêm trong `.env.example`:

- `RAG_DIRECT_ANSWER_THRESHOLD`
- `RAG_MIN_HIGH_QUALITY_RESOURCES`
- `RAG_MAX_CONTEXT_CHARS`
- `RAG_MAX_PROMPT_CHARS`

## 9. Chạy Bằng Docker

```bash
docker compose up -d --build
```

Services chính:

- `mongodb` (27017)
- `redis` (6379)
- `backend` (8000)
- `frontend` (5173)
- `mongo-express` (8081, profile `dev`)

## 10. Kiểm Thử Và Chất Lượng Mã

### 10.1 Backend

```bash
pytest backend/
black backend/
isort backend/
flake8 backend/
mypy backend/
```

### 10.2 Frontend

```bash
cd frontend
npm run type-check
npm run lint
npm run format:check
```

## 11. Troubleshooting Nhanh

### 11.1 `401 Unauthorized`

- Token hết hạn hoặc sai `SECRET_KEY`.
- Header Authorization thiếu `Bearer <token>`.
- `user_id` trong request không trùng user trong token.

### 11.2 Không kết nối được MongoDB

- Kiểm tra `MONGODB_URI`.
- Kiểm tra Mongo service có chạy không.
- Kiểm tra network/firewall nếu dùng Atlas.

### 11.3 AI trả fallback thường xuyên

- Kiểm tra `GEMINI_API_KEY` và quota.
- Giảm `RAG_DIRECT_ANSWER_THRESHOLD` nếu muốn tăng trả lời trực tiếp từ tài liệu.
- Kiểm tra chất lượng dữ liệu trong `resources`/`embeddings`.

### 11.4 Search không chính xác

- Hiện tại embedding fallback là hash-based deterministic nếu chưa bật external embedding provider.
- Để tăng semantic quality, cần cấu hình provider embedding thực tế.

## 12. Ghi Chú Thiết Kế

- Dự án ưu tiên tính ổn định: có nhiều nhánh fallback khi LLM/SDK lỗi.
- Adaptive learning và RAG có thể tinh chỉnh gần như toàn bộ qua biến môi trường.
- Kiến trúc service tách rõ giúp mở rộng dễ: thêm model AI, thêm nguồn dữ liệu, thêm chiến lược chấm điểm.

## 13. License

MIT. Xem file `LICENSE` để biết chi tiết.
