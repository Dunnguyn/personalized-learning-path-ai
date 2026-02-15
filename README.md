
# Personalized Learning Path AI

Hệ thống tạo lộ trình học tập cá nhân hóa bằng AI (Google Gemini) và RAG, giúp học sinh, sinh viên, người đi làm học tập hiệu quả theo mục tiêu của họ.

## 📚 Tính Năng Chính

- **🔐 Xác thực người dùng**: Đăng ký/Đăng nhập với JWT authentication
- **🎯 Tạo lộ trình học tập**: Tự động sinh lộ trình theo mục tiêu và trình độ
- **🤖 AI Advisor**: Gợi ý tài nguyên và câu hỏi thông minh bằng Gemini AI
- **📊 Quản lý tài nguyên**: Hỗ trợ PDF, YouTube, web resources
- **📈 Theo dõi tiến độ**: Theo dõi sự tiến bộ và điều chỉnh lộ trình
- **💬 RAG QA**: Hỏi đáp thông minh với Retrieval-Augmented Generation
- **🔄 Adaptive Learning**: Điều chỉnh khó độ dựa trên performance

## 🏗️ Kiến Trúc Hệ Thống

```
┌─────────────┐                    ┌──────────────────┐
│ Frontend    │                    │ Backend (FastAPI)│
│ React       │◄────── REST API ───►│ • Auth           │
│ TypeScript  │     (JSON/Token)    │ • Learning Path  │
│ Tailwind    │                    │ • RAG Pipeline   │
└─────────────┘                    │ • AI Services    │
                                   └────────┬────────┘
                                            │
                                   ┌────────▼────────┐
                                   │ MongoDB         │
                                   │ (User, Progress)│
                                   └─────────────────┘
                                            │
                                   ┌────────▼────────────┐
                                   │ Google Gemini API   │
                                   │ (LLM, Embeddings)   │
                                   └─────────────────────┘
```

## 💻 Tech Stack

### Backend
- **Framework**: FastAPI 0.112+ (Python 3.8+)
- **Database**: MongoDB 4.6+
- **Authentication**: JWT (python-jose)
- **Password Hashing**: Argon2 (passlib)
- **AI/LLM**: Google Generative AI (Gemini)
- **PDF Processing**: PyMuPDF, PyPDF
- **YouTube**: pytube, youtube-transcript-api, yt-dlp

### Frontend
- **Framework**: React 18 + TypeScript
- **Build Tool**: Vite
- **Styling**: Tailwind CSS
- **UI Components**: Custom React components
- **State Management**: React Context API
- **Routing**: React Router v6
- **HTTP Client**: Fetch API

## 📁 Cấu Trúc Thư Mục

```
personalized-learning-path-ai/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── auth.py           # Authentication endpoints
│   │   │   ├── users.py          # User management
│   │   │   ├── learning_path.py  # Learning path endpoints
│   │   │   ├── progress.py       # Progress tracking
│   │   │   ├── ask.py            # Q&A endpoints
│   │   │   ├── recommendations.py # Recommendations
│   │   │   ├── resources.py      # Resource management
│   │   │   └── schemas.py        # Pydantic models
│   │   ├── services/
│   │   │   ├── ai_service.py     # Gemini AI integration
│   │   │   ├── rag_pipeline.py   # RAG implementation
│   │   │   ├── embedding_service.py
│   │   │   ├── learning_path_service.py
│   │   │   ├── progress_service.py
│   │   │   └── ... (other services)
│   │   ├── database/
│   │   │   └── mongo.py          # MongoDB connection
│   │   └── utils/
│   ├── main.py                   # FastAPI app entry point
│   └── scripts/                  # Seed scripts
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── auth/             # Login, Signup components
│   │   │   └── layout/           # Layout components
│   │   ├── pages/                # Page components
│   │   ├── services/             # API services
│   │   ├── contexts/             # React Context
│   │   ├── types/                # TypeScript types
│   │   ├── utils/                # Utilities
│   │   └── App.tsx
│   ├── package.json
│   ├── vite.config.ts
│   └── tailwind.config.js
├── requirements.txt              # Backend dependencies
├── requirements-dev.txt          # Development dependencies
├── .env.example                  # Environment template
└── README.md
```

## 🚀 Cài Đặt & Chạy

