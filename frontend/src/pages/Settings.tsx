import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import DashboardLayout from '../components/layout/DashboardLayout';
import PageHero from '../components/ui/PageHero';
import { useAuth } from '../contexts/AuthContext';
import { authService } from '../services/authService';
import { learnerProfileService } from '../services/learnerProfileService';
import type {
  DiagnosticResult,
  DiagnosticStartResponse,
  LearnerLevel,
  LearnerProfile,
  LearningPace,
  PreferredResourceType,
  SubjectId,
  TimeBudgetUnit,
} from '../types/learnerProfile';

interface SettingsFormState {
  name: string;
  email: string;
  level: LearnerLevel;
  learningGoal: string;
  targetRole: string;
  targetOutcome: string;
  timeBudgetValue: number;
  timeBudgetUnit: TimeBudgetUnit;
  preferredResourceType: PreferredResourceType;
  learningPace: LearningPace;
  desiredDeadline: string;
}

const SUBJECT_OPTIONS: Array<{ value: SubjectId; label: string }> = [
  { value: 'python', label: 'Python' },
  { value: 'cpp', label: 'C++' },
  { value: 'csharp', label: 'C#' },
  { value: 'java', label: 'Java' },
  { value: 'web', label: 'Phát triển web' },
];

const LEVEL_OPTIONS: Array<{ value: LearnerLevel; label: string; description: string }> = [
  {
    value: 'beginner',
    label: 'Bắt đầu',
    description: 'Đi từ nền tảng, bám chặt các khái niệm cốt lõi trước khi mở rộng.',
  },
  {
    value: 'intermediate',
    label: 'Trung cấp',
    description: 'Đã có nền cơ bản và cần tăng tốc sang bài toán thực tế hơn.',
  },
  {
    value: 'advanced',
    label: 'Nâng cao',
    description: 'Ưu tiên chiều sâu, hệ thống lớn và bài tập gần môi trường thật.',
  },
];

const RESOURCE_TYPE_OPTIONS: Array<{ value: PreferredResourceType; label: string }> = [
  { value: 'mixed', label: 'Kết hợp' },
  { value: 'video', label: 'Video' },
  { value: 'pdf', label: 'PDF / tài liệu' },
  { value: 'practice', label: 'Thực hành' },
];

const PACE_OPTIONS: Array<{ value: LearningPace; label: string }> = [
  { value: 'light', label: 'Nhẹ' },
  { value: 'steady', label: 'Đều' },
  { value: 'intensive', label: 'Tăng tốc' },
];

const DIAGNOSTIC_SCORE_OPTIONS = [
  { value: 0, label: 'Chưa biết' },
  { value: 25, label: 'Biết sơ' },
  { value: 50, label: 'Làm được cơ bản' },
  { value: 75, label: 'Khá chắc' },
  { value: 100, label: 'Rất vững' },
];

const DEFAULT_FORM: SettingsFormState = {
  name: '',
  email: '',
  level: 'beginner',
  learningGoal: '',
  targetRole: '',
  targetOutcome: '',
  timeBudgetValue: 300,
  timeBudgetUnit: 'weekly',
  preferredResourceType: 'mixed',
  learningPace: 'steady',
  desiredDeadline: '',
};

const formatDiagnosticPercent = (value?: number | null) => {
  if (typeof value !== 'number' || Number.isNaN(value)) {
    return 'Chưa có';
  }
  return `${Math.round(value * 100)}%`;
};

const formatDate = (value?: string | null) => {
  if (!value) {
    return 'Chưa có';
  }
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }
  return parsed.toLocaleDateString('vi-VN');
};

const getSubjectLabel = (subjectId?: string | null) =>
  SUBJECT_OPTIONS.find((subject) => subject.value === subjectId)?.label || subjectId || 'Môn học';

const getLevelLabel = (level?: string | null) =>
  LEVEL_OPTIONS.find((option) => option.value === level)?.label || level || 'Chưa rõ';

