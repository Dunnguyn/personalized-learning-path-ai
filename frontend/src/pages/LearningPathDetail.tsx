import { useEffect, useMemo, useRef, useState } from 'react';
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
import { useAuth } from '../contexts/AuthContext';
import { learningPathService } from '../services';
import type {
  LearningPath,
  LearningPathChapter,
  LearningPathLesson,
  LessonRecommendedChunks,
  LessonQuestion,
  LessonQuestionBank,
  LessonStatus,
} from '../services/learningPathService';
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
}

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

const getChapterAccent = (chapterIndex: number) => CHAPTER_ACCENTS[(chapterIndex - 1) % CHAPTER_ACCENTS.length];

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
            <span className={`rounded-full px-3 py-1 text-[11px] font-semibold ${statusMeta.pillClass}`}>
              {statusMeta.label}
            </span>
          </div>
          <p className="max-h-[48px] overflow-hidden text-[20px] font-semibold leading-[1.2] tracking-[-0.03em] text-[#141217]">
            Bài {lesson.chapter_index}.{lesson.lesson_index}: {cleanLessonTitle(lesson.title)}
          </p>
        </div>
      </div>

      <p className="max-h-[72px] overflow-hidden text-[13px] leading-6 text-[#6a625d]">
        {lesson.summary?.trim() || 'Bài học này giúp bạn tiến thêm một bước trong lộ trình hiện tại.'}
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
            canOpenLesson
              ? 'bg-[#8c3451] text-white'
              : 'bg-slate-100 text-slate-500'
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

