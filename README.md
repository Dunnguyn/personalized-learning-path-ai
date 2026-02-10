# Personalized Learning Path AI System

He thong ca nhan hoa lo trinh hoc tap su dung AI (Google Gemini) + RAG de tao trai nghiem hoc tap tuy chinh cho tung nguoi dung.

## Tinh nang chinh
- Dang ky/Dang nhap JWT
- Tao lo trinh hoc tap theo muc tieu va trinh do
- Goi y noi dung bang AI (Gemini)
- Quan ly tai nguyen: PDF, YouTube, web
- Theo doi tien do hoc tap
- Hoi dap bang RAG

## Cau truc thu muc
- `backend/`: FastAPI, API, services, MongoDB
- `frontend/`: React + TypeScript + Tailwind
- `requirements.txt`, `.env.example`, `README.md`

## Cai dat nhanh
### Backend
```bash
git clone <your-repo-url>
cd personalized-learning-path-ai
python -m venv venv
venv\Scripts\activate  # Windows
pip install -r requirements.txt
cp .env.example .env
python -m uvicorn backend.main:app --reload
```
Backend: http://localhost:8000
Docs: http://localhost:8000/docs

### Frontend
```bash
cd frontend
npm install
npm run dev
```
Frontend: http://localhost:5173

## Bien moi truong can co
- `MONGODB_URI`
- `SECRET_KEY`
- `GEMINI_API_KEY`

## API chinh
```
POST /api/auth/signup
POST /api/auth/login
GET  /api/users/me
GET  /api/learning-paths
POST /api/ask
```

## Test
```bash
pytest
cd frontend && npm run test
```

## Deploy
- Backend: `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
- Frontend: `npm run build`
