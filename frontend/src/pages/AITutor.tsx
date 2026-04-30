import { useState, useEffect, useRef } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useNavigate, useSearchParams } from 'react-router-dom';
import DashboardLayout from '../components/layout/DashboardLayout';
import PageHero from '../components/ui/PageHero';
import StatusPanel from '../components/ui/StatusPanel';
import { useAuth } from '../contexts/AuthContext';
import { useSubjects } from '../hooks/useSubjects';
import { apiClient } from '../utils/apiClient';
import { learningPathService } from '../services';
import {
  buildSubjectGoal,
  findSubjectById,
  matchSubjectByGoalPrefix,
  stripSubjectPrefixFromGoal,
} from '../utils/subjects';

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

type TutorMode = 'explain' | 'practice' | 'summarize';

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

const LEVEL_META = {
  beginner: {
    label: 'Người mới',
    description: 'Ưu tiên giải thích nền tảng, ví dụ ngắn và nhịp học chậm hơn.',
  },
  intermediate: {
    label: 'Trung cấp',
    description: 'Đi thẳng vào mối liên hệ giữa các khái niệm và cách áp dụng.',
  },
  advanced: {
    label: 'Nâng cao',
    description: 'Tập trung vào trade-off, tối ưu hóa và tình huống thực tế.',
  },
} as const;

const SESSION_SETUP_NOTES = [
  'Chọn đúng môn để AI bám vào ngữ cảnh lộ trình và tài nguyên liên quan.',
  'Thêm mục tiêu chi tiết nếu bạn muốn câu trả lời tập trung hơn vào một nhánh kiến thức.',
  'Có thể đổi phiên học bất cứ lúc nào mà không ảnh hưởng đến các màn khác.',
] as const;

const TUTOR_MODE_META: Record<
  TutorMode,
  { label: string; shortLabel: string; description: string; helper: string }
