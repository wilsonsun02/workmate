import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    meta: {
      icon: 'lucide:users',
      order: 3,
      title: '组织与账户管理',
    },
    name: 'Organization',
    path: '/org',
    children: [
      {
        name: 'UsersManage',
        path: '/org/users',
        component: () => import('#/views/org/users.vue'),
        meta: {
          title: '员工管理',
        },
      },
    ],
  },
];

export default routes;
