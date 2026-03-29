import { useCallback, useEffect, useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import DashboardLayout from '../components/layout/DashboardLayout';
import { useAuth } from '../contexts/AuthContext';
import { analyticsService } from '../services/analyticsService';
import type { AdminDashboardMetrics } from '../types/analytics';

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
  no_data_message: 'Chưa có dữ liệu người dùng hoặc dữ liệu học tập để hiển thị.',
  updated_at: null,
};

const formatPercent = (value: number) => `${(Number(value || 0) * 100).toFixed(1)}%`;
const formatNumber = (value: number) => new Intl.NumberFormat('vi-VN').format(Number(value || 0));

const formatHours = (value: number) => {
  const safeValue = Number(value || 0);
  const decimals = safeValue >= 10 ? 0 : 1;
  return `${safeValue.toFixed(decimals).replace('.', ',')}h`;
};

const formatTimestamp = (value: string | null) => {
  if (!value) {
    return 'Chưa có dữ liệu';
  }

  const timestamp = new Date(value);
  if (Number.isNaN(timestamp.getTime())) {
    return 'Chưa có dữ liệu';
  }

  return new Intl.DateTimeFormat('vi-VN', {
    hour: '2-digit',
    minute: '2-digit',
    day: '2-digit',
    month: '2-digit',
  }).format(timestamp);
};

const getHealthStatus = (snapshot: AdminDashboardMetrics) => {
  const errorRate = Number(snapshot.api_error_rate || 0);
  const p95 = Number(snapshot.p95_latency_ms || 0);

  if (errorRate >= 0.1 || p95 >= 2500) {
    return {
      label: 'Cần chú ý',
      description: 'Độ trễ hoặc tỷ lệ lỗi đang cao. Nên kiểm tra log API và luồng request backend.',
      panelClass: 'border-rose-200 bg-rose-50',
      chipClass: 'bg-rose-100 text-rose-700',
      accentClass: 'text-rose-700',
    };
  }

  if (errorRate >= 0.03 || p95 >= 1200) {
    return {
      label: 'Ổn định',
      description: 'Hệ thống vẫn hoạt động tốt nhưng đã có dấu hiệu tăng tải cần theo dõi.',
      panelClass: 'border-amber-200 bg-amber-50',
      chipClass: 'bg-amber-100 text-amber-700',
      accentClass: 'text-amber-700',
    };
  }

  return {
    label: 'Tốt',
    description: 'Độ trễ và tỷ lệ lỗi đang ở mức an toàn cho dashboard admin.',
    panelClass: 'border-emerald-200 bg-emerald-50',
    chipClass: 'bg-emerald-100 text-emerald-700',
    accentClass: 'text-emerald-700',
  };
};

