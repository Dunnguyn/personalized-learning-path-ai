import { useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import DashboardLayout from '../components/layout/DashboardLayout';
import { useAuth } from '../contexts/AuthContext';
import { authService } from '../services/authService';

type LevelValue = 'beginner' | 'intermediate' | 'advanced';

interface SettingsFormState {
  name: string;
  email: string;
  level: LevelValue;
  learningGoal: string;
}

const LEVEL_OPTIONS: Array<{ value: LevelValue; label: string; description: string }> = [
  {
    value: 'beginner',
    label: 'Bắt đầu',
    description: 'Phù hợp nếu bạn mới làm quen và muốn đi từ nền tảng.',
  },
  {
    value: 'intermediate',
    label: 'Trung cấp',
    description: 'Phù hợp nếu bạn đã có nền tảng cơ bản và muốn tăng tốc.',
  },
  {
    value: 'advanced',
    label: 'Nâng cao',
    description: 'Phù hợp nếu bạn muốn học chuyên sâu và thực chiến hơn.',
  },
];

const DEFAULT_FORM: SettingsFormState = {
  name: '',
  email: '',
  level: 'beginner',
  learningGoal: '',
};

const normalizeLevel = (level?: string): LevelValue => {
  if (level === 'intermediate' || level === 'advanced') {
    return level;
  }
  return 'beginner';
};

export default function Settings() {
  const { user, loading: authLoading, refreshUser } = useAuth();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [form, setForm] = useState<SettingsFormState>(DEFAULT_FORM);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<string | null>(null);

  useEffect(() => {
    if (!authLoading && !user) {
      navigate('/login');
    }
  }, [authLoading, navigate, user]);

  useEffect(() => {
    const fetchProfile = async () => {
      if (!user) {
        setLoading(false);
        return;
      }

      try {
        setLoading(true);
        setError(null);

        const profile = await authService.getCurrentUser();
        const storedGoal = localStorage.getItem('userGoal') || '';

        setForm({
          name: profile.name || user.name || '',
          email: profile.email || user.email || '',
          level: normalizeLevel(profile.level || user.level),
          learningGoal: storedGoal,
        });
      } catch (fetchError) {
        console.error('Failed to load settings profile:', fetchError);
        setError(fetchError instanceof Error ? fetchError.message : 'Không thể tải cài đặt tài khoản.');
        setForm({
          name: user.name || '',
          email: user.email || '',
          level: normalizeLevel(user.level),
          learningGoal: localStorage.getItem('userGoal') || '',
        });
      } finally {
        setLoading(false);
      }
    };

    void fetchProfile();
  }, [user]);

  const activeLevelDescription = useMemo(
    () => LEVEL_OPTIONS.find((option) => option.value === form.level)?.description || '',
    [form.level]
  );

  const handleFieldChange = (
    field: keyof SettingsFormState,
    value: string
  ) => {
    setForm((prev) => ({
      ...prev,
      [field]: value,
    }));
    setSuccess(null);
  };

  const handleSave = async () => {
    if (!user) {
      return;
    }

    try {
      setSaving(true);
      setError(null);
      setSuccess(null);

      await authService.updateUserLevel({
        user_id: user.user_id,
        level: form.level,
        learning_goal: form.learningGoal.trim() || undefined,
      });

      localStorage.setItem('userGoal', form.learningGoal.trim());
      await refreshUser();
      setSuccess('Đã lưu cài đặt học tập của bạn.');
    } catch (saveError) {
      console.error('Failed to save settings:', saveError);
      setError(saveError instanceof Error ? saveError.message : 'Không thể lưu cài đặt lúc này.');
    } finally {
      setSaving(false);
    }
  };

  if (authLoading || loading) {
    return (
      <DashboardLayout>
        <div className="page-shell">
          <div className="white-panel flex min-h-[320px] items-center justify-center">
            <div className="text-center">
              <div className="mx-auto mb-4 h-12 w-12 animate-spin rounded-full border-b-2 border-[#8c3451]"></div>
              <p className="text-[#8c3451]">Đang tải cài đặt tài khoản...</p>
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
      <div className="page-shell">
        <p className="page-kicker">Cài đặt</p>
        <div className="mb-8 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <h1 className="page-title mb-3">Hồ sơ học tập</h1>
            <p className="max-w-[760px] text-[15px] leading-7 text-[#5b544d]">
              Bạn có thể cập nhật cấp độ hiện tại và mục tiêu học tập để hệ thống cá nhân hóa
              lộ trình, tài nguyên và gợi ý học tập phù hợp hơn.
            </p>
          </div>
          <button
            onClick={handleSave}
            disabled={saving}
            className="theme-button min-w-[180px] disabled:cursor-not-allowed disabled:opacity-60"
          >
            {saving ? 'Đang lưu...' : 'Lưu thay đổi'}
          </button>
        </div>

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

        <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_360px]">
          <section className="space-y-6">
            <div className="white-panel p-8">
              <div className="mb-6">
                <h2 className="page-section-title">Thông tin tài khoản</h2>
                <p className="mt-2 text-[14px] leading-6 text-[#6d6660]">
                  Tên và email hiện được đồng bộ từ hồ sơ đăng nhập. Bạn có thể dùng phần này để
                  kiểm tra nhanh thông tin tài khoản đang hoạt động.
                </p>
              </div>

              <div className="grid gap-5 md:grid-cols-2">
                <label className="block">
                  <span className="mb-2 block text-[13px] font-medium text-[#6a625d]">Họ và tên</span>
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
                <h2 className="page-section-title">Thiết lập cá nhân hóa</h2>
                <p className="mt-2 text-[14px] leading-6 text-[#6d6660]">
                  Các thay đổi dưới đây sẽ được dùng cho learning path, dashboard recommendation và
                  các gợi ý từ trợ giảng AI.
                </p>
              </div>

              <div className="space-y-6">
                <label className="block">
                  <span className="mb-2 block text-[13px] font-medium text-[#6a625d]">Cấp độ hiện tại</span>
                  <select
                    value={form.level}
                    onChange={(event) => handleFieldChange('level', event.target.value)}
                    className="theme-input rounded-[18px]"
                  >
                    {LEVEL_OPTIONS.map((option) => (
                      <option key={option.value} value={option.value}>
                        {option.label}
                      </option>
                    ))}
                  </select>
                  <p className="mt-3 text-[13px] leading-6 text-[#7a726c]">{activeLevelDescription}</p>
                </label>

                <label className="block">
                  <span className="mb-2 block text-[13px] font-medium text-[#6a625d]">Mục tiêu học tập</span>
                  <textarea
                    value={form.learningGoal}
                    onChange={(event) => handleFieldChange('learningGoal', event.target.value)}
                    rows={5}
                    placeholder="Ví dụ: Thành thạo Python backend để xây dựng API và sẵn sàng cho dự án thực tế."
                    className="theme-input min-h-[150px] resize-y rounded-[24px] py-4"
                  />
                  <div className="mt-3 flex items-center justify-between text-[12px] text-[#837b75]">
                    <span>Mục tiêu này sẽ được lưu cùng hồ sơ học tập hiện tại.</span>
                    <span>{form.learningGoal.trim().length} ký tự</span>
                  </div>
                </label>
              </div>
            </div>
          </section>

          <aside className="space-y-6 xl:sticky xl:top-4 xl:self-start">
            <div className="white-panel p-7">
              <h2 className="page-section-title mb-5">Tóm tắt nhanh</h2>
              <div className="space-y-4">
                <div className="metric-card">
                  <p className="text-[12px] uppercase tracking-[0.18em] text-[#8c3451]/55">Cấp độ</p>
                  <p className="mt-3 text-[26px] font-semibold text-[#121019]">
                    {LEVEL_OPTIONS.find((option) => option.value === form.level)?.label}
                  </p>
                </div>
                <div className="metric-card">
                  <p className="text-[12px] uppercase tracking-[0.18em] text-[#8c3451]/55">Mục tiêu</p>
                  <p className="mt-3 text-[14px] leading-6 text-[#564f49]">
                    {form.learningGoal.trim() || 'Bạn chưa thêm mục tiêu học tập cụ thể.'}
                  </p>
                </div>
              </div>
            </div>

            <div className="soft-panel p-7">
              <h2 className="page-section-title mb-4">Phạm vi đồng bộ</h2>
              <ul className="space-y-3 text-[14px] leading-6 text-[#5d5650]">
                <li>Lộ trình học tập sẽ dùng cấp độ và mục tiêu mới khi tạo lộ trình tiếp theo.</li>
                <li>Dashboard recommendation sẽ phản ánh hồ sơ học tập hiện tại của bạn.</li>
                <li>Trợ giảng AI sẽ dùng cấp độ này để gợi ý nội dung phù hợp hơn.</li>
              </ul>
            </div>
          </aside>
        </div>
      </div>
    </DashboardLayout>
  );
}
