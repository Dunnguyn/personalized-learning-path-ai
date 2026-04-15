import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import AdaptiveDemoPanel from '../components/adaptive/AdaptiveDemoPanel';
import DashboardLayout from '../components/layout/DashboardLayout';
import PageHero from '../components/ui/PageHero';
import { useAuth } from '../contexts/AuthContext';
import { analyticsService } from '../services/analyticsService';
import { learningPathService } from '../services/learningPathService';
import { resourceService } from '../services/resourceService';
import type { AdminDashboardMetrics, AdminResearchDashboardMetrics } from '../types/analytics';
import type { LearningPath } from '../types/learningPath';
import type { IngestionHealthSnapshot, ResourceCurationSnapshot } from '../types/resource';

type ConceptNode = {
  concept_id: string;
  concept_name: string;
  prerequisites: string[];
  subject_id?: string;
  topic?: string;
};

type ConceptGraph = {
  concepts: ConceptNode[];
  total_concepts: number;
  total_edges: number;
};

type ResourceDraft = {
  curatedConceptIds: string;
  qualityLabel: string;
  adminNotes: string;
  hiddenFromRecommendation: boolean;
};

type RecentJobSummary = {
  resourceId: string;
  resourceType: string;
  status: string;
  chunksCount: number;
  processingTime: number;
  error: string;
  updatedAt: string;
};

const emptySnapshot: AdminDashboardMetrics = {
  dau: 0,
  wau: 0,
  learning_path_generation_success_rate: 0,
  average_study_hours_per_user: 0,
  total_study_hours: 0,
  user_count: 0,
  p50_latency_ms: 0,
  p95_latency_ms: 0,
  p99_latency_ms: 0,
  api_error_rate: 0,
  has_user_data: false,
  no_data_message: 'Chưa có dữ liệu người học.',
  updated_at: null,
};

const emptyResearch: AdminResearchDashboardMetrics = {
  window_days: 30,
  recommendation: {
    window_days: 30,
    shown_count: 0,
    clicked_count: 0,
    ctr: 0,
    completion_after_recommendation: { completed_count: 0, rate: 0 },
    confidence_gain_after_recommendation: { avg_delta: 0, sample_size: 0 },
    top_resources: [],
  },
  learning_path: {
    window_days: 30,
    path_count: 0,
    completed_path_count: 0,
    completion_rate: 0,
    average_path_completion: 0,
    lesson_drop_off: [],
    refinement_count: 0,
    bridge_insertions: 0,
    intervention_type_counts: {},
    lowest_completion_paths: [],
  },
  ai_tutor: {
    window_days: 30,
    total_asks: 0,
    retrieval_hit_ratio: 0,
    average_answer_confidence: 0,
    follow_up_ask_rate: 0,
    follow_up_users: 0,
    average_retrieval_sources: 0,
    average_latency_ms: 0,
    llm_call_count: 0,
  },
  analytics_schema_version: 'analytics.research.v1',
};

const emptyCuration: ResourceCurationSnapshot = {
  items: [],
  status_counts: {},
  duplicate_groups: [],
  low_quality_count: 0,
  total_items: 0,
};

const emptyHealth: IngestionHealthSnapshot = {
  resource_status_counts: {},
  chunk_totals: { total: 0, with_embeddings: 0, without_embeddings: 0, by_backend: {} },
  embedding: {},
  vector_store: { available: false },
  recent_jobs: [],
};

const formatPercent = (value: number) => `${(Number(value || 0) * 100).toFixed(1)}%`;
const formatSignedPercent = (value: number) => {
  const numeric = Number(value || 0) * 100;
  const prefix = numeric > 0 ? '+' : '';
  return `${prefix}${numeric.toFixed(1)}%`;
};
const formatNumber = (value: number) => new Intl.NumberFormat('vi-VN').format(Number(value || 0));
const formatDateTime = (value: string | null | undefined) => {
  if (!value) return 'Chưa có mốc cập nhật';
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return String(value);
  return parsed.toLocaleString('vi-VN');
};
const parseConceptIds = (value: string) => value.split(',').map((item) => item.trim()).filter(Boolean);
const asRecord = (value: unknown) => (value && typeof value === 'object' ? (value as Record<string, unknown>) : {});
const asString = (value: unknown, fallback = '') => (value == null ? fallback : String(value));
const asNumber = (value: unknown, fallback = 0) => {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : fallback;
};

const getProblemFlagLabel = (flag: string) => {
  switch (flag) {
    case 'low_quality':
      return 'Chất lượng thấp';
    case 'duplicate_candidate':
      return 'Nghi trùng lặp';
    case 'ingestion_failed':
      return 'Ingestion lỗi';
    case 'missing_chunks':
      return 'Thiếu chunk';
    default:
      return flag;
  }
};

const getStatusChipClassName = (status: string) => {
  const normalized = status.trim().toLowerCase();
  if (['ready', 'completed', 'success'].includes(normalized)) return 'border-emerald-200 bg-emerald-50 text-emerald-700';
  if (['processing', 'running', 'queued'].includes(normalized)) return 'border-amber-200 bg-amber-50 text-amber-700';
  if (['failed', 'error'].includes(normalized)) return 'border-rose-200 bg-rose-50 text-rose-700';
  return 'border-[#f1d7df] bg-[#fff5f8] text-[#8c3451]';
};

