# Tài liệu mô tả backend

## 1. Mục tiêu của backend

Backend của dự án được xây dựng bằng `FastAPI + MongoDB`, đóng vai trò trung tâm điều phối cho hệ thống học tập cá nhân hóa có tích hợp AI. Phần này không chỉ cung cấp API CRUD cơ bản mà còn triển khai nhiều luồng nghiệp vụ thông minh:

- xác thực người dùng bằng JWT
- lưu trữ và tìm kiếm học liệu
- import học liệu từ PDF và YouTube
- hỏi đáp AI theo kiểu RAG
- phát hiện concept liên quan tới câu hỏi
- cập nhật tiến độ học tập theo mức độ tự tin
- sinh lộ trình học thích ứng
- gợi ý tài nguyên phù hợp với trình độ và trạng thái học
- sinh câu hỏi đánh giá dựa trên nội dung bài học

Nói ngắn gọn, backend này là lớp điều phối giữa:

1. dữ liệu người dùng và học liệu trong MongoDB
2. vector search / embedding để truy hồi ngữ nghĩa
3. logic thích ứng học tập
4. LLM để trả lời, chấm confidence, và sinh curriculum khi cần

---

## 2. Kiến trúc tổng thể

### 2.1. Cấu trúc lớp

Backend được tổ chức theo hướng `router mỏng - service dày`:

- `backend/main.py`
  - khởi tạo FastAPI app
  - cấu hình middleware, CORS, exception handler
  - mount toàn bộ router
- `backend/app/api`
  - định nghĩa endpoint, validate request, auth, trả response
  - hầu như không chứa business logic lớn
- `backend/app/services`
  - chứa phần nghiệp vụ chính
  - tập trung toàn bộ thuật toán RAG, adaptive learning, progress, search, import, recommendation
- `backend/app/database`
  - kết nối MongoDB
- `backend/app/utils`
  - tiện ích phụ trợ

### 2.2. Các module nghiệp vụ chính

- `auth.py`: đăng ký, đăng nhập, tạo và xác thực JWT
- `resources.py` + `resource_service.py`: quản lý học liệu
- `ai_tutor/service.py` + `ai_tutor/rag.py`: hỏi đáp AI, phát hiện concept, cập nhật tiến độ
- `learning_path/service.py`: sinh lộ trình học và curriculum
- `progress_tracking/progress.py`: theo dõi mastery, confidence, attempts
- `adaptive_engine.py`: quyết định mode học `remedial / normal / advanced`
- `embedding_service.py`: tạo embedding, lưu vector, semantic search
- `search_service.py`: multi-strategy search
- `resource_imports/pdf.py`: nhập PDF, trích xuất text, chunk, embedding
- `resource_imports/youtube.py`: nhập YouTube, transcript, chunk, embedding
- `question_generation/*`: pipeline sinh câu hỏi đánh giá

---

## 3. Entry point và khởi tạo ứng dụng

File: `backend/main.py`

### 3.1. Những gì xảy ra khi app khởi động

1. `load_dotenv()` nạp biến môi trường.
2. `validate_env()` kiểm tra ít nhất:
   - `MONGODB_URI`
   - `SECRET_KEY` phải khác giá trị mặc định
3. app khởi tạo `FastAPI(...)` với docs tại:
   - `/api/docs`
   - `/api/openapi.json`
4. middleware được gắn:
   - logging middleware để log method, path, status, thời gian xử lý
   - CORS middleware
5. router được mount dưới prefix `/api`
6. có thêm endpoint kiểm tra hệ thống:
   - `/`
   - `/api/health`
   - `/api/ready`

### 3.2. Ý nghĩa kỹ thuật

`main.py` đóng vai trò cổng vào duy nhất của backend. Phần này không làm nghiệp vụ, nhưng chịu trách nhiệm đảm bảo:

- ứng dụng chỉ chạy khi cấu hình hợp lệ
- request/response được log để theo dõi
- lỗi validation và lỗi runtime được chuẩn hóa thành JSON response

---

## 4. Tầng dữ liệu MongoDB

File: `backend/app/database/mongo.py`

### 4.1. Cơ chế kết nối

