import { useState, useEffect, useRef } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import DashboardLayout from '../components/layout/DashboardLayout';
import { useAuth } from '../contexts/AuthContext';
import { apiClient } from '../utils/apiClient';

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

export default function AITutor() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [goal, setGoal] = useState('');
  const [level, setLevel] = useState<'beginner' | 'intermediate' | 'advanced'>('beginner');
  const [showGoalInput, setShowGoalInput] = useState(!goal);
  const [currentConcept, setCurrentConcept] = useState<ConceptInfo | null>(null);
  const [conceptLoading, setConceptLoading] = useState(false);
  const [history, setHistory] = useState<HistoryItem[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [showHistory, setShowHistory] = useState(false);
  const messagesEndRef = useRef<HTMLDivElement>(null);

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
  }, [user, navigate, searchParams]);

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

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
      const data = await apiClient.get('/ask/history?limit=20');
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
      const response = await apiClient.delete(`/ask/history/${historyId}`);
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
    if (!goal.trim()) {
      setError('Vui lòng nhập mục tiêu học tập');
      return;
    }
    setShowGoalInput(false);
    setError(null);
    addMessage('assistant', `Xin chào! Tôi sẽ giúp bạn học: "${goal}". Hãy đặt bất kỳ câu hỏi nào về chủ đề này.`, null);
    loadHistory();
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

      const data = await apiClient.post('/ask/', {
        user_id: user.user_id,
        question: userQuestion,
        goal: goal,
        level: level,
        completed: currentConcept ? [currentConcept.concept_id.toString()] : [],
      });
      
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
      // Re-add user message for retry
      addMessage('user', userQuestion, null);
    } finally {
      setLoading(false);
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
              <input
                type="text"
                value={goal}
                onChange={(e) => setGoal(e.target.value)}
                placeholder="Ví dụ: Học Python cơ bản, Hiểu về React hooks..."
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
                        <p className="text-[14px] mb-2">{message.content}</p>
                        <p className="text-[12px] opacity-70">
                          {message.timestamp.toLocaleTimeString('vi-VN', {
                            hour: '2-digit',
                            minute: '2-digit',
                          })}
                        </p>

                        {/* Answer Details */}
                        {message.role === 'assistant' && message.answer && (
                          <div className="mt-4 pt-4 border-t border-gray-300">
                            {message.answer.sources && message.answer.sources.length > 0 && (
                              <div className="mb-3">
                                <p className="text-[12px] font-semibold mb-2">📚 Nguồn tài liệu:</p>
                                <div className="space-y-1">
                                  {message.answer.sources.map((source, idx) => (
                                    <div key={idx}>
                                      {source.url ? (
                                        <a
                                          href={source.url}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                          className="text-[12px] hover:underline"
                                        >
                                          {source.title}
                                        </a>
                                      ) : (
                                        <p className="text-[12px]">{source.title}</p>
                                      )}
                                    </div>
                                  ))}
                                </div>
                              </div>
                            )}

                            {message.answer.confidence && (
                              <p className="text-[12px]">
                                <span className="font-semibold">Độ tin cậy:</span> {Math.round(message.answer.confidence * 100)}%
                              </p>
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
