import type { Recordable, UserInfo } from '@vben/types';

import { ref } from 'vue';
import { useRouter } from 'vue-router';

import { LOGIN_PATH } from '@vben/constants';
import { preferences } from '@vben/preferences';
import { resetAllStores, useAccessStore, useUserStore } from '@vben/stores';

import { defineStore } from 'pinia';

import { getAccessCodesApi, getUserInfoApi, loginApi, logoutApi } from '#/api';
import { normalizeUserInfo } from '#/api/core/user';
import { clearAuthRedirectLock } from '#/utils/auth-redirect';

export const useAuthStore = defineStore('auth', () => {
  const accessStore = useAccessStore();
  const userStore = useUserStore();
  const router = useRouter();

  const loginLoading = ref(false);
  const loginError = ref<string>('');

  async function authLogin(
    params: Recordable<any>,
    onSuccess?: () => Promise<void> | void,
  ) {
    let userInfo: null | UserInfo = null;
    try {
      loginLoading.value = true;
      loginError.value = '';
      const { accessToken, user } = await loginApi(params);

      if (accessToken) {
        clearAuthRedirectLock();
        accessStore.setAccessToken(accessToken);
        localStorage.setItem('workmate_admin_token', accessToken);
        localStorage.setItem('workmate_admin_user', JSON.stringify(user));

        const [fetchUserInfoResult, accessCodes] = await Promise.all([
          fetchUserInfo(),
          getAccessCodesApi(),
        ]);

        userInfo = fetchUserInfoResult;

        userStore.setUserInfo(userInfo);
        accessStore.setAccessCodes(accessCodes);

        if (accessStore.loginExpired) {
          accessStore.setLoginExpired(false);
        } else {
          onSuccess
            ? await onSuccess?.()
            : await router.push(
                decodeURIComponent(
                  (router.currentRoute.value.query?.redirect as string) ||
                    userInfo.homePath ||
                    preferences.app.defaultHomePath,
                ),
              );
        }
      }
    } catch (error: any) {
      loginError.value = error?.message || '登录失败，请检查账号或密码';
      throw error;
    } finally {
      loginLoading.value = false;
    }

    return {
      userInfo,
    };
  }

  async function logout(redirect: boolean = true) {
    try {
      await logoutApi(
        accessStore.accessToken || localStorage.getItem('workmate_admin_token'),
      );
    } catch {
      // 不做任何处理
    }
    localStorage.removeItem('workmate_admin_token');
    localStorage.removeItem('workmate_admin_user');
    clearAuthRedirectLock();
    resetAllStores();
    accessStore.setLoginExpired(false);

    // 回登录页带上当前路由地址
    await router.replace({
      path: LOGIN_PATH,
      query: redirect
        ? {
            redirect: encodeURIComponent(router.currentRoute.value.fullPath),
          }
        : {},
    });
  }

  async function fetchUserInfo() {
    const baseUserInfo = await getUserInfoApi();
    const userInfo = normalizeUserInfo(
      baseUserInfo,
      accessStore.accessToken || localStorage.getItem('workmate_admin_token') || '',
    );
    userStore.setUserInfo(userInfo);
    return userInfo;
  }

  function $reset() {
    loginLoading.value = false;
  }

  return {
    $reset,
    authLogin,
    fetchUserInfo,
    loginError,
    loginLoading,
    logout,
  };
});