> = {
  explain: {
    label: 'Giải thích',
    shortLabel: 'Giải thích',
    description:
      'Ưu tiên trả lời có cấu trúc, giải thích khái niệm và nối lại với bối cảnh học hiện tại.',
    helper:
      'Phù hợp khi bạn cần hiểu rõ một khái niệm trước khi làm bài hoặc chuyển sang lesson tiếp theo.',
  },
  practice: {
    label: 'Luyện tập',
    shortLabel: 'Luyện tập',
    description:
      'Đẩy mạnh ví dụ, câu hỏi gợi mở và bước kiểm tra nhanh ngay trong cuộc hội thoại.',
    helper:
      'Dùng khi bạn muốn tự trả lời từng bước và nhận gợi ý thay vì đọc lời giải hoàn chỉnh.',
  },
  summarize: {
    label: 'Tóm tắt',
    shortLabel: 'Tóm tắt',
    description: 'Rút gọn nội dung thành ý chính, checklist và thứ tự học tiếp theo.',
    helper: 'Phù hợp cho lúc ôn tập nhanh, chuẩn bị quiz hoặc tổng kết trước khi chuyển chủ đề.',
  },
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

const saveStoredMessages = (
  userId: string,
  subjectKey: string,
  goalKey: string,
  messages: Message[],
) => {
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
  const { subjects } = useSubjects();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();

  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [goal, setGoal] = useState('');
  const [subjectId, setSubjectId] = useState('');
  const [goalDetail, setGoalDetail] = useState('');
  const [level, setLevel] = useState<'beginner' | 'intermediate' | 'advanced'>('beginner');
  const [tutorMode, setTutorMode] = useState<TutorMode>('explain');
  const [showGoalInput, setShowGoalInput] = useState(!goal);
  const [currentConcept, setCurrentConcept] = useState<ConceptInfo | null>(null);
  const [conceptLoading, setConceptLoading] = useState(false);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const composerRef = useRef<HTMLTextAreaElement>(null);
  const autoStartedRef = useRef(false);
  const currentSubject =
    findSubjectById(subjects, subjectId) ||
    matchSubjectByGoalPrefix(subjects, searchParams.get('goal')) ||
    matchSubjectByGoalPrefix(subjects, goal) ||
    subjects[0] ||
    null;
  const activeSubjectId = currentSubject?.id || '';
  const subjectGoalContext = goal || searchParams.get('goal') || '';
  const activeSubjectGoalDetail = stripSubjectPrefixFromGoal(
    subjects,
    currentSubject?.id || activeSubjectId,
    subjectGoalContext,
  );
  const formatSubjectOptionLabel = (label: string, detail?: string) => {
    const normalizedDetail = (detail || '').trim();
    return normalizedDetail ? `${label} - ${normalizedDetail}` : label;
  };
  const subjectOptions = subjects.map((subject) => ({
    id: subject.id,
    label: formatSubjectOptionLabel(
      subject.label,
      currentSubject?.id === subject.id ? activeSubjectGoalDetail : '',
    ),
  }));

  useEffect(() => {
    if (!subjectId && subjects[0]?.id) {
      setSubjectId(subjects[0].id);
    }
  }, [subjectId, subjects]);

  const renderMessageContent = (text: string) => (
    <ReactMarkdown
      remarkPlugins={[remarkGfm]}
      components={{
        h1: ({ children }) => (
          <h1 className="text-[18px] font-bold mb-3 mt-4 text-[#1a1a1a]">{children}</h1>
        ),
        h2: ({ children }) => (
          <h2 className="text-[16px] font-bold mb-2 mt-3 text-[#2a2a2a]">{children}</h2>
        ),
        h3: ({ children }) => (
          <h3 className="text-[15px] font-semibold mb-2 mt-2 text-[#333]">{children}</h3>
        ),
        p: ({ children }) => (
          <p className="text-[14px] leading-[1.6] mb-3 last:mb-0 text-[#444]">{children}</p>
        ),
        ul: ({ children }) => (
          <ul className="list-disc pl-6 mb-3 space-y-1.5 text-[#444]">{children}</ul>
        ),
        ol: ({ children }) => (
          <ol className="list-decimal pl-6 mb-3 space-y-1.5 text-[#444]">{children}</ol>
        ),
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
        thead: ({ children }) => <thead className="bg-[#f3f4f6]">{children}</thead>,
        tbody: ({ children }) => <tbody>{children}</tbody>,
        tr: ({ children }) => <tr className="border-b border-[#ddd]">{children}</tr>,
        th: ({ children }) => (
          <th className="border border-[#ddd] px-3 py-2 text-left font-semibold">{children}</th>
        ),
        td: ({ children }) => <td className="border border-[#ddd] px-3 py-2">{children}</td>,
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
    const resolvedSubject =
      (subjectParam ? findSubjectById(subjects, subjectParam) : null) ||
      matchSubjectByGoalPrefix(subjects, goalParam) ||
      findSubjectById(subjects, subjectId) ||
      matchSubjectByGoalPrefix(subjects, goal) ||
      subjects[0] ||
      null;
    const subjectKey = resolvedSubject?.id || subjectId;
    const goalKey = goalParam || '';
    if (resolvedSubject?.id && resolvedSubject.id !== subjectId) {
      setSubjectId(resolvedSubject.id);
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
            null,
          );
        }
        loadHistory();
      }
    }
  }, [goal, navigate, searchParams, subjectId, subjects, user]);
  /* eslint-enable react-hooks/exhaustive-deps */

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    if (!user || showGoalInput || !activeSubjectId || !goal || messages.length === 0) return;
    saveStoredMessages(user.user_id, activeSubjectId, goal, messages);
  }, [activeSubjectId, messages, user, showGoalInput, goal]);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const loadConceptInfo = async (conceptId: number) => {
    setConceptLoading(true);
    try {
      const [conceptResponse, progressResponse] = await Promise.all([
        learningPathService.getConceptDetails(conceptId),
        user
          ? learningPathService.getConceptProgress(conceptId, user.user_id)
          : Promise.resolve(null),
      ]);

      const concept = (conceptResponse?.concept ?? conceptResponse ?? {}) as ConceptApiRecord;
      const progress = (progressResponse?.progress ?? {}) as ConceptProgressRecord;

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
      const response = (await apiClient.delete(`/ask/history/${historyId}`)) as {
        success: boolean;
      };
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

  const handleStartChat = () => {
    const nextGoal = buildSubjectGoal(subjects, activeSubjectId, goalDetail);
    if (!nextGoal) {
      setError('Vui lòng chọn môn học');
      return;
    }
    setGoal(nextGoal);
    setShowGoalInput(false);
    setError(null);
    if (user) {
      const cachedMessages = loadStoredMessages(user.user_id, activeSubjectId, nextGoal);
      if (cachedMessages.length > 0) {
        setMessages(cachedMessages);
      } else {
        setMessages([]);
        addMessage(
          'assistant',
          `Xin chào! Tôi sẽ giúp bạn học: "${nextGoal}". Hãy đặt bất kỳ câu hỏi nào về chủ đề này.`,
          null,
        );
      }
    } else {
      setMessages([]);
      addMessage(
        'assistant',
        `Xin chào! Tôi sẽ giúp bạn học: "${nextGoal}". Hãy đặt bất kỳ câu hỏi nào về chủ đề này.`,
        null,
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

    clearStoredMessages(user.user_id, activeSubjectId, goal);
    setMessages([]);
    if (goal) {
      addMessage(
        'assistant',
        `Xin chào! Tôi sẽ giúp bạn học: "${goal}". Hãy đặt bất kỳ câu hỏi nào về chủ đề này.`,
        null,
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
        subject_id: activeSubjectId || undefined,
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
        addMessage(
          'assistant',
          data.answer?.answer_text || 'Xin lỗi, tôi không thể trả lời câu hỏi này lúc này.',
          {
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
          },
        );
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

  const currentLevelMeta = LEVEL_META[level];
  const activeTutorMode = TUTOR_MODE_META[tutorMode];
  const sessionQuestionCount = messages.filter((message) => message.role === 'user').length;
  const latestSourceCount =
    [...messages]
      .reverse()
      .find((message) => (message.answer?.sources?.length || 0) > 0)?.answer?.sources?.length || 0;
  const historyPreview = history.slice(0, 3);
  const activeGoalDetail = goalDetail.trim() || 'Chưa có mục tiêu chi tiết';
  const aiReadyContext = [
    {
      label: 'Môn học',
      value: currentSubject?.label || 'Chưa chọn',
      detail: currentSubject?.goal || 'Chọn môn để AI bám đúng ngữ cảnh.',
    },
    {
      label: 'Mục tiêu',
      value: goal || activeGoalDetail,
      detail: goal ? 'Đang được dùng cho phiên hiện tại.' : 'Sẽ được đưa vào phiên mới sau khi bắt đầu.',
    },
    {
      label: 'Chế độ Tutor',
      value: activeTutorMode.shortLabel,
      detail: activeTutorMode.helper,
    },
  ];
  const tutorModePrompts = {
    explain: currentConcept
      ? [
          `Giải thích ${currentConcept.concept_name} theo cách đơn giản và nối với mục tiêu hiện tại.`,
          `Vì sao ${currentConcept.concept_name} quan trọng trong lộ trình tôi đang học?`,
        ]
      : [
          `Giải thích khái niệm chính của ${currentSubject?.label || 'môn học này'} theo cách dễ hiểu.`,
          'Chia chủ đề này thành các ý chính và quan hệ giữa chúng.',
        ],
    practice: currentConcept
      ? [
          `Đặt cho tôi 3 câu hỏi luyện tập nhanh về ${currentConcept.concept_name}.`,
          `Cho tôi một bài tập ngắn để tự kiểm tra ${currentConcept.concept_name}.`,
        ]
      : [
          'Tạo cho tôi một bài luyện tập ngắn phù hợp với trình độ hiện tại.',
          'Hỏi tôi từng bước để tôi tự giải thay vì đưa đáp án ngay.',
        ],
    summarize: goal
      ? [
          `Tóm tắt những gì quan trọng nhất để đạt mục tiêu "${goal}".`,
          'Rút gọn buổi học này thành checklist ôn tập 5 ý.',
        ]
      : [
          'Tóm tắt chủ đề này thành checklist ngắn để ôn tập.',
          'Cho tôi thứ tự học tiếp theo dưới dạng 3 bước.',
        ],
  } as const;
  const quickPromptSuggestions = Array.from(
    new Set(
      [
        ...tutorModePrompts[tutorMode],
        currentConcept
          ? `Giải thích lại ${currentConcept.concept_name} bằng một ví dụ thật ngắn.`
          : '',
        currentConcept
          ? `Cho tôi 3 lỗi thường gặp khi học ${currentConcept.concept_name}.`
          : '',
        goal ? `Tóm tắt giúp tôi những ý quan trọng nhất để đạt mục tiêu "${goal}".` : '',
        'Từ phần đã trao đổi, tôi nên học tiếp theo thứ tự nào?',
      ].filter(Boolean),
    ),
  );

  const handleUsePrompt = (prompt: string) => {
    setInput(prompt);
    setError(null);
    window.requestAnimationFrame(() => composerRef.current?.focus());
  };

  useEffect(() => {
    if (!composerRef.current) {
      return;
    }

    composerRef.current.style.height = '0px';
    composerRef.current.style.height = `${Math.min(composerRef.current.scrollHeight, 180)}px`;
  }, [input]);

  if (showGoalInput) {
    return (
      <DashboardLayout>
        <div className="page-shell desktop-1440-ai-tutor pb-6">
          <PageHero
            className="mb-6"
            kicker="Thiết lập phiên học"
            title="Khởi tạo một phiên chat đúng ngữ cảnh trước khi hỏi."
            description=""
            actions={
              <>
                <span className="demo-pill">{currentSubject?.label || 'Môn học hiện tại'}</span>
                <span className="demo-pill">{currentLevelMeta.label}</span>
                <span className="demo-pill">{activeTutorMode.shortLabel}</span>
                <span className="demo-pill">Sẵn sàng chat theo mục tiêu</span>
              </>
            }
            metrics={[
              {
                label: 'Môn học',
                value: currentSubject?.label || 'Chưa chọn',
                detail: currentSubject?.goal || 'Chọn môn để hệ thống lấy mục tiêu nền.',
              },
              {
                label: 'Mục tiêu chi tiết',
                value: goalDetail.trim() ? 'Đã cá nhân hóa' : 'Đang dùng mục tiêu mặc định',
                detail: activeGoalDetail,
              },
              {
                label: 'Mức độ hỗ trợ',
                value: `${currentLevelMeta.label} • ${activeTutorMode.shortLabel}`,
                detail: activeTutorMode.helper,
              },
            ]}
          />

          <div className="grid gap-6">
            <div className="white-panel p-6 sm:p-8">
              <div className="mb-6 max-w-2xl">
                <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-[#b07a8e]">
                  Bắt đầu phiên học
                </p>
                <h2 className="mt-3 text-[26px] font-semibold tracking-[-0.04em] text-[#17141a] sm:text-[30px]">
                  Thiết lập vài tín hiệu trước khi trao đổi
                </h2>
                <p className="mt-3 text-[13px] leading-5 text-[#6b615d]">Chọn môn, mode và bắt đầu.</p>
              </div>

              <div className="mb-6 rounded-[24px] border border-[#f0d7e0] bg-[#fff8fb] p-4">
                <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                  <div className="max-w-[520px]">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8c3451]/55">
                      Chế độ Tutor
                    </p>
                    <h3 className="mt-2 text-[20px] font-semibold tracking-[-0.03em] text-[#17141a]">
                      AI sẽ hỗ trợ theo cách nào?
                    </h3>
                    <p className="mt-2 text-[13px] leading-5 text-[#6f5260]">
                      {activeTutorMode.description}
                    </p>
                  </div>
                  <div className="flex flex-wrap gap-2">
                    {(Object.keys(TUTOR_MODE_META) as TutorMode[]).map((mode) => {
                      const isActive = mode === tutorMode;
                      return (
                        <button
                          key={mode}
                          type="button"
                          onClick={() => setTutorMode(mode)}
                          className={`rounded-full border px-4 py-2 text-[12px] font-semibold transition ${
                            isActive
                              ? 'border-[#8c3451] bg-[#8c3451] text-white shadow-[0_12px_24px_rgba(140,52,81,0.18)]'
                              : 'border-[#ead6dd] bg-white text-[#6f5260] hover:bg-[#fff7fb]'
                          }`}
                        >
                          {TUTOR_MODE_META[mode].label}
                        </button>
                      );
                    })}
                  </div>
                </div>
                <p className="mt-4 text-[12px] leading-5 text-[#7d666f]">{activeTutorMode.helper}</p>
              </div>

              {error ? (
                <StatusPanel className="mb-6 px-4 py-3 shadow-none" tone="error" description={error} />
              ) : null}

              <div className="grid gap-4 lg:grid-cols-2">
                <label className="space-y-2">
                  <span className="text-[12px] font-medium text-[#6f5260]">Môn học</span>
                  <select
                    value={activeSubjectId}
                    onChange={(e) => setSubjectId(e.target.value)}
                    className="theme-input rounded-[18px]"
                  >
                    {subjectOptions.map((subject) => (
                      <option key={subject.id} value={subject.id}>
                        {subject.label}
                      </option>
                    ))}
                  </select>
                </label>

                <label className="space-y-2">
                  <span className="text-[12px] font-medium text-[#6f5260]">Trình độ hiện tại</span>
                  <select
                    value={level}
                    onChange={(e) =>
                      setLevel(e.target.value as 'beginner' | 'intermediate' | 'advanced')
                    }
                    className="theme-input rounded-[18px]"
                  >
                    <option value="beginner">Người mới bắt đầu</option>
                    <option value="intermediate">Trung cấp</option>
                    <option value="advanced">Nâng cao</option>
                  </select>
                </label>

                <label className="space-y-2 lg:col-span-2">
                  <span className="text-[12px] font-medium text-[#6f5260]">Mục tiêu chi tiết</span>
                  <input
                    type="text"
                    value={goalDetail}
                    onChange={(e) => setGoalDetail(e.target.value)}
                    placeholder="Ví dụ: backend, OOP, cấu trúc dữ liệu, React hooks..."
                    className="theme-input rounded-[18px]"
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') {
                        e.preventDefault();
                        handleStartChat();
                      }
                    }}
                  />
                </label>
              </div>

              <div className="mt-6 flex flex-col gap-3 sm:flex-row">
                <button
                  onClick={handleStartChat}
                  className="theme-button w-full justify-center text-[15px] sm:w-auto"
                >
                  Bắt đầu phiên chat
                </button>
                <button
                  type="button"
                  onClick={() => setGoalDetail('')}
                  className="theme-button-secondary w-full justify-center text-[15px] sm:w-auto"
                >
                  Xóa mục tiêu chi tiết
                </button>
              </div>

              <div className="mt-6 rounded-[24px] border border-[#ead6dd] bg-white/80 p-5">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8c3451]/55">
                      Gợi ý nhanh
                    </p>
                    <p className="mt-2 text-[12px] leading-5 text-[#6f5260]">Chạm để bắt đầu nhanh.</p>
                  </div>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  {quickPromptSuggestions.slice(0, 4).map((prompt) => (
                    <button
                      key={`setup-${prompt}`}
                      type="button"
                      onClick={() => handleUsePrompt(prompt)}
                      className="rounded-full border border-[#ead6dd] bg-[#fff8fb] px-4 py-2 text-[12px] font-medium text-[#7a4d5d] transition hover:-translate-y-0.5 hover:border-[#d1aabb] hover:bg-white"
                    >
                      {prompt}
                    </button>
                  ))}
                </div>
              </div>
            </div>

            <div className="hidden flex-col gap-4 xl:sticky xl:top-4 xl:self-start">
              <div className="soft-panel p-6">
                <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[#b07a8e]">
                  Ngữ cảnh AI đã nắm
                </p>
                <h3 className="mt-3 text-[24px] font-semibold tracking-[-0.04em] text-[#17141a]">
                  {currentSubject?.label || 'Phiên học mới'}
                </h3>
                <div className="mt-5 grid gap-3">
                  {aiReadyContext.map((item) => (
                    <div
                      key={item.label}
                      className="rounded-[18px] border border-white/80 bg-white/80 px-4 py-3"
                    >
                      <p className="text-[11px] uppercase tracking-[0.16em] text-[#8c3451]/55">
                        {item.label}
                      </p>
                      <p className="mt-2 text-[14px] font-semibold text-[#231d22]">{item.value}</p>
                      <p className="mt-1 text-[12px] leading-5 text-[#7d666f]">{item.detail}</p>
                    </div>
                  ))}
                </div>
              </div>

              <div className="white-panel p-6">
                <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[#b07a8e]">
                  Ghi chú nhanh
                </p>
                <div className="mt-4 space-y-3">
                  {SESSION_SETUP_NOTES.map((note) => (
                    <div
                      key={note}
                      className="rounded-[18px] border border-[#f0d7e0] bg-[#fff8fb] px-4 py-3 text-[13px] leading-6 text-[#6f5260]"
                    >
                      {note}
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </DashboardLayout>
    );
  }

  return (
    <DashboardLayout>
      <div className="page-shell max-w-[1560px] flex min-h-[calc(100vh-140px)] flex-col pb-6">
          <PageHero
            className="mb-6"
            kicker="Trợ giảng AI"
            title="Một workspace hỏi đáp giữ mạch học tập theo phiên."
            description=""
          actions={
            <>
              <span className="demo-pill">{currentSubject?.label || 'Môn học hiện tại'}</span>
              <span className="demo-pill">{currentLevelMeta.label}</span>
              <span className="demo-pill">{activeTutorMode.shortLabel}</span>
              <span className="demo-pill">{sessionQuestionCount} câu hỏi trong phiên</span>
              <button
                type="button"
                onClick={() => setShowHistory(!showHistory)}
                className="theme-button-secondary px-4 py-2 text-[12px]"
              >
                {showHistory ? 'Ẩn lịch sử' : `Lịch sử (${history.length})`}
              </button>
              <button
                type="button"
                onClick={() => {
                  setShowGoalInput(true);
                  setMessages([]);
                  setGoal('');
                }}
                className="theme-button px-4 py-2 text-[12px]"
              >
                Phiên mới
              </button>
            </>
          }
          metrics={[
            {
              label: 'Mục tiêu hiện tại',
              value: goal ? 'Đã thiết lập' : 'Chưa có mục tiêu',
              detail: goal || 'Thiết lập mục tiêu để AI trả lời sát hơn.',
            },
            {
              label: 'Lịch sử gần đây',
              value: `${history.length} mục`,
              detail:
                historyPreview[0]?.question || 'Chưa có lịch sử câu hỏi cho môn học hiện tại.',
            },
            {
              label: 'Khái niệm đang theo dõi',
              value: currentConcept?.concept_name || 'Chưa có',
              detail: currentConcept
                ? `Độ thành thạo ${Math.round(currentConcept.mastery * 100)}%`
                : 'Khái niệm sẽ xuất hiện khi câu hỏi được nhận diện theo ngữ cảnh.',
            },
          ]}
        />

        <div className="mb-6 hidden gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <div className="rounded-[24px] border border-[#ead6dd] bg-[#fff8fb] px-5 py-4">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="max-w-[760px]">
                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8c3451]/55">
                  Ngữ cảnh AI đã nắm
                </p>
                <h2 className="mt-2 text-[22px] font-semibold tracking-[-0.03em] text-[#18141a]">
                  Phiên này đang hiểu bạn theo tín hiệu nào
                </h2>
                <div className="mt-4 grid gap-3 md:grid-cols-3">
                  {aiReadyContext.map((item) => (
                    <div key={`session-${item.label}`} className="rounded-[18px] border border-white/80 bg-white/80 px-4 py-3">
                      <p className="text-[11px] uppercase tracking-[0.16em] text-[#8c3451]/55">
                        {item.label}
                      </p>
                      <p className="mt-2 text-[14px] font-semibold text-[#231d22]">{item.value}</p>
                      <p className="mt-1 text-[12px] leading-5 text-[#7d666f]">{item.detail}</p>
                    </div>
                  ))}
                </div>
              </div>
              <div className="rounded-[18px] border border-white/80 bg-white/80 px-4 py-4 lg:max-w-[320px]">
                <p className="text-[11px] uppercase tracking-[0.16em] text-[#8c3451]/55">
                  Chế độ Tutor
                </p>
                <div className="mt-3 flex flex-wrap gap-2">
                  {(Object.keys(TUTOR_MODE_META) as TutorMode[]).map((mode) => (
                    <button
                      key={`session-mode-${mode}`}
                      type="button"
                      onClick={() => setTutorMode(mode)}
                      className={`rounded-full border px-4 py-2 text-[12px] font-semibold transition ${
                        tutorMode === mode
                          ? 'border-[#8c3451] bg-[#8c3451] text-white shadow-[0_12px_24px_rgba(140,52,81,0.18)]'
                          : 'border-[#ead6dd] bg-white text-[#6f5260] hover:bg-[#fff7fb]'
                      }`}
                    >
                      {TUTOR_MODE_META[mode].label}
                    </button>
                  ))}
                </div>
                <p className="mt-3 text-[12px] leading-5 text-[#7d666f]">{activeTutorMode.shortLabel}</p>
              </div>
            </div>
          </div>

          <div className="rounded-[24px] border border-[#dbe8ff] bg-[#f5f9ff] px-5 py-4">
            <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#2563eb]">
              Gợi ý nhanh
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              {quickPromptSuggestions.slice(0, 4).map((prompt) => (
                <button
                  key={`hero-${prompt}`}
                  type="button"
                  onClick={() => handleUsePrompt(prompt)}
                  className="rounded-full border border-[#d4e3ff] bg-white px-4 py-2 text-[12px] font-medium text-[#34527c] transition hover:-translate-y-0.5 hover:border-[#aac7ff]"
                >
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div className="mb-6 hidden flex-wrap gap-3">
          <button
            type="button"
            onClick={handleClearSubjectHistory}
            className="theme-button-secondary border-red-200 bg-white/90 text-red-700"
          >
            Xóa lịch sử môn
          </button>
          <button
            type="button"
            onClick={() => navigate('/resources')}
            className="theme-button-secondary"
          >
            Mở thư viện tài nguyên
          </button>
          <button
            type="button"
            onClick={() => navigate('/learning-path')}
            className="theme-button-secondary"
          >
            Xem lộ trình học
          </button>
        </div>

        {/* History Modal */}
        {showHistory && (
          <div
            className="fixed inset-0 z-50 flex items-center justify-center bg-[#2a121b]/35 p-4 backdrop-blur-sm"
            onClick={() => setShowHistory(false)}
          >
            <div
              className="white-panel flex max-h-[82vh] w-full max-w-[620px] flex-col overflow-hidden rounded-[28px] border border-[#f1d7e2] shadow-[0_32px_80px_rgba(45,31,17,0.22)]"
              onClick={(event) => event.stopPropagation()}
            >
              <div className="border-b border-[#8c3451]/10 bg-[linear-gradient(180deg,#fff9fc_0%,#fff4f8_100%)] px-6 py-5">
                <div className="flex items-start justify-between gap-4">
                  <div className="min-w-0">
                    <p className="text-[11px] font-semibold uppercase tracking-[0.22em] text-[#b07a8e]">
                      Lịch sử phiên học
                    </p>
                    <h2 className="mt-2 text-[24px] font-semibold tracking-[-0.04em] text-[#8c3451]">
                      Câu hỏi gần đây
                    </h2>
                    <p className="mt-2 text-[13px] leading-6 text-[#6f5260]">
                      Chọn lại một câu hỏi để nạp nhanh vào ô chat, hoặc xóa riêng từng mục khi cần.
                    </p>
                  </div>
                  <button
                    type="button"
                    onClick={() => setShowHistory(false)}
                    className="rounded-full p-2 text-[#8c3451] transition hover:bg-white"
                    aria-label="Đóng lịch sử"
                  >
                    ×
                  </button>
                </div>
                <div className="mt-4 flex flex-wrap gap-2">
                  <span className="demo-pill">{currentSubject?.label || 'Môn hiện tại'}</span>
                  <span className="demo-pill">{history.length} mục lịch sử</span>
                </div>
              </div>

              <div className="scroll-soft flex-1 overflow-y-auto p-4 sm:p-5">
                {historyLoading ? (
                  <div className="flex min-h-[220px] items-center justify-center">
                    <div className="h-9 w-9 animate-spin rounded-full border-b-2 border-[#8c3451]" />
                  </div>
                ) : history.length === 0 ? (
                  <div className="flex min-h-[240px] items-center justify-center">
                    <div className="max-w-[340px] text-center">
                      <p className="text-[18px] font-semibold text-[#8c3451]">
                        Chưa có câu hỏi nào được lưu
                      </p>
                      <p className="mt-3 text-[13px] leading-6 text-[#6f5260]">
                        Sau khi bạn hỏi vài câu, lịch sử sẽ xuất hiện ở đây để tái sử dụng nhanh trong cùng môn học.
                      </p>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-3">
                    {history.map((item) => (
                      <div key={item._id} className="group rounded-[22px] border border-[#efe1e8] bg-[#fff9fb] p-4 transition hover:border-[#dcb4c4] hover:bg-white">
                        <div className="flex items-start justify-between gap-3">
                          <button
                            type="button"
                            className="min-w-0 flex-1 text-left"
                            onClick={() => handleLoadFromHistory(item)}
                          >
                            <p className="line-clamp-2 text-[14px] font-semibold leading-6 text-[#3b2c34]">
                              {item.question}
                            </p>
                            <p className="mt-2 text-[12px] text-[#8a5d6d]">
                              Mục tiêu: {item.goal}
                            </p>
                            <p className="mt-1 text-[11px] text-[#8e8388]">
                              {new Date(item.timestamp).toLocaleString('vi-VN')}
                            </p>
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDeleteHistoryItem(item._id)}
                            className="rounded-full border border-red-200 bg-white px-3 py-1.5 text-[11px] font-medium whitespace-nowrap text-red-600 opacity-100 transition hover:bg-red-50 sm:opacity-0 sm:group-hover:opacity-100"
                          >
                            Xóa
                          </button>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div className="border-t border-[#f0dfe7] bg-white/95 px-5 py-4 text-[12px] text-[#7d666f]">
                Nhấn vào một câu hỏi để nạp lại vào composer, sau đó chỉnh sửa và gửi như một lượt hỏi mới.
              </div>
            </div>
          </div>
        )}

        <div className="grid min-h-0 flex-1 gap-6">
          {/* Main Chat Area */}
          <div className="white-panel flex h-[82vh] min-h-[720px] max-h-[1560px] flex-col overflow-hidden">
            <div className="border-b border-[#8c3451]/10 bg-[linear-gradient(180deg,rgba(255,249,252,0.98),rgba(255,245,249,0.98))] px-6 py-5 xl:px-8">
              <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                <div className="min-w-0">
                  <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-[#8c3451]/55">
                    Phiên học đang chạy
                  </p>
                  <h2 className="mt-2 text-[24px] font-medium tracking-[-0.04em] text-[#18141a]">
                    Hỏi sâu, đọc nguồn, giữ mạch học liên tục
                  </h2>
                  <p className="mt-2 max-w-[760px] text-[13px] leading-5 text-[#655d58]">
                    Hỏi, nhận câu trả lời và đi tiếp.
                  </p>
                </div>

                <div className="flex flex-wrap gap-2 xl:max-w-[360px] xl:justify-end">
                  <span className="demo-pill">Môn: {currentSubject?.label || 'Chưa chọn'}</span>
                  <span className="demo-pill">Lịch sử: {history.length}</span>
                  {currentConcept ? (
                    <span className="demo-pill">
                      Thành thạo: {Math.round(currentConcept.mastery * 100)}%
                    </span>
                  ) : null}
                  {loading ? <span className="demo-pill">AI đang phản hồi</span> : null}
                </div>
              </div>
            </div>

            {/* Messages Area */}
            <div className="scroll-soft min-h-0 flex-1 space-y-5 overflow-y-auto px-6 py-6 xl:px-8 xl:py-7">
              {messages.length === 0 ? (
                <div className="flex h-full items-center justify-center">
                  <div className="max-w-[1560px] text-center">
                    <div className="mx-auto mb-5 flex h-16 w-16 items-center justify-center rounded-full bg-[#fdf0f5] text-[#8c3451] shadow-[0_12px_28px_rgba(140,52,81,0.12)]">
                      <svg
                        viewBox="0 0 24 24"
                        className="h-8 w-8"
                        fill="none"
                        stroke="currentColor"
                        strokeWidth="1.8"
                        strokeLinecap="round"
                        strokeLinejoin="round"
                      >
                        <path d="M12 3.8 13.7 8l4.5.4-3.4 2.9 1 4.4L12 13.5 8.2 15.7l1-4.4-3.4-2.9L10.3 8 12 3.8Z" />
                      </svg>
                    </div>
                    <p className="text-[22px] font-medium tracking-[-0.03em] text-[#8c3451]">
                      Bắt đầu bằng một câu hỏi thật cụ thể
                    </p>
                    <p className="mt-3 text-[13px] leading-5 text-[#645d58]">
                      Chọn một prompt hoặc gõ câu hỏi đầu tiên.
                    </p>
                    <div className="mt-5 grid gap-3 sm:grid-cols-2">
                      {quickPromptSuggestions.map((prompt) => (
                        <button
                          key={prompt}
                          type="button"
                          onClick={() => handleUsePrompt(prompt)}
                          className="rounded-[20px] border border-[#ead6dd] bg-white px-4 py-4 text-left text-[13px] font-medium leading-6 text-[#5c4450] transition hover:-translate-y-0.5 hover:border-[#d7b0bf] hover:bg-[#fff8fb]"
                        >
                          {prompt}
                        </button>
                      ))}
                    </div>
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
                        className={`max-w-[92%] rounded-[26px] p-4 sm:max-w-[78%] xl:p-5 2xl:max-w-[74%] ${
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
                                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-[#f9eef3] text-[11px] font-semibold">
                                    i
                                  </span>
                                  <span>Nguồn tài liệu</span>
                                </p>
                                <div className="scroll-soft max-h-44 space-y-2 overflow-y-auto pr-1">
                                  {message.answer.sources.map((source, idx) => (
                                    <div
                                      key={idx}
                                      className="flex items-start gap-2 p-2.5 bg-[#fef3f4] border border-[#f5d5dd] rounded-lg hover:bg-[#fedde2] transition-colors"
                                    >
                                      <span className="text-[11px] font-bold text-[#8c3451] min-w-[18px] text-center">
                                        {idx + 1}
                                      </span>
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
                                          <p className="text-[12px] font-medium text-[#333]">
                                            {source.title}
                                          </p>
                                        )}
                                      </div>
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}

                            {message.answer.confidence && (
                              <div className="flex items-center gap-2 p-2.5 bg-[#eef9ff] border border-[#b8e0f6] rounded-lg">
                                <span className="text-[13px] font-semibold text-[#0066cc]">
                                  Độ tin cậy:
                                </span>
                                <div className="flex-1 bg-white border border-[#d0e8ff] rounded-full h-2 overflow-hidden">
                                  <div
                                    className="h-full bg-gradient-to-r from-[#0066cc] to-[#003d99]"
                                    style={{
                                      width: `${Math.round(message.answer.confidence * 100)}%`,
                                    }}
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
                            <p className="text-[12px] font-semibold mb-1">
                              Khái niệm được phát hiện:
                            </p>
                            <p className="text-[13px]">{message.conceptDetected.concept_name}</p>
                            <p className="text-[11px] opacity-80 mt-1">
                              Độ phù hợp: {Math.round(message.conceptDetected.score * 100)}%
                            </p>
                          </div>
                        )}

                        {/* Learning Recommendations */}
                        {message.role === 'assistant' &&
                          message.learning_path &&
                          message.learning_path.length > 0 && (
                            <div className="mt-3 p-2 bg-white bg-opacity-20 rounded-[10px]">
                              <p className="text-[12px] font-semibold mb-2">
                                Khái niệm tiếp theo:
                              </p>
                              <div className="space-y-1">
                                {message.learning_path.slice(0, 3).map((concept, idx) => (
                                  <div key={idx} className="text-[12px]">
                                    <span className="font-medium">{idx + 1}.</span>{' '}
                                    {concept.concept_name}
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

            {error ? (
              <StatusPanel
                className="border-t border-red-200 rounded-none px-6 py-3 shadow-none"
                tone="error"
                description={error}
              />
            ) : null}

            {/* Input Area */}
            <div className="border-t border-[#8c3451]/10 bg-[#fff6fa] px-5 py-4 xl:px-6 xl:py-5">
              <div className="mb-2 flex items-center justify-between gap-3">
                <p className="text-[12px] font-medium text-[#8c3451]">Gợi ý hỏi nhanh</p>
              </div>
              <div className="mb-3 flex flex-wrap gap-2">
                {quickPromptSuggestions.map((prompt) => (
                  <button
                    key={`footer-${prompt}`}
                    type="button"
                    onClick={() => handleUsePrompt(prompt)}
                    className="rounded-full border border-[#ead6dd] bg-white px-3 py-1.5 text-[12px] font-medium text-[#7a4d5d] transition hover:border-[#d1aabb] hover:bg-[#fff7fb]"
                  >
                    {prompt}
                  </button>
                ))}
              </div>

              <div className="flex items-end gap-3">
                <div className="flex-1 rounded-[24px] border border-[#ecd6de] bg-white px-3 py-3 shadow-[inset_0_1px_0_rgba(255,255,255,0.7)]">
                  <textarea
                    ref={composerRef}
                    value={input}
                    onChange={(e) => setInput(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && !loading) {
                        e.preventDefault();
                        handleSendMessage();
                      }
                    }}
                    rows={1}
                    placeholder={`Đang ở chế độ ${activeTutorMode.shortLabel.toLowerCase()}. Hỏi thật cụ thể để AI trả lời đúng nhịp học của bạn.`}
                    disabled={loading}
                    className="min-h-[20px] max-h-[180px] w-full resize-none border-0 bg-transparent px-2 py-1 text-[14px] leading-6 text-[#3b2c34] outline-none placeholder:text-[#9b8790] disabled:cursor-not-allowed disabled:text-[#8f8690]"
                  />
                </div>
                <button
                  onClick={handleSendMessage}
                  disabled={loading || !input.trim()}
                  className="theme-button min-w-[108px] disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {loading ? 'Đang gửi' : 'Gửi'}
                </button>
              </div>
            </div>
          </div>

          {/* Right Sidebar - Learning Context */}
          <div className="hidden w-full flex-col gap-4 xl:sticky xl:top-4 xl:self-start">
            <div className="soft-panel p-5">
              <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8c3451]/55">
                Ngữ cảnh phiên học
              </p>
              <h3 className="mt-2 text-[22px] font-medium tracking-[-0.04em] text-[#20181d]">
                {currentSubject?.label || 'Phiên học hiện tại'}
              </h3>
              <p className="mt-3 line-clamp-2 text-[13px] leading-5 text-[#5d5651]">
                {goal || 'Chưa có mô tả mục tiêu.'}
              </p>
              <div className="mt-4 grid gap-3 sm:grid-cols-3 xl:grid-cols-1">
                <div className="rounded-[18px] border border-white/70 bg-white/80 p-3">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-[#8c3451]/55">
                      Trình độ
                  </p>
                    <p className="mt-2 text-[14px] font-semibold text-[#231d22]">
                      {currentLevelMeta.label}
                    </p>
                  <p className="mt-1 text-[12px] leading-5 text-[#7d666f]">
                      {currentLevelMeta.description}
                  </p>
                  </div>
                <div className="rounded-[18px] border border-white/70 bg-white/80 p-3">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-[#8c3451]/55">
                      Chế độ Tutor
                  </p>
                  <p className="mt-2 text-[14px] font-semibold text-[#231d22]">
                      {activeTutorMode.shortLabel}
                  </p>
                  <p className="mt-1 text-[12px] leading-5 text-[#7d666f]">{activeTutorMode.shortLabel}</p>
                </div>
                <div className="rounded-[18px] border border-white/70 bg-white/80 p-3">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-[#8c3451]/55">
                      Câu hỏi
                  </p>
                  <p className="mt-2 text-[14px] font-semibold text-[#231d22]">
                      {sessionQuestionCount} lượt hỏi
                  </p>
                </div>
                <div className="rounded-[18px] border border-white/70 bg-white/80 p-3">
                  <p className="text-[11px] uppercase tracking-[0.16em] text-[#8c3451]/55">
                      Nguồn gần nhất
                  </p>
                  <p className="mt-2 text-[14px] font-semibold text-[#231d22]">
                      {latestSourceCount} nguồn
                  </p>
                    <p className="mt-1 text-[12px] leading-5 text-[#7d666f]">
                      Số nguồn của phản hồi gần nhất có trích dẫn.
                    </p>
                </div>
              </div>
            </div>

            <div className="metric-card p-5">
              <h3 className="mb-1 text-[15px] font-medium text-[#8c3451]">Ngữ cảnh AI đã nắm</h3>
              <div className="space-y-3">
                {aiReadyContext.map((item) => (
                  <div key={`rail-${item.label}`} className="rounded-[18px] border border-[#efe1e8] bg-[#fff9fb] px-4 py-3">
                    <p className="text-[11px] uppercase tracking-[0.16em] text-[#8c3451]/55">
                      {item.label}
                    </p>
                    <p className="mt-2 text-[13px] font-semibold text-[#3c2f36]">{item.value}</p>
                    <p className="mt-1 text-[12px] leading-5 text-[#7d666f]">{item.detail}</p>
                  </div>
                ))}
              </div>
            </div>

            {/* Current Concept Card */}
            {currentConcept && (
              <div className="metric-card p-5">
                <h3 className="mb-3 text-[15px] font-medium text-[#8c3451]">
                  Khái niệm hiện tại
                </h3>
                {conceptLoading ? (
                  <div className="h-6 w-6 animate-spin rounded-full border-b-2 border-[#8c3451]" />
                ) : (
                  <>
                    <p className="text-[13px] font-medium text-[#333] mb-2">
                      {currentConcept.concept_name}
                    </p>
                    <p className="text-[12px] text-[#666] mb-3">{currentConcept.description}</p>

                    <div className="mb-3">
                      <p className="text-[12px] font-medium text-[#8c3451] mb-1">Độ thành thạo</p>
                      <div className="w-full h-2 bg-gray-200 rounded-full overflow-hidden">
                        <div
                          className="h-full bg-[#8c3451] transition-all"
                          style={{ width: `${currentConcept.mastery * 100}%` }}
                        />
                      </div>
                      <p className="text-[11px] text-[#666] mt-1">
                        {Math.round(currentConcept.mastery * 100)}%
                      </p>
                    </div>

                    <div
                      className="inline-block px-3 py-1 rounded-full text-[11px] font-medium"
                      style={{
                        backgroundColor:
                          currentConcept.status === 'complete'
                            ? '#d4f4dd'
                            : currentConcept.status === 'in_progress'
                              ? '#fff4d6'
                              : '#f0f0f0',
                        color:
                          currentConcept.status === 'complete'
                            ? '#1a6b2f'
                            : currentConcept.status === 'in_progress'
                              ? '#a67c2f'
                              : '#666',
                      }}
                    >
                      {currentConcept.status === 'complete'
                        ? 'Hoàn thành'
                        : currentConcept.status === 'in_progress'
                          ? 'Đang học'
                          : 'Chưa bắt đầu'}
                    </div>
                  </>
                )}
              </div>
            )}

            <div className="metric-card p-5">
              <h3 className="mb-1 text-[15px] font-medium text-[#8c3451]">Câu hỏi mẫu</h3>
              <p className="mb-3 text-[12px] leading-5 text-[#6b6460]">
                Chạm để đưa nhanh một câu hỏi vào ô nhập thay vì gõ lại từ đầu.
              </p>
              <div className="space-y-2">
                {quickPromptSuggestions.map((prompt) => (
                  <button
                    key={`sidebar-${prompt}`}
                    type="button"
                    onClick={() => handleUsePrompt(prompt)}
                    className="w-full rounded-[18px] border border-[#ead6dd] bg-[#fff8fb] px-4 py-3 text-left text-[12px] leading-5 text-[#5e4c56] transition hover:border-[#d5afbd] hover:bg-white"
                  >
                    {prompt}
                  </button>
                ))}
              </div>
            </div>

            <div className="metric-card p-5">
              <h3 className="mb-3 text-[15px] font-medium text-[#8c3451]">Lịch sử gần đây</h3>
              {historyPreview.length === 0 ? (
                <p className="text-[12px] leading-6 text-[#6a6460]">
                  Chưa có lịch sử câu hỏi cho mục tiêu này. Hãy hỏi câu đầu tiên để bắt đầu lưu.
                </p>
              ) : (
                <div className="space-y-3">
                  {historyPreview.map((item) => (
                    <button
                      key={item._id}
                      type="button"
                      onClick={() => handleLoadFromHistory(item)}
                      className="w-full rounded-[18px] border border-[#efe1e8] bg-[#fff9fb] px-4 py-3 text-left transition hover:border-[#d9b8c5] hover:bg-white"
                    >
                      <p className="line-clamp-2 text-[12px] font-semibold leading-5 text-[#3c2f36]">
                        {item.question}
                      </p>
                      <p className="mt-1 text-[11px] text-[#8a5d6d]">
                        {new Date(item.timestamp).toLocaleDateString('vi-VN')}
                      </p>
                    </button>
                  ))}
                </div>
              )}
            </div>

            <div className="metric-card p-5">
              <h3 className="mb-3 text-[15px] font-medium text-[#8c3451]">Hành động nhanh</h3>
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

      </div>
    </DashboardLayout>
  );
}
