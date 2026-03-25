import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import bunnyLogo from '../../assets/Elegant Sub-Logo Designs for Beauty Brands.jpg';
import illustrationLearning from '../../assets/tải xuống (1).jpg';
import type { SignUpRequest } from '../../types/auth';

export default function Signup() {
  const navigate = useNavigate();
  const [formData, setFormData] = useState<SignUpRequest>({
    fullName: '',
    email: '',
    password: '',
  });
  const [error, setError] = useState('');

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setFormData((prev) => ({
      ...prev,
      [name]: value,
    }));
  };

  const handleNext = (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    if (!formData.fullName.trim()) {
      setError('Vui lòng nhập tên của bạn');
      return;
    }
    if (!formData.email.trim()) {
      setError('Vui lòng nhập email');
      return;
    }
    if (!formData.password.trim()) {
      setError('Vui lòng nhập mật khẩu');
      return;
    }
    if (formData.password.length < 6) {
      setError('Mật khẩu phải có ít nhất 6 ký tự');
      return;
    }

    navigate('/signup-step2', { state: { formData } });
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[linear-gradient(180deg,#fbe7ef_0%,#f6d7e4_100%)] p-6">
      <div className="relative flex min-h-[800px] w-full max-w-[1253px] overflow-hidden rounded-[36px] border border-white/70 bg-[#fff9fd]/95 shadow-[0_28px_80px_rgba(114,62,83,0.16)]">
        <div className="flex w-[682px] flex-col items-center justify-center bg-[linear-gradient(180deg,#fff7fb_0%,#fce7f0_100%)] p-12">
          <div className="mb-8 h-[100px] w-[100px] overflow-hidden rounded-full">
            <img alt="Logo" className="h-full w-full object-cover" src={bunnyLogo} />
          </div>

          <div className="mb-8 flex gap-2">
            <div className="h-[4px] w-[10px] rounded-[2px] bg-[#5b1724]" />
            <div className="h-[4px] w-[10px] rounded-[2px] bg-[#de8fac]" />
          </div>

          <h1 className="mb-4 text-center text-[35px] font-semibold text-[#832e44]">Bắt đầu ngay</h1>

          <p className="mb-12 text-center text-[15px] text-[#832e44]">
            Tạo tài khoản để bắt đầu học theo lộ trình cá nhân hóa
          </p>

          <form onSubmit={handleNext} className="w-[396px] space-y-6">
            <div className="relative">
              <input
                type="text"
                name="fullName"
                value={formData.fullName}
                onChange={handleChange}
                placeholder="Tên"
                className="h-[35px] w-full rounded-[12px] border-none bg-white px-4 text-[13px] text-[#832e44] shadow-[0px_0px_4px_0px_rgba(253,171,181,0.2)] placeholder-[#e4b6d0] focus:outline-none focus:ring-2 focus:ring-[#832e44]"
                required
              />
            </div>

            <div className="relative">
              <input
                type="email"
                name="email"
                value={formData.email}
                onChange={handleChange}
                placeholder="Email"
                className="h-[35px] w-full rounded-[12px] border-none bg-white px-4 text-[13px] text-[#832e44] shadow-[0px_0px_4px_0px_rgba(253,171,181,0.2)] placeholder-[#e4b6d0] focus:outline-none focus:ring-2 focus:ring-[#832e44]"
                required
              />
            </div>

            <div className="relative">
              <input
                type="password"
                name="password"
                value={formData.password}
                onChange={handleChange}
                placeholder="Mật khẩu"
                className="h-[35px] w-full rounded-[12px] border-none bg-white px-4 text-[13px] text-[#832e44] shadow-[0px_0px_4px_0px_rgba(253,171,181,0.2)] placeholder-[#e4b6d0] focus:outline-none focus:ring-2 focus:ring-[#832e44]"
                required
              />
            </div>

            {error && <div className="text-center text-[12px] text-red-500">{error}</div>}

            <div className="flex justify-center pt-4">
              <button
                type="submit"
                className="h-[38px] w-full rounded-[14px] bg-[#5b1724] px-6 text-[13px] font-semibold text-[#f7d5e0] transition-colors duration-200 hover:bg-[#6d1f2e]"
              >
                Tiếp theo
              </button>
            </div>
          </form>

          <p className="mt-8 text-center text-[10px] text-[#832e44]">
            <span>Đã có tài khoản? </span>
            <button onClick={() => navigate('/login')} className="cursor-pointer font-bold hover:underline">
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
