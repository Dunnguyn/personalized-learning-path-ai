import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import bunnyLogo from '../../assets/Elegant Sub-Logo Designs for Beauty Brands.jpg';
import illustrationLearning from '../../assets/tải xuống (1).jpg';

interface SignupFormData {
  fullName: string;
  email: string;
  password: string;
}

export default function Signup() {
  const navigate = useNavigate();
  const [formData, setFormData] = useState<SignupFormData>({
    fullName: '',
    email: '',
    password: '',
  });
  const [error, setError] = useState('');

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: value,
    }));
  };

  const handleNext = (e: React.FormEvent) => {
    e.preventDefault();
    setError('');

    // Validate all fields
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

    // Proceed to step 2 (goal & level selection)
    navigate('/signup-step2', { state: { formData } });
  };

  const handleBackToLogin = () => {
    navigate('/login');
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-[linear-gradient(180deg,#fbe7ef_0%,#f6d7e4_100%)] p-6">
      <div className="relative flex min-h-[800px] w-full max-w-[1253px] overflow-hidden rounded-[36px] border border-white/70 bg-[#fff9fd]/95 shadow-[0_28px_80px_rgba(114,62,83,0.16)]">
        {/* Left Side - Form */}
        <div className="flex w-[682px] flex-col items-center justify-center bg-[linear-gradient(180deg,#fff7fb_0%,#fce7f0_100%)] p-12">
          {/* Logo */}
          <div className="w-[100px] h-[100px] rounded-full mb-8 overflow-hidden">
            <img 
              alt="Logo" 
              className="w-full h-full object-cover" 
              src={bunnyLogo} 
            />
          </div>

          {/* Progress Indicators */}
          <div className="flex gap-2 mb-8">
            <div className="w-[10px] h-[4px] rounded-[2px] bg-[#5b1724]" />
            <div className="w-[10px] h-[4px] rounded-[2px] bg-[#de8fac]" />
          </div>

          {/* Heading */}
          <h1 className="text-[35px] font-semibold text-[#832e44] text-center mb-4">
            Bắt đầu ngay
          </h1>

          {/* Subtitle */}
          <p className="mb-12 text-center text-[15px] text-[#832e44]">
            Tạo tài khoản để bắt đầu học theo lộ trình cá nhân hóa
          </p>

          {/* Form */}
          <form onSubmit={handleNext} className="w-[396px] space-y-6">
            {/* Full Name */}
            <div className="relative">
              <input
                type="text"
                name="fullName"
                value={formData.fullName}
                onChange={handleChange}
                placeholder="Tên"
                className="w-full h-[35px] px-4 rounded-[12px] bg-white placeholder-[#e4b6d0] text-[#832e44] text-[13px] shadow-[0px_0px_4px_0px_rgba(253,171,181,0.2)] border-none focus:outline-none focus:ring-2 focus:ring-[#832e44]"
                required
              />
            </div>

            {/* Email */}
            <div className="relative">
              <input
                type="email"
                name="email"
                value={formData.email}
                onChange={handleChange}
                placeholder="Email"
                className="w-full h-[35px] px-4 rounded-[12px] bg-white placeholder-[#e4b6d0] text-[#832e44] text-[13px] shadow-[0px_0px_4px_0px_rgba(253,171,181,0.2)] border-none focus:outline-none focus:ring-2 focus:ring-[#832e44]"
                required
              />
            </div>

            {/* Password */}
            <div className="relative">
              <input
                type="password"
                name="password"
                value={formData.password}
                onChange={handleChange}
                placeholder="Mật khẩu"
                className="w-full h-[35px] px-4 rounded-[12px] bg-white placeholder-[#e4b6d0] text-[#832e44] text-[13px] shadow-[0px_0px_4px_0px_rgba(253,171,181,0.2)] border-none focus:outline-none focus:ring-2 focus:ring-[#832e44]"
                required
              />
            </div>

            {/* Error Message */}
            {error && (
              <div className="text-red-500 text-[12px] text-center">
                {error}
              </div>
            )}

            {/* Next Button */}
            <div className="flex justify-center pt-4">
              <button
                type="submit"
                className="h-[38px] w-full rounded-[14px] bg-[#5b1724] px-6 text-[13px] font-semibold text-[#f7d5e0] transition-colors duration-200 hover:bg-[#6d1f2e]"
              >
                Tiếp theo
              </button>
            </div>
          </form>

          {/* Login Link */}
          <p className="text-[10px] text-[#832e44] mt-8 text-center">
            <span>Đã có tài khoản? </span>
            <button
              onClick={handleBackToLogin}
              className="font-bold hover:underline cursor-pointer"
            >
              Đăng nhập
            </button>
          </p>
        </div>

        {/* Right Side - Illustration */}
        <div className="relative h-full w-[571px] overflow-hidden">
          <img 
            alt="Learning illustration" 
            className="w-full h-full object-cover" 
            src={illustrationLearning} 
          />
          <div className="absolute inset-0 bg-[linear-gradient(180deg,rgba(140,52,81,0.08)_0%,rgba(255,255,255,0)_45%,rgba(140,52,81,0.14)_100%)]" />
        </div>
      </div>
    </div>
  );
}