- dùng `pymongo.MongoClient`
- lấy URI từ `MONGODB_URI` hoặc `MONGO_URI`
- database mặc định là `personalized_learning_path`

### 4.2. Các collection thực tế đang được dùng

Dựa trên code hiện tại, backend thao tác chủ yếu với các collection:

- `users`
- `resources`
- `embeddings`
- `concepts`
- `prerequisites`
- `progress`
- `ask_history`
- `learning_paths`
- `search_history`

### 4.3. Kiểu ID

- `users`, `resources`, `embeddings`, `learning_paths`, `ask_history` dùng `_id` kiểu Mongo `ObjectId`
- `concepts` dùng thêm `concept_id` kiểu số nguyên để phục vụ graph/prerequisite
- nhiều chỗ trong service trả ID dưới dạng string để client dễ dùng

---

## 5. Luồng API chính

### 5.1. Auth

File: `backend/app/api/auth.py`

Chức năng:

- `POST /api/auth/signup`
- `POST /api/auth/login`
- dependency `get_current_user()`

Thuật toán/chức năng chính:

- hash mật khẩu bằng `Argon2`
- verify password qua `passlib`
- tạo JWT với claim `sub = user_id`
- decode JWT và truy vấn user từ MongoDB

Vai trò:

- là lớp bảo vệ cho các endpoint cần xác thực
- tách riêng logic token khỏi nghiệp vụ học tập

### 5.2. Ask / AI Tutor

File: `backend/app/api/ask.py`

Các endpoint đáng chú ý:

- `POST /api/ask/`
- `GET /api/ask/adaptive-status`
- `POST /api/ask/detect-concepts`
- `GET /api/ask/recommend-concepts`
- `GET /api/ask/history`
- `DELETE /api/ask/history/{history_id}`
- `POST /api/ask/generate-assessment`

Router này chủ yếu làm 3 việc:

1. xác thực người dùng
2. validate request
3. gọi `AITutorService`

### 5.3. Learning Path

File: `backend/app/api/learning_path.py`

Endpoint chính:

- `POST /api/learning-path/generate`
- `GET /api/learning-path/history`
- `POST /api/learning-path/lesson-progress`
- `GET /api/learning-path/{path_id}`

Ý nghĩa:

- sinh lộ trình học cho goal hiện tại
- lưu lịch sử learning path
- cập nhật trạng thái lesson trong curriculum

### 5.4. Progress

File: `backend/app/api/progress.py`

Endpoint:

- `POST /api/progress/update`
- `GET /api/progress/summary`
- `GET /api/progress/overview`
- `GET /api/progress/confidence`
- `GET /api/progress/concept/{concept_id}`

Vai trò:

- ghi nhận tiến độ từng concept
- tổng hợp dashboard tiến độ và xu hướng confidence

### 5.5. Resources

File: `backend/app/api/resources.py`

Endpoint:

- `GET /api/resources/`
- `POST /api/resources/`
- `POST /api/resources/import`
- `GET /api/resources/search`
- `POST /api/resources/import-pdf`
- `POST /api/resources/import-youtube`
- `GET /api/resources/pdf/{resource_id}`

Vai trò:

- quản lý học liệu dạng text/PDF/YouTube
- phục vụ import, tìm kiếm và tải PDF

### 5.6. Concepts / Recommendations / RAG utility

- `concepts.py`: liệt kê concept và prerequisite graph
- `recommendations.py`: gợi ý tài nguyên và tổng hợp tiến độ theo goal
- `rag.py`: upload PDF nhanh và chat RAG đơn giản

---

## 6. Phân tích service lõi

## 6.1. `ai_tutor/service.py`

Đây là service điều phối trung tâm cho luồng hỏi đáp AI.

### 6.1.1. `ConceptDetector`

`ConceptDetector` dùng chiến lược nhiều tầng:

1. `detect_semantic(question)`
   - embed câu hỏi
   - so với embedding của tất cả concept
   - chọn concept có cosine similarity cao nhất nếu vượt ngưỡng
2. `detect_rule_based(question)`
   - xây map từ khóa dựa trên `concept_name`, `topic`, và synonym đơn giản
   - đếm số keyword match
