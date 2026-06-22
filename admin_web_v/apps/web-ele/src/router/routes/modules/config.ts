import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    meta: {
      icon: 'lucide:settings-2',
      order: 2,
      title: '系统配置中心',
    },
    name: 'Config',
    path: '/config',
    children: [
      {
        name: 'EnvConfig',
        path: '/config/env',
        component: () => import('#/views/config/env.vue'),
        meta: {
          title: '通用设置',
        },
      },
    ],
  },
];

export default routes;
