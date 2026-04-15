import { useEffect, useMemo, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import AuthShell from './AuthShell';
import illustrationLearning from '../../assets/tải xuống (1).jpg';
import { brandLogo } from '../../assets';
import { useAuth } from '../../contexts/AuthContext';
import { authService } from '../../services/authService';
import { learnerProfileService } from '../../services/learnerProfileService';
import type { SignUpRequest } from '../../types/auth';
import type { LearnerLevel, SubjectId } from '../../types/learnerProfile';

type GoalOption = {
  value: SubjectId;
  label: string;
  learningGoal: string;
  outcome: string;
};

const GOAL_OPTIONS: GoalOption[] = [
  {
    value: 'python',
    label: 'Học lập trình Python',
    learningGoal: 'Học lập trình Python',
    outcome: 'Nắm nền tảng Python và bắt đầu học theo lộ trình cá nhân hóa.',
  },
  {
    value: 'web',
    label: 'Phát triển web',
    learningGoal: 'Học phát triển web',
    outcome: 'Xây nền tảng HTML, CSS, JavaScript và học theo lộ trình web rõ ràng.',
  },
  {
    value: 'java',
    label: 'Lập trình Java',
    learningGoal: 'Học lập trình Java',
    outcome: 'Nắm nền tảng Java để đi tiếp sang ứng dụng thực tế.',
  },
  {
    value: 'cpp',
    label: 'Lập trình C++',
    learningGoal: 'Học lập trình C++',
    outcome: 'Xây chắc nền tảng C++ với nhịp học phù hợp trình độ hiện tại.',
  },
  {
    value: 'csharp',
    label: 'Lập trình C#',
    learningGoal: 'Học lập trình C#',
    outcome: 'Bắt đầu lộ trình C# có cấu trúc và bám sát mục tiêu học tập.',
  },
];

const LEVEL_OPTIONS: Array<{ value: LearnerLevel; label: string }> = [
  { value: 'beginner', label: 'Mới bắt đầu' },
  { value: 'intermediate', label: 'Đã có nền tảng' },
  { value: 'advanced', label: 'Muốn học chuyên sâu' },
];

const introVisual = (
  <div className="flex flex-col items-center">
    <div className="flex h-18 w-18 items-center justify-center rounded-full bg-[#fff4f8] shadow-[0_14px_32px_rgba(162,94,121,0.12)]">
      <img src={brandLogo} alt="Learning brand" className="h-11 w-11 rounded-full object-cover" />
    </div>
    <div className="mt-4 text-[14px] font-semibold tracking-[0.38em] text-[#8c3451]/56">02</div>
  </div>
);

export default function SignupStep2() {
  const navigate = useNavigate();
  const location = useLocation();
  const { setUser } = useAuth();
  const formData = (location.state?.formData as SignUpRequest) || {
    fullName: '',
    email: '',
    password: '',
  };

  const [selectedGoal, setSelectedGoal] = useState<SubjectId>('python');
  const [level, setLevel] = useState<LearnerLevel>('beginner');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  useEffect(() => {
    if (!formData.email || !formData.password || !formData.fullName) {
      navigate('/signup', { replace: true });
    }
  }, [formData.email, formData.fullName, formData.password, navigate]);

  const goalMeta = useMemo(
    () => GOAL_OPTIONS.find((option) => option.value === selectedGoal) || GOAL_OPTIONS[0],
    [selectedGoal],
  );

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');
    setLoading(true);

    try {
      const signupData = await authService.signup({
        email: formData.email,
        password: formData.password,
        fullName: formData.fullName,
      });

      localStorage.setItem('token', signupData.token);

      await learnerProfileService.updateMyProfile({
        level,
        learning_goal: goalMeta.learningGoal,
        target_outcome: goalMeta.outcome,
        time_budget: {
          value: 300,
          unit: 'weekly',
        },
        preferred_resource_type: 'mixed',
        learning_pace: 'steady',
        prior_knowledge_by_subject: {
          [goalMeta.value]: level,
        },
      });

      const currentUser = await authService.getCurrentUser();
      authService.setStoredUser(currentUser);
      setUser({
        user_id: currentUser.user_id || signupData.user.user_id,
        email: currentUser.email,
        name: currentUser.name,
        level: currentUser.level || level,
        role: currentUser.role || signupData.user.role,
        learning_goal: currentUser.learning_goal || goalMeta.learningGoal,
      });

      navigate('/dashboard');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể hoàn tất đăng ký.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell
      badge="Thiết lập hồ sơ"
      title="Bắt đầu ngay"
      description="Chọn mục tiêu của bạn để hệ thống tạo điểm khởi đầu phù hợp."
      mediaAlt="Minh họa học tập"
      mediaSrc={illustrationLearning}
      sideLabel=""
      sideTitle=""
      sideCopy=""
      showSideContent={false}
      introVisual={introVisual}
      centerContent
      titleClassName="mt-2 text-[42px] font-semibold leading-[1.02] tracking-[-0.05em] text-[#8c3451] md:text-[46px]"
      descriptionClassName="text-[14px] leading-6 text-[#6d655f]"
      formShellClassName="mt-8 w-full max-w-[410px] border-0 bg-transparent p-0 shadow-none"
      footerClassName="text-[13px] text-[#6d655f]"
      footer={
        <p>
          Đã có tài khoản?{' '}
          <button type="button" onClick={() => navigate('/login')} className="font-semibold text-[#8c3451] hover:underline">
            Đăng nhập
          </button>
        </p>
      }
    >
      <form onSubmit={handleSubmit} className="mx-auto flex w-full max-w-[410px] flex-col gap-4">
        <div>
          <label className="auth-label text-left">Mục tiêu</label>
          <select
            value={selectedGoal}
            onChange={(event) => setSelectedGoal(event.target.value as SubjectId)}
            className="auth-input text-[15px]"
          >
            {GOAL_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        <div>
          <label className="auth-label text-left">Cấp độ hiện tại</label>
          <select
            value={level}
            onChange={(event) => setLevel(event.target.value as LearnerLevel)}
            className="auth-input text-[15px]"
          >
            {LEVEL_OPTIONS.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </div>

        {error ? (
          <div className="rounded-[18px] border border-red-200 bg-red-50 px-4 py-3 text-left text-[13px] text-red-700">
            {error}
          </div>
        ) : null}

        <div className="rounded-[18px] border border-[#efe1d6] bg-white/80 px-4 py-3 text-left text-[13px] text-[#6d655f]">
          Hệ thống sẽ dùng mục tiêu và mức hiện tại để cá nhân hóa lộ trình học đầu tiên của bạn.
        </div>

        <button
          type="submit"
          disabled={loading}
          className="theme-button mt-2 min-h-[54px] w-full justify-center text-[15px] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading ? 'Đang đăng ký...' : 'Đăng ký'}
        </button>
      </form>
    </AuthShell>
  );
}
