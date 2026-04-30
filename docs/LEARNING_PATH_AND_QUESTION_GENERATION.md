# Phan tich chuc nang sinh lo trinh hoc tap va sinh cau hoi

Ngay cap nhat: 2026-04-30

Tai lieu nay mo ta rieng hai workflow quan trong cua he thong:

- Sinh lo trinh hoc tap ca nhan hoa.
- Sinh bo cau hoi theo lesson, gom ca quiz thuong va adaptive quiz.

Noi dung duoc viet theo trang thai code hien tai trong `backend/app/api/learning_paths.py`, `backend/app/api/lessons.py`, `backend/app/services/learning_path/`, `backend/app/services/question_generation/` va cac service lien quan.

## 1. Muc tieu nghiep vu

Chuc nang sinh lo trinh hoc tap nhan dau vao la subject, goal, level va ngu canh learner. Dau ra la mot learning path gom chapters, lessons, concept graph, prerequisite metadata, recommended resources/chunks va trang thai tien do ban dau.

Chuc nang sinh cau hoi nhan dau vao la lesson id, yeu cau quiz va metadata adaptive neu co. Dau ra la bo cau hoi bam theo recommended chunks cua lesson, co source tracking, concept coverage, difficulty/Bloom mix, fallback status va thong tin debug.

Hai chuc nang nay lien ket truc tiep:

```text
Generate learning path
  -> tao subject/chapter/lesson
  -> chon resource seed va recommended chunks
  -> luu learning_path + lesson metadata
  -> lesson question generation doc recommended chunks
  -> tao/lap lai quiz
  -> lesson progress cap nhat KT/adaptive/feedback
```

## 2. Sinh lo trinh hoc tap

### 2.1 API entrypoint

Endpoint chinh:

- `POST /api/learning-paths/generate`
- Request model: `LearningPathGenerateRequest`
- Response model: `GeneratedLearningPathResponse`

Request gom:

- `subject_id`: bat buoc.
- `goal`: tuy chon, 3-500 ky tu.
- `level`: tuy chon, enum `beginner`, `intermediate`, `advanced`.

Router lay `current_user` tu JWT, sau do:

1. Lay `user_id`.
2. Lay personalization context tu `learner_profile_service.personalization_context`.
3. Goi `learning_path_service.generate_learning_path`.
4. Bootstrap knowledge tracing bang `knowledge_tracing_service.bootstrap_from_generated_path`.
5. Ghi event `learning_path_generated`.
6. Tra response gom `path_id`, `chapters`, `concept_graph`, `concept_mastery`, `mastery_threshold`, `curriculum_source`, `llm_status`.

### 2.2 Service chinh

Service runtime la:

- `backend/app/services/unified_learning_path_service.py`: shim backward-compatible.
- `backend/app/services/learning_path/generator.py`: `UnifiedLearningPathService`.

`UnifiedLearningPathService` ke thua `HybridLearningPathService`, nen van dung lai cac helper cu nhu validate input, tao subject, build keywords, select resources va recommend chunks.

Module phu:

- `learning_path/personalization.py`: doc profile, latest path, completion history, learner model, priority scoring.
- `learning_path/chapter_lesson_builder.py`: tao outline/chapter bang LLM va build metadata/resource payload.
- `learning_path/concept_graph_builder.py`: stable concept id.
- `learning_path/persistence.py`: serialize/normalize path response.
- `learning_path_prompt_builder.py`: prompt, fallback curriculum, subject catalog, JSON extraction/normalization.

### 2.3 Pipeline generate_learning_path

Ham chinh: `UnifiedLearningPathService.generate_learning_path`.

Trinh tu hien tai:

1. `analyze_profile`
   - Lay learner profile theo `user_id`.
   - Tim latest path gan nhat.
   - Resolve `subject_id`, `goal`, `level`.
   - Lay learner snapshot tu `learner_state_service.compute_snapshot` neu co user id.
   - Tinh `current_mastery`, `weak_concepts`, diagnostic baseline, time budget.
   - Tao `learner_model_v1` gom mastery, weak concepts, pace, engagement, friction, risk, quiz accuracy, completion rate.
   - Tao `planner_input` lam dau vao cho planner.

2. Validate input
   - Goi `_validate_inputs` tu base service.
   - Resolve subject label tu `get_subject_label`.

