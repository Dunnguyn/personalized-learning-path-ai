import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';

const imgElegantSubLogoDesignsForBeautyBrands1 = "https://www.figma.com/api/mcp/asset/b9f53a19-9c58-41bc-a927-b3c36a787a5d";
const imgTiXung11 = "https://www.figma.com/api/mcp/asset/74bb8a67-994b-40d2-9369-9f290e40e751";

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
    <div className="bg-[#fafafa] relative w-full h-screen flex items-center justify-center">
      <div className="bg-[#f7dfed] h-[800px] rounded-[30px] w-[1253px] relative shadow-lg overflow-hidden flex">
        {/* Left Side - Form */}
        <div className="w-[682px] flex flex-col items-center justify-center p-12">
          {/* Logo */}
          <div className="w-[100px] h-[100px] rounded-full mb-8 overflow-hidden">
            <img 
              alt="Logo" 
              className="w-full h-full object-cover" 
              src={imgElegantSubLogoDesignsForBeautyBrands1} 
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
          <p className="text-[15px] text-[#832e44] text-center mb-12">
            Tạo tài khoản của bạn để bắt đầu!
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
                className="h-[30px] px-6 bg-[#5b1724] text-[#cc8597] text-[12px] font-semibold rounded-[10px] hover:bg-[#6d1f2e] transition-colors duration-200"
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
        <div className="w-[571px] h-full overflow-hidden">
          <img 
            alt="Learning illustration" 
            className="w-full h-full object-cover" 
            src={imgTiXung11} 
          />
        </div>
      </div>
    </div>
  );
}
