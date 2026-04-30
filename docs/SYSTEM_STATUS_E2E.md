# Tinh trang he thong hien tai - Tong quan end-to-end

Ngay cap nhat: 2026-04-30

## 1. Tom tat nhanh

`personalized-learning-path-ai` la mot ung dung full-stack cho viec tao lo trinh hoc tap ca nhan hoa bang AI. He thong hien dang duoc to chuc nhu mot modular monolith gom:

- Frontend React 18 + TypeScript + Vite + Tailwind CSS trong `frontend/`.
- Backend FastAPI trong `backend/`.
- MongoDB lam database chinh.
- Lop AI/RAG gom Gemini, embedding service, BM25/semantic retrieval va cac service tao cau hoi, goi y tai nguyen, AI tutor.
- Docker Compose de chay MongoDB, backend, frontend va tuy chon Mongo Express.

Trang thai ky thuat gan nhat:

- Frontend `npm run type-check` chay thanh cong voi `tsc --noEmit`.
- Repo hien co nhieu thay doi chua commit san tu truoc; tai lieu nay chi bo sung them file docs, khong thay doi code hien co.
- Chua thay thu muc test trong danh sach file hien tai, du `requirements.txt` va `backend/pyproject.toml` da cau hinh pytest cho `backend/tests`.
- README da mo ta `docs/ARCHITECTURE.md`, nhung truoc khi tao file nay repo chua co thu muc `docs`.
- Backend yeu cau `MONGODB_URI`/`MONGO_URI` va `SECRET_KEY` manh khi khoi dong; Gemini la tuy chon nhung cac workflow AI se bi gioi han neu khong cau hinh key.

## 2. Kien truc tong the

Lu anh chinh:

```text
Nguoi dung
  -> React SPA
  -> frontend/src/utils/apiClient.ts
  -> FastAPI /api/*
  -> API routers
  -> Services domain
  -> Repositories
  -> MongoDB collections
  -> AI/embedding/retrieval providers khi can
```

Frontend khong goi truc tiep database hay AI provider. Tat ca yeu cau di qua REST API co prefix `/api`. Backend tach cac phan theo lop:

- `backend/main.py`: khoi tao app, load env, validate runtime, middleware logging, CORS, health/readiness endpoints va dang ky routers.
- `backend/app/api/`: lop transport HTTP, dependency auth/admin, request/response schema.
- `backend/app/services/`: orchestration nghiep vu nhu learning path, lesson, adaptive, resource ingestion, recommendations, analytics, AI tutor.
- `backend/app/repositories/`: truy cap MongoDB theo collection.
- `backend/app/ai_module/`: LLM, embedding va retrieval primitives.
- `backend/app/jobs/`: cac batch/backfill job cho metadata, adaptive scope, resource quality, learner state snapshot.

## 3. Runtime va trien khai

He thong co 2 cach chay chinh.

Chay local thu cong:

- Backend: `python -m uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000`
- Frontend: `npm --prefix frontend run dev`
- MongoDB can chay rieng, mac dinh backend doc `MONGODB_URI` hoac `MONGO_URI`.

Chay bang Docker Compose:

- `mongodb`: MongoDB 7, expose `27017`.
- `backend`: FastAPI, expose `8000`, healthcheck `/api/health`.
- `frontend`: Vite dev server, expose `5173`.
- `mongo-express`: profile `dev`, expose `8081`.

Bien moi truong quan trong:

- Backend: `MONGODB_URI`, `DB_NAME`, `SECRET_KEY`, `ADMIN_EMAILS`, `GEMINI_API_KEY` hoac `GEMINI_API_KEYS`, `EMBEDDING_PROVIDER`, `CORS_ORIGINS`, `UPLOAD_DIR`.
- Frontend: `VITE_API_URL`, `VITE_API_BASE_PATH`, `VITE_APP_NAME`, `VITE_ENABLE_INSECURE_DIRECT_PASSWORD_RESET`.

