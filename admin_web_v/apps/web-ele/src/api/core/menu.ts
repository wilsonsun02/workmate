import type { RouteRecordStringComponent } from '@vben/types';

type WorkmateMenuItem = {
  name: string;
  path: string;
};

function createView(name: string, path: string, icon: string, children: WorkmateMenuItem[]): RouteRecordStringComponent {
  return {
    component: 'BasicLayout',
    meta: {
      icon,
      order: 1,
      title: name,
    },
    name,
    path,
    children,
  } as unknown as RouteRecordStringComponent;
}

/**
 * WorkMate 管理端使用前端静态菜单，不依赖 Vben 默认的 `/menu/all` 接口。
 */
export async function getAllMenusApi() {
  return [
    createView('Dashboard', '/dashboard', 'lucide:layout-dashboard', [
      {
        name: 'DashboardHome',
        path: '/dashboard',
      },
      {
        name: 'Cost',
        path: '/cost',
      },
      {
        name: 'Audit',
        path: '/audit',
      },
    ]),
    createView('Config', '/config', 'lucide:settings-2', [
      {
        name: 'ConfigEnv',
        path: '/config/env',
      },
      {
        name: 'ConfigPrompts',
        path: '/config/prompts',
      },
      {
        name: 'ConfigDatasource',
        path: '/config/datasource',
      },
    ]),
    createView('Org', '/org', 'lucide:users', [
      {
        name: 'OrgUsers',
        path: '/org/users',
      },
      {
        name: 'OrgMidMemory',
        path: '/org/mid-memory',
      },
    ]),
    createView('Client', '/client', 'lucide:monitor-smartphone', [
      {
        name: 'ClientOnlineUsers',
        path: '/client/online-users',
      },
      {
        name: 'ClientCredentials',
        path: '/client/credentials',
      },
    ]),
    createView('Capability', '/capability', 'lucide:cpu', [
      {
        name: 'CapabilityMcp',
        path: '/capability/mcp',
      },
      {
        name: 'CapabilitySkills',
        path: '/capability/skills',
      },
    ]),
  ] as RouteRecordStringComponent[];
}
