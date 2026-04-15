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
import DesktopPageGrid from '../components/layout/DesktopPageGrid';
import StickyInsightRail from '../components/layout/StickyInsightRail';
import PDFViewer from '../components/PDFViewer';
import FeatureCallout from '../components/ui/FeatureCallout';
import PageHero from '../components/ui/PageHero';
import PanelHeader from '../components/ui/PanelHeader';
import SectionIntro from '../components/ui/SectionIntro';
import StatusPanel from '../components/ui/StatusPanel';
import ValueTile from '../components/ui/ValueTile';
import { useAuth } from '../contexts/AuthContext';
import { adaptiveService, learningPathService, pathRefinementService } from '../services';
import type { AdaptiveExplanationResponse } from '../types/adaptive';
import type {
  BloomLevel,
  LearningPath,
  LearningPathChapter,
  LearningPathLesson,
  LearningLevel,
  LessonCompletionStatus,
  LessonLockInfo,
  LessonAttemptStatistics,
  LessonProgressApiResponse,
  LessonQuestionGenerationResponse,
  LessonRecommendedChunks,
  LessonQuestion,
  LessonQuestions,
  LessonQuestionType,
  LessonStatus,
} from '../types/learningPath';
import type { PathRefinementAction } from '../types/pathRefinement';
import { SUBJECTS } from '../utils/subjects';

interface PathState {
  path?: LearningPath;
}

type ScreenMode = 'subject' | 'map' | 'lesson';
type LessonTab = 'lesson' | 'questions';
type QuizTransitionDirection = 'forward' | 'backward';

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
  targetCount: number | null;
  difficulty: LearningLevel;
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
  // eslint-disable-next-line no-unused-vars
  onSelect(lesson: LessonNode): void;
  // eslint-disable-next-line no-unused-vars
  onOpenLesson(lesson: LessonNode): void;
  // eslint-disable-next-line no-unused-vars
  onHoverLesson(lesson: LessonNode | null): void;
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
        pillClass: 'bg-amber-100 text-amber-700',
        accentClass: 'bg-amber-500',
      };
    default:
      return {
        label: 'Chưa mở',
        dot: '○',
        pillClass: 'bg-blue-50 text-blue-700',
        accentClass: 'bg-blue-400',
      };
  }
};

interface LessonBadgeMeta {
  key: string;
  label: string;
  className: string;
}

const applyLessonLocksToPath = (
  currentPath: LearningPath,
  lessonLocks: Record<string, LessonLockInfo>,
): LearningPath => {
  const mapLesson = (lesson: LearningPathLesson): LearningPathLesson => {
    const lockInfo = lessonLocks[lesson.lesson_id];
    return {
      ...lesson,
      is_locked: lockInfo?.is_locked ?? false,
      reason_locked: lockInfo?.reason ?? undefined,
      blocking_lesson_id: lockInfo?.blocking_lesson_id ?? null,
      blocking_concepts: lockInfo?.blocking_concepts ?? [],
      missing_prerequisite_concepts: lockInfo?.missing_prerequisite_concepts ?? [],
      prerequisite_mastery: lockInfo?.prerequisite_mastery ?? {},
      bridge_recommendations: lockInfo?.bridge_recommendations ?? [],
      mastery_threshold: lockInfo?.mastery_threshold ?? null,
    };
  };

  const nextChapters = (currentPath.curriculum?.length ? currentPath.curriculum : currentPath.chapters).map(
    (chapter) => ({
      ...chapter,
      lessons: chapter.lessons.map(mapLesson),
    }),
  );

  return {
    ...currentPath,
    chapters: nextChapters,
    curriculum: nextChapters,
  };
};

const getLessonBadges = (lesson?: LearningPathLesson | null): LessonBadgeMeta[] => {
  if (!lesson) {
    return [];
  }

  const badges: LessonBadgeMeta[] = [];
  const adaptationMetadata =
    lesson.adaptation_metadata && typeof lesson.adaptation_metadata === 'object'
      ? lesson.adaptation_metadata
      : {};
  const weakConcepts = Array.isArray(adaptationMetadata.weak_concepts)
    ? adaptationMetadata.weak_concepts
    : [];
  const suggestedMode =
    typeof adaptationMetadata.suggested_mode === 'string' ? adaptationMetadata.suggested_mode : '';

  if (lesson.is_locked) {
    badges.push({
      key: 'locked',
      label: 'Locked by prerequisite',
      className: 'bg-slate-100 text-slate-700',
    });
  }
  if (suggestedMode === 'reinforce_weaknesses' || weakConcepts.length > 0) {
    badges.push({
      key: 'review',
      label: 'Recommended review',
      className: 'bg-[#fff1f6] text-[#a94872]',
    });
  }
  if (lesson.refinement?.extra_practice || lesson.refinement?.bridge_required) {
    badges.push({
      key: 'reinforced',
      label: 'Reinforced by low performance',
      className: 'bg-[#f6e9ff] text-[#7b49a8]',
    });
  }

  return badges.slice(0, 3);
};

const getLessonWeakConceptLabels = (lesson?: LearningPathLesson | null) => {
  const adaptationMetadata =
    lesson?.adaptation_metadata && typeof lesson.adaptation_metadata === 'object'
      ? lesson.adaptation_metadata
      : {};
  const weakConcepts = Array.isArray(adaptationMetadata.weak_concepts)
    ? adaptationMetadata.weak_concepts
    : [];

  return weakConcepts
    .map((concept) => (typeof concept === 'string' ? concept.trim() : ''))
    .filter(Boolean)
    .slice(0, 4);
};

const isVirtualBridgeLesson = (lesson?: LearningPathLesson | null) =>
  Boolean(
    lesson &&
      lesson.lesson_kind === 'bridge' &&
      (String(lesson.lesson_id).startsWith('bridge_') ||
        Boolean((lesson.refinement as Record<string, unknown> | undefined)?.inserted_by_refinement)),
  );

const LearningMapNodeCard = ({ data }: NodeProps<MapLessonNodeData>) => {
  const { lesson, isSelected, isInPath, onSelect, onOpenLesson, onHoverLesson, accent } = data;
  const statusMeta = getLessonStatusMeta(lesson.status);
  const canOpenLesson = !lesson.is_locked;
  const lessonBadges = getLessonBadges(lesson);

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
        borderColor: lesson.is_locked
          ? '#f1b5bf'
          : isSelected
            ? accent.solid
            : isInPath
              ? accent.text
              : accent.border,
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
          {lessonBadges.length > 0 ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {lessonBadges.map((badge) => (
                <span
                  key={`${lesson.lesson_id}-${badge.key}`}
                  className={`rounded-full px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.14em] ${badge.className}`}
                >
                  {badge.label}
                </span>
              ))}
            </div>
          ) : null}
        </div>
      </div>

      <p className="line-clamp-2 min-h-[40px] text-[13px] leading-5 text-[#6a625d]">
        {lesson.summary?.trim() ||
          'Bài học này giúp bạn tiến thêm một bước trong lộ trình hiện tại.'}
      </p>

      <div className="mt-5 flex items-center justify-between gap-3">
        <span className="text-[12px] font-medium text-[#8c3451]/70">
          {lesson.is_locked ? 'Mở prerequisite' : lesson.status === 'complete' ? 'Hoàn thành' : 'Học tiếp'}
        </span>
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
      return 'Mở đầu';
    case 'explanation':
      return 'Giải thích';
    case 'worked_example':
      return 'Ví dụ';
    case 'misconception_fix':
      return 'Lỗi thường gặp';
    case 'summary':
      return 'Tóm tắt';
    case 'practice_hint':
      return 'Gợi ý thực hành';
    default:
      return 'Đoạn học liệu của lesson';
  }
};

