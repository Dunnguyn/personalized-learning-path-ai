export interface SubjectOption {
  id: string;
  label: string;
  goal: string;
  slug?: string;
  description?: string;
  level?: string;
}

const MONGO_OBJECT_ID_RE = /^[a-f0-9]{24}$/i;

export const FALLBACK_SUBJECTS: SubjectOption[] = [
  {
    id: 'python',
    slug: 'python',
    label: 'Lập trình Python',
    goal: 'Học lập trình Python',
  },
  {
    id: 'cpp',
    slug: 'cpp',
    label: 'Lập trình C++',
    goal: 'Học lập trình C++',
  },
  {
    id: 'csharp',
    slug: 'csharp',
    label: 'Lập trình C#',
    goal: 'Học lập trình C#',
  },
  {
    id: 'java',
    slug: 'java',
    label: 'Lập trình Java',
    goal: 'Học lập trình Java',
  },
  {
    id: 'web',
    slug: 'web',
    label: 'Phát triển Web',
    goal: 'Học phát triển Web',
  },
];

export const SUBJECTS = FALLBACK_SUBJECTS;

const normalizeLookupText = (value?: string | null) =>
  String(value || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();

const getSafeText = (value: unknown) => (typeof value === 'string' ? value.trim() : '');

const toSlug = (value: string) => normalizeLookupText(value).replace(/\s+/g, '-');

export const isObjectIdLike = (value?: string | null) =>
  MONGO_OBJECT_ID_RE.test(getSafeText(value));

const buildBaseGoal = (label: string, description?: string) => {
  const normalizedDescription = getSafeText(description);
  if (/^học\s+/i.test(normalizedDescription)) {
    return normalizedDescription;
  }

  if (/^học\s+/i.test(label)) {
    return label;
  }

  return `Học ${label}`;
};

export const normalizeSubjectOption = (value: Record<string, unknown>): SubjectOption | null => {
  const rawTitle = getSafeText(value.title);
  const rawSlug = getSafeText(value.slug);
  const rawTopic = getSafeText(value.topic);
  const rawDescription = getSafeText(value.description);
  const rawLevel = getSafeText(value.level);
  const rawSubjectId = getSafeText(value.subject_id);

  const id = rawSubjectId || rawSlug || toSlug(rawTitle || rawTopic);
  if (!id) {
    return null;
  }

  const labelCandidates = [rawTitle, rawSlug, rawTopic].filter(Boolean);
  const label = labelCandidates.find((candidate) => !isObjectIdLike(candidate)) || '';
  if (!label) {
    return null;
  }

  return {
    id,
    slug: rawSlug || undefined,
    label,
    goal: buildBaseGoal(label, rawDescription),
    description: rawDescription || undefined,
    level: rawLevel || undefined,
  };
};

export const sanitizeSubjectOptions = (subjects: SubjectOption[]) => {
  const deduped = new Map<string, SubjectOption>();

  subjects.forEach((subject) => {
    if (!subject?.id || !subject?.label || isObjectIdLike(subject.label)) {
      return;
    }

    const key = normalizeLookupText(subject.slug || subject.label || subject.id);
    if (!deduped.has(key)) {
      deduped.set(key, subject);
    }
  });

  return Array.from(deduped.values());
};

export const getSubjectSuggestionKey = (subject?: SubjectOption | null) =>
  (subject?.slug || subject?.id || '').trim().toLowerCase();

export const findSubjectById = (subjects: SubjectOption[], subjectId?: string | null) => {
  const normalizedSubjectId = getSafeText(subjectId);
  if (!normalizedSubjectId) {
    return null;
  }

  return (
    subjects.find((subject) => subject.id === normalizedSubjectId) ||
    subjects.find((subject) => subject.slug === normalizedSubjectId) ||
    null
  );
};

export const getSubjectLabel = (
  subjects: SubjectOption[],
  subjectId?: string | null,
  fallback = 'Tên môn học',
) => findSubjectById(subjects, subjectId)?.label || fallback;

export const buildSubjectGoal = (
  subjects: SubjectOption[],
  subjectId: string,
  goalDetail: string,
) => {
  const subject = findSubjectById(subjects, subjectId);
  const baseGoal = subject?.goal?.trim() ?? '';
  const detail = goalDetail.trim();

  if (!baseGoal && !detail) {
    return '';
  }
  if (!baseGoal) {
    return detail;
  }
  if (!detail) {
    return baseGoal;
  }

  return `${baseGoal} - ${detail}`;
};

export const stripSubjectPrefixFromGoal = (
  subjects: SubjectOption[],
  subjectId?: string | null,
  goal?: string | null,
) => {
  const rawGoal = getSafeText(goal);
  if (!rawGoal) {
    return '';
  }

  const subject = findSubjectById(subjects, subjectId);
  const prefixes = [subject?.label, subject?.goal].filter(Boolean) as string[];
  let normalizedGoal = rawGoal;

  prefixes.forEach((prefix) => {
    const escapedPrefix = prefix.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
    normalizedGoal = normalizedGoal
      .replace(new RegExp(`^${escapedPrefix}\\s*-?\\s*`, 'i'), '')
      .trim();
  });

  return normalizedGoal || rawGoal;
};

export const matchSubjectByGoalPrefix = (subjects: SubjectOption[], goal?: string | null) => {
  const normalizedGoal = normalizeLookupText(goal);
  if (!normalizedGoal) {
    return null;
  }

  return (
    subjects.find((subject) => {
      const normalizedLabel = normalizeLookupText(subject.label);
      const normalizedSubjectGoal = normalizeLookupText(subject.goal);
      return (
        (normalizedSubjectGoal && normalizedGoal.startsWith(normalizedSubjectGoal)) ||
        (normalizedLabel && normalizedGoal.startsWith(normalizedLabel))
      );
    }) || null
  );
};
