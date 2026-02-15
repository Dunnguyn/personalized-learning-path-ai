import { createContext, useContext, useState, useEffect, ReactNode } from 'react';
import { authService } from '../services/authService';

interface User {
  user_id: string;
  name: string;
  email: string;
  level?: string;
}

interface AuthContextType {
  user: User | null;
  loading: boolean;
  setUser: (user: User | null) => void;
  logout: () => void;
  refreshUser: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Check if user is authenticated on mount
    const token = authService.getStoredToken();
    if (token) {
      const storedUser = authService.getStoredUser();
      if (storedUser) {
        setUser({
          user_id: storedUser.user_id || storedUser._id,
          name: storedUser.name,
          email: storedUser.email,
          level: storedUser.level || 'beginner'
        });
      }
    }
    setLoading(false);
  }, []);

  const refreshUser = async () => {
    try {
      const token = authService.getStoredToken();
      if (token) {
        // Try to fetch fresh user data from API
        // This requires a /users/me endpoint in backend
        const userData = await authService.getCurrentUser();
        const updatedUser = {
          user_id: userData.user_id || userData._id,
          name: userData.name,
          email: userData.email,
          level: userData.level
        };
        setUser(updatedUser);
        authService.setStoredUser(updatedUser);
      }
    } catch (error) {
      console.error('Failed to refresh user:', error);
    }
  };

  const logout = () => {
    authService.logout();
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, loading, setUser, logout, refreshUser }}>
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (context === undefined) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