const getInstructionRoleHint = (role?: string) => {
  switch ((role || '').toLowerCase()) {
    case 'introduction':
      return 'Nắm ý chính trước khi đi sâu vào chi tiết.';
    case 'explanation':
      return 'Đoạn giải thích trọng tâm cho lesson này.';
    case 'worked_example':
      return 'Xem ví dụ hoàn chỉnh để hiểu cách áp dụng.';
    case 'summary':
      return 'Tóm tắt nhanh trước khi chuyển sang quiz.';
    default:
      return 'Đoạn học liệu phù hợp nhất để đọc tiếp trong lesson này.';
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
  switch (questionType) {
    case 'multiple_choice':
      return 'Trắc nghiệm';
    case 'true_false':
      return 'Đúng / Sai';
    case 'short_answer':
      return 'Trả lời ngắn';
    default:
      return 'Câu hỏi';
  }
};

  const getFallbackStyleLabel = (style?: unknown) => {
    switch (String(style || '').toLowerCase()) {
      case 'describe_focus_mcq':
        return 'Mô tả khái niệm';
      case 'focus_from_description_mcq':
        return 'Nhận diện khái niệm';
      case 'fill_blank_mcq':
        return 'Điền khuyết';
      case 'complete_concept_mcq':
        return 'Hoàn thành khái niệm';
      case 'describe_focus_short':
        return 'Giải thích ngắn';
      case 'complete_statement_short':
        return 'Hoàn thành ý';
      case 'worked_example_short':
        return 'Ví dụ áp dụng';
      case 'true_false_statement':
        return 'Nhận định';
      default:
        return '';
    }
  };

  const isFallbackQuestion = (question: LessonQuestion) => {
    const generationSource = String(question.metadata?.generation_source || '').toLowerCase();
    const generationMode = String(question.metadata?.generation_mode || '').toLowerCase();
    return generationSource === 'local_fallback' || generationMode === 'local_fallback';
  };

const getBloomLevelLabel = (bloomLevel: BloomLevel) => {
  switch (bloomLevel) {
    case 'remember':
      return 'Ghi nhớ';
    case 'understand':
      return 'Hiểu';
    case 'apply':
      return 'Áp dụng';
    case 'analyze':
      return 'Phân tích';
    case 'evaluate':
      return 'Đánh giá';
    case 'create':
      return 'Sáng tạo';
    default:
      return bloomLevel;
  }
};

const getAutoQuestionTypes = (): LessonQuestionType[] => [
  'multiple_choice',
  'short_answer',
];

const getAutoBloomLevels = (difficulty: LearningLevel) => {
  switch (difficulty) {
    case 'advanced':
      return ['apply', 'analyze', 'understand'] as const;
    case 'intermediate':
      return ['understand', 'apply', 'analyze'] as const;
    case 'beginner':
    default:
      return ['remember', 'understand', 'apply'] as const;
  }
};

const getDifficultyLabel = (difficulty: LearningLevel) => {
  return DIFFICULTY_OPTIONS.find((item) => item.value === difficulty)?.label || difficulty;
};

const getCompletionStatusMeta = (status?: LessonCompletionStatus | null) => {
  switch (status) {
    case 'completed':
      return {
        title: 'Đạt chuẩn hoàn thành lesson',
        toneClass: 'border-emerald-200 bg-[#f6fdf8]',
        badgeClass: 'semantic-pill-green',
      };
    case 'retry_required':
      return {
        title: 'Cần học lại nền tảng trước khi tiếp tục',
        toneClass: 'border-red-200 bg-[#fff7f7]',
        badgeClass: 'semantic-pill-red',
      };
    case 'reinforce_required':
    default:
      return {
        title: 'Cần quiz củng cố trước khi qua bài mới',
        toneClass: 'border-amber-200 bg-[#fffaf2]',
        badgeClass: 'semantic-pill-yellow',
      };
  }
};

const getCompletionStatusLabel = (status?: LessonCompletionStatus | null) => {
  switch (status) {
    case 'completed':
      return 'Hoàn thành';
    case 'retry_required':
      return 'Cần học lại';
    case 'reinforce_required':
      return 'Cần củng cố';
    default:
      return '--';
  }
};

const getLessonPassConclusion = (status?: LessonCompletionStatus | null) => {
  switch (status) {
    case 'completed':
      return 'Kết luận: Đã hoàn thành lesson';
    case 'retry_required':
      return 'Kết luận: Chưa hoàn thành lesson, cần học lại';
    case 'reinforce_required':
      return 'Kết luận: Chưa hoàn thành lesson, cần củng cố thêm';
    default:
      return 'Kết luận: Chưa có đủ dữ liệu để đánh giá lesson';
  }
};

const getHistoricalLessonPassConclusion = (
  stats?: LessonAttemptStatistics | null,
) => {
  if (!stats || stats.total_attempts <= 0) {
    return 'Kết luận: Chưa có đủ dữ liệu để đánh giá lesson';
  }
  if (stats.passed_attempts > 0) {
    return 'Kết luận: Lesson đã từng được hoàn thành ở ít nhất một lượt quiz';
  }
  return 'Kết luận: Chưa có lượt quiz nào đạt đủ điều kiện hoàn thành lesson';
};

const getHistoricalCompletionBadge = (stats?: LessonAttemptStatistics | null) => {
  if (!stats || stats.total_attempts <= 0) {
    return {
      label: 'Chưa có dữ liệu',
      badgeClass: 'rounded-full bg-white px-3 py-1 text-[11px] font-semibold text-[#6f5260]',
    };
  }
  if (stats.passed_attempts > 0) {
    return {
      label: 'Đã từng hoàn thành',
      badgeClass: 'semantic-pill-green rounded-full px-3 py-1 text-[11px] font-semibold',
    };
  }
  return {
    label: 'Chưa có lượt đạt chuẩn',
    badgeClass: 'semantic-pill-yellow rounded-full px-3 py-1 text-[11px] font-semibold',
  };
};

const formatPercent = (value?: number | null) =>
  value == null || Number.isNaN(value) ? '--' : `${Math.round(value * 100)}%`;

const deriveBloomScore = (
  bloomScore?: number | null,
  bloomAccuracyByLevel?: Partial<Record<BloomLevel, number>>,
) => {
  if (typeof bloomScore === 'number' && !Number.isNaN(bloomScore)) {
    return bloomScore;
  }

  const values = Object.values(bloomAccuracyByLevel || {}).filter(
    (value): value is number => typeof value === 'number' && !Number.isNaN(value),
  );
  if (values.length === 0) {
    return null;
  }
  return values.reduce((sum, value) => sum + value, 0) / values.length;
};

const BLOOM_PASS_THRESHOLDS: Partial<Record<BloomLevel, number>> = {
  remember: 0.7,
  understand: 0.7,
  apply: 0.6,
};

const getLessonCompletionBlockers = ({
  completionStatus,
  masteryScore,
  bloomAccuracyByLevel,
  conceptCoverageRate,
  confidenceScore,
}: {
  completionStatus?: LessonCompletionStatus | null;
  masteryScore?: number | null;
  bloomAccuracyByLevel?: Partial<Record<BloomLevel, number>>;
  conceptCoverageRate?: number | null;
  confidenceScore?: number | null;
}) => {
  if (completionStatus === 'completed') {
    return [];
  }

  const blockers: string[] = [];
  const weakBloomLevels = (Object.entries(BLOOM_PASS_THRESHOLDS) as Array<[BloomLevel, number]>)
    .filter(([level, threshold]) => {
      const value = bloomAccuracyByLevel?.[level];
      return typeof value === 'number' && !Number.isNaN(value) && value < threshold;
    })
    .map(([level]) => getBloomLevelLabel(level));

  if (weakBloomLevels.length > 0) {
    blockers.push(`Bloom chưa đạt ở ${weakBloomLevels.join(', ')}`);
  }

  if (
    typeof conceptCoverageRate === 'number' &&
    !Number.isNaN(conceptCoverageRate) &&
    conceptCoverageRate < 0.7
  ) {
    blockers.push(
      `Concept mastery ${Math.round(conceptCoverageRate * 100)}%, cần tối thiểu 70%`,
    );
  }

  if (
    typeof confidenceScore === 'number' &&
    !Number.isNaN(confidenceScore) &&
    confidenceScore < 0.6
  ) {
    blockers.push(`Confidence ${Math.round(confidenceScore * 100)}%, cần tối thiểu 60%`);
  }

  if (typeof masteryScore === 'number' && !Number.isNaN(masteryScore) && masteryScore < 0.75) {
    blockers.push(`Mastery ${Math.round(masteryScore * 100)}%, chưa đạt ngưỡng hoàn thành 75%`);
  }

  return blockers;
};

const computeLocalBloomMetrics = (
  questions: LessonQuestion[],
  selectedAnswers: Record<string, string>,
) => {
  const buckets: Record<'remember' | 'understand' | 'apply' | 'analyze', boolean[]> = {
    remember: [],
    understand: [],
    apply: [],
    analyze: [],
  };

  questions.forEach((question) => {
    const level = question.bloom_level;
    if (!['remember', 'understand', 'apply', 'analyze'].includes(level)) {
      return;
    }
    buckets[level as 'remember' | 'understand' | 'apply' | 'analyze'].push(
      isQuestionAnsweredCorrectly(question, selectedAnswers[question.question_id]),
    );
  });

  const accuracyByLevel: Partial<Record<BloomLevel, number>> = {};
  (['remember', 'understand', 'apply', 'analyze'] as const).forEach((level) => {
    const attempts = buckets[level];
    if (attempts.length === 0) {
      return;
    }
    accuracyByLevel[level] =
      attempts.filter(Boolean).length / Math.max(1, attempts.length);
  });

  const weightedScore =
    (accuracyByLevel.remember ?? 0) * 0.25 +
    (accuracyByLevel.understand ?? 0) * 0.25 +
    (accuracyByLevel.apply ?? 0) * 0.3 +
    (accuracyByLevel.analyze ?? 0) * 0.2;

  return {
    accuracyByLevel,
    score:
      Object.keys(accuracyByLevel).length > 0
        ? Math.max(0, Math.min(1, weightedScore))
        : null,
  };
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
  const [lessonResourcesLoading, setLessonResourcesLoading] = useState(false);
  const [lessonResourcesError, setLessonResourcesError] = useState<string | null>(null);
  const [lessonQuestions, setLessonQuestions] = useState<LessonQuestions | null>(null);
  const [questionLoading, setQuestionLoading] = useState(false);
  const [questionGenerating, setQuestionGenerating] = useState(false);
  const [questionError, setQuestionError] = useState<string | null>(null);
  const [questionNotice, setQuestionNotice] = useState<string | null>(null);
  const [, setLessonLocks] = useState<Record<string, LessonLockInfo>>({});
  const [refinementActions, setRefinementActions] = useState<PathRefinementAction[]>([]);
  const [adaptiveExplanation, setAdaptiveExplanation] =
    useState<AdaptiveExplanationResponse | null>(null);
  const [, setAdaptiveExplanationError] = useState<string | null>(null);
  const [lastGenerationSummary, setLastGenerationSummary] =
    useState<LessonQuestionGenerationResponse | null>(null);
  const [lastLessonProgressResult, setLastLessonProgressResult] =
    useState<LessonProgressApiResponse | null>(null);
  const [quizSubmitting, setQuizSubmitting] = useState(false);
  const [, setLatestAdaptiveQuizPlan] = useState<{
    whyThisQuiz: string | null;
    policyVersion: string | null;
    policyBucket: string | null;
    questionTypes: LessonQuestionType[];
  } | null>(null);
  const [lessonAttemptStatistics, setLessonAttemptStatistics] =
    useState<LessonAttemptStatistics | null>(null);
  const [attemptStatisticsError, setAttemptStatisticsError] = useState<string | null>(null);
  const [questionConfig, setQuestionConfig] = useState<QuestionGenerationConfig>({
    targetCount: null,
    difficulty: 'beginner',
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
  const [quizTransitionDirection, setQuizTransitionDirection] =
    useState<QuizTransitionDirection>('forward');
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
  const quizSubmitInFlightRef = useRef(false);

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
  const learningPathOverview = useMemo(() => {
    const totalLessons = lessons.length;
    const completedLessons = lessons.filter((lesson) => lesson.status === 'complete').length;
    const inProgressLessons = lessons.filter((lesson) => lesson.status === 'in_progress').length;
    const notStartedLessons = Math.max(totalLessons - completedLessons - inProgressLessons, 0);
    const progressPercent =
      totalLessons > 0 ? Math.round((completedLessons / totalLessons) * 100) : 0;

    return {
      totalLessons,
      completedLessons,
      inProgressLessons,
      notStartedLessons,
      progressPercent,
    };
  }, [lessons]);
  const visibleRefinementActions = useMemo(
    () =>
      screenMode === 'subject'
        ? refinementActions
        : refinementActions.filter((action) =>
            selectedLesson?.lesson_id ? action.lesson_id === selectedLesson.lesson_id : true,
          ),
    [refinementActions, screenMode, selectedLesson?.lesson_id],
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

  const refreshPathSignals = useCallback(
    async (targetPathId: string, basePath?: LearningPath | null) => {
      if (!user?.user_id) {
        return;
      }

      try {
        const [lockResponse, refinementResponse] = await Promise.all([
          learningPathService.getLessonLocks(targetPathId).catch(() => null),
          pathRefinementService
            .getRefinementActions({
              user_id: user.user_id,
              path_id: targetPathId,
            })
            .catch(() => null),
        ]);

        if (lockResponse) {
          setLessonLocks(lockResponse.lesson_locks);
          setPath((previousPath) => {
            const sourcePath = previousPath?.path_id === targetPathId ? previousPath : basePath;
            return sourcePath ? applyLessonLocksToPath(sourcePath, lockResponse.lesson_locks) : previousPath;
          });
        }

        if (refinementResponse) {
          setRefinementActions(refinementResponse.items);
        }
      } catch (refreshError) {
        console.error('Failed to refresh lesson signals:', refreshError);
      }
    },
    [user?.user_id],
  );

  useEffect(() => {
    if (!path?.path_id) {
      setLessonLocks({});
      setRefinementActions([]);
      return;
    }
    void refreshPathSignals(path.path_id, path);
  }, [path?.path_id, refreshPathSignals]);

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
    setAdaptiveExplanation(null);
    setAdaptiveExplanationError(null);
    setLastGenerationSummary(null);
    setLastLessonProgressResult(null);
    setLatestAdaptiveQuizPlan(null);
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
      setLessonResourcesError(null);
      return;
    }
    if (isVirtualBridgeLesson(selectedLesson)) {
      setLessonRecommendedChunks(null);
      setLessonResourcesLoading(false);
      setLessonResourcesError(null);
      return;
    }

    const lessonId = selectedLesson.lesson_id;
    let active = true;

    const loadRecommendedChunks = async () => {
      try {
        if (active) {
          setLessonResourcesLoading(true);
          setLessonResourcesError(null);
        }
        const existing = await learningPathService.getLessonRecommendedChunks(lessonId);
        if (active) {
          setLessonRecommendedChunks(existing);
          setLessonResourcesError(null);
        }
      } catch {
        try {
          const generated = await learningPathService.recommendLessonChunks(lessonId, {
            max_chunks: 6,
            metadata: { source: 'learning_path_detail' },
          });
          if (active) {
            setLessonRecommendedChunks(generated);
            setLessonResourcesError(null);
          }
        } catch (error) {
          if (active) {
            setLessonRecommendedChunks(null);
            setLessonResourcesError(
              error instanceof Error
                ? error.message
                : 'Không thể tải học liệu gợi ý cho bài học này.',
            );
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
  }, [selectedLesson?.lesson_id, selectedLesson?.lesson_kind]);

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

    if (selectedLesson?.recommended_resources?.length) {
      return selectedLesson.recommended_resources.map((resource, index) => ({
        key: `${resource.resource_id || resource.url || resource.title || 'resource'}-${index}`,
        title: resource.title?.trim() || `Học liệu gợi ý ${index + 1}`,
        source: formatResourceSource(
          typeof resource.source === 'string'
            ? resource.source
            : typeof resource.type === 'string'
              ? resource.type
              : undefined,
        ),
        preview: `Nguồn gợi ý theo adaptive refinement cho ${cleanLessonTitle(selectedLesson.title)}.`,
        resourceId: resource.resource_id || undefined,
        resourceUrl: resource.url || undefined,
        actionLabel:
          (resource.source || '').toLowerCase() === 'pdf' ? 'Đọc tài liệu' : 'Mở tài liệu',
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
  }, [lessonRecommendedChunks, selectedLesson?.recommended_resources, selectedLesson?.resources, selectedLesson?.title]);

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

  const handleOpenAllLessonResources = useCallback(() => {
    const openedTargets = new Set<string>();

    currentLessonResources.forEach((resource) => {
      const targetUrl = buildLessonResourceOpenUrl(resource);
      if (!targetUrl || openedTargets.has(targetUrl)) {
        return;
      }
      openedTargets.add(targetUrl);
      window.open(targetUrl, '_blank', 'noopener,noreferrer');
    });
  }, [buildLessonResourceOpenUrl, currentLessonResources]);

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

  const retryLessonResources = useCallback(async () => {
    if (!selectedLesson?.lesson_id) {
      return;
    }
    if (isVirtualBridgeLesson(selectedLesson)) {
      setLessonResourcesError('Bridge lesson dùng tài nguyên đã gắn sẵn từ refinement, không cần truy hồi chunk mới.');
      return;
    }

    try {
      setLessonResourcesLoading(true);
      const result = await learningPathService.recommendLessonChunks(selectedLesson.lesson_id, {
        max_chunks: 6,
        metadata: { source: 'learning_path_detail_retry' },
      });
      setLessonRecommendedChunks(result);
      setLessonResourcesError(null);
    } catch (error) {
      setLessonResourcesError(
        error instanceof Error ? error.message : 'Không thể tải lại học liệu gợi ý.',
      );
    } finally {
      setLessonResourcesLoading(false);
    }
  }, [selectedLesson]);

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
    return lessonQuestions?.questions || [];
  }, [lessonQuestions]);

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
  const currentGenerationSummary = useMemo(() => {
    if (!selectedLesson?.lesson_id) {
      return null;
    }
    return lastGenerationSummary?.lesson_id === selectedLesson.lesson_id
      ? lastGenerationSummary
      : null;
  }, [lastGenerationSummary, selectedLesson?.lesson_id]);
  const currentLessonProgressResult = useMemo(() => {
    if (!selectedLesson?.lesson_id) {
      return null;
    }
    return lastLessonProgressResult?.lesson_id === selectedLesson.lesson_id
      ? lastLessonProgressResult
      : null;
  }, [lastLessonProgressResult, selectedLesson?.lesson_id]);
  const localBloomMetrics = useMemo(
    () => computeLocalBloomMetrics(quizQuestions, selectedAnswers),
    [quizQuestions, selectedAnswers],
  );
  const nextLessonAfterSelected = useMemo(() => {
    if (!selectedLesson) {
      return null;
    }

    const selectedIndex = lessons.findIndex((lesson) => lesson.lesson_id === selectedLesson.lesson_id);
    if (selectedIndex < 0) {
      return null;
    }

    return lessons[selectedIndex + 1] || null;
  }, [lessons, selectedLesson]);
  const quizAdaptiveFeedback = useMemo(() => {
    if (!submitted || !selectedLesson || quizSubmitting) {
      return null;
    }

    const progressResult = currentLessonProgressResult;
    const completionMeta = getCompletionStatusMeta(progressResult?.completion_status || null);
    const targetConfidence = progressResult?.completion_status === 'completed' ? 75 : 60;
    const needsRemediation = Boolean(
      progressResult?.reinforce_required || progressResult?.retry_required,
    );
    const resolvedBloomScore = deriveBloomScore(
      progressResult?.bloom_score ?? null,
      progressResult?.bloom_accuracy_by_level,
    );
    const hasUsableBackendBloomBreakdown = Boolean(
      progressResult?.bloom_accuracy_by_level &&
        Object.values(progressResult.bloom_accuracy_by_level).some(
          (value) => typeof value === 'number' && !Number.isNaN(value) && value > 0,
        ),
    );
    const resolvedBloomAccuracyByLevel =
      hasUsableBackendBloomBreakdown
        ? progressResult?.bloom_accuracy_by_level ?? {}
        : localBloomMetrics.accuracyByLevel;
    const displayedBloomScore =
      resolvedBloomScore != null && resolvedBloomScore > 0
        ? resolvedBloomScore
        : localBloomMetrics.score;
    const weakConcepts =
      progressResult?.weak_concepts?.length
        ? progressResult.weak_concepts
        : getLessonWeakConceptLabels(selectedLesson);
    const reason =
      typeof progressResult?.reason_locked === 'string'
        ? progressResult.reason_locked
        : typeof selectedLesson.adaptation_metadata?.['why_this_lesson_now'] === 'string'
        ? String(selectedLesson.adaptation_metadata['why_this_lesson_now'])
        : adaptiveExplanation?.adaptive_explanation ||
          adaptiveExplanation?.explanation ||
          'Kết quả quiz này sẽ được dùng để điều chỉnh cường độ ôn tập và bước học tiếp theo.';

    return {
      targetConfidence,
      needsRemediation,
      title: progressResult?.completion_status
        ? completionMeta.title
        : needsRemediation
          ? 'Cần củng cố thêm trước khi tiến tiếp'
          : 'Bạn đã sẵn sàng để đi tiếp',
      toneClass: progressResult?.completion_status
        ? completionMeta.toneClass
        : needsRemediation
          ? 'border-red-200 bg-[#fff7f7]'
          : 'border-emerald-200 bg-[#f6fdf8]',
      badgeClass: progressResult?.completion_status
        ? completionMeta.badgeClass
        : needsRemediation
          ? 'semantic-pill-red'
          : 'semantic-pill-green',
      nextStep: progressResult?.completion_status === 'completed'
        ? nextLessonAfterSelected
          ? `Lesson đã hoàn thành. Tiếp tục sang ${cleanLessonTitle(nextLessonAfterSelected.title)}.`
          : 'Lesson đã hoàn thành. Bạn có thể quay lại lộ trình hoặc tiếp tục phần tiếp theo.'
        : needsRemediation
        ? progressResult?.retry_required
          ? 'Học lại lesson và làm lại quiz từ mức dễ hơn.'
          : weakConcepts.length > 0
          ? `Ôn lại ${weakConcepts.slice(0, 2).join(' và ')} rồi làm lại quiz.`
          : 'Ôn lại các đoạn học liệu chính rồi làm lại quiz.'
        : nextLessonAfterSelected
          ? `Tiếp tục sang ${cleanLessonTitle(nextLessonAfterSelected.title)}.`
          : 'Bạn có thể tiếp tục phần tiếp theo trong lộ trình hiện tại.',
      reason,
      weakConcepts,
      masteryScore: progressResult?.mastery_score ?? null,
      completionStatus: progressResult?.completion_status ?? null,
      bloomScore: displayedBloomScore,
      conceptCoverageRate:
        progressResult?.concept_coverage_rate ?? progressResult?.concept_coverage_score ?? null,
      confidenceScore: progressResult?.confidence_score ?? null,
      bloomAccuracyByLevel: resolvedBloomAccuracyByLevel,
      completionBlockers: getLessonCompletionBlockers({
        completionStatus: progressResult?.completion_status ?? null,
        masteryScore: progressResult?.mastery_score ?? null,
        bloomAccuracyByLevel: resolvedBloomAccuracyByLevel,
        conceptCoverageRate:
          progressResult?.concept_coverage_rate ?? progressResult?.concept_coverage_score ?? null,
        confidenceScore: progressResult?.confidence_score ?? null,
      }),
    };
  }, [
    adaptiveExplanation,
    currentLessonProgressResult,
    localBloomMetrics.accuracyByLevel,
    localBloomMetrics.score,
    nextLessonAfterSelected,
    selectedLesson,
    submitted,
    quizSubmitting,
  ]);
  const displayedBestBloomScore = useMemo(() => {
    const historyScore =
      typeof lessonAttemptStatistics?.best_bloom_score === 'number' &&
      !Number.isNaN(lessonAttemptStatistics.best_bloom_score)
        ? lessonAttemptStatistics.best_bloom_score
        : null;
    const latestScore = deriveBloomScore(
      currentLessonProgressResult?.bloom_score ?? null,
      currentLessonProgressResult?.bloom_accuracy_by_level,
    );
    const localScore = localBloomMetrics.score;

    return [historyScore, latestScore, localScore].reduce<number | null>((best, value) => {
      if (typeof value !== 'number' || Number.isNaN(value)) {
        return best;
      }
      return best == null ? value : Math.max(best, value);
    }, null);
  }, [
    currentLessonProgressResult?.bloom_accuracy_by_level,
    currentLessonProgressResult?.bloom_score,
    lessonAttemptStatistics?.best_bloom_score,
    localBloomMetrics.score,
  ]);
  const displayedHistoricalAttemptMetrics = useMemo(() => {
    if (!lessonAttemptStatistics) {
      return {
        confidence: null,
        bloomScore: displayedBestBloomScore,
        masteryScore: null,
        completionStatus: null,
        attemptNumber: null,
      };
    }

    const resolvedReferenceBloomScore =
      typeof lessonAttemptStatistics.best_attempt_bloom_score === 'number' &&
      !Number.isNaN(lessonAttemptStatistics.best_attempt_bloom_score) &&
      lessonAttemptStatistics.best_attempt_bloom_score > 0
        ? lessonAttemptStatistics.best_attempt_bloom_score
        : displayedBestBloomScore;

    return {
      confidence:
        lessonAttemptStatistics.best_attempt_confidence ?? lessonAttemptStatistics.best_confidence,
      bloomScore: resolvedReferenceBloomScore,
      masteryScore:
        lessonAttemptStatistics.best_attempt_mastery_score ??
        lessonAttemptStatistics.best_mastery_score ??
        null,
      completionStatus:
        lessonAttemptStatistics.best_attempt_completion_status ??
        lessonAttemptStatistics.latest_completion_status ??
        null,
      attemptNumber: lessonAttemptStatistics.best_attempt_number ?? null,
    };
  }, [displayedBestBloomScore, lessonAttemptStatistics]);
  const historicalCompletionBadge = useMemo(
    () => getHistoricalCompletionBadge(lessonAttemptStatistics),
    [lessonAttemptStatistics],
  );

  const loadLessonAttemptStatistics = useCallback(async (lessonId: string) => {
    try {
      const stats = await learningPathService.getLessonAttemptStatistics(lessonId);
      setLessonAttemptStatistics(stats);
      setAttemptStatisticsError(null);
    } catch (error) {
      setLessonAttemptStatistics(null);
      setAttemptStatisticsError(
        error instanceof Error
          ? error.message
          : 'Không thể tải thống kê các lần làm quiz cho bài học này.',
      );
    }
  }, []);

  useEffect(() => {
    if (!selectedLesson?.lesson_id) {
      setLessonAttemptStatistics(null);
      setAttemptStatisticsError(null);
      return;
    }
    if (isVirtualBridgeLesson(selectedLesson)) {
      setLessonAttemptStatistics(null);
      setAttemptStatisticsError(null);
      return;
    }
    void loadLessonAttemptStatistics(selectedLesson.lesson_id);
  }, [loadLessonAttemptStatistics, selectedLesson?.lesson_id, selectedLesson?.lesson_kind]);

  useEffect(() => {
    if (!user?.user_id || !path?.path_id || !selectedLesson?.lesson_id) {
      setAdaptiveExplanation(null);
      setAdaptiveExplanationError(null);
      return;
    }
    if (isVirtualBridgeLesson(selectedLesson)) {
      setAdaptiveExplanation(null);
      setAdaptiveExplanationError(null);
      return;
    }

    let active = true;
    const loadAdaptiveExplanation = async () => {
      try {
        const explanation = await adaptiveService.getAdaptiveExplanation({
          user_id: user.user_id,
          path_id: path.path_id,
          lesson_id: selectedLesson.lesson_id,
        });
        if (!active) {
          return;
        }
        setAdaptiveExplanation(explanation);
        setAdaptiveExplanationError(null);
      } catch (adaptiveError) {
        if (!active) {
          return;
        }
        setAdaptiveExplanation(null);
        setAdaptiveExplanationError(
          adaptiveError instanceof Error
            ? adaptiveError.message
            : 'Không thể tải giải thích adaptive cho bài học này.',
        );
      }
    };

    void loadAdaptiveExplanation();

    return () => {
      active = false;
    };
  }, [path?.path_id, selectedLesson?.lesson_id, selectedLesson?.lesson_kind, user?.user_id]);

  const handleSubmitQuizAnswers = useCallback(() => {
    if (submitted || quizQuestions.length === 0 || answeredQuestionCount === 0 || quizSubmitInFlightRef.current) {
      return;
    }

    // Show grading state immediately in the UI.
    setSubmitted(true);
    setQuizSubmitting(true);
    setLastLessonProgressResult(null);
    quizSubmitInFlightRef.current = true;

    if (!selectedLesson?.lesson_id || !path?.path_id) {
      setQuizSubmitting(false);
      quizSubmitInFlightRef.current = false;
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

    const submit = async () => {
      try {
        const response = await learningPathService.updateLessonProgress({
          path_id: path.path_id,
          lesson_id: lessonId,
          status: 'in_progress',
          confidence: confidenceDecimal,
          questions_answered: questionsAnswered,
        });
        setLastLessonProgressResult(response);

        if (response.auto_completed && response.status === 'complete') {
          setPath((previousPath) => {
            if (!previousPath) {
              return previousPath;
            }
            return updateLessonStatusInPath(previousPath, lessonId, response.status);
          });
        }

        const latestPath = await learningPathService
          .getLearningPathById(path.path_id)
          .catch(() => null);
        if (latestPath) {
          setPath(latestPath);
          await refreshPathSignals(path.path_id, latestPath);
        } else {
          await refreshPathSignals(path.path_id);
        }

        void loadLessonAttemptStatistics(lessonId);
      } catch (err) {
        console.error('Failed to submit quiz confidence:', err);
        setQuestionNotice('Không thể đồng bộ kết quả quiz. Hãy nộp lại lượt này.');
        setSubmitted(false);
      } finally {
        setQuizSubmitting(false);
        quizSubmitInFlightRef.current = false;
      }
    };

    void submit();
  }, [
    answeredQuestionCount,
    loadLessonAttemptStatistics,
    path?.path_id,
    quizQuestions,
    setQuestionNotice,
    refreshPathSignals,
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
      if (selectedLesson?.lesson_id === lesson.lesson_id && !lesson.is_locked) {
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
      setLastLessonProgressResult(response);

      const latestPath = await learningPathService
        .getLearningPathById(path.path_id)
        .catch(() => null);

      if (latestPath) {
        setPath(latestPath);
        await refreshPathSignals(path.path_id, latestPath);
      } else {
        setPath((previousPath) => {
          if (!previousPath) {
            return previousPath;
          }
          return updateLessonStatusInPath(previousPath, lessonId, response.status);
        });
        await refreshPathSignals(path.path_id);
      }
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
      setLessonQuestions(response);
      setCurrentQuestionIndex(0);
      setSelectedAnswers({});
      setSubmitted(false);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Không thể tải câu hỏi ôn tập';
      setQuestionError(message);
      setLessonQuestions(null);
    } finally {
      setQuestionLoading(false);
    }
  };

  const generateLessonQuestions = async (overwrite = true) => {
    if (!selectedLesson) {
      return;
    }
    if (isVirtualBridgeLesson(selectedLesson)) {
      setLessonQuestions({
        lesson_id: selectedLesson.lesson_id,
        total: 0,
        questions: [],
      });
      setQuestionError('Bridge lesson chỉ hiển thị can thiệp thích nghi, không sinh quiz trực tiếp.');
      return;
    }

    try {
      setQuestionGenerating(true);
      setQuestionError(null);
      setQuestionNotice(null);
      const autoQuestionTypes = getAutoQuestionTypes();
      const autoBloomLevels = getAutoBloomLevels(questionConfig.difficulty);
      const adaptiveQuizResponse =
        path?.path_id && overwrite
          ? await learningPathService.getNextAdaptiveQuiz(selectedLesson.lesson_id, {
              path_id: path.path_id,
              target_count: questionConfig.targetCount ?? undefined,
            })
          : null;
      if (adaptiveQuizResponse) {
        setLatestAdaptiveQuizPlan({
          whyThisQuiz:
            adaptiveQuizResponse.generation_request.why_this_quiz ||
            adaptiveQuizResponse.next_action.why_this_quiz ||
            null,
          policyVersion:
            adaptiveQuizResponse.generation_request.policy_version ||
            adaptiveQuizResponse.next_action.policy_version ||
            null,
          policyBucket:
            adaptiveQuizResponse.generation_request.policy_bucket ||
            adaptiveQuizResponse.next_action.policy_bucket ||
            null,
          questionTypes:
            adaptiveQuizResponse.generation_request.question_types ||
            adaptiveQuizResponse.next_action.question_types ||
            [],
        });
      } else {
        setLatestAdaptiveQuizPlan(null);
      }
      const result = adaptiveQuizResponse
        ? adaptiveQuizResponse.generated
        : await learningPathService.generateLessonQuestions(selectedLesson.lesson_id, {
            target_count: questionConfig.targetCount ?? undefined,
            question_types: autoQuestionTypes,
            difficulty: questionConfig.difficulty,
            bloom_levels: [...autoBloomLevels],
            overwrite,
            metadata: {
              source: 'learning_path_quiz',
              path_id: path?.path_id,
              lesson_id: selectedLesson.lesson_id,
              config_target_count: questionConfig.targetCount ?? 'auto',
              config_question_types: autoQuestionTypes,
              config_bloom_levels: [...autoBloomLevels],
              config_difficulty: questionConfig.difficulty,
              config_mode: 'auto_balanced',
            },
          });
      setLastGenerationSummary(result);
      if (result.insufficient_data || result.generated_count === 0) {
        setLessonQuestions({
          lesson_id: selectedLesson.lesson_id,
          total: 0,
          questions: [],
        });
        setQuestionError(result.message || 'Hiện chưa thể tạo câu hỏi ôn tập cho bài học này.');
        return;
      }
      await loadLessonQuestions(selectedLesson.lesson_id);
      if (result.message) {
        setQuestionNotice(result.message);
      }
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
    if (isVirtualBridgeLesson(selectedLesson)) {
      setLessonQuestions({
        lesson_id: selectedLesson.lesson_id,
        total: 0,
        questions: [],
      });
      setQuestionError('Bridge lesson không có bộ câu hỏi riêng.');
      return;
    }
    if (
      lessonQuestions?.lesson_id === selectedLesson.lesson_id &&
      lessonQuestions.total > 0
    ) {
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

  const handlePrevQuestion = () => {
    if (currentQuestionIndex === 0) {
      return;
    }
    setQuizTransitionDirection('backward');
    setCurrentQuestionIndex((value) => Math.max(value - 1, 0));
  };

  const handleNextQuestion = () => {
    if (currentQuestionIndex >= quizQuestions.length - 1) {
      return;
    }
    setQuizTransitionDirection('forward');
    setCurrentQuestionIndex((value) => Math.min(value + 1, quizQuestions.length - 1));
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
    <PageHero
      className={screenMode === 'lesson' ? 'mb-8' : 'mb-10'}
      kicker={
        screenMode === 'subject'
          ? 'Tổng quan lộ trình'
          : screenMode === 'map'
            ? 'Bản đồ lộ trình'
            : 'Không gian lesson'
      }
      title={
        screenMode === 'subject'
          ? `Lộ trình chi tiết cho ${subjectLabel}`
          : screenMode === 'map'
            ? `Bản đồ học tập - ${subjectLabel}`
            : `Bài ${selectedLesson?.chapter_index}.${selectedLesson?.lesson_index} - ${cleanLessonTitle(selectedLesson?.title || 'Lesson')}`
      }
      titleClassName="text-[#141217]"
      description={
        screenMode === 'subject'
          ? `Theo dõi toàn bộ chương, lesson và mức độ hoàn thành cho ${displayGoal || subjectLabel}.`
          : screenMode === 'map'
            ? 'Quan sát mạch học hiện tại, tìm nhanh bài cần mở và điều hướng theo chương hoặc theo hành trình.'
            : selectedLesson?.summary?.trim() || 'Mở tài nguyên, làm quiz và ghi nhận tiến độ ngay trong cùng một màn hình.'
      }
      descriptionClassName="max-w-[860px]"
      actions={
        <>
          {screenMode !== 'subject' && (
            <button
              type="button"
              onClick={() => setScreenMode('subject')}
              className="theme-button-secondary px-5 py-3 text-[14px]"
            >
              Tổng quan path
            </button>
          )}
          {screenMode !== 'map' && lessons.length > 0 && (
            <button
              type="button"
              onClick={() => setScreenMode('map')}
              className="theme-button-secondary px-5 py-3 text-[14px]"
            >
              Xem bản đồ
            </button>
          )}
          {path?.path_id && (
            <button
              type="button"
              onClick={() => setPendingDeletePath(true)}
              className="theme-button-secondary px-5 py-3 text-[14px] text-[#8c3451]"
            >
              Xóa lộ trình
            </button>
          )}
        </>
      }
      actionsClassName="xl:justify-end"
      metrics={[
        {
          label: 'Tiến độ',
          value: `${learningPathOverview.progressPercent}%`,
          detail: `${learningPathOverview.completedLessons}/${learningPathOverview.totalLessons} lesson đã hoàn thành.`,
        },
        {
          label: 'Lesson đang học',
          value: learningPathOverview.inProgressLessons,
          detail: `${learningPathOverview.notStartedLessons} lesson chưa mở trong lộ trình hiện tại.`,
        },
        {
          label: 'Cấu trúc',
          value: chapters.length,
          detail: `Chương học với ${learningPathOverview.totalLessons} lesson được sắp theo trình tự.`,
        },
        {
          label: 'Trình độ',
          value: path?.level || 'beginner',
          detail: 'Độ khó hiện tại được dùng cho lesson, resource và quiz.',
        },
      ]}
    >
      {curriculumNotice && (
        <div className="info-banner border-amber-300 bg-amber-50 text-amber-900">
          {curriculumNotice}
        </div>
      )}
    </PageHero>
  );

  const renderLessonTabs = () => (
    <div className="mb-0 flex flex-wrap translate-y-[-1px] gap-3 pt-6">
      <button
        onClick={() => setLessonTab('lesson')}
        className={`h-[56px] w-full rounded-full border text-[16px] font-medium transition-colors sm:h-[64px] sm:min-w-[220px] sm:flex-1 sm:text-[17px] lg:flex-none ${
          lessonTab === 'lesson' ? 'bg-[#8c3451] text-white' : 'bg-white text-[#141217]'
        }`}
        style={{ borderColor: 'rgba(17,16,21,0.08)' }}
      >
        Bài học
      </button>
      <button
        onClick={() => void handleOpenQuestionsTab()}
        className={`h-[56px] w-full rounded-full border text-[16px] font-medium transition-colors sm:h-[64px] sm:min-w-[220px] sm:flex-1 sm:text-[17px] lg:flex-none ${
          lessonTab === 'questions' ? 'bg-[#8c3451] text-white' : 'bg-white text-[#141217]'
        }`}
        style={{ borderColor: 'rgba(17,16,21,0.08)' }}
      >
        Câu hỏi ôn tập
      </button>
    </div>
  );

  const renderRefinementTimeline = () => {
    const items = visibleRefinementActions.slice(0, 4);

    return (
      <div className="soft-panel mt-6 px-6 py-6">
        <PanelHeader
          kicker="Dòng thời gian adaptive"
          title="Lộ trình đã được điều chỉnh thế nào"
          description="Mỗi refinement đều ghi lại nguyên nhân, hệ quả và khuyến nghị tiếp theo để bạn nhìn thấy vòng thích nghi đang diễn ra."
        />

        <div className="mt-5 space-y-3">
          {items.length > 0 ? (
            items.map((action) => {
              const op = action.new_path_patch?.ops?.[0];
              return (
                <div
                  key={action.action_id}
                  className="rounded-[22px] border border-[#edd7e1] bg-white px-5 py-5"
                >
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <p className="text-[15px] font-semibold text-[#141217]">
                        {action.summary?.headline || 'Adaptive refinement'}
                      </p>
                      <p className="mt-1 text-[12px] text-[#8c3451]">
                        Lesson {action.lesson_id}
                      </p>
                    </div>
                    <span className="rounded-full bg-[#fff3f7] px-3 py-1 text-[11px] font-semibold text-[#8c3451]">
                      {action.created_at
                        ? new Intl.DateTimeFormat('vi-VN', {
                            day: '2-digit',
                            month: '2-digit',
                            hour: '2-digit',
                            minute: '2-digit',
                          }).format(new Date(action.created_at))
                        : 'Vừa cập nhật'}
                    </span>
                  </div>

                  <div className="mt-4 grid gap-3 md:grid-cols-3">
                    <div className="rounded-[18px] bg-[#fff8fb] px-4 py-4">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]/60">
                        Nguyên nhân
                      </p>
                      <p className="mt-2 text-[13px] leading-6 text-[#5f5853]">
                        {op?.reasons?.[0]?.trigger_reason || action.trigger_reason || 'auto_refinement'}
                      </p>
                    </div>
                    <div className="rounded-[18px] bg-[#fff8fb] px-4 py-4">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]/60">
                        Hệ quả
                      </p>
                      <p className="mt-2 text-[13px] leading-6 text-[#5f5853]">
                        {op?.effects?.[0]?.label || 'Lesson hiện tại được gia cố thêm để giảm rủi ro trượt nhịp.'}
                      </p>
                    </div>
                    <div className="rounded-[18px] bg-[#fff8fb] px-4 py-4">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]/60">
                        Khuyến nghị tiếp theo
                      </p>
                      <p className="mt-2 text-[13px] leading-6 text-[#5f5853]">
                        {op?.recommendations?.[0]?.label || 'Tiếp tục học theo nhịp đã điều chỉnh.'}
                      </p>
                    </div>
                  </div>
                </div>
              );
            })
          ) : (
            <StatusPanel
              className="shadow-none"
              tone="info"
              description="Chưa có refinement mới cho phạm vi đang xem. Khi hệ thống tự điều chỉnh lesson hoặc path, log sẽ xuất hiện ở đây."
            />
          )}
        </div>
      </div>
    );
  };

  const renderSubjectScreen = () => (
    <div>
      <div className="section-shell">
        <SectionIntro
          title={
            <>
              {subjectLabel}
              {displayGoal ? ` - ${displayGoal}` : ''}
            </>
          }
          description="Lộ trình học tập được cá nhân hóa theo môn học, mục tiêu và tiến độ hiện tại của bạn."
          actions={
            <span className="inline-flex shrink-0 items-center rounded-full bg-[#8c3451] px-4 py-2 text-[12px] font-medium text-white">
              {chapters.some((chapter) => getChapterStatusLabel(chapter) === 'Đang học')
                ? 'Đang học'
                : 'Chưa học'}
            </span>
          }
          actionsClassName="lg:self-start"
        />

        <div className="mt-6 grid gap-4 md:grid-cols-3">
          <ValueTile
            label="Trình độ"
            value={path?.level || 'beginner'}
            className="metric-card p-4 shadow-none"
            labelClassName="text-[12px] font-medium uppercase tracking-[0.18em] text-black/35"
            valueClassName="mt-2 text-[18px] font-semibold capitalize text-[#141217]"
          />
          <ValueTile
            label="Ngày tạo"
            value={formatDateTime(path?.generated_at)}
            className="metric-card p-4 shadow-none"
            labelClassName="text-[12px] font-medium uppercase tracking-[0.18em] text-black/35"
            valueClassName="mt-2 text-[18px] font-semibold text-[#141217]"
          />
          <ValueTile
            label="Số chương"
            value={`${chapters.length} chương`}
            className="metric-card p-4 shadow-none"
            labelClassName="text-[12px] font-medium uppercase tracking-[0.18em] text-black/35"
            valueClassName="mt-2 text-[18px] font-semibold text-[#141217]"
          />
        </div>
        <div className="mt-6 flex flex-wrap gap-3">
          <button
            onClick={() => setScreenMode('map')}
            className="theme-button-secondary gap-3 px-5 py-3 text-[14px]"
          >
            Xem lộ trình dạng map
            <span className="text-[16px] leading-none">→</span>
          </button>
          <button
            onClick={() => {
              const firstActiveLesson =
                lessons.find((lesson) => lesson.status === 'in_progress') || lessons[0];
              if (firstActiveLesson) {
                openLessonScreen(firstActiveLesson);
              }
            }}
            className="theme-button px-5 py-3 text-[14px]"
          >
            Mở lesson hiện tại
          </button>
        </div>
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

      {renderRefinementTimeline()}
    </div>
  );

  const renderMapScreen = () => {
    const selectedStatusMeta = getLessonStatusMeta(selectedLesson?.status);
    const mapResources = currentLessonResources.slice(0, 2).map((resource, index) => ({
      label: resource.preview,
      source: resource.source,
      display: resource.title || `Học liệu gợi ý ${index + 1}`,
    }));
    const canOpenSelectedLesson = !selectedLesson?.is_locked;
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
      <div className="section-shell overflow-hidden p-0">
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
          {selectedLesson ? (
            <div className="mt-4 flex flex-wrap gap-2">
              {getLessonBadges(selectedLesson).map((badge) => (
                <span
                  key={`selected-lesson-badge-${badge.key}`}
                  className={`rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] ${badge.className}`}
                >
                  {badge.label}
                </span>
              ))}
            </div>
          ) : null}
          <div className="mt-4 flex flex-wrap gap-2">
            <span className="rounded-full px-3 py-1 text-[11px] font-semibold semantic-pill-blue">
              {selectedStatusMeta.label}
            </span>
            {selectedLesson ? (
              <span className="rounded-full px-3 py-1 text-[11px] font-semibold semantic-pill-yellow">
                Bài tiếp theo
              </span>
            ) : null}
          </div>
          {selectedLesson?.adaptation_metadata ? (
            <details className="mt-4 rounded-[20px] border border-[#dbe8ff] bg-[#f5f9ff] px-4 py-4">
              <summary className="cursor-pointer list-none text-[11px] font-semibold uppercase tracking-[0.16em] text-[#2563eb]">
                Vì sao?
              </summary>
              <p className="mt-3 text-[13px] leading-5 text-[#334155]">
                {typeof selectedLesson.adaptation_metadata['why_this_lesson_now'] === 'string'
                  ? String(selectedLesson.adaptation_metadata['why_this_lesson_now'])
                  : adaptiveExplanation?.adaptive_explanation ||
                    adaptiveExplanation?.explanation ||
                    'Thứ tự node này đang được điều chỉnh theo prerequisite, mức độ vững kiến thức và tín hiệu học gần nhất.'}
              </p>
            </details>
          ) : null}
          {selectedLesson?.is_locked && selectedLesson.reason_locked ? (
            <p className="mt-3 text-[13px] leading-5 text-[#8c3451]">
              {selectedLesson.reason_locked}
            </p>
          ) : null}
        </div>

        <div className="grid gap-3 border-b border-black/5 px-6 py-5 sm:grid-cols-2">
          <ValueTile
            label="Tiến độ"
            value={selectedStatusMeta.label}
            className="metric-card p-4 shadow-none"
            labelClassName="text-[12px] uppercase tracking-[0.14em] text-[#8c3451]/55"
            valueClassName="mt-2 text-[18px] font-semibold text-[#141217]"
          />
          <ValueTile
            label="Cấp độ"
            value={path?.level || 'beginner'}
            className="metric-card p-4 shadow-none"
            labelClassName="text-[12px] uppercase tracking-[0.14em] text-[#8c3451]/55"
            valueClassName="mt-2 text-[18px] font-semibold capitalize text-[#141217]"
          />
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
            <div className="grid gap-3 sm:grid-cols-2">
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
        <DesktopPageGrid className={mapPresentationMode ? 'space-y-0' : ''}>
          <section className="section-shell overflow-visible p-0 xl:col-span-9">
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

              <div className="flex flex-wrap items-stretch gap-2 sm:items-center">
                <div className="flex w-full min-w-0 flex-1 items-center gap-2 rounded-full border border-[#f0d7e0] bg-white px-3 py-2 shadow-[0_10px_20px_rgba(114,62,83,0.06)] sm:min-w-[240px] sm:max-w-[360px]">
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
                  className="w-full rounded-full border border-[#f0d7e0] bg-white px-4 py-2 text-[13px] font-medium text-[#5c5550] transition hover:shadow-[0_10px_18px_rgba(137,78,99,0.08)] disabled:cursor-not-allowed disabled:opacity-40 sm:w-auto"
                >
                  Fit toàn bộ
                </button>

                <button
                  onClick={() => setIsMapControlsDrawerOpen(true)}
                  className="w-full rounded-full border border-[#f0d7e0] bg-white px-4 py-2 text-[13px] font-medium text-[#5c5550] transition hover:shadow-[0_10px_18px_rgba(137,78,99,0.08)] md:hidden sm:w-auto"
                >
                  Bộ lọc
                </button>

                {!mapPresentationMode && (
                  <button
                    onClick={() => setIsMapDetailDrawerOpen(true)}
                    className="w-full rounded-full border border-[#f0d7e0] bg-white px-4 py-2 text-[13px] font-medium text-[#5c5550] transition hover:shadow-[0_10px_18px_rgba(137,78,99,0.08)] sm:w-auto xl:hidden"
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
                      className="absolute left-0 top-[calc(100%+10px)] z-30 w-[min(304px,calc(100vw-48px))] rounded-[24px] border border-[#f0d7e0] bg-white p-3 shadow-[0_18px_36px_rgba(114,62,83,0.14)]"
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
                                ? 'Thoát chế độ trình bày'
                                : 'Chế độ trình bày'}
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
                  <StatusPanel
                    className="max-w-[420px]"
                    centered
                    title="Không có bài học nào khớp bộ lọc hiện tại"
                    description="Hãy thử đổi trạng thái, mở lại chương đang thu gọn hoặc xóa từ khóa tìm kiếm để xem nhiều bài học hơn."
                  />
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
                    <span className="h-3 w-3 rounded-full bg-amber-500"></span>
                    <span className="hidden sm:inline">Đang học</span>
                  </div>
                  <div className="flex items-center gap-2 text-[11px] font-medium text-[#6f6762] md:text-[12px]">
                    <span className="h-3 w-3 rounded-full bg-emerald-500"></span>
                    <span className="hidden sm:inline">Hoàn thành</span>
                  </div>
                  <div className="flex items-center gap-2 text-[11px] font-medium text-[#6f6762] md:text-[12px]">
                    <span className="h-3 w-3 rounded-full bg-blue-400"></span>
                    <span className="hidden sm:inline">Chưa mở</span>
                  </div>
                  <div className="hidden items-center gap-2 text-[11px] font-medium text-[#6f6762] md:flex">
                    <span className="h-3 w-3 rounded-full bg-red-400"></span>
                    <span>Blocked</span>
                  </div>
                </div>
              </div>
            </div>
          </section>

          {!mapPresentationMode && (
            <StickyInsightRail className="hidden xl:col-span-3 xl:block">
              {detailPanel}
            </StickyInsightRail>
          )}
        </DesktopPageGrid>

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
                      {mapPresentationMode ? 'Thoát chế độ trình bày' : 'Chế độ trình bày'}
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
      {renderLessonTabs()}

      <div className="soft-panel mt-6 px-6 pb-6 pt-6">
        <PanelHeader
          className="border-b border-black/5 pb-4"
          kicker="Học liệu gợi ý"
          description="Hệ thống đang ưu tiên đúng tài liệu và đúng trang liên quan nhất với lesson hiện tại để bạn đọc tiếp nhanh hơn."
          descriptionClassName="mt-2 text-[14px] leading-6 text-[#6a625d]"
          aside={
            lessonRecommendedChunks?.metadata?.selected_count ? (
              <>
                <span className="demo-pill">
                  {String(lessonRecommendedChunks.metadata.selected_count)} đoạn học liệu đã chọn
                </span>
                {currentLessonResources.some((resource) => buildLessonResourceOpenUrl(resource)) ? (
                  <button
                    type="button"
                    onClick={handleOpenAllLessonResources}
                    className="theme-button-secondary px-4 py-2 text-[12px]"
                  >
                    Mở tất cả học liệu
                  </button>
                ) : null}
              </>
            ) : null
          }
        />

        {selectedLesson ? (
          <div className="mt-4 flex flex-wrap gap-2">
            {getLessonBadges(selectedLesson).map((badge) => (
              <span
                key={`lesson-screen-badge-${badge.key}`}
                className={`rounded-full px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.14em] ${badge.className}`}
              >
                {badge.label}
              </span>
            ))}
          </div>
        ) : null}

        {selectedLesson?.adaptation_metadata ? (
          <FeatureCallout
            className="mt-5 rounded-[22px] border-[#efdfeb] bg-white shadow-[0_14px_30px_rgba(114,62,83,0.06)]"
            kicker="Vì sao là bài này"
            title={
              typeof selectedLesson.adaptation_metadata['why_this_lesson_now'] === 'string'
                ? String(selectedLesson.adaptation_metadata['why_this_lesson_now'])
                : 'Thứ tự bài học đang được điều chỉnh theo trạng thái học hiện tại của bạn.'
            }
            description={
              Array.isArray(selectedLesson.adaptation_metadata['priority_reasons']) &&
              selectedLesson.adaptation_metadata['priority_reasons'].length > 0
                ? selectedLesson.adaptation_metadata['priority_reasons']
                    .map((reason) => String(reason))
                    .join(' • ')
                : 'Path planner đang cân bằng mức vững kiến thức, concept yếu, nhịp học và quỹ thời gian cho bài này.'
            }
            badges={
              <>
                {typeof selectedLesson.adaptation_metadata['priority_score'] === 'number' ? (
                  <span className="rounded-full bg-white px-3 py-1 text-[11px] font-semibold text-[#8c3451]">
                    Ưu tiên {selectedLesson.adaptation_metadata['priority_score'].toFixed(2)}
                  </span>
                ) : null}
                {typeof selectedLesson.adaptation_metadata['refinement_action_mode'] === 'string' ? (
                  <span className="rounded-full bg-[#f7dfe8] px-3 py-1 text-[11px] font-semibold text-[#8c3451]">
                    {String(selectedLesson.adaptation_metadata['refinement_action_mode'])}
                  </span>
                ) : null}
              </>
            }
          />
        ) : null}

        {isVirtualBridgeLesson(selectedLesson) ? (
          <StatusPanel
            className="mt-5 rounded-[16px] px-4 py-4 shadow-none"
            tone="info"
            title="Bridge lesson đang được chèn vào lộ trình"
            description="Đây là bridge lesson do adaptive refinement chèn vào path để vá lỗ hổng tiên quyết trước khi quay lại bài chính."
          />
        ) : null}

        {lessonResourcesError ? (
          <StatusPanel
            className="mt-5 rounded-[16px] px-4 py-4 shadow-none"
            tone="error"
            title="Không thể tải học liệu gợi ý"
            description={lessonResourcesError}
            actions={
              selectedLesson ? (
                <button
                  type="button"
                  onClick={() => void retryLessonResources()}
                  className="theme-button px-5 py-3 text-[13px]"
                >
                  Thử tải lại học liệu
                </button>
              ) : undefined
            }
          />
        ) : null}

        {resolvedPinnedLessonResource ? (
          <FeatureCallout
            kicker="Tài liệu đã ghim"
            title={resolvedPinnedLessonResource.title}
            meta={
              <>
                {resolvedPinnedLessonResource.source}
                {resolvedPinnedLessonResource.pageNumber
                  ? ` • Quay lại từ trang ${resolvedPinnedLessonResource.pageNumber}`
                  : ''}
              </>
            }
            description="Tài liệu này được giữ lại theo lesson hiện tại để bạn quay lại đúng chỗ đang đọc sau mỗi lần rời trang."
            badges={
              <>
                <span className="rounded-full bg-white px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]">
                  Đọc tiếp nhanh
                </span>
                <span className="rounded-full bg-[#f7dfe8] px-3 py-1 text-[11px] font-semibold text-[#8c3451]">
                  Đã ghim
                </span>
              </>
            }
            actions={
              <>
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
              </>
            }
          />
        ) : resolvedCurrentReadingResource ? (
          <FeatureCallout
            kicker="Bạn đang đọc"
            title={
              <>
                {resolvedCurrentReadingResource.title}
                {resolvedCurrentReadingResource.pageNumber
                  ? ` • Trang ${resolvedCurrentReadingResource.pageNumber}`
                  : ''}
              </>
            }
            className="rounded-[22px] border-[#efdfeb] bg-white shadow-[0_14px_30px_rgba(114,62,83,0.06)]"
            titleClassName="text-[15px] font-medium tracking-normal"
            metaClassName="hidden"
            descriptionClassName="hidden"
            actions={
              <button
                type="button"
                onClick={() => handleTogglePinnedLessonResource(resolvedCurrentReadingResource)}
                className="theme-button-secondary px-5 py-3 text-[13px]"
              >
                Ghim để quay lại nhanh
              </button>
            }
          />
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
            {currentLessonResources.length === 0 ? (
              <div className="md:col-span-2 xl:col-span-3 2xl:col-span-4">
                <StatusPanel
                  className="rounded-[24px] px-6 py-8 shadow-none"
                  tone="info"
                  centered
                  title="Chưa có học liệu phù hợp cho bài này"
                  description="Bạn có thể tải lại danh sách gợi ý hoặc quay lại lesson sau khi hệ thống có thêm tín hiệu từ tiến độ và quiz."
                  actions={
                    selectedLesson ? (
                      <button
                        type="button"
                        onClick={() => void retryLessonResources()}
                        className="theme-button px-5 py-3 text-[13px]"
                      >
                        Tải lại học liệu
                      </button>
                    ) : undefined
                  }
                />
              </div>
            ) : currentLessonResources.map((resource) => {
              const theme = getLessonResourceTheme(resource.source);
              const canOpenResource = Boolean(
                (resource.source === 'PDF' && resource.resourceId) || resource.resourceUrl,
              );
              const isPinned = resolvedPinnedLessonResource?.key === resource.key;
              const isCurrentReading = resolvedCurrentReadingResource?.key === resource.key;

              return (
                <div
                  key={resource.key}
                  className={`interactive-panel flex min-h-[360px] flex-col rounded-[30px] border px-5 pb-5 pt-5 shadow-[0_18px_34px_rgba(114,62,83,0.06)] ${theme.frame}`}
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
                      {resource.instructionRole ? (
                        <p className="mt-2 text-[13px] leading-5 text-[#6a625d]">
                          {getInstructionRoleHint(resource.instructionRole)}
                        </p>
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

      {renderRefinementTimeline()}

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
    <div className="focus-quiz-card min-h-[667px] overflow-hidden px-6 pb-8 pt-0 md:px-8">
      {renderLessonTabs()}

      <div className="mt-6 grid gap-5">
        <div className="soft-panel px-6 py-6">
          <PanelHeader
            kicker="Khu vực quiz"
            title="Tạo bộ câu hỏi sát với lesson này"
          />

          <div className="mt-5 rounded-[24px] border border-[#efdfeb] bg-white px-5 py-5 shadow-[0_14px_30px_rgba(114,62,83,0.06)]">
            <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
              <div className="max-w-[720px]">
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]/55">
                  Thành tích tốt nhất
                </p>
                <h3 className="mt-3 text-[26px] font-semibold tracking-[-0.03em] text-[#141217]">
                  {lessonAttemptStatistics?.total_attempts
                    ? 'Kết quả tốt nhất của lesson'
                    : 'Lesson này chưa có lượt làm quiz'}
                </h3>
                <p className="mt-3 text-[16px] font-semibold text-[#141217]">
                  {getHistoricalLessonPassConclusion(lessonAttemptStatistics)}
                </p>
                <p className="mt-3 text-[14px] leading-6 text-[#6d5d66]">
                  {lessonAttemptStatistics?.total_attempts
                    ? displayedHistoricalAttemptMetrics.attemptNumber
                      ? `Các chỉ số bên dưới lấy từ lượt #${displayedHistoricalAttemptMetrics.attemptNumber}, là lượt tham chiếu tốt nhất của lesson.`
                      : 'Các chỉ số bên dưới lấy từ một lượt tham chiếu tốt nhất trong lịch sử quiz của lesson.'
                    : 'Sau khi có ít nhất một lần nộp quiz, hệ thống sẽ lưu confidence và Bloom tốt nhất của lesson tại đây.'}
                </p>
                {attemptStatisticsError ? (
                  <p className="mt-3 text-[12px] leading-5 text-[#8f6075]">
                    {attemptStatisticsError}
                  </p>
                ) : null}
              </div>
              <span className={historicalCompletionBadge.badgeClass}>
                {historicalCompletionBadge.label}
              </span>
            </div>

              <div className="mt-5 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
              <div className="rounded-[20px] border border-[#efdfeb] bg-[#fffafc] px-4 py-4">
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]/55">
                  Confidence lượt tham chiếu
                </p>
                <p className="mt-3 text-[24px] font-semibold tracking-[-0.03em] text-[#141217]">
                  {formatPercent(displayedHistoricalAttemptMetrics.confidence)}
                </p>
              </div>
              <div className="rounded-[20px] border border-[#efdfeb] bg-[#fffafc] px-4 py-4">
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]/55">
                  Bloom lượt tham chiếu
                </p>
                <p className="mt-3 text-[24px] font-semibold tracking-[-0.03em] text-[#141217]">
                  {formatPercent(displayedHistoricalAttemptMetrics.bloomScore)}
                </p>
              </div>
              <div className="rounded-[20px] border border-[#efdfeb] bg-[#fffafc] px-4 py-4">
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]/55">
                  Mastery lượt tham chiếu
                </p>
                <p className="mt-3 text-[24px] font-semibold tracking-[-0.03em] text-[#141217]">
                  {formatPercent(displayedHistoricalAttemptMetrics.masteryScore)}
                </p>
              </div>
              <div className="rounded-[20px] border border-[#efdfeb] bg-[#fffafc] px-4 py-4">
                <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]/55">
                  Lượt đạt chuẩn
                </p>
                <p className="mt-3 text-[24px] font-semibold tracking-[-0.03em] text-[#141217]">
                  {lessonAttemptStatistics?.total_attempts != null
                    ? `${lessonAttemptStatistics.passed_attempts}/${lessonAttemptStatistics.total_attempts}`
                    : '--'}
                </p>
                <p className="mt-2 text-[12px] leading-5 text-[#6d5d66]">
                  {lessonAttemptStatistics?.latest_completion_status
                    ? `Lượt gần nhất: ${getCompletionStatusLabel(lessonAttemptStatistics.latest_completion_status)}`
                    : 'Chưa có dữ liệu lịch sử'}
                </p>
              </div>
            </div>
          </div>

          <div className="mt-6 flex flex-wrap gap-3">
            <button
              type="button"
              onClick={() => void generateLessonQuestions(true)}
              disabled={questionGenerating}
              className="theme-button px-5 py-3 text-[14px] disabled:opacity-50"
            >
              {questionGenerating ? 'Đang tạo bộ câu hỏi...' : 'Sinh quiz adaptive mới'}
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

        <div className="hidden soft-panel px-6 py-6">
          <PanelHeader kicker="Tiến độ ôn tập" />
          <div className="mt-4 space-y-3">
            <ValueTile
              label="Đã trả lời"
              value={`${answeredQuestionCount}/${quizStats.total || currentGenerationSummary?.target_count || questionConfig.targetCount || '--'}`}
            />
            <ValueTile
              label="Độ tự tin"
              value={
                selectedLesson?.status === 'complete' &&
                lessonAttemptStatistics?.best_confidence != null
                  ? formatPercent(lessonAttemptStatistics.best_confidence)
                  : submitted
                    ? `${quizStats.confidence}%`
                    : '--'
              }
              hint={
                selectedLesson?.status === 'complete' &&
                lessonAttemptStatistics?.best_confidence != null
                  ? 'Điểm cao nhất'
                  : undefined
              }
            />
            <ValueTile
              label="Đúng / Sai"
              value={submitted ? `${quizStats.correct} đúng · ${quizStats.wrong} sai` : 'Chưa nộp bài'}
              valueClassName="mt-1 text-[20px] font-semibold tracking-[-0.03em] text-[#141217]"
            />
            <div className="rounded-[18px] bg-[linear-gradient(135deg,#fffafd_0%,#fdf2f6_100%)] px-4 py-4 text-[13px] leading-6 text-[#6a625d] shadow-[0_12px_24px_rgba(114,62,83,0.06)]">
              Bài này hiện có{' '}
              <span className="font-semibold text-[#8c3451]">
                {lessonRecommendedChunks?.recommended_chunks?.length || 0} đoạn học liệu
              </span>{' '}
              gợi ý để làm nguồn sinh câu hỏi.
            </div>
            {attemptStatisticsError ? (
              <StatusPanel
                className="rounded-[18px] px-4 py-4 shadow-none"
                tone="info"
                description={attemptStatisticsError}
              />
            ) : null}
          </div>
        </div>
      </div>

      {questionNotice && !questionError && (
        <StatusPanel
          className="mt-5 rounded-[18px] px-4 py-4 shadow-none"
          tone="info"
          title="Cập nhật từ quiz"
          description={questionNotice}
        />
      )}

      {questionLoading ? (
        <StatusPanel
          className="mt-6 rounded-[24px] py-12 shadow-none"
          tone="info"
          centered
          title="Đang chuẩn bị bộ câu hỏi"
          description="Hệ thống đang tải hoặc dựng lại câu hỏi ôn tập theo lesson hiện tại."
        />
      ) : questionError ? (
        <StatusPanel
          className="rounded-[18px] px-4 py-4 shadow-none"
          tone="error"
          title="Không thể tải câu hỏi ôn tập"
          description={questionError}
          actions={
            <button
              onClick={() => void generateLessonQuestions(true)}
              className="theme-button px-5 py-3 text-[14px]"
            >
              Tạo câu hỏi mới
            </button>
          }
        />
      ) : !currentQuestion ? (
        <StatusPanel
          className="mt-6 rounded-[24px] py-10 shadow-none"
          tone="info"
          centered
          title="Bài học này chưa có bộ câu hỏi"
          description="Tạo một bộ câu hỏi mới để kiểm tra nhanh mức hiểu bài ngay trong lesson này."
          actions={
            <button
              onClick={() => void generateLessonQuestions(true)}
              className="theme-button px-5 py-3 text-[14px]"
            >
              {questionGenerating ? 'Đang tạo...' : 'Tạo câu hỏi ôn tập'}
            </button>
          }
        />
      ) : (
        <>
          <div className="quiz-stage-shell mt-8">
            <div className="quiz-stage-header">
              <div>
                <p className="text-[13px] font-semibold uppercase tracking-[0.22em] text-[#9b3a5a]/65">
                  Câu hỏi ôn tập
                </p>
                <h2 className="mt-3 text-[28px] font-semibold tracking-[-0.04em] text-[#2a2a2a] sm:text-[34px]">
                  {cleanLessonTitle(selectedLesson?.title || 'Lesson')}
                </h2>
              </div>
              <span className="rounded-full border border-[#ebcfd8] bg-white px-4 py-2 text-[12px] font-semibold text-[#9b3a5a]">
                Bài {selectedLesson?.lesson_index || 1} / Chương {selectedLesson?.chapter_index || 1}
              </span>
            </div>

            <div className="quiz-timeline-row mt-6">
              <div className="quiz-timeline-track">
                {quizQuestions.map((question, index) => {
                  const isCompleted = index < currentQuestionIndex;
                  const isCurrent = index === currentQuestionIndex;

                  return (
                    <div key={`timeline-${question.question_id}`} className="quiz-timeline-step">
                      <span
                        className={`quiz-timeline-node ${
                          isCompleted
                            ? 'is-completed'
                            : isCurrent
                              ? 'is-current'
                              : 'is-upcoming'
                        }`}
                      />
                      {index < quizQuestions.length - 1 ? (
                        <span
                          className={`quiz-timeline-connector ${
                            index < currentQuestionIndex ? 'is-completed' : 'is-upcoming'
                          }`}
                        />
                      ) : null}
                    </div>
                  );
                })}
              </div>
              <p className="shrink-0 text-[14px] font-semibold text-[#6d5d66]">
                Câu {currentQuestionIndex + 1}/{quizQuestions.length}
              </p>
            </div>

            <div className="relative mt-8 flex items-center justify-center">
              <button
                onClick={handlePrevQuestion}
                disabled={currentQuestionIndex === 0}
                className="quiz-nav-button left-0 hidden md:flex"
                aria-label="Câu trước"
              >
                ←
              </button>

              <div className="relative w-full max-w-[860px] px-0 md:px-16">
                <div className="quiz-card-stack">
                  <div className="quiz-card-ghost quiz-card-ghost-back" />
                  <div className="quiz-card-ghost quiz-card-ghost-middle" />
                  <div
                    key={`${currentQuestion.question_id}-${currentQuestionIndex}-${quizTransitionDirection}`}
                    className={`quiz-card-surface ${
                      quizTransitionDirection === 'forward'
                        ? 'quiz-card-enter-forward'
                        : 'quiz-card-enter-backward'
                    }`}
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="rounded-full bg-[#f9e8ee] px-4 py-2 text-[12px] font-semibold text-[#9b3a5a]">
                        {getQuestionTypeLabel(currentQuestion.question_type)}
                      </span>
                      <span className="rounded-full border border-[#ebcfd8] bg-white px-4 py-2 text-[12px] font-semibold text-[#6d5d66]">
                        {getBloomLevelLabel(currentQuestion.bloom_level)}
                      </span>
                      <span className="rounded-full border border-[#ebcfd8] bg-white px-4 py-2 text-[12px] font-semibold text-[#6d5d66]">
                        {getDifficultyLabel(currentQuestion.difficulty)}
                      </span>
                      <span className="rounded-full border border-[#ebcfd8] bg-white px-4 py-2 text-[12px] font-semibold text-[#6d5d66]">
                        {getFallbackStyleLabel(currentQuestion.metadata?.fallback_style) || 'Nhận định'}
                      </span>
                      {isFallbackQuestion(currentQuestion) ? (
                        <span className="rounded-full border border-[#f2d4a8] bg-[#fff6e7] px-4 py-2 text-[12px] font-semibold text-[#8b5f2b]">
                          AI dự phòng
                        </span>
                      ) : null}
                    </div>

                    <div className="mt-8">
                      <p className="text-[15px] font-medium text-[#9b3a5a]/70">
                        Câu {currentQuestionIndex + 1}
                      </p>
                      <h3 className="mt-3 text-[24px] font-medium leading-[1.45] tracking-[-0.03em] text-[#2a2a2a] sm:text-[30px]">
                        {currentQuestion.question}
                      </h3>
                    </div>

                    {currentQuestion.question_type === 'short_answer' ? (
                      <div className="mt-8">
                        <textarea
                          value={selectedAnswers[currentQuestion.question_id] || ''}
                          onChange={(event) =>
                            handleSelectAnswer(currentQuestion.question_id, event.target.value)
                          }
                          disabled={submitted}
                          placeholder="Nhập câu trả lời ngắn..."
                          className="min-h-[150px] w-full rounded-[24px] border border-[#ebcfd8] bg-white px-5 py-4 text-[16px] text-[#2a2a2a] outline-none transition focus:border-[#9b3a5a]"
                        />
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
                              disabled={submitted}
                              className={`quiz-option-pill ${
                                picked ? 'is-selected' : ''
                              } ${isCorrect ? 'is-correct' : ''} ${isWrong ? 'is-wrong' : ''}`}
                            >
                              <span className="quiz-option-label">{label}</span>
                              <span className="text-[16px] font-medium text-[#2a2a2a]">
                                {getQuestionChoiceLabel(choice)}
                              </span>
                            </button>
                          );
                        })}
                      </div>
                    )}

                    {submitted ? (
                      <div className="mt-8 rounded-[24px] border border-[#ebcfd8] bg-[#fffafc] px-5 py-5 text-[#2a2a2a]">
                        <div className="flex flex-wrap items-center gap-2">
                          <span
                            className={`rounded-full px-3 py-1 text-[12px] font-semibold ${
                              isQuestionAnsweredCorrectly(
                                currentQuestion,
                                selectedAnswers[currentQuestion.question_id],
                              )
                                ? 'semantic-pill-green'
                                : 'semantic-pill-red'
                            }`}
                          >
                            {isQuestionAnsweredCorrectly(
                              currentQuestion,
                              selectedAnswers[currentQuestion.question_id],
                            )
                              ? 'Đúng'
                              : 'Chưa đúng'}
                          </span>
                          <span className="text-[14px] font-medium text-[#6d5d66]">
                            Đáp án: {getQuestionChoiceLabel(currentQuestion.correct_answer)}
                          </span>
                        </div>
                        <details className="mt-4 text-[14px] text-[#5f5954]">
                          <summary className="cursor-pointer list-none font-semibold text-[#9b3a5a]">
                            Xem giải thích
                          </summary>
                          {currentQuestion.question_type === 'short_answer' ? (
                            <p className="mt-3">
                              Bạn trả lời: {selectedAnswers[currentQuestion.question_id] || 'Chưa trả lời'}
                            </p>
                          ) : null}
                          <p className="mt-3">
                            {currentQuestion.explanation || 'Chưa có giải thích chi tiết.'}
                          </p>
                          {currentQuestionSources.length > 0 ? (
                            <div className="mt-4 flex flex-wrap gap-2">
                              {currentQuestionSources.map((item) => (
                                <span
                                  key={`question-source-${item.chunk_id}`}
                                  className="rounded-full border border-[#ebcfd8] bg-white px-3 py-1 text-[12px] font-medium text-[#9b3a5a]"
                                >
                                  {item.page_number
                                    ? `${item.resource_title || 'PDF'} · trang ${item.page_number}`
                                    : item.resource_title || `Đoạn học liệu ${item.chunk_index + 1}`}
                                </span>
                              ))}
                            </div>
                          ) : null}
                        </details>
                      </div>
                    ) : null}
                  </div>
                </div>
              </div>

              <button
                onClick={handleNextQuestion}
                disabled={currentQuestionIndex >= quizQuestions.length - 1}
                className="quiz-nav-button right-0 hidden md:flex"
                aria-label="Câu tiếp theo"
              >
                →
              </button>
            </div>

            <div className="mt-5 flex justify-center gap-3 md:hidden">
              <button
                onClick={handlePrevQuestion}
                disabled={currentQuestionIndex === 0}
                className="quiz-nav-button relative left-auto right-auto flex"
                aria-label="Câu trước"
              >
                ←
              </button>
              <button
                onClick={handleNextQuestion}
                disabled={currentQuestionIndex >= quizQuestions.length - 1}
                className="quiz-nav-button relative left-auto right-auto flex"
                aria-label="Câu tiếp theo"
              >
                →
              </button>
            </div>
          </div>

          <div className="mt-6 flex flex-wrap items-center justify-center gap-4">
            <button
              type="button"
              onClick={() => {
                setSelectedAnswers({});
                setSubmitted(false);
                setQuizTransitionDirection('forward');
                setCurrentQuestionIndex(0);
              }}
              className="theme-button-secondary px-8 py-3 text-[15px] font-bold"
            >
              Làm lại lượt này
            </button>
            <button
              onClick={handleSubmitQuizAnswers}
              disabled={
                submitted || quizSubmitting || quizQuestions.length === 0 || answeredQuestionCount === 0
              }
              className="theme-button px-12 py-3 text-[15px] font-bold disabled:opacity-50"
            >
              Nộp bài
            </button>
          </div>

          {quizSubmitting ? (
            <p className="mt-4 text-center text-[13px] font-medium text-[#8c3451]">
              Đang chấm kết quả và đồng bộ trạng thái lesson...
            </p>
          ) : null}

          {quizAdaptiveFeedback ? (
            <div className={`mt-6 rounded-[24px] border px-5 py-5 ${quizAdaptiveFeedback.toneClass}`}>
              <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
                <div className="max-w-[720px]">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className={`rounded-full px-3 py-1 text-[11px] font-semibold ${quizAdaptiveFeedback.badgeClass}`}>
                      {quizAdaptiveFeedback.completionStatus
                        ? getCompletionStatusLabel(quizAdaptiveFeedback.completionStatus)
                        : `${quizStats.confidence}% vs target ${quizAdaptiveFeedback.targetConfidence}%`}
                    </span>
                    <span className="rounded-full bg-white px-3 py-1 text-[11px] font-semibold text-[#6f5260]">
                      {quizStats.correct}/{quizStats.total} đúng
                    </span>
                    {quizAdaptiveFeedback.masteryScore != null ? (
                      <span className="rounded-full bg-white px-3 py-1 text-[11px] font-semibold text-[#6f5260]">
                        Mastery {formatPercent(quizAdaptiveFeedback.masteryScore)}
                      </span>
                    ) : null}
                  </div>
                  <h3 className="mt-3 text-[20px] font-semibold tracking-[-0.03em] text-[#141217]">
                    {quizAdaptiveFeedback.title}
                  </h3>
                  <p className="mt-3 text-[16px] font-semibold text-[#141217]">
                    {getLessonPassConclusion(quizAdaptiveFeedback.completionStatus)}
                  </p>
                  <p className="mt-3 text-[14px] font-medium text-[#141217]">
                    {quizAdaptiveFeedback.nextStep}
                  </p>
                  {quizAdaptiveFeedback.completionBlockers.length > 0 ? (
                    <div className="mt-3 rounded-[16px] bg-white/70 px-4 py-3">
                      <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]/55">
                        Chưa hoàn thành vì
                      </p>
                      <div className="mt-2 flex flex-wrap gap-2">
                        {quizAdaptiveFeedback.completionBlockers.map((blocker) => (
                          <span
                            key={blocker}
                            className="rounded-full border border-[#efcfda] bg-white px-3 py-1 text-[12px] font-medium text-[#8c3451]"
                          >
                            {blocker}
                          </span>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  {(quizAdaptiveFeedback.bloomScore != null ||
                    quizAdaptiveFeedback.conceptCoverageRate != null ||
                    quizAdaptiveFeedback.confidenceScore != null) && (
                    <div className="mt-4 grid gap-3 sm:grid-cols-3">
                      <div className="rounded-[18px] bg-white/80 px-4 py-3">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]/55">
                          Bloom
                        </p>
                        <p className="mt-2 text-[18px] font-semibold text-[#141217]">
                          {formatPercent(quizAdaptiveFeedback.bloomScore)}
                        </p>
                      </div>
                      <div className="rounded-[18px] bg-white/80 px-4 py-3">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]/55">
                          Concept mastery
                        </p>
                        <p className="mt-2 text-[18px] font-semibold text-[#141217]">
                          {formatPercent(quizAdaptiveFeedback.conceptCoverageRate)}
                        </p>
                      </div>
                      <div className="rounded-[18px] bg-white/80 px-4 py-3">
                        <p className="text-[11px] font-semibold uppercase tracking-[0.16em] text-[#8c3451]/55">
                          Confidence
                        </p>
                        <p className="mt-2 text-[18px] font-semibold text-[#141217]">
                          {formatPercent(quizAdaptiveFeedback.confidenceScore)}
                        </p>
                      </div>
                    </div>
                  )}
                </div>

                <div className="flex w-full flex-col gap-3 lg:w-[260px]">
                  {quizAdaptiveFeedback.completionStatus === 'completed' ? (
                    <>
                      <button
                        type="button"
                        onClick={() =>
                          nextLessonAfterSelected
                            ? openLessonScreen(nextLessonAfterSelected)
                            : navigate('/learning-path')
                        }
                        className="theme-button w-full justify-center"
                      >
                        {nextLessonAfterSelected ? 'Sang bài tiếp theo' : 'Xem lại lộ trình'}
                      </button>
                      <button
                        type="button"
                        onClick={() => setLessonTab('lesson')}
                        className="theme-button-secondary w-full justify-center"
                      >
                        Xem lại bài học
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        onClick={() => setLessonTab('lesson')}
                        className="theme-button-secondary w-full justify-center"
                      >
                        Ôn lại bài học
                      </button>
                      {quizAdaptiveFeedback.needsRemediation ? (
                        <button
                          type="button"
                          onClick={() =>
                            navigate(
                              `/resources?q=${encodeURIComponent(cleanLessonTitle(selectedLesson?.title || ''))}`,
                            )
                          }
                          className="theme-button w-full justify-center"
                        >
                          Mở tài nguyên bổ trợ
                        </button>
                      ) : nextLessonAfterSelected ? (
                        <button
                          type="button"
                          onClick={() => openLessonScreen(nextLessonAfterSelected)}
                          className="theme-button w-full justify-center"
                        >
                          Sang bài tiếp theo
                        </button>
                      ) : (
                        <button
                          type="button"
                          onClick={() => navigate('/learning-path')}
                          className="theme-button w-full justify-center"
                        >
                          Xem lại lộ trình
                        </button>
                      )}
                    </>
                  )}
                </div>
              </div>
            </div>
          ) : null}
        </>
      )}
    </div>
  );

  const renderLessonScreen = () =>
    lessonTab === 'lesson' ? (
      <DesktopPageGrid>
        <section className="xl:col-span-12">{renderLessonResources()}</section>
      </DesktopPageGrid>
    ) : (
      <div className="page-shell">{renderQuestionScreen()}</div>
    );

  return (
    <DashboardLayout>
      <div className="min-h-[calc(100vh-110px)] px-2 py-3 md:px-4 md:py-5">
        {loading ? (
          <div className="white-panel flex min-h-[440px] items-center justify-center px-6 py-10">
            <div className="max-w-[420px] text-center">
              <div className="mx-auto mb-5 flex h-14 w-14 items-center justify-center rounded-full bg-[#fff1f6] shadow-[0_14px_28px_rgba(140,52,81,0.12)]">
                <div className="h-7 w-7 animate-spin rounded-full border-b-2 border-[#8c3451]" />
              </div>
              <p className="text-[22px] font-semibold tracking-[-0.03em] text-[#8c3451]">
                Đang tải chi tiết lộ trình
              </p>
              <p className="mt-3 text-[14px] leading-7 text-[#645d58]">
                Hệ thống đang dựng lại cấu trúc chương, bài học và tín hiệu thích nghi cho lộ trình này.
              </p>
            </div>
          </div>
        ) : error ? (
          <div className="white-panel flex min-h-[440px] items-center justify-center px-6 py-10">
            <div className="max-w-[520px] text-center">
              <StatusPanel
                className="rounded-[24px] px-5 py-5 shadow-none"
                tone="error"
                centered
                title="Không thể tải lộ trình"
                description={error}
              />
              <div className="mt-5 flex flex-wrap justify-center gap-3">
                <button
                  type="button"
                  onClick={() => navigate(0)}
                  className="theme-button px-6 py-3"
                >
                  Thử tải lại
                </button>
                <button
                  type="button"
                  onClick={() => navigate('/learning-path')}
                  className="theme-button-secondary px-6 py-3"
                >
                  Quay lại danh sách lộ trình
                </button>
              </div>
            </div>
          </div>
        ) : (
          <div className="page-shell desktop-1440-learning-path-detail">
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