3. Tao curriculum
   - Goi `_generate_curriculum`.
   - Tao fallback curriculum truoc bang `build_fallback_curriculum`.
   - Neu LLM khong available hoac dang cooldown, dung fallback.
   - Neu LLM available:
     - Mode `legacy_strict`: tao curriculum mot lan bang strict prompt.
     - Mode adaptive: tao dynamic plan theo outline/chapter.
     - Neu dynamic/strict khong dat, thu enrichment tren fallback.
     - Neu van fail, quay ve fallback.

4. Enrich concept graph
   - Goi `concept_graph_service.enrich_curriculum`.
   - Bo sung `target_concepts`, `prerequisite_concepts`, concept graph va metadata lien quan.

5. Prioritize curriculum
   - Goi `_prioritize_curriculum`.
   - Scoring lesson dua tren weak overlap, prerequisite gap, novelty, difficulty fit, time budget, friction, pace va diagnostic baseline.
   - Sap xep lesson de uu tien gap quan trong nhung van ton trong prerequisite readiness.

6. Persist subject/chapter/lesson
   - Tao `path_id` bang `uuid.uuid4().hex`.
   - Dam bao subject ton tai bang `_ensure_subject`.
   - Tao chapter document cho moi chapter.
   - Tao lesson document cho moi lesson, gom:
     - `title`, `summary`, `order`, `topic`, `level`.
     - `learning_objectives`, `keywords`.
     - `resource_ids` seed.
     - `metadata.learning_path_id`, `goal`, `curriculum_source`.
     - `metadata.target_concepts`, `prerequisite_concepts`, `difficulty`, `lesson_kind`.
     - `unlock_strategy = concept_mastery`.
     - `prerequisite_mastery_threshold = 0.7`.
     - `adaptation_metadata`.

7. Recommend/freeze chunks neu cau hinh cho phep
   - Neu `precompute_recommendations_on_generate` bat, goi `_recommend_chunks_for_lesson`.
   - Luu `recommended_chunk_ids`, `recommended_resource_ids` vao lesson.
   - Build `recommended_resources` de tra ve frontend.

8. Persist learning path
   - Tao document trong `learning_paths`.
   - Luu `lesson_progress` mac dinh `not_started`.
   - Luu `lesson_confidence_log` mac dinh confidence 0.
   - Luu `concept_graph`, `concept_mastery`, `llm_status`, `curriculum_source`.
   - Luu metadata pipeline: `unified_learning_path_v2_concept_graph`, planner input, concept graph, lesson concept map, profile analysis.

9. Tra ket qua
   - Response gom chapters/lessons da tao, concept graph, threshold mastery, source va message.

### 2.4 Data dau vao

Dau vao truc tiep:

- `subject_id`
- `goal`
- `level`
- `user_id` tu JWT

Dau vao gian tiep:

- Learner profile: goal, level, time budget, pace, preferred resource type, target role/outcome, diagnostic summary/scores.
- Learner state snapshot: mastery by concept, focus concepts, active days, learning velocity, engagement, fatigue/frustration, fail streak, retry count.
- Existing/latest path va completion history.
- Resource/chunk store de seed recommendations.
- Gemini/curriculum LLM neu available.

### 2.5 Data dau ra va collection bi anh huong

Collection ghi/chinh sua:

- `subjects`: subject doc neu chua co.
- `chapters`: chapter doc moi.
- `lessons`: lesson doc moi, co metadata path/concept/resource.
- `lesson_recommended_chunks`: neu precompute recommendation.
- `learning_paths`: path tong hop cua user.
- `concept_mastery_states`: sau router, knowledge tracing bootstrap co the tao state ban dau.
- `event_logs`/learning event collections: ghi event generation.

Response frontend nhan:

- `path_id`
- `subject_id`
- `goal`
- `level`
- `generated_at`
- `chapters[]`
- `concept_graph[]`
- `concept_mastery`
- `mastery_threshold`
- `curriculum_source`
- `llm_status`
- `message`

### 2.6 Fallback va failure mode

Fallback quan trong:

- Khong co LLM key, provider khong available hoac cooldown: dung fallback curriculum.
- LLM tra JSON loi/yeu: thu repair/enrichment, neu fail dung fallback.
- Subject khong resolve duoc tu input/profile/latest path: fallback ve `python`.
- Khong co learner snapshot: dung snapshot rong voi default mastery/progress.
- Khong co resource phu hop: lesson van duoc tao, nhung recommended resources/chunks co the rong.

Rui ro van hanh:

- `curriculum_source` trong generator chi gan `"ai"` khi source bang `"ai"`; source `"ai_legacy_strict"` co the bi response/persist map thanh `"fallback"` trong code hien tai. Can xem lai neu muon phan biet strict AI voi fallback.
- Path generation co nhieu write vao Mongo; neu loi giua chung, co nguy co tao mot phan chapter/lesson nhung path chua duoc luu.
- Chat luong recommendation phu thuoc resource_chunks va embedding.
- Neu worktree/env sai, backend co the fail startup truoc khi den workflow nay do `SECRET_KEY` hoac Mongo URI.

## 3. Sinh cau hoi theo lesson

### 3.1 API entrypoint

Endpoint chinh:

- `POST /api/lessons/{lesson_id}/generate-questions`
- Request model: `LessonQuestionGenerationRequest`
- Response model: `LessonQuestionGenerationResponse`

Endpoint doc cau hoi:

- `GET /api/lessons/{lesson_id}/questions`
- Query optional: `question_set_kind`, vi du `standard` hoac `adaptive`.

Endpoint debug admin:

- `POST /api/lessons/{lesson_id}/question-generation-debug`

Endpoint adaptive quiz:

- `POST /api/lessons/{lesson_id}/adaptive-quiz/next`
- Goi adaptive service de build quiz request, sau do cung dung question generation service.

### 3.2 Request sinh cau hoi

`LessonQuestionGenerationRequest` gom:

- `target_count`: tuy chon, 1-20.
- `question_types`: mac dinh `multiple_choice`.
- `difficulty`: mac dinh `beginner`.
- `bloom_levels`: mac dinh `remember`, `understand`.
- `allow_llm`: mac dinh `true`.
- `mastery`: tuy chon 0-1.
- `success_rate`: tuy chon 0-1.
- `overwrite`: mac dinh `false`.
- `metadata`: gom adaptive flags, `path_id`, `target_chunk_ids`, `target_concepts`, `required_concepts`, `current_focus_concepts`, retry strategy, generation strategy.

### 3.3 Service chinh

Service runtime la:

- `backend/app/services/question_generation_service.py`: shim backward-compatible.
- `backend/app/services/question_generation/orchestrator.py`: `LessonScopedQuestionGenerationService`.

Module phu:

- `scope_loader.py`: nap recommendation/chunks lam generation scope.
- `template_fill.py`: tao cau hoi template.
- `llm_fill.py`: lay them cau hoi tu LLM khi thieu.
- `fallback_fill.py`: tao cau hoi cuc bo tu excerpt/chunk.
- `target_concepts.py`: map/validate concept target.
- `dedup.py`: signature va excluded signatures.
- `postprocess.py`: clean prompt/statement/excerpt.
- `lesson_assessment_sizing_service.py`: phan loai lesson size, target count, difficulty/Bloom distribution, concept coverage.
- `question_validation_service.py`, `question_validator.py`, `question_cross_verification_service.py`: validate va cross-check cau hoi.

### 3.4 Pipeline generate_questions_for_lesson

Ham public: `generate_questions_for_lesson`.

Service co in-flight lock theo request key. Neu hai request giong nhau chay dong thoi, request sau se doi ket qua cua request dau thay vi sinh trung.

Trinh tu chinh trong `_generate_questions_for_lesson_impl`:

1. Normalize request
   - Normalize `question_types`.
   - Resolve `question_set_kind`: standard/adaptive dua vao metadata.
   - Resolve difficulty adaptive dua tren `difficulty`, `mastery`, `success_rate`, metadata.

2. Lay lesson context
   - Goi `lesson_structure_service.get_lesson_context`.
   - Context gom lesson, chapter, subject.

3. Dam bao recommendation/chunk scope
   - Goi `_ensure_generation_recommendation`.
   - Neu metadata co target concepts nhung recommendation khong cover, refresh recommendation voi trigger `target_concept_refresh`.
   - Nap `chunk_ids` va chunk documents qua `_load_generation_scope`.
   - Neu scope loi, refresh voi trigger `question_generation_scope_recovery`.

4. Kiem tra existing questions
   - Doc `lesson_questions` theo lesson va `question_set_kind`.
   - Neu `overwrite = false` va da co cau hoi, tra ve existing set, khong ghi de.

5. Lap assessment plan
   - Tinh lesson size bang chunk count, token length, concept count, estimated learning time.
   - Lesson size -> target count auto:
     - small: 6
     - medium: 10
     - large: 12
   - Tinh difficulty distribution theo mastery.
   - Tinh Bloom distribution, dam bao co `apply`; medium/large co them `analyze`.
   - Validate concept coverage requirement mac dinh khoang 80%.

