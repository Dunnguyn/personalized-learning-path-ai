import { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useNavigate, useSearchParams } from 'react-router-dom';
import DashboardLayout from '../components/layout/DashboardLayout';
import { useAuth } from '../contexts/AuthContext';
import { apiClient } from '../utils/apiClient';
import { SUBJECTS } from '../utils/subjects';
import { assessmentService, type AssessmentQuestion, type AssessmentDifficulty } from '../services/assessmentService';

interface Message {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  timestamp: Date;
  answer?: {
    answer_text: string;
    sources: Array<{
      title: string;
      url?: string;
      type?: string;
    }>;
    confidence: number;
    latency_ms: number;
  };
  conceptDetected?: {
    concept_id: number;
    concept_name: string;
    score: number;
  };
  learning_path?: Array<{
    concept_id: number;
    concept_name: string;
    order: number;
    status: string;
  }>;
  adaptive_info?: {
    mode: string;
    difficulty_boost: number;
    practice_recommendations: string[];
  };
}

interface ConceptInfo {
  concept_id: number;
  concept_name: string;
  description: string;
  mastery: number;
  status: string;
}

interface HistoryItem {
  _id: string;
  question: string;
  answer: string;
  goal: string;
  level: string;
  concept_name?: string;
  confidence: number;
  timestamp: string;
}

interface AssessmentDraft {
  concept: string;
  difficulty: AssessmentDifficulty;
  num_questions: number;
  chapter_content: string;
}

type StoredMessage = Omit<Message, 'timestamp'> & { timestamp: string };

const buildStorageKey = (userId: string, subjectKey: string, goalKey: string) => {
  const safeSubject = encodeURIComponent(subjectKey || 'unknown');
  const safeGoal = encodeURIComponent(goalKey.trim() || 'default');
  return `aitutor_history_${userId}_${safeSubject}_${safeGoal}`;
};

const loadStoredMessages = (userId: string, subjectKey: string, goalKey: string) => {
  try {
    const raw = localStorage.getItem(buildStorageKey(userId, subjectKey, goalKey));
    if (!raw) return [] as Message[];
    const data = JSON.parse(raw) as StoredMessage[];
    return data.map((message) => ({
      ...message,
      timestamp: new Date(message.timestamp),
    }));
  } catch {
    return [] as Message[];
  }
};

const saveStoredMessages = (userId: string, subjectKey: string, goalKey: string, messages: Message[]) => {
  try {
    const data: StoredMessage[] = messages.map((message) => ({
      ...message,
      timestamp: message.timestamp.toISOString(),
    }));
    localStorage.setItem(buildStorageKey(userId, subjectKey, goalKey), JSON.stringify(data));
  } catch {
    // Ignore storage errors (quota, private mode, etc.)
  }
};

const clearStoredMessages = (userId: string, subjectKey: string, goalKey: string) => {
  try {
    localStorage.removeItem(buildStorageKey(userId, subjectKey, goalKey));
  } catch {
    // Ignore storage errors (quota, private mode, etc.)
  }
};