3. `detect_fallback()`
   - nếu không match được thì trả concept dễ nhất

Đây là thiết kế kiểu `semantic first, rule-based second, fallback last`.

### 6.1.2. `AITutorService.ask_ai(...)`

Đây là pipeline nghiệp vụ quan trọng nhất của hệ thống:

1. gọi RAG để lấy câu trả lời
2. chấm confidence của câu trả lời
3. phát hiện concept mà câu hỏi đang nhắm tới
4. cập nhật tiến độ của user trên concept đó
5. tính adaptive mode
6. sinh learning path mới phù hợp mode
7. đóng gói response về cho API

Response trả về gồm:

- `answer`
- `learning_path`
- `concept_detected`
- `adaptive_info`
- `progress_updated`

### 6.1.3. Sinh assessment

`generate_assessment_questions(...)` hiện đang dựa chủ yếu vào rule-based grounding:

- tách các đoạn trích từ `chapter_content`
- chọn excerpt liên quan tới concept
- sinh câu hỏi bằng template theo `difficulty` và `question_type`
- sinh answer/explanation ngắn bám trực tiếp vào excerpt

Điểm mạnh của cách này là an toàn, ít hallucination hơn vì câu hỏi bám nội dung đầu vào.

---

## 6.2. `ai_tutor/rag.py`

Đây là module RAG cốt lõi của hệ thống.

### 6.2.1. Vai trò

`RAGPipeline` triển khai đủ chuỗi:

1. retrieval
2. context building
3. prompt building
4. answer generation
5. fallback khi LLM lỗi hoặc không có tài liệu

### 6.2.2. Thuật toán retrieval

Hàm `retrieve_context(...)`:

- gọi `semantic_search(...)`
- lấy ra danh sách resource phù hợp với query
- không ép topic filter cứng vì goal có thể là tiếng Việt còn topic trong DB là tiếng Anh
- nếu không có resource thì cho phép rơi về nhánh AI/fallback

### 6.2.3. Thuật toán direct answer vs AI answer

Hàm `_can_answer_from_context(resources)` quyết định có thể trả lời trực tiếp từ tài liệu hay không.

Điều kiện:

- phải là tài liệu thật từ DB
- phải có ít nhất `MIN_HIGH_QUALITY_RESOURCES`
- mỗi tài liệu phải có `score >= DIRECT_ANSWER_THRESHOLD`

Nếu đạt điều kiện:

- gọi `_generate_direct_answer(...)`
- tổng hợp câu trả lời trực tiếp từ snippet
- không cần gọi LLM

Nếu không đạt:

- build context
- build prompt
- gọi LLM để tạo câu trả lời

Đây là chiến lược tiết kiệm token và giảm hallucination khi retrieval đủ mạnh.

### 6.2.4. Thuật toán build context

`build_context(resources)`:

- ghép các snippet theo format nguồn
- cắt theo `MAX_CONTEXT_CHARS`
- ưu tiên cắt ở ranh giới câu bằng `_truncate_to_sentence(...)`

### 6.2.5. Các fallback trong RAG

Module có rất nhiều nhánh an toàn:

- fallback knowledge base nếu thiếu tài liệu thật
- fallback retrieval-only khi Gemini không dùng được
- cooldown khi dính quota
- parse nhiều kiểu response object của SDK

### 6.2.6. Ý nghĩa thiết kế

RAG ở đây không chỉ là “search rồi gọi LLM”, mà còn có một lớp quyết định:

- khi nào nên trả lời trực tiếp
- khi nào nên dùng AI
- khi nào phải hạ cấp sang fallback

---

## 6.3. `progress_tracking/progress.py`

Đây là module quản lý tiến độ học tập.

### 6.3.1. Thuật toán chính: EMA mastery

Hàm `update_progress_with_confidence(...)` dùng công thức:

`new_mastery = old_mastery * (1 - alpha) + confidence * alpha`

Trong đó:

- `alpha` lấy từ env `PROGRESS_ALPHA`, mặc định `0.3`
- `confidence` là điểm đánh giá chất lượng câu trả lời

Ý nghĩa:

- điểm mastery không nhảy quá mạnh sau một lần hỏi
- kiến thức được cập nhật theo kiểu “học dần”
- các lần gần đây có ảnh hưởng nhiều hơn quá khứ

### 6.3.2. Các trường được cập nhật

Ngoài mastery, service còn cập nhật:

- `confidence`
- `total_attempts`
- `successful_attempts`
- `success_rate`
- `status`
- `last_updated`

### 6.3.3. Trạng thái tiến độ

`_calculate_status(mastery)`:

- `0` -> `not_started`
- `> 0` -> `in_progress`
- `>= proficient threshold` -> `proficient`
- `>= complete threshold` -> `complete`

### 6.3.4. Các hàm đọc dữ liệu

- `get_progress(user_id, concept_id)`
- `get_user_progress_summary(user_id)`
- `get_concept_progress(concept_id)`

Chúng phục vụ dashboard, API overview và phân tích theo người học / concept.

---

## 6.4. `progress_tracking/confidence_scorer.py`

Module này chấm điểm độ tin cậy của câu trả lời trong khoảng `[0, 1]`.

### 6.4.1. Cách hoạt động

1. rút gọn question/answer theo giới hạn
2. tạo prompt yêu cầu Gemini chỉ trả về một số thực từ `0.0` đến `1.0`
3. thử nhiều dạng SDK call
4. parse text hoặc trường số trong response
5. nếu mọi thứ lỗi thì trả fallback `0.5`

### 6.4.2. Ý nghĩa

Điểm confidence này chính là đầu vào cho:

- cập nhật mastery
- adaptive engine
- thống kê tiến độ người học

---

## 6.5. `adaptive_engine.py`

Đây là module quyết định chiến lược học tập thích ứng.

### 6.5.1. Ba mode học

- `REMEDIAL`: học lại, củng cố nền tảng
- `NORMAL`: học theo lộ trình tiêu chuẩn
- `ADVANCED`: tăng tốc, chuyển sang tài nguyên khó hơn

### 6.5.2. Thuật toán `decide_learning_mode(...)`

Decision tree:

1. nếu `mastery < low` hoặc `confidence < low` -> `REMEDIAL`
2. nếu `mastery >= high` và `confidence >= high` và `attempts <= max` -> `ADVANCED`
3. còn lại -> `NORMAL`

Đây là một decision rule rất rõ ràng, dễ điều chỉnh bằng env.

### 6.5.3. Thuật toán lọc tài nguyên

`filter_resources_by_mode(resources, mode)` dựa trên Bloom taxonomy:

- remedial: `remember`, `understand`
- normal: `remember`, `understand`, `apply`
- advanced: `apply`, `analyze`, `evaluate`, `create`

### 6.5.4. Các quyết định phụ trợ

- `can_unlock_next_concept(...)`
- `recommend_difficulty_boost(...)`
- `get_practice_recommendations(...)`
- `adaptive_decision_summary(...)`
- `rank_resources_by_adaptiveness(...)`

Nói cách khác, adaptive engine không chỉ nói “đang ở mode nào”, mà còn gợi ý:

- có nên mở concept tiếp theo không
- nên tăng/giảm độ khó hay không
- nên drill, review hay challenge

---

## 6.6. `learning_path/service.py`

Đây là service sinh lộ trình học tập cá nhân hóa.

### 6.6.1. Luồng chính `generate_learning_path(...)`

Pipeline thực tế:

1. validate `user_id`, `goal`, `level`
2. đọc progress hiện tại của user
3. lấy toàn bộ concept
4. xây graph prerequisite
5. phát hiện cycle
6. topological sort graph
7. lọc concept theo level
8. xác định adaptive mode từ tiến độ hiện tại
9. loại các concept đã hoàn thành hoặc chưa đủ prerequisite
10. tính `priority_score`
11. gọi `recommend_resources_for_concept(...)`
12. nếu cần thì gọi LLM để sinh curriculum chương/bài

### 6.6.2. Thuật toán prerequisite graph

Graph được xây từ collection `prerequisites`:

- node: `concept_id`
- edge: `from_concept_id -> to_concept_id`

