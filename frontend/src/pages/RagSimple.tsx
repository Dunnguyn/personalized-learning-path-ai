import { useMemo, useRef, useState } from 'react';

interface ChatMessage {
  id: string;
  role: 'user' | 'assistant';
  content: string;
}

export default function RagSimple() {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const messagesEndRef = useRef<HTMLDivElement>(null);

  const apiUrl = useMemo(() => {
    const base = import.meta.env.VITE_API_URL || 'http://localhost:8000';
    const path = import.meta.env.VITE_API_BASE_PATH || '/api';
    return `${base}${path}`;
  }, []);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  };

  const handleUpload = async () => {
    if (!file) {
      setError('Vui lòng chọn file PDF.');
      return;
    }

    setUploading(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append('file', file);

      const response = await fetch(`${apiUrl}/rag/upload-pdf`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || 'Upload thất bại');
      }

      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: 'PDF đã được xử lý. Bạn có thể đặt câu hỏi ngay bây giờ.',
        },
      ]);
      setFile(null);
      scrollToBottom();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Có lỗi khi upload PDF.';
      setError(message);
    } finally {
      setUploading(false);
    }
  };

  const handleSend = async () => {
    if (!input.trim()) {
      return;
    }

    const question = input.trim();
    setInput('');
    setSending(true);
    setError(null);

    const userMessage: ChatMessage = {
      id: crypto.randomUUID(),
      role: 'user',
      content: question,
    };

    setMessages((prev) => [...prev, userMessage]);

    try {
      const response = await fetch(`${apiUrl}/rag/chat`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ question }),
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data.detail || 'Không thể lấy câu trả lời.');
      }

      const data = await response.json();
      const answer = data.answer || 'Xin lỗi, tôi chưa có câu trả lời.';

      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: 'assistant',
          content: answer,
        },
      ]);
      scrollToBottom();
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Có lỗi khi hỏi đáp.';
      setError(message);
    } finally {
      setSending(false);
    }
  };

  return (
    <div className="min-h-screen bg-gradient-to-br from-[#fdf7f9] via-[#f7e9f0] to-[#fefefe] px-6 py-10 text-[#4b1d2a]">
      <div className="max-w-3xl mx-auto">
        <div className="mb-8 text-center">
          <h1 className="text-[28px] font-semibold tracking-tight">Tra cuu PDF</h1>
          <p className="text-[14px] text-[#7b4a5a] mt-2">
            Tai lieu duoc xu ly ngam. Chi can upload va hoi dap.
          </p>
        </div>

        <div className="bg-white rounded-[18px] border border-[#e7c8d5] shadow-[0_12px_30px_rgba(143,16,37,0.08)] p-6 mb-6">
          <label className="block text-[13px] font-medium mb-3">Upload PDF</label>
          <div className="flex flex-col sm:flex-row gap-3 items-start sm:items-center">
            <input
              type="file"
              accept="application/pdf"
              onChange={(e) => setFile(e.target.files?.[0] || null)}
              className="w-full sm:flex-1 text-[13px] file:mr-4 file:py-2 file:px-4 file:rounded-[10px] file:border-0 file:text-[12px] file:font-semibold file:bg-[#f2d7e1] file:text-[#8f1025]"
            />
            <button
              onClick={handleUpload}
              disabled={uploading}
              className="w-full sm:w-auto px-5 py-2 rounded-[12px] bg-[#8f1025] text-white text-[13px] font-semibold disabled:opacity-50"
            >
              {uploading ? 'Dang xu ly...' : 'Upload'}
            </button>
          </div>
        </div>

        <div className="bg-white rounded-[18px] border border-[#e7c8d5] shadow-[0_12px_30px_rgba(143,16,37,0.08)] p-6">
          <div className="h-[360px] overflow-y-auto border border-[#f0dde6] rounded-[14px] p-4 bg-[#fffafa]">
            {messages.length === 0 ? (
              <p className="text-[13px] text-[#7b4a5a]">
                Hay upload PDF va bat dau dat cau hoi.
              </p>
            ) : (
              messages.map((message) => (
                <div
                  key={message.id}
                  className={`mb-4 flex ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
                >
                  <div
                    className={`max-w-[80%] px-4 py-2 rounded-[14px] text-[13px] leading-relaxed shadow-sm ${
                      message.role === 'user'
                        ? 'bg-[#8f1025] text-white'
                        : 'bg-white border border-[#f0dde6] text-[#4b1d2a]'
                    }`}
                  >
                    {message.content}
                  </div>
                </div>
              ))
            )}
            <div ref={messagesEndRef} />
          </div>

          <div className="mt-4 flex gap-3">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              placeholder="Nhap cau hoi..."
              className="flex-1 px-4 py-2 rounded-[12px] border border-[#e7c8d5] text-[13px] focus:outline-none focus:ring-2 focus:ring-[#8f1025]"
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  handleSend();
                }
              }}
            />
            <button
              onClick={handleSend}
              disabled={sending}
              className="px-5 py-2 rounded-[12px] bg-[#8f1025] text-white text-[13px] font-semibold disabled:opacity-50"
            >
              {sending ? 'Dang gui...' : 'Gui'}
            </button>
          </div>
        </div>

        {error && (
          <div className="mt-4 text-[13px] text-red-600 text-center">{error}</div>
        )}
      </div>
    </div>
  );
}
