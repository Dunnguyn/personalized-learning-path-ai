import { FormEvent, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import DashboardLayout from '../components/layout/DashboardLayout';
import { useAuth } from '../contexts/AuthContext';
import { learningPathService } from '../services/learningPathService';
import type { LessonQuestionBankDetail, LessonQuestionBankSummary } from '../services/learningPathService';

export default function QuestionBankManager() {
  const { user } = useAuth();
  const navigate = useNavigate();

  const [loading, setLoading] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [lessonId, setLessonId] = useState('');
  const [banks, setBanks] = useState<LessonQuestionBankSummary[]>([]);
  const [selectedBank, setSelectedBank] = useState<LessonQuestionBankDetail | null>(null);

  const loadBanks = async () => {
    try {
      setLoading(true);
      const response = await learningPathService.listLessonQuestionBanks(30);
      setBanks(response.items || []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể tải danh sách question bank');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (!user) {
      navigate('/login');
      return;
    }
    loadBanks();
  }, [user, navigate]);

  const handleFetchBank = async (targetLessonId: string) => {
    if (!targetLessonId.trim()) {
      setError('Vui lòng nhập lesson_id');
      return;
    }

    try {
      setSubmitting(true);
      const bank = await learningPathService.getLessonQuestionBank(targetLessonId.trim());
      setSelectedBank(bank);
      setLessonId(targetLessonId.trim());
      setError(null);
    } catch (err) {
      setSelectedBank(null);
      setError(err instanceof Error ? err.message : 'Không thể tải question bank');
    } finally {
      setSubmitting(false);
    }
  };

  const handleGenerateBank = async (event?: FormEvent) => {
    event?.preventDefault();
    if (!lessonId.trim()) {
      setError('Vui lòng nhập lesson_id');
      return;
    }

    try {
      setSubmitting(true);
      const bank = await learningPathService.generateLessonQuestionBank(lessonId.trim());
      setSelectedBank(bank);
      await loadBanks();
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Không thể tạo question bank');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <DashboardLayout>
      <div className="max-w-[1190px] mx-auto">
        <div className="flex items-center justify-between mt-[25px] mb-6">
          <h1 className="text-[25px] font-semibold text-secondary">Quản trị Question Bank</h1>
          <button
            onClick={() => navigate('/learning-path')}
            className="bg-white border border-[#8f1025] text-[#8f1025] text-[13px] font-medium px-4 py-2 rounded-[10px] hover:bg-gray-50 transition-colors"
          >
            Về Learning Path
          </button>
        </div>

        <div className="bg-white border border-[#ce6a86] rounded-[18px] p-6 mb-6">
          <form onSubmit={handleGenerateBank} className="flex flex-col gap-4 md:flex-row md:items-end">
            <div className="flex-1">
              <label className="block text-[13px] font-medium text-[#8f1025] mb-2">Lesson ID</label>
              <input
                value={lessonId}
                onChange={(e) => setLessonId(e.target.value)}
                placeholder="Ví dụ: lesson_python_intro"
                className="w-full rounded-[10px] border border-[#e4b6d0] px-4 py-2 text-[14px] focus:outline-none focus:ring-2 focus:ring-[#8f1025]"
              />
            </div>
            <div className="flex gap-3">
              <button
                type="button"
                onClick={() => handleFetchBank(lessonId)}
                disabled={submitting}
                className="rounded-[10px] border border-[#8f1025] px-4 py-2 text-[13px] font-medium text-[#8f1025] hover:bg-[#f7dfed] disabled:opacity-50"
              >
                Xem bank
              </button>
              <button
                type="submit"
                disabled={submitting}
                className="rounded-[10px] bg-[#8f1025] px-4 py-2 text-[13px] font-medium text-white hover:bg-[#7a0e20] disabled:opacity-50"
              >
                {submitting ? 'Đang xử lý...' : 'Tạo lại bank'}
              </button>
            </div>
          </form>
          {error && (
            <div className="mt-4 rounded-[10px] border border-red-200 bg-red-50 px-4 py-3 text-[13px] text-red-700">
              {error}
            </div>
          )}
        </div>

        <div className="grid gap-6 lg:grid-cols-[360px,1fr]">
          <div className="bg-white border border-[#ce6a86] rounded-[18px] p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-[16px] font-semibold text-[#8f1025]">Bank đã có</h2>
              <button
                onClick={loadBanks}
                disabled={loading}
                className="text-[12px] text-[#8f1025] hover:underline disabled:opacity-50"
              >
                Làm mới
              </button>
            </div>
            {loading ? (
              <p className="text-[13px] text-[#666]">Đang tải danh sách question bank...</p>
            ) : banks.length === 0 ? (
              <p className="text-[13px] text-[#666]">Chưa có question bank nào được tạo.</p>
            ) : (
              <div className="space-y-3">
                {banks.map((bank) => (
                  <button
                    key={bank.lesson_id}
                    onClick={() => handleFetchBank(bank.lesson_id)}
                    className="w-full rounded-[12px] border border-[#f0c8d7] bg-[#fff8fb] px-4 py-3 text-left hover:bg-[#fdf3f7]"
                  >
                    <p className="text-[13px] font-semibold text-[#8f1025]">{bank.lesson_id}</p>
                    <p className="text-[12px] text-[#666] mt-1">Chapter: {bank.chapter_id}</p>
                    <p className="text-[12px] text-[#666] mt-1">{bank.total_questions} câu hỏi</p>
                  </button>
                ))}
              </div>
            )}
          </div>

          <div className="bg-white border border-[#ce6a86] rounded-[18px] p-5">
            <h2 className="text-[16px] font-semibold text-[#8f1025] mb-4">Chi tiết Question Bank</h2>
            {!selectedBank ? (
              <p className="text-[13px] text-[#666]">Chọn một lesson để xem question bank trực tiếp.</p>
            ) : (
              <div className="space-y-4">
                <div className="rounded-[12px] border border-[#f0c8d7] bg-[#fff8fb] p-4">
                  <p className="text-[13px] font-semibold text-[#8f1025]">{selectedBank.lesson_id}</p>
                  <p className="text-[12px] text-[#666] mt-1">Chapter ID: {selectedBank.chapter_id}</p>
                  <p className="text-[12px] text-[#666] mt-1">Tổng số câu hỏi: {selectedBank.total_questions}</p>
                </div>

                <div className="space-y-3 max-h-[620px] overflow-y-auto pr-1">
                  {selectedBank.questions.map((question, index) => (
                    <div key={question.question_id} className="rounded-[12px] border border-[#f0c8d7] p-4">
                      <div className="flex items-start justify-between gap-4">
                        <div>
                          <p className="text-[13px] font-semibold text-[#333]">
                            {index + 1}. {question.question_text}
                          </p>
                          <p className="text-[12px] text-[#666] mt-2">
                            Concept: <span className="font-medium">{question.concept}</span> • Relation: {question.relation_type}
                          </p>
                          <p className="text-[12px] text-[#666] mt-1">Template ID: {question.template_id}</p>
                        </div>
                      </div>
                      <div className="mt-3 rounded-[10px] bg-[#fdf3f7] px-3 py-2 text-[12px] text-[#5b1724]">
                        Đáp án: {question.answer}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      </div>
    </DashboardLayout>
  );
}
