
# Personalized Learning Path AI

Hệ thống giúp tạo lộ trình học tập cá nhân hóa bằng AI (Google Gemini) kết hợp RAG. Mục tiêu là hỗ trợ người học theo đuổi mục tiêu rõ ràng, theo dõi tiến độ và nhận gợi ý tài nguyên phù hợp.

## Tính năng nổi bật

- Xác thực người dùng với JWT.
- Tạo lộ trình học tập dựa trên mục tiêu và trình độ.
- Hỏi đáp thông minh và gợi ý tài nguyên từ AI.
- Quản lý tài nguyên (PDF, YouTube, web).
- Theo dõi tiến độ và điều chỉnh độ khó.

## Tổng quan kiến trúc

- Frontend: React + TypeScript + Tailwind.
- Backend: FastAPI (REST API).
- Database: MongoDB.
- AI/LLM: Google Gemini (gợi ý, hỏi đáp, embeddings).

## Cài đặt nhanh

### Yêu cầu

- Python 3.11/3.12 (khuyến nghị), 3.8+ vẫn chạy được.
- Node.js 16+.
- MongoDB 4.6+.
- Gemini API Key.

### Backend

```bash
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
python -m uvicorn backend.main:app --reload
```

Backend chạy tại `http://localhost:8000`.

### Frontend

```bash
cd frontend
npm install
npm run dev
```

Frontend chạy tại `http://localhost:5173`.

## Biến môi trường

```bash
MONGODB_URI=mongodb://localhost:27017/learning_path_ai
SECRET_KEY=your-secret-key-min-32-chars
ACCESS_TOKEN_EXPIRE_MINUTES=60
GEMINI_API_KEY=your-api-key
VITE_API_URL=http://localhost:8000
VITE_API_BASE_PATH=/api
```

## Cấu trúc thư mục (tóm tắt)

```
backend/    # FastAPI, services, database
frontend/   # React + Vite
requirements.txt
.env.example
```

## API chính

```
POST   /api/auth/signup
POST   /api/auth/login
GET    /api/learning-paths
POST   /api/learning-paths
GET    /api/progress/overview
POST   /api/ask
GET    /api/resources
```

## Phát triển

```bash
pip install -r requirements-dev.txt
black backend/
isort backend/
flake8 backend/
mypy backend/
```

## License

MIT License - xem [LICENSE](LICENSE)
