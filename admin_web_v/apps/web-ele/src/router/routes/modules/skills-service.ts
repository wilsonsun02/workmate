import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    meta: {
      icon: 'lucide:wrench',
      order: 6,
      title: 'SKILLS 服务',
    },
    name: 'SkillsService',
    path: '/skills-service',
    children: [
      {
        name: 'SkillsServiceManage',
        path: '/skills-service/manage',
        component: () => import('#/views/capability/skills.vue'),
        meta: {
          title: 'SKILLS 服务管理',
        },
      },
      {
        name: 'SkillsServiceAllocation',
        path: '/skills-service/allocation',
        component: () => import('#/views/capability/skills-allocation.vue'),
        meta: {
          title: 'SKILLS 服务分配',
        },
      },
      {
        name: 'SkillsServiceApproval',
        path: '/skills-service/approval',
        component: () => import('#/views/capability/skills-approval.vue'),
        meta: {
          title: 'SKILLS 服务审批',
        },
      },
    ],
  },
];

export default routes;