Hàm:

- `_has_cycle(graph)`: DFS tô màu `WHITE/GRAY/BLACK`
- `_topological_sort(graph)`: DFS hậu tự

Nếu graph có chu trình:

- service ghi log cảnh báo
- fallback sang thứ tự tùy ý để tránh crash

### 6.6.3. Thuật toán xếp hạng concept

Mỗi concept đủ điều kiện được tính điểm dựa trên:

- độ khó so với level hiện tại
- bonus nếu phù hợp khoảng difficulty của level
- penalty nếu user đã học dở concept đó

Công thức gần đúng:

`priority = level_factor * (10 - difficulty)/10 + level_bonus - started_penalty`

### 6.6.4. Sinh curriculum bằng AI

Phần curriculum có 2 đường:

1. `AI path`
   - retrieve thêm materials cho goal
   - build prompt JSON
   - gọi LLM
   - parse JSON
   - normalize chapter/lesson
2. `fallback path`
   - build curriculum từ danh sách concept/recommended path

Hàm `_generate_curriculum(...)` có retry parse JSON, và luôn có fallback nếu AI không trả dữ liệu hợp lệ.

### 6.6.5. Trường hợp không có concept trong DB

Nếu DB chưa có concept:

- service dùng `_build_goal_seed_concepts(goal, level)`
- tạo các concept seed từ chính goal
- sau đó vẫn cố sinh curriculum

Điều này giúp hệ thống vẫn hoạt động ngay cả khi dữ liệu seed chưa đầy đủ.

---

## 6.7. `learning_path/recommender.py`

Module này chuyên gợi ý resource cho từng concept.

### 6.7.1. Thuật toán chấm điểm tài nguyên

Mỗi resource được chấm bởi nhiều tín hiệu:

- semantic similarity với query
- độ phù hợp của `bloom_level` với `user_level`
- độ phù hợp của `pedagogy_type`
- độ mới của tài nguyên

Hàm `_calculate_composite_score(...)` dùng trọng số:

- semantic: 40%
- bloom: 30%
- pedagogy: 20%
- recency: 10%

### 6.7.2. Ý nghĩa

Đây là module giúp learning path không chỉ trả “concept tiếp theo”, mà còn đính kèm “nên học bằng tài nguyên nào”.

---

## 6.8. `embedding_service.py`

Module này là nền tảng của semantic search.

### 6.8.1. Tạo embedding

`embed_text(text)` có 2 hướng:

1. nếu có external embedding provider thì dùng provider
2. nếu không thì dùng fallback embedding dựa trên hash

Fallback hiện tại:

- tạo seed từ `md5(text)`
- sinh vector ngẫu nhiên ổn định theo seed
- normalize vector

Điểm cần hiểu rõ:

- fallback này ổn định, nhưng không thật sự mang nghĩa ngữ nghĩa như embedding chuẩn của model
- nó phù hợp cho môi trường dev/fallback hơn là production semantic quality cao

### 6.8.2. Lưu resource và chunk embedding

- `store_resource(...)`: lưu resource chính vào `resources`
- `store_embedding_only(...)`: lưu chunk vào `embeddings`

### 6.8.3. Thuật toán `semantic_search(...)`

Đây là điểm rất quan trọng:

1. embed query
2. quét collection `resources`
3. quét collection `embeddings`
4. với chunk match thì truy ngược `parent_resource_id`
5. deduplicate theo resource
6. giữ score tốt nhất cho mỗi resource
7. sort giảm dần theo cosine similarity

Thiết kế này cho phép:

- search cả trên tài nguyên tổng quát
- search sâu vào các chunk nhỏ của PDF
- nhưng vẫn trả về resource cấp cao để frontend dễ hiển thị

---

## 6.9. `search_service.py`

Đây là lớp search nâng cao, đa chiến lược.

### 6.9.1. Các chiến lược tìm kiếm

- semantic search
- keyword search
- concept-aware search
- popularity/trending search

### 6.9.2. Thuật toán `search_learning_resources(...)`

Pipeline:

