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

const ASSESSMENT_QUESTION_TYPE_OPTIONS = [
  { value: 'short_answer', label: 'Trả lời ngắn' },
  { value: 'multiple_choice', label: 'Trắc nghiệm' },
  { value: 'true_false', label: 'Đúng / Sai' },
] as const;

const ASSESSMENT_DIFFICULTY_LABELS: Record<AssessmentDifficulty, string> = {
  easy: 'Dễ',
  medium: 'Trung bình',
  hard: 'Khó',
};

const getAssessmentQuestionTypeLabel = (value: string) =>
  ASSESSMENT_QUESTION_TYPE_OPTIONS.find((option) => option.value === value)?.label || value;

const ASSESSMENT_OPTION_LABELS = ['A', 'B', 'C', 'D', 'E', 'F'];

const normalizeAssessmentOptionLabel = (value: string) => {
  const normalized = value.trim().toLowerCase();
  if (normalized === 'dung' || normalized === 'true') {
    return 'Đúng';
  }
  if (normalized === 'sai' || normalized === 'false') {
    return 'Sai';
  }
  return value.trim();
};

const normalizeAssessmentAnswerValue = (value: string) =>
  value
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();

type StoredMessage = Omit<Message, 'timestamp'> & { timestamp: string };
type MessagePayload = {
  answer?: Message['answer'];
  conceptDetected?: Message['conceptDetected'];
  learning_path?: Message['learning_path'];
  adaptive_info?: Message['adaptive_info'];
} | null;
type ConceptApiRecord = {
  concept_id?: number;
  concept_name?: string;
  topic?: string;
  description?: string;
};
type ConceptProgressRecord = {
  mastery?: number;
  status?: string;
};

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
  const [isAssessmentModalOpen, setIsAssessmentModalOpen] = useState(false);
  const [activeAssessmentIndex, setActiveAssessmentIndex] = useState(0);
  const [assessmentResponses, setAssessmentResponses] = useState<string[]>([]);
  const [assessmentRevealed, setAssessmentRevealed] = useState<boolean[]>([]);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const autoStartedRef = useRef(false);

  const normalizedAssessmentDraft = {
    lessonTitle: assessmentDraft.lesson_title.trim(),
    concept: assessmentDraft.concept.trim(),
    questionType: assessmentDraft.question_type.trim(),
    chapterContent: assessmentDraft.chapter_content.trim(),
    numQuestions: Number.isFinite(assessmentDraft.num_questions) ? assessmentDraft.num_questions : 0,
  };

  const assessmentValidationMessage = (() => {
    if (!normalizedAssessmentDraft.concept) {
      return 'Cần nhập khái niệm để tạo câu hỏi.';
    }
    if (!normalizedAssessmentDraft.questionType) {
      return 'Cần chọn loại câu hỏi.';
    }
    if (!normalizedAssessmentDraft.chapterContent || normalizedAssessmentDraft.chapterContent.length < 50) {
      return 'Nội dung chương học cần ít nhất 50 ký tự.';
    }
    if (normalizedAssessmentDraft.numQuestions < 1 || normalizedAssessmentDraft.numQuestions > 20) {
      return 'Số câu hỏi phải nằm trong khoảng từ 1 đến 20.';
    }
    return null;
  })();

  const canGenerateAssessment = !assessmentLoading && !assessmentValidationMessage;
  const activeAssessmentQuestion = assessmentQuestions[activeAssessmentIndex] || null;
  const activeAssessmentChoices = (activeAssessmentQuestion?.options || []).map(normalizeAssessmentOptionLabel);
  const activeAssessmentAnswer = activeAssessmentQuestion
    ? normalizeAssessmentOptionLabel(activeAssessmentQuestion.answer)
    : '';
  const activeAssessmentResponse = assessmentResponses[activeAssessmentIndex] || '';
  const isActiveAssessmentRevealed = Boolean(assessmentRevealed[activeAssessmentIndex]);
  const isActiveAssessmentCorrect =
    isActiveAssessmentRevealed &&
    normalizeAssessmentAnswerValue(activeAssessmentResponse) === normalizeAssessmentAnswerValue(activeAssessmentAnswer);
  const answeredAssessmentCount = assessmentRevealed.filter(Boolean).length;
  const correctAssessmentCount = assessmentQuestions.reduce((count, question, index) => {
    if (!assessmentRevealed[index]) {
      return count;
    }
    const normalizedUserAnswer = normalizeAssessmentAnswerValue(assessmentResponses[index] || '');
    const normalizedCorrectAnswer = normalizeAssessmentAnswerValue(
      normalizeAssessmentOptionLabel(question.answer || ''),
    );
    return normalizedUserAnswer === normalizedCorrectAnswer ? count + 1 : count;
  }, 0);
  const incorrectAssessmentIndexes = assessmentQuestions.reduce<number[]>((indexes, question, index) => {
    if (!assessmentRevealed[index]) {
      return indexes;
    }
    const normalizedUserAnswer = normalizeAssessmentAnswerValue(assessmentResponses[index] || '');
    const normalizedCorrectAnswer = normalizeAssessmentAnswerValue(
      normalizeAssessmentOptionLabel(question.answer || ''),
    );
    if (normalizedUserAnswer !== normalizedCorrectAnswer) {
      indexes.push(index);
    }
    return indexes;
  }, []);
  const incorrectAssessmentCount = incorrectAssessmentIndexes.length;
  const allAssessmentAnswered = assessmentQuestions.length > 0 && answeredAssessmentCount === assessmentQuestions.length;

  useEffect(() => {
    if (!isAssessmentModalOpen) {
      return;
    }

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = 'hidden';

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsAssessmentModalOpen(false);
      }
    };

    window.addEventListener('keydown', handleKeyDown);

    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isAssessmentModalOpen]);

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

  /* eslint-disable react-hooks/exhaustive-deps */
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
  /* eslint-enable react-hooks/exhaustive-deps */

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

      const concept = ((conceptResponse?.concept ?? conceptResponse ?? {}) as ConceptApiRecord);
      const progress = ((progressResponse?.progress ?? {}) as ConceptProgressRecord);

      setCurrentConcept({
        concept_id: Number(concept?.concept_id ?? conceptId),
        concept_name: String(concept?.concept_name ?? `Concept ${conceptId}`),
        description: String(concept?.topic ?? concept?.description ?? 'Không có mô tả chi tiết'),
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
          answer: data.answer
            ? {
                answer_text: data.answer.answer_text ?? '',
                sources: data.answer.sources ?? [],
                confidence: data.answer.confidence ?? 0,
                latency_ms: data.answer.latency_ms ?? 0,
              }
            : undefined,
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
    setIsAssessmentModalOpen(false);
    setActiveAssessmentIndex(0);
    setAssessmentResponses([]);
    setAssessmentRevealed([]);

    if (assessmentValidationMessage) {
      setAssessmentError(assessmentValidationMessage);
      return;
    }

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

    await runAssessmentGeneration({
      user_id: user.user_id,
      lesson_title: normalizedAssessmentDraft.lessonTitle || normalizedAssessmentDraft.concept,
      concept: normalizedAssessmentDraft.concept,
      difficulty: assessmentDraft.difficulty,
      question_type: normalizedAssessmentDraft.questionType || 'short_answer',
      num_questions: normalizedAssessmentDraft.numQuestions,
      chapter_content: normalizedAssessmentDraft.chapterContent,
      retrieved_context: normalizedAssessmentDraft.chapterContent,
    });
  };

  const runAssessmentGeneration = async (
    payload: Parameters<typeof assessmentService.generateQuestions>[0],
  ) => {
    setAssessmentLoading(true);

    try {
      const response = await assessmentService.generateQuestions(payload);

      if (!response.success) {
        throw new Error('Không thể tạo câu hỏi kiểm tra');
      }

      const generatedQuestions = response.questions || [];
      if (!generatedQuestions.length) {
        throw new Error('Chưa nhận được câu hỏi nào từ hệ thống');
      }

      setAssessmentQuestions(generatedQuestions);
      setAssessmentResponses(new Array(generatedQuestions.length).fill(''));
      setAssessmentRevealed(new Array(generatedQuestions.length).fill(false));
      setActiveAssessmentIndex(0);
      setIsAssessmentModalOpen(true);
      return true;
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Đã xảy ra lỗi khi tạo câu hỏi';
      setAssessmentError(message);
      return false;
    } finally {
      setAssessmentLoading(false);
    }
  };

  const handleUpdateAssessmentResponse = (value: string) => {
    setAssessmentResponses((prev) => {
      const next = [...prev];
      next[activeAssessmentIndex] = value;
      return next;
    });

    setAssessmentRevealed((prev) => {
      if (!prev[activeAssessmentIndex]) {
        return prev;
      }
      const next = [...prev];
      next[activeAssessmentIndex] = false;
      return next;
    });
  };

  const handleRevealAssessmentAnswer = () => {
    if (!activeAssessmentResponse.trim()) {
      return;
    }

    setAssessmentRevealed((prev) => {
      const next = [...prev];
      next[activeAssessmentIndex] = true;
      return next;
    });
  };

  const handleResetAssessmentSession = () => {
    setAssessmentResponses(new Array(assessmentQuestions.length).fill(''));
    setAssessmentRevealed(new Array(assessmentQuestions.length).fill(false));
    setActiveAssessmentIndex(0);
  };

  const handleGenerateAssessmentFromMistakes = async () => {
    if (!user || incorrectAssessmentCount === 0) {
      return;
    }

    const incorrectQuestions = incorrectAssessmentIndexes.map((index) => assessmentQuestions[index]).filter(Boolean);
    const retryConcept = Array.from(
      new Set(
        incorrectQuestions
          .map((question) => question.concept?.trim())
          .filter((value): value is string => Boolean(value)),
      ),
    ).join(', ');
    const retryContext = incorrectQuestions
      .map((question) => [question.source_excerpt, question.explanation].filter(Boolean).join('\n'))
      .filter(Boolean)
      .join('\n\n');

    setAssessmentError(null);

    await runAssessmentGeneration({
      user_id: user.user_id,
      lesson_title: normalizedAssessmentDraft.lessonTitle || 'Ôn tập lỗi sai',
      concept: retryConcept || normalizedAssessmentDraft.concept,
      difficulty: assessmentDraft.difficulty,
      question_type: normalizedAssessmentDraft.questionType || 'short_answer',
      num_questions: Math.min(
        Math.max(incorrectQuestions.length, 1),
        Math.max(normalizedAssessmentDraft.numQuestions, 1),
      ),
      chapter_content: retryContext || normalizedAssessmentDraft.chapterContent,
      retrieved_context: retryContext || normalizedAssessmentDraft.chapterContent,
    });
  };

  const addMessage = (role: 'user' | 'assistant', content: string, data: MessagePayload) => {
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
          <p className="page-kicker">Trợ giảng AI</p>
          <h1 className="page-title">Trợ giảng AI</h1>
          
          <div className="mb-[40px] flex items-center gap-2">
            <div className="h-[28px] w-[3px] rounded-[5px] bg-[#8c3451]" />
            <h2 className="page-section-title text-[18px]">Bắt đầu phiên học tập</h2>
          </div>

          <div className="soft-panel max-w-[720px] p-8">
            <div className="mb-6">
              <label className="mb-3 block text-[16px] font-medium text-[#514942]">
                Mục tiêu học tập của bạn là gì?
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
                Mục tiêu chi tiết (tùy chọn)
              </label>
              <input
                type="text"
                value={goalDetail}
                onChange={(e) => setGoalDetail(e.target.value)}
                placeholder="VD: backend, OOP, cấu trúc dữ liệu..."
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
                Trình độ hiện tại
              </label>
              <select
                value={level}
                onChange={(e) => setLevel(e.target.value as 'beginner' | 'intermediate' | 'advanced')}
                className="theme-input rounded-[18px]"
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
              className="theme-button w-full justify-center text-[16px]"
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
        <div className="page-shell flex min-h-[calc(100vh-140px)] flex-col pb-6">
          <div className="mb-6 flex flex-wrap items-center justify-between gap-3">
            <div>
              <p className="page-kicker mb-2">Trợ giảng AI</p>
              <h1 className="page-title mb-0">Trợ giảng AI</h1>
            </div>
            <div className="flex flex-wrap gap-3">
            <button
              onClick={handleClearSubjectHistory}
              className="theme-button-secondary border-red-200 bg-white/90 text-red-700"
            >
              🗑️ Xóa lịch sử môn
            </button>
            <button
              onClick={() => setShowHistory(!showHistory)}
              className="theme-button-secondary"
            >
              📋 Lịch sử ({history.length})
            </button>
            <button
              onClick={() => {
                setShowGoalInput(true);
                setMessages([]);
                setGoal('');
              }}
              className="theme-button"
            >
              Phiên mới
            </button>
          </div>
        </div>

        {/* History Modal */}
        {showHistory && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/30 p-4 backdrop-blur-sm">
            <div className="white-panel flex max-h-[80vh] w-full max-w-[560px] flex-col overflow-hidden">
              <div className="flex items-center justify-between border-b border-[#8c3451]/10 p-6">
                <h2 className="text-[22px] font-medium tracking-[-0.03em] text-[#8c3451]">Lịch sử câu hỏi</h2>
                <button
                  onClick={() => setShowHistory(false)}
                  className="text-[24px] text-[#8c3451]"
                >
                  ×
                </button>
              </div>

              <div className="scroll-soft flex-1 overflow-y-auto p-4 space-y-3">
                {historyLoading ? (
                  <div className="flex items-center justify-center py-8">
                    <div className="h-8 w-8 animate-spin rounded-full border-b-2 border-[#8c3451]" />
                  </div>
                ) : history.length === 0 ? (
                  <div className="text-center py-8 text-[#666]">
                    <p>Chưa có câu hỏi nào</p>
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
                            Mục tiêu: {item.goal}
                          </p>
                          <p className="text-[10px] text-[#999]">
                            {new Date(item.timestamp).toLocaleString('vi-VN')}
                          </p>
                        </div>
                         <button
                           onClick={() => handleDeleteHistoryItem(item._id)}
                           className="rounded-full bg-red-100 px-2 py-1 text-[11px] whitespace-nowrap text-red-600 opacity-0 transition-opacity group-hover:opacity-100"
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

        <div className="flex min-h-0 flex-1 flex-col gap-6 xl:flex-row">
          {/* Main Chat Area */}
          <div className="white-panel flex min-h-[540px] flex-1 flex-col overflow-hidden">
            {/* Messages Area */}
            <div className="scroll-soft flex-1 overflow-y-auto p-6 space-y-4">
              {messages.length === 0 ? (
                <div className="flex items-center justify-center h-full">
                  <div className="text-center">
                    <div className="text-[50px] mb-4">💡</div>
                    <p className="text-[#8c3451] text-[16px]">Hãy bắt đầu bằng cách đặt một câu hỏi</p>
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
                                  <span>📚</span> Nguồn tài liệu
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
              <div className="border-t border-red-200 bg-red-50 px-6 py-3 text-[13px] text-red-700">
                ⚠️ {error}
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
                  placeholder="Nhập câu hỏi của bạn..."
                  disabled={loading}
                  className="theme-input flex-1 rounded-[18px] disabled:bg-gray-100"
                />
                <button
                  onClick={handleSendMessage}
                  disabled={loading || !input.trim()}
                  className="theme-button disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {loading ? '...' : 'Gửi'}
                </button>
              </div>
            </div>
          </div>

          {/* Right Sidebar - Learning Context */}
          <div className="flex w-full flex-col gap-4 xl:sticky xl:top-4 xl:w-[320px] xl:self-start">
            {/* Assessment Generator Card */}
            <div className="soft-panel p-5">
              <h3 className="mb-3 text-[16px] font-medium text-[#8c3451]">📝 Tạo câu hỏi kiểm tra</h3>

              <div className="space-y-3">
                <div>
                  <label className="block text-[12px] text-[#8c3451] mb-1">Tên bài học</label>
                  <input
                    type="text"
                    value={assessmentDraft.lesson_title}
                    onChange={(e) =>
                      setAssessmentDraft((prev) => ({
                        ...prev,
                        lesson_title: e.target.value,
                      }))
                    }
                    placeholder="Ví dụ: Giới thiệu về RAG"
                    className="theme-input rounded-[14px] px-3 py-2 text-[12px]"
                  />
                </div>

                <div>
                  <label className="block text-[12px] text-[#8c3451] mb-1">Khái niệm</label>
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
                    className="theme-input rounded-[14px] px-3 py-2 text-[12px]"
                  />
                </div>

                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <label className="block text-[12px] text-[#8c3451] mb-1">Độ khó</label>
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
                      <option value="easy">Dễ</option>
                      <option value="medium">Trung bình</option>
                      <option value="hard">Khó</option>
                    </select>
                  </div>

                  <div>
                    <label className="block text-[12px] text-[#8c3451] mb-1">Loại câu hỏi</label>
                    <select
                      aria-label="Loại câu hỏi"
                      value={assessmentDraft.question_type}
                      onChange={(e) =>
                        setAssessmentDraft((prev) => ({
                          ...prev,
                          question_type: e.target.value,
                        }))
                      }
                      className="theme-input rounded-[14px] px-2 py-2 text-[12px]"
                    >
                      {ASSESSMENT_QUESTION_TYPE_OPTIONS.map((option) => (
                        <option key={option.value} value={option.value}>
                          {option.label}
                        </option>
                      ))}
                    </select>
                  </div>

                  <div>
                    <label className="block text-[12px] text-[#8c3451] mb-1">Số câu</label>
                    <input
                      type="number"
                      min={1}
                      max={20}
                      aria-label="Số câu"
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
                  <label className="block text-[12px] text-[#8c3451] mb-1">Nội dung chương học</label>
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
                     className="theme-input min-h-[132px] resize-y rounded-[14px] px-3 py-2 text-[12px]"
                  />
                </div>

                <div
                  className={`rounded-[12px] border px-3 py-2 text-[12px] ${
                    assessmentValidationMessage
                      ? 'border-amber-200 bg-amber-50 text-amber-800'
                      : 'border-emerald-200 bg-emerald-50 text-emerald-700'
                  }`}
                >
                  {assessmentValidationMessage || 'Đã đủ thông tin. Bấm tạo để mở popup card câu hỏi.'}
                </div>

                {assessmentError && (
                  <div className="text-[12px] text-red-700 bg-red-50 border border-red-200 rounded-[8px] px-2 py-2">
                    {assessmentError}
                  </div>
                )}

                <button
                  onClick={handleGenerateAssessment}
                  disabled={!canGenerateAssessment}
                   className="theme-button w-full rounded-[14px] py-2 text-[12px] disabled:opacity-50"
                >
                  {assessmentLoading ? 'Đang tạo...' : 'Tạo câu hỏi'}
                </button>
              </div>

              {assessmentQuestions.length > 0 && (
                <div className="mt-4 border-t border-[#f2c9d4] pt-3">
                  <p className="text-[12px] font-semibold text-[#8c3451] mb-2">Dữ liệu câu hỏi</p>
                  <div className="hidden max-h-[260px] overflow-y-auto border border-[#f2d5dd] rounded-[10px] bg-[#fff9fb] p-2">
                    <pre className="text-[11px] text-[#333] whitespace-pre-wrap break-words">
                      {JSON.stringify(assessmentQuestions, null, 2)}
                    </pre>
                  </div>
                  <div className="rounded-[12px] border border-[#f2d5dd] bg-[#fff9fb] p-3 text-[12px] text-[#5c4350]">
                    Đã tạo {assessmentQuestions.length} câu hỏi. Nhấn nút dưới để xem popup card.
                  </div>
                  <button
                    type="button"
                    onClick={() => {
                      setActiveAssessmentIndex(0);
                      setIsAssessmentModalOpen(true);
                    }}
                    className="theme-button-secondary mt-3 w-full rounded-[14px] py-2 text-[12px]"
                  >
                    Xem bộ câu hỏi
                  </button>
                </div>
              )}
            </div>

            {/* Goal Card */}
            <div className="metric-card p-5">
              <h3 className="mb-3 text-[15px] font-medium text-[#8c3451]">📚 Mục tiêu</h3>
              <p className="text-[13px] text-[#333] line-clamp-3">{goal}</p>
              <p className="text-[12px] text-[#8c3451] mt-3 font-medium">Trình độ: {
                level === 'beginner' ? 'Người mới' :
                level === 'intermediate' ? 'Trung cấp' : 'Nâng cao'
              }</p>
            </div>

            {/* Current Concept Card */}
            {currentConcept && (
              <div className="metric-card p-5">
                <h3 className="mb-3 text-[15px] font-medium text-[#8c3451]">🎯 Khái niệm hiện tại</h3>
                {conceptLoading ? (
                  <div className="h-6 w-6 animate-spin rounded-full border-b-2 border-[#8c3451]" />
                ) : (
                  <>
                    <p className="text-[13px] font-medium text-[#333] mb-2">{currentConcept.concept_name}</p>
                    <p className="text-[12px] text-[#666] mb-3">{currentConcept.description}</p>
                    
                    <div className="mb-3">
                      <p className="text-[12px] font-medium text-[#8c3451] mb-1">Độ thành thạo</p>
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
                      {currentConcept.status === 'complete' ? 'Hoàn thành' :
                       currentConcept.status === 'in_progress' ? 'Đang học' : 'Chưa bắt đầu'}
                    </div>
                  </>
                )}
              </div>
            )}

            {/* Learning Tips Card */}
            <div className="metric-card p-5">
              <h3 className="mb-3 text-[15px] font-medium text-[#8c3451]">💡 Mẹo học tập</h3>
              <ul className="text-[12px] text-[#666] space-y-2">
                <li>✓ Hỏi các câu hỏi chi tiết</li>
                <li>✓ Kiểm tra nguồn tài liệu</li>
                <li>✓ Luyện tập các khái niệm</li>
                <li>✓ Xem tài nguyên được đề xuất</li>
              </ul>
            </div>

            {/* Quick Actions */}
            <div className="metric-card p-5">
              <h3 className="mb-3 text-[15px] font-medium text-[#8c3451]">⚡ Hành động nhanh</h3>
              <button
                onClick={() => navigate('/resources')}
                className="theme-button-secondary mb-2 w-full rounded-[14px] py-2 text-[12px]"
              >
                Xem tài nguyên
              </button>
              <button
                onClick={() => navigate('/learning-path')}
                className="theme-button-secondary w-full rounded-[14px] py-2 text-[12px]"
              >
                Lộ trình học
              </button>
            </div>
          </div>
        </div>

        {isAssessmentModalOpen && activeAssessmentQuestion && (
          <div className="fixed inset-0 z-[60] flex items-center justify-center bg-black/35 p-4 backdrop-blur-sm">
            <div className="white-panel flex max-h-[90vh] w-full max-w-[760px] flex-col overflow-hidden">
              <div className="flex items-start justify-between gap-4 border-b border-[#8c3451]/10 p-6">
                <div>
                  <p className="text-[12px] font-medium uppercase tracking-[0.24em] text-[#b26a83]">
                    Bộ câu hỏi kiểm tra
                  </p>
                  <h2 className="mt-2 text-[26px] font-medium tracking-[-0.03em] text-[#8c3451]">
                    Câu {activeAssessmentIndex + 1}/{assessmentQuestions.length}
                  </h2>
                </div>
                <button
                  type="button"
                  onClick={() => setIsAssessmentModalOpen(false)}
                  className="theme-button-secondary rounded-full px-4 py-2 text-[12px]"
                >
                  Đóng
                </button>
              </div>

              <div className="scroll-soft flex-1 space-y-4 overflow-y-auto p-6">
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-[22px] border border-[#f2d5dd] bg-[#fff9fb] p-4">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#b26a83]">
                      Đã chấm
                    </p>
                    <p className="mt-2 text-[24px] font-medium text-[#8c3451]">
                      {answeredAssessmentCount}/{assessmentQuestions.length}
                    </p>
                  </div>
                  <div className="rounded-[22px] border border-[#d8eee3] bg-[#f5fffa] p-4">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#3d8c6a]">
                      Trả lời đúng
                    </p>
                    <p className="mt-2 text-[24px] font-medium text-[#2e7355]">
                      {correctAssessmentCount}
                    </p>
                  </div>
                  <div className="rounded-[22px] border border-[#e6d9f6] bg-[#fbf8ff] p-4">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8d69b2]">
                      Tỉ lệ hiện tại
                    </p>
                    <p className="mt-2 text-[24px] font-medium text-[#6f59c0]">
                      {answeredAssessmentCount > 0 ? Math.round((correctAssessmentCount / answeredAssessmentCount) * 100) : 0}%
                    </p>
                  </div>
                </div>

                {allAssessmentAnswered && (
                  <div className="rounded-[28px] border border-[#e7d4db] bg-[linear-gradient(135deg,rgba(255,249,251,0.98),rgba(250,243,255,0.96))] p-5 shadow-[0_18px_50px_rgba(140,52,81,0.1)]">
                    <p className="text-[12px] font-medium uppercase tracking-[0.18em] text-[#b26a83]">
                      Tổng kết bộ đề
                    </p>
                    <h3 className="mt-2 text-[24px] font-medium leading-[1.4] text-[#2b1f26]">
                      {correctAssessmentCount}/{assessmentQuestions.length} câu đúng
                    </h3>
                    <p className="mt-2 text-[14px] leading-[1.7] text-[#6e5a63]">
                      {incorrectAssessmentCount === 0
                        ? 'Bạn đã hoàn thành rất tốt. Có thể làm lại bộ đề để luyện phản xạ hoặc tạo bộ mới khó hơn.'
                        : `Bạn còn ${incorrectAssessmentCount} câu cần cải thiện. Mình đã chuẩn bị sẵn nút ôn tập theo đúng các lỗi sai này.`}
                    </p>
                    <div className="mt-4 flex flex-wrap gap-3">
                      {incorrectAssessmentCount > 0 && (
                        <button
                          type="button"
                          onClick={() => setActiveAssessmentIndex(incorrectAssessmentIndexes[0] ?? 0)}
                          className="theme-button-secondary rounded-[14px] px-4 py-2 text-[12px]"
                        >
                          Xem câu sai đầu tiên
                        </button>
                      )}
                      <button
                        type="button"
                        onClick={handleGenerateAssessmentFromMistakes}
                        disabled={incorrectAssessmentCount === 0 || assessmentLoading}
                        className="theme-button rounded-[14px] px-4 py-2 text-[12px] disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {assessmentLoading ? 'Đang tạo lại...' : 'Tạo bộ đề mới theo lỗi sai'}
                      </button>
                    </div>
                  </div>
                )}

                <div className="flex flex-wrap gap-2">
                  <span className="rounded-full bg-[#fdf0f5] px-3 py-1 text-[12px] font-medium text-[#8c3451]">
                    {activeAssessmentQuestion.concept || normalizedAssessmentDraft.concept || 'Khái niệm tổng hợp'}
                  </span>
                  <span className="rounded-full bg-[#f7f3ff] px-3 py-1 text-[12px] font-medium text-[#6f59c0]">
                    {ASSESSMENT_DIFFICULTY_LABELS[activeAssessmentQuestion.difficulty] || activeAssessmentQuestion.difficulty}
                  </span>
                  <span className="rounded-full bg-[#eef9ff] px-3 py-1 text-[12px] font-medium text-[#2f6b9a]">
                    {getAssessmentQuestionTypeLabel(activeAssessmentQuestion.question_type)}
                  </span>
                </div>

                <div className="rounded-[28px] border border-[#f2d5dd] bg-[#fff9fb] p-5">
                  <p className="text-[12px] font-medium uppercase tracking-[0.18em] text-[#b26a83]">
                    Câu hỏi
                  </p>
                  <p className="mt-3 text-[22px] font-medium leading-[1.5] text-[#2b1f26]">
                    {activeAssessmentQuestion.question}
                  </p>
                </div>

                {activeAssessmentChoices.length > 0 && (
                  <div className="grid gap-3 sm:grid-cols-2">
                    {activeAssessmentChoices.map((choice, choiceIndex) => (
                      <button
                        type="button"
                        key={`${choice}-${choiceIndex}`}
                        onClick={() => handleUpdateAssessmentResponse(choice)}
                        className={`rounded-[22px] border bg-white p-4 text-left shadow-[0_10px_30px_rgba(140,52,81,0.08)] transition-all ${
                          activeAssessmentResponse === choice
                            ? 'border-[#8c3451] ring-2 ring-[#8c3451]/15'
                            : 'border-[#ead6dd] hover:border-[#d7a6b7]'
                        } ${
                          isActiveAssessmentRevealed && choice === activeAssessmentAnswer
                            ? 'border-emerald-300 bg-emerald-50'
                            : ''
                        } ${
                          isActiveAssessmentRevealed &&
                          activeAssessmentResponse === choice &&
                          choice !== activeAssessmentAnswer
                            ? 'border-red-300 bg-red-50'
                            : ''
                        }`}
                      >
                        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#b26a83]">
                          {ASSESSMENT_OPTION_LABELS[choiceIndex] || `Lựa chọn ${choiceIndex + 1}`}
                        </p>
                        <p className="mt-2 text-[15px] leading-[1.6] text-[#43313a]">{choice}</p>
                      </button>
                    ))}
                  </div>
                )}

                {activeAssessmentChoices.length === 0 && (
                  <div className="rounded-[24px] border border-[#ead6dd] bg-white p-5 shadow-[0_10px_30px_rgba(140,52,81,0.08)]">
                    <p className="text-[12px] font-medium uppercase tracking-[0.18em] text-[#b26a83]">
                      Câu trả lời của bạn
                    </p>
                    <textarea
                      value={activeAssessmentResponse}
                      onChange={(event) => handleUpdateAssessmentResponse(event.target.value)}
                      rows={5}
                      placeholder="Nhập câu trả lời ngắn của bạn..."
                      className="theme-input mt-3 min-h-[120px] w-full resize-y rounded-[18px] px-4 py-3 text-[14px]"
                    />
                  </div>
                )}

                <div className="grid gap-4 md:grid-cols-2">
                  <div
                    className={`rounded-[24px] border p-5 ${
                      !isActiveAssessmentRevealed
                        ? 'border-[#f0e6f5] bg-[#fbf8ff]'
                        : isActiveAssessmentCorrect
                          ? 'border-emerald-200 bg-emerald-50'
                          : 'border-red-200 bg-red-50'
                    }`}
                  >
                    <p className="text-[12px] font-medium uppercase tracking-[0.18em] text-[#8d69b2]">
                      Kết quả câu này
                    </p>
                    {!isActiveAssessmentRevealed ? (
                      <p className="mt-3 text-[15px] leading-[1.7] text-[#5f5470]">
                        Chọn hoặc nhập đáp án của bạn rồi bấm kiểm tra để xem kết quả.
                      </p>
                    ) : (
                      <>
                        <p
                          className={`mt-3 inline-flex rounded-full px-3 py-1 text-[12px] font-medium ${
                            isActiveAssessmentCorrect
                              ? 'bg-emerald-100 text-emerald-700'
                              : 'bg-red-100 text-red-700'
                          }`}
                        >
                          {isActiveAssessmentCorrect ? 'Bạn trả lời đúng' : 'Bạn cần cải thiện câu này'}
                        </p>
                        <p className="mt-3 text-[14px] text-[#5f5470]">
                          Câu trả lời của bạn: <span className="font-medium text-[#2b1f26]">{activeAssessmentResponse || 'Chưa trả lời'}</span>
                        </p>
                        <p className="mt-2 text-[15px] leading-[1.7] text-[#3e3150]">
                          Đáp án đúng: {activeAssessmentAnswer || 'Chưa có đáp án gợi ý.'}
                        </p>
                      </>
                    )}
                  </div>

                  <div className="rounded-[24px] border border-[#d8eee3] bg-[#f5fffa] p-5">
                    <p className="text-[12px] font-medium uppercase tracking-[0.18em] text-[#3d8c6a]">
                      Giải thích
                    </p>
                    {isActiveAssessmentRevealed ? (
                      <p className="mt-3 text-[15px] leading-[1.7] text-[#285542]">
                        {activeAssessmentQuestion.explanation || 'Chưa có giải thích chi tiết.'}
                      </p>
                    ) : (
                      <p className="mt-3 text-[15px] leading-[1.7] text-[#4e7a67]">
                        Phần giải thích sẽ hiện sau khi bạn tự trả lời và bấm kiểm tra.
                      </p>
                    )}
                  </div>
                </div>

                <div className="rounded-[24px] border border-[#f0e1c9] bg-[#fffaf1] p-5">
                  <p className="text-[12px] font-medium uppercase tracking-[0.18em] text-[#a2752a]">
                    Đoạn nội dung tham chiếu
                  </p>
                  <p className="mt-3 whitespace-pre-wrap text-[14px] leading-[1.7] text-[#5f4b2a]">
                    {activeAssessmentQuestion.source_excerpt || normalizedAssessmentDraft.chapterContent || 'Chưa có đoạn trích nguồn.'}
                  </p>
                </div>
              </div>

              <div className="flex flex-wrap items-center justify-between gap-3 border-t border-[#8c3451]/10 bg-[#fff6fa] p-6">
                <p className="text-[13px] text-[#7d5d68]">
                  Bạn có thể làm từng câu, kiểm tra ngay trong popup và theo dõi tiến độ của cả bộ câu hỏi.
                </p>
                <div className="flex flex-wrap gap-3">
                  <button
                    type="button"
                    onClick={handleResetAssessmentSession}
                    disabled={assessmentQuestions.length === 0}
                    className="theme-button-secondary rounded-[14px] px-4 py-2 text-[12px] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Làm lại bộ câu hỏi
                  </button>
                  <button
                    type="button"
                    onClick={handleRevealAssessmentAnswer}
                    disabled={!activeAssessmentResponse.trim()}
                    className="theme-button rounded-[14px] px-4 py-2 text-[12px] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {isActiveAssessmentRevealed ? 'Xem lại kết quả' : 'Kiểm tra đáp án'}
                  </button>
                  <button
                    type="button"
                    onClick={() => setActiveAssessmentIndex((prev) => Math.max(prev - 1, 0))}
                    disabled={activeAssessmentIndex === 0}
                    className="theme-button-secondary rounded-[14px] px-4 py-2 text-[12px] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Câu trước
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      setActiveAssessmentIndex((prev) => Math.min(prev + 1, assessmentQuestions.length - 1))
                    }
                    disabled={activeAssessmentIndex === assessmentQuestions.length - 1}
                    className="theme-button rounded-[14px] px-4 py-2 text-[12px] disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    Câu tiếp
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </DashboardLayout>
  );
}
