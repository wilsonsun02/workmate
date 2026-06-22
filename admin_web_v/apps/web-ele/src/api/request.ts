import { useAppConfig } from '@vben/hooks';
import { RequestClient } from '@vben/request';
import { useAccessStore } from '@vben/stores';

import { ElMessage } from 'element-plus';

import { isAuthFailureStatus, redirectToLogin } from '#/utils/auth-redirect';

const runtimeApiUrl = window.__APP_CONFIG__?.VITE_ADMIN_API_BASE;
const { apiURL } = useAppConfig(import.meta.env, import.meta.env.PROD);
const baseURL = (runtimeApiUrl || apiURL || '/api/admin').replace(/\/$/, '');

function formatToken(token: null | string) {
  return token ? `Bearer ${token}` : null;
}

function createRequestClient() {
  const client = new RequestClient({
    baseURL,
    responseReturn: 'body',
  });

  client.addRequestInterceptor({
    fulfilled: async (config) => {
      const accessStore = useAccessStore();
      const token =
        accessStore.accessToken || localStorage.getItem('workmate_admin_token');
      config.headers.Authorization = formatToken(token);
      return config;
    },
  });

  client.addResponseInterceptor({
    fulfilled: (response) => response?.data ?? response,
    rejected: async (error) => {
      if (isAuthFailureStatus(error?.response?.status)) {
        useAccessStore().setAccessToken(null);
        redirectToLogin();
        return Promise.reject(error);
      }
      const message =
        error?.response?.data?.detail ||
        error?.response?.data?.message ||
        error?.message;
      if (message) {
        ElMessage.error(message);
      }
      return Promise.reject(error);
    },
  });

  return client;
}

export const requestClient = createRequestClient();
export const baseRequestClient = requestClient;
