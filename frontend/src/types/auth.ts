// Authentication Types
export type UserRole = 'learner' | 'admin';

export interface User {
  user_id: string;
  email: string;
  name: string;
  level?: string;
  role?: UserRole;
  learning_goal?: string;
  created_at?: string;
}

export interface StoredUser {
  user_id?: string;
  _id?: string;
  name: string;
  email: string;
  level?: string;
  role?: UserRole;
  learning_goal?: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  email: string;
  name: string;
  role: UserRole;
}

export interface SignupResponse {
  token: string;
  user: {
    user_id: string;
    email: string;
    name: string;
    level: string;
    role: UserRole;
    created_at: string;
  };
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface ForgotPasswordRequest {
  email: string;
  new_password: string;
}

export interface ForgotPasswordResponse {
  success: boolean;
  message: string;
}

export interface SignUpRequest {
  email: string;
  password: string;
  fullName: string;
}

export interface SignupStep2FormData {
  goal: string;
  level: string;
}

export interface UpdateUserLevelRequest {
  user_id: string;
  level: string;
  learning_goal?: string;
}

export type CurrentUserResponse = StoredUser;

export interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  loading: boolean;
  error: string | null;
}