Backend se tu choi khoi dong neu thieu Mongo URI hoac `SECRET_KEY` khong du manh. Endpoint `/api/ready` kiem tra database va trang thai AI embedding stack; `/api/health/ai` va `/api/debug/ai` tra snapshot ve embedding/vector/chunk.

## 4. Frontend hien tai

Frontend la SPA voi routing chinh trong `frontend/src/App.tsx`:

- `/login`
- `/forgot-password`
- `/signup`
- `/signup-step2`
- `/dashboard`
- `/learning-path`
- `/learning-path/:pathId`
- `/resources`
- `/ai-tutor`
- `/settings`

`AuthProvider` boc toan bo app. `apiClient` gan token JWT tu `localStorage` vao header `Authorization: Bearer ...`, retry network error toi da 3 lan, timeout mac dinh 30 giay va redirect ve `/login` khi gap 401.

Service layer frontend dang gom:

- `authService`: login, signup, forgot password, current user, logout.
- `learningPathService`: subject, generate/history/detail/delete path, lesson progress, study time, question generation, adaptive quiz, concept/progress endpoints.
- `resourceService`: search/list/upload/import/delete resource, job status, admin curation, ingestion health.
- `dashboardService`: progress overview, confidence, summary, adaptive/resource recommendations.
- `adaptiveService`: next action, adaptive recommendation, learner state, recompute state, explanation.
- `learnerProfileService`: profile va diagnostic flow.
- `analyticsService`: admin dashboards.
- `pathRefinementService` va `recommendationInteractionService`: refinement/intervention va feedback interaction.

Trang thai xac minh: `npm run type-check` tai repo root da thanh cong.

## 5. Backend API hien tai

Backend dang dang ky cac router sau duoi `/api`:

- `/auth`: signup, login, forgot-password, logout.
- `/users`: current user va update user.
- `/learner-profile`: profile cua learner.
- `/diagnostic`: start/submit/result diagnostic.
- `/subjects`, `/chapters`, `/lessons`: cau truc noi dung hoc.
- `/learning-paths`: generate, history, detail, delete, lesson progress, lesson locks, study time, study summary.
- `/resources`: list/search/detail, import manual/PDF/YouTube, job status, PDF serving, admin curation va ingestion health.
- `/recommendations`: resource/progress recommendations, debug signal, click/completion/feedback events.
- `/progress`: update va truy van progress/concept progress.
- `/adaptive`: event ingestion, recompute/get learner state, next step/action, recommendations, explanations, admin backfill/audit.
- `/ask`: AI tutor/ask history endpoints.
- `/feedback`, `/kt`, `/path/refinement`, `/interventions`, `/concepts`, `/exercise_attempts`, `/analytics`.

Auth hien dung JWT HS256, password hash bang Argon2, role admin lay tu field `role` hoac email nam trong `ADMIN_EMAILS`. Cac endpoint quan tri dung `require_admin_user`.

Middleware backend ghi log request/response, decode token neu co de gan `user_id`, va dua API events vao `event_logging_service`.

## 6. Data va persistence

MongoDB la persistence layer chinh. Cac collection dang duoc repo/service su dung gom:

- Nguoi dung va auth: `users`, token revoke/index trong auth flow.
- Noi dung hoc: `subjects`, `chapters`, `lessons`, `learning_paths`.
- Tai nguyen: `resources`, `resource_chunks`, `ingestion_jobs`, `resource_quality_stats`.
- Cau hoi va quiz: `lesson_questions`, `question_bank`, `question_semantic_memory`, `exercise_attempts`, `lesson_quiz_attempts`.
- Progress/adaptive: `learning_events`, `adaptive_events`, `adaptive_action_logs`, `learner_state_snapshots`, `learner_resource_state`, `user_learning_state`, `concept_mastery_states`, `lesson_study_time`.
- Feedback/recommendation: `learner_feedback`, `learner_signals`, `recommendation_explanations`.
- Analytics/admin: `event_logs`, `ask_history`, `path_refinement_actions`, `intervention_logs`.
- Learner profile: `learner_profiles`, `diagnostic_sessions`.