export default function AdminDashboard() {
  const { user } = useAuth();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<AdminDashboardMetrics>(emptySnapshot);

  const loadAdminData = useCallback(
    async (mode: 'initial' | 'refresh' = 'initial') => {
      try {
        if (mode === 'initial') {
          setLoading(true);
        } else {
          setRefreshing(true);
        }

        setError(null);
        const [adminSnapshot, studyHours] = await Promise.all([
          analyticsService.getAdminDashboard(),
          analyticsService.getAdminAverageStudyHours(),
        ]);

        setSnapshot({
          ...adminSnapshot,
          ...studyHours,
        });
      } catch (loadError) {
        console.error('Failed to load admin dashboard:', loadError);
        setError(loadError instanceof Error ? loadError.message : 'Khong the tai du lieu admin.');
      } finally {
        setLoading(false);
        setRefreshing(false);
      }
    },
    [],
  );

  useEffect(() => {
    if (!user) {
      navigate('/login');
      return;
    }

    if (user.role !== 'admin') {
      navigate('/dashboard');
      return;
    }

    void loadAdminData('initial');
  }, [loadAdminData, navigate, user]);

  const healthStatus = useMemo(() => getHealthStatus(snapshot), [snapshot]);
  const hasUserData = snapshot.has_user_data;

  const highlightCards = useMemo(
    () => [
      {
        title: 'Người dùng hoạt động (trong ngày)',
        value: hasUserData ? formatNumber(snapshot.dau) : 'Chưa có dữ liệu',
        caption: hasUserData
          ? 'Tổng số user có phát sinh hoạt động trong 24 giờ gần nhất.'
          : 'Sẽ hiển thị khi hệ thống bắt đầu ghi nhận hoạt động người dùng.',
        tone: 'pastel-pink',
      },
      {
        title: 'Người dùng hoạt động (trong tuần)',
        value: hasUserData ? formatNumber(snapshot.wau) : 'Chưa có dữ liệu',
        caption: hasUserData
          ? 'Số user quay lại trong 7 ngày gần đây.'
          : 'Chỉ số WAU sẽ có sau khi có lịch sử sử dụng trong tuần.',
        tone: 'pastel-yellow',
      },
      {
        title: 'Tỷ lệ tạo request thành công',
        value: hasUserData
          ? formatPercent(snapshot.learning_path_generation_success_rate)
          : 'Chưa có dữ liệu',
        caption: hasUserData
          ? 'Tỷ lệ backend tạo learning path thành công.'
          : 'Chỉ số này xuất hiện khi đã có request tạo learning path.',
        tone: 'pastel-purple',
      },
      {
        title: 'Trung bình số giờ học',
        value: hasUserData ? formatHours(snapshot.average_study_hours_per_user) : 'Chưa có dữ liệu',
        caption: hasUserData
          ? `Tổng ${formatNumber(snapshot.total_study_hours)} giờ / ${formatNumber(snapshot.user_count)} user.`
          : 'Chỉ số này sẽ tính từ lesson_study_time khi user bắt đầu học.',
        tone: 'pastel-mint',
      },
    ],
    [hasUserData, snapshot],
  );

  const latencyMetrics = useMemo(
    () => [
      {
        label: 'P50',
        value: `${formatNumber(snapshot.p50_latency_ms)} ms`,
      },
      {
        label: 'P95',
        value: `${formatNumber(snapshot.p95_latency_ms)} ms`,
      },
      {
        label: 'P99',
        value: `${formatNumber(snapshot.p99_latency_ms)} ms`,
      },
    ],
    [snapshot],
  );

  if (loading) {
    return (
      <DashboardLayout>
        <div className="page-shell">
          <div className="white-panel flex min-h-[360px] items-center justify-center">
            <div className="text-center">
              <div className="mx-auto mb-4 h-12 w-12 animate-spin rounded-full border-b-2 border-[#8c3451]" />
              <p className="text-[#8c3451]">Đang tải dashboard admin...</p>
            </div>
          </div>
        </div>
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout>
      <div className="page-shell max-w-[1140px]">
        {error && (
          <div className="white-panel mb-6 border border-red-200 px-5 py-4 text-[14px] text-red-700">
            {error}
          </div>
        )}

        {!hasUserData && !error && (
          <div className="white-panel mb-6 border border-amber-200 bg-amber-50/80 px-5 py-4">
            <p className="text-[14px] font-semibold text-amber-800">Chưa có dữ liệu vận hành</p>
            <p className="mt-1 text-[14px] leading-6 text-amber-900/80">
              {snapshot.no_data_message ||
                'Dashboard chưa ghi nhận user, learning path hoặc thời gian học. Các thẻ bên dưới sẽ chuyển sang số thật khi hệ thống có dữ liệu.'}
            </p>
          </div>
        )}

        <section className="soft-panel px-6 py-6 md:px-8 md:py-8">
          <div className="grid gap-5 xl:grid-cols-[minmax(0,1.9fr)_260px]">
            <div className="rounded-[30px] border border-white/50 bg-[linear-gradient(135deg,rgba(251,236,242,0.92),rgba(248,224,235,0.86))] px-6 py-6 md:px-7">
              <p className="page-kicker !mb-2">Admin workspace</p>
              <h1 className="max-w-[620px] text-[38px] font-medium leading-[1.02] tracking-[-0.05em] text-[#8c3451] md:text-[54px]">
                Trung tâm vận hành dành cho Admin
              </h1>
              <p className="mt-4 max-w-[680px] text-[14px] leading-6 text-[#5f5954] md:text-[15px]">
                Giao diện này tập trung vào sức khỏe hệ thống và các chỉ số vận hành cốt lõi:
                mức hoạt động của user, tỷ lệ tạo learning path thành công và nhịp học trung bình
                trên toàn bộ nền tảng.
              </p>
            </div>

            <div className="white-panel flex h-full flex-col justify-between p-5">
              <div>
                <p className="text-[11px] uppercase tracking-[0.18em] text-[#8c3451]/55">
                  Cập nhật gần đây nhất
                </p>
                <p className="mt-2 text-[30px] font-semibold tracking-[-0.04em] text-[#18141a]">
                  {formatTimestamp(snapshot.updated_at)}
                </p>
              </div>

              <div className={`mt-5 rounded-[20px] border px-4 py-4 ${healthStatus.panelClass}`}>
                <p className="text-[11px] uppercase tracking-[0.18em] text-[#8c3451]/55">
                  Tình trạng hệ thống
                </p>
                <p className={`mt-2 text-[20px] font-semibold ${healthStatus.accentClass}`}>
                  {healthStatus.label}
                </p>
              </div>

              <button
                type="button"
                onClick={() => void loadAdminData('refresh')}
                disabled={refreshing}
                className="theme-button-secondary mt-5 w-full disabled:opacity-60"
              >
                {refreshing ? 'Đang làm mới...' : 'Làm mới dữ liệu'}
              </button>
            </div>
          </div>
        </section>

        <section className="mt-6 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {highlightCards.map((card) => (
            <article key={card.title} className={`pastel-card ${card.tone} min-h-[152px] px-6 py-5`}>
              <p className="text-[11px] uppercase tracking-[0.14em] text-[#8c3451]/55">{card.title}</p>
              <p className="mt-5 text-[24px] font-semibold tracking-[-0.03em] text-[#17141a] md:text-[40px]">
                {card.value}
              </p>
              <p className="mt-3 text-[13px] leading-5 text-[#5f5954]">{card.caption}</p>
            </article>
          ))}
        </section>

        <section className={`mt-6 rounded-[30px] border p-6 md:p-7 ${healthStatus.panelClass}`}>
          <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <p className="text-[14px] font-medium text-[#5b544d]">Sức khỏe hệ thống</p>
              <h2 className={`mt-3 text-[34px] font-semibold tracking-[-0.04em] ${healthStatus.accentClass}`}>
                {healthStatus.label}
              </h2>
              <p className="mt-3 max-w-[560px] text-[14px] leading-6 text-[#5f5954]">
                {healthStatus.description}
              </p>
            </div>

            <span className={`inline-flex rounded-full px-4 py-2 text-[12px] font-semibold ${healthStatus.chipClass}`}>
              Error rate {formatPercent(snapshot.api_error_rate)}
            </span>
          </div>

          <div className="mt-6 grid gap-3 md:grid-cols-3">
            {latencyMetrics.map((item) => (
              <div
                key={item.label}
                className="rounded-[22px] border border-white/80 bg-white/80 px-4 py-4 shadow-[0_12px_28px_rgba(114,62,83,0.08)]"
              >
                <p className="text-[12px] uppercase tracking-[0.14em] text-[#8c3451]/55">{item.label}</p>
                <p className="mt-3 text-[24px] font-semibold tracking-[-0.03em] text-[#17141a]">
                  {item.value}
                </p>
              </div>
            ))}
          </div>
        </section>
      </div>
    </DashboardLayout>
  );
}
