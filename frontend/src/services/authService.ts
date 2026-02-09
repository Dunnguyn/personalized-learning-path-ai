import { apiClient } from '../utils/apiClient';
import type { LoginRequest, SignUpRequest, AuthResponse } from '../types/auth';

export const authService = {
  async login(credentials: LoginRequest): Promise<AuthResponse> {
    return apiClient.post('/auth/login', credentials);
  },

  async signup(data: SignUpRequest): Promise<AuthResponse> {
    return apiClient.post('/auth/signup', data);
  },

  async logout(): Promise<void> {
    localStorage.removeItem('token');
    localStorage.removeItem('email');
  },

  async refreshToken(): Promise<string> {
    const response = await apiClient.post('/auth/refresh');
    if (response.token) {
      localStorage.setItem('token', response.token);
      return response.token;
    }
    throw new Error('Failed to refresh token');
  },

  getStoredToken(): string | null {
    return localStorage.getItem('token');
  },

  getStoredEmail(): string | null {
    return localStorage.getItem('email');
  },

  isAuthenticated(): boolean {
    return !!this.getStoredToken();
  },
};