1. validate query
2. chọn chiến lược tìm kiếm
3. chạy từng chiến lược
4. merge kết quả
5. deduplicate
6. áp boost theo popularity/recency/review
7. sort theo `relevance | recency | popularity`
8. ghi `search_history`

### 6.9.3. Công thức boost

`_get_search_score_boost(...)` cộng điểm bởi:

- `hit_count`
- `created_at`
- `is_reviewed`

Điều này giúp resource phổ biến hoặc mới được đẩy lên cao hơn khi relevance tương đương.

---

## 6.10. `resource_service.py`

Đây là service orchestration cho tài nguyên.

### 6.10.1. Chức năng chính

- list resource có phân trang
- add resource thủ công
- import batch
- search theo regex
- import PDF
- import YouTube
- thống kê tài nguyên

### 6.10.2. Hàm tiêu biểu

- `get_resources_service(...)`
- `add_resource_service(...)`
- `import_resources_service(...)`
- `search_resources_service(...)`
- `import_pdf_service(...)`
- `import_youtube_service(...)`
- `get_resource_stats(...)`

### 6.10.3. Vai trò trong hệ thống

`resource_service.py` là lớp phối hợp giữa API và các importer/phần lưu embedding. Nó giúp API không phải biết chi tiết:

- validate file thế nào
- lưu file ở đâu
- gọi importer ra sao
- chuẩn hóa dữ liệu trả về như thế nào

---

## 6.11. `resource_imports/pdf.py`

Đây là module import PDF vào hệ thống RAG.

### 6.11.1. Pipeline

1. validate file path và kích thước
2. trích xuất text từ PDF bằng `PyMuPDF`, fallback `pypdf`
3. tạo thumbnail nếu có thể
4. tạo một resource chính cho file PDF
5. chunk toàn bộ text
6. lọc chunk theo relevance
7. inject context
8. lưu từng chunk vào `embeddings`

### 6.11.2. Thuật toán chunking

`chunk_text(...)`:

- chia theo `chunk_size`
- có `overlap`
- ưu tiên cắt ở ranh giới câu / đoạn
- có guard chống vòng lặp vô hạn

### 6.11.3. Thuật toán relevance filter

`_get_topic_keywords(topic)` tạo danh sách keyword theo chủ đề.

`_score_chunk_relevance(chunk, keywords)`:

- đếm số keyword match
- chia cho tổng số keyword
- lấy làm relevance score

`_is_relevant_chunk(...)` giữ lại chunk nếu score vượt ngưỡng.

Nếu pass 1 không có chunk nào:

- module retry một lượt không dùng keyword filter

Điều này rất hữu ích khi topic quá rộng hoặc keyword set chưa tốt.

---

## 6.12. `resource_imports/youtube.py`

Đây là module import video YouTube thành học liệu.

### 6.12.1. Pipeline

1. validate URL
2. extract `video_id`
3. check duplicate
4. lấy metadata bằng `pytube`
5. lấy transcript bằng `youtube-transcript-api`
6. nếu không có transcript thì vẫn lưu metadata-only
7. nếu có transcript thì chunk text
8. embed từng chunk
9. lưu chunk thành documents trong `resources`

### 6.12.2. Thuật toán chunk transcript

`_chunk_text_with_overlap(...)`:

- chia theo số ký tự
- ưu tiên cắt ở dấu câu hoặc newline
- thêm overlap để giữ ngữ cảnh
- loại chunk quá ngắn

### 6.12.3. Đặc điểm thiết kế

Khác PDF importer:

- YouTube hiện lưu từng chunk trực tiếp vào `resources`
- PDF lại lưu 1 resource chính và các chunk ở `embeddings`

Đây là điểm rất quan trọng khi đọc dữ liệu hoặc thiết kế frontend hiển thị.

---

## 6.13. `concept_mapper.py`

Module này map text tự do sang `concept_id`.

### 6.13.1. Thuật toán chấm điểm

`resolve_concept_id(topic, allow_fallback=True, min_score=0.40)` kết hợp:

- exact topic match
- exact concept_name match
- substring match
- token overlap
- fuzzy similarity bằng `difflib.SequenceMatcher`

Nếu score tốt nhất < `min_score`:

