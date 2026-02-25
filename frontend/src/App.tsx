import { BrowserRouter as Router, Routes, Route, Navigate } from 'react-router-dom'
import { AuthProvider } from './contexts/AuthContext'
import Login from './components/auth/Login'
import Signup from './components/auth/Signup'
import SignupStep2 from './components/auth/SignupStep2'
import Dashboard from './pages/Dashboard'
import LearningPath from './pages/LearningPath'
import LearningPathDetail from './pages/LearningPathDetail'
import Resources from './pages/Resources'
import AITutor from './pages/AITutor'
import Settings from './pages/Settings'
import DebugToken from './pages/DebugToken'
import RagSimple from './pages/RagSimple'

function App() {
  return (
    <AuthProvider>
      <Router>
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
          <Route path="/rag" element={<RagSimple />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/debug-token" element={<DebugToken />} />
          {/* Add more routes here as you develop */}
        </Routes>
      </Router>
    </AuthProvider>
  )
}

export default App
