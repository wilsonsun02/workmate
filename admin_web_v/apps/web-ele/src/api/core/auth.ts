import { baseRequestClient, requestClient } from '#/api/request';

export namespace AuthApi {
  export interface LoginParams {
    password?: string;
    username?: string;
  }

  export interface LoginResult {
    accessToken: string;
    user: Record<string, any>;
  }
}

export async function loginApi(data: AuthApi.LoginParams) {
  const response = await requestClient.post<any>('/auth/login', data);
  const payload = response?.data ?? response;
  if (!payload?.success || !payload?.token) {
    throw new Error(payload?.message || payload?.detail || '登录失败');
  }
  return {
    accessToken: payload.token,
    user: payload.user || {},
  };
}

export async function refreshTokenApi() {
  return null;
}

export async function logoutApi(token?: null | string) {
  const query = token ? `?token=${encodeURIComponent(token)}` : '';
  return baseRequestClient.post(`/auth/logout${query}`);
}

export async function getAccessCodesApi() {
  return [] as string[];
}
