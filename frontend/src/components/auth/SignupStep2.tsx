import React, { useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import bunnyLogo from '../../assets/Elegant Sub-Logo Designs for Beauty Brands.jpg';
import iconDropdown from '../../assets/down-arrow.png';
import illustrationLearning from '../../assets/tải xuống (1).jpg';
import { authService } from '../../services/authService';
import type { SignUpRequest, SignupStep2FormData } from '../../types/auth';

export default function SignupStep2() {
  const navigate = useNavigate();
  const location = useLocation();
  const formData = (location.state?.formData as SignUpRequest) || {
    fullName: '',
    email: '',
    password: '',
  };

  const [step2Data, setStep2Data] = useState<SignupStep2FormData>({
    goal: '',
    level: '',
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const goalOptions = [
    'Cải thiện kỹ năng',
    'Học một ngôn ngữ mới',
    'Chuẩn bị thi cử',
    'Phát triển sự nghiệp',
  ];

  const levelOptions = ['Bước đầu', 'Trung cấp', 'Nâng cao'];

  const handleChange = (field: 'goal' | 'level', value: string) => {
    setStep2Data((prev) => ({
      ...prev,
      [field]: value,
    }));
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!step2Data.goal.trim()) {
      setError('Vui lòng chọn mục tiêu');
      return;
    }
    if (!step2Data.level.trim()) {
      setError('Vui lòng chọn cấp độ hiện tại');
      return;
    }

    setLoading(true);

    try {
      const signupData = await authService.signup({
        email: formData.email,
        password: formData.password,
        fullName: formData.fullName,
      });

      localStorage.setItem('token', signupData.token);
      authService.setStoredUser(signupData.user);

      const levelMap: Record<string, string> = {
        'Bước đầu': 'beginner',
        'Trung cấp': 'intermediate',
        'Nâng cao': 'advanced',
      };
      const englishLevel = levelMap[step2Data.level] || 'beginner';

      try {
        await new Promise((resolve) => setTimeout(resolve, 100));
        await authService.updateUserLevel({
          user_id: signupData.user.user_id,
          level: englishLevel,
          learning_goal: step2Data.goal,
        });

        authService.setStoredUser({
          ...signupData.user,
          level: englishLevel,
        });
      } catch (updateErr) {
        console.error('Failed to update user level:', updateErr);
      }

      localStorage.setItem('userGoal', step2Data.goal);
      window.location.href = '/dashboard';
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Có lỗi xảy ra. Vui lòng thử lại.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[linear-gradient(180deg,#fbe7ef_0%,#f6d7e4_100%)] p-6">
      <div className="relative flex min-h-[800px] w-full max-w-[1253px] overflow-hidden rounded-[36px] border border-white/70 bg-[#fff9fd]/95 shadow-[0_28px_80px_rgba(114,62,83,0.16)]">
        <div className="flex w-[682px] flex-col items-center justify-center bg-[linear-gradient(180deg,#fff7fb_0%,#fce7f0_100%)] p-12">
          <div className="mb-8 h-[100px] w-[100px] overflow-hidden rounded-full">
            <img alt="Logo" className="h-full w-full object-cover" src={bunnyLogo} />
          </div>

          <div className="mb-8 flex gap-2">
            <div className="h-[4px] w-[10px] rounded-[2px] bg-[#de8fac]" />
            <div className="h-[4px] w-[10px] rounded-[2px] bg-[#5b1724]" />
          </div>

          <h1 className="mb-4 text-center text-[35px] font-semibold text-[#832e44]">
            Bắt đầu ngay
          </h1>

          <p className="mb-12 text-center text-[15px] text-[#832e44]">Chọn mục tiêu của bạn</p>

          <form onSubmit={handleSubmit} className="w-[396px] space-y-6">
            <div className="relative">
              <select
                value={step2Data.goal}
                onChange={(e) => handleChange('goal', e.target.value)}
                className="h-[35px] w-full cursor-pointer appearance-none rounded-[12px] border-none bg-white px-4 text-[13px] text-[#e4b6d0] shadow-[0px_0px_4px_0px_rgba(253,171,181,0.2)] focus:outline-none focus:ring-2 focus:ring-[#832e44]"
              >
                <option value="">Mục tiêu</option>
                {goalOptions.map((opt) => (
                  <option key={opt} value={opt} className="text-[#832e44]">
                    {opt}
                  </option>
                ))}
              </select>
              <img
                alt=""
                className="pointer-events-none absolute right-4 top-1/2 h-5 w-5 -translate-y-1/2"
                src={iconDropdown}
              />
            </div>

            <div className="relative">
              <select
                value={step2Data.level}
                onChange={(e) => handleChange('level', e.target.value)}
                className="h-[35px] w-full cursor-pointer appearance-none rounded-[12px] border-none bg-white px-4 text-[13px] text-[#e4b6d0] shadow-[0px_0px_4px_0px_rgba(253,171,181,0.2)] focus:outline-none focus:ring-2 focus:ring-[#832e44]"
              >
                <option value="">Cấp độ hiện tại</option>
                {levelOptions.map((opt) => (
                  <option key={opt} value={opt} className="text-[#832e44]">
                    {opt}
                  </option>
                ))}
              </select>
              <img
                alt=""
                className="pointer-events-none absolute right-4 top-1/2 h-5 w-5 -translate-y-1/2"
                src={iconDropdown}
              />
            </div>

            {error && <div className="text-center text-[12px] text-red-500">{error}</div>}

            <div className="flex justify-center pt-4">
              <button
                type="submit"
                disabled={loading}
                className="h-[38px] w-full rounded-[14px] bg-[#5b1724] px-6 text-[13px] font-semibold text-[#f7d5e0] transition-colors duration-200 hover:bg-[#6d1f2e]"
              >
                {loading ? 'Đang xử lý...' : 'Đăng ký'}
              </button>
            </div>
          </form>

          <button
            onClick={() => navigate('/signup')}
            className="mt-4 text-[13px] text-[#832e44] hover:underline"
          >
            ← Quay lại
          </button>

          <p className="mt-8 text-center text-[10px] text-[#832e44]">
            <span>Đã có tài khoản? </span>
            <button
              onClick={() => navigate('/login')}
              className="cursor-pointer font-bold hover:underline"
            >
              Đăng nhập
            </button>
          </p>
        </div>

        <div className="relative h-full w-[571px] overflow-hidden">
          <img
            alt="Learning illustration"
            className="h-full w-full object-cover"
            src={illustrationLearning}
          />
          <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(140,52,81,0.08)_0%,rgba(255,255,255,0)_45%,rgba(140,52,81,0.14)_100%)]" />
        </div>
      </div>
    </div>
  );
}