### Yêu Cầu
- Python 3.8+
- Node.js 16+
- MongoDB 4.6+ (local hoặc cloud)
- Google Gemini API Key

### Backend Setup

1. **Clone repository**
```bash
git clone <repo-url>
cd personalized-learning-path-ai
```

2. **Tạo virtual environment**
```bash
python -m venv venv
venv\Scripts\activate  # Windows
# hoặc
source venv/bin/activate  # macOS/Linux
```

3. **Cài đặt dependencies**
```bash
pip install -r requirements.txt
```

4. **Cấu hình environment**
```bash
cp .env.example .env
# Edit .env với các giá trị:
# MONGODB_URI=mongodb://localhost:27017/learning_path_ai
# SECRET_KEY=your_secret_key_here
# GEMINI_API_KEY=your_gemini_api_key
# ACCESS_TOKEN_EXPIRE_MINUTES=60
```

5. **Chạy backend**
```bash
python -m uvicorn backend.main:app --reload
```

Backend sẽ chạy tại: `http://localhost:8000`
- API Docs: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

### Frontend Setup

1. **Vào thư mục frontend**
```bash
cd frontend
```

2. **Cài đặt dependencies**
```bash
npm install
```

3. **Chạy development server**
```bash
npm run dev
```

Frontend sẽ chạy tại: `http://localhost:5173`

## 🔌 API Endpoints

### Authentication
```
POST   /api/auth/signup           # Đăng ký
POST   /api/auth/login            # Đăng nhập
```

### User Management
```
GET    /api/users/me              # Lấy thông tin hiện tại
PUT    /api/users/{user_id}       # Cập nhật profile
```

### Learning Path
```
GET    /api/learning-paths        # Lấy lộ trình
POST   /api/learning-paths        # Tạo lộ trình
GET    /api/concepts              # Lấy khái niệm
```

### Progress
```
GET    /api/progress/overview     # Tổng quan tiến độ
GET    /api/progress/confidence   # Độ tự tin
GET    /api/progress/summary      # Tóm tắt tiến độ
POST   /api/progress              # Cập nhật tiến độ
```

### AI & Q&A
```
POST   /api/ask                   # Hỏi đáp thông minh
GET    /api/recommendations       # Gợi ý tài nguyên
```

### Resources
```
GET    /api/resources             # Lấy tài nguyên
POST   /api/resources/upload      # Upload PDF
POST   /api/resources/youtube     # Thêm video YouTube
```

## 🧪 Testing

```bash
# Backend tests
pytest

# Frontend tests
cd frontend
npm run test
```

## 📦 Deployment

### Backend (Production)
```bash
# Sử dụng Gunicorn + Uvicorn
gunicorn backend.main:app -w 4 -k uvicorn.workers.UvicornWorker

# Hoặc Docker
docker build -t learning-path-api .
docker run -p 8000:8000 learning-path-api
```

### Frontend (Production)
```bash
# Build bundle
npm run build

# Deploy to static hosting (Vercel, Netlify, GitHub Pages, etc.)
npm run preview  # Test production build locally
```

## 🔐 Environment Variables

```bash
# MongoDB
MONGODB_URI=mongodb://username:password@host:port/database

# JWT
SECRET_KEY=your-secret-key-min-32-chars
ACCESS_TOKEN_EXPIRE_MINUTES=60

# Google Gemini
GEMINI_API_KEY=your-api-key

# Frontend
VITE_API_URL=http://localhost:8000
VITE_API_BASE_PATH=/api
```

## 📝 Development

### Install Development Dependencies
```bash
pip install -r requirements-dev.txt
```

### Code Formatting
```bash
black backend/
isort backend/
```

### Linting
```bash
flake8 backend/
mypy backend/
```

## 🤝 Contributing

1. Fork repository
2. Create feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit changes (`git commit -m 'Add AmazingFeature'`)
4. Push to branch (`git push origin feature/AmazingFeature`)
5. Open Pull Request

## 📄 License

MIT License - xem [LICENSE](LICENSE) file

## 👥 Authors

- Nguyễn Thị Thúy Dung - Founder & Developer

## 📞 Support

- Email: support@example.com
- Issues: [GitHub Issues](https://github.com/yourusername/personalized-learning-path-ai/issues)

---

**Made with ❤️ for learners everywhere**
