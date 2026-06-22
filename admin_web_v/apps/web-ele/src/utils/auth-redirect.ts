import { LOGIN_PATH } from '@vben/constants';
import { useAccessStore } from '@vben/stores';

import { router } from '#/router';

const AUTH_FAILURE_STATUSES = new Set([401, 403, 419, 440, 498]);
const REDIRECT_LOCK_KEY = 'workmate_admin_auth_redirecting';
const REDIRECT_COOLDOWN_MS = 1500;

function getRedirectTarget() {
  const currentPath = `${window.location.pathname}${window.location.search}${window.location.hash}`;
  if (!currentPath || currentPath.startsWith(LOGIN_PATH)) {
    return LOGIN_PATH;
  }
  return `${LOGIN_PATH}?redirect=${encodeURIComponent(currentPath)}`;
}

export function isAuthFailureStatus(status?: number) {
  return typeof status === 'number' && AUTH_FAILURE_STATUSES.has(status);
}

function clearAuthState() {
  localStorage.removeItem('workmate_admin_token');
  localStorage.removeItem('workmate_admin_user');

  const accessStore = useAccessStore();
  accessStore.setAccessToken(null);
  accessStore.setRefreshToken(null);
  accessStore.setIsAccessChecked(false);
  accessStore.setLoginExpired(false);
  accessStore.setAccessCodes([]);
  accessStore.setAccessMenus([]);
  accessStore.setAccessRoutes([]);
}

export function redirectToLogin() {
  clearAuthState();

  const currentPath = router.currentRoute.value.fullPath || window.location.pathname;
  if (currentPath.startsWith(LOGIN_PATH)) {
    clearAuthRedirectLock();
    return;
  }

  const lastRedirectAt = Number(sessionStorage.getItem(REDIRECT_LOCK_KEY) || '0');
  const now = Date.now();
  if (now - lastRedirectAt < REDIRECT_COOLDOWN_MS) {
    return;
  }

  sessionStorage.setItem(REDIRECT_LOCK_KEY, String(now));
  void router.replace(getRedirectTarget());
}

export function clearAuthRedirectLock() {
  sessionStorage.removeItem(REDIRECT_LOCK_KEY);
}
