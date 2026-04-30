import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import AuthShell from './AuthShell';
import { learningJourneyIcon as authHeroImage } from '../../assets';
import { authService } from '../../services/authService';

export default function ForgotPassword() {
  const navigate = useNavigate();
  const allowDirectReset = import.meta.env.VITE_ENABLE_INSECURE_DIRECT_PASSWORD_RESET === 'true';
  const [email, setEmail] = useState(authService.getStoredEmail() || '');
  const [password, setPassword] = useState('');
  const [confirmPassword, setConfirmPassword] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [submitted, setSubmitted] = useState(false);
  const [message, setMessage] = useState('');

  const handleSubmit = async (event: React.FormEvent) => {
    event.preventDefault();
    setError('');

    if (password.length < 6) {
      setError('Máº­t kháº©u má»›i pháº£i cÃ³ Ã­t nháº¥t 6 kÃ½ tá»±.');
      return;
    }

    if (password !== confirmPassword) {
      setError('Máº­t kháº©u xÃ¡c nháº­n khÃ´ng khá»›p.');
      return;
    }

    setLoading(true);
    try {
      const response = await authService.requestPasswordReset({
        email,
        new_password: password,
      });
      localStorage.removeItem('token');
      localStorage.removeItem('user');
      setMessage(response.message);
      setSubmitted(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'KhÃ´ng thá»ƒ Ä‘áº·t láº¡i máº­t kháº©u');
    } finally {
      setLoading(false);
    }
  };

  return (
    <AuthShell
      title="Äáº·t láº¡i máº­t kháº©u"
      description={
        allowDirectReset
          ? 'Luá»“ng reset nhanh nÃ y chá»‰ nÃªn dÃ¹ng cho local demo. Triá»ƒn khai cÃ´ng khai cáº§n má»™t quy trÃ¬nh reset qua email Ä‘Ã£ xÃ¡c minh.'
          : 'Báº£n public release táº¯t luá»“ng reset trá»±c tiáº¿p qua email Ä‘á»ƒ trÃ¡nh chiáº¿m quyá»n tÃ i khoáº£n. HÃ£y triá»ƒn khai reset token qua email hoáº·c liÃªn há»‡ admin há»‡ thá»‘ng.'
      }
      mediaAlt="Há»c táº­p cÃ¡ nhÃ¢n hÃ³a"
      mediaSrc={authHeroImage}
      sideLabel="LÆ°u Ã½"
      sideTitle={
        allowDirectReset
          ? 'Cháº¿ Ä‘á»™ demo khÃ´ng an toÃ n cho production.'
          : 'Cáº§n má»™t luá»“ng reset cÃ³ xÃ¡c minh danh tÃ­nh.'
      }
      sideCopy={
        allowDirectReset
          ? 'Báº¥t ká»³ ai biáº¿t email Ä‘Ã£ Ä‘Äƒng kÃ½ Ä‘á»u cÃ³ thá»ƒ Ä‘á»•i máº­t kháº©u. Chá»‰ báº­t tÃ¹y chá»n nÃ y trong mÃ´i trÆ°á»ng demo cÃ¡ch ly.'
          : 'MÃ n hÃ¬nh nÃ y Ä‘Æ°á»£c giá»¯ láº¡i Ä‘á»ƒ nháº¯c ngÆ°á»i triá»ƒn khai vá» yÃªu cáº§u báº£o máº­t. Khuyáº¿n nghá»‹ dÃ¹ng token reset cÃ³ háº¡n vÃ  email xÃ¡c minh.'
      }
      showSideContent={false}
      formShellClassName="mt-8 w-full max-w-[430px]"
      footer={
        <p>
          Nhá»› ra máº­t kháº©u?{' '}
          <button
            type="button"
            onClick={() => navigate('/login')}
            className="font-semibold text-[#8c3451] hover:underline"
          >
            Quay láº¡i Ä‘Äƒng nháº­p
          </button>
        </p>
      }
    >
      {!allowDirectReset ? (
        <div className="space-y-4">
          <div className="rounded-[22px] border border-amber-200 bg-amber-50 px-5 py-5 text-[14px] leading-7 text-amber-900">
            <p className="font-semibold">Self-service reset is disabled in this release build.</p>
            <p className="mt-2">
              Set <code>ALLOW_INSECURE_EMAIL_ONLY_PASSWORD_RESET=true</code> in the backend and{' '}
              <code>VITE_ENABLE_INSECURE_DIRECT_PASSWORD_RESET=true</code> in the frontend only
              for a local demo.
            </p>
          </div>

          <button
            type="button"
            onClick={() => navigate('/login')}
            className="theme-button min-h-[50px] px-6"
          >
            Quay láº¡i Ä‘Äƒng nháº­p
          </button>
        </div>
      ) : submitted ? (
        <div className="space-y-4">
          <div className="rounded-[22px] border border-[#ead7df] bg-white/90 px-5 py-5 text-[14px] leading-7 text-[#5f545b]">
            <p className="font-semibold text-[#8c3451]">Máº­t kháº©u Ä‘Ã£ Ä‘Æ°á»£c cáº­p nháº­t.</p>
            <p className="mt-2">{message || 'Báº¡n cÃ³ thá»ƒ Ä‘Äƒng nháº­p láº¡i báº±ng máº­t kháº©u má»›i.'}</p>
          </div>

          <div className="flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => navigate('/login')}
              className="theme-button min-h-[50px] px-6"
            >
              ÄÄƒng nháº­p ngay
            </button>
            <button
              type="button"
              onClick={() => {
                setSubmitted(false);
                setPassword('');
                setConfirmPassword('');
                setMessage('');
              }}
              className="theme-button-secondary min-h-[50px] px-6"
            >
              Äáº·t láº¡i láº§n ná»¯a
            </button>
          </div>
        </div>
      ) : (
        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="rounded-[18px] border border-amber-200 bg-amber-50 px-4 py-3 text-[13px] text-amber-900">
            Demo-only flow. Do not enable this in a public deployment without verified reset
            tokens.
          </div>

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
            <label className="auth-label">Máº­t kháº©u má»›i</label>
            <input
              type="password"
              value={password}
              onChange={(event) => setPassword(event.target.value)}
              placeholder="Ãt nháº¥t 6 kÃ½ tá»±"
              className="auth-input"
              required
            />
          </div>

          <div>
            <label className="auth-label">XÃ¡c nháº­n máº­t kháº©u má»›i</label>
            <input
              type="password"
              value={confirmPassword}
              onChange={(event) => setConfirmPassword(event.target.value)}
              placeholder="Nháº­p láº¡i máº­t kháº©u má»›i"
              className="auth-input"
              required
            />
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
            {loading ? 'Äang cáº­p nháº­t...' : 'Cáº­p nháº­t máº­t kháº©u'}
          </button>
        </form>
      )}
    </AuthShell>
  );
}
