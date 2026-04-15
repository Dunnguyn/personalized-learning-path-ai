import { Suspense, lazy } from 'react';
import { BrowserRouter as Router, Navigate, Route, Routes } from 'react-router-dom';
import { AuthProvider } from './contexts/AuthContext';

const Login = lazy(() => import('./components/auth/Login'));
const Signup = lazy(() => import('./components/auth/Signup'));
const SignupStep2 = lazy(() => import('./components/auth/SignupStep2'));
const Dashboard = lazy(() => import('./pages/Dashboard'));
const LearningPath = lazy(() => import('./pages/LearningPath'));
const LearningPathDetail = lazy(() => import('./pages/LearningPathDetail'));
const Resources = lazy(() => import('./pages/Resources'));
const AITutor = lazy(() => import('./pages/AITutor'));
const Settings = lazy(() => import('./pages/Settings'));
const DebugToken = lazy(() => import('./pages/DebugToken'));

function App() {
  return (
    <AuthProvider>
      <Router>
        <Suspense
          fallback={
            <div className="flex min-h-screen items-center justify-center bg-[linear-gradient(180deg,#fcf4ec_0%,#f3e5d5_100%)] px-4 text-center">
              <div className="rounded-[28px] border border-white/70 bg-white/80 px-8 py-6 text-[15px] font-semibold text-[#8c3451] shadow-[0_24px_56px_rgba(92,62,46,0.12)] backdrop-blur-md">
                Loading workspace...
              </div>
            </div>
          }
        >
          <Routes>
            <Route path="/" element={<Navigate to="/login" replace />} />
            <Route path="/login" element={<Login />} />
            <Route path="/signup" element={<Signup />} />
            <Route path="/signup-step2" element={<SignupStep2 />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/learning-path" element={<LearningPath />} />
            <Route path="/learning-path/:pathId" element={<LearningPathDetail />} />
            <Route path="/resources" element={<Resources />} />
            <Route path="/ai-tutor" element={<AITutor />} />
            <Route path="/settings" element={<Settings />} />
            <Route path="/debug-token" element={<DebugToken />} />
          </Routes>
        </Suspense>
      </Router>
    </AuthProvider>
  );
}

export default App;