6. Detect degraded mode
   - Lay debug status cua LLM.
   - Neu LLM cooldown/quota/empty/invalid/client unavailable, vao degraded local mode.
   - Khi degraded, recalculate target count theo available chunks/concepts.
   - Sau do tat `allow_llm`.

7. Mo rong chunks truoc khi generate neu can
   - Neu pregen expansion bat, target count du lon, chunk count qua thap va khong degraded, refresh recommendation voi max chunks lon hon.

8. Sinh candidates
   - Neu `allow_llm = true`: goi `_run_generation`, build payload gom lesson context, chunk payload, resource metadata, recommendation score, instruction role, covered concepts, questionability score.
   - Neu `allow_llm = false`: chay template generator truoc, sau do local fallback candidates.
   - Neu LLM tra insufficient/invalid: refresh recommendation neu can, sau do fallback local.
   - Neu LLM sinh it cau hon target va LLM available: co the collect additional LLM questions truoc khi template fill.
   - Merge/deduplicate cac group cau hoi.

9. Finalize candidates
   - Round-robin theo chunk order de tranh tap trung vao mot chunk.
   - Loc question type khong hop le.
   - Dedup theo signature.
   - Enrich metadata: chunk/resource/page, quality score, generation metadata.
   - Bo sung fallback/reinforcement questions neu thieu.
   - Semantic dedup theo threshold.
   - Cross verification theo target concepts va Bloom levels.
   - Validate concept coverage, tao cau hoi bo sung cho missing concepts neu can.
   - Chon bo cau hoi da dang theo target count, plan difficulty/Bloom va concept coverage.
   - Loai cau hoi local low quality; co salvage/degraded fill khi can.

10. Persist
   - Neu `overwrite = true` hoac da co question set, xoa question semantic memory va xoa question set hien tai theo lesson/kind.
   - Insert vao `lesson_questions`.
   - Persist semantic memory vao `question_semantic_memory`.
   - Log outcome voi status, generation mode, chunk count, covered chunk count, runtime details.

11. Response
   - Tra `status`, `generated_count`, `saved_count`, `question_ids`, `chunks_used`.
   - Tra `sources`: so cau hoi tu template/llm/local_fallback/existing_reuse.
   - Tra `lesson_size`, `target_count`, `effective_target_count`, `degraded_mode`, `llm_status`.
   - Tra `difficulty_mix`, `bloom_mix`, `concept_coverage_rate`, valid/rejected target concepts, verification diagnostics, next action va message.

### 3.5 Adaptive quiz

Endpoint `POST /api/lessons/{lesson_id}/adaptive-quiz/next` la wrapper tren question generation:

1. Goi `adaptive_learning_service.build_next_quiz_request`.
2. Service adaptive tra target count, recommended difficulty, Bloom levels, target chunks/concepts, retry strategy, policy bucket va explanation.
3. Router build metadata:
   - `adaptive_quiz = true`
   - `generation_reason = adaptive_quiz_next`
   - `path_id`
   - `target_chunk_ids`
   - `target_concepts`
   - `retry_strategy`
   - `adaptive_explanation`
   - `generation_strategy`
4. Goi `lesson_question_generation_service.generate_questions_for_lesson` voi `overwrite = true`.
5. Response gom `next_action`, `generation_request`, va `generated`.

Ket qua adaptive question set co the duoc luu rieng voi `question_set_kind = adaptive`, tuy thuoc metadata/generation reason.

### 3.6 Data dau vao

Dau vao truc tiep:

- `lesson_id`
- `target_count`, `question_types`, `difficulty`, `bloom_levels`
- `allow_llm`, `mastery`, `success_rate`, `overwrite`
- `metadata.target_concepts`, `target_chunk_ids`, `required_concepts`, adaptive flags

Dau vao gian tiep:

- `lessons`, `chapters`, `subjects`
- `lesson_recommended_chunks`
- `resource_chunks`
- `resources`
- Existing `lesson_questions`
- `question_semantic_memory`
- LLM status/provider/model
- Embedding service cho semantic dedup va recommendation quality

### 3.7 Data dau ra va collection bi anh huong

Collection doc:

- `lessons`
- `chapters`
- `subjects`
- `lesson_recommended_chunks`
- `resource_chunks`
- `resources`
- `lesson_questions`
- `question_semantic_memory`