- nếu `allow_fallback=True` thì trả concept dễ nhất
- nếu không thì trả `None`

Đây là thuật toán rule-based lai fuzzy matching, nhẹ nhưng khá thực dụng.

---

## 6.14. `question_generation/*`

Nhóm module này phục vụ sinh câu hỏi đánh giá.

### 6.14.1. Thành phần

- `lesson_content.py`: truy hồi nội dung bài học
- `prompt_builder.py`: dựng prompt
- `llm_generator.py`: gọi LLM để sinh câu hỏi
- `validator.py`: lọc và xác thực câu hỏi sinh ra
- `pipeline.py`: ghép toàn bộ pipeline
- `generator.py`, `bloom.py`, `rules.py`, `templates.py`: các hướng sinh câu hỏi theo template/rule/Bloom

### 6.14.2. Pipeline chuẩn

`LessonQuestionGenerationPipeline.run(...)`:

1. retrieve lesson chunks
2. generate nhiều câu hỏi hơn target
3. validate grounding và chất lượng
4. chuẩn hóa output thành danh sách question dict

Ý tưởng ở đây là:

- sinh dư trước
- lọc sau

Đây là pattern rất hay dùng khi sinh nội dung bằng LLM.

---

## 7. Phân tích các thuật toán cốt lõi

## 7.1. Thuật toán phát hiện concept

Nguồn: `ai_tutor/service.py`

Mô hình:

1. semantic similarity
2. keyword matching
3. fallback concept dễ nhất

Ưu điểm:

- chịu lỗi tốt
- vẫn chạy được nếu embedding kém hoặc DB thiếu dữ liệu

Nhược điểm:

- fallback có thể trả concept không thật sự liên quan

## 7.2. Thuật toán mastery theo EMA

Nguồn: `progress_tracking/progress.py`

Mô hình:

- không dùng điểm tuyệt đối một lần
- dùng trung bình mũ để “làm mượt” tiến độ

Phù hợp với hệ thống tutoring vì:

- một câu trả lời sai không kéo tụt toàn bộ mastery quá mạnh
- người học cải thiện dần sẽ phản ánh tốt hơn

## 7.3. Thuật toán adaptive decision

Nguồn: `adaptive_engine.py`

Mô hình:

- rule-based decision tree
- đầu vào: mastery, confidence, attempts
- đầu ra: mode học + difficulty boost + practice recommendation

Ưu điểm:

- minh bạch, dễ giải thích
- dễ thay đổi ngưỡng qua env

## 7.4. Thuật toán prerequisite graph

Nguồn: `learning_path/service.py`

Mô hình:

- graph concept phụ thuộc
- detect cycle
- topo sort
- chỉ cho qua những concept đủ prerequisite

Đây là xương sống giúp learning path có logic sư phạm thay vì random.

## 7.5. Thuật toán semantic retrieval hai tầng

Nguồn: `embedding_service.py`

Mô hình:

- tìm trên `resources`
- tìm trên `embeddings`
- quy chunk về parent resource
- deduplicate

Điểm mạnh:

- vừa truy hồi sâu theo đoạn nhỏ
- vừa trả về entity đủ lớn cho UI và recommendation

## 7.6. Thuật toán curriculum generation có fallback

Nguồn: `learning_path/service.py`

Mô hình:

- AI sinh JSON chapters/lessons
- parse retry
- normalize structure
- fallback curriculum nếu AI fail

Điểm mạnh:

- vẫn giữ được tính linh hoạt của AI
- không làm hỏng trải nghiệm nếu AI trả JSON lỗi

## 7.7. Thuật toán scoring resource recommendation

Nguồn: `learning_path/recommender.py`

Mô hình:

- semantic
- Bloom fit
- pedagogy fit
- recency

Đây là cơ chế giúp resource gợi ý “hợp người học” hơn là chỉ “hợp chủ đề”.

---

## 8. Các model dữ liệu đầu vào/đầu ra quan trọng

File: `backend/app/api/schemas.py`

Các enum chính:

- `LevelEnum`: `beginner | intermediate | advanced`
- `SourceEnum`: `pdf | youtube | web`
- `PedagogyEnum`: `video | text | quiz`

