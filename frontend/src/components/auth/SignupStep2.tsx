import React, { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { authService } from '../../services/authService';

const imgElegantSubLogoDesignsForBeautyBrands1 = "https://www.figma.com/api/mcp/asset/43e212e0-6b90-489d-84ed-da84b79b15f9";
const imgDownArrow = "https://www.figma.com/api/mcp/asset/7fd33db0-bb3d-4e02-9fd2-9795673c13e0";
const imgTiXung11 = "https://www.figma.com/api/mcp/asset/48695258-c92c-44ad-a2f3-53cd0740ad30";

interface SignupFormData {
  fullName: string;
  email: string;
  password: string;
}

interface Step2FormData {
  goal: string;
  level: string;
}

export default function SignupStep2() {
  const navigate = useNavigate();
  const location = useLocation();
  const formData = (location.state?.formData as SignupFormData) || {
    fullName: '',
    email: '',
    password: '',
  };

  const [step2Data, setStep2Data] = useState<Step2FormData>({
    goal: '',
    level: '',
  });
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  // Goal options
  const goalOptions = [
    'Cải thiện kỹ năng',
    'Học một ngôn ngữ mới',
    'Chuẩn bị thi cử',
    'Phát triển sự nghiệp',
  ];

  // Level options
  const levelOptions = [
    'Bước đầu',
    'Trung cấp',
    'Nâng cao',
  ];

  const handleChange = (field: 'goal' | 'level', value: string) => {
    setStep2Data(prev => ({
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
      const data = await authService.signup({
        email: formData.email,
        password: formData.password,
        fullName: formData.fullName,
      });

      localStorage.setItem('token', data.token);
      localStorage.setItem('userGoal', step2Data.goal);
      localStorage.setItem('userLevel', step2Data.level);

      navigate('/dashboard');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Có lỗi xảy ra');
    } finally {
      setLoading(false);
    }
  };

  const handleBack = () => {
    navigate('/signup');
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
            <div className="w-[10px] h-[4px] rounded-[2px] bg-[#de8fac]" />
            <div className="w-[10px] h-[4px] rounded-[2px] bg-[#5b1724]" />
          </div>

          {/* Heading */}
          <h1 className="text-[35px] font-semibold text-[#832e44] text-center mb-4">
            Bắt đầu ngay
          </h1>

          {/* Subtitle */}
          <p className="text-[15px] text-[#832e44] text-center mb-12">
            Chọn mục tiêu của bạn
          </p>

          {/* Form */}
          <form onSubmit={handleSubmit} className="w-[396px] space-y-6">
            {/* Goal Dropdown */}
            <div className="relative">
              <select
                value={step2Data.goal}
                onChange={(e) => handleChange('goal', e.target.value)}
                className="w-full h-[35px] px-4 rounded-[12px] bg-white text-[#e4b6d0] text-[13px] shadow-[0px_0px_4px_0px_rgba(253,171,181,0.2)] border-none focus:outline-none focus:ring-2 focus:ring-[#832e44] appearance-none cursor-pointer"
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
                className="absolute right-4 top-1/2 -translate-y-1/2 w-5 h-5 pointer-events-none" 
                src={imgDownArrow} 
              />
            </div>

            {/* Level Dropdown */}
            <div className="relative">
              <select
                value={step2Data.level}
                onChange={(e) => handleChange('level', e.target.value)}
                className="w-full h-[35px] px-4 rounded-[12px] bg-white text-[#e4b6d0] text-[13px] shadow-[0px_0px_4px_0px_rgba(253,171,181,0.2)] border-none focus:outline-none focus:ring-2 focus:ring-[#832e44] appearance-none cursor-pointer"
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
                className="absolute right-4 top-1/2 -translate-y-1/2 w-5 h-5 pointer-events-none" 
                src={imgDownArrow} 
              />
            </div>

            {/* Error Message */}
            {error && (
              <div className="text-red-500 text-[12px] text-center">
                {error}
              </div>
            )}

            {/* Submit Button */}
            <div className="flex justify-center pt-4">
              <button
                type="submit"
                disabled={loading}
                className="h-[30px] px-6 bg-[#5b1724] text-[#cc8597] text-[12px] font-semibold rounded-[10px] hover:bg-[#6d1f2e] transition-colors duration-200"
              >
                {loading ? 'Đang xử lý...' : 'Đăng ký'}
              </button>
            </div>
          </form>

          {/* Back Button */}
          <button
            onClick={handleBack}
            className="mt-4 text-[#832e44] text-[13px] hover:underline"
          >
            ← Quay lại
          </button>

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