const buildDrafts = (snapshot: ResourceCurationSnapshot): Record<string, ResourceDraft> =>
  Object.fromEntries(
    snapshot.items.map((item) => [
      item.resource_id,
      {
        curatedConceptIds: item.curated_concept_ids.join(', '),
        qualityLabel: item.quality_label || '',
        adminNotes: item.admin_notes || '',
        hiddenFromRecommendation: item.hidden_from_recommendation,
      },
    ]),
  );

const asConceptNode = (value: unknown): ConceptNode => {
  const record = asRecord(value);
  return {
    concept_id: asString(record.concept_id),
    concept_name: asString(record.concept_name || record.name || record.label || record.concept_id),
    prerequisites: Array.isArray(record.prerequisites) ? record.prerequisites.map((item) => String(item)) : [],
    subject_id: typeof record.subject_id === 'string' ? record.subject_id : undefined,
    topic: typeof record.topic === 'string' ? record.topic : undefined,
  };
};

const normalizeRecentJob = (value: Record<string, unknown>): RecentJobSummary => ({
  resourceId: asString(value.resource_id || value._id || 'N/A'),
  resourceType: asString(value.resource_type || 'unknown'),
  status: asString(value.status || 'unknown'),
  chunksCount: asNumber(value.chunks_count),
  processingTime: asNumber(value.processing_time),
  error: asString(value.error || ''),
  updatedAt: asString(value.updated_at || value.created_at || ''),
});