Các request/response quan trọng:

- `ResourceCreate`
- `ResourceImportRequest`
- `YouTubeImportRequest`
- `ProgressUpdate`
- `LearningPathResponse`
- `AskRequest`
- `AskResponse`
- `GenerateAssessmentQuestionsRequest`

Ý nghĩa:

- toàn bộ API hiện tại dùng Pydantic để chuẩn hóa payload
- giúp backend tự động validate format trước khi chạm tới service

---

## 9. Các luồng nghiệp vụ tiêu biểu

## 9.1. Luồng hỏi đáp AI

1. client gọi `POST /api/ask/`
2. API xác thực JWT
3. `AITutorService.ask_ai(...)`
4. `RAGPipeline.run(...)`
5. `score_confidence(...)`
6. `ConceptDetector.detect(...)`
7. `update_progress_with_confidence(...)`
8. `adaptive_decision_summary(...)`
9. `generate_learning_path(...)`
10. lưu `ask_history`
11. trả response cho frontend

## 9.2. Luồng import PDF

1. client upload file
2. API validate extension/size
3. file được lưu vào `backend/uploads`
4. `import_pdf(...)` trích xuất text
5. text được chunk
6. chunk được lọc relevance
7. embedding được lưu vào DB
8. resource chính giữ `pdf_file_path`
9. frontend có thể gọi `/api/resources/pdf/{resource_id}` để xem file

## 9.3. Luồng sinh learning path

1. đọc tiến độ user
2. dựng graph concept
3. topo sort
4. lọc theo level và prerequisite
5. tính adaptive mode
6. gợi ý resource cho từng concept
7. cố sinh curriculum bằng AI
8. fallback nếu AI lỗi
9. lưu vào `learning_paths`

---

## 10. Điểm mạnh của backend hiện tại

- kiến trúc module hóa khá rõ giữa `api` và `services`
- nhiều cơ chế fallback nên hệ thống khó bị “gãy cứng”
- đã có kết hợp giữa graph learning path, progress tracking và RAG
- có nhiều lớp scoring thay vì logic một chiều
- import PDF/YouTube được thiết kế riêng, không trộn lẫn
- curriculum generation có kiểm soát format JSON

---

## 11. Những điểm cần lưu ý khi mở rộng

### 11.1. Sự khác nhau giữa các kiểu search

Hiện có hai hướng search:

- `resource_service.search_resources_service(...)`: regex/text search đơn giản
- `search_service.search_learning_resources(...)`: multi-strategy search nâng cao

Nếu muốn frontend dùng search “thông minh” hơn, nên cân nhắc nối endpoint sang `search_service.py`.

### 11.2. Chất lượng embedding fallback

Embedding fallback hiện là hash-based deterministic vector. Nó ổn cho fallback/dev, nhưng nếu cần retrieval chính xác hơn ở production thì nên thay bằng embedding model thật.

### 11.3. Hai kiểu lưu chunk khác nhau

- PDF: resource chính ở `resources`, chunk ở `embeddings`
- YouTube: chunk lưu trực tiếp trong `resources`

Khi viết analytics hoặc UI, cần nhớ khác biệt này để tránh đếm sai.

### 11.4. Adaptive engine hiện là rule-based

Đây là ưu điểm về tính minh bạch, nhưng nếu sau này muốn cá nhân hóa sâu hơn có thể nâng cấp sang:

- bandit / reinforcement heuristics
- knowledge tracing
- mastery model theo từng kỹ năng con

---

## 12. Kết luận

Backend hiện tại không chỉ là REST API CRUD, mà là một backend AI orchestration tương đối đầy đủ. Trục chính của hệ thống là:

- `RAGPipeline` để trả lời
- `ConceptDetector` để hiểu người học đang hỏi gì
- `Progress Service` để cập nhật mastery
- `Adaptive Engine` để chọn mode học
- `Learning Path Service` để sinh bước học tiếp theo

Nếu mô tả ngắn bằng một câu:

> Backend này là bộ não điều phối giữa dữ liệu học tập, truy hồi ngữ nghĩa, suy luận AI và cơ chế học thích ứng cho từng người dùng.

