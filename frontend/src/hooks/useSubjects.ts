import { useCallback, useEffect, useState } from 'react';
import { learningPathService } from '../services/learningPathService';
import {
  FALLBACK_SUBJECTS,
  sanitizeSubjectOptions,
  type SubjectOption,
} from '../utils/subjects';

const SAFE_FALLBACK_SUBJECTS = sanitizeSubjectOptions(FALLBACK_SUBJECTS);

export const useSubjects = () => {
  const [subjects, setSubjects] = useState<SubjectOption[]>(SAFE_FALLBACK_SUBJECTS);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);
      const items = await learningPathService.getSubjects();
      const normalizedItems = sanitizeSubjectOptions(items);
      setSubjects(normalizedItems.length > 0 ? normalizedItems : SAFE_FALLBACK_SUBJECTS);
    } catch (err) {
      setSubjects(SAFE_FALLBACK_SUBJECTS);
      setError(err instanceof Error ? err.message : 'Không thể tải danh sách môn học');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return {
    subjects,
    loading,
    error,
    refresh,
  };
};