const getResourcePreferenceLabel = (value: PreferredResourceType) =>
  RESOURCE_TYPE_OPTIONS.find((option) => option.value === value)?.label || value;

const getPaceLabel = (value: LearningPace) =>
  PACE_OPTIONS.find((option) => option.value === value)?.label || value;

const profileToForm = (
  profile: LearnerProfile,
  currentUser: { name?: string; email?: string } | null,
): SettingsFormState => ({
  name: currentUser?.name || '',
  email: currentUser?.email || '',
  level: profile.level || 'beginner',
  learningGoal: profile.learning_goal || '',
  targetRole: profile.target_role || '',
  targetOutcome: profile.target_outcome || '',
  timeBudgetValue: profile.time_budget?.value || 300,
  timeBudgetUnit: profile.time_budget?.unit || 'weekly',
  preferredResourceType: profile.preferred_resource_type || 'mixed',
  learningPace: profile.learning_pace || 'steady',
  desiredDeadline: profile.desired_deadline || '',
});

export default function Settings() {
  const { user, loading: authLoading, refreshUser } = useAuth();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<SettingsFormState>(DEFAULT_FORM);
  const [profile, setProfile] = useState<LearnerProfile | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);
  const [diagnosticSubject, setDiagnosticSubject] = useState<SubjectId>('python');
  const [diagnosticSession, setDiagnosticSession] = useState<DiagnosticStartResponse | null>(null);
  const [diagnosticAnswers, setDiagnosticAnswers] = useState<Record<string, number | undefined>>(
    {},
  );
  const [diagnosticResult, setDiagnosticResult] = useState<DiagnosticResult | null>(null);
  const [diagnosticLoading, setDiagnosticLoading] = useState(false);

  useEffect(() => {
    if (!authLoading && !user) {
      navigate('/login');
    }
  }, [authLoading, navigate, user]);

  useEffect(() => {
    const fetchSettingsContext = async () => {
      if (!user) {
        setLoading(false);
        return;
      }

      try {
        setLoading(true);
        setError(null);

        const [currentUser, learnerProfile] = await Promise.all([
          authService.getCurrentUser(),
          learnerProfileService.getMyProfile(),
        ]);

        const firstDiagnosticSubject =
          (Object.keys(learnerProfile.diagnostic_summary_by_subject || {})[0] as
            | SubjectId
            | undefined) ||
          (Object.keys(learnerProfile.prior_knowledge_by_subject || {})[0] as
            | SubjectId
            | undefined) ||
          'python';

        setProfile(learnerProfile);
        setForm(profileToForm(learnerProfile, currentUser));
        setDiagnosticSubject(firstDiagnosticSubject);

        try {
          const result = await learnerProfileService.getDiagnosticResult(firstDiagnosticSubject);
          setDiagnosticResult(result.completed ? result : null);
        } catch {
          setDiagnosticResult(null);
        }
      } catch (fetchError) {
        console.error('Failed to load settings profile:', fetchError);
        setError(
          fetchError instanceof Error ? fetchError.message : 'Không thể tải learner profile.',
        );
      } finally {
        setLoading(false);
      }
    };

    void fetchSettingsContext();
  }, [user]);

  useEffect(() => {
    const fetchDiagnosticResult = async () => {
      if (!user) {
        return;
      }

      try {
        const result = await learnerProfileService.getDiagnosticResult(diagnosticSubject);
        setDiagnosticResult(result.completed ? result : null);
      } catch {
        setDiagnosticResult(null);
      }
    };

    if (profile) {
      void fetchDiagnosticResult();
    }
  }, [diagnosticSubject, profile, user]);

  const activeLevelDescription = useMemo(
    () => LEVEL_OPTIONS.find((option) => option.value === form.level)?.description || '',
    [form.level],
  );

  const activeSignalSummary = useMemo(
    () => [
      {
        label: 'Mục tiêu học',
        value: form.learningGoal.trim() || 'Chưa thiết lập rõ',
        detail: 'Dùng để ưu tiên chủ đề và thứ tự bài học.',
      },
      {
        label: 'Cách học phù hợp',
        value: `${getPaceLabel(form.learningPace)} • ${getResourcePreferenceLabel(form.preferredResourceType)}`,
        detail: `${form.timeBudgetValue} phút/${form.timeBudgetUnit === 'daily' ? 'ngày' : 'tuần'}`,
      },
      {
        label: 'Mức hệ thống đang hiểu',
        value: getLevelLabel(
          (profile?.prior_knowledge_by_subject || {})[diagnosticSubject] || form.level,
        ),
        detail: diagnosticResult?.completed
          ? `Lần chẩn đoán gần nhất: ${formatDiagnosticPercent(diagnosticResult.average_score)}`
          : 'Chưa có kết quả chẩn đoán gần đây.',
      },
    ],
    [
      diagnosticResult?.average_score,
      diagnosticResult?.completed,
      diagnosticSubject,
      form.learningGoal,
      form.learningPace,
      form.preferredResourceType,
      form.timeBudgetUnit,
      form.timeBudgetValue,
      form.level,
      profile?.prior_knowledge_by_subject,
    ],
  );

  const learnerSignalsApplied = useMemo(
    () =>
      [
        `Mục tiêu: ${form.learningGoal.trim() || 'chưa khai báo chi tiết'}`,
        `Đầu ra mong muốn: ${form.targetOutcome.trim() || 'chưa khai báo'}`,
        `Nhịp học: ${getPaceLabel(form.learningPace)}`,
        `Quỹ thời gian: ${form.timeBudgetValue} phút/${form.timeBudgetUnit === 'daily' ? 'ngày' : 'tuần'}`,
        `Ưa thích tài nguyên: ${getResourcePreferenceLabel(form.preferredResourceType)}`,
        `Mức hiện tại: ${getLevelLabel((profile?.prior_knowledge_by_subject || {})[diagnosticSubject] || form.level)}`,
      ].filter(Boolean),
    [
      diagnosticSubject,
      form.learningGoal,
      form.learningPace,
      form.preferredResourceType,
      form.targetOutcome,
      form.timeBudgetUnit,
      form.timeBudgetValue,
      form.level,
      profile?.prior_knowledge_by_subject,
    ],
  );

  const handleFieldChange = (field: keyof SettingsFormState, value: string | number) => {
    setForm((previous) => ({
      ...previous,
      [field]: value,
    }));
    setSuccess(null);
  };

  const handleSave = async () => {
    try {
      setSaving(true);
      setError(null);
      setSuccess(null);

      const updatedProfile = await learnerProfileService.updateMyProfile({
        level: form.level,
        learning_goal: form.learningGoal.trim() || undefined,
        target_role: form.targetRole.trim() || undefined,
        target_outcome: form.targetOutcome.trim() || undefined,
        time_budget: {
          value: form.timeBudgetValue,
          unit: form.timeBudgetUnit,
        },
        preferred_resource_type: form.preferredResourceType,
        learning_pace: form.learningPace,
        desired_deadline: form.desiredDeadline || undefined,
        prior_knowledge_by_subject: {
          [diagnosticSubject]: form.level,
        },
      });

      setProfile(updatedProfile);
      await refreshUser();
      setSuccess('Đã cập nhật learner profile và các tín hiệu cá nhân hóa.');
    } catch (saveError) {
      console.error('Failed to save settings:', saveError);
      setError(saveError instanceof Error ? saveError.message : 'Không thể lưu learner profile.');
    } finally {
      setSaving(false);
    }
  };

  const handleStartDiagnostic = async () => {
    try {
      setDiagnosticLoading(true);
      setError(null);
      setSuccess(null);

      const session = await learnerProfileService.startDiagnostic({
        subject_id: diagnosticSubject,
        goal: form.learningGoal.trim() || undefined,
      });

      setDiagnosticSession(session);
      setDiagnosticAnswers(
        Object.fromEntries(session.questions.map((question) => [question.concept_key, undefined])),
      );
      setDiagnosticResult(null);
    } catch (diagnosticError) {
      console.error('Failed to start diagnostic:', diagnosticError);
      setError(
        diagnosticError instanceof Error
          ? diagnosticError.message
          : 'Không thể khởi tạo chẩn đoán đầu vào.',
      );
    } finally {
      setDiagnosticLoading(false);
    }
  };

  const handleSubmitDiagnostic = async () => {
    if (!diagnosticSession) {
      return;
    }

    const unanswered = diagnosticSession.questions.find(
      (question) => diagnosticAnswers[question.concept_key] == null,
    );
    if (unanswered) {
      setError('Vui lòng trả lời đủ tất cả các mục chẩn đoán.');
      return;
    }

    try {
      setDiagnosticLoading(true);
      setError(null);
      setSuccess(null);

      const result = await learnerProfileService.submitDiagnostic({
        session_id: diagnosticSession.session_id,
        subject_id: diagnosticSubject,
        answers: diagnosticSession.questions.map((question) => ({
          concept_key: question.concept_key,
          score: diagnosticAnswers[question.concept_key] ?? 0,
        })),
      });

      setDiagnosticResult(result);
      setDiagnosticSession(null);
      setForm((previous) => ({
        ...previous,
        level: result.recommended_level,
      }));

      const refreshedProfile = await learnerProfileService.getMyProfile();
      setProfile(refreshedProfile);
      await refreshUser();
      setSuccess('Đã cập nhật chẩn đoán đầu vào cho môn học này.');
    } catch (diagnosticError) {
      console.error('Failed to submit diagnostic:', diagnosticError);
      setError(
        diagnosticError instanceof Error
          ? diagnosticError.message
          : 'Không thể lưu kết quả chẩn đoán.',
      );
    } finally {
      setDiagnosticLoading(false);
    }
  };

  if (authLoading || loading) {
    return (
      <DashboardLayout>
        <div className="page-shell">
          <div className="white-panel flex min-h-[320px] items-center justify-center">
            <div className="text-center">
              <div className="mx-auto mb-4 h-12 w-12 animate-spin rounded-full border-b-2 border-[#8c3451]" />
              <p className="text-[#8c3451]">Đang tải learner profile...</p>
            </div>
          </div>
        </div>
      </DashboardLayout>
    );
  }

  if (!user) {
    return null;
  }

  return (
    <DashboardLayout>
      <div className="page-shell desktop-1440-settings">
        <PageHero
          className="mb-6"
          kicker="Thiết lập học tập"
          title="Tinh chỉnh cách hệ thống hiểu bạn để path và recommendation bám sát hơn."
          description="Trang này gom các tín hiệu thực sự ảnh hưởng đến lộ trình, tài nguyên và nhịp học tiếp theo. Bạn chỉ cần nói rõ muốn học gì, muốn học như thế nào và kiểm tra lại hệ thống đang hiểu bạn ra sao."
          actions={
            <button
              onClick={handleSave}
              disabled={saving}
              className="theme-button min-w-[180px] disabled:cursor-not-allowed disabled:opacity-60"
            >
              {saving ? 'Đang lưu...' : 'Lưu thay đổi'}
            </button>
          }
        />
        {error && (
          <div className="white-panel mb-6 border border-red-200 px-5 py-4 text-[14px] text-red-700">
            {error}
          </div>
        )}

        {success && (
          <div className="white-panel mb-6 border border-emerald-200 px-5 py-4 text-[14px] text-emerald-700">
            {success}
          </div>
        )}

        <div className="grid gap-6">
          <section className="space-y-6">
            <div className="white-panel p-8">
              <div className="mb-6">
                <h2 className="page-section-title">Thông tin tài khoản</h2>
                <p className="mt-2 text-[13px] leading-5 text-[#6d6660]">Chỉ dùng để nhận diện tài khoản.</p>
              </div>

              <div className="grid gap-5 md:grid-cols-2">
                <label className="block">
                  <span className="mb-2 block text-[13px] font-medium text-[#6a625d]">
                    Họ và tên
                  </span>
                  <input
                    value={form.name}
                    disabled
                    className="theme-input rounded-[18px] bg-[#fbf4f8] text-[#514942] opacity-80"
                  />
                </label>
                <label className="block">
                  <span className="mb-2 block text-[13px] font-medium text-[#6a625d]">Email</span>
                  <input
                    value={form.email}
                    disabled
                    className="theme-input rounded-[18px] bg-[#fbf4f8] text-[#514942] opacity-80"
                  />
                </label>
              </div>
            </div>

            <div className="soft-panel p-8">
              <div className="mb-6">
                <h2 className="page-section-title">Bạn muốn học gì</h2>
                <p className="mt-2 text-[13px] leading-5 text-[#6d6660]">Mục tiêu rõ hơn, path gọn hơn.</p>
              </div>

              <div className="grid gap-5 md:grid-cols-2">
                <label className="block md:col-span-2">
                  <span className="mb-2 block text-[13px] font-medium text-[#6a625d]">
                    Bạn đang hướng tới điều gì?
                  </span>
                  <textarea
                    value={form.learningGoal}
                    onChange={(event) => handleFieldChange('learningGoal', event.target.value)}
                    rows={4}
                    className="theme-input min-h-[140px] resize-y rounded-[24px] py-4"
                    placeholder="Ví dụ: hoàn thành backend foundation để build API production-ready."
                  />
                </label>

                <label className="block">
                  <span className="mb-2 block text-[13px] font-medium text-[#6a625d]">
                    Bạn muốn trở thành ai?
                  </span>
                  <input
                    value={form.targetRole}
                    onChange={(event) => handleFieldChange('targetRole', event.target.value)}
                    className="theme-input rounded-[18px]"
                    placeholder="Backend developer, frontend intern..."
                  />
                </label>

                <label className="block">
                  <span className="mb-2 block text-[13px] font-medium text-[#6a625d]">
                    Kết quả bạn muốn đạt được
                  </span>
                  <input
                    value={form.targetOutcome}
                    onChange={(event) => handleFieldChange('targetOutcome', event.target.value)}
                    className="theme-input rounded-[18px]"
                    placeholder="Build được API, pass vòng phỏng vấn đầu tiên..."
                  />
                </label>

                <div className="md:col-span-2 mt-2 rounded-[22px] border border-white/70 bg-white/70 px-5 py-4">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8c3451]/55">
                    Bạn muốn học như thế nào
                  </p>
                  <p className="mt-2 text-[13px] leading-5 text-[#6d6660]">Chọn nhịp, thời gian và dạng tài nguyên.</p>
                </div>

                <label className="block">
                  <span className="mb-2 block text-[13px] font-medium text-[#6a625d]">
                    Mức hiện tại của bạn
                  </span>
                  <select
                    value={form.level}
                    onChange={(event) =>
                      handleFieldChange('level', event.target.value as LearnerLevel)
                    }
                    className="theme-input rounded-[18px]"
                  >
                    {LEVEL_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                  <p className="mt-3 text-[12px] leading-5 text-[#7a726c]">
                    {activeLevelDescription}
                  </p>
                </label>

                <label className="block">
                  <span className="mb-2 block text-[13px] font-medium text-[#6a625d]">
                    Nhịp học mong muốn
                  </span>
                  <select
                    value={form.learningPace}
                    onChange={(event) =>
                      handleFieldChange('learningPace', event.target.value as LearningPace)
                    }
                    className="theme-input rounded-[18px]"
                  >
                    {PACE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="block">
                  <span className="mb-2 block text-[13px] font-medium text-[#6a625d]">
                    Bạn dành bao nhiêu thời gian?
                  </span>
                  <input
                    type="number"
                    min={30}
                    value={form.timeBudgetValue}
                    onChange={(event) =>
                      handleFieldChange('timeBudgetValue', Number(event.target.value) || 30)
                    }
                    className="theme-input rounded-[18px]"
                  />
                </label>

                <label className="block">
                  <span className="mb-2 block text-[13px] font-medium text-[#6a625d]">Theo chu kỳ nào?</span>
                  <select
                    value={form.timeBudgetUnit}
                    onChange={(event) =>
                      handleFieldChange('timeBudgetUnit', event.target.value as TimeBudgetUnit)
                    }
                    className="theme-input rounded-[18px]"
                  >
                    <option value="daily">Mỗi ngày</option>
                    <option value="weekly">Mỗi tuần</option>
                  </select>
                </label>

                <label className="block">
                  <span className="mb-2 block text-[13px] font-medium text-[#6a625d]">
                    Bạn thích học bằng dạng tài nguyên nào?
                  </span>
                  <select
                    value={form.preferredResourceType}
                    onChange={(event) =>
                      handleFieldChange(
                        'preferredResourceType',
                        event.target.value as PreferredResourceType,
                      )
                    }
                    className="theme-input rounded-[18px]"
                  >
                    {RESOURCE_TYPE_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="block">
                  <span className="mb-2 block text-[13px] font-medium text-[#6a625d]">
                    Mốc bạn muốn đạt tới
                  </span>
                  <input
                    type="date"
                    value={form.desiredDeadline}
                    onChange={(event) => handleFieldChange('desiredDeadline', event.target.value)}
                    className="theme-input rounded-[18px]"
                  />
                </label>
              </div>
            </div>
            <div className="white-panel p-8">
              <div className="mb-6 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
                <div>
                  <h2 className="page-section-title">Hệ thống hiện đang hiểu bạn ra sao</h2>
                  <p className="mt-2 text-[13px] leading-5 text-[#6d6660]">Chạy chẩn đoán để cập nhật mức hiện tại.</p>
                </div>
                <div className="flex gap-3">
                  <select
                    value={diagnosticSubject}
                    onChange={(event) => setDiagnosticSubject(event.target.value as SubjectId)}
                    className="theme-input min-w-[180px] rounded-[18px]"
                  >
                    {SUBJECT_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={handleStartDiagnostic}
                    disabled={diagnosticLoading}
                    className="theme-button-secondary disabled:opacity-60"
                  >
                    {diagnosticLoading ? 'Đang tạo...' : 'Bắt đầu chẩn đoán'}
                  </button>
                </div>
              </div>

              {diagnosticResult && !diagnosticSession ? (
                <div className="mb-6 rounded-[24px] border border-[#efe1d6] bg-[#fff8fb] p-5">
                  <div className="grid gap-4 md:grid-cols-3">
                    <div className="metric-card">
                      <p className="text-[12px] uppercase tracking-[0.18em] text-[#8c3451]/55">
                        Môn đang đọc tín hiệu
                      </p>
                      <p className="mt-3 text-[20px] font-semibold text-[#121019]">
                        {getSubjectLabel(diagnosticResult.subject_id)}
                      </p>
                    </div>
                    <div className="metric-card">
                      <p className="text-[12px] uppercase tracking-[0.18em] text-[#8c3451]/55">
                        Mức hệ thống gợi ý
                      </p>
                      <p className="mt-3 text-[20px] font-semibold text-[#121019]">
                        {getLevelLabel(diagnosticResult.recommended_level)}
                      </p>
                    </div>
                    <div className="metric-card">
                      <p className="text-[12px] uppercase tracking-[0.18em] text-[#8c3451]/55">
                        Độ vững trung bình
                      </p>
                      <p className="mt-3 text-[20px] font-semibold text-[#121019]">
                        {formatDiagnosticPercent(diagnosticResult.average_score)}
                      </p>
                    </div>
                  </div>
                  <p className="mt-4 text-[13px] text-[#6d6660]">
                    Đánh giá gần nhất: {formatDate(diagnosticResult.evaluated_at)}
                  </p>
                </div>
              ) : null}

              {diagnosticSession ? (
                <div className="space-y-4">
                  {diagnosticSession.questions.map((question, index) => (
                    <div
                      key={question.concept_key}
                      className="rounded-[22px] border border-[#efe1d6] bg-white/80 px-4 py-4"
                    >
                      <p className="text-[12px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]/60">
                        Mục {index + 1}
                      </p>
                      <p className="mt-2 text-[16px] font-semibold text-[#17141a]">
                        {question.title}
                      </p>
                      <p className="mt-2 text-[12px] leading-5 text-[#6d655f]">
                        {question.prompt}
                      </p>
                      <select
                        value={diagnosticAnswers[question.concept_key] ?? ''}
                        onChange={(event) =>
                          setDiagnosticAnswers((previous) => ({
                            ...previous,
                            [question.concept_key]: Number(event.target.value),
                          }))
                        }
                        className="theme-input mt-4 rounded-[18px]"
                      >
                        <option value="">Chọn mức độ tự tin</option>
                        {DIAGNOSTIC_SCORE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                    </div>
                  ))}

                  <div className="flex flex-wrap gap-3">
                    <button
                      type="button"
                      onClick={handleSubmitDiagnostic}
                      disabled={diagnosticLoading}
                    className="theme-button disabled:opacity-60"
                  >
                      {diagnosticLoading ? 'Đang lưu...' : 'Lưu kết quả chẩn đoán'}
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setDiagnosticSession(null);
                        setDiagnosticAnswers({});
                      }}
                      className="theme-button-secondary"
                    >
                      Hủy phiên này
                    </button>
                  </div>
                </div>
              ) : (
                <div className="rounded-[22px] border border-dashed border-[#ead7df] bg-[#fff8fb] px-5 py-5 text-[13px] leading-5 text-[#6d6660]">
                  {diagnosticResult?.completed
                    ? 'Có thể chạy lại khi mức học thay đổi.'
                    : 'Chưa có tín hiệu chẩn đoán cho môn này.'}
                </div>
              )}
            </div>
          </section>

          <aside className="hidden space-y-6 xl:sticky xl:top-4 xl:self-start">
            <div className="white-panel p-7">
              <h2 className="page-section-title mb-5">Các tín hiệu đang được áp dụng</h2>
              <div className="space-y-4">
                {activeSignalSummary.map((item) => (
                  <div key={item.label} className="metric-card">
                    <p className="text-[12px] uppercase tracking-[0.18em] text-[#8c3451]/55">
                      {item.label}
                    </p>
                    <p className="mt-3 text-[14px] leading-5 text-[#564f49]">{item.value}</p>
                    <p className="mt-2 text-[12px] leading-5 text-[#7d666f]">{item.detail}</p>
                  </div>
                ))}
              </div>
            </div>

            <div className="soft-panel p-7">
              <h2 className="page-section-title mb-4">Tín hiệu người học đang được dùng ở đâu</h2>
              <div className="space-y-3">
                {learnerSignalsApplied.map((signal) => (
                  <div
                    key={signal}
                    className="rounded-[18px] border border-white/70 bg-white/75 px-4 py-3 text-[12px] leading-5 text-[#5d5650]"
                  >
                    {signal}
                  </div>
                ))}
              </div>
              <div className="mt-5 rounded-[18px] border border-white/70 bg-white/75 px-4 py-4 text-[12px] leading-5 text-[#5d5650]">
                Path dùng mục tiêu và mức hiện tại. Recommendation dùng thời gian, nhịp học và ưu tiên tài nguyên.
              </div>
            </div>
          </aside>
        </div>
      </div>
    </DashboardLayout>
  );
}