Repository layer chiu trach nhiem thao tac collection; service layer thuc hien logic va mapping ket qua sang schema API.

## 7. Luong end-to-end chinh

### 7.1 Dang ky, dang nhap va onboarding

1. Nguoi dung dang ky/dang nhap tu frontend auth pages.
2. Frontend goi `/api/auth/signup` hoac `/api/auth/login`.
3. Backend hash/verify password, tao JWT va tra thong tin user kem role.
4. Frontend luu token/user vao `localStorage`; cac request sau duoc `apiClient` tu dong gan bearer token.
5. Learner co the cap nhat profile qua `/api/learner-profile/me` va lam diagnostic qua `/api/diagnostic/*`.

### 7.2 Nap va tim kiem tai nguyen hoc

1. Admin them resource bang text/manual, PDF hoac YouTube trong Resources page.
2. Frontend goi `/api/resources`, `/api/resources/import-pdf`, `/api/resources/import-youtube` hoac `/api/resources/import`.
3. Backend tao ingestion job va chay background task.
4. Ingestion service trich noi dung, chia chunk, tao embedding, map concept/metadata, luu `resources`, `resource_chunks`, `ingestion_jobs`.
5. Nguoi dung tim kiem qua `/api/resources/search`; backend search theo chunk embedding va tra parent resource hits.
6. Admin co endpoint curation de xem chat luong, duplicate, concept mapping va an/hien resource trong recommendation.

### 7.3 Tao learning path ca nhan hoa

1. Learner chon subject/goal/level tren Learning Path page.
2. Frontend goi `/api/learning-paths/generate`.
3. Backend lay personalization context tu learner profile.
4. `unified_learning_path_service` tao learning path theo subject scope, co the dung LLM/curriculum fallback.
5. He thong tao chapters, lessons, concept graph, mastery metadata va freeze recommended chunks cho lesson khi phu hop.
6. Knowledge tracing bootstrap state ban dau tu path vua tao.
7. Event `learning_path_generated` duoc ghi log.
8. Frontend hien path va co the lay history/detail qua `/api/learning-paths/history` va `/api/learning-paths/{path_id}`.

### 7.4 Hoc lesson, cau hoi va mastery

1. Learner mo lesson trong path.
2. Frontend lay lesson detail, lesson locks, recommended chunks va question set.
3. Backend ghi event `lesson_opened`/`lesson_started`, cap nhat tin hieu implicit feedback va knowledge tracing.
4. Neu can cau hoi, frontend goi `/api/lessons/{lesson_id}/generate-questions` hoac adaptive quiz `/api/lessons/{lesson_id}/adaptive-quiz/next`.
5. Question generation chi dua tren recommended chunks da freeze; co template, fallback va tuy chon LLM.
6. Khi learner nop bai/cap nhat tien do, frontend goi `/api/learning-paths/lesson-progress`.
7. Backend danh gia completion bang mastery engine, khong chi dua tren raw accuracy. Tin hieu chinh gom accuracy, Bloom pass, concept coverage, critical concepts va confidence.
8. Backend cap nhat learning path, knowledge tracing, feedback, adaptive events, event logs va co the kich hoat path refinement neu performance thap.

### 7.5 AI tutor va RAG

1. Nguoi dung dat cau hoi trong AI Tutor page.
2. Frontend goi `/api/ask`.
3. Backend AI tutor service phat hien concept, truy xuat context tu resources/chunks/history, build prompt, goi answer generation va map citations.
4. Ket qua duoc tra ve frontend, dong thoi ask history va cac post-response action co the duoc ghi lai.
5. Neu thieu Gemini key hoac embedding backend khong san sang, chat luong/kha nang RAG se phu thuoc fallback hien co.

### 7.6 Adaptive learning loop va recommendations

1. Cac hanh vi hoc tap tao events: lesson opened/completed, quiz submitted, time spent, recommendation click/completion, feedback.
2. Backend ghi vao learning/adaptive/event collections.
3. Adaptive service tinh learner state snapshot theo user/path/lesson.
4. Frontend co the lay:
   - `/api/adaptive/next-action`
   - `/api/adaptive/recommendation`
   - `/api/adaptive/state/{user_id}`
   - `/api/adaptive/next-step`
   - `/api/adaptive/explanations/{user_id}`
