import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import ReactFlow, {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  type Edge,
  type Node,
  type NodeProps,
  type ReactFlowInstance,
} from 'reactflow';
import 'reactflow/dist/style.css';
import DashboardLayout from '../components/layout/DashboardLayout';
import PDFViewer from '../components/PDFViewer';
import { useAuth } from '../contexts/AuthContext';
import { adaptiveService } from '../services/adaptiveService';
import { learningPathService } from '../services';
import { recommendationInteractionService } from '../services/recommendationInteractionService';
import type {
  AdaptiveNextAction,
  AdaptiveRecommendationPayload,
} from '../types/adaptive';
import type {
  BloomLevel,
  LearningPath,
  LearningPathChapter,
  LearningPathLesson,
  LearningLevel,
  LessonRecommendedChunks,
  LessonQuestion,
  LessonQuestionBank,
  LessonQuestionType,
  LessonStatus,
} from '../types/learningPath';
import { SUBJECTS } from '../utils/subjects';

interface PathState {
  path?: LearningPath;
}

type ScreenMode = 'subject' | 'map' | 'lesson';
type LessonTab = 'lesson' | 'questions';

interface LessonNode extends LearningPathLesson {
  chapter_id: string;
  chapter_title: string;
  chapter_index: number;
  lesson_index: number;
}

interface LessonResourceCard {
  key: string;
  title: string;
  source: string;
  preview: string;
  resourceId?: string;
  resourceUrl?: string;
  pageNumber?: number;
  actionLabel?: string;
  instructionRole?: string;
  estimatedReadTime?: number;
  questionabilityScore?: number;
  coveredConcepts?: string[];
  sequencePosition?: number;
}

interface PinnedLessonResource extends LessonResourceCard {
  pinnedAt: string;
}

interface QuestionGenerationConfig {
  targetCount: number;
  difficulty: LearningLevel;
  questionTypes: LessonQuestionType[];
  bloomLevels: BloomLevel[];
}

const LESSON_RESOURCE_STOP_WORDS = new Set([
  'bai',
  'bài',
  'chuong',
  'chương',
  'lesson',
  'chapter',
  'hoc',
  'học',
  'trong',
  'cua',
  'của',
  'voi',
  'với',
  'cho',
  'nguoi',
  'người',
  'co',
  'có',
  'ban',
  'bạn',
  'muc',
  'mục',
  'tieu',
  'tiêu',
]);

const QUESTION_COUNT_OPTIONS = [4, 6, 8];
const QUESTION_TYPE_OPTIONS: Array<{
  value: LessonQuestionType;
  label: string;
  description: string;
}> = [
  { value: 'multiple_choice', label: 'Trắc nghiệm', description: 'Chọn 1 đáp án đúng' },
  { value: 'true_false', label: 'Đúng / Sai', description: 'Kiểm tra nhận định nhanh' },
  { value: 'short_answer', label: 'Trả lời ngắn', description: 'Tự gõ câu trả lời' },
];
const BLOOM_LEVEL_OPTIONS: Array<{ value: BloomLevel; label: string }> = [
  { value: 'remember', label: 'Ghi nhớ' },
  { value: 'understand', label: 'Hiểu' },
  { value: 'apply', label: 'Áp dụng' },
  { value: 'analyze', label: 'Phân tích' },
  { value: 'evaluate', label: 'Đánh giá' },
  { value: 'create', label: 'Sáng tạo' },
];
const DIFFICULTY_OPTIONS: Array<{ value: LearningLevel; label: string }> = [
  { value: 'beginner', label: 'Cơ bản' },
  { value: 'intermediate', label: 'Trung bình' },
  { value: 'advanced', label: 'Nâng cao' },
];
const STUDY_TIME_MIN_SECONDS = 10;
const STUDY_TIME_FLUSH_INTERVAL_MS = 15000;

interface MapLessonNodeData {
  lesson: LessonNode;
  isSelected: boolean;
  isInPath: boolean;
  onSelect: (lesson: LessonNode) => void;
  onOpenLesson: (lesson: LessonNode) => void;
  onHoverLesson: (lesson: LessonNode | null) => void;
  accent: {
    solid: string;
    soft: string;
    border: string;
    text: string;
  };
}

interface MapChapterNodeData {
  chapterIndex: number;
  title: string;
  accent: {
    solid: string;
    soft: string;
    border: string;
    text: string;
  };
}

type MapStatusFilter = 'all' | LessonStatus;
type MapLayoutMode = 'chapter' | 'journey';

const MAP_NODE_WIDTH = 304;
const MAP_NODE_HEIGHT = 300;
const CHAPTER_SPACING_X = 392;
const LESSON_SPACING_Y = 392;
const CHAPTER_LABEL_OFFSET_Y = 12;
const JOURNEY_COLUMNS = 3;
const JOURNEY_SPACING_X = 388;
const JOURNEY_SPACING_Y = 404;

const CHAPTER_ACCENTS = [
  { solid: '#8c3451', soft: '#f9e8ef', border: '#efcfdb', text: '#8c3451' },
  { solid: '#b76e79', soft: '#faece8', border: '#f1d6d3', text: '#9b5562' },
  { solid: '#8b5cf6', soft: '#f1ecff', border: '#ddd3ff', text: '#7c4ded' },
  { solid: '#0f9f8c', soft: '#e8f8f4', border: '#cdeee6', text: '#0d8b7a' },
  { solid: '#f59e0b', soft: '#fff5e3', border: '#fde6bb', text: '#d08700' },
];

const getChapterAccent = (chapterIndex: number) =>
  CHAPTER_ACCENTS[(chapterIndex - 1) % CHAPTER_ACCENTS.length];

const getLessonStatusMeta = (status?: LessonStatus) => {
  switch (status) {
    case 'complete':
      return {
        label: 'Hoàn thành',
        dot: '✓',
        pillClass: 'bg-emerald-100 text-emerald-700',
        accentClass: 'bg-emerald-500',
      };
    case 'in_progress':
      return {
        label: 'Đang học',
        dot: '•',
        pillClass: 'bg-[#8c3451] text-white',
        accentClass: 'bg-[#8c3451]',
      };
    default:
      return {
        label: 'Chưa mở',
        dot: '○',
        pillClass: 'bg-slate-100 text-slate-600',
        accentClass: 'bg-slate-300',
      };
  }
};

const LearningMapNodeCard = ({ data }: NodeProps<MapLessonNodeData>) => {
  const { lesson, isSelected, isInPath, onSelect, onOpenLesson, onHoverLesson, accent } = data;
  const statusMeta = getLessonStatusMeta(lesson.status);
  const canOpenLesson = lesson.status !== 'not_started';

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={() => onSelect(lesson)}
      onMouseEnter={() => onHoverLesson(lesson)}
      onMouseLeave={() => onHoverLesson(null)}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onSelect(lesson);
        }
      }}
      className="learning-flow-node group min-h-[300px] w-[304px] rounded-[28px] border bg-white/95 px-5 py-5 text-left shadow-[0_20px_40px_rgba(114,62,83,0.08)] transition-all duration-200"
      style={{
        borderColor: isSelected ? accent.solid : isInPath ? accent.text : accent.border,
        boxShadow: isSelected
          ? `0 24px 48px ${accent.border}`
          : isInPath
            ? `0 20px 42px ${accent.soft}`
            : '0 20px 40px rgba(114,62,83,0.08)',
        background: isInPath ? 'rgba(255,255,255,1)' : 'rgba(255,255,255,0.95)',
      }}
    >
      <Handle
        type="target"
        position={Position.Top}
        className="!h-3 !w-3 !border-2 !border-white !bg-[#d38ba1]"
      />

      <div className="mb-4 flex items-start gap-4">
        <div
          className="flex h-14 w-11 shrink-0 items-center justify-center rounded-[18px] text-[20px] font-semibold text-white"
          style={{ background: lesson.status === 'not_started' ? '#cbd5e1' : accent.solid }}
        >
          {statusMeta.dot}
        </div>
        <div className="min-w-0 flex-1">
          <div className="mb-2 flex items-center justify-between gap-3">
            <span
              className="rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.16em]"
              style={{ background: accent.soft, color: accent.text }}
            >
              Chương {lesson.chapter_index}
            </span>
            <span
              className={`rounded-full px-3 py-1 text-[11px] font-semibold ${statusMeta.pillClass}`}
            >
              {statusMeta.label}
            </span>
          </div>
          <p className="max-h-[48px] overflow-hidden text-[20px] font-semibold leading-[1.2] tracking-[-0.03em] text-[#141217]">
            Bài {lesson.chapter_index}.{lesson.lesson_index}: {cleanLessonTitle(lesson.title)}
          </p>
        </div>
      </div>

      <p className="max-h-[72px] overflow-hidden text-[13px] leading-6 text-[#6a625d]">
        {lesson.summary?.trim() ||
          'Bài học này giúp bạn tiến thêm một bước trong lộ trình hiện tại.'}
      </p>

      <div className="mt-5 flex items-center justify-between gap-3">
        <span className="text-[12px] font-medium text-[#8c3451]/70">{lesson.chapter_title}</span>
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            if (canOpenLesson) {
              onOpenLesson(lesson);
            }
          }}
          disabled={!canOpenLesson}
          className={`rounded-full px-4 py-2 text-[12px] font-semibold transition ${
            canOpenLesson ? 'bg-[#8c3451] text-white' : 'bg-slate-100 text-slate-500'
          }`}
        >
          {canOpenLesson ? 'Mở bài' : 'Đang khóa'}
        </button>
      </div>

      <Handle
        type="source"
        position={Position.Bottom}
        className="!h-3 !w-3 !border-2 !border-white !bg-[#d38ba1]"
      />
    </div>
  );
};

const LearningMapChapterCard = ({ data }: NodeProps<MapChapterNodeData>) => (
  <div
    className="pointer-events-none rounded-full border bg-white/90 px-5 py-3 shadow-[0_14px_28px_rgba(114,62,83,0.08)] backdrop-blur-sm"
    style={{ borderColor: data.accent.border }}
  >
    <p
      className="text-[11px] font-semibold uppercase tracking-[0.18em]"
      style={{ color: data.accent.text, opacity: 0.7 }}
    >
      Chương {data.chapterIndex}
    </p>
    <p className="mt-1 text-[15px] font-semibold text-[#141217]">{cleanChapterTitle(data.title)}</p>
  </div>
);

const mapNodeTypes = {
  lessonNode: LearningMapNodeCard,
  chapterNode: LearningMapChapterCard,
};

const getLearningPathNotice = (path?: LearningPath | null) => {
  if (!path || path.curriculum_source !== 'fallback') {
    return null;
  }
  return (
    path.curriculum_notice ||
    'AI hiện chưa phản hồi ổn định. Hệ thống đã dùng lộ trình dự phòng để bạn vẫn có thể bắt đầu học.'
  );
};

const getChapterStatusLabel = (chapter: LearningPathChapter) => {
  const lessons = chapter.lessons || [];
  if (lessons.length === 0) {
    return 'Chưa học';
  }
  if (lessons.every((lesson) => lesson.status === 'complete')) {
    return 'Hoàn thành';
  }
  if (lessons.some((lesson) => lesson.status === 'in_progress' || lesson.status === 'complete')) {
    return 'Đang học';
  }
  return 'Chưa học';
};

const buildLessonCollection = (chapters: LearningPathChapter[]): LessonNode[] => {
  const lessons: LessonNode[] = [];

  chapters.forEach((chapter, chapterIndex) => {
    chapter.lessons.forEach((lesson, lessonIndex) => {
      lessons.push({
        ...lesson,
        chapter_id: chapter.chapter_id,
        chapter_title: chapter.title,
        chapter_index: chapterIndex + 1,
        lesson_index: lessonIndex + 1,
      });
    });
  });

  return lessons;
};

const updateLessonStatusInPath = (
  currentPath: LearningPath,
  lessonId: string,
  status: LessonStatus,
): LearningPath => {
  const updateChapters = (chapters: LearningPathChapter[]) =>
    chapters.map((chapter) => ({
      ...chapter,
      lessons: chapter.lessons.map((lesson) =>
        lesson.lesson_id === lessonId
          ? {
              ...lesson,
              status,
            }
          : lesson,
      ),
    }));

  const nextChapters = updateChapters(
    currentPath.curriculum?.length ? currentPath.curriculum : currentPath.chapters,
  );

  return {
    ...currentPath,
    chapters: nextChapters,
    curriculum: nextChapters,
  };
};