const updateLessonStatusInPath = (currentPath: LearningPath, lessonId: string, status: LessonStatus): LearningPath => {
  const updateChapters = (chapters: LearningPathChapter[]) =>
    chapters.map((chapter) => ({
      ...chapter,
      lessons: chapter.lessons.map((lesson) =>
        lesson.lesson_id === lessonId
          ? {
              ...lesson,
              status,
            }
          : lesson
      ),
    }));

  const nextChapters = updateChapters(currentPath.curriculum?.length ? currentPath.curriculum : currentPath.chapters);

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
  chapter.lessons.find((lesson) => lesson.summary?.trim())?.summary?.trim() || 'Nội dung chương trình';

const cleanChapterTitle = (title: string) => title.replace(/^chương\s*\d+\s*:\s*/i, '').trim();
const cleanLessonTitle = (title: string) => title.replace(/^bài\s*\d+(?:\.\d+)?\s*:\s*/i, '').trim();

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

const buildQuestionChoices = (question: LessonQuestion) => {
  if (question.question_type === 'multiple_choice') {
    return [question.correct_answer, ...question.distractors].filter(Boolean).slice(0, 4);
  }
  if (question.question_type === 'true_false') {
    return ['Đúng', 'Sai'];
  }
  return [question.correct_answer || 'Trả lời ngắn'];
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
  const [lessonRecommendedChunks, setLessonRecommendedChunks] = useState<LessonRecommendedChunks | null>(null);
  const [questionBank, setQuestionBank] = useState<LessonQuestionBank | null>(null);
  const [questionLoading, setQuestionLoading] = useState(false);
  const [questionGenerating, setQuestionGenerating] = useState(false);
  const [questionError, setQuestionError] = useState<string | null>(null);
  const [questionNotice, setQuestionNotice] = useState<string | null>(null);
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
    [path]
  );
  const lessons = useMemo(() => buildLessonCollection(chapters), [chapters]);
  const curriculumNotice = useMemo(() => getLearningPathNotice(path), [path]);
  const subjectLabel = getSubjectLabel(path?.subject_id, path?.goal);
  const displayGoal = useMemo(() => getDisplayGoal(path?.subject_id, path?.goal), [path?.goal, path?.subject_id]);
  const collapsedChapterKey = useMemo(() => collapsedChapterIds.slice().sort().join(','), [collapsedChapterIds]);
  const mapViewportStorageKey = useMemo(
    () =>
      path?.path_id
        ? `learning-path-map-viewport:${path.path_id}:${mapLayoutMode}:${mapStatusFilter}:${collapsedChapterKey}`
        : null,
    [collapsedChapterKey, mapLayoutMode, mapStatusFilter, path?.path_id]
  );
  const mapLessons = useMemo(
    () =>
      lessons.filter(
        (lesson) =>
          (mapStatusFilter === 'all' ? true : lesson.status === mapStatusFilter) &&
          (!mapFocusedChapterId || lesson.chapter_id === mapFocusedChapterId) &&
          !collapsedChapterIds.includes(lesson.chapter_id)
      ),
    [collapsedChapterIds, lessons, mapFocusedChapterId, mapStatusFilter]
  );
  const selectedLessonGlobalIndex = useMemo(
    () => lessons.findIndex((lesson) => lesson.lesson_id === selectedLesson?.lesson_id),
    [lessons, selectedLesson?.lesson_id]
  );
  const selectedLessonVisibleIndex = useMemo(
    () => mapLessons.findIndex((lesson) => lesson.lesson_id === selectedLesson?.lesson_id),
    [mapLessons, selectedLesson?.lesson_id]
  );

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

    if (!selectedLesson || !mapLessons.some((lesson) => lesson.lesson_id === selectedLesson.lesson_id)) {
              setSelectedLesson(mapLessons[0]);
    }
  }, [mapLessons, selectedLesson]);

  useEffect(() => {
    if (hoveredLesson && !mapLessons.some((lesson) => lesson.lesson_id === hoveredLesson.lesson_id)) {
      setHoveredLesson(null);
    }
  }, [hoveredLesson, mapLessons]);

  useEffect(() => {
    if (!selectedLesson) {
      setLessonRecommendedChunks(null);
      return;
    }

    let active = true;

    const loadRecommendedChunks = async () => {
      try {
        const existing = await learningPathService.getLessonRecommendedChunks(selectedLesson.lesson_id);
        if (active) {
          setLessonRecommendedChunks(existing);
        }
      } catch {
        try {
          const generated = await learningPathService.recommendLessonChunks(selectedLesson.lesson_id, {
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
      }
    };

    void loadRecommendedChunks();

    return () => {
      active = false;
    };
  }, [selectedLesson?.lesson_id]);

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
      return lessonRecommendedChunks.recommended_chunks.slice(0, 3).map((chunk, index) => ({
        key: chunk.chunk_id || `${chunk.resource_id}-${index}`,
        title: `Học liệu gợi ý ${index + 1}`,
        source: 'Chunk gợi ý',
        preview: chunk.preview?.trim() || 'Đang đồng bộ nội dung học liệu từ backend.',
      }));
    }

    if (selectedLesson?.resources?.length) {
      return selectedLesson.resources.slice(0, 3).map((resource, index) => ({
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

  const quizQuestions = useMemo(() => {
    const items = questionBank?.questions || [];
    const multipleChoice = items.filter((question) => buildQuestionChoices(question).length >= 2);
    return multipleChoice.length > 0 ? multipleChoice : items;
  }, [questionBank]);

  const currentQuestion = quizQuestions[currentQuestionIndex] || null;

  const quizStats = useMemo(() => {
    const total = quizQuestions.length;
    const correct = quizQuestions.reduce((count, question) => {
      return selectedAnswers[question.question_id] === question.correct_answer ? count + 1 : count;
    }, 0);
    const wrong = submitted ? Math.max(total - correct, 0) : 0;
    const confidence = total > 0 && submitted ? Math.round((correct / total) * 100) : 0;
    return { total, correct, wrong, confidence };
  }, [quizQuestions, selectedAnswers, submitted]);

  const openLessonScreen = (lesson: LessonNode) => {
    setSelectedLesson(lesson);
    setLessonTab('lesson');
    setScreenMode('lesson');
  };

  const handleMapLessonSelect = (lesson: LessonNode) => {
    if (selectedLesson?.lesson_id === lesson.lesson_id && lesson.status !== 'not_started') {
      openLessonScreen(lesson);
      return;
    }
    setSelectedLesson(lesson);
  };

  const mapNodes = useMemo<Node[]>(
    () => {
      const visibleChapters = chapters
        .map((chapter, chapterIndex) => ({ chapter, chapterIndex }))
        .filter(({ chapter }) => !collapsedChapterIds.includes(chapter.chapter_id));

      const chapterNodes: Node<MapChapterNodeData>[] = visibleChapters.map(({ chapter, chapterIndex }, visibleIndex) => ({
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
      }));

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
                  (isZigzagRow ? JOURNEY_COLUMNS - 1 - journeyColumn : journeyColumn) * JOURNEY_SPACING_X,
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
              mapLessons.findIndex((item) => item.lesson_id === lesson.lesson_id) <= selectedLessonVisibleIndex,
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
    },
    [chapters, collapsedChapterIds, handleMapLessonSelect, mapLayoutMode, mapLessons, openLessonScreen, selectedLesson?.lesson_id, selectedLessonVisibleIndex]
  );

  const mapEdges = useMemo<Edge[]>(
    () =>
      mapLessons.slice(1).map((lesson, index) => {
        const previousLesson = mapLessons[index];
        const chapterChanged = previousLesson.chapter_id !== lesson.chapter_id;
        const isHighlighted = selectedLessonVisibleIndex >= index + 1 && selectedLessonVisibleIndex >= 0;
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
    [mapLessons, selectedLessonVisibleIndex]
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
    if (screenMode !== 'map' || !mapInstance || !mapViewportStorageKey || hasRestoredViewportRef.current) {
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
      previous === selectedLesson.chapter_id ? null : selectedLesson.chapter_id
    );
  };

  const handleFitAllMapNodes = () => {
    if (!mapInstance || mapLessons.length === 0) {
      return;
    }

    mapInstance.fitView({
      padding: 0.18,
      duration: 500,
    });
  };

  const handleFitCurrentChapter = () => {
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
  };

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

  const previousLesson = selectedLessonGlobalIndex > 0 ? lessons[selectedLessonGlobalIndex - 1] : null;
  const nextLesson =
    selectedLessonGlobalIndex >= 0 && selectedLessonGlobalIndex < lessons.length - 1
      ? lessons[selectedLessonGlobalIndex + 1]
      : null;
  const previewLesson = hoveredLesson || selectedLesson;
  const currentChapterProgress = selectedLesson
    ? chapters.find((chapter) => chapter.chapter_id === selectedLesson.chapter_id)
    : null;
  const currentChapterLessons = currentChapterProgress?.lessons || [];
  const currentChapterCompleted = currentChapterLessons.filter((lesson) => lesson.status === 'complete').length;

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

  const handleLessonStatusUpdate = async (lessonId: string, status: LessonStatus) => {
    if (!path?.path_id) {
      return;
    }

    try {
      setUpdatingLessonId(lessonId);
      setError(null);

      const response = await learningPathService.updateLessonProgress({
        path_id: path.path_id,
        lesson_id: lessonId,
        status,
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

  const generateLessonQuestions = async () => {
    if (!selectedLesson) {
      return;
    }

    try {
      setQuestionGenerating(true);
      setQuestionError(null);
      setQuestionNotice(null);
      const result = await learningPathService.generateLessonQuestions(selectedLesson.lesson_id, {
        target_count: 5,
        question_types: ['multiple_choice'],
        difficulty: path?.level || 'beginner',
        bloom_levels: ['remember', 'understand', 'apply'],
        overwrite: true,
        metadata: { source: 'learning_path_quiz' },
      });
      if (result.reused_existing && result.existing_count > 0) {
        await loadLessonQuestions(selectedLesson.lesson_id);
        setQuestionNotice(result.message || 'Đang dùng lại bộ câu hỏi đã tạo trước đó cho bài học này.');
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
            {screenMode === 'subject' ? 'Lộ trình học tập chi tiết' : `Lộ trình học tập - ${subjectLabel}`}
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
            Bài {selectedLesson.chapter_index}.{selectedLesson.lesson_index}: {cleanLessonTitle(selectedLesson.title)}
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
            {chapters.some((chapter) => getChapterStatusLabel(chapter) === 'Đang học') ? 'Đang học' : 'Chưa học'}
          </span>
        </div>

        <div className="mt-6 grid gap-4 md:grid-cols-3">
          <div className="metric-card p-4">
            <p className="text-[12px] font-medium uppercase tracking-[0.18em] text-black/35">Trình độ</p>
            <p className="mt-2 text-[18px] font-semibold capitalize text-[#141217]">{path?.level || 'beginner'}</p>
          </div>
          <div className="metric-card p-4">
            <p className="text-[12px] font-medium uppercase tracking-[0.18em] text-black/35">Ngày tạo</p>
            <p className="mt-2 text-[18px] font-semibold text-[#141217]">{formatDateTime(path?.generated_at)}</p>
          </div>
          <div className="metric-card p-4">
            <p className="text-[12px] font-medium uppercase tracking-[0.18em] text-black/35">Số chương</p>
            <p className="mt-2 text-[18px] font-semibold text-[#141217]">{chapters.length} chương</p>
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
                const firstLesson = lessons.find((lesson) => lesson.chapter_id === chapter.chapter_id);
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
                  <p className="mt-3 max-w-3xl text-[14px] leading-7 text-black/55">{getChapterDescription(chapter)}</p>
                </div>
                <span className={`inline-flex shrink-0 items-center rounded-full px-4 py-2 text-[12px] font-medium ${statusLabel === 'Đang học' ? 'bg-[#8c3451] text-white' : 'bg-[#f8e3ea] text-black/65'}`}>
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
              {subjectLabel} / Chương {selectedLesson.chapter_index} / Bài {selectedLesson.lesson_index}
            </p>
          )}
          <div className="mb-4 flex items-center justify-between gap-4">
            <span className="rounded-full bg-white/80 px-4 py-2 text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]/75">
              {selectedLesson ? `Chương ${selectedLesson.chapter_index}` : 'Bài học'}
            </span>
            <span className={`rounded-full px-3 py-1 text-[11px] font-semibold ${selectedStatusMeta.pillClass}`}>
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
            <p className="mt-2 text-[18px] font-semibold text-[#141217]">{selectedStatusMeta.label}</p>
          </div>
          <div className="metric-card p-4">
            <p className="text-[12px] uppercase tracking-[0.14em] text-[#8c3451]/55">Cấp độ</p>
            <p className="mt-2 text-[18px] font-semibold capitalize text-[#141217]">{path?.level || 'beginner'}</p>
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
              onClick={() => selectedLesson && canOpenSelectedLesson && openLessonScreen(selectedLesson)}
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
              disabled={!selectedLesson || selectedLesson.status === 'in_progress' || updatingLessonId === selectedLesson?.lesson_id}
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
        <div className={mapPresentationMode ? 'space-y-0' : 'grid gap-6 xl:grid-cols-[minmax(0,1fr)_380px]'}>
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
                <span className="flex h-9 w-9 items-center justify-center rounded-full bg-[#f9eef3] text-[#8c3451]">⌕</span>
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
                            {mapPresentationMode ? 'Thoát presentation mode' : 'Presentation mode'}
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
                  const chapterLessonsCount = lessons.filter((lesson) => lesson.chapter_id === chapter.chapter_id).length;
                  return (
                    <option key={chapter.chapter_id || `${chapter.title}-${index}`} value={chapter.chapter_id}>
                      {`Chương ${index + 1} (${chapterLessonsCount} bài)`}
                    </option>
                  );
                })}
              </select>

              {mapSearchTerm.trim() && (
                <span className="shrink-0 rounded-full bg-[#f9eef3] px-4 py-2 text-[12px] font-medium text-[#8c3451]">
                  {searchedLessons.length > 0 ? `${searchedLessons.length} bài khớp` : 'Không có kết quả'}
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
                const chapterLessonsCount = lessons.filter((lesson) => lesson.chapter_id === chapter.chapter_id).length;
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
                    {isActiveChapter ? <span className="ml-2 opacity-70">• {chapterLessonsCount} bài</span> : null}
                  </button>
                );
              })}

              {mapSearchTerm.trim() && (
                <span className="shrink-0 rounded-full bg-[#f9eef3] px-4 py-2 text-[12px] font-medium text-[#8c3451]">
                  {searchedLessons.length > 0 ? `${searchedLessons.length} bài khớp` : 'Không có kết quả'}
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
                    Bài {previewLesson.chapter_index}.{previewLesson.lesson_index}: {cleanLessonTitle(previewLesson.title)}
                  </p>
                  <p className="mt-2 hidden max-h-[76px] overflow-hidden text-[13px] leading-6 text-[#625b56] md:block">
                    {previewLesson.summary?.trim() || 'Bài học này giúp bạn tiếp tục tiến lên trong lộ trình hiện tại.'}
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
                  <p className="text-[18px] font-semibold text-[#141217]">Không có bài học nào khớp bộ lọc hiện tại</p>
                  <p className="mt-3 text-[14px] leading-7 text-[#615954]">
                    Hãy thử đổi trạng thái, mở lại chương đang thu gọn hoặc xóa từ khóa tìm kiếm để xem nhiều bài học hơn.
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
                    if (lessonNode?.lesson?.status === 'in_progress') return lessonNode?.accent?.solid || '#8c3451';
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

          {!mapPresentationMode && <aside className="hidden space-y-5 xl:sticky xl:top-4 xl:block xl:self-start">{detailPanel}</aside>}
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
                  <p className="mt-1 text-[14px] text-[#615954]">Xem nhanh nội dung và thao tác tiếp theo</p>
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
                  <p className="mt-1 text-[14px] text-[#615954]">Chọn cách xem phù hợp rồi quay lại sơ đồ</p>
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

      <div className="soft-panel mt-6 grid grid-cols-1 gap-8 px-6 pb-6 pt-7 xl:grid-cols-3">
        {currentLessonResources.slice(0, 3).map((resource) => {
          return (
            <div
              key={resource.key}
              className="min-h-[404px] rounded-[28px] border bg-white px-5 pb-6 pt-5"
              style={{ borderColor: 'rgba(17,16,21,0.08)' }}
            >
              <div className="flex items-start justify-between gap-4">
                <div>
                  <h3 className="text-[20px] font-semibold tracking-[-0.03em] text-[#141217]">{resource.title}</h3>
                  <p className="mt-1 text-[13px] text-black/55">Nguồn: {resource.source}</p>
                </div>
                <span className="rounded-full bg-[#f6d6e0] px-4 py-2 text-[11px] font-semibold text-[#7f3650]">
                  {path?.level || 'Cơ bản'}
                </span>
              </div>
              <div
                className="mx-auto mt-8 flex h-[309px] w-full max-w-[227px] items-start justify-center overflow-hidden rounded-[22px] bg-[#fbf8f3] px-4 pt-4 text-[10px] text-black/70"
                style={{ boxShadow: '0 12px 28px rgba(45,31,17,0.08)' }}
              >
                <p className="max-h-[260px] overflow-hidden text-center text-[12px] leading-6 text-black/65">{resource.preview}</p>
              </div>
            </div>
          );
        })}
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

      <div className="soft-panel mt-6 grid w-full gap-1 px-6 py-5 text-[13px] font-semibold text-[#141217] sm:max-w-[260px]">
        <p>Độ tự tin: {submitted ? `${quizStats.confidence}%` : ''}</p>
        <p>Số câu đúng: {submitted ? quizStats.correct : ''}</p>
        <p>Số câu sai: {submitted ? quizStats.wrong : ''}</p>
      </div>

      {questionNotice && !questionError && (
        <div className="mt-5 rounded-[14px] border border-[#ead7df] bg-[#fff7fb] px-4 py-4 text-[14px] text-[#8c3451]">
          <p>{questionNotice}</p>
        </div>
      )}

      {questionLoading ? (
        <div className="py-20 text-center text-[15px] text-[#8c3451]">Đang tải câu hỏi ôn tập...</div>
      ) : questionError ? (
        <div className="rounded-[14px] border border-red-200 bg-red-50 px-4 py-4 text-[14px] text-red-700">
          <p>{questionError}</p>
          <button onClick={() => void generateLessonQuestions()} className="theme-button mt-3 px-5 py-3 text-[14px]">
            Tạo câu hỏi mới
          </button>
        </div>
      ) : !currentQuestion ? (
        <div className="py-16 text-center">
          <p className="text-[15px] text-[#8c3451]">Chưa có câu hỏi cho bài học này.</p>
          <button onClick={() => void generateLessonQuestions()} className="theme-button mt-4 px-5 py-3 text-[14px]">
            {questionGenerating ? 'Đang tạo...' : 'Tạo câu hỏi ôn tập'}
          </button>
        </div>
      ) : (
        <>
          <div className="flex items-center justify-center gap-3 px-0 pt-10 sm:gap-6 sm:px-2">
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
                className="relative z-[2] min-h-[320px] w-[min(700px,calc(100vw-140px))] rounded-[28px] border border-black/10 bg-[#f7d7de] px-5 py-6 sm:px-8 sm:py-7"
                style={{ boxShadow: '0 18px 36px rgba(45,31,17,0.12)' }}
              >
                <h3 className="text-[22px] font-semibold tracking-[-0.03em] text-[#141217]">
                  Câu hỏi {currentQuestionIndex + 1}: <span className="font-normal">{currentQuestion.question}</span>
                </h3>

                <div className="mt-8 space-y-4">
                  {buildQuestionChoices(currentQuestion).map((choice, index) => {
                    const label = ['A', 'B', 'C', 'D'][index] || `${index + 1}`;
                    const picked = selectedAnswers[currentQuestion.question_id] === choice;
                    const isCorrect = submitted && choice === currentQuestion.correct_answer;
                    const isWrong = submitted && picked && choice !== currentQuestion.correct_answer;

                    return (
                      <button
                        key={`${currentQuestion.question_id}-${label}`}
                        onClick={() => handleSelectAnswer(currentQuestion.question_id, choice)}
                        className={`flex w-full items-center gap-3 rounded-[18px] px-2 py-1 text-left ${picked ? 'bg-white/50' : 'bg-transparent'}`}
                      >
                        <span
                          className={`flex h-11 w-11 items-center justify-center rounded-full bg-white text-[18px] font-bold text-[#141217] ${
                            isCorrect ? 'ring-2 ring-green-500' : isWrong ? 'ring-2 ring-red-400' : ''
                          }`}
                        >
                          {label}
                        </span>
                        <span className="text-[16px] text-[#141217]">{choice}</span>
                      </button>
                    );
                  })}
                </div>

                {submitted && (
                  <div className="mt-6 rounded-[18px] bg-white/70 px-4 py-4 text-[14px] text-[#141217]">
                    <p className="font-semibold">Đáp án đúng: {currentQuestion.correct_answer}</p>
                    <p className="mt-1">{currentQuestion.explanation || 'Chưa có giải thích chi tiết.'}</p>
                  </div>
                )}
              </div>
            </div>

            <button
              onClick={() => setCurrentQuestionIndex((value) => Math.min(value + 1, quizQuestions.length - 1))}
              disabled={currentQuestionIndex >= quizQuestions.length - 1}
              className="flex h-14 w-14 items-center justify-center rounded-full border border-black/10 bg-white text-[38px] leading-none text-[#141217] shadow-[0_12px_24px_rgba(45,31,17,0.08)] disabled:opacity-30"
            >
              →
            </button>
          </div>

          <div className="mt-6 flex items-center justify-center gap-4">
            <button
              onClick={() => setSubmitted(true)}
              disabled={submitted || quizQuestions.length === 0}
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
          <div className="white-panel border border-red-200 bg-red-50 px-4 py-4 text-red-700">{error}</div>
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
            <h3 className="text-[28px] font-semibold tracking-[-0.04em] text-[#141217]">Bạn có chắc muốn xóa?</h3>
            <p className="mt-4 text-[15px] leading-7 text-[#5f5853]">
              Lộ trình <span className="font-semibold text-[#8c3451]">{displayGoal || subjectLabel}</span> sẽ bị xóa
              cùng các chương, bài học và câu hỏi được sinh riêng cho lộ trình này.
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


