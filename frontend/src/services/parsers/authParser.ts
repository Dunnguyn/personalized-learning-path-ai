import type {
  CurrentUserResponse,
  LoginResponse,
  SignupResponse,
  StoredUser,
} from '../../types/auth';

type ApiRecord = Record<string, unknown>;

const asRecord = (value: unknown): ApiRecord =>
  typeof value === 'object' && value !== null ? (value as ApiRecord) : {};

const asString = (value: unknown, fallback = ''): string =>
  typeof value === 'string' ? value : fallback;

export const normalizeStoredUser = (value: unknown): StoredUser => {
  const record = asRecord(value);

  return {
    user_id: typeof record.user_id === 'string' ? record.user_id : undefined,
    _id: typeof record._id === 'string' ? record._id : undefined,
    name: asString(record.name, 'Người học'),
    email: asString(record.email),
    level: typeof record.level === 'string' ? record.level : undefined,
    learning_goal: typeof record.learning_goal === 'string' ? record.learning_goal : undefined,
  };
};

export const normalizeLoginResponse = (value: unknown): LoginResponse => {
  const record = asRecord(value);

  return {
    access_token: asString(record.access_token),
    token_type: asString(record.token_type, 'bearer'),
    user_id: asString(record.user_id),
    email: asString(record.email),
    name: asString(record.name, 'Người học'),
  };
};

export const normalizeSignupResponse = (value: unknown): SignupResponse => {
  const record = asRecord(value);
  const user = asRecord(record.user);

  return {
    token: asString(record.token),
    user: {
      user_id: asString(user.user_id),
      email: asString(user.email),
      name: asString(user.name, 'Người học'),
      level: asString(user.level, 'beginner'),
      created_at: asString(user.created_at),
    },
  };
};

export const normalizeCurrentUserResponse = (value: unknown): CurrentUserResponse =>
  normalizeStoredUser(value);

export const parseStoredUser = (value: string | null): StoredUser | null => {
  if (!value) {
    return null;
  }

  try {
    return normalizeStoredUser(JSON.parse(value));
  } catch {
    return null;
  }
};
