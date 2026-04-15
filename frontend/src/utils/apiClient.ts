// ==========================================
// TYPES
// ==========================================
export interface ApiError {
  status: number;
  message: string;
  detail?: unknown;
}

export interface ApiResponse<T = unknown> {
  data?: T;
  error?: ApiError;
}

type ApiClientError = Error & {
  status?: number;
};

type ApiRequestOptions = RequestInit & {
  timeoutMs?: number | null;
};

// ==========================================
// CONFIG
// ==========================================

const API_BASE_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000';
const API_BASE_PATH = import.meta.env.VITE_API_BASE_PATH || '/api';

const DEFAULT_TIMEOUT = 30000; // 30 seconds
const MAX_RETRIES = 3;
const RETRY_DELAY_MS = 1000;

// ==========================================
// REQUEST/RESPONSE INTERCEPTORS
// ==========================================

interface RequestInterceptor {
  (config: RequestInit): RequestInit;
}

interface ResponseInterceptor {
  (response: Response): Promise<Response>;
}

interface ErrorInterceptor {
  (error: Error): void;
}

class ApiClient {
  private baseUrl: string;
  private basePath: string;
  private timeout: number;
  private maxRetries: number;

  private requestInterceptors: RequestInterceptor[] = [];
  private responseInterceptors: ResponseInterceptor[] = [];
  private errorInterceptors: ErrorInterceptor[] = [];

  constructor(baseUrl: string, basePath: string) {
    this.baseUrl = baseUrl;
    this.basePath = basePath;
    this.timeout = DEFAULT_TIMEOUT;
    this.maxRetries = MAX_RETRIES;

    // Default request interceptor - add auth token
    this.addRequestInterceptor((config) => {
      const token = localStorage.getItem('token');
      if (token) {
        const headers = new Headers(
          config.headers instanceof Headers
            ? config.headers
            : (config.headers as Record<string, string>) || {},
        );
        headers.set('Authorization', `Bearer ${token}`);
        config.headers = headers;
      }
      return config;
    });

    // Default error interceptor - handle auth errors
    this.addErrorInterceptor((error) => {
      const status = Number((error as Error & { status?: number }).status || 0);
      if (status === 401) {
        localStorage.removeItem('token');
        localStorage.removeItem('user');
        localStorage.removeItem('email');
        window.location.href = '/login';
      }
    });
  }

  addRequestInterceptor(interceptor: RequestInterceptor): void {
    this.requestInterceptors.push(interceptor);
  }

  addResponseInterceptor(interceptor: ResponseInterceptor): void {
    this.responseInterceptors.push(interceptor);
  }

  addErrorInterceptor(interceptor: ErrorInterceptor): void {
    this.errorInterceptors.push(interceptor);
  }

  private async applyRequestInterceptors(config: RequestInit): Promise<RequestInit> {
    let finalConfig = config;
    for (const interceptor of this.requestInterceptors) {
      finalConfig = interceptor(finalConfig);
    }
    return finalConfig;
  }

  private async applyResponseInterceptors(response: Response): Promise<Response> {
    let finalResponse = response;
    for (const interceptor of this.responseInterceptors) {
      finalResponse = await interceptor(finalResponse);
    }
    return finalResponse;
  }

  private applyErrorInterceptors(error: Error): void {
    for (const interceptor of this.errorInterceptors) {
      interceptor(error);
    }
  }

  async request(
    endpoint: string,
    options: ApiRequestOptions = {},
    retries: number = 0,
  ): Promise<unknown> {
    const url = `${this.baseUrl}${this.basePath}${endpoint}`;
    const { timeoutMs, ...requestOptions } = options;

    const headersObj: Record<string, string> = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
    };

    let config: RequestInit = {
      ...requestOptions,
      headers: {
        ...headersObj,
        ...(requestOptions.headers instanceof Headers
          ? Object.fromEntries(requestOptions.headers)
          : (requestOptions.headers as Record<string, string>)),
      },
    };

    // Apply request interceptors
    config = await this.applyRequestInterceptors(config);

    try {
      const fetchPromise = fetch(url, config);
      const response =
        timeoutMs === null
          ? await fetchPromise
          : await Promise.race([
              fetchPromise,
              new Promise<Response>((_, reject) =>
                setTimeout(
                  () =>
                    reject(
                      new Error(
                        `Yêu cầu đã hết thời gian chờ sau ${typeof timeoutMs === 'number' ? timeoutMs : this.timeout}ms`,
                      ),
                    ),
                  typeof timeoutMs === 'number' ? timeoutMs : this.timeout,
                ),
              ),
            ]);

      // Apply response interceptors
      const finalResponse = await this.applyResponseInterceptors(response);

      if (!finalResponse.ok) {
        const error = await finalResponse.json().catch(() => ({}));
        const message =
          error.detail || error.message || `YÃªu cáº§u tháº¥t báº¡i: ${finalResponse.statusText}`;

        const apiError: ApiClientError = new Error(message);
        apiError.status = finalResponse.status;
        throw apiError;
      }

      return await finalResponse.json();
    } catch (error) {
      const isNetworkError = error instanceof TypeError;
      const shouldRetry = isNetworkError && retries < this.maxRetries;

      if (shouldRetry) {
        await new Promise((resolve) => setTimeout(resolve, RETRY_DELAY_MS * (retries + 1)));
        return this.request(endpoint, options, retries + 1);
      }

      // Apply error interceptors
      if (error instanceof Error) {
        this.applyErrorInterceptors(error);
      }

      throw error;
    }
  }

  get(endpoint: string, options: ApiRequestOptions = {}) {
    return this.request(endpoint, { ...options, method: 'GET' });
  }

  post(endpoint: string, data?: unknown, options: ApiRequestOptions = {}) {
    return this.request(endpoint, {
      ...options,
      method: 'POST',
      body: data ? JSON.stringify(data) : undefined,
    });
  }

  put(endpoint: string, data?: unknown, options: ApiRequestOptions = {}) {
    return this.request(endpoint, {
      ...options,
      method: 'PUT',
      body: data ? JSON.stringify(data) : undefined,
    });
  }

  patch(endpoint: string, data?: unknown, options: ApiRequestOptions = {}) {
    return this.request(endpoint, {
      ...options,
      method: 'PATCH',
      body: data ? JSON.stringify(data) : undefined,
    });
  }

  delete(endpoint: string, options: ApiRequestOptions = {}) {
    return this.request(endpoint, { ...options, method: 'DELETE' });
  }
}

// ==========================================
// EXPORT INSTANCE
// ==========================================

export const apiClient = new ApiClient(API_BASE_URL, API_BASE_PATH);

