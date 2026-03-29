import React, { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import bunnyLogo from '../../assets/Elegant Sub-Logo Designs for Beauty Brands.jpg';
import illustrationLearning from '../../assets/tải xuống (1).jpg';
import { useAuth } from '../../contexts/AuthContext';
import { authService } from '../../services/authService';
import type { StoredUser } from '../../types/auth';

export default function Login() {
  const navigate = useNavigate();
  const { setUser } = useAuth();
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

      localStorage.setItem('token', data.access_token);

      let user: StoredUser = {
        user_id: data.user_id,
        email: data.email,
        name: data.name,
        role: data.role,
      };
      try {
        user = await authService.getCurrentUser();
      } catch (profileError) {
        console.warn('Could not load full profile after login:', profileError);
      }

      authService.setStoredUser(user);
      setUser({
        user_id: user.user_id || data.user_id,
        email: user.email,
        name: user.name,
        level: user.level || 'beginner',
        role: user.role || data.role,
      });

      if (rememberMe) {
        localStorage.setItem('email', email);
      } else {
        localStorage.removeItem('email');
      }

      navigate('/dashboard');
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Email hoặc mật khẩu không đúng');
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

          <div className="mb-6 text-center">
            <h1 className="text-[35px] font-semibold leading-tight text-[#832e44]">
              <div>Xin chào,</div>
              <div>Mừng bạn quay trở lại!</div>
            </h1>
          </div>

          <p className="mb-12 text-center text-[15px] text-[#832e44]">
            Đăng nhập để tiếp tục hành trình học tập cá nhân hóa
          </p>

          <form onSubmit={handleLogin} className="w-[396px] space-y-6">
            <div className="relative">
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="Email"
                className="h-[35px] w-full rounded-[12px] border-none bg-white px-4 text-[13px] text-[#832e44] shadow-[0px_0px_4px_0px_rgba(253,171,181,0.2)] placeholder-[#e4b6d0] focus:outline-none focus:ring-2 focus:ring-[#832e44]"
                required
              />
            </div>

            <div className="relative">
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Mật khẩu"
                className="h-[35px] w-full rounded-[12px] border-none bg-white px-4 text-[13px] text-[#832e44] shadow-[0px_0px_4px_0px_rgba(253,171,181,0.2)] placeholder-[#e4b6d0] focus:outline-none focus:ring-2 focus:ring-[#832e44]"
                required
              />
            </div>

            <div className="flex items-center justify-between text-[10px]">
              <label className="flex cursor-pointer items-center gap-2">
                <input
                  type="checkbox"
                  checked={rememberMe}
                  onChange={(e) => setRememberMe(e.target.checked)}
                  className="h-2 w-2 border border-[#832e44]"
                />
                <span className="text-[#832e44]">Ghi nhớ đăng nhập</span>
              </label>
              <button type="button" className="text-[#832e44] hover:underline">
                Quên mật khẩu?
              </button>
            </div>

            {error && <div className="text-center text-[12px] text-red-500">{error}</div>}

            <button
              type="submit"
              disabled={loading}
              className="mx-auto block h-[38px] w-full rounded-[14px] bg-[#5b1724] text-[13px] font-semibold text-[#f7d5e0] transition-colors duration-200 hover:bg-[#6d1f2e]"
            >
              {loading ? 'Đang xử lý...' : 'Đăng nhập'}
            </button>
          </form>

          <p className="mt-8 text-center text-[10px] text-[#832e44]">
            <span>Chưa có tài khoản? </span>
            <button
              onClick={() => navigate('/signup')}
              className="cursor-pointer font-bold hover:underline"
            >
              Đăng ký
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
