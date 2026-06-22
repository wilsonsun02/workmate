import type { UserInfo } from '@vben/types';

function normalizeUserInfo(raw: Record<string, any>, token = ''): UserInfo {
  const username = raw.username || 'admin';
  return {
    ...raw,
    avatar: raw.avatar || '',
    desc: raw.desc || 'WorkMate 管理员',
    homePath: raw.homePath || '/dashboard',
    realName: raw.realName || raw.name || raw.username || '管理员',
    roles: Array.isArray(raw.roles) && raw.roles.length ? raw.roles : ['admin'],
    token,
    userId: String(raw.userId || raw.id || username),
    username,
  };
}

export async function getUserInfoApi() {
  const userStr = localStorage.getItem('workmate_admin_user');
  const token = localStorage.getItem('workmate_admin_token') || '';
  const raw = userStr ? JSON.parse(userStr) : null;
  return normalizeUserInfo(raw || {}, token);
}

export { normalizeUserInfo };
