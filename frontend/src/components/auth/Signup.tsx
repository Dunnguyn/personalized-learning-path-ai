import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import AuthShell from './AuthShell';
import AuthStepIndicator from './AuthStepIndicator';
import authHeroImage from '../../assets/tải xuống (1).jpg';
import type { SignUpRequest } from '../../types/auth';

const introVisual = <AuthStepIndicator activeStep={1} />;

export default function Signup() {
  const navigate = useNavigate();
  const [formData, setFormData] = useState<SignUpRequest>({
    fullName: '',
    email: '',
    password: '',
  });
  const [error, setError] = useState('');

  const handleChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = event.target;
    setFormData((previous) => ({
      ...previous,
      [name]: value,
    }));
  };

  const handleNext = (event: React.FormEvent) => {
    event.preventDefault();
    setError('');

    if (!formData.fullName.trim()) {
      setError('Vui lòng nhập tên của bạn.');
      return;
    }
    if (!formData.email.trim()) {
      setError('Vui lòng nhập email.');
      return;
    }
    if (!formData.password.trim()) {
      setError('Vui lòng nhập mật khẩu.');
      return;
    }
    if (formData.password.length < 6) {
      setError('Mật khẩu phải có ít nhất 6 ký tự.');
      return;
    }

    navigate('/signup-step2', { state: { formData } });
  };

  return (
    <AuthShell
      title="Bắt đầu ngay"
      description="Tạo tài khoản để bắt đầu hành trình học tập cá nhân hóa."
      mediaAlt="Minh họa học tập"
      mediaSrc={authHeroImage}
      sideLabel=""
      sideTitle=""
      sideCopy=""
      showSideContent={false}
      introVisual={introVisual}
      centerContent
      titleClassName="mt-7 text-[42px] font-semibold leading-[1.02] tracking-[-0.05em] text-[#8c3451] md:text-[46px]"
      descriptionClassName="text-[15px] leading-7 text-[#6d655f]"
      formShellClassName="mt-10 w-full max-w-[390px] border-0 bg-transparent p-0 shadow-none"
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
      <form onSubmit={handleNext} className="mx-auto flex w-full max-w-[390px] flex-col gap-4">
        <div>
          <label className="auth-label text-left">Tên</label>
          <input
            type="text"
            name="fullName"
            value={formData.fullName}
            onChange={handleChange}
            placeholder="Nguyễn Văn A"
            className="auth-input text-[15px]"
            required
          />
        </div>

        <div>
          <label className="auth-label text-left">Email</label>
          <input
            type="email"
            name="email"
            value={formData.email}
            onChange={handleChange}
            placeholder="you@example.com"
            className="auth-input text-[15px]"
            required
          />
        </div>

        <div>
          <label className="auth-label text-left">Mật khẩu</label>
          <input
            type="password"
            name="password"
            value={formData.password}
            onChange={handleChange}
            placeholder="Ít nhất 6 ký tự"
            className="auth-input text-[15px]"
            required
          />
        </div>

        {error ? (
          <div className="rounded-[18px] border border-red-200 bg-red-50 px-4 py-3 text-left text-[13px] text-red-700">
            {error}
          </div>
        ) : null}

        <div className="rounded-[18px] border border-[#efe1d6] bg-white/80 px-4 py-3 text-left text-[13px] text-[#6d655f]">
          Bước tiếp theo bạn sẽ chọn mục tiêu học tập và mức hiện tại để hệ thống cá nhân hóa trải nghiệm.
        </div>

        <button
          type="submit"
          className="theme-button mt-2 min-h-[54px] w-full justify-center text-[15px]"
        >
          Tiếp theo
        </button>
      </form>
    </AuthShell>
  );
}
