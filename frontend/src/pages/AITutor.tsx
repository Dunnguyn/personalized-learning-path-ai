import { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useNavigate, useSearchParams } from 'react-router-dom';
import DashboardLayout from '../components/layout/DashboardLayout';
import { useAuth } from '../contexts/AuthContext';
import { apiClient } from '../utils/apiClient';
import { SUBJECTS } from '../utils/subjects';
import { assessmentService, type AssessmentQuestion, type AssessmentDifficulty } from '../services/assessmentService';
import { learningPathService } from '../services';

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
  lesson_title: string;
  concept: string;
  difficulty: AssessmentDifficulty;
  question_type: string;
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
    lesson_title: '',
    concept: '',
    difficulty: 'easy',
    question_type: 'short_answer',
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
            `Xin ch?o! T?i s? gi?p b?n h?c: "${goalParam}". H?y ??t b?t k? c?u h?i n?o v? ch? ?? n?y.`,
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
      const [conceptResponse, progressResponse] = await Promise.all([
        learningPathService.getConceptDetails(conceptId),
        user ? learningPathService.getConceptProgress(conceptId, user.user_id) : Promise.resolve(null),
      ]);

      const concept = conceptResponse?.concept ?? conceptResponse ?? {};
      const progress = progressResponse?.progress ?? {};

      setCurrentConcept({
        concept_id: Number(concept?.concept_id ?? conceptId),
        concept_name: String(concept?.concept_name ?? `Concept ${conceptId}`),
        description: String(concept?.topic ?? concept?.description ?? 'Kh?ng c? m? t? chi ti?t'),
        mastery: typeof progress?.mastery === 'number' ? progress.mastery : 0,
        status: String(progress?.status ?? 'not_started'),
      });
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
    if (!confirm('B?n c? ch?c ch?n mu?n x?a c?u h?i n?y kh?i l?ch s??')) {
      return;
    }

    try {
      const response = (await apiClient.delete(`/ask/history/${historyId}`)) as { success: boolean };
      if (response.success) {
        setHistory(history.filter((item) => item._id !== historyId));
      } else {
        setError('Kh?ng th? x?a m?c l?ch s?');
      }
    } catch (err) {
      console.error('Error deleting history:', err);
      setError('L?i khi x?a m?c l?ch s?');
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
      setError('Vui l?ng ch?n m?n h?c');
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
          `Xin ch?o! T?i s? gi?p b?n h?c: "${nextGoal}". H?y ??t b?t k? c?u h?i n?o v? ch? ?? n?y.`,
          null
        );
      }
    } else {
      setMessages([]);
      addMessage(
        'assistant',
        `Xin ch?o! T?i s? gi?p b?n h?c: "${nextGoal}". H?y ??t b?t k? c?u h?i n?o v? ch? ?? n?y.`,
        null
      );
    }
    loadHistory();
  };

  const handleClearSubjectHistory = () => {
    if (!user) return;

    if (!confirm('B?n c? ch?c ch?n mu?n x?a l?ch s? c?a m?n h?c n?y?')) {
      return;
    }

    if (!goal) return;

    clearStoredMessages(user.user_id, subjectId, goal);
    setMessages([]);
    if (goal) {
      addMessage(
        'assistant',
        `Xin ch?o! T?i s? gi?p b?n h?c: "${goal}". H?y ??t b?t k? c?u h?i n?o v? ch? ?? n?y.`,
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
        addMessage('assistant', data.answer?.answer_text || 'Xin l?i, t?i kh?ng th? tr? l?i c?u h?i n?y l?c n?y.', {
          answer: data.answer,
          conceptDetected: data.concept_detected,
          learning_path: data.learning_path,
          adaptive_info: data.adaptive_info,
        });
      } else {
        throw new Error(data.error || 'Kh?ng nh?n ???c ph?n h?i t? server');
      }
    } catch (err) {
      const errorMessage = err instanceof Error ? err.message : '?? x?y ra l?i kh?ng x?c ??nh';
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
      setAssessmentError('Vui l?ng nh?p concept');
      return;
    }

    if (!assessmentDraft.chapter_content.trim() || assessmentDraft.chapter_content.trim().length < 50) {
      setAssessmentError('N?i dung ch??ng h?c c?n ?t nh?t 50 k? t?');
      return;
    }

    if (assessmentDraft.num_questions < 1 || assessmentDraft.num_questions > 20) {
      setAssessmentError('S? c?u h?i ph?i t? 1 ??n 20');
      return;
    }

    setAssessmentLoading(true);

    try {
      const response = await assessmentService.generateQuestions({
        user_id: user.user_id,
        lesson_title: assessmentDraft.lesson_title.trim() || assessmentDraft.concept.trim(),
        concept: assessmentDraft.concept.trim(),
        difficulty: assessmentDraft.difficulty,
        question_type: assessmentDraft.question_type.trim() || 'short_answer',
        num_questions: assessmentDraft.num_questions,
        chapter_content: assessmentDraft.chapter_content.trim(),
        retrieved_context: assessmentDraft.chapter_content.trim(),
      });

      if (!response.success) {
        throw new Error('Kh?ng th? t?o c?u h?i ki?m tra');
      }

      setAssessmentQuestions(response.questions || []);
    } catch (err) {
      const message = err instanceof Error ? err.message : '?? x?y ra l?i khi t?o c?u h?i';
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
        <div className="page-shell-narrow">
          <p className="page-kicker">Tr? gi?ng AI</p>
          <h1 className="page-title">Tr? gi?ng AI</h1>
          
          <div className="mb-[40px] flex items-center gap-2">
            <div className="h-[28px] w-[3px] rounded-[5px] bg-[#8c3451]" />
            <h2 className="page-section-title text-[18px]">B?t ??u phi?n h?c t?p</h2>
          </div>

          <div className="soft-panel max-w-[720px] p-8">
            <div className="mb-6">
              <label className="mb-3 block text-[16px] font-medium text-[#514942]">
                M?c ti?u h?c t?p c?a b?n l? g??
              </label>
              <select
                value={subjectId}
                onChange={(e) => setSubjectId(e.target.value)}
                className="theme-input rounded-[18px]"
              >
                {SUBJECTS.map((subject) => (
                  <option key={subject.id} value={subject.id}>
                    {subject.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="mb-6">
              <label className="mb-3 block text-[16px] font-medium text-[#514942]">
                M?c ti?u chi ti?t (t?y ch?n)
              </label>
              <input
                type="text"
                value={goalDetail}
                onChange={(e) => setGoalDetail(e.target.value)}
                placeholder="VD: backend, OOP, c?u tr?c d? li?u..."
                className="theme-input rounded-[18px]"
                onKeyDown={(e) => {
                  if (e.key === 'Enter') {
                    e.preventDefault();
                    handleStartChat();
                  }
                }}
              />
            </div>

            <div className="mb-6">
              <label className="mb-3 block text-[16px] font-medium text-[#514942]">
                Tr?nh ?? hi?n t?i
              </label>
              <select
                value={level}
                onChange={(e) => setLevel(e.target.value as 'beginner' | 'intermediate' | 'advanced')}
                className="theme-input rounded-[18px]"
              >
                <option value="beginner">Ng??i m?i b?t ??u</option>
                <option value="intermediate">Trung c?p</option>
                <option value="advanced">N?ng cao</option>
              </select>
            </div>

            {error && (
              <div className="mb-4 p-3 bg-red-100 border border-red-300 text-red-800 rounded-[10px] text-[14px]">
                {error}
              </div>
            )}

            <button
              onClick={handleStartChat}
              className="theme-button w-full justify-center text-[16px]"
            >
              B?t ??u
            </button>
          </div>
        </div>
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout>
      <div className="page-shell flex min-h-[calc(100vh-140px)] flex-col pb-6">
        <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
          <div>
            <p className="page-kicker mb-2">Tr? gi?ng AI</p>
            <h1 className="page-title mb-0">Tr? gi?ng AI</h1>
          </div>
          <div className="flex flex-wrap gap-3">
            <button
              onClick={handleClearSubjectHistory}
              className="theme-button-secondary border-red-200 bg-white/90 text-red-700"
            >
              ??? X?a l?ch s? m?n
            </button>
            <button
              onClick={() => setShowHistory(!showHistory)}
              className="theme-button-secondary"
            >
              ?? L?ch s? ({history.length})
            </button>
            <button
              onClick={() => {
                setShowGoalInput(true);
                setMessages([]);
                setGoal('');
              }}
              className="theme-button"
            >
              Phi?n m?i
            </button>
          </div>
        </div>

        {/* History Modal */}
        {showHistory && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4 backdrop-blur-sm">
            <div className="white-panel flex max-h-[80vh] w-full max-w-[560px] flex-col overflow-hidden">
              <div className="flex items-center justify-between border-b border-[#8c3451]/10 p-6">
                <h2 className="text-[22px] font-medium tracking-[-0.03em] text-[#8c3451]">L?ch s? c?u h?i</h2>
                <button
                  onClick={() => setShowHistory(false)}
                  className="text-[24px] text-[#8c3451]"
                >
                  ?
                </button>
              </div>

              <div className="scroll-soft flex-1 overflow-y-auto p-4 space-y-3">
                {historyLoading ? (
                  <div className="flex items-center justify-center py-8">
                    <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-[#8c3451]" />
                  </div>
                ) : history.length === 0 ? (
                  <div className="text-center py-8 text-[#666]">
                    <p>Ch?a c? c?u h?i n?o</p>
                  </div>
                ) : (
                  history.map((item) => (
                    <div key={item._id} className="metric-card group p-3">
                      <div className="flex justify-between items-start gap-2">
                        <div className="flex-1 cursor-pointer" onClick={() => handleLoadFromHistory(item)}>
                           <p className="mb-1 line-clamp-2 text-[13px] font-medium text-[#8c3451]">
                            {item.question}
                          </p>
                           <p className="mb-1 text-[11px] text-[#666]">
                            M?c ti?u: {item.goal}
                          </p>
                          <p className="text-[10px] text-[#999]">
                            {new Date(item.timestamp).toLocaleString('vi-VN')}
                          </p>
                        </div>
                         <button
                           onClick={() => handleDeleteHistoryItem(item._id)}
                           className="rounded-full bg-red-100 px-2 py-1 text-[11px] whitespace-nowrap text-red-600 opacity-0 transition-opacity group-hover:opacity-100"
                         >
                            X?a
                         </button>
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </div>
        )}

        <div className="flex min-h-0 flex-1 flex-col gap-6 xl:flex-row">
          {/* Main Chat Area */}
          <div className="white-panel flex min-h-[540px] flex-1 flex-col overflow-hidden">
            {/* Messages Area */}
            <div className="scroll-soft flex-1 overflow-y-auto p-6 space-y-4">
              {messages.length === 0 ? (
                <div className="flex items-center justify-center h-full">
                  <div className="text-center">
                    <div className="text-[50px] mb-4">??</div>
                    <p className="text-[#8c3451] text-[16px]">H?y b?t ??u b?ng c?ch ??t m?t c?u h?i</p>
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
                        className={`max-w-[88%] rounded-[24px] p-4 sm:max-w-[70%] ${
                          message.role === 'user'
                            ? 'rounded-br-[10px] bg-[#8c3451] text-white'
                            : 'rounded-bl-[10px] bg-[#fdf0f5] text-[#5f3040]'
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
                                <p className="text-[13px] font-bold mb-3 text-[#8c3451] flex items-center gap-1.5">
                                  <span>??</span> Ngu?n t?i li?u
                                </p>
                                <div className="space-y-2">
                                  {message.answer.sources.map((source, idx) => (
                                    <div
                                      key={idx}
                                      className="flex items-start gap-2 p-2.5 bg-[#fef3f4] border border-[#f5d5dd] rounded-lg hover:bg-[#fedde2] transition-colors"
                                    >
                                      <span className="text-[11px] font-bold text-[#8c3451] min-w-[18px] text-center">{idx + 1}</span>
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
                                <span className="text-[13px] font-semibold text-[#0066cc]">? ?? tin c?y:</span>
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
                            <p className="text-[12px] font-semibold mb-1">?? Kh?i ni?m ???c ph?t hi?n:</p>
                            <p className="text-[13px]">{message.conceptDetected.concept_name}</p>
                            <p className="text-[11px] opacity-80 mt-1">
                              ?? ph? h?p: {Math.round(message.conceptDetected.score * 100)}%
                            </p>
                          </div>
                        )}

                        {/* Learning Recommendations */}
                        {message.role === 'assistant' && message.learning_path && message.learning_path.length > 0 && (
                          <div className="mt-3 p-2 bg-white bg-opacity-20 rounded-[10px]">
                            <p className="text-[12px] font-semibold mb-2">?? Kh?i ni?m ti?p theo:</p>
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
              <div className="border-t border-red-200 bg-red-50 px-6 py-3 text-[13px] text-red-700">
                ?? {error}
              </div>
            )}

            {/* Input Area */}
            <div className="border-t border-[#8c3451]/10 bg-[#fff6fa] p-4">
              <div className="flex gap-2">
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' && !loading) {
                      e.preventDefault();
                      handleSendMessage();
                    }
                  }}
                  placeholder="Nh?p c?u h?i c?a b?n..."
                  disabled={loading}
                  className="theme-input flex-1 rounded-[18px] disabled:bg-gray-100"
                />
                <button
                  onClick={handleSendMessage}
                  disabled={loading || !input.trim()}
                  className="theme-button disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {loading ? '...' : 'G?i'}
                </button>
              </div>
            </div>
          </div>

          {/* Right Sidebar - Learning Context */}
          <div className="flex w-full flex-col gap-4 xl:sticky xl:top-4 xl:w-[320px] xl:self-start">
            {/* Assessment Generator Card */}
            <div className="soft-panel p-5">
              <h3 className="mb-3 text-[16px] font-medium text-[#8c3451]">?? T?o c?u h?i ki?m tra</h3>

              <div className="space-y-3">
                <div>
                  <label className="block text-[12px] text-[#8c3451] mb-1">T?n b?i h?c</label>
                  <input
                    type="text"
                    value={assessmentDraft.lesson_title}
                    onChange={(e) =>
                      setAssessmentDraft((prev) => ({
                        ...prev,
                        lesson_title: e.target.value,
                      }))
                    }
                    placeholder="V? d?: Gi?i thi?u v? RAG"
                    className="theme-input rounded-[14px] px-3 py-2 text-[12px]"
                  />
                </div>

                <div>
                  <label className="block text-[12px] text-[#8c3451] mb-1">Kh?i ni?m</label>
                  <input
                    type="text"
                    value={assessmentDraft.concept}
                    onChange={(e) =>
                      setAssessmentDraft((prev) => ({
                        ...prev,
                        concept: e.target.value,
                      }))
                    }
                    placeholder="V? d?: RAG Pipeline"
                    className="theme-input rounded-[14px] px-3 py-2 text-[12px]"
                  />
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="block text-[12px] text-[#8c3451] mb-1">?? kh?</label>
                    <select
                      value={assessmentDraft.difficulty}
                      onChange={(e) =>
                        setAssessmentDraft((prev) => ({
                          ...prev,
                          difficulty: e.target.value as AssessmentDifficulty,
                        }))
                      }
                       className="theme-input rounded-[14px] px-2 py-2 text-[12px]"
                    >
                      <option value="easy">D?</option>
                      <option value="medium">Trung b?nh</option>
                      <option value="hard">Kh?</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-[12px] text-[#8c3451] mb-1">Lo?i c?u h?i</label>
                    <input
                      type="text"
                      aria-label="Lo?i c?u h?i"
                      value={assessmentDraft.question_type}
                      onChange={(e) =>
                        setAssessmentDraft((prev) => ({
                          ...prev,
                          question_type: e.target.value,
                        }))
                      }
                      placeholder="V? d?: short_answer"
                       className="theme-input rounded-[14px] px-2 py-2 text-[12px]"
                    />
                  </div>

                  <div>
                    <label className="block text-[12px] text-[#8c3451] mb-1">S? c?u</label>
                    <input
                      type="number"
                      min={1}
                      max={20}
                      aria-label="S? c?u"
                      value={assessmentDraft.num_questions}
                      onChange={(e) =>
                        setAssessmentDraft((prev) => ({
                          ...prev,
                          num_questions: Number(e.target.value) || 1,
                        }))
                      }
                       className="theme-input rounded-[14px] px-2 py-2 text-[12px]"
                    />
                  </div>
                </div>

                <div>
                  <label className="block text-[12px] text-[#8c3451] mb-1">N?i dung ch??ng h?c</label>
                  <textarea
                    value={assessmentDraft.chapter_content}
                    onChange={(e) =>
                      setAssessmentDraft((prev) => ({
                        ...prev,
                        chapter_content: e.target.value,
                      }))
                    }
                    rows={6}
                    placeholder="D?n n?i dung ch??ng h?c v?o ??y..."
                     className="theme-input min-h-[132px] resize-y rounded-[14px] px-3 py-2 text-[12px]"
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
                   className="theme-button w-full rounded-[14px] py-2 text-[12px] disabled:opacity-50"
                >
                  {assessmentLoading ? '?ang t?o...' : 'T?o c?u h?i'}
                </button>
              </div>

              {assessmentQuestions.length > 0 && (
                <div className="mt-4 border-t border-[#f2c9d4] pt-3">
                  <p className="text-[12px] font-semibold text-[#8c3451] mb-2">D? li?u c?u h?i</p>
                  <div className="max-h-[260px] overflow-y-auto border border-[#f2d5dd] rounded-[10px] bg-[#fff9fb] p-2">
                    <pre className="text-[11px] text-[#333] whitespace-pre-wrap break-words">
                      {JSON.stringify(assessmentQuestions, null, 2)}
                    </pre>
                  </div>
                </div>
              )}
            </div>

            {/* Goal Card */}
            <div className="metric-card p-5">
              <h3 className="mb-3 text-[15px] font-medium text-[#8c3451]">?? M?c ti?u</h3>
              <p className="text-[13px] text-[#333] line-clamp-3">{goal}</p>
              <p className="text-[12px] text-[#8c3451] mt-3 font-medium">Tr?nh ??: {
                level === 'beginner' ? 'Ng??i m?i' :
                level === 'intermediate' ? 'Trung c?p' : 'N?ng cao'
              }</p>
            </div>

            {/* Current Concept Card */}
            {currentConcept && (
              <div className="metric-card p-5">
                <h3 className="mb-3 text-[15px] font-medium text-[#8c3451]">?? Kh?i ni?m hi?n t?i</h3>
                {conceptLoading ? (
                  <div className="h-6 w-6 animate-spin rounded-full border-b-2 border-[#8c3451]" />
                ) : (
                  <>
                    <p className="text-[13px] font-medium text-[#333] mb-2">{currentConcept.concept_name}</p>
                    <p className="text-[12px] text-[#666] mb-3">{currentConcept.description}</p>
                    
                    <div className="mb-3">
                      <p className="text-[12px] font-medium text-[#8c3451] mb-1">?? th?nh th?o</p>
                      <div className="w-full h-2 bg-gray-200 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-[#8c3451] transition-all"
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
                      {currentConcept.status === 'complete' ? 'Ho?n th?nh' :
                       currentConcept.status === 'in_progress' ? '?ang h?c' : 'Ch?a b?t ??u'}
                    </div>
                  </>
                )}
              </div>
            )}

            {/* Learning Tips Card */}
            <div className="metric-card p-5">
              <h3 className="mb-3 text-[15px] font-medium text-[#8c3451]">?? M?o h?c t?p</h3>
              <ul className="text-[12px] text-[#666] space-y-2">
                <li>? H?i c?c c?u h?i chi ti?t</li>
                <li>? Ki?m tra ngu?n t?i li?u</li>
                <li>? Luy?n t?p c?c kh?i ni?m</li>
                <li>? Xem t?i nguy?n ???c ?? xu?t</li>
              </ul>
            </div>

            {/* Quick Actions */}
            <div className="metric-card p-5">
              <h3 className="mb-3 text-[15px] font-medium text-[#8c3451]">? H?nh ??ng nhanh</h3>
              <button
                onClick={() => navigate('/resources')}
                className="theme-button-secondary mb-2 w-full rounded-[14px] py-2 text-[12px]"
              >
                Xem t?i nguy?n
              </button>
              <button
                onClick={() => navigate('/learning-path')}
                className="theme-button-secondary w-full rounded-[14px] py-2 text-[12px]"
              >
                L? tr?nh h?c
              </button>
            </div>
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}
