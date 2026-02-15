import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { authService } from '../../services/authService';

const imgElegantSubLogoDesignsForBeautyBrands1 = "https://www.figma.com/api/mcp/asset/07fc363a-2c60-4907-b8d9-9d9bbe95c03e";
const imgTiXung11 = "https://www.figma.com/api/mcp/asset/929a7953-0bc8-4ffb-8469-c95c81832d07";

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

          {/* Greeting Text */}
          <div className="text-center mb-6">
            <h1 className="text-[35px] font-semibold text-[#832e44] leading-tight">
              <div>Xin chào,</div>
              <div>Mừng bạn quay trở lại!</div>
            </h1>
          </div>

          {/* Subtitle */}
          <p className="text-[15px] text-[#832e44] mb-12 text-center">
            Đăng nhập tài khoản để tham gia học tập
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
                <span className="text-[#832e44]">Ghi nhớ?</span>
              </label>
              <a href="#" className="text-[#832e44] hover:underline">
                Quên mật khẩu?
              </a>
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
              className="w-[105px] h-[30px] mx-auto block bg-[#5b1724] text-[#cc8597] text-[12px] font-semibold rounded-[10px] hover:bg-[#6d1f2e] transition-colors duration-200"
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