5. Recommendations ket hop retrieval, scoring, filters, reranking va explanations. Feedback/click/completion tiep tuc lam tin hieu cho vong lap sau.

### 7.7 Analytics va admin

1. Backend tong hop tu `learning_events`, `lesson_quiz_attempts`, `lesson_study_time`, `learner_state_snapshots`, `ask_history`, `resources`, path refinement va intervention logs.
2. Frontend admin/dashboard services goi `/api/analytics/admin/dashboard`, `/api/analytics/admin/average-study-hours`, `/api/analytics/admin/research-dashboard`.
3. Resource admin curation va ingestion health nam trong `/api/resources/admin/*`.
4. Adaptive admin backfill/audit nam trong `/api/adaptive/admin/backfill-path-scope*`.

## 8. Trang thai chat luong va rui ro hien tai

Nhung diem tot:

- Phan lop backend tuong doi ro: API -> service -> repository.
- Frontend co service layer rieng va parser/normalizer cho nhieu response.
- Co health/readiness endpoints cho database va AI stack.
- Co nhieu workflow domain da duoc noi thanh vong lap: path generation, lesson progress, KT, adaptive, feedback, recommendation.
- Docker Compose da bao phu local stack co MongoDB, backend, frontend.

Rui ro/gap can theo doi:

- Chua thay test files trong repo hien tai; backend pytest config ton tai nhung `backend/tests` chua co trong danh sach file.
- Chua xac minh backend startup/runtime trong lan kiem tra nay vi can MongoDB va env secret thuc.
- Worktree dang co nhieu file modified/deleted/untracked tu truoc; can tach bach thay doi truoc khi release/merge.
- Mot so service backend va page frontend co pham vi lon, de kho debug khi workflow adaptive/RAG loi.
- Cau hinh runtime phan tan giua root `.env`, `backend/.env`, `.env.example`, Docker Compose va frontend `.env`.
- Neu khong cau hinh Gemini/embedding provider dung, mot so tinh nang AI/RAG se roi ve fallback hoac khong dat chat luong mong muon.
- README co nhac den `docs/ARCHITECTURE.md`; nen tao/cap nhat them tai lieu kien truc rieng hoac doi link ve file nay.

## 9. Checklist van hanh de kiem tra end-to-end

Truoc khi demo hoac release, nen kiem tra theo thu tu:

1. Tao `.env` hop le voi `MONGODB_URI`, `DB_NAME`, `SECRET_KEY` manh, `GEMINI_API_KEY` neu dung AI.
2. Chay MongoDB va backend; kiem tra `/api/health`, `/api/ready`, `/api/health/ai`.
3. Chay frontend; dang ky/dang nhap va xac nhan token duoc gan vao API requests.
4. Tao/cap nhat learner profile va chay diagnostic.
5. Import it nhat mot resource, doi ingestion job complete, search resource bang `/resources/search`.
6. Generate learning path theo subject/goal/level.
7. Mo lesson, lay recommended chunks, tao questions, submit quiz/progress.
8. Kiem tra adaptive next action/recommendation sau khi co event.
9. Kiem tra AI Tutor tra loi co context/citation hop ly.
10. Kiem tra analytics/admin dashboard va resource curation.
11. Chay frontend type-check/build va backend tests khi co test suite.

## 10. Ket luan hien tai

He thong dang o trang thai functional prototype/monolithic product codebase: domain workflow da kha day du va co kha nang chay end-to-end neu cau hinh MongoDB, secret va AI provider dung. Thanh phan frontend da pass type-check. Diem yeu lon nhat hien tai la thieu test suite hien huu, chua co xac minh backend runtime trong lan danh gia nay, va worktree dang co nhieu thay doi chua dong goi nen can duoc lam sach/tracking truoc khi release.
