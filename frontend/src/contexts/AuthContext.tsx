import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { authService } from '../services/authService';
import type { StoredUser, User } from '../types/auth';

interface AuthContextType {
  user: User | null;
  loading: boolean;
  setUser: (user: User | null) => void;
  logout: () => Promise<void>;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

const normalizeAuthUser = (user: StoredUser): User | null => {
  const userId = user.user_id || user._id;
  if (!userId || !user.name || !user.email) {
    return null;
  }

  return {
    user_id: userId,
    name: user.name,
    email: user.email,
    level: user.level || 'beginner',
  };
};

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const token = authService.getStoredToken();
    if (token) {
      const storedUser = authService.getStoredUser();
      if (storedUser) {
        setUser(normalizeAuthUser(storedUser));
      }
    }
    setLoading(false);
  }, []);

  const refreshUser = async () => {
    try {
      const token = authService.getStoredToken();
      if (token) {
        const userData = await authService.getCurrentUser();
        const updatedUser = normalizeAuthUser(userData);
        if (updatedUser) {
          setUser(updatedUser);
          authService.setStoredUser(updatedUser);
        }
      }
    } catch (error) {
      console.error('Failed to refresh user:', error);
    }
  };

  const logout = async () => {
    await authService.logout();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, setUser, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
