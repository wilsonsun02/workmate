import type { RouteRecordRaw } from 'vue-router';

const routes: RouteRecordRaw[] = [
  {
    meta: {
      icon: 'lucide:server',
      order: 5,
      title: 'MCP 服务',
    },
    name: 'McpService',
    path: '/mcp-service',
    children: [
      {
        name: 'McpServiceManage',
        path: '/mcp-service/manage',
        component: () => import('#/views/capability/mcp.vue'),
        meta: {
          title: 'MCP 服务管理',
        },
      },
      {
        name: 'McpServiceAllocation',
        path: '/mcp-service/allocation',
        component: () => import('#/views/capability/mcp-allocation.vue'),
        meta: {
          title: 'MCP 服务分配',
        },
      },
    ],
  },
];

export default routes;