const formatDateTime = (value?: string) => {
  if (!value) {
    return 'Không rõ';
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat('vi-VN', {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  }).format(date);
};

const getSubjectLabel = (subjectId?: string, goal?: string) =>
  SUBJECTS.find((subject) => subject.id === subjectId)?.label || goal || 'Tên môn học';

const getDisplayGoal = (subjectId?: string, goal?: string) => {
  const rawGoal = (goal || '').trim();
  if (!rawGoal) {
    return '';
  }

  const subject = SUBJECTS.find((item) => item.id === subjectId);
  const prefixes = [subject?.label, subject?.goal].filter(Boolean) as string[];

  let normalizedGoal = rawGoal;
  prefixes.forEach((prefix) => {
    const escaped = prefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    normalizedGoal = normalizedGoal.replace(new RegExp(`^${escaped}\\s*-?\\s*`, 'i'), '').trim();
  });

  return normalizedGoal || rawGoal;
};

const getChapterDescription = (chapter: LearningPathChapter) =>
  chapter.lessons.find((lesson) => lesson.summary?.trim())?.summary?.trim() ||
  'Nội dung chương trình';

const cleanChapterTitle = (title: string) => title.replace(/^chương\s*\d+\s*:\s*/i, '').trim();
const cleanLessonTitle = (title: string) =>
  title.replace(/^bài\s*\d+(?:\.\d+)?\s*:\s*/i, '').trim();

const getResourceSource = (resource: string) => {
  const normalized = resource.toLowerCase();
  if (normalized.includes('youtube') || normalized.includes('youtu.be')) return 'Youtube';
  if (normalized.includes('pdf')) return 'PDF';
  if (normalized.startsWith('http') || normalized.includes('www.')) return 'Trang web';
  return 'Tài liệu';
};

const getResourcePreview = (source: string) => {
  if (source === 'Youtube') return 'Thumbnail clip Youtube';
  if (source === 'PDF') return 'Bản xem trước bìa';
  return 'Xem trước tài nguyên';
};

const formatPdfResourceTitle = (title: string) =>
  title
    .replace(/\.pdf$/i, '')
    .replace(/[_-]+/g, ' ')
    .replace(/([A-Za-z])(\d)/g, '$1 $2')
    .replace(/(\d)([A-Za-z])/g, '$1 $2')
    .replace(/\s+/g, ' ')
    .trim();

const formatResourceSource = (source?: string) => {
  switch ((source || '').toLowerCase()) {
    case 'youtube':
      return 'YouTube';
    case 'pdf':
      return 'PDF';
    case 'web':
      return 'Trang web';
    default:
      return source?.trim() || 'Tài liệu';
  }
};

const getInstructionRoleLabel = (role?: string) => {
  switch ((role || '').toLowerCase()) {
    case 'introduction':
      return 'Intro';
    case 'explanation':
      return 'Explain';
    case 'worked_example':
      return 'Example';
    case 'misconception_fix':
      return 'Common mistake';
    case 'summary':
      return 'Summary';
    case 'practice_hint':
      return 'Practice hint';
    default:
      return 'Lesson chunk';
  }
};

const getAdaptiveActionLabel = (action?: string) => {
  switch (action) {
    case 'study_worked_example':
      return 'Học lại worked example';
    case 'study_misconception_fix':
      return 'Đọc phần common mistake';
    case 'quick_review_session':
      return 'Quick review trước khi làm lại quiz';
    case 'review_summary':
      return 'Đọc bản tóm tắt';
    case 'retry_with_easier_resource':
      return 'Ôn bằng tài liệu dễ hơn';
    default:
      return 'Adaptive suggestion';
  }
};

const getLessonResourceTheme = (source: string) => {
  switch (source) {
    case 'PDF':
      return {
        chip: 'bg-[#f4edff] text-[#6d4c8f]',
        frame: 'bg-[linear-gradient(180deg,#fffaff_0%,#f5eefc_100%)] border-[#eadff9]',
        preview: 'bg-[#f7f1ff]',
        accent: 'text-[#6d4c8f]',
        icon: 'PDF',
      };
    case 'YouTube':
      return {
        chip: 'bg-[#fff1f6] text-[#9b2f55]',
        frame: 'bg-[linear-gradient(180deg,#fff9fb_0%,#fdeef4_100%)] border-[#f5d8e3]',
        preview: 'bg-[#fff3f7]',
        accent: 'text-[#9b2f55]',
        icon: 'YT',
      };
    case 'Trang web':
      return {
        chip: 'bg-[#eef8fd] text-[#2f657f]',
        frame: 'bg-[linear-gradient(180deg,#fcfeff_0%,#eef8fd_100%)] border-[#dbe8f2]',
        preview: 'bg-[#f2f9fd]',
        accent: 'text-[#2f657f]',
        icon: 'WEB',
      };
    default:
      return {
        chip: 'bg-[#f6f1f4] text-[#6f5260]',
        frame: 'bg-[linear-gradient(180deg,#fffdfd_0%,#faf5f8_100%)] border-[#eadfe5]',
        preview: 'bg-[#faf5f8]',
        accent: 'text-[#6f5260]',
        icon: 'DOC',
      };
  }
};

const getLessonResourceHint = (resource: LessonResourceCard) => {
  if (resource.source === 'PDF' && resource.pageNumber) {
    return `Mở trực tiếp từ trang ${resource.pageNumber} để đọc đúng đoạn được gợi ý.`;
  }
  if (resource.source === 'PDF') {
    return 'Mở trực tiếp tài liệu PDF trong trình xem tích hợp.';
  }
  if (resource.source === 'YouTube') {
    return 'Mở nguồn video gốc để xem toàn bộ nội dung liên quan.';
  }
  return 'Mở nguồn tài liệu gốc để đọc đầy đủ nội dung tham khảo.';
};

const toNumericResourceId = (value?: string) => {
  if (!value) {
    return undefined;
  }

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
};

const extractLessonResourceTerms = (lesson?: LessonNode | null) => {
  const sources = [cleanLessonTitle(lesson?.title || ''), lesson?.summary || ''];
  const tokens = new Set<string>();

  sources.forEach((source) => {
    const matches = source.match(/\p{L}[\p{L}\p{N}]*/gu) || [];
    matches.forEach((token) => {
      const normalized = token.toLowerCase().trim();
      if (normalized.length < 4 || LESSON_RESOURCE_STOP_WORDS.has(normalized)) {
        return;
      }
      tokens.add(normalized);
    });
  });

  return Array.from(tokens).slice(0, 8);
};

const buildQuestionChoices = (question: LessonQuestion) => {
  if (question.question_type === 'multiple_choice') {
    return [question.correct_answer, ...question.distractors].filter(Boolean).slice(0, 4);
  }
  if (question.question_type === 'true_false') {
    return ['True', 'False'];
  }
  return [question.correct_answer || 'Trả lời ngắn'];
};

const getQuestionChoiceLabel = (choice: string) => {
  if (choice === 'True') {
    return 'Đúng';
  }
  if (choice === 'False') {
    return 'Sai';
  }
  return choice;
};

const getQuestionTypeLabel = (questionType: LessonQuestionType) => {
  return QUESTION_TYPE_OPTIONS.find((item) => item.value === questionType)?.label || 'Câu hỏi';
};

const getBloomLevelLabel = (bloomLevel: BloomLevel) => {
  return BLOOM_LEVEL_OPTIONS.find((item) => item.value === bloomLevel)?.label || bloomLevel;
};

const getDifficultyLabel = (difficulty: LearningLevel) => {
  return DIFFICULTY_OPTIONS.find((item) => item.value === difficulty)?.label || difficulty;
};

const normalizeQuizAnswer = (value: string) =>
  value
    .normalize('NFD')
    .replace(/\p{Diacritic}/gu, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();

const isShortAnswerMatch = (picked: string, correct: string) => {
  const normalizedPicked = normalizeQuizAnswer(picked);
  const normalizedCorrect = normalizeQuizAnswer(correct);

  if (!normalizedPicked || !normalizedCorrect) {
    return false;
  }

  if (normalizedPicked === normalizedCorrect) {
    return true;
  }

  if (
    normalizedCorrect.includes(normalizedPicked) ||
    normalizedPicked.includes(normalizedCorrect)
  ) {
    return true;
  }

  const pickedTokens = new Set(normalizedPicked.split(' ').filter((token) => token.length > 2));
  const correctTokens = normalizedCorrect.split(' ').filter((token) => token.length > 2);
  if (pickedTokens.size === 0 || correctTokens.length === 0) {
    return false;
  }

  const overlap = correctTokens.filter((token) => pickedTokens.has(token)).length;
  return overlap >= Math.max(1, Math.ceil(correctTokens.length * 0.6));
};

const isQuestionAnsweredCorrectly = (question: LessonQuestion, answer?: string) => {
  if (!answer?.trim()) {
    return false;
  }

  if (question.question_type === 'short_answer') {
    return isShortAnswerMatch(answer, question.correct_answer);
  }

  return normalizeQuizAnswer(answer) === normalizeQuizAnswer(question.correct_answer);
};

export default function LearningPathDetail() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const { pathId } = useParams();
  const location = useLocation();

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [path, setPath] = useState<LearningPath | null>(null);
  const [screenMode, setScreenMode] = useState<ScreenMode>('subject');
  const [lessonTab, setLessonTab] = useState<LessonTab>('lesson');
  const [selectedLesson, setSelectedLesson] = useState<LessonNode | null>(null);
  const [lessonRecommendedChunks, setLessonRecommendedChunks] =
    useState<LessonRecommendedChunks | null>(null);
  const [adaptiveNextAction, setAdaptiveNextAction] = useState<AdaptiveNextAction | null>(null);
  const [adaptiveRecommendation, setAdaptiveRecommendation] =
    useState<AdaptiveRecommendationPayload | null>(null);
  const [lessonResourcesLoading, setLessonResourcesLoading] = useState(false);
  const [questionBank, setQuestionBank] = useState<LessonQuestionBank | null>(null);
  const [questionLoading, setQuestionLoading] = useState(false);
  const [questionGenerating, setQuestionGenerating] = useState(false);
  const [questionError, setQuestionError] = useState<string | null>(null);
  const [questionNotice, setQuestionNotice] = useState<string | null>(null);
  const [bestLessonConfidence, setBestLessonConfidence] = useState<number | null>(null);
  const [questionConfig, setQuestionConfig] = useState<QuestionGenerationConfig>({
    targetCount: 6,
    difficulty: 'beginner',
    questionTypes: ['multiple_choice', 'true_false'],
    bloomLevels: ['remember', 'understand', 'apply'],
  });
  const [viewingPDF, setViewingPDF] = useState<{
    key: string;
    title: string;
    resourceId: string;
    initialPage?: number;
  } | null>(null);
  const [currentReadingResource, setCurrentReadingResource] = useState<LessonResourceCard | null>(
    null,
  );
  const [pinnedLessonResource, setPinnedLessonResource] = useState<PinnedLessonResource | null>(
    null,
  );
  const [pendingDeletePath, setPendingDeletePath] = useState(false);
  const [deletingPath, setDeletingPath] = useState(false);
  const [currentQuestionIndex, setCurrentQuestionIndex] = useState(0);
  const [selectedAnswers, setSelectedAnswers] = useState<Record<string, string>>({});
  const [submitted, setSubmitted] = useState(false);
  const [updatingLessonId, setUpdatingLessonId] = useState<string | null>(null);
  const [mapStatusFilter, setMapStatusFilter] = useState<MapStatusFilter>('all');
  const [mapLayoutMode, setMapLayoutMode] = useState<MapLayoutMode>('chapter');
  const [mapInstance, setMapInstance] = useState<ReactFlowInstance | null>(null);
  const [mapSearchTerm, setMapSearchTerm] = useState('');
  const [mapFocusedChapterId, setMapFocusedChapterId] = useState<string | null>(null);
  const [hoveredLesson, setHoveredLesson] = useState<LessonNode | null>(null);
  const [collapsedChapterIds, setCollapsedChapterIds] = useState<string[]>([]);
  const [mapPresentationMode, setMapPresentationMode] = useState(false);
  const [isMapFullscreen, setIsMapFullscreen] = useState(false);
  const [isMapDetailDrawerOpen, setIsMapDetailDrawerOpen] = useState(false);
  const [isMapControlsDrawerOpen, setIsMapControlsDrawerOpen] = useState(false);
  const [isDesktopOptionsOpen, setIsDesktopOptionsOpen] = useState(false);
  const hasRestoredViewportRef = useRef(false);
  const skipNextAutoFocusRef = useRef(false);
  const mapCanvasRef = useRef<HTMLDivElement | null>(null);
  const mapSearchInputRef = useRef<HTMLInputElement | null>(null);
  const desktopOptionsRef = useRef<HTMLDivElement | null>(null);
  const studyTrackingStartedAtRef = useRef<number | null>(null);
  const trackedLessonIdRef = useRef<string | null>(null);
  const trackedPathIdRef = useRef<string | null>(null);
  const lastSubmittedAttemptKeyRef = useRef<string | null>(null);

  const statePath = (location.state as PathState | null)?.path;

  useEffect(() => {
    if (!user) {
      navigate('/login');
      return;
    }

    if (!pathId && !statePath?.path_id) {
      setError('Không tìm thấy lộ trình');
      setLoading(false);
      return;
    }

    if (statePath?.path_id) {
      setPath(statePath);
      setLoading(false);
      return;
    }

    const loadPath = async () => {
      try {
        setLoading(true);
        setError(null);
        const response = await learningPathService.getLearningPathById(pathId as string);
        if (!response?.path_id) {
          setError('Không tìm thấy lộ trình');
          return;
        }
        setPath(response);
      } catch (err) {
        const message = err instanceof Error ? err.message : 'Không thể tải lộ trình';
        setError(message);
      } finally {
        setLoading(false);
      }
    };

    void loadPath();
  }, [navigate, pathId, statePath, user]);

  const chapters = useMemo(
    () => (path?.curriculum && path.curriculum.length > 0 ? path.curriculum : path?.chapters || []),
    [path],
  );
  const lessons = useMemo(() => buildLessonCollection(chapters), [chapters]);
  const curriculumNotice = useMemo(() => getLearningPathNotice(path), [path]);
  const subjectLabel = getSubjectLabel(path?.subject_id, path?.goal);
  const displayGoal = useMemo(
    () => getDisplayGoal(path?.subject_id, path?.goal),
    [path?.goal, path?.subject_id],
  );
  const collapsedChapterKey = useMemo(
    () => collapsedChapterIds.slice().sort().join(','),
    [collapsedChapterIds],
  );
  const mapViewportStorageKey = useMemo(
    () =>
      path?.path_id
        ? `learning-path-map-viewport:${path.path_id}:${mapLayoutMode}:${mapStatusFilter}:${collapsedChapterKey}`
        : null,
    [collapsedChapterKey, mapLayoutMode, mapStatusFilter, path?.path_id],
  );
  const mapLessons = useMemo(
    () =>
      lessons.filter(
        (lesson) =>
          (mapStatusFilter === 'all' ? true : lesson.status === mapStatusFilter) &&
          (!mapFocusedChapterId || lesson.chapter_id === mapFocusedChapterId) &&
          !collapsedChapterIds.includes(lesson.chapter_id),
      ),
    [collapsedChapterIds, lessons, mapFocusedChapterId, mapStatusFilter],
  );
  const selectedLessonGlobalIndex = useMemo(
    () => lessons.findIndex((lesson) => lesson.lesson_id === selectedLesson?.lesson_id),
    [lessons, selectedLesson?.lesson_id],
  );
  const selectedLessonVisibleIndex = useMemo(
    () => mapLessons.findIndex((lesson) => lesson.lesson_id === selectedLesson?.lesson_id),
    [mapLessons, selectedLesson?.lesson_id],
  );
  const lessonResourceHighlightTerms = useMemo(
    () => extractLessonResourceTerms(selectedLesson),
    [selectedLesson],
  );
  const pinnedLessonResourceStorageKey = useMemo(() => {
    if (!selectedLesson) {
      return null;
    }

    return `learning-path:pinned-resource:${path?.path_id || pathId || 'draft'}:${selectedLesson.lesson_id}`;
  }, [path?.path_id, pathId, selectedLesson]);

  useEffect(() => {
    if (!path?.level) {
      return;
    }

    setQuestionConfig((previous) => ({
      ...previous,
      difficulty: path.level,
    }));
  }, [path?.level]);

  useEffect(() => {
    if (lessons.length === 0) {
      setSelectedLesson(null);
      return;
    }

    setSelectedLesson((previous) => {
      if (previous) {
        const matched = lessons.find((lesson) => lesson.lesson_id === previous.lesson_id);
        if (matched) {
          return matched;
        }
      }
      return lessons.find((lesson) => lesson.status === 'in_progress') || lessons[0];
    });
  }, [lessons]);

  useEffect(() => {
    if (mapLessons.length === 0) {
      return;
    }

    if (
      !selectedLesson ||
      !mapLessons.some((lesson) => lesson.lesson_id === selectedLesson.lesson_id)
    ) {
      setSelectedLesson(mapLessons[0]);
    }
  }, [mapLessons, selectedLesson]);

  useEffect(() => {
    if (
      hoveredLesson &&
      !mapLessons.some((lesson) => lesson.lesson_id === hoveredLesson.lesson_id)
    ) {
      setHoveredLesson(null);
    }
  }, [hoveredLesson, mapLessons]);

  useEffect(() => {
    setViewingPDF(null);
    setCurrentReadingResource(null);
  }, [selectedLesson?.lesson_id]);

  useEffect(() => {
    // Keep quiz state scoped to the currently selected lesson.
    setSelectedAnswers({});
    setSubmitted(false);
    setCurrentQuestionIndex(0);
    setQuestionError(null);
    setQuestionNotice(null);
  }, [selectedLesson?.lesson_id]);

  useEffect(() => {
    if (!pinnedLessonResourceStorageKey) {
      setPinnedLessonResource(null);
      return;
    }

    try {
      const storedValue = window.localStorage.getItem(pinnedLessonResourceStorageKey);
      if (!storedValue) {
        setPinnedLessonResource(null);
        return;
      }

      const parsed = JSON.parse(storedValue) as PinnedLessonResource;
      if (!parsed?.key || !parsed?.title) {
        setPinnedLessonResource(null);
        return;
      }

      setPinnedLessonResource(parsed);
    } catch {
      setPinnedLessonResource(null);
    }
  }, [pinnedLessonResourceStorageKey]);

  useEffect(() => {
    if (!selectedLesson?.lesson_id) {
      setLessonRecommendedChunks(null);
      setLessonResourcesLoading(false);
      return;
    }

    const lessonId = selectedLesson.lesson_id;
    let active = true;

    const loadRecommendedChunks = async () => {
      try {
        if (active) {
          setLessonResourcesLoading(true);
        }
        const existing = await learningPathService.getLessonRecommendedChunks(lessonId);
        if (active) {
          setLessonRecommendedChunks(existing);
        }
      } catch {
        try {
          const generated = await learningPathService.recommendLessonChunks(lessonId, {
            max_chunks: 6,
            metadata: { source: 'learning_path_detail' },
          });
          if (active) {
            setLessonRecommendedChunks(generated);
          }
        } catch {
          if (active) {
            setLessonRecommendedChunks(null);
          }
        }
      } finally {
        if (active) {
          setLessonResourcesLoading(false);
        }
      }
    };

    void loadRecommendedChunks();

    return () => {
      active = false;
    };
  }, [selectedLesson?.lesson_id]);

  useEffect(() => {
    if (!selectedLesson?.lesson_id || !user?.user_id) {
      setAdaptiveNextAction(null);
      setAdaptiveRecommendation(null);
      return;
    }

    let active = true;
    const loadAdaptiveSuggestion = async () => {
      try {
        const [nextAction, recommendation] = await Promise.all([
          adaptiveService.getNextBestAction({
            user_id: user.user_id,
            lesson_id: selectedLesson.lesson_id,
          }),
          adaptiveService.getAdaptiveRecommendation({
            user_id: user.user_id,
            lesson_id: selectedLesson.lesson_id,
            goal: path?.goal || undefined,
            level: path?.level || undefined,
          }),
        ]);
        if (!active) {
          return;
        }
        setAdaptiveNextAction(nextAction);
        setAdaptiveRecommendation(recommendation);
      } catch {
        if (!active) {
          return;
        }
        setAdaptiveNextAction(null);
        setAdaptiveRecommendation(null);
      }
    };

    void loadAdaptiveSuggestion();
    return () => {
      active = false;
    };
  }, [path?.goal, path?.level, selectedLesson?.lesson_id, user?.user_id]);

  useEffect(() => {
    if (screenMode !== 'map' || mapPresentationMode) {
      setIsMapDetailDrawerOpen(false);
      setIsMapControlsDrawerOpen(false);
      setIsDesktopOptionsOpen(false);
    }
  }, [mapPresentationMode, screenMode]);

  useEffect(() => {
    if (!isDesktopOptionsOpen) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        setIsDesktopOptionsOpen(false);
      }
    };

    const handlePointerDown = (event: MouseEvent) => {
      if (!desktopOptionsRef.current?.contains(event.target as globalThis.Node | null)) {
        setIsDesktopOptionsOpen(false);
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    window.addEventListener('mousedown', handlePointerDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      window.removeEventListener('mousedown', handlePointerDown);
    };
  }, [isDesktopOptionsOpen]);

  useEffect(() => {
    hasRestoredViewportRef.current = false;
  }, [mapViewportStorageKey]);

  useEffect(() => {
    const handleFullscreenChange = () => {
      setIsMapFullscreen(document.fullscreenElement === mapCanvasRef.current);
    };

    document.addEventListener('fullscreenchange', handleFullscreenChange);
    return () => document.removeEventListener('fullscreenchange', handleFullscreenChange);
  }, []);

  const currentLessonResources = useMemo<LessonResourceCard[]>(() => {
    if (lessonRecommendedChunks?.recommended_chunks?.length) {
      return lessonRecommendedChunks.recommended_chunks.map((chunk, index) => ({
        key: chunk.chunk_id || `${chunk.resource_id}-${index}`,
        title:
          (chunk.resource_source || '').toLowerCase() === 'pdf'
            ? formatPdfResourceTitle(chunk.resource_title || '') || `Tài liệu gợi ý ${index + 1}`
            : chunk.resource_title?.trim() || `Tài liệu gợi ý ${index + 1}`,
        source: formatResourceSource(chunk.resource_source),
        preview: chunk.preview?.trim() || 'Đang đồng bộ nội dung học liệu từ backend.',
        resourceId: chunk.resource_id || undefined,
        resourceUrl: chunk.resource_url || undefined,
        pageNumber: chunk.page_number,
        instructionRole: chunk.instruction_role,
        estimatedReadTime: chunk.estimated_read_time,
        questionabilityScore: chunk.questionability_score,
        coveredConcepts: chunk.covered_concepts,
        sequencePosition: chunk.sequence_position,
        actionLabel:
          (chunk.resource_source || '').toLowerCase() === 'pdf' ? 'Đọc tài liệu' : 'Mở tài liệu',
      }));
    }

    if (selectedLesson?.resources?.length) {
      return selectedLesson.resources.map((resource, index) => ({
        key: `${resource}-${index}`,
        title: `Học liệu gợi ý ${index + 1}`,
        source: getResourceSource(resource),
        preview: getResourcePreview(getResourceSource(resource)),
      }));
    }

    return [
      {
        key: 'fallback-pdf',
        title: 'Học liệu gợi ý 1',
        source: 'PDF',
        preview: 'Bản xem trước bìa',
      },
      {
        key: 'fallback-video',
        title: 'Học liệu gợi ý 2',
        source: 'Youtube',
        preview: 'Thumbnail clip Youtube',
      },
      {
        key: 'fallback-web',
        title: 'Học liệu gợi ý 3',
        source: 'Trang web',
        preview: 'Xem trước tài nguyên',
      },
    ];
  }, [lessonRecommendedChunks, selectedLesson?.resources]);

  const lessonSequenceMeta = useMemo(
    () => (lessonRecommendedChunks?.sequence_metadata as Record<string, unknown> | undefined) || {},
    [lessonRecommendedChunks],
  );

  const resolvedPinnedLessonResource = useMemo<PinnedLessonResource | null>(() => {
    if (!pinnedLessonResource) {
      return null;
    }

    const matchedResource = currentLessonResources.find(
      (resource) => resource.key === pinnedLessonResource.key,
    );
    if (!matchedResource) {
      return pinnedLessonResource;
    }

    return {
      ...pinnedLessonResource,
      ...matchedResource,
      pageNumber: pinnedLessonResource.pageNumber ?? matchedResource.pageNumber,
    };
  }, [currentLessonResources, pinnedLessonResource]);

  const resolvedCurrentReadingResource = useMemo<LessonResourceCard | null>(() => {
    if (!currentReadingResource) {
      return null;
    }

    const matchedResource = currentLessonResources.find(
      (resource) => resource.key === currentReadingResource.key,
    );
    if (!matchedResource) {
      return currentReadingResource;
    }

    return {
      ...matchedResource,
      pageNumber: currentReadingResource.pageNumber ?? matchedResource.pageNumber,
    };
  }, [currentLessonResources, currentReadingResource]);

  const persistPinnedLessonResource = useCallback(
    (resource: PinnedLessonResource | null) => {
      setPinnedLessonResource(resource);

      if (!pinnedLessonResourceStorageKey) {
        return;
      }

      try {
        if (!resource) {
          window.localStorage.removeItem(pinnedLessonResourceStorageKey);
          return;
        }

        window.localStorage.setItem(pinnedLessonResourceStorageKey, JSON.stringify(resource));
      } catch {
        // Ignore storage write issues so the lesson experience still works in-memory.
      }
    },
    [pinnedLessonResourceStorageKey],
  );

  const buildLessonResourceOpenUrl = useCallback((resource: LessonResourceCard) => {
    if (!resource.resourceId) {
      return resource.resourceUrl || null;
    }

    if (resource.source === 'PDF') {
      const apiBaseUrl = import.meta.env.VITE_API_URL || 'http://localhost:8000';
      const apiBasePath = import.meta.env.VITE_API_BASE_PATH || '/api';
      const normalizedBaseUrl = apiBaseUrl.replace(/\/$/, '');
      const normalizedBasePath = apiBasePath.startsWith('/') ? apiBasePath : `/${apiBasePath}`;
      const baseUrl = `${normalizedBaseUrl}${normalizedBasePath}/resources/pdf/${resource.resourceId}`;
      return resource.pageNumber ? `${baseUrl}#page=${resource.pageNumber}` : baseUrl;
    }

    return resource.resourceUrl || null;
  }, []);

  const handleTogglePinnedLessonResource = useCallback(
    (resource: LessonResourceCard, pageOverride?: number) => {
      if (resolvedPinnedLessonResource?.key === resource.key) {
        persistPinnedLessonResource(null);
        return;
      }

      persistPinnedLessonResource({
        ...resource,
        pageNumber: pageOverride ?? resource.pageNumber,
        pinnedAt: new Date().toISOString(),
      });
    },
    [persistPinnedLessonResource, resolvedPinnedLessonResource?.key],
  );

  const handleOpenLessonResource = useCallback((resource: LessonResourceCard) => {
    const resourceSnapshot = {
      ...resource,
    };

    setCurrentReadingResource(resourceSnapshot);

    if (!resource.resourceId) {
      if (resource.resourceUrl) {
        window.open(resource.resourceUrl, '_blank', 'noopener,noreferrer');
      }
      return;
    }

    if (resource.source === 'PDF') {
      setViewingPDF({
        key: resource.key,
        title: resource.title,
        resourceId: resource.resourceId,
        initialPage: resource.pageNumber,
      });
      return;
    }

    if (resource.resourceUrl) {
      window.open(resource.resourceUrl, '_blank', 'noopener,noreferrer');
    }
  }, []);

  const handleMarkLessonResourceCompleted = useCallback(
    async (resource: LessonResourceCard, context: string = 'resource_card') => {
      const lessonStatus = String(selectedLesson?.status || '').toLowerCase();
      const canMarkCompleted = lessonStatus === 'complete' || lessonStatus === 'completed';
      if (!canMarkCompleted) {
        return;
      }

      try {
        await recommendationInteractionService.trackResourceCompleted({
          resource_id: toNumericResourceId(resource.resourceId),
          lesson_id: selectedLesson?.lesson_id,
          goal: path?.goal,
          level: path?.level,
          metadata: {
            source_screen: 'learning_path_detail',
            completion_context: context,
            path_id: path?.path_id,
            lesson_id: selectedLesson?.lesson_id,
            resource_key: resource.key,
            resource_source: resource.source,
            resource_identifier: resource.resourceId || resource.resourceUrl,
            page_number: resource.pageNumber,
          },
        });
      } catch (completionError) {
        console.error('Failed to track lesson resource completion:', completionError);
      }
    },
    [path?.goal, path?.level, path?.path_id, selectedLesson?.lesson_id, selectedLesson?.status],
  );

  const handleOpenAllLessonResources = useCallback(() => {
    currentLessonResources.forEach((resource) => {
      const targetUrl = buildLessonResourceOpenUrl(resource);
      if (!targetUrl) {
        return;
      }
      window.open(targetUrl, '_blank', 'noopener,noreferrer');
    });
  }, [buildLessonResourceOpenUrl, currentLessonResources]);

  const handleOpenAdaptiveLessonSuggestion = useCallback(() => {
    const firstItem =
      adaptiveRecommendation?.items?.[0] &&
      typeof adaptiveRecommendation.items[0] === 'object' &&
      !Array.isArray(adaptiveRecommendation.items[0])
        ? (adaptiveRecommendation.items[0] as Record<string, unknown>)
        : null;

    if (!firstItem) {
      return;
    }

    if (adaptiveRecommendation?.recommendation_type === 'chunk') {
      const resourceId =
        typeof firstItem.resource_id === 'string' ? firstItem.resource_id : undefined;
      const matchedResource = currentLessonResources.find((resource) => resource.resourceId === resourceId);
      if (matchedResource) {
        handleOpenLessonResource(matchedResource);
        return;
      }
      if (currentLessonResources[0]) {
        handleOpenLessonResource(currentLessonResources[0]);
      }
      return;
    }

    if (adaptiveRecommendation?.recommendation_type === 'lesson') {
      if (selectedLesson) {
        setScreenMode('lesson');
        setLessonTab('lesson');
      }
      return;
    }

    const resourceUrl = typeof firstItem.url === 'string' ? firstItem.url : undefined;
    if (resourceUrl) {
      window.open(resourceUrl, '_blank', 'noopener,noreferrer');
      return;
    }

    const resourceId = typeof firstItem.resource_id === 'string' ? firstItem.resource_id : undefined;
    const matchedResource = currentLessonResources.find((resource) => resource.resourceId === resourceId);
    if (matchedResource) {
      handleOpenLessonResource(matchedResource);
    }
  }, [
    adaptiveRecommendation,
    currentLessonResources,
    handleOpenLessonResource,
    selectedLesson,
  ]);

  const handlePDFViewerPageChange = useCallback(
    (page: number) => {
      setCurrentReadingResource((previous) =>
        previous && viewingPDF && previous.key === viewingPDF.key
          ? {
              ...previous,
              pageNumber: page,
            }
          : previous,
      );

      if (!viewingPDF) {
        return;
      }

      if (resolvedPinnedLessonResource?.key === viewingPDF.key) {
        persistPinnedLessonResource({
          ...resolvedPinnedLessonResource,
          pageNumber: page,
        });
      }
    },
    [persistPinnedLessonResource, resolvedPinnedLessonResource, viewingPDF],
  );

  const handleTogglePinnedViewingPDF = useCallback(
    (page: number) => {
      if (!viewingPDF) {
        return;
      }

      const resourceToPin =
        currentLessonResources.find((resource) => resource.key === viewingPDF.key) ||
        (resolvedCurrentReadingResource?.key === viewingPDF.key
          ? resolvedCurrentReadingResource
          : null) ||
        null;

      if (!resourceToPin) {
        return;
      }

      handleTogglePinnedLessonResource(resourceToPin, page);
      setCurrentReadingResource({
        ...resourceToPin,
        pageNumber: page,
      });
    },
    [
      currentLessonResources,
      handleTogglePinnedLessonResource,
      resolvedCurrentReadingResource,
      viewingPDF,
    ],
  );

  const renderHighlightedPreview = useCallback(
    (preview: string) => {
      if (!lessonResourceHighlightTerms.length) {
        return preview;
      }

      const escapedTerms = lessonResourceHighlightTerms
        .map((term) => term.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'))
        .filter(Boolean);
      if (!escapedTerms.length) {
        return preview;
      }

      const regex = new RegExp(`(${escapedTerms.join('|')})`, 'giu');
      const parts = preview.split(regex);

      return parts.map((part, index) => {
        const normalized = part.toLowerCase();
        const isHighlighted = lessonResourceHighlightTerms.some((term) => normalized === term);
        if (!isHighlighted) {
          return <span key={`${part}-${index}`}>{part}</span>;
        }

        return (
          <mark
            key={`${part}-${index}`}
            className="rounded-[6px] bg-[#ffe6f0] px-1 py-0.5 font-semibold text-[#8c3451]"
          >
            {part}
          </mark>
        );
      });
    },
    [lessonResourceHighlightTerms],
  );

  const quizQuestions = useMemo(() => {
    return questionBank?.questions || [];
  }, [questionBank]);

  const currentQuestion = quizQuestions[currentQuestionIndex] || null;
  const currentQuestionSources = useMemo(() => {
    if (!currentQuestion || !lessonRecommendedChunks?.recommended_chunks?.length) {
      return [];
    }

    return currentQuestion.chunk_ids
      .map((chunkId) =>
        lessonRecommendedChunks.recommended_chunks.find((item) => item.chunk_id === chunkId),
      )
      .filter((item): item is NonNullable<typeof item> => Boolean(item));
  }, [currentQuestion, lessonRecommendedChunks]);

  const quizStats = useMemo(() => {
    const total = quizQuestions.length;
    const correct = quizQuestions.reduce((count, question) => {
      return isQuestionAnsweredCorrectly(question, selectedAnswers[question.question_id])
        ? count + 1
        : count;
    }, 0);
    const wrong = submitted ? Math.max(total - correct, 0) : 0;
    const confidence = total > 0 && submitted ? Math.round((correct / total) * 100) : 0;
    return { total, correct, wrong, confidence };
  }, [quizQuestions, selectedAnswers, submitted]);
  const answeredQuestionCount = useMemo(
    () =>
      quizQuestions.filter((question) => Boolean(selectedAnswers[question.question_id]?.trim()))
        .length,
    [quizQuestions, selectedAnswers],
  );

  const loadLessonAttemptStatistics = useCallback(async (lessonId: string) => {
    try {
      const stats = await learningPathService.getLessonAttemptStatistics(lessonId);
      if (stats.best_confidence == null) {
        setBestLessonConfidence(null);
        return;
      }
      setBestLessonConfidence(Math.round(stats.best_confidence * 100));
    } catch {
      setBestLessonConfidence(null);
    }
  }, []);

  useEffect(() => {
    if (!selectedLesson?.lesson_id) {
      setBestLessonConfidence(null);
      return;
    }
    void loadLessonAttemptStatistics(selectedLesson.lesson_id);
  }, [loadLessonAttemptStatistics, selectedLesson?.lesson_id]);

  useEffect(() => {
    if (!submitted) {
      lastSubmittedAttemptKeyRef.current = null;
    }
  }, [submitted]);

  const handleSubmitQuizAnswers = useCallback(() => {
    if (submitted || quizQuestions.length === 0 || answeredQuestionCount === 0) {
      return;
    }

    // Show grading state immediately in the UI.
    setSubmitted(true);

    if (!selectedLesson?.lesson_id || !path?.path_id) {
      return;
    }

    const lessonId = selectedLesson.lesson_id;
    const questionsAnswered = quizQuestions.map((question) => ({
      question_id: question.question_id,
      question: question.question,
      question_type: question.question_type,
      user_answer: selectedAnswers[question.question_id] || '',
      correct_answer: question.correct_answer,
      is_correct: isQuestionAnsweredCorrectly(question, selectedAnswers[question.question_id]),
      difficulty: question.difficulty,
      bloom_level: question.bloom_level,
    }));
    const correctCount = questionsAnswered.reduce(
      (count, answer) => (answer.is_correct ? count + 1 : count),
      0,
    );
    const confidencePercent =
      questionsAnswered.length > 0 ? Math.round((correctCount / questionsAnswered.length) * 100) : 0;
    const confidenceDecimal = confidencePercent / 100;
    const attemptKey = `${path.path_id}:${lessonId}:${confidencePercent}:${correctCount}/${questionsAnswered.length}`;

    if (lastSubmittedAttemptKeyRef.current === attemptKey) {
      return;
    }
    lastSubmittedAttemptKeyRef.current = attemptKey;

    const submit = async () => {
      try {
        const response = await learningPathService.updateLessonProgress({
          path_id: path.path_id,
          lesson_id: lessonId,
          status: 'in_progress',
          confidence: confidenceDecimal,
          questions_answered: questionsAnswered,
        });

        if (response.auto_completed && response.status === 'complete') {
          setPath((previousPath) => {
            if (!previousPath) {
              return previousPath;
            }
            return updateLessonStatusInPath(previousPath, lessonId, response.status);
          });
        }

        void loadLessonAttemptStatistics(lessonId);
      } catch (err) {
        console.error('Failed to submit quiz confidence:', err);
        if (lastSubmittedAttemptKeyRef.current === attemptKey) {
          lastSubmittedAttemptKeyRef.current = null;
        }
      }
    };

    void submit();
  }, [
    answeredQuestionCount,
    loadLessonAttemptStatistics,
    path?.path_id,
    quizQuestions,
    selectedAnswers,
    selectedLesson?.lesson_id,
    submitted,
  ]);

  const openLessonScreen = useCallback((lesson: LessonNode) => {
    setSelectedLesson(lesson);
    setLessonTab('lesson');
    setScreenMode('lesson');
  }, []);

  const handleMapLessonSelect = useCallback(
    (lesson: LessonNode) => {
      if (selectedLesson?.lesson_id === lesson.lesson_id && lesson.status !== 'not_started') {
        openLessonScreen(lesson);
        return;
      }
      setSelectedLesson(lesson);
    },
    [openLessonScreen, selectedLesson?.lesson_id],
  );

  const mapNodes = useMemo<Node[]>(() => {
    const visibleChapters = chapters
      .map((chapter, chapterIndex) => ({ chapter, chapterIndex }))
      .filter(({ chapter }) => !collapsedChapterIds.includes(chapter.chapter_id));

    const chapterNodes: Node<MapChapterNodeData>[] = visibleChapters.map(
      ({ chapter, chapterIndex }, visibleIndex) => ({
        id: `chapter-${chapter.chapter_id || chapterIndex + 1}`,
        type: 'chapterNode',
        position: {
          x:
            mapLayoutMode === 'chapter'
              ? 80 + visibleIndex * CHAPTER_SPACING_X
              : 60 + (visibleIndex % JOURNEY_COLUMNS) * JOURNEY_SPACING_X,
          y: CHAPTER_LABEL_OFFSET_Y,
        },
        data: {
          chapterIndex: chapterIndex + 1,
          title: chapter.title,
          accent: getChapterAccent(chapterIndex + 1),
        },
        draggable: false,
        selectable: false,
        style: {
          width: 280,
          background: 'transparent',
          border: 'none',
        },
      }),
    );

    const lessonNodes: Node<MapLessonNodeData>[] = mapLessons.map((lesson, index) => {
      const accent = getChapterAccent(lesson.chapter_index);
      const chapterOffset = (lesson.chapter_index - 1) * CHAPTER_SPACING_X;
      const rowOffset = (lesson.lesson_index - 1) * LESSON_SPACING_Y;
      const chapterStagger = (lesson.chapter_index % 2) * 54;
      const lessonStagger = ((lesson.lesson_index + index) % 2) * 34;
      const journeyColumn = index % JOURNEY_COLUMNS;
      const journeyRow = Math.floor(index / JOURNEY_COLUMNS);
      const isZigzagRow = journeyRow % 2 === 1;

      return {
        id: lesson.lesson_id,
        type: 'lessonNode',
        position: {
          x:
            mapLayoutMode === 'chapter'
              ? 80 + chapterOffset + lessonStagger
              : 60 +
                (isZigzagRow ? JOURNEY_COLUMNS - 1 - journeyColumn : journeyColumn) *
                  JOURNEY_SPACING_X,
          y:
            mapLayoutMode === 'chapter'
              ? 92 + rowOffset + chapterStagger
              : 100 + journeyRow * JOURNEY_SPACING_Y + (journeyColumn % 2) * 28,
        },
        data: {
          lesson,
          isSelected: selectedLesson?.lesson_id === lesson.lesson_id,
          isInPath:
            selectedLessonVisibleIndex >= 0 &&
            mapLessons.findIndex((item) => item.lesson_id === lesson.lesson_id) <=
              selectedLessonVisibleIndex,
          onSelect: handleMapLessonSelect,
          onOpenLesson: openLessonScreen,
          onHoverLesson: setHoveredLesson,
          accent,
        },
        draggable: false,
        selectable: false,
        sourcePosition: Position.Bottom,
        targetPosition: Position.Top,
        style: {
          width: MAP_NODE_WIDTH,
          height: MAP_NODE_HEIGHT,
          background: 'transparent',
          border: 'none',
        },
      };
    });

    return [...chapterNodes, ...lessonNodes];
  }, [
    chapters,
    collapsedChapterIds,
    handleMapLessonSelect,
    mapLayoutMode,
    mapLessons,
    openLessonScreen,
    selectedLesson?.lesson_id,
    selectedLessonVisibleIndex,
  ]);

  const mapEdges = useMemo<Edge[]>(
    () =>
      mapLessons.slice(1).map((lesson, index) => {
        const previousLesson = mapLessons[index];
        const chapterChanged = previousLesson.chapter_id !== lesson.chapter_id;
        const isHighlighted =
          selectedLessonVisibleIndex >= index + 1 && selectedLessonVisibleIndex >= 0;
        const accent = getChapterAccent(previousLesson.chapter_index);

        return {
          id: `${previousLesson.lesson_id}-${lesson.lesson_id}`,
          source: previousLesson.lesson_id,
          target: lesson.lesson_id,
          type: chapterChanged ? 'smoothstep' : 'default',
          label: chapterChanged
            ? 'Sang chương mới'
            : isHighlighted
              ? 'Đường học hiện tại'
              : previousLesson.status === 'complete' && lesson.status === 'not_started'
                ? 'Mở khóa tiếp theo'
                : 'Bước tiếp theo',
          labelStyle: {
            fill: isHighlighted ? accent.solid : '#7a726c',
            fontWeight: 600,
            fontSize: 11,
          },
          labelBgStyle: {
            fill: '#fffafc',
            fillOpacity: 0.92,
            stroke: chapterChanged ? accent.border : 'rgba(140,52,81,0.08)',
            strokeWidth: 1,
            rx: 999,
            ry: 999,
          },
          labelBgPadding: [10, 5],
          labelBgBorderRadius: 999,
          animated: previousLesson.status === 'complete' && lesson.status === 'in_progress',
          markerEnd: {
            type: MarkerType.ArrowClosed,
            width: 18,
            height: 18,
            color: isHighlighted ? accent.solid : '#d38ba1',
          },
          style: {
            stroke: isHighlighted ? accent.solid : '#d38ba1',
            strokeWidth: isHighlighted ? 3 : chapterChanged ? 2.5 : 2,
            strokeDasharray: chapterChanged ? '7 7' : '0',
          },
        };
      }),
    [mapLessons, selectedLessonVisibleIndex],
  );

  const searchedLessons = useMemo(() => {
    const keyword = mapSearchTerm.trim().toLowerCase();
    if (!keyword) {
      return [];
    }

    return lessons.filter((lesson) => {
      const title = cleanLessonTitle(lesson.title).toLowerCase();
      const summary = lesson.summary?.toLowerCase() || '';
      return title.includes(keyword) || summary.includes(keyword);
    });
  }, [lessons, mapSearchTerm]);

  useEffect(() => {
    if (
      screenMode !== 'map' ||
      !mapInstance ||
      !mapViewportStorageKey ||
      hasRestoredViewportRef.current
    ) {
      return;
    }

    hasRestoredViewportRef.current = true;

    const rawViewport = localStorage.getItem(mapViewportStorageKey);
    if (!rawViewport) {
      return;
    }

    try {
      const parsedViewport = JSON.parse(rawViewport) as { x: number; y: number; zoom: number };
      skipNextAutoFocusRef.current = true;
      window.setTimeout(() => {
        mapInstance.setViewport(parsedViewport, { duration: 0 });
      }, 0);
    } catch (restoreError) {
      console.error('Failed to restore learning path viewport:', restoreError);
    }
  }, [mapInstance, mapViewportStorageKey, screenMode]);

  useEffect(() => {
    if (screenMode !== 'map' || !mapInstance || !selectedLesson) {
      return;
    }

    if (skipNextAutoFocusRef.current) {
      skipNextAutoFocusRef.current = false;
      return;
    }

    const selectedNode = mapNodes.find((node) => node.id === selectedLesson.lesson_id);
    if (!selectedNode || !selectedNode.position) {
      return;
    }

    const centerX = selectedNode.position.x + MAP_NODE_WIDTH / 2;
    const centerY = selectedNode.position.y + MAP_NODE_HEIGHT / 2;

    window.setTimeout(() => {
      mapInstance.setCenter(centerX, centerY, {
        zoom: mapLayoutMode === 'chapter' ? 0.84 : 0.78,
        duration: 500,
      });
    }, 60);
  }, [mapInstance, mapLayoutMode, mapNodes, screenMode, selectedLesson]);

  const handleMapSearch = () => {
    if (searchedLessons.length === 0) {
      return;
    }

    setMapStatusFilter('all');
    setMapFocusedChapterId(null);
    setSelectedLesson(searchedLessons[0]);
  };

  const handleFocusChapter = (chapterId?: string) => {
    if (!chapterId) {
      return;
    }

    setMapStatusFilter('all');
    setCollapsedChapterIds((previous) => previous.filter((id) => id !== chapterId));
    const firstLesson = lessons.find((lesson) => lesson.chapter_id === chapterId);
    if (firstLesson) {
      setSelectedLesson(firstLesson);
    }
  };

  const handleExpandAllChapters = () => {
    setCollapsedChapterIds([]);
  };

  const handleCollapseOtherChapters = () => {
    if (!selectedLesson) {
      return;
    }

    const nextCollapsed = chapters
      .filter((chapter) => chapter.chapter_id !== selectedLesson.chapter_id)
      .map((chapter) => chapter.chapter_id);

    setCollapsedChapterIds(nextCollapsed);
    setMapFocusedChapterId(selectedLesson.chapter_id);
  };

  const handleToggleFocusedChapter = () => {
    if (!selectedLesson) {
      return;
    }

    setMapStatusFilter('all');
    setMapFocusedChapterId((previous) =>
      previous === selectedLesson.chapter_id ? null : selectedLesson.chapter_id,
    );
  };

  const handleFitAllMapNodes = useCallback(() => {
    if (!mapInstance || mapLessons.length === 0) {
      return;
    }

    mapInstance.fitView({
      padding: 0.18,
      duration: 500,
    });
  }, [mapInstance, mapLessons.length]);

  const handleFitCurrentChapter = useCallback(() => {
    if (!mapInstance || !selectedLesson) {
      return;
    }

    const chapterNodeId = `chapter-${selectedLesson.chapter_id || selectedLesson.chapter_index}`;
    const targetNodes = mapNodes.filter((node) => {
      if (node.id === chapterNodeId) {
        return true;
      }
      const lessonNode = node.data as MapLessonNodeData | undefined;
      return lessonNode?.lesson?.chapter_id === selectedLesson.chapter_id;
    });

    if (targetNodes.length === 0) {
      return;
    }

    mapInstance.fitView({
      nodes: targetNodes,
      padding: 0.22,
      duration: 500,
    });
  }, [mapInstance, mapNodes, selectedLesson]);

  const handlePersistViewport = () => {
    if (!mapInstance || !mapViewportStorageKey) {
      return;
    }

    try {
      localStorage.setItem(mapViewportStorageKey, JSON.stringify(mapInstance.getViewport()));
    } catch (persistError) {
      console.error('Failed to persist learning path viewport:', persistError);
    }
  };

  const handleToggleMapFullscreen = async () => {
    const element = mapCanvasRef.current;
    if (!element) {
      return;
    }

    try {
      if (document.fullscreenElement === element) {
        await document.exitFullscreen();
        return;
      }

      setMapPresentationMode(true);
      await element.requestFullscreen();
    } catch (fullscreenError) {
      console.error('Failed to toggle learning path fullscreen:', fullscreenError);
    }
  };

  const previousLesson =
    selectedLessonGlobalIndex > 0 ? lessons[selectedLessonGlobalIndex - 1] : null;
  const nextLesson =
    selectedLessonGlobalIndex >= 0 && selectedLessonGlobalIndex < lessons.length - 1
      ? lessons[selectedLessonGlobalIndex + 1]
      : null;
  const previewLesson = hoveredLesson || selectedLesson;
  const currentChapterProgress = selectedLesson
    ? chapters.find((chapter) => chapter.chapter_id === selectedLesson.chapter_id)
    : null;
  const currentChapterLessons = currentChapterProgress?.lessons || [];
  const currentChapterCompleted = currentChapterLessons.filter(
    (lesson) => lesson.status === 'complete',
  ).length;

  useEffect(() => {
    if (screenMode !== 'map') {
      return;
    }

    const handleMapShortcuts = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      const isTypingTarget =
        target instanceof HTMLInputElement ||
        target instanceof HTMLTextAreaElement ||
        target instanceof HTMLSelectElement ||
        target?.isContentEditable;

      if (event.key === 'Escape') {
        if (document.fullscreenElement === mapCanvasRef.current) {
          void document.exitFullscreen();
          return;
        }

        if (mapPresentationMode) {
          setMapPresentationMode(false);
        }
        return;
      }

      if (isTypingTarget) {
        return;
      }

      if (event.key === '/') {
        event.preventDefault();
        mapSearchInputRef.current?.focus();
        mapSearchInputRef.current?.select();
        return;
      }

      if (event.key === 'ArrowLeft' && previousLesson) {
        event.preventDefault();
        setMapStatusFilter('all');
        setMapFocusedChapterId(null);
        setSelectedLesson(previousLesson);
        return;
      }

      if (event.key === 'ArrowRight' && nextLesson) {
        event.preventDefault();
        setMapStatusFilter('all');
        setMapFocusedChapterId(null);
        setSelectedLesson(nextLesson);
        return;
      }

      if (event.key.toLowerCase() === 'f') {
        event.preventDefault();
        handleFitAllMapNodes();
        return;
      }

      if (event.key.toLowerCase() === 'c') {
        event.preventDefault();
        handleFitCurrentChapter();
        return;
      }

      if (event.key.toLowerCase() === 'p') {
        event.preventDefault();
        setMapPresentationMode((value) => !value);
      }
    };

    window.addEventListener('keydown', handleMapShortcuts);
    return () => window.removeEventListener('keydown', handleMapShortcuts);
  }, [
    mapPresentationMode,
    nextLesson,
    previousLesson,
    screenMode,
    handleFitAllMapNodes,
    handleFitCurrentChapter,
  ]);

  const flushTrackedStudyTime = useCallback(async (keepTracking = false) => {
    const trackedPathId = trackedPathIdRef.current;
    const trackedLessonId = trackedLessonIdRef.current;
    const startedAt = studyTrackingStartedAtRef.current;

    if (!trackedPathId || !trackedLessonId || !startedAt) {
      return;
    }

    const elapsedSeconds = Math.floor((Date.now() - startedAt) / 1000);
    if (elapsedSeconds < STUDY_TIME_MIN_SECONDS) {
      if (keepTracking) {
        studyTrackingStartedAtRef.current = Date.now();
      } else {
        studyTrackingStartedAtRef.current = null;
        trackedLessonIdRef.current = null;
        trackedPathIdRef.current = null;
      }
      return;
    }

    try {
      await learningPathService.recordLessonStudyTime({
        path_id: trackedPathId,
        lesson_id: trackedLessonId,
        seconds_spent: elapsedSeconds,
      });
    } catch (trackingError) {
      console.error('Failed to record lesson study time:', trackingError);
    } finally {
      if (keepTracking) {
        studyTrackingStartedAtRef.current = Date.now();
      } else {
        studyTrackingStartedAtRef.current = null;
        trackedLessonIdRef.current = null;
        trackedPathIdRef.current = null;
      }
    }
  }, []);

  useEffect(() => {
    const activePathId = path?.path_id || null;
    const activeLessonId = screenMode === 'lesson' ? selectedLesson?.lesson_id || null : null;
    const trackedLessonId = trackedLessonIdRef.current;
    const trackedPathId = trackedPathIdRef.current;

    if (
      trackedLessonId &&
      trackedPathId &&
      (!activeLessonId ||
        !activePathId ||
        trackedLessonId !== activeLessonId ||
        trackedPathId !== activePathId)
    ) {
      void flushTrackedStudyTime(false);
    }

    if (
      activePathId &&
      activeLessonId &&
      (trackedLessonId !== activeLessonId ||
        trackedPathId !== activePathId ||
        !studyTrackingStartedAtRef.current)
    ) {
      trackedPathIdRef.current = activePathId;
      trackedLessonIdRef.current = activeLessonId;
      studyTrackingStartedAtRef.current = Date.now();
    }
  }, [flushTrackedStudyTime, path?.path_id, screenMode, selectedLesson?.lesson_id]);

  useEffect(() => {
    const handleVisibilityChange = () => {
      if (document.visibilityState === 'hidden') {
        void flushTrackedStudyTime(false);
        return;
      }

      if (
        document.visibilityState === 'visible' &&
        trackedLessonIdRef.current &&
        trackedPathIdRef.current
      ) {
        studyTrackingStartedAtRef.current = Date.now();
      }
    };

    const intervalId = window.setInterval(() => {
      if (
        trackedLessonIdRef.current &&
        trackedPathIdRef.current &&
        studyTrackingStartedAtRef.current
      ) {
        void flushTrackedStudyTime(true);
      }
    }, STUDY_TIME_FLUSH_INTERVAL_MS);

    document.addEventListener('visibilitychange', handleVisibilityChange);
    return () => {
      window.clearInterval(intervalId);
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      void flushTrackedStudyTime(false);
    };
  }, [flushTrackedStudyTime]);

  const handleLessonStatusUpdate = async (lessonId: string, status: LessonStatus) => {
    if (!path?.path_id) {
      return;
    }

    try {
      setUpdatingLessonId(lessonId);
      setError(null);

      const includeQuizPayload =
        status === 'complete' &&
        selectedLesson?.lesson_id === lessonId &&
        submitted &&
        quizQuestions.length > 0;

      const questionsAnswered = includeQuizPayload
        ? quizQuestions.map((question) => ({
            question_id: question.question_id,
            question: question.question,
            question_type: question.question_type,
            user_answer: selectedAnswers[question.question_id] || '',
            correct_answer: question.correct_answer,
            is_correct: isQuestionAnsweredCorrectly(
              question,
              selectedAnswers[question.question_id],
            ),
            difficulty: question.difficulty,
            bloom_level: question.bloom_level,
          }))
        : undefined;

      const response = await learningPathService.updateLessonProgress({
        path_id: path.path_id,
        lesson_id: lessonId,
        status,
        confidence: includeQuizPayload ? quizStats.confidence / 100 : undefined,
        questions_answered: questionsAnswered,
      });

      setPath((previousPath) => {
        if (!previousPath) {
          return previousPath;
        }
        return updateLessonStatusInPath(previousPath, lessonId, response.status);
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Không thể cập nhật tiến độ bài học';
      setError(message);
    } finally {
      setUpdatingLessonId(null);
    }
  };

  const loadLessonQuestions = async (lessonId: string) => {
    try {
      setQuestionLoading(true);
      setQuestionError(null);
      setQuestionNotice(null);
      const response = await learningPathService.getLessonQuestions(lessonId);
      setQuestionBank(response);
      setCurrentQuestionIndex(0);
      setSelectedAnswers({});
      setSubmitted(false);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Không thể tải câu hỏi ôn tập';
      setQuestionError(message);
      setQuestionBank(null);
    } finally {
      setQuestionLoading(false);
    }
  };

  const generateLessonQuestions = async (overwrite = true) => {
    if (!selectedLesson) {
      return;
    }

    try {
      setQuestionGenerating(true);
      setQuestionError(null);
      setQuestionNotice(null);
      const result = await learningPathService.generateLessonQuestions(selectedLesson.lesson_id, {
        target_count: questionConfig.targetCount,
        question_types: questionConfig.questionTypes,
        difficulty: questionConfig.difficulty,
        bloom_levels: questionConfig.bloomLevels,
        overwrite,
        metadata: {
          source: 'learning_path_quiz',
          config_target_count: questionConfig.targetCount,
          config_question_types: questionConfig.questionTypes,
          config_bloom_levels: questionConfig.bloomLevels,
          config_difficulty: questionConfig.difficulty,
        },
      });
      if (result.reused_existing && result.existing_count > 0) {
        await loadLessonQuestions(selectedLesson.lesson_id);
        setQuestionNotice(
          result.message || 'Đang dùng lại bộ câu hỏi đã tạo trước đó cho bài học này.',
        );
        return;
      }
      if (result.insufficient_data || result.generated_count === 0) {
        setQuestionBank({
          lesson_id: selectedLesson.lesson_id,
          total: 0,
          questions: [],
        });
        setQuestionError(result.message || 'Hiện chưa thể tạo câu hỏi ôn tập cho bài học này.');
        return;
      }
      await loadLessonQuestions(selectedLesson.lesson_id);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Không thể tạo câu hỏi ôn tập';
      setQuestionError(message);
    } finally {
      setQuestionGenerating(false);
    }
  };

  const handleOpenQuestionsTab = async () => {
    setLessonTab('questions');
    if (!selectedLesson) {
      return;
    }
    if (questionBank?.lesson_id === selectedLesson.lesson_id && questionBank.total > 0) {
      return;
    }
    await loadLessonQuestions(selectedLesson.lesson_id);
  };

  const handleSelectAnswer = (questionId: string, value: string) => {
    if (submitted) {
      return;
    }

    setSelectedAnswers((previous) => ({
      ...previous,
      [questionId]: value,
    }));
  };

  const handleQuestionTypeToggle = (questionType: LessonQuestionType) => {
    setQuestionConfig((previous) => {
      const exists = previous.questionTypes.includes(questionType);
      const nextQuestionTypes = exists
        ? previous.questionTypes.filter((item) => item !== questionType)
        : [...previous.questionTypes, questionType];

      return {
        ...previous,
        questionTypes: nextQuestionTypes.length > 0 ? nextQuestionTypes : previous.questionTypes,
      };
    });
  };

  const handleBloomLevelToggle = (bloomLevel: BloomLevel) => {
    setQuestionConfig((previous) => {
      const exists = previous.bloomLevels.includes(bloomLevel);
      const nextBloomLevels = exists
        ? previous.bloomLevels.filter((item) => item !== bloomLevel)
        : [...previous.bloomLevels, bloomLevel];

      return {
        ...previous,
        bloomLevels: nextBloomLevels.length > 0 ? nextBloomLevels : previous.bloomLevels,
      };
    });
  };

  const handleDeletePath = async () => {
    if (!path?.path_id) {
      return;
    }

    try {
      setDeletingPath(true);
      setError(null);
      await learningPathService.deleteLearningPath(path.path_id);
      navigate('/learning-path', {
        state: { notice: 'Đã xóa lộ trình học và dữ liệu sinh kèm.' },
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Không thể xóa lộ trình học';
      setError(message);
    } finally {
      setDeletingPath(false);
      setPendingDeletePath(false);
    }
  };

  const renderHeader = () => (
    <div className={screenMode === 'lesson' ? 'mb-8' : 'mb-10'}>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="page-kicker">Lộ trình học tập</p>
          <h1 className="page-title mb-0 text-[#141217]">
            {screenMode === 'subject'
              ? 'Lộ trình học tập chi tiết'
              : `Lộ trình học tập - ${subjectLabel}`}
          </h1>
        </div>
        {path?.path_id && (
          <button
            type="button"
            onClick={() => setPendingDeletePath(true)}
            className="theme-button-secondary px-5 py-3 text-[14px] text-[#8c3451]"
          >
            Xóa lộ trình
          </button>
        )}
      </div>
      {screenMode === 'lesson' && selectedLesson && (
        <>
          <h2 className="mt-3 text-[28px] font-semibold tracking-[-0.04em] text-[#141217] md:text-[34px]">
            Bài {selectedLesson.chapter_index}.{selectedLesson.lesson_index}:{' '}
            {cleanLessonTitle(selectedLesson.title)}
          </h2>
          <p className="mt-2 max-w-3xl text-[15px] leading-7 text-black/55">
            {selectedLesson.summary?.trim() || 'Nội dung bài học'}
          </p>
        </>
      )}
    </div>
  );

  const renderSubjectScreen = () => (
    <div>
      <div className="white-panel p-7 md:p-8">
        <div className="flex flex-col gap-5 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <h2 className="text-[24px] font-semibold tracking-[-0.03em] text-[#141217] md:text-[30px]">
              {subjectLabel}
              {displayGoal ? ` - ${displayGoal}` : ''}
            </h2>
            <p className="mt-3 max-w-3xl text-[14px] leading-7 text-black/48">
              Lộ trình học tập được cá nhân hóa theo môn học, mục tiêu và tiến độ hiện tại của bạn.
            </p>
          </div>
          <span className="inline-flex shrink-0 items-center rounded-full bg-[#8c3451] px-4 py-2 text-[12px] font-medium text-white">
            {chapters.some((chapter) => getChapterStatusLabel(chapter) === 'Đang học')
              ? 'Đang học'
              : 'Chưa học'}
          </span>
        </div>

        <div className="mt-6 grid gap-4 md:grid-cols-3">
          <div className="metric-card p-4">
            <p className="text-[12px] font-medium uppercase tracking-[0.18em] text-black/35">
              Trình độ
            </p>
            <p className="mt-2 text-[18px] font-semibold capitalize text-[#141217]">
              {path?.level || 'beginner'}
            </p>
          </div>
          <div className="metric-card p-4">
            <p className="text-[12px] font-medium uppercase tracking-[0.18em] text-black/35">
              Ngày tạo
            </p>
            <p className="mt-2 text-[18px] font-semibold text-[#141217]">
              {formatDateTime(path?.generated_at)}
            </p>
          </div>
          <div className="metric-card p-4">
            <p className="text-[12px] font-medium uppercase tracking-[0.18em] text-black/35">
              Số chương
            </p>
            <p className="mt-2 text-[18px] font-semibold text-[#141217]">
              {chapters.length} chương
            </p>
          </div>
        </div>
      </div>

      {curriculumNotice && (
        <div className="mt-4 rounded-[16px] border border-amber-300 bg-amber-50 px-4 py-3 text-[14px] text-amber-900">
          {curriculumNotice}
        </div>
      )}

      <div className="mt-6 flex justify-end">
        <button
          onClick={() => setScreenMode('map')}
          className="theme-button-secondary gap-3 px-5 py-3 text-[14px]"
        >
          Xem lộ trình dạng map
          <span className="text-[16px] leading-none">→</span>
        </button>
      </div>

      <div className="mt-8 space-y-5">
        {chapters.map((chapter, chapterIndex) => {
          const statusLabel = getChapterStatusLabel(chapter);

          return (
            <button
              key={chapter.chapter_id || chapter.title}
              onClick={() => {
                const firstLesson = lessons.find(
                  (lesson) => lesson.chapter_id === chapter.chapter_id,
                );
                if (firstLesson) {
                  openLessonScreen(firstLesson);
                }
              }}
              className="white-panel block w-full px-6 py-6 text-left transition duration-200 hover:-translate-y-0.5 hover:shadow-[0_16px_36px_rgba(45,31,17,0.09)] md:px-7"
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <h3 className="text-[22px] font-semibold tracking-[-0.03em] text-[#141217]">
                    Chương {chapterIndex + 1}: {cleanChapterTitle(chapter.title)}
                  </h3>
                  <p className="mt-3 max-w-3xl text-[14px] leading-7 text-black/55">
                    {getChapterDescription(chapter)}
                  </p>
                </div>
                <span
                  className={`inline-flex shrink-0 items-center rounded-full px-4 py-2 text-[12px] font-medium ${statusLabel === 'Đang học' ? 'bg-[#8c3451] text-white' : 'bg-[#f8e3ea] text-black/65'}`}
                >
                  {statusLabel === 'Chưa học' ? 'Chưa học' : statusLabel}
                </span>
              </div>
            </button>
          );
        })}
      </div>
    </div>
  );

  const renderMapScreen = () => {
    const selectedStatusMeta = getLessonStatusMeta(selectedLesson?.status);
    const mapResources = currentLessonResources.slice(0, 2).map((resource, index) => ({
      label: resource.preview,
      source: resource.source,
      display: resource.title || `Học liệu gợi ý ${index + 1}`,
    }));
    const canOpenSelectedLesson = selectedLesson?.status !== 'not_started';
    const filterOptions: Array<{ value: MapStatusFilter; label: string }> = [
      { value: 'all', label: 'Tất cả' },
      { value: 'in_progress', label: 'Đang học' },
      { value: 'complete', label: 'Hoàn thành' },
      { value: 'not_started', label: 'Chưa mở' },
    ];
    const layoutOptions: Array<{ value: MapLayoutMode; label: string }> = [
      { value: 'chapter', label: 'Theo chương' },
      { value: 'journey', label: 'Theo hành trình' },
    ];
    const detailPanel = (
      <div className="soft-panel overflow-hidden">
        <div className="border-b border-black/5 px-6 py-6">
          {selectedLesson && (
            <p className="mb-4 text-[12px] font-medium uppercase tracking-[0.16em] text-[#8c3451]/55">
              {subjectLabel} / Chương {selectedLesson.chapter_index} / Bài{' '}
              {selectedLesson.lesson_index}
            </p>
          )}
          <div className="mb-4 flex items-center justify-between gap-4">
            <span className="rounded-full bg-white/80 px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]/75">
              {selectedLesson ? `Chương ${selectedLesson.chapter_index}` : 'Bài học'}
            </span>
            <span
              className={`rounded-full px-3 py-1 text-[11px] font-semibold ${selectedStatusMeta.pillClass}`}
            >
              {selectedStatusMeta.label}
            </span>
          </div>

          <h3 className="text-[28px] font-semibold leading-[1.15] tracking-[-0.04em] text-[#141217]">
            {selectedLesson
              ? `Bài ${selectedLesson.chapter_index}.${selectedLesson.lesson_index}: ${cleanLessonTitle(selectedLesson.title)}`
              : 'Chọn một bài học để xem chi tiết'}
          </h3>
          <p className="mt-4 text-[14px] leading-7 text-[#615954]">
            {selectedLesson?.summary?.trim() ||
              'Bản đồ học tập giúp bạn theo dõi trình tự bài học, tiến độ hiện tại và các bước nên học tiếp theo.'}
          </p>
        </div>

        <div className="grid grid-cols-2 gap-3 border-b border-black/5 px-6 py-5">
          <div className="metric-card p-4">
            <p className="text-[12px] uppercase tracking-[0.14em] text-[#8c3451]/55">Tiến độ</p>
            <p className="mt-2 text-[18px] font-semibold text-[#141217]">
              {selectedStatusMeta.label}
            </p>
          </div>
          <div className="metric-card p-4">
            <p className="text-[12px] uppercase tracking-[0.14em] text-[#8c3451]/55">Cấp độ</p>
            <p className="mt-2 text-[18px] font-semibold capitalize text-[#141217]">
              {path?.level || 'beginner'}
            </p>
          </div>
        </div>

        {selectedLesson && currentChapterProgress && (
          <div className="border-b border-black/5 px-6 py-5">
            <p className="mb-3 text-[12px] font-semibold uppercase tracking-[0.18em] text-[#8c3451]/55">
              Tiến độ chương hiện tại
            </p>
            <div className="white-panel p-4">
              <div className="mb-2 flex items-center justify-between text-[13px] text-[#5f5752]">
                <span>{cleanChapterTitle(currentChapterProgress.title)}</span>
                <span className="font-semibold text-[#141217]">
                  {currentChapterCompleted}/{currentChapterLessons.length}
                </span>
              </div>
              <div className="h-2 rounded-full bg-[#f4e7ed]">
                <div
                  className="h-2 rounded-full bg-[#8c3451]"
                  style={{
                    width: `${
                      currentChapterLessons.length > 0
                        ? (currentChapterCompleted / currentChapterLessons.length) * 100
                        : 0
                    }%`,
                  }}
                />
              </div>
            </div>
          </div>
        )}

        <div className="px-6 py-6">
          <p className="mb-4 text-[13px] font-semibold uppercase tracking-[0.18em] text-[#8c3451]/55">
            Học liệu gợi ý
          </p>
          <div className="space-y-3">
            {mapResources.map((resource, index) => (
              <div
                key={`${resource.label}-${index}`}
                className="white-panel flex items-center justify-between gap-3 px-4 py-4"
              >
                <div className="min-w-0">
                  <p className="text-[14px] font-semibold text-[#141217]">{resource.display}</p>
                  <p className="mt-1 truncate text-[12px] text-[#6f6762]">{resource.source}</p>
                </div>
                <span className="rounded-full bg-[#f9eef3] px-3 py-1 text-[11px] font-semibold text-[#8c3451]">
                  {index + 1}
                </span>
              </div>
            ))}
          </div>

          <div className="mt-5 flex flex-col gap-3">
            <div className="grid grid-cols-2 gap-3">
              <button
                onClick={() => {
                  if (!previousLesson) return;
                  setMapStatusFilter('all');
                  setMapFocusedChapterId(null);
                  setSelectedLesson(previousLesson);
                }}
                disabled={!previousLesson}
                className="theme-button-secondary justify-center disabled:cursor-not-allowed disabled:opacity-50"
              >
                ← Bài trước
              </button>
              <button
                onClick={() => {
                  if (!nextLesson) return;
                  setMapStatusFilter('all');
                  setMapFocusedChapterId(null);
                  setSelectedLesson(nextLesson);
                }}
                disabled={!nextLesson}
                className="theme-button-secondary justify-center disabled:cursor-not-allowed disabled:opacity-50"
              >
                Bài tiếp →
              </button>
            </div>
            <button
              onClick={() =>
                selectedLesson && canOpenSelectedLesson && openLessonScreen(selectedLesson)
              }
              disabled={!selectedLesson || !canOpenSelectedLesson}
              className="theme-button w-full justify-center disabled:cursor-not-allowed disabled:opacity-50"
            >
              {canOpenSelectedLesson ? 'Mở bài học' : 'Hoàn thành bài trước để mở'}
            </button>
            <button
              onClick={() =>
                selectedLesson &&
                selectedLesson.status !== 'in_progress' &&
                handleLessonStatusUpdate(selectedLesson.lesson_id, 'in_progress')
              }
              disabled={
                !selectedLesson ||
                selectedLesson.status === 'in_progress' ||
                updatingLessonId === selectedLesson?.lesson_id
              }
              className="theme-button-secondary w-full justify-center disabled:cursor-not-allowed disabled:opacity-50"
            >
              Đánh dấu đang học
            </button>
          </div>
        </div>
      </div>
    );

    return (
      <>
        <div
          className={
            mapPresentationMode ? 'space-y-0' : 'grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]'
          }
        >
          <section className="white-panel overflow-visible p-0">
            <div className="space-y-4 border-b border-black/5 px-5 py-5 md:px-6">
              <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex flex-wrap items-center gap-3">
                  <button
                    onClick={() => setScreenMode('subject')}
                    className="theme-button-secondary px-5 py-3 text-[14px]"
                  >
                    ← Quay lại
                  </button>
                  <div className="rounded-full border border-[#f0d7e0] bg-[#fff9fb] px-4 py-3 text-[13px] font-medium text-[#6e6460]">
                    {chapters.length} chương • {mapLessons.length} bài học
                  </div>
                </div>
              </div>

              <div className="flex flex-wrap items-center gap-2">
                <div className="flex min-w-[240px] max-w-[360px] flex-1 items-center gap-2 rounded-full border border-[#f0d7e0] bg-white px-3 py-2 shadow-[0_10px_20px_rgba(114,62,83,0.06)]">
                  <span className="flex h-9 w-9 items-center justify-center rounded-full bg-[#f9eef3] text-[#8c3451]">
                    ⌕
                  </span>
                  <input
                    ref={mapSearchInputRef}
                    value={mapSearchTerm}
                    onChange={(event) => setMapSearchTerm(event.target.value)}
                    onKeyDown={(event) => {
                      if (event.key === 'Enter') {
                        event.preventDefault();
                        handleMapSearch();
                      }
                    }}
                    placeholder="Tìm bài học trên bản đồ"
                    className="w-full border-none bg-transparent text-[13px] text-[#141217] outline-none placeholder:text-[#8f8782]"
                  />
                  <button
                    onClick={handleMapSearch}
                    disabled={searchedLessons.length === 0}
                    className="rounded-full bg-[#8c3451] px-4 py-2 text-[12px] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    Tìm
                  </button>
                </div>

                <div className="hidden flex-wrap items-center gap-2 rounded-full border border-[#f0d7e0] bg-[#fff9fb] p-1 md:flex">
                  {filterOptions.map((option) => (
                    <button
                      key={option.value}
                      onClick={() => setMapStatusFilter(option.value)}
                      className={`rounded-full px-4 py-2 text-[13px] font-medium transition ${
                        mapStatusFilter === option.value
                          ? 'bg-[#8c3451] text-white shadow-[0_12px_22px_rgba(140,52,81,0.18)]'
                          : 'text-[#5c5550]'
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>

                <div className="hidden flex-wrap items-center gap-2 rounded-full border border-[#f0d7e0] bg-[#fff9fb] p-1 md:flex">
                  {layoutOptions.map((option) => (
                    <button
                      key={option.value}
                      onClick={() => setMapLayoutMode(option.value)}
                      className={`rounded-full px-4 py-2 text-[13px] font-medium transition ${
                        mapLayoutMode === option.value
                          ? 'bg-[#f9eef3] text-[#8c3451] ring-1 ring-[#efd2dd]'
                          : 'text-[#5c5550]'
                      }`}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>

                <button
                  onClick={handleFitAllMapNodes}
                  disabled={!mapInstance || mapLessons.length === 0}
                  className="rounded-full border border-[#f0d7e0] bg-white px-4 py-2 text-[13px] font-medium text-[#5c5550] transition hover:shadow-[0_10px_18px_rgba(137,78,99,0.08)] disabled:cursor-not-allowed disabled:opacity-40"
                >
                  Fit toàn bộ
                </button>

                <button
                  onClick={() => setIsMapControlsDrawerOpen(true)}
                  className="rounded-full border border-[#f0d7e0] bg-white px-4 py-2 text-[13px] font-medium text-[#5c5550] transition hover:shadow-[0_10px_18px_rgba(137,78,99,0.08)] md:hidden"
                >
                  Bộ lọc
                </button>

                {!mapPresentationMode && (
                  <button
                    onClick={() => setIsMapDetailDrawerOpen(true)}
                    className="rounded-full border border-[#f0d7e0] bg-white px-4 py-2 text-[13px] font-medium text-[#5c5550] transition hover:shadow-[0_10px_18px_rgba(137,78,99,0.08)] xl:hidden"
                  >
                    Chi tiết bài học
                  </button>
                )}

                <div ref={desktopOptionsRef} className="relative hidden md:block">
                  <button
                    type="button"
                    onClick={() => setIsDesktopOptionsOpen((value) => !value)}
                    className={`rounded-full border px-4 py-2 text-[13px] font-medium transition ${
                      isDesktopOptionsOpen
                        ? 'border-[#e7c6d2] bg-[#f9eef3] text-[#8c3451] shadow-[0_10px_18px_rgba(137,78,99,0.08)]'
                        : 'border-[#f0d7e0] bg-white text-[#5c5550] hover:shadow-[0_10px_18px_rgba(137,78,99,0.08)]'
                    }`}
                    aria-expanded={isDesktopOptionsOpen}
                    aria-haspopup="menu"
                  >
                    Tùy chọn
                  </button>
                  {isDesktopOptionsOpen && (
                    <div
                      role="menu"
                      className="absolute left-0 top-[calc(100%+10px)] z-30 w-[304px] rounded-[24px] border border-[#f0d7e0] bg-white p-3 shadow-[0_18px_36px_rgba(114,62,83,0.14)]"
                    >
                      <div className="mb-3 rounded-[18px] bg-[#fff8fb] px-4 py-3">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8c3451]/55">
                          Tùy chọn bản đồ
                        </p>
                        <p className="mt-1 text-[13px] leading-6 text-[#6b645e]">
                          Chọn nhanh cách xem phù hợp rồi quay lại sơ đồ.
                        </p>
                      </div>

                      <div className="space-y-3">
                        <div>
                          <p className="mb-2 px-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8c3451]/55">
                            Khung nhìn
                          </p>
                          <div className="grid gap-2">
                            <button
                              onClick={() => {
                                handleFitCurrentChapter();
                                setIsDesktopOptionsOpen(false);
                              }}
                              disabled={!mapInstance || !selectedLesson}
                              className="rounded-[18px] border border-[#f0d7e0] bg-white px-4 py-3 text-left text-[13px] font-medium text-[#5c5550] transition hover:bg-[#fcf6f9] disabled:cursor-not-allowed disabled:opacity-40"
                            >
                              Fit chương hiện tại
                            </button>
                            <button
                              onClick={() => {
                                void handleToggleMapFullscreen();
                                setIsDesktopOptionsOpen(false);
                              }}
                              className="rounded-[18px] border border-[#f0d7e0] bg-white px-4 py-3 text-left text-[13px] font-medium text-[#5c5550] transition hover:bg-[#fcf6f9]"
                            >
                              {isMapFullscreen ? 'Thoát toàn màn hình' : 'Toàn màn hình'}
                            </button>
                          </div>
                        </div>

                        <div>
                          <p className="mb-2 px-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8c3451]/55">
                            Chương học
                          </p>
                          <div className="grid gap-2">
                            <button
                              onClick={() => {
                                handleExpandAllChapters();
                                setIsDesktopOptionsOpen(false);
                              }}
                              disabled={collapsedChapterIds.length === 0}
                              className="rounded-[18px] border border-[#f0d7e0] bg-white px-4 py-3 text-left text-[13px] font-medium text-[#5c5550] transition hover:bg-[#fcf6f9] disabled:cursor-not-allowed disabled:opacity-40"
                            >
                              Mở tất cả chương
                            </button>
                            <button
                              onClick={() => {
                                handleCollapseOtherChapters();
                                setIsDesktopOptionsOpen(false);
                              }}
                              disabled={!selectedLesson || chapters.length <= 1}
                              className="rounded-[18px] border border-[#f0d7e0] bg-white px-4 py-3 text-left text-[13px] font-medium text-[#5c5550] transition hover:bg-[#fcf6f9] disabled:cursor-not-allowed disabled:opacity-40"
                            >
                              Thu chương khác
                            </button>
                            <button
                              onClick={() => {
                                handleToggleFocusedChapter();
                                setIsDesktopOptionsOpen(false);
                              }}
                              disabled={!selectedLesson}
                              className="rounded-[18px] border border-[#f0d7e0] bg-white px-4 py-3 text-left text-[13px] font-medium text-[#5c5550] transition hover:bg-[#fcf6f9] disabled:cursor-not-allowed disabled:opacity-40"
                            >
                              {mapFocusedChapterId === selectedLesson?.chapter_id
                                ? 'Hiện tất cả chương'
                                : 'Chỉ xem chương hiện tại'}
                            </button>
                          </div>
                        </div>

                        <div>
                          <p className="mb-2 px-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8c3451]/55">
                            Chế độ hiển thị
                          </p>
                          <div className="grid gap-2">
                            <button
                              onClick={() => {
                                setMapPresentationMode((value) => !value);
                                setIsDesktopOptionsOpen(false);
                              }}
                              className="rounded-[18px] border border-[#f0d7e0] bg-white px-4 py-3 text-left text-[13px] font-medium text-[#5c5550] transition hover:bg-[#fcf6f9]"
                            >
                              {mapPresentationMode
                                ? 'Thoát presentation mode'
                                : 'Presentation mode'}
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              </div>
            </div>

            <div className="border-b border-black/5 px-5 py-4 md:px-6">
              <div className="flex items-center gap-3 overflow-x-auto pb-1 md:hidden">
                <select
                  value={mapFocusedChapterId || 'all'}
                  onChange={(event) => {
                    const value = event.target.value;
                    if (value === 'all') {
                      setMapFocusedChapterId(null);
                      setCollapsedChapterIds([]);
                      return;
                    }
                    handleFocusChapter(value);
                  }}
                  className="min-w-[190px] rounded-full border border-[#f0d7e0] bg-white px-4 py-3 text-[13px] font-medium text-[#5c5550] outline-none"
                >
                  <option value="all">Tất cả chương</option>
                  {chapters.map((chapter, index) => {
                    const chapterLessonsCount = lessons.filter(
                      (lesson) => lesson.chapter_id === chapter.chapter_id,
                    ).length;
                    return (
                      <option
                        key={chapter.chapter_id || `${chapter.title}-${index}`}
                        value={chapter.chapter_id}
                      >
                        {`Chương ${index + 1} (${chapterLessonsCount} bài)`}
                      </option>
                    );
                  })}
                </select>

                {mapSearchTerm.trim() && (
                  <span className="shrink-0 rounded-full bg-[#f9eef3] px-4 py-2 text-[12px] font-medium text-[#8c3451]">
                    {searchedLessons.length > 0
                      ? `${searchedLessons.length} bài khớp`
                      : 'Không có kết quả'}
                  </span>
                )}
              </div>

              <div className="hidden items-center gap-3 overflow-x-auto pb-1 md:flex">
                <button
                  onClick={() => {
                    setMapFocusedChapterId(null);
                    setCollapsedChapterIds([]);
                  }}
                  className={`shrink-0 rounded-full px-4 py-2 text-[12px] font-semibold transition ${
                    !mapFocusedChapterId && collapsedChapterIds.length === 0
                      ? 'bg-[#8c3451] text-white shadow-[0_12px_22px_rgba(140,52,81,0.18)]'
                      : 'border border-[#f0d7e0] bg-white text-[#5c5550]'
                  }`}
                >
                  Tất cả chương
                </button>

                {chapters.map((chapter, index) => {
                  const accent = getChapterAccent(index + 1);
                  const chapterLessonsCount = lessons.filter(
                    (lesson) => lesson.chapter_id === chapter.chapter_id,
                  ).length;
                  const isActiveChapter = selectedLesson?.chapter_id === chapter.chapter_id;

                  return (
                    <button
                      key={chapter.chapter_id || `${chapter.title}-${index}`}
                      onClick={() => handleFocusChapter(chapter.chapter_id)}
                      className="shrink-0 rounded-full border px-4 py-2 text-[12px] font-semibold transition"
                      style={{
                        borderColor: isActiveChapter ? accent.solid : accent.border,
                        background: isActiveChapter ? accent.soft : 'rgba(255,255,255,0.92)',
                        color: isActiveChapter ? accent.text : '#5c5550',
                      }}
                    >
                      Chương {index + 1}
                      {isActiveChapter ? (
                        <span className="ml-2 opacity-70">• {chapterLessonsCount} bài</span>
                      ) : null}
                    </button>
                  );
                })}

                {mapSearchTerm.trim() && (
                  <span className="shrink-0 rounded-full bg-[#f9eef3] px-4 py-2 text-[12px] font-medium text-[#8c3451]">
                    {searchedLessons.length > 0
                      ? `${searchedLessons.length} bài khớp`
                      : 'Không có kết quả'}
                  </span>
                )}

                {collapsedChapterIds.length > 0 && (
                  <span className="shrink-0 rounded-full border border-[#f0d7e0] bg-white px-4 py-2 text-[12px] font-medium text-[#6b645e]">
                    Đang ẩn {collapsedChapterIds.length} chương
                  </span>
                )}
              </div>
            </div>

            <div
              ref={mapCanvasRef}
              className={`learning-flow-canvas relative overflow-hidden bg-[radial-gradient(circle_at_1px_1px,rgba(140,52,81,0.08)_1px,transparent_0)] [background-size:22px_22px] ${
                isMapFullscreen ? 'h-screen rounded-none bg-[#fff8fb]' : 'h-[780px]'
              }`}
            >
              {previewLesson && (
                <div className="pointer-events-none absolute left-3 top-3 z-[5] max-w-[280px] md:left-5 md:top-5 md:max-w-[360px]">
                  <div className="white-panel px-4 py-3 shadow-[0_20px_36px_rgba(114,62,83,0.12)] md:px-5 md:py-4">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-[#8c3451]/55 md:text-[11px]">
                      {hoveredLesson ? 'Xem nhanh' : 'Bài đang chọn'}
                    </p>
                    <p className="mt-1 overflow-hidden text-ellipsis whitespace-nowrap text-[14px] font-semibold leading-[1.3] text-[#141217] md:mt-2 md:text-[18px]">
                      Bài {previewLesson.chapter_index}.{previewLesson.lesson_index}:{' '}
                      {cleanLessonTitle(previewLesson.title)}
                    </p>
                    <p className="mt-2 hidden max-h-[76px] overflow-hidden text-[13px] leading-6 text-[#625b56] md:block">
                      {previewLesson.summary?.trim() ||
                        'Bài học này giúp bạn tiếp tục tiến lên trong lộ trình hiện tại.'}
                    </p>
                  </div>
                </div>
              )}

              {mapPresentationMode && (
                <div className="absolute right-5 top-5 z-[5] hidden w-[360px] xl:block">
                  {detailPanel}
                </div>
              )}

              {mapLessons.length === 0 ? (
                <div className="flex h-full items-center justify-center p-8">
                  <div className="white-panel max-w-[420px] p-8 text-center">
                    <p className="text-[18px] font-semibold text-[#141217]">
                      Không có bài học nào khớp bộ lọc hiện tại
                    </p>
                    <p className="mt-3 text-[14px] leading-7 text-[#615954]">
                      Hãy thử đổi trạng thái, mở lại chương đang thu gọn hoặc xóa từ khóa tìm kiếm
                      để xem nhiều bài học hơn.
                    </p>
                  </div>
                </div>
              ) : (
                <ReactFlow
                  nodes={mapNodes}
                  edges={mapEdges}
                  nodeTypes={mapNodeTypes}
                  onInit={setMapInstance}
                  onMoveEnd={handlePersistViewport}
                  fitView
                  fitViewOptions={{ padding: 0.18 }}
                  minZoom={0.55}
                  maxZoom={1.5}
                  defaultViewport={{ x: 0, y: 0, zoom: 0.82 }}
                  nodesDraggable={false}
                  nodesConnectable={false}
                  elementsSelectable={false}
                  panOnDrag
                  zoomOnScroll
                  zoomOnPinch
                  proOptions={{ hideAttribution: true }}
                >
                  <Background gap={22} size={1.4} color="rgba(140,52,81,0.12)" />
                  <MiniMap
                    pannable
                    zoomable
                    position="bottom-right"
                    className="!mb-5 !mr-5 !overflow-hidden !rounded-[20px] !border !border-[#ead7df] !bg-white/95 !shadow-[0_18px_32px_rgba(114,62,83,0.12)]"
                    nodeColor={(node) => {
                      if (String(node.id).startsWith('chapter-')) {
                        const chapterNode = node.data as MapChapterNodeData | undefined;
                        return chapterNode?.accent?.soft || '#f6dce6';
                      }

                      const lessonNode = node.data as MapLessonNodeData | undefined;
                      if (lessonNode?.lesson?.status === 'complete') return '#10b981';
                      if (lessonNode?.lesson?.status === 'in_progress')
                        return lessonNode?.accent?.solid || '#8c3451';
                      return '#cbd5e1';
                    }}
                  />
                  <Controls
                    position="top-right"
                    showInteractive={false}
                    className="!overflow-hidden !rounded-[20px] !border !border-[#ead7df] !bg-white/95 !shadow-[0_20px_36px_rgba(114,62,83,0.12)]"
                  />
                </ReactFlow>
              )}

              <div className="pointer-events-none absolute bottom-3 left-3 md:bottom-5 md:left-5">
                <div className="white-panel flex items-center gap-3 px-3 py-2 md:gap-4 md:px-4 md:py-3">
                  <div className="flex items-center gap-2 text-[11px] font-medium text-[#6f6762] md:text-[12px]">
                    <span className="h-3 w-3 rounded-full bg-[#8c3451]"></span>
                    <span className="hidden sm:inline">Đang học</span>
                  </div>
                  <div className="flex items-center gap-2 text-[11px] font-medium text-[#6f6762] md:text-[12px]">
                    <span className="h-3 w-3 rounded-full bg-emerald-500"></span>
                    <span className="hidden sm:inline">Hoàn thành</span>
                  </div>
                  <div className="flex items-center gap-2 text-[11px] font-medium text-[#6f6762] md:text-[12px]">
                    <span className="h-3 w-3 rounded-full bg-slate-300"></span>
                    <span className="hidden sm:inline">Chưa mở</span>
                  </div>
                </div>
              </div>
            </div>
          </section>

          {!mapPresentationMode && (
            <aside className="hidden space-y-5 xl:sticky xl:top-4 xl:block xl:self-start">
              {detailPanel}
            </aside>
          )}
        </div>

        {!mapPresentationMode && isMapDetailDrawerOpen && (
          <div className="fixed inset-0 z-40 bg-[#141217]/30 backdrop-blur-[2px] xl:hidden">
            <button
              aria-label="Đóng chi tiết bài học"
              className="absolute inset-0 h-full w-full cursor-default"
              onClick={() => setIsMapDetailDrawerOpen(false)}
            />
            <div className="absolute inset-x-0 bottom-0 max-h-[82vh] overflow-y-auto rounded-t-[28px] bg-[#fff8fb] p-4 shadow-[0_-18px_40px_rgba(20,18,23,0.14)]">
              <div className="mx-auto mb-4 h-1.5 w-14 rounded-full bg-[#e8d3dc]" />
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8c3451]/55">
                    Chi tiết bài học
                  </p>
                  <p className="mt-1 text-[14px] text-[#615954]">
                    Xem nhanh nội dung và thao tác tiếp theo
                  </p>
                </div>
                <button
                  onClick={() => setIsMapDetailDrawerOpen(false)}
                  className="rounded-full border border-[#f0d7e0] bg-white px-4 py-2 text-[13px] font-medium text-[#5c5550]"
                >
                  Đóng
                </button>
              </div>
              {detailPanel}
            </div>
          </div>
        )}

        {!mapPresentationMode && isMapControlsDrawerOpen && (
          <div className="fixed inset-0 z-40 bg-[#141217]/30 backdrop-blur-[2px] md:hidden">
            <button
              aria-label="Đóng bộ lọc bản đồ"
              className="absolute inset-0 h-full w-full cursor-default"
              onClick={() => setIsMapControlsDrawerOpen(false)}
            />
            <div className="absolute inset-x-0 bottom-0 max-h-[82vh] overflow-y-auto rounded-t-[28px] bg-[#fff8fb] p-4 shadow-[0_-18px_40px_rgba(20,18,23,0.14)]">
              <div className="mx-auto mb-4 h-1.5 w-14 rounded-full bg-[#e8d3dc]" />
              <div className="mb-4 flex items-center justify-between gap-3">
                <div>
                  <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-[#8c3451]/55">
                    Bộ lọc bản đồ
                  </p>
                  <p className="mt-1 text-[14px] text-[#615954]">
                    Chọn cách xem phù hợp rồi quay lại sơ đồ
                  </p>
                </div>
                <button
                  onClick={() => setIsMapControlsDrawerOpen(false)}
                  className="rounded-full border border-[#f0d7e0] bg-white px-4 py-2 text-[13px] font-medium text-[#5c5550]"
                >
                  Đóng
                </button>
              </div>

              <div className="space-y-5">
                <div>
                  <p className="mb-3 text-[12px] font-semibold uppercase tracking-[0.18em] text-[#8c3451]/55">
                    Trạng thái
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {filterOptions.map((option) => (
                      <button
                        key={option.value}
                        onClick={() => {
                          setMapStatusFilter(option.value);
                          setIsMapControlsDrawerOpen(false);
                        }}
                        className={`rounded-full px-4 py-2 text-[13px] font-medium transition ${
                          mapStatusFilter === option.value
                            ? 'bg-[#8c3451] text-white shadow-[0_12px_22px_rgba(140,52,81,0.18)]'
                            : 'border border-[#f0d7e0] bg-white text-[#5c5550]'
                        }`}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <p className="mb-3 text-[12px] font-semibold uppercase tracking-[0.18em] text-[#8c3451]/55">
                    Bố cục
                  </p>
                  <div className="flex flex-wrap gap-2">
                    {layoutOptions.map((option) => (
                      <button
                        key={option.value}
                        onClick={() => {
                          setMapLayoutMode(option.value);
                          setIsMapControlsDrawerOpen(false);
                        }}
                        className={`rounded-full px-4 py-2 text-[13px] font-medium transition ${
                          mapLayoutMode === option.value
                            ? 'bg-[#f9eef3] text-[#8c3451] ring-1 ring-[#efd2dd]'
                            : 'border border-[#f0d7e0] bg-white text-[#5c5550]'
                        }`}
                      >
                        {option.label}
                      </button>
                    ))}
                  </div>
                </div>

                <div>
                  <p className="mb-3 text-[12px] font-semibold uppercase tracking-[0.18em] text-[#8c3451]/55">
                    Tùy chọn nhanh
                  </p>
                  <div className="grid gap-2">
                    <button
                      onClick={() => {
                        handleFitCurrentChapter();
                        setIsMapControlsDrawerOpen(false);
                      }}
                      disabled={!mapInstance || !selectedLesson}
                      className="rounded-[18px] border border-[#f0d7e0] bg-white px-4 py-3 text-left text-[13px] font-medium text-[#5c5550] disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      Fit chương hiện tại
                    </button>
                    <button
                      onClick={() => {
                        handleExpandAllChapters();
                        setIsMapControlsDrawerOpen(false);
                      }}
                      disabled={collapsedChapterIds.length === 0}
                      className="rounded-[18px] border border-[#f0d7e0] bg-white px-4 py-3 text-left text-[13px] font-medium text-[#5c5550] disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      Mở tất cả chương
                    </button>
                    <button
                      onClick={() => {
                        handleCollapseOtherChapters();
                        setIsMapControlsDrawerOpen(false);
                      }}
                      disabled={!selectedLesson || chapters.length <= 1}
                      className="rounded-[18px] border border-[#f0d7e0] bg-white px-4 py-3 text-left text-[13px] font-medium text-[#5c5550] disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      Thu chương khác
                    </button>
                    <button
                      onClick={() => {
                        handleToggleFocusedChapter();
                        setIsMapControlsDrawerOpen(false);
                      }}
                      disabled={!selectedLesson}
                      className="rounded-[18px] border border-[#f0d7e0] bg-white px-4 py-3 text-left text-[13px] font-medium text-[#5c5550] disabled:cursor-not-allowed disabled:opacity-40"
                    >
                      {mapFocusedChapterId === selectedLesson?.chapter_id
                        ? 'Hiện tất cả chương'
                        : 'Chỉ xem chương hiện tại'}
                    </button>
                    <button
                      onClick={() => {
                        void handleToggleMapFullscreen();
                        setIsMapControlsDrawerOpen(false);
                      }}
                      className="rounded-[18px] border border-[#f0d7e0] bg-white px-4 py-3 text-left text-[13px] font-medium text-[#5c5550]"
                    >
                      {isMapFullscreen ? 'Thoát toàn màn hình' : 'Toàn màn hình'}
                    </button>
                    <button
                      onClick={() => {
                        setMapPresentationMode((value) => !value);
                        setIsMapControlsDrawerOpen(false);
                      }}
                      className="rounded-[18px] border border-[#f0d7e0] bg-white px-4 py-3 text-left text-[13px] font-medium text-[#5c5550]"
                    >
                      {mapPresentationMode ? 'Thoát presentation mode' : 'Presentation mode'}
                    </button>
                  </div>
                </div>
              </div>
            </div>
          </div>
        )}
      </>
    );
  };

  const renderLessonResources = () => (
    <div className="white-panel min-h-[667px] overflow-hidden px-6 pb-8 pt-0 md:px-8">
      <div className="mb-0 flex flex-wrap translate-y-[-1px] gap-3 pt-6">
        <button
          onClick={() => setLessonTab('lesson')}
          className={`h-[56px] w-full rounded-full border text-[16px] font-medium transition-colors sm:h-[64px] sm:w-[220px] sm:text-[17px] ${
            lessonTab === 'lesson' ? 'bg-[#8c3451] text-white' : 'bg-white text-[#141217]'
          }`}
          style={{ borderColor: 'rgba(17,16,21,0.08)' }}
        >
          Bài học
        </button>
        <button
          onClick={() => void handleOpenQuestionsTab()}
          className={`h-[56px] w-full rounded-full border text-[16px] font-medium transition-colors sm:h-[64px] sm:w-[220px] sm:text-[17px] ${
            lessonTab === 'questions' ? 'bg-[#8c3451] text-white' : 'bg-white text-[#141217]'
          }`}
          style={{ borderColor: 'rgba(17,16,21,0.08)' }}
        >
          Câu hỏi ôn tập
        </button>
      </div>

      <div className="soft-panel mt-6 px-6 pb-6 pt-6">
        <div className="flex flex-wrap items-center justify-between gap-3 border-b border-black/5 pb-4">
          <div>
            <p className="text-[12px] font-semibold uppercase tracking-[0.22em] text-[#8c3451]/60">
              Học liệu gợi ý
            </p>
            <p className="mt-2 text-[14px] leading-6 text-[#6a625d]">
              Hệ thống đang ưu tiên đúng tài liệu và đúng trang liên quan nhất với lesson hiện tại
              để bạn đọc tiếp nhanh hơn.
            </p>
          </div>
          {lessonRecommendedChunks?.metadata?.selected_count ? (
            <div className="flex flex-wrap items-center gap-3">
              <span className="rounded-full bg-white px-4 py-2 text-[12px] font-medium text-[#8c3451] shadow-[0_10px_20px_rgba(114,62,83,0.08)]">
                {String(lessonRecommendedChunks.metadata.selected_count)} chunk đã chọn
              </span>
              {lessonSequenceMeta.roles_present ? (
                <span className="rounded-full bg-white px-4 py-2 text-[12px] font-medium text-[#6f5260] shadow-[0_10px_20px_rgba(114,62,83,0.08)]">
                  Sequence: {String((lessonSequenceMeta.roles_present as string[]).join(' → '))}
                </span>
              ) : null}
              {currentLessonResources.some((resource) => buildLessonResourceOpenUrl(resource)) ? (
                <button
                  type="button"
                  onClick={handleOpenAllLessonResources}
                  className="theme-button-secondary px-4 py-2 text-[12px]"
                >
                  Mở tất cả học liệu
                </button>
              ) : null}
            </div>
          ) : null}
        </div>

        {adaptiveNextAction ? (
          <div className="mt-6 rounded-[24px] border border-[#efd7e0] bg-[linear-gradient(135deg,#fffafd_0%,#fdf2f6_100%)] p-5 shadow-[0_16px_36px_rgba(114,62,83,0.08)]">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full bg-white px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]">
                    Adaptive suggestion
                  </span>
                  {adaptiveNextAction.target_concepts.slice(0, 2).map((concept) => (
                    <span
                      key={`lesson-adaptive-${concept}`}
                      className="rounded-full bg-[#f7dfe8] px-3 py-1 text-[11px] font-semibold text-[#8c3451]"
                    >
                      {concept}
                    </span>
                  ))}
                  {adaptiveNextAction.estimated_total_time ? (
                    <span className="rounded-full bg-white px-3 py-1 text-[11px] font-semibold text-[#6f5260]">
                      {adaptiveNextAction.estimated_total_time} phút
                    </span>
                  ) : null}
                </div>
                <h3 className="mt-3 text-[20px] font-semibold tracking-[-0.03em] text-[#141217]">
                  {getAdaptiveActionLabel(adaptiveNextAction.next_best_action)}
                </h3>
                <p className="mt-2 max-w-3xl text-[14px] leading-6 text-[#6a625d]">
                  {adaptiveNextAction.reason}
                </p>
              </div>
              <div className="flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={handleOpenAdaptiveLessonSuggestion}
                  className="theme-button px-5 py-3 text-[13px]"
                >
                  Mở gợi ý này
                </button>
                <button
                  type="button"
                  onClick={() => setLessonTab('questions')}
                  className="theme-button-secondary px-5 py-3 text-[13px]"
                >
                  Sang phần quiz
                </button>
              </div>
            </div>
          </div>
        ) : null}

        {resolvedPinnedLessonResource ? (
          <div className="mt-6 rounded-[24px] border border-[#efd7e0] bg-[linear-gradient(135deg,#fffafd_0%,#fdf2f6_100%)] p-5 shadow-[0_16px_36px_rgba(114,62,83,0.08)]">
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="rounded-full bg-white px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]">
                    Đọc tiếp nhanh
                  </span>
                  <span className="rounded-full bg-[#f7dfe8] px-3 py-1 text-[11px] font-semibold text-[#8c3451]">
                    Đã ghim
                  </span>
                </div>
                <h3 className="mt-3 text-[20px] font-semibold tracking-[-0.03em] text-[#141217]">
                  {resolvedPinnedLessonResource.title}
                </h3>
                <p className="mt-2 text-[14px] leading-6 text-[#6a625d]">
                  {resolvedPinnedLessonResource.source}
                  {resolvedPinnedLessonResource.pageNumber
                    ? ` • Quay lại từ trang ${resolvedPinnedLessonResource.pageNumber}`
                    : ''}
                </p>
                <p className="mt-3 max-w-3xl text-[13px] leading-6 text-[#6a625d]">
                  Tài liệu này được giữ lại theo lesson hiện tại để bạn quay lại đúng chỗ đang đọc
                  sau mỗi lần rời trang.
                </p>
              </div>
              <div className="flex flex-wrap gap-3">
                <button
                  type="button"
                  onClick={() => handleOpenLessonResource(resolvedPinnedLessonResource)}
                  className="theme-button px-5 py-3 text-[13px]"
                >
                  Mở lại tài liệu
                </button>
                <button
                  type="button"
                  onClick={() => persistPinnedLessonResource(null)}
                  className="theme-button-secondary px-5 py-3 text-[13px]"
                >
                  Bỏ ghim
                </button>
              </div>
            </div>
          </div>
        ) : resolvedCurrentReadingResource ? (
          <div className="mt-6 rounded-[22px] border border-[#efdfeb] bg-white px-5 py-4 shadow-[0_14px_30px_rgba(114,62,83,0.06)]">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="text-[12px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]/60">
                  Bạn đang đọc
                </p>
                <p className="mt-2 text-[15px] font-medium text-[#141217]">
                  {resolvedCurrentReadingResource.title}
                  {resolvedCurrentReadingResource.pageNumber
                    ? ` • Trang ${resolvedCurrentReadingResource.pageNumber}`
                    : ''}
                </p>
              </div>
              <button
                type="button"
                onClick={() => handleTogglePinnedLessonResource(resolvedCurrentReadingResource)}
                className="theme-button-secondary px-5 py-3 text-[13px]"
              >
                Ghim để quay lại nhanh
              </button>
            </div>
          </div>
        ) : null}

        {lessonResourcesLoading ? (
          <div className="mt-6 grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {Array.from(
              {
                length: Math.min(
                  8,
                  Math.max(4, Number(lessonRecommendedChunks?.metadata?.selected_count ?? 4)),
                ),
              },
              (_, index) => (
                <div
                  key={`resource-skeleton-${index}`}
                  className="min-h-[360px] animate-pulse rounded-[30px] border bg-white/90 px-5 pb-5 pt-5 shadow-[0_18px_34px_rgba(114,62,83,0.06)]"
                  style={{ borderColor: 'rgba(17,16,21,0.08)' }}
                >
                  <div className="flex items-center justify-between gap-3">
                    <div className="h-8 w-16 rounded-full bg-[#f3dbe5]" />
                    <div className="h-8 w-20 rounded-full bg-[#f7e8ee]" />
                  </div>
                  <div className="mt-5 h-7 w-3/4 rounded-full bg-[#f7e8ee]" />
                  <div className="mt-3 h-5 w-1/2 rounded-full bg-[#f7e8ee]" />
                  <div className="mt-6 h-[170px] rounded-[22px] bg-[#fbf4f7]" />
                  <div className="mt-4 h-4 w-full rounded-full bg-[#f7e8ee]" />
                  <div className="mt-2 h-4 w-5/6 rounded-full bg-[#f7e8ee]" />
                  <div className="mt-5 h-11 w-full rounded-full bg-[#f3dbe5]" />
                </div>
              ),
            )}
          </div>
        ) : (
          <div className="mt-6 grid grid-cols-1 gap-6 md:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
            {currentLessonResources.map((resource) => {
              const theme = getLessonResourceTheme(resource.source);
              const canOpenResource = Boolean(
                (resource.source === 'PDF' && resource.resourceId) || resource.resourceUrl,
              );
              const isPinned = resolvedPinnedLessonResource?.key === resource.key;
              const isCurrentReading = resolvedCurrentReadingResource?.key === resource.key;

              return (
                <div
                  key={resource.key}
                  className={`flex min-h-[360px] flex-col rounded-[30px] border px-5 pb-5 pt-5 shadow-[0_18px_34px_rgba(114,62,83,0.06)] transition-transform duration-200 hover:-translate-y-1 hover:shadow-[0_24px_44px_rgba(114,62,83,0.1)] ${theme.frame}`}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0 flex-1">
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className={`inline-flex rounded-full px-3 py-1 text-[11px] font-semibold ${theme.chip}`}
                        >
                          {resource.source}
                        </span>
                        {resource.instructionRole ? (
                          <span className="inline-flex rounded-full bg-white px-3 py-1 text-[11px] font-semibold text-[#6f5260]">
                            {getInstructionRoleLabel(resource.instructionRole)}
                          </span>
                        ) : null}
                        {isPinned ? (
                          <span className="inline-flex rounded-full bg-white px-3 py-1 text-[11px] font-semibold text-[#8c3451]">
                            Đã ghim
                          </span>
                        ) : null}
                        {isCurrentReading ? (
                          <span className="inline-flex rounded-full bg-white px-3 py-1 text-[11px] font-semibold text-[#6f5260]">
                            Đang đọc
                          </span>
                        ) : null}
                      </div>
                      <h3
                        className="mt-3 text-[22px] font-semibold leading-[1.15] tracking-[-0.04em] text-[#141217]"
                        style={{
                          display: '-webkit-box',
                          WebkitLineClamp: 2,
                          WebkitBoxOrient: 'vertical',
                          overflow: 'hidden',
                        }}
                      >
                        {resource.title}
                      </h3>
                      <p className="mt-3 text-[12px] font-medium uppercase tracking-[0.16em] text-[#8c3451]/60">
                        Đoạn trích nên đọc tiếp
                      </p>
                    </div>
                    <div className="flex shrink-0 flex-col items-end gap-2">
                      <span className="rounded-full bg-[#f6d6e0] px-4 py-2 text-[11px] font-semibold text-[#7f3650]">
                        #{resource.sequencePosition || 0}
                      </span>
                      {resource.estimatedReadTime ? (
                        <span className="rounded-full bg-white px-4 py-2 text-[12px] font-semibold text-[#6f5260] shadow-[0_8px_18px_rgba(114,62,83,0.08)]">
                          {resource.estimatedReadTime} phút
                        </span>
                      ) : null}
                      {resource.pageNumber ? (
                        <span
                          className={`rounded-full bg-white px-4 py-2 text-[12px] font-semibold shadow-[0_8px_18px_rgba(114,62,83,0.08)] ${theme.accent}`}
                        >
                          Trang {resource.pageNumber}
                        </span>
                      ) : null}
                    </div>
                  </div>
                  <div
                    className={`mt-6 flex h-[178px] w-full overflow-hidden rounded-[24px] border border-white/70 px-5 py-5 text-[10px] text-black/70 ${theme.preview}`}
                    style={{ boxShadow: '0 12px 28px rgba(45,31,17,0.08)' }}
                  >
                    <div className="flex h-full w-full flex-col">
                      <span
                        className={`w-fit rounded-full bg-white/90 px-3 py-1 text-[10px] font-semibold tracking-[0.18em] ${theme.accent}`}
                      >
                        {theme.icon}
                      </span>
                      <p
                        className="mt-4 overflow-hidden text-left text-[13px] leading-7 text-black/65"
                        style={{
                          display: '-webkit-box',
                          WebkitLineClamp: 5,
                          WebkitBoxOrient: 'vertical',
                        }}
                      >
                        {renderHighlightedPreview(resource.preview)}
                      </p>
                    </div>
                  </div>
                  <p className="mt-4 text-[13px] leading-6 text-[#6a625d]">
                    {getLessonResourceHint(resource)}
                  </p>
                  {resource.coveredConcepts?.length ? (
                    <div className="mt-3 flex flex-wrap gap-2">
                      {resource.coveredConcepts.slice(0, 3).map((concept) => (
                        <span
                          key={`${resource.key}-${concept}`}
                          className="rounded-full bg-white px-3 py-1 text-[11px] font-medium text-[#8c3451]"
                        >
                          {concept}
                        </span>
                      ))}
                    </div>
                  ) : null}
                  <div className="mt-auto pt-5">
                    <button
                      type="button"
                      onClick={() => handleOpenLessonResource(resource)}
                      disabled={!canOpenResource}
                      className="theme-button w-full px-5 py-3 text-[13px] disabled:cursor-not-allowed disabled:opacity-50"
                    >
                      {resource.actionLabel || 'Mở tài liệu'}
                    </button>
                    <div className="mt-3 flex flex-wrap items-center gap-2">
                      <button
                        type="button"
                        onClick={() => handleTogglePinnedLessonResource(resource)}
                        disabled={!canOpenResource}
                        className="theme-button-secondary px-4 py-2.5 text-[12px] disabled:cursor-not-allowed disabled:opacity-50"
                      >
                        {isPinned ? 'Bỏ ghim' : 'Ghim nhanh'}
                      </button>
                      <button
                        type="button"
                        onClick={() => void handleMarkLessonResourceCompleted(resource)}
                        disabled={selectedLesson?.status !== 'complete'}
                        className="rounded-full border border-emerald-200 bg-white px-4 py-2.5 text-[12px] font-medium text-emerald-700 transition hover:bg-emerald-50 disabled:cursor-not-allowed disabled:bg-emerald-50 disabled:opacity-65"
                      >
                        Đã học xong
                      </button>
                      {resource.pageNumber ? (
                        <span
                          className={`inline-flex items-center rounded-full bg-white px-4 py-2.5 text-[12px] font-medium shadow-[0_8px_18px_rgba(114,62,83,0.08)] ${theme.accent}`}
                        >
                          Đọc từ trang {resource.pageNumber}
                        </span>
                      ) : null}
                      {typeof resource.questionabilityScore === 'number' &&
                      resource.questionabilityScore >= 0.65 ? (
                        <span className="inline-flex items-center rounded-full bg-[#fff1f6] px-4 py-2.5 text-[12px] font-medium text-[#8c3451]">
                          Good for quiz generation
                        </span>
                      ) : null}
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      <div className="mt-6 flex flex-wrap gap-3">
        {selectedLesson && selectedLesson.status !== 'in_progress' && (
          <button
            onClick={() => handleLessonStatusUpdate(selectedLesson.lesson_id, 'in_progress')}
            disabled={updatingLessonId === selectedLesson.lesson_id}
            className="theme-button-secondary px-5 py-3 text-[14px] disabled:opacity-50"
          >
            Bắt đầu học
          </button>
        )}
        {selectedLesson && selectedLesson.status !== 'complete' && (
          <button
            onClick={() => handleLessonStatusUpdate(selectedLesson.lesson_id, 'complete')}
            disabled={updatingLessonId === selectedLesson.lesson_id}
            className="theme-button px-5 py-3 text-[14px] disabled:opacity-50"
          >
            Đánh dấu hoàn thành
          </button>
        )}
        <button
          onClick={() => setScreenMode('map')}
          className="theme-button-secondary px-5 py-3 text-[14px]"
        >
          Quay lại map
        </button>
      </div>

      <PDFViewer
        isOpen={!!viewingPDF}
        title={viewingPDF?.title || ''}
        resourceId={viewingPDF?.resourceId || ''}
        initialPage={viewingPDF?.initialPage}
        isPinned={resolvedPinnedLessonResource?.key === viewingPDF?.key}
        onPageChange={handlePDFViewerPageChange}
        onTogglePin={handleTogglePinnedViewingPDF}
        onClose={() => setViewingPDF(null)}
      />
    </div>
  );

  const renderQuestionScreen = () => (
    <div className="white-panel min-h-[667px] overflow-hidden px-6 pb-8 pt-0 md:px-8">
      <div className="mb-0 flex flex-wrap translate-y-[-1px] gap-3 pt-6">
        <button
          onClick={() => setLessonTab('lesson')}
          className={`h-[56px] w-full rounded-full border text-[16px] font-medium transition-colors sm:h-[64px] sm:w-[220px] sm:text-[17px] ${
            lessonTab === 'lesson' ? 'bg-white text-[#141217]' : 'bg-white text-[#141217]'
          }`}
          style={{ borderColor: 'rgba(17,16,21,0.08)' }}
        >
          Bài học
        </button>
        <button
          onClick={() => void handleOpenQuestionsTab()}
          className={`h-[56px] w-full rounded-full border text-[16px] font-medium transition-colors sm:h-[64px] sm:w-[220px] sm:text-[17px] ${
            lessonTab === 'questions' ? 'bg-[#8c3451] text-white' : 'bg-white text-[#141217]'
          }`}
          style={{ borderColor: 'rgba(17,16,21,0.08)' }}
        >
          Câu hỏi ôn tập
        </button>
      </div>

      <div className="mt-6 grid gap-5 xl:grid-cols-[minmax(0,1.45fr)_320px]">
        <div className="soft-panel px-6 py-6">
          <p className="text-[12px] font-semibold uppercase tracking-[0.22em] text-[#8c3451]/60">
            Quiz Studio
          </p>
          <h3 className="mt-2 text-[28px] font-semibold tracking-[-0.04em] text-[#141217]">
            Tạo bộ câu hỏi sát với lesson này
          </h3>
          <p className="mt-3 text-[14px] leading-6 text-[#6a625d]">
            Câu hỏi sẽ bám trên các chunk đã được gợi ý cho lesson hiện tại. Bạn có thể đổi số
            lượng, dạng câu hỏi và mức tư duy trước khi sinh lại.
          </p>

          <div className="mt-6 grid gap-5 lg:grid-cols-2">
            <div>
              <p className="text-[12px] font-semibold uppercase tracking-[0.18em] text-[#8c3451]/60">
                Số lượng câu
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {QUESTION_COUNT_OPTIONS.map((count) => {
                  const active = questionConfig.targetCount === count;
                  return (
                    <button
                      key={`question-count-${count}`}
                      type="button"
                      onClick={() =>
                        setQuestionConfig((previous) => ({ ...previous, targetCount: count }))
                      }
                      className={`rounded-full border px-4 py-2 text-[13px] font-semibold transition ${
                        active
                          ? 'bg-[#8c3451] text-white shadow-[0_16px_28px_rgba(140,52,81,0.18)]'
                          : 'bg-white text-[#6a625d]'
                      }`}
                      style={{ borderColor: active ? '#8c3451' : 'rgba(17,16,21,0.08)' }}
                    >
                      {count} câu
                    </button>
                  );
                })}
              </div>
            </div>

            <div>
              <p className="text-[12px] font-semibold uppercase tracking-[0.18em] text-[#8c3451]/60">
                Độ khó
              </p>
              <div className="mt-3 flex flex-wrap gap-2">
                {DIFFICULTY_OPTIONS.map((option) => {
                  const active = questionConfig.difficulty === option.value;
                  return (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() =>
                        setQuestionConfig((previous) => ({ ...previous, difficulty: option.value }))
                      }
                      className={`rounded-full border px-4 py-2 text-[13px] font-semibold transition ${
                        active
                          ? 'bg-[#8c3451] text-white shadow-[0_16px_28px_rgba(140,52,81,0.18)]'
                          : 'bg-white text-[#6a625d]'
                      }`}
                      style={{ borderColor: active ? '#8c3451' : 'rgba(17,16,21,0.08)' }}
                    >
                      {option.label}
                    </button>
                  );
                })}
              </div>
            </div>
          </div>

          <div className="mt-5">
            <p className="text-[12px] font-semibold uppercase tracking-[0.18em] text-[#8c3451]/60">
              Loại câu hỏi
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {QUESTION_TYPE_OPTIONS.map((option) => {
                const active = questionConfig.questionTypes.includes(option.value);
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => handleQuestionTypeToggle(option.value)}
                    className={`rounded-[18px] border px-4 py-3 text-left transition ${
                      active
                        ? 'bg-[#8c3451] text-white shadow-[0_16px_28px_rgba(140,52,81,0.18)]'
                        : 'bg-white text-[#6a625d]'
                    }`}
                    style={{ borderColor: active ? '#8c3451' : 'rgba(17,16,21,0.08)' }}
                  >
                    <p className="text-[13px] font-semibold">{option.label}</p>
                    <p
                      className={`mt-1 text-[12px] ${active ? 'text-white/80' : 'text-[#8b7f88]'}`}
                    >
                      {option.description}
                    </p>
                  </button>
                );
              })}
            </div>
          </div>

          <div className="mt-5">
            <p className="text-[12px] font-semibold uppercase tracking-[0.18em] text-[#8c3451]/60">
              Mức tư duy Bloom
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              {BLOOM_LEVEL_OPTIONS.map((option) => {
                const active = questionConfig.bloomLevels.includes(option.value);
                return (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => handleBloomLevelToggle(option.value)}
                    className={`rounded-full border px-4 py-2 text-[13px] font-semibold transition ${
                      active ? 'bg-[#f6d6e0] text-[#8c3451]' : 'bg-white text-[#6a625d]'
                    }`}
                    style={{ borderColor: active ? '#e8bfd0' : 'rgba(17,16,21,0.08)' }}
                  >
                    {option.label}
                  </button>
                );
              })}
            </div>
          </div>

          <div className="mt-6 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => void generateLessonQuestions(true)}
              disabled={questionGenerating}
              className="theme-button px-5 py-3 text-[14px] disabled:opacity-50"
            >
              {questionGenerating ? 'Đang tạo bộ câu hỏi...' : 'Sinh lại theo thiết lập này'}
            </button>
            <button
              type="button"
              onClick={() => void generateLessonQuestions(false)}
              disabled={questionGenerating}
              className="theme-button-secondary px-5 py-3 text-[14px] disabled:opacity-50"
            >
              Dùng lại nếu đã có
            </button>
          </div>
        </div>

        <div className="soft-panel px-6 py-6">
          <p className="text-[12px] font-semibold uppercase tracking-[0.22em] text-[#8c3451]/60">
            Tiến độ ôn tập
          </p>
          <div className="mt-4 space-y-3">
            <div className="rounded-[18px] bg-white/90 px-4 py-4 shadow-[0_12px_24px_rgba(114,62,83,0.06)]">
              <p className="text-[13px] text-[#8b7f88]">Đã trả lời</p>
              <p className="mt-1 text-[26px] font-semibold tracking-[-0.03em] text-[#141217]">
                {answeredQuestionCount}/{quizStats.total || questionConfig.targetCount}
              </p>
            </div>
            <div className="rounded-[18px] bg-white/90 px-4 py-4 shadow-[0_12px_24px_rgba(114,62,83,0.06)]">
              <p className="text-[13px] text-[#8b7f88]">Độ tự tin</p>
              <p className="mt-1 text-[26px] font-semibold tracking-[-0.03em] text-[#141217]">
                {selectedLesson?.status === 'complete' && bestLessonConfidence !== null
                  ? `${bestLessonConfidence}%`
                  : submitted
                    ? `${quizStats.confidence}%`
                    : '--'}
              </p>
              {selectedLesson?.status === 'complete' && bestLessonConfidence !== null && (
                <p className="mt-1 text-[12px] text-[#8c3451]">Điểm cao nhất</p>
              )}
            </div>
            <div className="rounded-[18px] bg-white/90 px-4 py-4 shadow-[0_12px_24px_rgba(114,62,83,0.06)]">
              <p className="text-[13px] text-[#8b7f88]">Đúng / Sai</p>
              <p className="mt-1 text-[20px] font-semibold tracking-[-0.03em] text-[#141217]">
                {submitted ? `${quizStats.correct} đúng · ${quizStats.wrong} sai` : 'Chưa nộp bài'}
              </p>
            </div>
            <div className="rounded-[18px] bg-[linear-gradient(135deg,#fffafd_0%,#fdf2f6_100%)] px-4 py-4 text-[13px] leading-6 text-[#6a625d] shadow-[0_12px_24px_rgba(114,62,83,0.06)]">
              Bài này hiện có{' '}
              <span className="font-semibold text-[#8c3451]">
                {lessonRecommendedChunks?.recommended_chunks?.length || 0} chunk
              </span>{' '}
              gợi ý để làm nguồn sinh câu hỏi.
            </div>
          </div>
        </div>
      </div>

      {questionNotice && !questionError && (
        <div className="mt-5 rounded-[14px] border border-[#ead7df] bg-[#fff7fb] px-4 py-4 text-[14px] text-[#8c3451]">
          <p>{questionNotice}</p>
        </div>
      )}

      {questionLoading ? (
        <div className="py-20 text-center text-[15px] text-[#8c3451]">
          Đang tải câu hỏi ôn tập...
        </div>
      ) : questionError ? (
        <div className="rounded-[14px] border border-red-200 bg-red-50 px-4 py-4 text-[14px] text-red-700">
          <p>{questionError}</p>
          <button
            onClick={() => void generateLessonQuestions(true)}
            className="theme-button mt-3 px-5 py-3 text-[14px]"
          >
            Tạo câu hỏi mới
          </button>
        </div>
      ) : !currentQuestion ? (
        <div className="py-16 text-center">
          <p className="text-[15px] text-[#8c3451]">Chưa có câu hỏi cho bài học này.</p>
          <button
            onClick={() => void generateLessonQuestions(true)}
            className="theme-button mt-4 px-5 py-3 text-[14px]"
          >
            {questionGenerating ? 'Đang tạo...' : 'Tạo câu hỏi ôn tập'}
          </button>
        </div>
      ) : (
        <>
          <div className="mt-8 flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-[#f6d6e0] px-4 py-2 text-[12px] font-semibold text-[#8c3451]">
                {getQuestionTypeLabel(currentQuestion.question_type)}
              </span>
              <span className="rounded-full bg-white px-4 py-2 text-[12px] font-semibold text-[#6f5260]">
                {getBloomLevelLabel(currentQuestion.bloom_level)}
              </span>
              <span className="rounded-full bg-white px-4 py-2 text-[12px] font-semibold text-[#6f5260]">
                {getDifficultyLabel(currentQuestion.difficulty)}
              </span>
              {currentQuestionSources.length > 0 ? (
                <span className="rounded-full bg-white px-4 py-2 text-[12px] font-semibold text-[#6f5260]">
                  {currentQuestionSources
                    .map((item) =>
                      item.page_number ? `trang ${item.page_number}` : item.chunk_index + 1,
                    )
                    .join(' · ')}
                </span>
              ) : null}
            </div>
            <p className="text-[13px] text-[#8b7f88]">
              Câu {currentQuestionIndex + 1}/{quizQuestions.length}
            </p>
          </div>

          <div className="mt-4 h-2 overflow-hidden rounded-full bg-[#f7e8ee]">
            <div
              className="h-full rounded-full bg-[#8c3451] transition-all"
              style={{
                width: `${quizQuestions.length > 0 ? ((currentQuestionIndex + 1) / quizQuestions.length) * 100 : 0}%`,
              }}
            />
          </div>

          <div className="flex items-center justify-center gap-3 px-0 pt-8 sm:gap-6 sm:px-2">
            <button
              onClick={() => setCurrentQuestionIndex((value) => Math.max(value - 1, 0))}
              disabled={currentQuestionIndex === 0}
              className="flex h-14 w-14 items-center justify-center rounded-full border border-black/10 bg-white text-[38px] leading-none text-[#141217] shadow-[0_12px_24px_rgba(45,31,17,0.08)] disabled:opacity-30"
            >
              ←
            </button>

            <div className="relative max-w-full">
              <div className="absolute left-[42px] top-0 h-full w-full rounded-[28px] border border-black/10 bg-[#efc1cc]" />
              <div className="absolute left-[22px] top-0 h-full w-full rounded-[28px] border border-black/10 bg-[#efcddb]" />
              <div
                className="relative z-[2] min-h-[360px] w-[min(760px,calc(100vw-140px))] rounded-[28px] border border-black/10 bg-[#f7d7de] px-5 py-6 sm:px-8 sm:py-7"
                style={{ boxShadow: '0 18px 36px rgba(45,31,17,0.12)' }}
              >
                <h3 className="text-[22px] font-semibold tracking-[-0.03em] text-[#141217]">
                  Câu hỏi {currentQuestionIndex + 1}:{' '}
                  <span className="font-normal">{currentQuestion.question}</span>
                </h3>

                {currentQuestion.question_type === 'short_answer' ? (
                  <div className="mt-8">
                    <textarea
                      value={selectedAnswers[currentQuestion.question_id] || ''}
                      onChange={(event) =>
                        handleSelectAnswer(currentQuestion.question_id, event.target.value)
                      }
                      disabled={submitted}
                      placeholder="Tự nhập câu trả lời ngắn của bạn..."
                      className="min-h-[140px] w-full rounded-[22px] border border-white/80 bg-white/85 px-5 py-4 text-[16px] text-[#141217] outline-none placeholder:text-[#8b7f88] focus:border-[#8c3451]"
                    />
                    <p className="mt-3 text-[13px] leading-6 text-[#6a625d]">
                      Câu trả lời ngắn sẽ được đối chiếu gần đúng theo từ khóa chính của đáp án mẫu.
                    </p>
                  </div>
                ) : (
                  <div className="mt-8 space-y-4">
                    {buildQuestionChoices(currentQuestion).map((choice, index) => {
                      const label = ['A', 'B', 'C', 'D'][index] || `${index + 1}`;
                      const picked = selectedAnswers[currentQuestion.question_id] === choice;
                      const isCorrect =
                        submitted && isQuestionAnsweredCorrectly(currentQuestion, choice);
                      const isWrong =
                        submitted &&
                        picked &&
                        !isQuestionAnsweredCorrectly(currentQuestion, choice);

                      return (
                        <button
                          key={`${currentQuestion.question_id}-${label}`}
                          onClick={() => handleSelectAnswer(currentQuestion.question_id, choice)}
                          className={`flex w-full items-center gap-3 rounded-[18px] px-2 py-1 text-left ${picked ? 'bg-white/50' : 'bg-transparent'}`}
                        >
                          <span
                            className={`flex h-11 w-11 items-center justify-center rounded-full bg-white text-[18px] font-bold text-[#141217] ${
                              isCorrect
                                ? 'ring-2 ring-green-500'
                                : isWrong
                                  ? 'ring-2 ring-red-400'
                                  : ''
                            }`}
                          >
                            {label}
                          </span>
                          <span className="text-[16px] text-[#141217]">
                            {getQuestionChoiceLabel(choice)}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                )}

                {submitted && (
                  <div className="mt-6 rounded-[18px] bg-white/70 px-4 py-4 text-[14px] text-[#141217]">
                    {currentQuestion.question_type === 'short_answer' ? (
                      <p className="font-semibold">
                        Câu trả lời của bạn:{' '}
                        <span className="font-normal">
                          {selectedAnswers[currentQuestion.question_id] || 'Chưa trả lời'}
                        </span>
                      </p>
                    ) : null}
                    <p className="font-semibold">
                      Đáp án đúng: {getQuestionChoiceLabel(currentQuestion.correct_answer)}
                    </p>
                    <p className="mt-1">
                      {currentQuestion.explanation || 'Chưa có giải thích chi tiết.'}
                    </p>
                    {currentQuestionSources.length > 0 ? (
                      <div className="mt-3 flex flex-wrap gap-2">
                        {currentQuestionSources.map((item) => (
                          <span
                            key={`question-source-${item.chunk_id}`}
                            className="rounded-full bg-white px-3 py-1 text-[12px] font-medium text-[#8c3451]"
                          >
                            {item.page_number
                              ? `${item.resource_title || 'PDF'} · trang ${item.page_number}`
                              : item.resource_title || `Chunk ${item.chunk_index + 1}`}
                          </span>
                        ))}
                      </div>
                    ) : null}
                  </div>
                )}
              </div>
            </div>

            <button
              onClick={() =>
                setCurrentQuestionIndex((value) => Math.min(value + 1, quizQuestions.length - 1))
              }
              disabled={currentQuestionIndex >= quizQuestions.length - 1}
              className="flex h-14 w-14 items-center justify-center rounded-full border border-black/10 bg-white text-[38px] leading-none text-[#141217] shadow-[0_12px_24px_rgba(45,31,17,0.08)] disabled:opacity-30"
            >
              →
            </button>
          </div>

          <div className="mt-6 flex flex-wrap items-center justify-center gap-4">
            <button
              type="button"
              onClick={() => {
                setSelectedAnswers({});
                setSubmitted(false);
                setCurrentQuestionIndex(0);
              }}
              className="theme-button-secondary px-8 py-3 text-[15px] font-bold"
            >
              Làm lại lượt này
            </button>
            <button
              onClick={handleSubmitQuizAnswers}
              disabled={submitted || quizQuestions.length === 0 || answeredQuestionCount === 0}
              className="theme-button px-12 py-3 text-[15px] font-bold disabled:opacity-50"
            >
              Nộp bài
            </button>
          </div>
        </>
      )}
    </div>
  );

  const renderLessonScreen = () => (
    <div>{lessonTab === 'lesson' ? renderLessonResources() : renderQuestionScreen()}</div>
  );

  return (
    <DashboardLayout>
      <div className="min-h-[calc(100vh-110px)] px-2 py-3 md:px-4 md:py-5">
        {loading ? (
          <div className="white-panel flex min-h-[420px] items-center justify-center">
            <div className="text-[16px] text-black/60">Đang tải lộ trình...</div>
          </div>
        ) : error ? (
          <div className="white-panel border border-red-200 bg-red-50 px-4 py-4 text-red-700">
            {error}
          </div>
        ) : (
          <div className="page-shell max-w-[1280px]">
            {renderHeader()}
            {screenMode === 'subject' && renderSubjectScreen()}
            {screenMode === 'map' && renderMapScreen()}
            {screenMode === 'lesson' && selectedLesson && renderLessonScreen()}
          </div>
        )}
      </div>

      {pendingDeletePath && path?.path_id && (
        <div
          className="fixed inset-0 z-[90] flex items-center justify-center bg-[#2a1522]/20 px-4 py-6 backdrop-blur-sm"
          onClick={() => {
            if (!deletingPath) {
              setPendingDeletePath(false);
            }
          }}
        >
          <div
            className="white-panel ui-pop-in w-full max-w-[480px] rounded-[28px] p-7 shadow-[0_28px_80px_rgba(140,52,81,0.16)]"
            onClick={(event) => event.stopPropagation()}
          >
            <p className="page-kicker mb-2">Xóa lộ trình</p>
            <h3 className="text-[28px] font-semibold tracking-[-0.04em] text-[#141217]">
              Bạn có chắc muốn xóa?
            </h3>
            <p className="mt-4 text-[15px] leading-7 text-[#5f5853]">
              Lộ trình{' '}
              <span className="font-semibold text-[#8c3451]">{displayGoal || subjectLabel}</span> sẽ
              bị xóa cùng các chương, bài học và câu hỏi được sinh riêng cho lộ trình này.
            </p>
            <div className="mt-8 flex flex-wrap justify-end gap-3">
              <button
                type="button"
                onClick={() => setPendingDeletePath(false)}
                disabled={deletingPath}
                className="theme-button-secondary"
              >
                Giữ lại
              </button>
              <button
                type="button"
                onClick={() => void handleDeletePath()}
                disabled={deletingPath}
                className="theme-button disabled:opacity-60"
              >
                {deletingPath ? 'Đang xóa...' : 'Xóa lộ trình'}
              </button>
            </div>
          </div>
        </div>
      )}
    </DashboardLayout>
  );
}
