# 🎓 Personalized Learning Path AI System

Hệ thống cá nhân hóa lộ trình học tập sử dụng **AI (Google Gemini) + RAG** để tạo ra một trải nghiệm học tập được tùy chỉnh cho từng người dùng.

## ✨ Features

- 🔐 **Authentication**: JWT-based user authentication với email/password
- 🎯 **Smart Learning Paths**: Tạo lộ trình học tập được tùy chỉnh dựa trên mục tiêu và mức độ
- 🤖 **AI-Powered**: Sử dụng Google Gemini để tạo nội dung và gợi ý cá nhân
- 📚 **Multi-Source Resources**: Hỗ trợ PDF, YouTube, web resources
- 📊 **Progress Tracking**: Theo dõi tiến độ học tập và cải thiện
- 💬 **RAG Pipeline**: Retrieval Augmented Generation để trả lời các câu hỏi học tập

## 🏗️ Project Structure

```
personalized-learning-path-ai/
│
├── backend/                           # FastAPI Backend
│   ├── main.py                        # App initialization + CORS
│   ├── app/
│   │   ├── api/                       # API endpoints
│   │   │   ├── auth.py               # Login/Signup (JWT)
│   │   │   ├── users.py              # User management
│   │   │   ├── learning_path.py      # Learning path endpoints
│   │   │   ├── progress.py           # Progress tracking
│   │   │   ├── ask.py                # Q&A with AI
│   │   │   ├── recommendations.py    # Smart recommendations
│   │   │   ├── resources.py          # Resource management
│   │   │   └── schemas.py            # Pydantic models
│   │   ├── services/                  # Business logic
│   │   │   ├── ai_service.py         # Gemini integration
│   │   │   ├── rag_pipeline.py       # RAG implementation
│   │   │   ├── adaptive_engine.py    # Learning path generation
│   │   │   ├── progress_service.py   # Progress calculations
│   │   │   ├── embedding_service.py  # Vector embeddings
│   │   │   └── ...more services
│   │   └── database/
│   │       └── mongo.py              # MongoDB connection
│   ├── scripts/                       # Seeding scripts
│   └── uploads/                       # User uploaded files
│
├── frontend/                          # React + TypeScript Frontend
│   ├── src/
│   │   ├── components/
│   │   │   └── auth/
│   │   │       ├── Login.tsx          # Login page
│   │   │       ├── Signup.tsx         # Signup page (Step 1)
│   │   │       └── SignupStep2.tsx    # Signup page (Step 2)
│   │   ├── services/
│   │   │   ├── authService.ts        # Auth logic
│   │   │   └── index.ts
│   │   ├── types/
│   │   │   ├── auth.ts               # Type definitions
│   │   │   └── index.ts
│   │   ├── utils/
│   │   │   ├── apiClient.ts          # HTTP client
│   │   │   └── index.ts
│   │   ├── App.tsx                    # Main component
│   │   └── main.tsx                   # Entry point
│   ├── package.json
│   ├── tsconfig.json
│   ├── tailwind.config.js
│   ├── vite.config.ts
│   └── index.html
│
├── requirements.txt                  # Python dependencies
├── .env.example                      # Environment template
├── .gitignore                        # Git ignore rules
└── README.md                         # This file
```

## 🚀 Quick Start

### Prerequisites

- **Python 3.10+**
- **Node.js 18+** và **npm**
- **MongoDB** (local hoặc Atlas)
- **Google Gemini API Key** (free tier available)

### 1. Backend Setup

```bash
# Clone repository
git clone <your-repo-url>
cd personalized-learning-path-ai

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or
venv\Scripts\activate     # Windows

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your config:
# - MONGODB_URI
# - SECRET_KEY (generate random string)
# - GEMINI_API_KEY

# Start backend server
python -m uvicorn backend.main:app --reload

# Backend runs at: http://localhost:8000
# API docs: http://localhost:8000/docs
```

### 2. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Configure environment (optional)
cp .env.example .env
# Edit .env if needed

# Start development server
npm run dev

