import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import AuthShell from './AuthShell';
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

  const handleLogin = async (event: React.FormEvent) => {
    event.preventDefault();
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
        learning_goal: user.learning_goal,
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
    <AuthShell
      title="Quay lại nhịp học đang dang dở."
      description="Đăng nhập để tiếp tục lộ trình cá nhân hóa, xem tài nguyên phù hợp và hỏi AI Tutor trong đúng ngữ cảnh học tập hiện tại."
      mediaAlt="Minh họa học tập"
      mediaSrc={illustrationLearning}
      sideLabel="Điểm nổi bật"
      sideTitle="Một nơi để theo dõi cả tiến độ lẫn quyết định học tiếp theo."
      sideCopy="Từ dashboard đến AI Tutor, mọi gợi ý đều bám theo mục tiêu và mức độ hiện tại của bạn thay vì đưa ra nội dung chung chung."
      showSideContent={false}
      footer={
        <p>
          Chưa có tài khoản?{' '}
          <button onClick={() => navigate('/signup')} className="font-semibold text-[#8c3451] hover:underline">
            Tạo tài khoản mới
          </button>
        </p>
      }
    >
      <form onSubmit={handleLogin} className="space-y-5">
        <div>
          <label className="auth-label">Email</label>
          <input
            type="email"
            value={email}
            onChange={(event) => setEmail(event.target.value)}
            placeholder="you@example.com"
            className="auth-input"
            required
          />
        </div>

        <div>
          <label className="auth-label">Mật khẩu</label>
          <input
            type="password"
            value={password}
            onChange={(event) => setPassword(event.target.value)}
            placeholder="Nhập mật khẩu của bạn"
            className="auth-input"
            required
          />
        </div>

        <div className="flex flex-col gap-3 text-[13px] text-[#6d655f] sm:flex-row sm:items-center sm:justify-between">
          <label className="flex cursor-pointer items-center gap-3">
            <input
              type="checkbox"
              checked={rememberMe}
              onChange={(event) => setRememberMe(event.target.checked)}
              className="h-4 w-4 rounded border-[#cdb6bf] text-[#8c3451] focus:ring-[#8c3451]"
            />
            <span>Ghi nhớ email cho lần đăng nhập tiếp theo</span>
          </label>
          <button type="button" className="text-left font-medium text-[#8c3451] hover:underline sm:text-right">
            Quên mật khẩu?
          </button>
        </div>

        {error ? (
          <div className="rounded-[18px] border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700">
            {error}
          </div>
        ) : null}

        <button
          type="submit"
          disabled={loading}
          className="theme-button min-h-[54px] w-full justify-center text-[15px] disabled:cursor-not-allowed disabled:opacity-60"
        >
          {loading ? 'Đang xử lý...' : 'Đăng nhập'}
        </button>
      </form>
    </AuthShell>
  );
}
