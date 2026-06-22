import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    meta: {
      icon: 'lucide:layout-template',
      order: 6,
      title: '模板管理',
    },
    name: 'Template',
    path: '/template',
    children: [
      {
        name: 'TemplateList',
        path: '/template/list',
        component: () => import('#/views/template/index.vue'),
        meta: {
          title: '模板列表',
        },
      },
    ],
  },
];

export default routes;
