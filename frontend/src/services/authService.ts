import { apiClient } from '../utils/apiClient';
import type { 
  LoginRequest, 
  SignUpRequest, 
  LoginResponse, 
  SignupResponse,
  UpdateUserLevelRequest 
} from '../types/auth';

export const authService = {
  async login(credentials: LoginRequest): Promise<LoginResponse> {
    return apiClient.post('/auth/login', credentials);
  },

  async signup(data: SignUpRequest): Promise<SignupResponse> {
    return apiClient.post('/auth/signup', data);
  },

  async updateUserLevel(data: { user_id: string; level: string; learning_goal?: string }): Promise<any> {
    // Update user level in database
    return apiClient.put(`/users/${data.user_id}`, {
      level: data.level,
      learning_goal: data.learning_goal
    });
  },

  async getCurrentUser(): Promise<any> {
    return apiClient.get('/users/me');
  },

  async logout(): Promise<void> {
    localStorage.removeItem('token');
    localStorage.removeItem('email');
    localStorage.removeItem('user');
  },

  getStoredToken(): string | null {
    return localStorage.getItem('token');
  },

  getStoredEmail(): string | null {
    return localStorage.getItem('email');
  },

  getStoredUser(): any | null {
    const user = localStorage.getItem('user');
    return user ? JSON.parse(user) : null;
  },

  setStoredUser(user: any): void {
    localStorage.setItem('user', JSON.stringify(user));
  },

  isAuthenticated(): boolean {
    return !!this.getStoredToken();
  },
};
