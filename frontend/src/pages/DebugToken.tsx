import { useEffect, useState } from 'react';

interface TokenPayload {
  [key: string]: unknown;
}

interface DebugTokenInfo {
  token?: string;
  payload?: TokenPayload;
  user?: unknown;
  fullToken?: string;
  error?: string;
  exception?: string;
}

export default function DebugToken() {
  const [tokenInfo, setTokenInfo] = useState<DebugTokenInfo | null>(null);

  useEffect(() => {
    const token = localStorage.getItem('token');
    const user = localStorage.getItem('user');
    
    if (token) {
      try {
        // Decode JWT (without verification - just for debugging)
        const parts = token.split('.');
        if (parts.length === 3) {
          const payload = JSON.parse(atob(parts[1])) as TokenPayload;
          setTokenInfo({
            token: token.substring(0, 50) + '...',
            payload,
            user: user ? (JSON.parse(user) as unknown) : null,
            fullToken: token
          });
        }
      } catch (e) {
        setTokenInfo({ error: 'Failed to decode token', exception: String(e) });
      }
    } else {
      setTokenInfo({ error: 'No token found in localStorage' });
    }
  }, []);

  return (
    <div className="p-8">
      <h1 className="text-2xl font-bold mb-4">Token Debug Info</h1>
      <pre className="bg-gray-100 p-4 rounded overflow-auto">
        {JSON.stringify(tokenInfo, null, 2)}
      </pre>
      
      <div className="mt-4">
        <button 
          onClick={() => {
            const token = localStorage.getItem('token');
            if (token) {
              navigator.clipboard.writeText(token);
              alert('Token copied to clipboard!');
            }
          }}
          className="bg-blue-500 text-white px-4 py-2 rounded"
        >
          Copy Full Token
        </button>
      </div>
    </div>
  );
}
