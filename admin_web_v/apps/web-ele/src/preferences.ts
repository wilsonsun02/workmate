import { defineOverridesPreferences } from '@vben/preferences';

/**
 * @description 项目配置文件
 * 只需要覆盖项目中的一部分配置，不需要的配置不用覆盖，会自动使用默认配置
 * !!! 更改配置后请清空缓存，否则可能不生效
 */
export const overridesPreferences = defineOverridesPreferences({
  app: {
    accessMode: 'frontend',
    defaultHomePath: '/dashboard',
    enableRefreshToken: false,
    locale: 'zh-CN',
    loginExpiredMode: 'page',
    name: import.meta.env.VITE_APP_TITLE || 'WorkMate',
  },
  
  logo: {
    enable: true,
    fit: 'contain',
    source: '/logo.png',
    sourceDark: '/logo.png',
  },
  copyright: {
    companyName: 'richsupply',
  },
  theme: {
    mode: 'light',
  }
});