export default function AdminDashboard() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loadWarnings, setLoadWarnings] = useState<string[]>([]);
  const [snapshot, setSnapshot] = useState(emptySnapshot);
  const [research, setResearch] = useState(emptyResearch);
  const [curation, setCuration] = useState(emptyCuration);
  const [health, setHealth] = useState(emptyHealth);
  const [graph, setGraph] = useState<ConceptGraph>({ concepts: [], total_concepts: 0, total_edges: 0 });
  const [demoPaths, setDemoPaths] = useState<LearningPath[]>([]);
  const [demoError, setDemoError] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, ResourceDraft>>({});
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [savingResourceId, setSavingResourceId] = useState<string | null>(null);
  const [selectedConceptId, setSelectedConceptId] = useState('');
  const [prerequisiteDraft, setPrerequisiteDraft] = useState('');
  const [savingConcept, setSavingConcept] = useState(false);

  const loadData = useCallback(async (mode: 'initial' | 'refresh' = 'initial') => {
    try {
      if (mode === 'initial') setLoading(true);
      else setRefreshing(true);
      setError(null);
      setLoadWarnings([]);

      const results = await Promise.allSettled([
        analyticsService.getAdminDashboard(),
        analyticsService.getAdminAverageStudyHours(),
        analyticsService.getAdminResearchDashboard(30),
        resourceService.getAdminCurationDashboard({ limit: 6 }),
        resourceService.getIngestionHealth(),
        learningPathService.getAdminPrerequisiteGraph(),
      ]);

      const [dashboardResult, studyHoursResult, researchResult, curationResult, healthResult, graphResult] = results;
      const warnings: string[] = [];

      if (dashboardResult.status === 'fulfilled') {
        const studyHours = studyHoursResult.status === 'fulfilled' ? studyHoursResult.value : emptySnapshot;
        if (studyHoursResult.status !== 'fulfilled') warnings.push('giờ học trung bình');
        setSnapshot({ ...dashboardResult.value, ...studyHours });
      } else if (studyHoursResult.status === 'fulfilled') {
        warnings.push('tổng quan hệ thống');
        setSnapshot((current) => ({ ...current, ...studyHoursResult.value }));
      } else {
        warnings.push('tổng quan hệ thống');
      }

      if (researchResult.status === 'fulfilled') setResearch(researchResult.value);
      else warnings.push('research metrics');

      if (curationResult.status === 'fulfilled') {
        setCuration(curationResult.value);
        setDrafts(buildDrafts(curationResult.value));
      } else {
        warnings.push('resource curation');
      }

      if (healthResult.status === 'fulfilled') setHealth(healthResult.value);
      else warnings.push('ingestion health');

      if (graphResult.status === 'fulfilled') {
        const graphResponse = graphResult.value as Record<string, unknown>;
        const concepts = Array.isArray(graphResponse.concepts) ? graphResponse.concepts.map(asConceptNode) : [];
        setGraph({
          concepts,
          total_concepts: Number(graphResponse.total_concepts || concepts.length),
          total_edges: Number(graphResponse.total_edges || 0),
        });
      } else {
        warnings.push('prerequisite graph');
      }

      setLoadWarnings(warnings);
      if (warnings.length === results.length) {
        setError('Không thể tải dữ liệu quản trị. Vui lòng thử lại sau.');
      } else if (warnings.length > 0) {
        setError(`Một số khối dữ liệu chưa tải được: ${warnings.join(', ')}.`);
      }
    } catch (loadError) {
      console.error('Failed to load admin dashboard:', loadError);
      setError(loadError instanceof Error ? loadError.message : 'Không thể tải bảng điều khiển quản trị.');
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  const loadDemoPaths = useCallback(async () => {
    try {
      setDemoError(null);
      const history = await learningPathService.getLearningPathHistory();
      const items = await Promise.all(history.slice(0, 10).map((path) => learningPathService.getLearningPathById(path.path_id)));
      setDemoPaths(items);
    } catch (loadError) {
      setDemoError(loadError instanceof Error ? loadError.message : 'Không thể tải các luồng adaptive demo.');
    }
  }, []);

  useEffect(() => {
    if (!user) {
      navigate('/login');
      return;
    }
    if (user.role !== 'admin') {
      navigate('/dashboard');
      return;
    }
    void loadData('initial');
    void loadDemoPaths();
  }, [loadData, loadDemoPaths, navigate, user]);

  useEffect(() => {
    if (!selectedConceptId && graph.concepts.length > 0) {
      setSelectedConceptId(graph.concepts[0].concept_id);
      setPrerequisiteDraft(graph.concepts[0].prerequisites.join(', '));
    }
  }, [graph.concepts, selectedConceptId]);

  const selectedConcept = useMemo(
    () => graph.concepts.find((item) => item.concept_id === selectedConceptId) || null,
    [graph.concepts, selectedConceptId],
  );

  const resourceStatusEntries = useMemo(
    () => Object.entries(health.resource_status_counts || {}).sort((left, right) => right[1] - left[1]),
    [health.resource_status_counts],
  );
  const recentJobs = useMemo(
    () => (health.recent_jobs || []).map((item) => normalizeRecentJob(asRecord(item))).slice(0, 5),
    [health.recent_jobs],
  );
  const curationSummary = useMemo(
    () => ({
      duplicateGroups: curation.duplicate_groups.length,
      lowQuality: curation.low_quality_count,
      hidden: curation.items.filter((item) => item.hidden_from_recommendation).length,
    }),
    [curation],
  );
  const operationalWarnings = useMemo(() => {
    const items: string[] = [];
    if (!health.vector_store.available) items.push('Vector store chưa sẵn sàng');
    if (Number(health.chunk_totals.without_embeddings || 0) > 0) {
      items.push(`${formatNumber(health.chunk_totals.without_embeddings)} chunk chưa có embedding`);
    }
    if (Number(snapshot.api_error_rate || 0) >= 0.03) items.push('Tỷ lệ lỗi API đang cao');
    if (loadWarnings.length > 0) items.push(`Thiếu dữ liệu ở ${loadWarnings.join(', ')}`);
    return items;
  }, [health.chunk_totals.without_embeddings, health.vector_store.available, loadWarnings, snapshot.api_error_rate]);
  const showSecondaryAdminSections = false;
  const learnerSignals = useMemo(() => {
    const totalUsers = Number(snapshot.user_count || 0);
    const dau = Number(snapshot.dau || 0);
    const wau = Number(snapshot.wau || 0);
    const avgStudyHours = Number(snapshot.average_study_hours_per_user || 0);
    const pathSuccessRate = Number(snapshot.learning_path_generation_success_rate || 0);
    const dailyActiveRate = totalUsers > 0 ? dau / totalUsers : 0;
    const weeklyActiveRate = totalUsers > 0 ? wau / totalUsers : 0;

    const weeklyMomentum =
      weeklyActiveRate >= 0.6
        ? { label: 'Đà quay lại tốt', detail: `${formatPercent(weeklyActiveRate)} người học quay lại trong tuần`, tone: 'text-emerald-700 bg-emerald-50 border-emerald-200' }
        : weeklyActiveRate >= 0.3
          ? { label: 'Đà quay lại trung bình', detail: `${formatPercent(weeklyActiveRate)} người học quay lại trong tuần`, tone: 'text-amber-700 bg-amber-50 border-amber-200' }
          : { label: 'Đà quay lại thấp', detail: `${formatPercent(weeklyActiveRate)} người học quay lại trong tuần`, tone: 'text-rose-700 bg-rose-50 border-rose-200' };

    const studyRhythm =
      avgStudyHours >= 1.5
        ? { label: 'Nhịp học ổn định', detail: `Trung bình ${avgStudyHours.toFixed(1)}h mỗi người`, tone: 'text-emerald-700 bg-emerald-50 border-emerald-200' }
        : avgStudyHours >= 0.75
          ? { label: 'Nhịp học cần theo dõi', detail: `Trung bình ${avgStudyHours.toFixed(1)}h mỗi người`, tone: 'text-amber-700 bg-amber-50 border-amber-200' }
          : { label: 'Nhịp học thấp', detail: `Trung bình ${avgStudyHours.toFixed(1)}h mỗi người`, tone: 'text-rose-700 bg-rose-50 border-rose-200' };

    const learnerExperience =
      pathSuccessRate >= 0.9
        ? { label: 'Trải nghiệm tạo path tốt', detail: `${formatPercent(pathSuccessRate)} yêu cầu tạo path thành công`, tone: 'text-emerald-700 bg-emerald-50 border-emerald-200' }
        : pathSuccessRate >= 0.7
          ? { label: 'Trải nghiệm tạo path chấp nhận được', detail: `${formatPercent(pathSuccessRate)} yêu cầu tạo path thành công`, tone: 'text-amber-700 bg-amber-50 border-amber-200' }
          : { label: 'Trải nghiệm tạo path cần chú ý', detail: `${formatPercent(pathSuccessRate)} yêu cầu tạo path thành công`, tone: 'text-rose-700 bg-rose-50 border-rose-200' };

    return { dailyActiveRate, weeklyMomentum, studyRhythm, learnerExperience };
  }, [snapshot.average_study_hours_per_user, snapshot.dau, snapshot.learning_path_generation_success_rate, snapshot.user_count, snapshot.wau]);
  const adminPriorities = useMemo(() => {
    const totalUsers = Number(snapshot.user_count || 0);
    const dau = Number(snapshot.dau || 0);
    const wau = Number(snapshot.wau || 0);
    const pathSuccessRate = Number(snapshot.learning_path_generation_success_rate || 0);
    const avgStudyHours = Number(snapshot.average_study_hours_per_user || 0);

    if (totalUsers === 0) {
      return [
        {
          title: 'Chưa có người học hoạt động',
          detail: 'Kiểm tra luồng onboarding hoặc tài khoản demo để có dữ liệu học tập đầu tiên.',
          tone: 'border-amber-200 bg-amber-50 text-amber-800',
        },
      ];
    }

    const items = [];

    if (dau / totalUsers < 0.4) {
      items.push({
        title: 'Kéo lại hoạt động trong ngày',
        detail: `${formatNumber(dau)}/${formatNumber(totalUsers)} người học quay lại hôm nay. Nên ưu tiên nhắc học hoặc resource ngắn.`,
        tone: 'border-amber-200 bg-amber-50 text-amber-800',
      });
    }

    if (wau / totalUsers < 0.6) {
      items.push({
        title: 'Theo dõi nhóm có nguy cơ rơi nhịp',
        detail: `${formatNumber(wau)}/${formatNumber(totalUsers)} người học còn hoạt động trong tuần. Cần theo dõi nhóm không quay lại.`,
        tone: 'border-rose-200 bg-rose-50 text-rose-800',
      });
    }

    if (avgStudyHours < 1) {
      items.push({
        title: 'Thời lượng học còn thấp',
        detail: `Trung bình mới đạt ${avgStudyHours.toFixed(1)}h mỗi người. Có thể cần chia bài nhỏ hơn hoặc tăng reminder.`,
        tone: 'border-amber-200 bg-amber-50 text-amber-800',
      });
    }

    if (pathSuccessRate < 0.9) {
      items.push({
        title: 'Kiểm tra trải nghiệm tạo learning path',
        detail: `${formatPercent(pathSuccessRate)} yêu cầu tạo path thành công. Cần rà lại các case fail để tránh chặn người học mới.`,
        tone: 'border-rose-200 bg-rose-50 text-rose-800',
      });
    }

    if (items.length === 0) {
      items.push({
        title: 'Nhịp học đang ổn',
        detail: 'Các chỉ số chính đang ở vùng an toàn. Nên tiếp tục theo dõi người học quay lại và giờ học trung bình.',
        tone: 'border-emerald-200 bg-emerald-50 text-emerald-800',
      });
    }

    return items.slice(0, 3);
  }, [snapshot.average_study_hours_per_user, snapshot.dau, snapshot.learning_path_generation_success_rate, snapshot.user_count, snapshot.wau]);
  const learnerOverviewNotes = useMemo(
    () => [
      `${formatNumber(snapshot.user_count)} người học đã được ghi nhận trong hệ thống`,
      `${formatNumber(snapshot.dau)} người học có hoạt động trong 24 giờ gần nhất`,
      `${formatNumber(snapshot.wau)} người học quay lại trong 7 ngày gần nhất`,
      `${Number(snapshot.total_study_hours || 0).toFixed(1)} giờ học đã được tích lũy`,
    ],
    [snapshot.dau, snapshot.total_study_hours, snapshot.user_count, snapshot.wau],
  );

  const saveResource = useCallback(async (resourceId: string) => {
    const draft = drafts[resourceId];
    if (!draft) return;
    try {
      setSavingResourceId(resourceId);
      const updated = await resourceService.updateResourceCuration(resourceId, {
        curated_concept_ids: parseConceptIds(draft.curatedConceptIds),
        quality_label: draft.qualityLabel,
        admin_notes: draft.adminNotes,
        hidden_from_recommendation: draft.hiddenFromRecommendation,
      });
      setCuration((current) => ({
        ...current,
        items: current.items.map((item) => (item.resource_id === resourceId ? updated : item)),
      }));
      setSaveMessage(`Đã lưu cấu hình cho tài nguyên ${updated.title || resourceId}.`);
    } catch (saveError) {
      setSaveMessage(saveError instanceof Error ? saveError.message : 'Không thể lưu cấu hình kiểm duyệt tài nguyên.');
    } finally {
      setSavingResourceId(null);
    }
  }, [drafts]);

  const saveConcept = useCallback(async () => {
    if (!selectedConceptId) return;
    try {
      setSavingConcept(true);
      const response = await learningPathService.updateConceptPrerequisites(selectedConceptId, parseConceptIds(prerequisiteDraft));
      const updated = asConceptNode((response as Record<string, unknown>).concept);
      setGraph((current) => ({
        ...current,
        concepts: current.concepts.map((item) => (item.concept_id === updated.concept_id ? updated : item)),
      }));
      setSaveMessage(`Đã cập nhật đồ thị tiên quyết cho ${updated.concept_name || selectedConceptId}.`);
    } catch (saveError) {
      setSaveMessage(saveError instanceof Error ? saveError.message : 'Không thể lưu đồ thị tiên quyết.');
    } finally {
      setSavingConcept(false);
    }
  }, [prerequisiteDraft, selectedConceptId]);

  if (loading) {
    return (
      <DashboardLayout>
        <div className="page-shell">
          <div className="white-panel p-8 text-center text-[#8c3451]">Đang tải bảng điều khiển quản trị...</div>
        </div>
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout>
      <div className="page-shell max-w-[1360px]">
        {error ? (
          <div className="white-panel mb-6 border border-amber-200 bg-[#fffaf2] px-5 py-4 text-amber-800">
            <p className="text-[12px] uppercase tracking-[0.16em] text-amber-700/80">Trạng thái tải dữ liệu</p>
            <p className="mt-2 text-[15px]">{error}</p>
          </div>
        ) : null}

        {saveMessage ? (
          <div className="white-panel mb-6 border border-[#f1d7df] bg-[#fff8fb] px-5 py-4 text-[#5f5954]">
            {saveMessage}
          </div>
        ) : null}

        <PageHero
          kicker="Quản lý người học"
          title="Nắm nhịp lớp học và tiến độ người học."
          className="!px-6 !py-5 md:!px-8 md:!py-6"
          titleClassName="max-w-[760px] text-[32px] font-medium leading-[1.06] tracking-[-0.05em] text-[#8c3451] md:text-[42px] xl:text-[48px]"
          description="Ưu tiên theo dõi người học đang quay lại, thời lượng học tích lũy và chất lượng trải nghiệm tạo learning path."
          descriptionClassName="max-w-[720px] text-[15px]"
          actionsClassName="w-full lg:w-[300px] xl:w-[320px] shrink-0"
          actions={
            <div className="white-panel flex h-full min-h-[180px] flex-col justify-between p-5">
              <div>
                <p className="text-[11px] uppercase tracking-[0.18em] text-[#8c3451]/55">Tình hình lớp học</p>
                <p className="mt-2 text-[28px] font-semibold text-[#17141a]">{formatNumber(snapshot.user_count)}</p>
                <p className="mt-1 text-[13px] text-[#5f5954]">Người học đã có dữ liệu trong hệ thống</p>
                <div className="mt-4 space-y-2.5">
                  <div className="flex items-center justify-between rounded-[16px] bg-[#fff7fa] px-4 py-2.5">
                    <span className="text-[12px] uppercase tracking-[0.14em] text-[#8c3451]/55">Hôm nay</span>
                    <span className="text-[16px] font-semibold text-[#17141a]">{formatNumber(snapshot.dau)} người học</span>
                  </div>
                  <div className="flex items-center justify-between rounded-[16px] bg-[#fff7fa] px-4 py-2.5">
                    <span className="text-[12px] uppercase tracking-[0.14em] text-[#8c3451]/55">7 ngày</span>
                    <span className="text-[16px] font-semibold text-[#17141a]">{formatNumber(snapshot.wau)} người quay lại</span>
                  </div>
                  <div className="flex items-center justify-between rounded-[16px] bg-[#fff7fa] px-4 py-2.5">
                    <span className="text-[12px] uppercase tracking-[0.14em] text-[#8c3451]/55">Nhịp học</span>
                    <span className="text-[16px] font-semibold text-[#17141a]">
                      {Number(snapshot.average_study_hours_per_user || 0).toFixed(1)}h / người
                    </span>
                  </div>
                </div>
              </div>
              <div>
                <p className="text-[12px] text-[#5f5954]">Cập nhật: {formatDateTime(snapshot.updated_at)}</p>
                <button type="button" onClick={() => void loadData('refresh')} disabled={refreshing} className="theme-button-secondary mt-4 w-full disabled:opacity-60">
                  {refreshing ? 'Đang làm mới...' : 'Làm mới dữ liệu'}
                </button>
              </div>
            </div>
          }
        />

        <section className="mt-6 grid gap-4 lg:grid-cols-2">
          <article className="white-panel p-5">
            <p className="text-[11px] uppercase tracking-[0.16em] text-[#8c3451]/55">Nhịp quay lại</p>
            <p className="mt-3 text-[22px] font-semibold tracking-[-0.04em] text-[#17141a]">
              {formatPercent(learnerSignals.dailyActiveRate)} hoạt động mỗi ngày
            </p>
            <p className="mt-2 text-[14px] leading-6 text-[#5f5954]">{learnerSignals.weeklyMomentum.detail}</p>
          </article>

          <article className="white-panel p-5">
            <p className="text-[11px] uppercase tracking-[0.16em] text-[#8c3451]/55">Thời lượng học</p>
            <p className="mt-3 text-[22px] font-semibold tracking-[-0.04em] text-[#17141a]">
              {Number(snapshot.average_study_hours_per_user || 0).toFixed(1)}h / người
            </p>
            <p className="mt-2 text-[14px] leading-6 text-[#5f5954]">{learnerSignals.studyRhythm.detail}</p>
          </article>
        </section>

        <section className="mt-6 grid gap-4 xl:grid-cols-[1.1fr,0.9fr]">
          <article className="white-panel p-6">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-[12px] uppercase tracking-[0.16em] text-[#8c3451]/55">Ưu tiên hôm nay</p>
                <h2 className="mt-2 text-[24px] font-semibold tracking-[-0.04em] text-[#17141a]">
                  Những điểm admin nên theo dõi tiếp theo
                </h2>
              </div>
              <span className="rounded-full bg-[#fff5f8] px-4 py-2 text-[12px] font-semibold text-[#8c3451]">
                {formatNumber(adminPriorities.length)} mục
              </span>
            </div>
            <div className="mt-5 space-y-3">
              {adminPriorities.map((item) => (
                <div key={item.title} className={`rounded-[20px] border px-4 py-4 ${item.tone}`}>
                  <p className="text-[16px] font-semibold">{item.title}</p>
                  <p className="mt-2 text-[14px] leading-6">{item.detail}</p>
                </div>
              ))}
            </div>
          </article>

          <article className="white-panel p-6">
            <p className="text-[12px] uppercase tracking-[0.16em] text-[#8c3451]/55">Góc nhìn nhanh</p>
            <h2 className="mt-2 text-[24px] font-semibold tracking-[-0.04em] text-[#17141a]">
              Tóm tắt ngắn về trạng thái người học
            </h2>
            <div className="mt-5 space-y-3">
              {learnerOverviewNotes.map((note) => (
                <div key={note} className="rounded-[18px] border border-[#f1e0e6] bg-white/75 px-4 py-3 text-[14px] leading-6 text-[#5f5954]">
                  {note}
                </div>
              ))}
            </div>
          </article>
        </section>

        {showSecondaryAdminSections && operationalWarnings.length > 0 ? (
          <section className="mt-6 white-panel border border-amber-200 bg-[#fffaf2] p-6">
            <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <p className="text-[12px] uppercase tracking-[0.16em] text-amber-700/80">Cảnh báo cần xử lý</p>
                <h2 className="mt-2 text-[24px] font-semibold text-[#17141a]">Một số tín hiệu cho thấy dữ liệu hoặc semantic stack chưa ở trạng thái tốt nhất.</h2>
              </div>
              <span className="rounded-full bg-white px-4 py-2 text-[12px] font-semibold text-amber-700">
                {formatNumber(operationalWarnings.length)} cảnh báo
              </span>
            </div>
            <div className="mt-5 flex flex-wrap gap-3">
              {operationalWarnings.map((warning) => (
                <span key={warning} className="rounded-full border border-amber-200 bg-white px-4 py-2 text-[13px] text-amber-800">
                  {warning}
                </span>
              ))}
            </div>
          </section>
        ) : null}

        {showSecondaryAdminSections ? (
        <section className="mt-6 white-panel p-6 md:p-7">
          <div className="mb-5 flex flex-col gap-2 sm:flex-row sm:items-end sm:justify-between">
            <div>
              <p className="text-[12px] uppercase tracking-[0.16em] text-[#8c3451]/55">Research metrics</p>
              <h2 className="mt-2 text-[28px] font-semibold text-[#17141a]">Tín hiệu nghiên cứu của recommendation, learning path và AI tutor</h2>
            </div>
            <span className="rounded-full bg-[#fff1f6] px-4 py-2 text-[12px] font-semibold text-[#8c3451]">
              Cửa sổ {research.window_days} ngày
            </span>
          </div>
          <div className="grid gap-4 lg:grid-cols-3">
            <article className="rounded-[22px] border border-[#f1e0e6] px-5 py-5">
              <p className="text-[12px] uppercase tracking-[0.16em] text-[#8c3451]/55">Recommendation</p>
              <p className="mt-3 text-[34px] font-semibold text-[#17141a]">{formatPercent(research.recommendation.ctr)}</p>
              <p className="mt-2 text-[14px] text-[#5f5954]">Tỷ lệ hoàn thành sau click {formatPercent(research.recommendation.completion_after_recommendation.rate)}</p>
              <p className="mt-1 text-[14px] text-[#5f5954]">Biến động confidence {formatSignedPercent(research.recommendation.confidence_gain_after_recommendation.avg_delta)}</p>
            </article>
            <article className="rounded-[22px] border border-[#f1e0e6] px-5 py-5">
              <p className="text-[12px] uppercase tracking-[0.16em] text-[#8c3451]/55">Learning path</p>
              <p className="mt-3 text-[34px] font-semibold text-[#17141a]">{formatPercent(research.learning_path.completion_rate)}</p>
              <p className="mt-2 text-[14px] text-[#5f5954]">Mức hoàn thành trung bình {formatPercent(research.learning_path.average_path_completion)}</p>
              <p className="mt-1 text-[14px] text-[#5f5954]">{formatNumber(research.learning_path.refinement_count)} lần refinement, {formatNumber(research.learning_path.bridge_insertions)} bridge insertions</p>
            </article>
            <article className="rounded-[22px] border border-[#f1e0e6] px-5 py-5">
              <p className="text-[12px] uppercase tracking-[0.16em] text-[#8c3451]/55">AI tutor</p>
              <p className="mt-3 text-[34px] font-semibold text-[#17141a]">{formatPercent(research.ai_tutor.retrieval_hit_ratio)}</p>
              <p className="mt-2 text-[14px] text-[#5f5954]">Độ tin cậy câu trả lời trung bình {formatPercent(research.ai_tutor.average_answer_confidence)}</p>
              <p className="mt-1 text-[14px] text-[#5f5954]">Tỷ lệ hỏi tiếp {formatPercent(research.ai_tutor.follow_up_ask_rate)}</p>
            </article>
          </div>
        </section>
        ) : null}

        {showSecondaryAdminSections ? (
        <AdaptiveDemoPanel
          userId={user?.user_id || ''}
          paths={demoPaths}
          mode="admin"
          refreshLabel="Tải lại các luồng adaptive demo"
          onRefreshPaths={loadDemoPaths}
          pathsError={demoError}
        />
        ) : null}

        {showSecondaryAdminSections ? (
        <section className="mt-6 grid gap-4 xl:grid-cols-[1.15fr,0.85fr]">
          <article className="white-panel p-6">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div>
                <p className="text-[12px] uppercase tracking-[0.16em] text-[#8c3451]/55">Resource curation</p>
                <h2 className="mt-2 text-[28px] font-semibold text-[#17141a]">Kiểm duyệt chất lượng và concept mapping của tài nguyên</h2>
              </div>
              <div className="flex flex-wrap gap-2">
                <span className="rounded-full bg-[#fff1f6] px-4 py-2 text-[12px] font-semibold text-[#8c3451]">{formatNumber(curation.total_items)} tài nguyên</span>
                <span className="rounded-full bg-amber-50 px-4 py-2 text-[12px] font-semibold text-amber-700">{formatNumber(curationSummary.lowQuality)} chất lượng thấp</span>
                <span className="rounded-full bg-rose-50 px-4 py-2 text-[12px] font-semibold text-rose-700">{formatNumber(curationSummary.duplicateGroups)} nhóm trùng lặp</span>
              </div>
            </div>

            <div className="mt-5 space-y-4">
              {curation.items.length === 0 ? (
                <div className="rounded-[20px] border border-dashed border-[#ecd7df] px-4 py-5 text-[14px] text-[#7b6f75]">
                  Chưa có dữ liệu kiểm duyệt tài nguyên.
                </div>
              ) : (
                curation.items.map((item) => {
                  const draft = drafts[item.resource_id] || {
                    curatedConceptIds: item.curated_concept_ids.join(', '),
                    qualityLabel: item.quality_label,
                    adminNotes: item.admin_notes,
                    hiddenFromRecommendation: item.hidden_from_recommendation,
                  };

                  return (
                    <div key={item.resource_id} className="rounded-[22px] border border-[#f1e0e6] px-5 py-5">
                      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                        <div>
                          <p className="text-[16px] font-semibold text-[#17141a]">{item.title}</p>
                          <p className="mt-1 text-[13px] text-[#5f5954]">{item.topic} • {item.source} • {item.status} • {formatNumber(item.chunks_count)} chunk</p>
                          <p className="mt-1 text-[12px] text-[#8b8187]">Cập nhật {formatDateTime(item.updated_at)}</p>
                        </div>
                        <div className="flex flex-wrap gap-2 lg:justify-end">
                          <span className="rounded-full bg-[#fff1f6] px-3 py-1 text-[12px] font-semibold text-[#8c3451]">
                            Chất lượng {formatPercent(item.quality_score)}
                          </span>
                          {item.problem_flags.map((flag) => (
                            <span key={flag} className="rounded-full border border-rose-200 bg-rose-50 px-3 py-1 text-[12px] font-semibold text-rose-700">
                              {getProblemFlagLabel(flag)}
                            </span>
                          ))}
                        </div>
                      </div>

                      <div className="mt-4 grid gap-3 lg:grid-cols-2">
                        <input
                          value={draft.curatedConceptIds}
                          onChange={(event) =>
                            setDrafts((current) => ({
                              ...current,
                              [item.resource_id]: { ...draft, curatedConceptIds: event.target.value },
                            }))
                          }
                          className="h-11 rounded-[16px] border border-[#e8d8de] px-4 text-[14px]"
                          placeholder="Danh sách concept id đã kiểm duyệt"
                        />
                        <input
                          value={draft.qualityLabel}
                          onChange={(event) =>
                            setDrafts((current) => ({
                              ...current,
                              [item.resource_id]: { ...draft, qualityLabel: event.target.value },
                            }))
                          }
                          className="h-11 rounded-[16px] border border-[#e8d8de] px-4 text-[14px]"
                          placeholder="Nhãn chất lượng"
                        />
                      </div>

                      <textarea
                        value={draft.adminNotes}
                        onChange={(event) =>
                          setDrafts((current) => ({
                            ...current,
                            [item.resource_id]: { ...draft, adminNotes: event.target.value },
                          }))
                        }
                        rows={3}
                        className="mt-3 w-full rounded-[16px] border border-[#e8d8de] px-4 py-3 text-[14px]"
                        placeholder="Ghi chú kiểm duyệt cho nội bộ admin"
                      />

                      <div className="mt-3 flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                        <label className="inline-flex items-center gap-3 text-[14px] text-[#362c31]">
                          <input
                            type="checkbox"
                            checked={draft.hiddenFromRecommendation}
                            onChange={(event) =>
                              setDrafts((current) => ({
                                ...current,
                                [item.resource_id]: { ...draft, hiddenFromRecommendation: event.target.checked },
                              }))
                            }
                          />
                          Ẩn khỏi recommendation
                        </label>
                        <button type="button" onClick={() => void saveResource(item.resource_id)} disabled={savingResourceId === item.resource_id} className="theme-button-primary disabled:opacity-60">
                          {savingResourceId === item.resource_id ? 'Đang lưu...' : 'Lưu kiểm duyệt'}
                        </button>
                      </div>
                    </div>
                  );
                })
              )}
            </div>
          </article>

          <div className="space-y-4">
            <article className="white-panel p-6">
              <p className="text-[12px] uppercase tracking-[0.16em] text-[#8c3451]/55">Ingestion health</p>
              <h2 className="mt-2 text-[24px] font-semibold text-[#17141a]">Trạng thái semantic stack</h2>
              <div className="mt-5 grid gap-3 sm:grid-cols-2">
                <div className="rounded-[18px] bg-[#fff5f8] px-4 py-4">
                  <p className="text-[12px] uppercase tracking-[0.14em] text-[#8c3451]/55">Embedding backend</p>
                  <p className="mt-2 text-[18px] font-semibold text-[#17141a]">{String((health.embedding as Record<string, unknown>).backend || 'unknown')}</p>
                </div>
                <div className="rounded-[18px] bg-[#fff5f8] px-4 py-4">
                  <p className="text-[12px] uppercase tracking-[0.14em] text-[#8c3451]/55">Vector store</p>
                  <p className="mt-2 text-[18px] font-semibold text-[#17141a]">{health.vector_store.available ? 'Sẵn sàng' : 'Chưa sẵn sàng'}</p>
                </div>
                <div className="rounded-[18px] bg-[#fff5f8] px-4 py-4">
                  <p className="text-[12px] uppercase tracking-[0.14em] text-[#8c3451]/55">Chunks có embedding</p>
                  <p className="mt-2 text-[18px] font-semibold text-[#17141a]">{formatNumber(health.chunk_totals.with_embeddings)}</p>
                </div>
                <div className="rounded-[18px] bg-[#fff5f8] px-4 py-4">
                  <p className="text-[12px] uppercase tracking-[0.14em] text-[#8c3451]/55">Chunks chưa có embedding</p>
                  <p className="mt-2 text-[18px] font-semibold text-[#17141a]">{formatNumber(health.chunk_totals.without_embeddings)}</p>
                </div>
              </div>
              <div className="mt-5">
                <p className="text-[12px] uppercase tracking-[0.14em] text-[#8c3451]/55">Trạng thái tài nguyên</p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {resourceStatusEntries.length === 0 ? (
                    <span className="rounded-full border border-dashed border-[#ead7de] px-3 py-2 text-[13px] text-[#7b6f75]">Chưa có dữ liệu trạng thái</span>
                  ) : (
                    resourceStatusEntries.map(([status, count]) => (
                      <span key={status} className={`rounded-full border px-3 py-2 text-[12px] font-semibold ${getStatusChipClassName(status)}`}>
                        {status}: {formatNumber(count)}
                      </span>
                    ))
                  )}
                </div>
              </div>

              <div className="mt-5">
                <div className="flex items-center justify-between gap-3">
                  <p className="text-[12px] uppercase tracking-[0.14em] text-[#8c3451]/55">Recent ingestion jobs</p>
                  <span className="text-[12px] text-[#7b6f75]">{formatNumber(recentJobs.length)} job gần nhất</span>
                </div>
                <div className="mt-3 space-y-3">
                  {recentJobs.length === 0 ? (
                    <div className="rounded-[18px] border border-dashed border-[#ecd7df] px-4 py-4 text-[13px] text-[#7b6f75]">Chưa có job ingestion gần đây.</div>
                  ) : (
                    recentJobs.map((job) => (
                      <div key={`${job.resourceId}-${job.updatedAt}-${job.status}`} className="rounded-[18px] border border-[#f1e0e6] px-4 py-4">
                        <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
                          <div>
                            <p className="text-[14px] font-semibold text-[#17141a]">Resource {job.resourceId.slice(-8)}</p>
                            <p className="mt-1 text-[12px] text-[#5f5954]">{job.resourceType} • {formatNumber(job.chunksCount)} chunk • {Math.round(job.processingTime)} ms</p>
                          </div>
                          <span className={`rounded-full border px-3 py-1 text-[12px] font-semibold ${getStatusChipClassName(job.status)}`}>
                            {job.status}
                          </span>
                        </div>
                        <p className="mt-2 text-[12px] text-[#7b6f75]">Cập nhật {formatDateTime(job.updatedAt)}</p>
                        {job.error ? <p className="mt-2 text-[12px] text-rose-700">{job.error}</p> : null}
                      </div>
                    ))
                  )}
                </div>
              </div>
            </article>

            <article className="white-panel p-6">
              <p className="text-[12px] uppercase tracking-[0.16em] text-[#8c3451]/55">Prerequisite graph</p>
              <h2 className="mt-2 text-[24px] font-semibold text-[#17141a]">Trình chỉnh đồ thị tiên quyết</h2>
              <select
                value={selectedConceptId}
                onChange={(event) => {
                  setSelectedConceptId(event.target.value);
                  const found = graph.concepts.find((item) => item.concept_id === event.target.value);
                  setPrerequisiteDraft(found ? found.prerequisites.join(', ') : '');
                }}
                className="mt-4 h-11 w-full rounded-[16px] border border-[#e8d8de] px-4 text-[14px]"
              >
                {graph.concepts.map((concept) => (
                  <option key={concept.concept_id} value={concept.concept_id}>
                    {concept.concept_name || concept.concept_id}
                  </option>
                ))}
              </select>
              <textarea
                value={prerequisiteDraft}
                onChange={(event) => setPrerequisiteDraft(event.target.value)}
                rows={4}
                className="mt-3 w-full rounded-[16px] border border-[#e8d8de] px-4 py-3 text-[14px]"
                placeholder="Danh sách id tiên quyết, phân tách bằng dấu phẩy"
              />
              {selectedConcept ? (
                <p className="mt-3 text-[13px] text-[#5f5954]">
                  Môn/chủ đề {selectedConcept.subject_id || selectedConcept.topic || 'chưa rõ'} • {formatNumber(graph.total_concepts)} khái niệm • {formatNumber(graph.total_edges)} cạnh
                </p>
              ) : null}
              <button type="button" onClick={() => void saveConcept()} disabled={!selectedConceptId || savingConcept} className="theme-button-primary mt-4 w-full disabled:opacity-60">
                {savingConcept ? 'Đang lưu đồ thị...' : 'Lưu đồ thị tiên quyết'}
              </button>
            </article>
          </div>
        </section>
        ) : null}
      </div>
    </DashboardLayout>
  );
}
