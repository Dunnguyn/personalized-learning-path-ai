import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { authService } from '../../services/authService';
import bunnyLogo from '../../assets/Elegant Sub-Logo Designs for Beauty Brands.jpg';
import illustrationLearning from '../../assets/tải xuống (1).jpg';

export default function Login() {
  const navigate = useNavigate();
  const [email, setEmail] = useState(authService.getStoredEmail() || '');
  const [password, setPassword] = useState('');
  const [rememberMe, setRememberMe] = useState(!!authService.getStoredEmail());
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');

  const handleLogin = async (e: React.FormEvent) => {
    e.preventDefault();
    setLoading(true);
    setError('');

    try {
      const data = await authService.login({ email, password });
      
      // Store token
      localStorage.setItem('token', data.access_token);
      
      // Store user info
      const user = {
        user_id: data.user_id,
        email: data.email,
        name: data.name
      };
      authService.setStoredUser(user);
      
      // Remember email if checked
      if (rememberMe) {
        localStorage.setItem('email', email);
      } else {
        localStorage.removeItem('email');
      }

      // Navigate to dashboard
      navigate('/dashboard');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Email hoặc mật khẩu không đúng');
    } finally {
      setLoading(false);
    }
  };

  const handleSignUp = () => {
    navigate('/signup');
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

          {/* Greeting Text */}
          <div className="text-center mb-6">
            <h1 className="text-[35px] font-semibold text-[#832e44] leading-tight">
              <div>Xin chào,</div>
              <div>Mừng bạn quay trở lại!</div>
            </h1>
          </div>

          {/* Subtitle */}
          <p className="mb-12 text-center text-[15px] text-[#832e44]">
            Đăng nhập để tiếp tục hành trình học tập cá nhân hóa
          </p>

          {/* Form */}
          <form onSubmit={handleLogin} className="w-[396px] space-y-6">
            {/* Email Input */}
            <div className="relative">
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Email"
                className="w-full h-[35px] px-4 rounded-[12px] bg-white placeholder-[#e4b6d0] text-[#832e44] text-[13px] shadow-[0px_0px_4px_0px_rgba(253,171,181,0.2)] border-none focus:outline-none focus:ring-2 focus:ring-[#832e44]"
                required
              />
            </div>

            {/* Password Input */}
            <div className="relative">
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Mật khẩu"
                className="w-full h-[35px] px-4 rounded-[12px] bg-white placeholder-[#e4b6d0] text-[#832e44] text-[13px] shadow-[0px_0px_4px_0px_rgba(253,171,181,0.2)] border-none focus:outline-none focus:ring-2 focus:ring-[#832e44]"
                required
              />
            </div>

            {/* Remember Me & Forgot Password */}
            <div className="flex justify-between items-center text-[10px]">
              <label className="flex items-center gap-2 cursor-pointer">
                <input
                  type="checkbox"
                  checked={rememberMe}
                  onChange={(e) => setRememberMe(e.target.checked)}
                  className="w-2 h-2 border border-[#832e44]"
                />
                <span className="text-[#832e44]">Ghi nhớ đăng nhập</span>
              </label>
              <button type="button" className="text-[#832e44] hover:underline">
                Quên mật khẩu?
              </button>
            </div>

            {/* Error Message */}
            {error && (
              <div className="text-red-500 text-[12px] text-center">
                {error}
              </div>
            )}

            {/* Login Button */}
            <button
              type="submit"
              disabled={loading}
              className="mx-auto block h-[38px] w-full rounded-[14px] bg-[#5b1724] text-[13px] font-semibold text-[#f7d5e0] transition-colors duration-200 hover:bg-[#6d1f2e]"
            >
              {loading ? 'Đang xử lý...' : 'Đăng nhập'}
            </button>
          </form>

          {/* Sign Up Link */}
          <p className="text-[10px] text-[#832e44] mt-8 text-center">
            <span>Chưa có tài khoản? </span>
            <button
              onClick={handleSignUp}
              className="font-bold hover:underline cursor-pointer"
            >
              Đăng ký
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