export default function AITutor() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [goal, setGoal] = useState('');
  const [subjectId, setSubjectId] = useState(SUBJECTS[0]?.id ?? '');
  const [goalDetail, setGoalDetail] = useState('');
  const [level, setLevel] = useState<'beginner' | 'intermediate' | 'advanced'>('beginner');
  const [showGoalInput, setShowGoalInput] = useState(!goal);
  const [currentConcept, setCurrentConcept] = useState<ConceptInfo | null>(null);
  const [conceptLoading, setConceptLoading] = useState(false);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const [assessmentDraft, setAssessmentDraft] = useState<AssessmentDraft>({
    concept: '',
    difficulty: 'easy',
    num_questions: 5,
    chapter_content: '',
  });
  const [assessmentLoading, setAssessmentLoading] = useState(false);
  const [assessmentQuestions, setAssessmentQuestions] = useState<AssessmentQuestion[]>([]);
  const [assessmentError, setAssessmentError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const autoStartedRef = useRef(false);

  const renderMessageContent = (text: string) => (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        h1: ({ children }) => <h1 className="text-[18px] font-bold mb-3 mt-4 text-[#1a1a1a]">{children}</h1>,
        h2: ({ children }) => <h2 className="text-[16px] font-bold mb-2 mt-3 text-[#2a2a2a]">{children}</h2>,
        h3: ({ children }) => <h3 className="text-[15px] font-semibold mb-2 mt-2 text-[#333]">{children}</h3>,
        p: ({ children }) => <p className="text-[14px] leading-[1.6] mb-3 last:mb-0 text-[#444]">{children}</p>,
        ul: ({ children }) => <ul className="list-disc pl-6 mb-3 space-y-1.5 text-[#444]">{children}</ul>,
        ol: ({ children }) => <ol className="list-decimal pl-6 mb-3 space-y-1.5 text-[#444]">{children}</ol>,
        li: ({ children }) => <li className="text-[14px] leading-relaxed ml-1">{children}</li>,
        strong: ({ children }) => <strong className="font-bold text-[#1a1a1a]">{children}</strong>,
        em: ({ children }) => <em className="italic text-[#555]">{children}</em>,
        a: ({ children, href }) => (
          <a
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="text-[#0066cc] underline hover:text-[#0052a3] transition-colors"
          >
            {children}
          </a>
        ),
        code: ({ className, children }) =>
          !className ? (
            <code className="px-1.5 py-0.5 bg-[#f3f4f6] border border-[#e5e7eb] rounded text-[13px] font-mono text-[#d63384]">
              {children}
            </code>
          ) : (
            <code className="block bg-[#1e293b] text-[#e2e8f0] p-4 rounded-lg text-[13px] font-mono overflow-x-auto mb-3 border-l-4 border-[#ce6a86]">
              {children}
            </code>
          ),
        pre: ({ children }) => (
          <pre className="bg-[#1e293b] text-[#e2e8f0] p-4 rounded-lg text-[13px] font-mono overflow-x-auto mb-3 border border-[#334155] shadow-sm">
            {children}
          </pre>
        ),
        blockquote: ({ children }) => (
          <blockquote className="border-l-4 border-[#ce6a86] pl-4 py-2 italic text-[14px] text-[#666] mb-3 bg-[#fef3f4] my-3 rounded-r">
            {children}
          </blockquote>
        ),
        table: ({ children }) => (
          <table className="w-full border-collapse border border-[#ddd] my-3 text-[13px]">
            {children}
          </table>
        ),
        thead: ({ children }) => (
          <thead className="bg-[#f3f4f6]">{children}</thead>
        ),
        tbody: ({ children }) => (
          <tbody>{children}</tbody>
        ),
        tr: ({ children }) => (
          <tr className="border-b border-[#ddd]">{children}</tr>
        ),
        th: ({ children }) => (
          <th className="border border-[#ddd] px-3 py-2 text-left font-semibold">{children}</th>
        ),
        td: ({ children }) => (
          <td className="border border-[#ddd] px-3 py-2">{children}</td>
        ),
      }}
    >
      {text}
    </ReactMarkdown>
  );

  const renderUserMessageContent = (text: string) => (
    <p className="text-[14px] leading-[1.6] text-white whitespace-pre-wrap">{text}</p>
  );

  useEffect(() => {
    if (!user) {
      navigate('/login');
      return;
    }

    // Check if there's a concept parameter from navigation
    const conceptIdParam = searchParams.get('concept');
    if (conceptIdParam) {
      loadConceptInfo(parseInt(conceptIdParam));
    }

    const goalParam = searchParams.get('goal');
    const levelParam = searchParams.get('level');
    const subjectParam = searchParams.get('subject');
    const subjectKey = subjectParam || subjectId;
    const goalKey = goalParam || '';
    if (subjectParam) {
      setSubjectId(subjectParam);
    }
    if (levelParam === 'beginner' || levelParam === 'intermediate' || levelParam === 'advanced') {
      setLevel(levelParam);
    }
    if (goalParam) {
      setGoal(goalParam);
      setShowGoalInput(false);
      setError(null);
      if (!autoStartedRef.current) {
        autoStartedRef.current = true;
        const cachedMessages = user ? loadStoredMessages(user.user_id, subjectKey, goalKey) : [];
        if (cachedMessages.length > 0) {
          setMessages(cachedMessages);
        } else {
          setMessages([]);
          addMessage(
            'assistant',
            `Xin chào! Tôi sẽ giúp bạn học: "${goalParam}". Hãy đặt bất kỳ câu hỏi nào về chủ đề này.`,
            null
          );
        }
        loadHistory();
      }
    }
  }, [user, navigate, searchParams]);

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    if (!user || showGoalInput || !subjectId || !goal || messages.length === 0) return;
    saveStoredMessages(user.user_id, subjectId, goal, messages);
  }, [messages, user, showGoalInput, subjectId, goal]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const loadConceptInfo = async (conceptId: number) => {
    setConceptLoading(true);
    try {
      // TODO: Replace with actual API call to fetch concept info
      const mockConcept: ConceptInfo = {
        concept_id: conceptId,
        concept_name: 'Python Basics',
        description: 'Learn the fundamentals of Python programming',
        mastery: 0.45,
        status: 'in_progress',
      };
      setCurrentConcept(mockConcept);
    } catch (err) {
      console.error('Error loading concept:', err);
    } finally {
      setConceptLoading(false);
    }
  };

  const loadHistory = async () => {
    if (!user) return;
    
    setHistoryLoading(true);
    try {
      const data = (await apiClient.get('/ask/history?limit=20')) as {
        success: boolean;
        history?: HistoryItem[];
      };
      if (data.success) {
        setHistory(data.history || []);
      }
    } catch (err) {
      console.error('Error loading history:', err);
    } finally {
      setHistoryLoading(false);
    }
  };

  const handleDeleteHistoryItem = async (historyId: string) => {
    if (!confirm('Bạn có chắc chắn muốn xóa câu hỏi này khỏi lịch sử?')) {
      return;
    }

    try {
      const response = (await apiClient.delete(`/ask/history/${historyId}`)) as { success: boolean };
      if (response.success) {
        setHistory(history.filter((item) => item._id !== historyId));
      } else {
        setError('Không thể xóa mục lịch sử');
      }
    } catch (err) {
      console.error('Error deleting history:', err);
      setError('Lỗi khi xóa mục lịch sử');
    }
  };

  const handleLoadFromHistory = (item: HistoryItem) => {
    setInput(item.question);
    setShowHistory(false);
  };

  const buildGoal = (selectedSubjectId: string, detail: string) => {
    const subject = SUBJECTS.find((item) => item.id === selectedSubjectId);
    const baseGoal = subject?.goal ?? '';
    const trimmedDetail = detail.trim();

    if (!baseGoal && !trimmedDetail) {
      return '';
    }

    if (!baseGoal) {
      return trimmedDetail;
    }

    if (!trimmedDetail) {
      return baseGoal;
    }

    return `${baseGoal} - ${trimmedDetail}`;
  };

  const handleStartChat = () => {
    const nextGoal = buildGoal(subjectId, goalDetail);
    if (!nextGoal) {
      setError('Vui lòng chọn môn học');
      return;
    }
    setGoal(nextGoal);
    setShowGoalInput(false);
    setError(null);
    if (user) {
      const cachedMessages = loadStoredMessages(user.user_id, subjectId, nextGoal);
      if (cachedMessages.length > 0) {
        setMessages(cachedMessages);
      } else {
        setMessages([]);
        addMessage(
          'assistant',
          `Xin chào! Tôi sẽ giúp bạn học: "${nextGoal}". Hãy đặt bất kỳ câu hỏi nào về chủ đề này.`,
          null
        );
      }
    } else {
      setMessages([]);
      addMessage(
        'assistant',
        `Xin chào! Tôi sẽ giúp bạn học: "${nextGoal}". Hãy đặt bất kỳ câu hỏi nào về chủ đề này.`,
        null
      );
    }
    loadHistory();
  };

  const handleClearSubjectHistory = () => {
    if (!user) return;

    if (!confirm('Bạn có chắc chắn muốn xóa lịch sử của môn học này?')) {
      return;
    }

    if (!goal) return;

    clearStoredMessages(user.user_id, subjectId, goal);
    setMessages([]);
    if (goal) {
      addMessage(
        'assistant',
        `Xin chào! Tôi sẽ giúp bạn học: "${goal}". Hãy đặt bất kỳ câu hỏi nào về chủ đề này.`,
        null
      );
    }
  };

  const handleSendMessage = async () => {
    if (!input.trim() || !user) {
      return;
    }

    const userQuestion = input;
    setInput('');
    
    // Add user message
    addMessage('user', userQuestion, null);
    setLoading(true);
    setError(null);

    try {
      // Validate input
      if (userQuestion.length < 5) {
        throw new Error('Câu hỏi phải có ít nhất 5 ký tự');
      }
      if (!goal || goal.length < 3) {
        throw new Error('Mục tiêu học tập không hợp lệ');
      }

      const data = (await apiClient.post('/ask/', {
        user_id: user.user_id,
        question: userQuestion,
        goal: goal,
        level: level,
        completed: currentConcept ? [currentConcept.concept_id.toString()] : [],
      })) as {
        success: boolean;
        answer?: {
          answer_text?: string;
          sources?: Array<{ title: string; url?: string; type?: string }>;
          confidence?: number;
          latency_ms?: number;
        };
        concept_detected?: {
          concept_id: number;
          concept_name: string;
          score: number;
        };
        learning_path?: Array<{
          concept_id: number;
          concept_name: string;
          order: number;
          status: string;
        }>;
        adaptive_info?: {
          mode: string;
          difficulty_boost: number;
          practice_recommendations: string[];
        };
        error?: string;
      };
      
      if (data.success) {
        addMessage('assistant', data.answer?.answer_text || 'Xin lỗi, tôi không thể trả lời câu hỏi này lúc này.', {
          answer: data.answer,
          conceptDetected: data.concept_detected,
          learning_path: data.learning_path,
          adaptive_info: data.adaptive_info,
        });
      } else {
        throw new Error(data.error || 'Không nhận được phản hồi từ server');
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : 'Đã xảy ra lỗi không xác định';
      setError(errorMessage);
      console.error('Error sending message:', err);
    } finally {
      setLoading(false);
    }
  };

  const handleGenerateAssessment = async () => {
    if (!user) {
      return;
    }

    setAssessmentError(null);
    setAssessmentQuestions([]);

    if (!assessmentDraft.concept.trim()) {
      setAssessmentError('Vui lòng nhập concept');
      return;
    }

    if (!assessmentDraft.chapter_content.trim() || assessmentDraft.chapter_content.trim().length < 50) {
      setAssessmentError('Nội dung chương học cần ít nhất 50 ký tự');
      return;
    }

    if (assessmentDraft.num_questions < 1 || assessmentDraft.num_questions > 20) {
      setAssessmentError('Số câu hỏi phải từ 1 đến 20');
      return;
    }

    setAssessmentLoading(true);

    try {
      const response = await assessmentService.generateQuestions({
        user_id: user.user_id,
        concept: assessmentDraft.concept.trim(),
        difficulty: assessmentDraft.difficulty,
        num_questions: assessmentDraft.num_questions,
        chapter_content: assessmentDraft.chapter_content.trim(),
      });

      if (!response.success) {
        throw new Error('Không thể tạo câu hỏi kiểm tra');
      }

      setAssessmentQuestions(response.questions || []);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Đã xảy ra lỗi khi tạo câu hỏi';
      setAssessmentError(message);
    } finally {
      setAssessmentLoading(false);
    }
  };

  const addMessage = (role: 'user' | 'assistant', content: string, data: any) => {
    const newMessage: Message = {
      id: Math.random().toString(36).substr(2, 9),
      role,
      content,
      timestamp: new Date(),
      ...(data && {
        answer: data.answer,
        conceptDetected: data.conceptDetected,
        learning_path: data.learning_path,
        adaptive_info: data.adaptive_info,
      }),
    };
    setMessages((prev) => [...prev, newMessage]);
  };

  if (showGoalInput) {
    return (
      <DashboardLayout>
        <div className="max-w-[1190px] mx-auto">
          <h1 className="text-[25px] font-semibold text-secondary mb-8 mt-[25px]">AI Tutor</h1>
          
          <div className="flex items-center gap-2 mb-[40px]">
            <div className="w-[3px] h-[28px] bg-[#8f1025] rounded-[5px]" />
            <h2 className="text-[18px] font-medium text-[#8f1025]">Bắt đầu phiên học tập</h2>
          </div>

          <div className="bg-white border border-[#ce6a86] rounded-[20px] p-8 max-w-[600px]">
            <div className="mb-6">
              <label className="block text-[16px] font-medium text-[#8f1025] mb-3">
                Mục tiêu học tập của bạn là gì?
              </label>
              <select
                value={subjectId}
                onChange={(e) => setSubjectId(e.target.value)}
                className="w-full px-4 py-3 border border-[#ce6a86] rounded-[10px] focus:outline-none focus:border-[#8f1025] text-[14px]"
              >
                {SUBJECTS.map((subject) => (
                  <option key={subject.id} value={subject.id}>
                    {subject.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="mb-6">
              <label className="block text-[16px] font-medium text-[#8f1025] mb-3">
                Mục tiêu chi tiết (tùy chọn)
              </label>
              <input
                type="text"
                value={goalDetail}
                onChange={(e) => setGoalDetail(e.target.value)}
                placeholder="VD: backend, OOP, cấu trúc dữ liệu..."
                className="w-full px-4 py-3 border border-[#ce6a86] rounded-[10px] focus:outline-none focus:border-[#8f1025] text-[14px]"
                onKeyPress={(e) => e.key === 'Enter' && handleStartChat()}
              />
            </div>

            <div className="mb-6">
              <label className="block text-[16px] font-medium text-[#8f1025] mb-3">
                Trình độ hiện tại
              </label>
              <select
                value={level}
                onChange={(e) => setLevel(e.target.value as 'beginner' | 'intermediate' | 'advanced')}
                className="w-full px-4 py-3 border border-[#ce6a86] rounded-[10px] focus:outline-none focus:border-[#8f1025] text-[14px]"
              >
                <option value="beginner">Người mới bắt đầu</option>
                <option value="intermediate">Trung cấp</option>
                <option value="advanced">Nâng cao</option>
              </select>
            </div>

            {error && (
              <div className="mb-4 p-3 bg-red-100 border border-red-300 text-red-800 rounded-[10px] text-[14px]">
                {error}
              </div>
            )}

            <button
              onClick={handleStartChat}
              className="w-full bg-[#8f1025] text-white py-3 rounded-[10px] font-medium hover:bg-[#7a0e20] transition-colors text-[16px]"
            >
              Bắt đầu
            </button>
          </div>
        </div>
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout>
      <div className="max-w-[1190px] mx-auto h-[calc(100vh-120px)] flex flex-col">
        <div className="flex items-center justify-between mb-6 mt-[25px]">
          <h1 className="text-[25px] font-semibold text-secondary">AI Tutor</h1>
          <div className="flex gap-3">
            <button
              onClick={handleClearSubjectHistory}
              className="px-4 py-2 text-[14px] bg-red-50 text-red-700 rounded-[10px] hover:bg-red-100 transition-colors"
            >
              🗑️ Xóa lịch sử môn
            </button>
            <button
              onClick={() => setShowHistory(!showHistory)}
              className="px-4 py-2 text-[14px] bg-gray-200 text-[#333] rounded-[10px] hover:bg-gray-300 transition-colors"
            >
              📋 Lịch sử ({history.length})
            </button>
            <button
              onClick={() => {
                setShowGoalInput(true);
                setMessages([]);
                setGoal('');
              }}
              className="px-4 py-2 text-[14px] bg-[#8f1025] text-white rounded-[10px] hover:bg-[#7a0e20] transition-colors"
            >
              Phiên mới
            </button>
          </div>
        </div>

        {/* History Modal */}
        {showHistory && (
          <div className="fixed inset-0 bg-black bg-opacity-50 z-50 flex items-center justify-center">
            <div className="bg-white rounded-[20px] w-[500px] max-h-[80vh] flex flex-col border border-[#ce6a86] shadow-lg">
              <div className="flex items-center justify-between p-6 border-b border-[#ce6a86]">
                <h2 className="text-[20px] font-semibold text-[#8f1025]">Lịch sử câu hỏi</h2>
                <button
                  onClick={() => setShowHistory(false)}
                  className="text-[24px] text-[#8f1025] hover:text-[#7a0e20]"
                >
                  ×
                </button>
              </div>

              <div className="flex-1 overflow-y-auto p-4 space-y-3">
                {historyLoading ? (
                  <div className="flex items-center justify-center py-8">
                    <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-[#8f1025]" />
                  </div>
                ) : history.length === 0 ? (
                  <div className="text-center py-8 text-[#666]">
                    <p>Chưa có câu hỏi nào</p>
                  </div>
                ) : (
                  history.map((item) => (
                    <div
                      key={item._id}
                      className="p-3 bg-gray-50 rounded-[10px] border border-[#ce6a86] hover:bg-gray-100 transition-colors group"
                    >
                      <div className="flex justify-between items-start gap-2">
                        <div className="flex-1 cursor-pointer" onClick={() => handleLoadFromHistory(item)}>
                          <p className="text-[13px] font-medium text-[#8f1025] mb-1 line-clamp-2">
                            {item.question}
                          </p>
                          <p className="text-[11px] text-[#666] mb-1">
                            Mục tiêu: {item.goal}
                          </p>
                          <p className="text-[10px] text-[#999]">
                            {new Date(item.timestamp).toLocaleString('vi-VN')}
                          </p>
                        </div>
                        <button
                          onClick={() => handleDeleteHistoryItem(item._id)}
                          className="px-2 py-1 text-[11px] bg-red-100 text-red-600 rounded-[5px] opacity-0 group-hover:opacity-100 transition-opacity whitespace-nowrap"
                        >
                          Xóa
                        </button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        )}

        <div className="flex gap-6 flex-1 min-h-0">
          {/* Main Chat Area */}
          <div className="flex-1 flex flex-col bg-white border border-[#ce6a86] rounded-[20px] overflow-hidden">
            {/* Messages Area */}
            <div className="flex-1 overflow-y-auto p-6 space-y-4">
              {messages.length === 0 ? (
                <div className="flex items-center justify-center h-full">
                  <div className="text-center">
                    <div className="text-[50px] mb-4">💡</div>
                    <p className="text-[#8f1025] text-[16px]">Hãy bắt đầu bằng cách đặt một câu hỏi</p>
                  </div>
                </div>
              ) : (
                <>
                  {messages.map((message) => (
                    <div
                      key={message.id}
                      className={`flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
                    >
                      <div
                        className={`max-w-[70%] rounded-[15px] p-4 ${
                          message.role === 'user'
                            ? 'bg-[#8f1025] text-white rounded-br-none'
                            : 'bg-gray-100 text-[#333] rounded-bl-none'
                        }`}
                      >
                        {(() => {
                          const mainText =
                            message.role === 'assistant'
                              ? message.content || message.answer?.answer_text || ''
                              : message.content;

                          if (!mainText) return null;

                          return message.role === 'assistant'
                            ? renderMessageContent(mainText)
                            : renderUserMessageContent(mainText);
                        })()}
                        <p className="text-[12px] opacity-70">
                          {message.timestamp.toLocaleTimeString('vi-VN', {
                            hour: '2-digit',
                            minute: '2-digit',
                          })}
                        </p>

                        {/* Answer Details */}
                        {message.role === 'assistant' && message.answer && (
                          <div className="mt-5 pt-4 border-t-2 border-gray-200">
                            {message.answer.sources && message.answer.sources.length > 0 && (
                              <div className="mb-4">
                                <p className="text-[13px] font-bold mb-3 text-[#8f1025] flex items-center gap-1.5">
                                  <span>📚</span> Nguồn tài liệu
                                </p>
                                <div className="space-y-2">
                                  {message.answer.sources.map((source, idx) => (
                                    <div
                                      key={idx}
                                      className="flex items-start gap-2 p-2.5 bg-[#fef3f4] border border-[#f5d5dd] rounded-lg hover:bg-[#fedde2] transition-colors"
                                    >
                                      <span className="text-[11px] font-bold text-[#8f1025] min-w-[18px] text-center">{idx + 1}</span>
                                      <div className="flex-1">
                                        {source.url ? (
                                          <a
                                            href={source.url}
                                            target="_blank"
                                            rel="noopener noreferrer"
                                            className="text-[12px] font-medium text-[#0066cc] hover:underline break-words"
                                          >
                                            {source.title}
                                          </a>
                                        ) : (
                                          <p className="text-[12px] font-medium text-[#333]">{source.title}</p>
                                        )}
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}

                            {message.answer.confidence && (
                              <div className="flex items-center gap-2 p-2.5 bg-[#eef9ff] border border-[#b8e0f6] rounded-lg">
                                <span className="text-[13px] font-semibold text-[#0066cc]">⭐ Độ tin cậy:</span>
                                <div className="flex-1 bg-white border border-[#d0e8ff] rounded-full h-2 overflow-hidden">
                                  <div
                                    className="h-full bg-gradient-to-r from-[#0066cc] to-[#003d99]"
                                    style={{ width: `${Math.round(message.answer.confidence * 100)}%` }}
                                  />
                                </div>
                                <span className="text-[12px] font-bold text-[#0066cc] min-w-[35px] text-right">
                                  {Math.round(message.answer.confidence * 100)}%
                                </span>
                              </div>
                            )}
                          </div>
                        )}

                        {/* Concept Detected */}
                        {message.role === 'assistant' && message.conceptDetected && (
                          <div className="mt-3 p-2 bg-white bg-opacity-20 rounded-[10px]">
                            <p className="text-[12px] font-semibold mb-1">📌 Khái niệm được phát hiện:</p>
                            <p className="text-[13px]">{message.conceptDetected.concept_name}</p>
                            <p className="text-[11px] opacity-80 mt-1">
                              Độ phù hợp: {Math.round(message.conceptDetected.score * 100)}%
                            </p>
                          </div>
                        )}

                        {/* Learning Recommendations */}
                        {message.role === 'assistant' && message.learning_path && message.learning_path.length > 0 && (
                          <div className="mt-3 p-2 bg-white bg-opacity-20 rounded-[10px]">
                            <p className="text-[12px] font-semibold mb-2">🎯 Khái niệm tiếp theo:</p>
                            <div className="space-y-1">
                              {message.learning_path.slice(0, 3).map((concept, idx) => (
                                <div key={idx} className="text-[12px]">
                                  <span className="font-medium">{idx + 1}.</span> {concept.concept_name}
                                </div>
                              ))}
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                  <div ref={messagesEndRef} />
                </>
              )}
            </div>

            {error && (
              <div className="px-6 py-3 bg-red-50 border-t border-red-200 text-red-700 text-[13px]">
                ⚠️ {error}
              </div>
            )}

            {/* Input Area */}
            <div className="border-t border-[#ce6a86] p-4 bg-gray-50">
              <div className="flex gap-2">
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyPress={(e) => e.key === 'Enter' && !loading && handleSendMessage()}
                  placeholder="Nhập câu hỏi của bạn..."
                  disabled={loading}
                  className="flex-1 px-4 py-3 border border-[#ce6a86] rounded-[10px] focus:outline-none focus:border-[#8f1025] disabled:bg-gray-100 text-[14px]"
                />
                <button
                  onClick={handleSendMessage}
                  disabled={loading || !input.trim()}
                  className="px-6 py-3 bg-[#8f1025] text-white rounded-[10px] hover:bg-[#7a0e20] disabled:opacity-50 disabled:cursor-not-allowed transition-colors font-medium text-[14px]"
                >
                  {loading ? '...' : 'Gửi'}
                </button>
              </div>
            </div>
          </div>

          {/* Right Sidebar - Learning Context */}
          <div className="w-[300px] flex flex-col gap-4">
            {/* Assessment Generator Card */}
            <div className="bg-white border border-[#ce6a86] rounded-[20px] p-5">
              <h3 className="text-[14px] font-semibold text-[#8f1025] mb-3">📝 Tạo câu hỏi kiểm tra</h3>

              <div className="space-y-3">
                <div>
                  <label className="block text-[12px] text-[#8f1025] mb-1">Concept</label>
                  <input
                    type="text"
                    value={assessmentDraft.concept}
                    onChange={(e) =>
                      setAssessmentDraft((prev) => ({
                        ...prev,
                        concept: e.target.value,
                      }))
                    }
                    placeholder="Ví dụ: RAG Pipeline"
                    className="w-full px-3 py-2 border border-[#ce6a86] rounded-[8px] text-[12px] focus:outline-none focus:border-[#8f1025]"
                  />
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="block text-[12px] text-[#8f1025] mb-1">Độ khó</label>
                    <select
                      value={assessmentDraft.difficulty}
                      onChange={(e) =>
                        setAssessmentDraft((prev) => ({
                          ...prev,
                          difficulty: e.target.value as AssessmentDifficulty,
                        }))
                      }
                      className="w-full px-2 py-2 border border-[#ce6a86] rounded-[8px] text-[12px] focus:outline-none focus:border-[#8f1025]"
                    >
                      <option value="easy">easy</option>
                      <option value="medium">medium</option>
                      <option value="hard">hard</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-[12px] text-[#8f1025] mb-1">Số câu</label>
                    <input
                      type="number"
                      min={1}
                      max={20}
                      value={assessmentDraft.num_questions}
                      onChange={(e) =>
                        setAssessmentDraft((prev) => ({
                          ...prev,
                          num_questions: Number(e.target.value) || 1,
                        }))
                      }
                      className="w-full px-2 py-2 border border-[#ce6a86] rounded-[8px] text-[12px] focus:outline-none focus:border-[#8f1025]"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-[12px] text-[#8f1025] mb-1">Nội dung chương học</label>
                  <textarea
                    value={assessmentDraft.chapter_content}
                    onChange={(e) =>
                      setAssessmentDraft((prev) => ({
                        ...prev,
                        chapter_content: e.target.value,
                      }))
                    }
                    rows={6}
                    placeholder="Dán nội dung chương học vào đây..."
                    className="w-full px-3 py-2 border border-[#ce6a86] rounded-[8px] text-[12px] focus:outline-none focus:border-[#8f1025] resize-y"
                  />
                </div>

                {assessmentError && (
                  <div className="text-[12px] text-red-700 bg-red-50 border border-red-200 rounded-[8px] px-2 py-2">
                    {assessmentError}
                  </div>
                )}

                <button
                  onClick={handleGenerateAssessment}
                  disabled={assessmentLoading}
                  className="w-full px-3 py-2 bg-[#8f1025] text-white rounded-[8px] text-[12px] font-medium hover:bg-[#7a0e20] disabled:opacity-50"
                >
                  {assessmentLoading ? 'Đang tạo...' : 'Tạo câu hỏi'}
                </button>
              </div>

              {assessmentQuestions.length > 0 && (
                <div className="mt-4 border-t border-[#f2c9d4] pt-3">
                  <p className="text-[12px] font-semibold text-[#8f1025] mb-2">Kết quả JSON</p>
                  <div className="max-h-[260px] overflow-y-auto border border-[#f2d5dd] rounded-[10px] bg-[#fff9fb] p-2">
                    <pre className="text-[11px] text-[#333] whitespace-pre-wrap break-words">
                      {JSON.stringify(assessmentQuestions, null, 2)}
                    </pre>
                  </div>
                </div>
              )}
            </div>

            {/* Goal Card */}
            <div className="bg-white border border-[#ce6a86] rounded-[20px] p-5">
              <h3 className="text-[14px] font-semibold text-[#8f1025] mb-3">📚 Mục tiêu</h3>
              <p className="text-[13px] text-[#333] line-clamp-3">{goal}</p>
              <p className="text-[12px] text-[#8f1025] mt-3 font-medium">Trình độ: {
                level === 'beginner' ? 'Người mới' :
                level === 'intermediate' ? 'Trung cấp' : 'Nâng cao'
              }</p>
            </div>

            {/* Current Concept Card */}
            {currentConcept && (
              <div className="bg-white border border-[#ce6a86] rounded-[20px] p-5">
                <h3 className="text-[14px] font-semibold text-[#8f1025] mb-3">🎯 Khái niệm hiện tại</h3>
                {conceptLoading ? (
                  <div className="animate-spin rounded-full h-6 w-6 border-b-2 border-[#8f1025]" />
                ) : (
                  <>
                    <p className="text-[13px] font-medium text-[#333] mb-2">{currentConcept.concept_name}</p>
                    <p className="text-[12px] text-[#666] mb-3">{currentConcept.description}</p>
                    
                    <div className="mb-3">
                      <p className="text-[12px] font-medium text-[#8f1025] mb-1">Độ thành thạo</p>
                      <div className="w-full h-2 bg-gray-200 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-[#8f1025] transition-all"
                          style={{ width: `${currentConcept.mastery * 100}%` }}
                        />
                      </div>
                      <p className="text-[11px] text-[#666] mt-1">{Math.round(currentConcept.mastery * 100)}%</p>
                    </div>

                    <div className="inline-block px-3 py-1 rounded-full text-[11px] font-medium"
                         style={{
                           backgroundColor: currentConcept.status === 'complete' ? '#d4f4dd' :
                                          currentConcept.status === 'in_progress' ? '#fff4d6' : '#f0f0f0',
                           color: currentConcept.status === 'complete' ? '#1a6b2f' :
                                  currentConcept.status === 'in_progress' ? '#a67c2f' : '#666'
                         }}>
                      {currentConcept.status === 'complete' ? 'Hoàn thành' :
                       currentConcept.status === 'in_progress' ? 'Đang học' : 'Chưa bắt đầu'}
                    </div>
                  </>
                )}
              </div>
            )}

            {/* Learning Tips Card */}
            <div className="bg-white border border-[#ce6a86] rounded-[20px] p-5">
              <h3 className="text-[14px] font-semibold text-[#8f1025] mb-3">💡 Mẹo học tập</h3>
              <ul className="text-[12px] text-[#666] space-y-2">
                <li>✓ Hỏi các câu hỏi chi tiết</li>
                <li>✓ Kiểm tra nguồn tài liệu</li>
                <li>✓ Luyện tập các khái niệm</li>
                <li>✓ Xem tài nguyên được đề xuất</li>
              </ul>
            </div>

            {/* Quick Actions */}
            <div className="bg-white border border-[#ce6a86] rounded-[20px] p-5">
              <h3 className="text-[14px] font-semibold text-[#8f1025] mb-3">⚡ Hành động nhanh</h3>
              <button
                onClick={() => navigate('/resources')}
                className="w-full text-[12px] px-3 py-2 mb-2 bg-gray-50 hover:bg-gray-100 border border-[#ce6a86] text-[#8f1025] rounded-[8px] transition-colors"
              >
                Xem tài nguyên
              </button>
              <button
                onClick={() => navigate('/learning-path')}
                className="w-full text-[12px] px-3 py-2 bg-gray-50 hover:bg-gray-100 border border-[#ce6a86] text-[#8f1025] rounded-[8px] transition-colors"
              >
                Lộ trình học
              </button>
            </div>
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}