Collection ghi:

- `lesson_questions`: bo cau hoi moi.
- `question_semantic_memory`: vector/text memory de dedup ve sau.
- `lesson_recommended_chunks`: co the refresh recommendation.
- Event/log collection: generation outcome/debug log tuy service.

Moi question document gom:

- `subject_id`, `chapter_id`, `lesson_id`
- `chunk_ids`, `resource_ids`
- `question_type`, `question`, `correct_answer`, `distractors`, `explanation`
- `difficulty`, `bloom_level`, `concept_id`
- `retry_strategy`
- `is_ai_generated`, `llm_provider`, `llm_model`
- `metadata`: generation source, tracked Bloom/difficulty/confidence, recommendation id, resource/page/chunk indexes, concept coverage va runtime flags.

## 4. Cau hinh runtime quan trong

Sinh lo trinh:

- `GEMINI_API_KEY` hoac `GEMINI_API_KEYS`: can cho Gemini.
- `GEMINI_MODEL`: model mac dinh cho curriculum/question neu khong override.
- `UNIFIED_LEARNING_PATH_CURRICULUM_MODE`: mac dinh `legacy_strict`; gia tri khac se vao adaptive/dynamic mode.
- `LEARNING_PATH_GOLDEN_EXAMPLES_ENABLED`: bat/tat golden examples trong prompt/fallback builder.

Sinh cau hoi:

- `LESSON_QUESTION_LLM_MODEL`: model rieng cho cau hoi; fallback ve `GEMINI_MODEL`.
- `LESSON_QUESTION_LOW_COUNT_RETRY_ENABLED`: retry khi LLM sinh it cau.
- `LESSON_QUESTION_LOW_COUNT_RETRY_DELAY_SECONDS`: delay truoc retry.
- `LESSON_QUESTION_PREGEN_CHUNK_EXPANSION_ENABLED`: cho phep refresh/morong chunks truoc generation.
- `LESSON_QUESTION_PREGEN_MIN_RECOMMENDED_CHUNKS`: nguong chunks toi thieu mong muon.
- `LESSON_QUESTION_REFRESH_MAX_CHUNKS`: so chunks toi da khi refresh.
- `LESSON_QUESTION_LOW_COUNT_FORCE_FILL_ENABLED`: force fill bang local candidates khi thieu.
- `LESSON_QUESTION_DIVERSITY_MAX_PER_CHUNK`: gioi han cau hoi moi chunk.
- `LESSON_QUESTION_SEMANTIC_DEDUP_ENABLED`: bat/tat semantic dedup.
- `LESSON_QUESTION_SEMANTIC_DEDUP_THRESHOLD`: threshold semantic duplicate, mac dinh 0.92.
- `LESSON_QUESTION_SEMANTIC_DEDUP_LOOKBACK`: so memory gan nhat de so sanh.
- `LESSON_QUESTION_PREFER_LLM_FILL_BEFORE_TEMPLATE_ENABLED`: uu tien LLM fill truoc template fill khi thieu.
- `LESSON_QUESTION_LLM_FILL_MAX_ATTEMPTS`: so lan thu them cau hoi bang LLM.

Embedding/retrieval:

- `EMBEDDING_PROVIDER`
- `GEMINI_EMBEDDING_MODEL`
- Sentence transformer settings neu dung local embedding.

## 5. Cach van hanh thu cong

### 5.1 Dieu kien truoc khi test

Can co:

- Backend da chay.
- MongoDB connected.
- `SECRET_KEY` hop le.
- It nhat mot user dang nhap.
- Subject/resource/chunk data du de recommendation co noi dung.
- Gemini key neu muon test AI mode; neu khong, test fallback/local mode.

Kiem tra health:

```bash
curl http://localhost:8000/api/health
curl http://localhost:8000/api/ready
curl http://localhost:8000/api/health/ai
```

### 5.2 Test sinh lo trinh

Flow API:

```http
POST /api/learning-paths/generate
Authorization: Bearer <token>
Content-Type: application/json

{
  "subject_id": "python",
  "goal": "Hoc Python de xay dung backend API",
  "level": "beginner"
}
```

Sau khi thanh cong, kiem tra:

- Response co `path_id`.
- `chapters` co lesson id.
- `curriculum_source` la `ai` hoac `fallback`.
- `llm_status` neu LLM da duoc cau hinh.
- Collection `learning_paths` co document moi.
- Collection `lessons` co lesson metadata `learning_path_id`.
- Neu precompute recommendations bat, lesson co `recommended_chunk_ids`.