# Frontend runs at: http://localhost:5173
```

### 3. Access the Application

- **Frontend**: http://localhost:5173
- **Backend API**: http://localhost:8000
- **API Documentation**: http://localhost:8000/docs (Swagger UI)

## 📝 Authentication Flow

### Signup (2-Step Process)

**Step 1**: `/signup`
- Nhập: Tên, Email, Mật khẩu
- Validation: Email format, Password min 6 chars
- Action: Proceed to Step 2

**Step 2**: `/signup-step2`
- Chọn: Mục tiêu học tập, Cấp độ hiện tại
- Action: Tạo tài khoản, nhận JWT token
- Redirect: `/dashboard`

### Login

**Route**: `/login`
- Nhập: Email, Mật khẩu
- Action: Xác thực, nhận JWT token
- Redirect: `/dashboard`

## 🔌 API Endpoints

### Authentication

```
POST   /api/auth/signup       Create new account
POST   /api/auth/login        Login with email/password
POST   /api/auth/refresh      Refresh JWT token
```

### Users

```
GET    /api/users/me          Get current user profile
PUT    /api/users/me          Update user profile
```

### Learning Paths

```
GET    /api/learning-paths    Get user's learning paths
POST   /api/learning-paths    Create new learning path
GET    /api/learning-paths/{id}  Get specific path
```

### Progress

```
GET    /api/progress          Get user progress
POST   /api/progress          Log learning activity
```

### Resources

```
GET    /api/resources         List resources
POST   /api/resources         Upload/add resource
```

### AI Q&A

```
POST   /api/ask               Ask question to AI
```

## 🔐 Environment Variables

### Required
- `MONGODB_URI` - MongoDB connection string
- `SECRET_KEY` - JWT secret (generate: `openssl rand -hex 32`)
- `GEMINI_API_KEY` - Google Gemini API key

### Optional
- `SMTP_SERVER` - For email notifications
- `REDIS_URL` - For caching

See `.env.example` for full list.

## 📦 Tech Stack

### Backend
- **FastAPI** - Modern Python web framework
- **MongoDB** - NoSQL database
- **Google Gemini** - AI model for content generation
- **JWT** - Authentication tokens
- **Argon2** - Password hashing

### Frontend
- **React 18** - UI library
- **TypeScript** - Type safety
- **Tailwind CSS** - Styling
- **React Router** - Navigation
- **Vite** - Build tool

## 🧪 Testing

### Backend Tests
```bash
pytest
pytest --cov  # With coverage
```

### Frontend Tests
```bash
cd frontend
npm run test
```

## 📚 API Documentation

Interactive API docs available at: **http://localhost:8000/docs**

Swagger UI showing:
- All endpoints
- Request/response schemas
- Try-it-out functionality
- Authentication bearer token input

## 🚢 Deployment

### Backend (Vercel/Railway/Heroku)

```bash
# Build
pip install -r requirements.txt

# Run
uvicorn backend.main:app --host 0.0.0.0 --port $PORT
```

### Frontend (Vercel/Netlify)

```bash
cd frontend
npm run build
# Deploy 'dist' folder
```

### Environment Variables

Set these in your deployment dashboard:
- `MONGODB_URI`
- `SECRET_KEY`
- `GEMINI_API_KEY`
- `FRONTEND_URL` (for CORS)

## 🐛 Troubleshooting

### Port Already in Use

```bash
# Backend (change port)
python -m uvicorn backend.main:app --port 8001

# Frontend (change port)
npm run dev -- --port 5174
```

### CORS Errors

Ensure backend `main.py` has CORS middleware for your frontend origin:
```python
allow_origins=["http://localhost:5173"]
```

### MongoDB Connection Error

```bash
# Test connection
python -c "from pymongo import MongoClient; print(MongoClient('mongodb://localhost:27017'))"
```

### Missing API Key

```bash
# Make sure .env has:
GEMINI_API_KEY=your-actual-key
```

## 📖 Documentation

- [Backend API Guide](./backend/README.md) - Coming soon
- [Frontend Setup Guide](./frontend/README.md)
- [Database Schema](./docs/database.md) - Coming soon
- [AI/RAG Pipeline](./docs/ai-pipeline.md) - Coming soon

## 🤝 Contributing

1. Create feature branch: `git checkout -b feature/amazing-feature`
2. Commit changes: `git commit -m 'Add amazing feature'`
3. Push to branch: `git push origin feature/amazing-feature`
4. Open Pull Request

## 📄 License

This project is licensed under the MIT License - see LICENSE file for details.

## 👥 Team

- **AI/Backend**: Python, FastAPI, MongoDB, Gemini
- **Frontend**: React, TypeScript, Tailwind CSS
- **DevOps**: Docker, Cloud deployment

## 📞 Support

For issues or questions:
1. Check existing issues on GitHub
2. Create new issue with detailed description
3. Include: OS, Python/Node version, error message, steps to reproduce

## 🎯 Roadmap

- [x] User authentication (Login/Signup)
- [x] Basic API structure
- [ ] Dashboard page
- [ ] Learning path generation
- [ ] Progress tracking
- [ ] AI Q&A integration
- [ ] Resource recommendations
- [ ] Mobile app
- [ ] Real-time notifications

## 📈 Performance Tips

### Backend
- Enable Redis caching
- Use async operations
- Optimize database queries

### Frontend
- Code splitting with lazy loading
- Image optimization
- Service Worker for offline support

---

**Made with ❤️ for personalized learning**
