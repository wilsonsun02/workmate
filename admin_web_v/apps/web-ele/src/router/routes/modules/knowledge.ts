import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    meta: {
      icon: 'lucide:book-open',
      order: 4,
      title: '知识库管理',
    },
    name: 'Knowledge',
    path: '/knowledge',
    children: [
      {
        name: 'KnowledgeCompany',
        path: '/knowledge/company',
        component: () => import('#/views/knowledge/company.vue'),
        meta: {
          title: '企业知识库',
        },
      },
      {
        name: 'KnowledgePersonal',
        path: '/knowledge/personal',
        component: () => import('#/views/knowledge/personal.vue'),
        meta: {
          title: '个人知识库',
        },
      },
      {
        name: 'KnowledgeShares',
        path: '/knowledge/shares',
        component: () => import('#/views/knowledge/shares.vue'),
        meta: {
          title: '分享记录',
        },
      },
    ],
  },
];

export default routes;
