import { apiClient } from '../utils/apiClient';
import type {
  CurrentUserResponse,
  ForgotPasswordRequest,
  ForgotPasswordResponse,
  LoginRequest,
  LoginResponse,
  SignUpRequest,
  SignupResponse,
  StoredUser,
  UpdateUserLevelRequest,
} from '../types/auth';
import {
  normalizeCurrentUserResponse,
  normalizeForgotPasswordResponse,
  normalizeLoginResponse,
  normalizeSignupResponse,
  normalizeStoredUser,
  parseStoredUser,
} from './parsers/authParser';

export type { CurrentUserResponse, StoredUser } from '../types/auth';

export const authService = {
  async login(credentials: LoginRequest): Promise<LoginResponse> {
    return normalizeLoginResponse(await apiClient.post('/auth/login', credentials));
  },

  async signup(data: SignUpRequest): Promise<SignupResponse> {
    return normalizeSignupResponse(await apiClient.post('/auth/signup', data));
  },

  async requestPasswordReset(data: ForgotPasswordRequest): Promise<ForgotPasswordResponse> {
    return normalizeForgotPasswordResponse(await apiClient.post('/auth/forgot-password', data));
  },

  async updateUserLevel(data: UpdateUserLevelRequest): Promise<CurrentUserResponse> {
    return normalizeCurrentUserResponse(
      await apiClient.put(`/users/${data.user_id}`, {
        level: data.level,
        learning_goal: data.learning_goal,
      }),
    );
  },

  async getCurrentUser(): Promise<CurrentUserResponse> {
    return normalizeCurrentUserResponse(await apiClient.get('/users/me'));
  },

  async logout(): Promise<void> {
    try {
      await apiClient.post('/auth/logout', {});
    } catch (error) {
      console.warn('Logout API failed, clearing local session anyway:', error);
    } finally {
      localStorage.removeItem('token');
      localStorage.removeItem('email');
      localStorage.removeItem('user');
    }
  },

  getStoredToken(): string | null {
    return localStorage.getItem('token');
  },

  getStoredEmail(): string | null {
    return localStorage.getItem('email');
  },

  getStoredUser(): StoredUser | null {
    return parseStoredUser(localStorage.getItem('user'));
  },

  setStoredUser(user: StoredUser): void {
    localStorage.setItem('user', JSON.stringify(normalizeStoredUser(user)));
  },

  isAuthenticated(): boolean {
    return !!this.getStoredToken();
  },
};