### 5.3 Test sinh cau hoi standard

Flow API:

```http
POST /api/lessons/<lesson_id>/generate-questions
Authorization: Bearer <token>
Content-Type: application/json

{
  "target_count": 6,
  "question_types": ["multiple_choice"],
  "difficulty": "beginner",
  "bloom_levels": ["remember", "understand", "apply"],
  "allow_llm": true,
  "overwrite": true,
  "metadata": {
    "path_id": "<path_id>",
    "target_concepts": ["variables", "data types"]
  }
}
```

Kiem tra response:

- `status`: `ok`, partial/degraded status hoac `insufficient_context`.
- `saved_count` > 0.
- `sources.llm/template/local_fallback`.
- `chunks_used` khong rong.
- `concept_coverage_rate`.
- `degraded_mode` va `llm_status`.

Doc lai:

```http
GET /api/lessons/<lesson_id>/questions
Authorization: Bearer <token>
```

### 5.4 Test adaptive quiz

```http
POST /api/lessons/<lesson_id>/adaptive-quiz/next
Authorization: Bearer <token>
Content-Type: application/json

{
  "path_id": "<path_id>",
  "target_count": 4
}
```

Kiem tra:

- `next_action.recommended_difficulty`
- `next_action.recommended_bloom_levels`
- `next_action.target_chunk_ids`
- `generation_request.retry_strategy`
- `generated.saved_count`
- `generated.question_ids`

## 6. Checklist debug su co

Neu generate learning path fail:

1. Kiem tra backend startup co pass env validation khong.
2. Kiem tra MongoDB connection.
3. Kiem tra request co `subject_id` hop le va `goal` du dai.
4. Xem `llm_status`: provider unavailable/cooldown/quota co the khien dung fallback.
5. Kiem tra `learning_paths`, `chapters`, `lessons` co partial write khong neu request loi giua chung.
6. Kiem tra resource/chunk data neu lessons tao ra nhung recommended resources rong.

Neu generate questions fail hoac `insufficient_context`:

1. Goi debug endpoint admin `/api/lessons/{lesson_id}/question-generation-debug`.
2. Kiem tra lesson co context day du: lesson, chapter, subject.
3. Kiem tra `lesson_recommended_chunks` co record va chunk ids load duoc.
4. Kiem tra `resource_chunks.content` co noi dung du dai, khong phai index/glossary/noise.
5. Kiem tra target concepts co match chunk/recommendation khong.
6. Kiem tra `llm_status`: cooldown/quota/client unavailable se vao degraded local mode.
7. Neu existing questions duoc reuse ngoai y muon, gui `overwrite = true`.
8. Neu concept coverage thap, thu refresh recommendation hoac import/curate resource tot hon.
9. Neu local fallback tao cau hoi kem, can bo sung resource chunks chat luong hon thay vi chi tang target count.

## 7. Diem can cai thien

- Them transaction/cleanup strategy cho path generation de tranh partial chapters/lessons khi loi giua pipeline.
- Chuan hoa mapping `curriculum_source` de phan biet ro `ai`, `ai_legacy_strict`, `fallback`.
- Them integration tests cho:
  - Generate path voi LLM unavailable.
  - Generate path voi fallback curriculum.
  - Generate question voi existing reuse.
  - Generate question voi overwrite.
  - Generate question degraded local mode.
  - Adaptive quiz request tao metadata dung.
- Them seed data/test fixtures cho resource_chunks de test end-to-end deterministic.
- Expose mot endpoint admin read-only cho lesson generation readiness, de frontend biet truoc lesson co du chunks/concepts de tao quiz hay khong.

## 8. Tom tat van hanh

De chuc nang sinh lo trinh va sinh cau hoi chay tot, can dam bao ba lop du lieu:

1. Learner data: profile, diagnostic, learner state.
2. Content data: subject, resource, resource chunks, embeddings.
3. Runtime AI/retrieval: Gemini key/model, embedding provider, recommendation health.

Sinh lo trinh co the chay voi fallback khi LLM khong san sang, nhung chat luong ca nhan hoa va ten lesson se phu thuoc fallback templates. Sinh cau hoi phu thuoc manh vao recommended chunks; neu chunks thieu/noise, service se refresh, fallback local, degraded target count hoac tra `insufficient_context`.
