import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    meta: {
      affixTab: true,
      icon: 'lucide:layout-dashboard',
      order: 1,
      title: '控制塔总览',
    },
    name: 'Dashboard',
    path: '/dashboard',
    component: () => import('#/views/dashboard/index.vue'),
  },
  {
    meta: {
      icon: 'lucide:wallet-cards',
      order: 5,
      title: '成本与资源管理',
    },
    name: 'Cost',
    path: '/cost',
    component: () => import('#/views/cost/index.vue'),
  },
  {
    meta: {
      icon: 'lucide:shield-alert',
      order: 99,
      title: '安全合规',
    },
    name: 'Audit',
    path: '/audit',
    redirect: '/audit/logs',
    children: [
      {
        meta: { title: '拦截日志', icon: 'lucide:file-warning' },
        name: 'AuditLogs',
        path: 'logs',
        component: () => import('#/views/audit/index.vue'),
      },
      {
        meta: { title: '规则配置', icon: 'lucide:settings-2' },
        name: 'AuditRules',
        path: 'rules',
        component: () => import('#/views/audit/rules.vue'),
      },
    ],
  },
];

export default routes;
