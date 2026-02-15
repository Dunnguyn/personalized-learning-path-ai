// Authentication Types
export interface User {
  user_id: string;
  email: string;
  name: string;
  level?: string;
  created_at?: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  email: string;
  name: string;
}

export interface SignupResponse {
  token: string;
  user: {
    user_id: string;
    email: string;
    name: string;
    level: string;
    created_at: string;
  };
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface SignUpRequest {
  email: string;
  password: string;
  fullName: string;
}

export interface UpdateUserLevelRequest {
  user_id: string;
  level: string;
  learning_goal?: string;
}

export interface AuthState {
  user: User | null;
  token: string | null;
  isAuthenticated: boolean;
  loading: boolean;
  error: string | null;
}
