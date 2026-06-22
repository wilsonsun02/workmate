export const dashboardStats = [
  { label: '在线代理线程', value: '24', trend: '+18%', tone: 'emerald' },
  { label: '当月 Token 消耗', value: '1.24M', trend: '-6%', tone: 'amber' },
  { label: '已启用技能', value: '15', trend: '+3', tone: 'sky' },
  { label: 'MCP 服务节点', value: '08', trend: '99.2%', tone: 'violet' }
]

export const dashboardTimeline = [
  { time: '09:00', title: '晨间巡检完成', detail: '7 个核心服务可用，调度队列健康。' },
  { time: '11:30', title: '新技能已发布', detail: 'report-writer 与 frontend-design 完成版本同步。' },
  { time: '15:10', title: '审计策略触发', detail: '检测到一次敏感目录访问，已进入复核。' }
]

export const dashboardFocus = [
  { title: '调度任务成功率', value: '98.6%', detail: '过去 7 天共执行 214 次，失败集中在外部依赖超时。' },
  { title: '知识库命中质量', value: '92 分', detail: '文件检索回答的可用度持续提升，可增加热词缓存。' },
  { title: '高优先级告警', value: '3 项', detail: '包括 1 项 API 密钥轮换、2 项权限配置待确认。' }
]

export const departmentTree = [
  {
    label: 'WorkMate 总部',
    children: [
      { label: '研发中台' },
      { label: '智能交付' },
      { label: '市场运营' },
      { label: '财务与法务' }
    ]
  }
]

export const members = [
  {
    username: 'admin',
    wechat_work_id: 'leizhen',
    role: '超级管理员',
    quota: '无限制',
    status: 1,
    dept: '研发中台',
    online: '在线',
    efficiency: 96
  },
  {
    username: 'zhangsan',
    wechat_work_id: 'zhangsan001',
    role: '普通员工',
    quota: '1,000,000',
    status: 1,
    dept: '市场运营',
    online: '忙碌',
    efficiency: 78
  },
  {
    username: 'lisi',
    wechat_work_id: 'lisi008',
    role: '知识库管理员',
    quota: '600,000',
    status: 0,
    dept: '智能交付',
    online: '离线',
    efficiency: 61
  },
  {
    username: 'wangwu',
    wechat_work_id: 'wangwu009',
    role: '普通员工',
    quota: '500,000',
    status: 1,
    dept: '智能交付',
    online: '在线',
    efficiency: 85
  },
  {
    username: 'zhaoliu',
    wechat_work_id: 'zhaoliu010',
    role: '财务审核员',
    quota: '800,000',
    status: 1,
    dept: '财务与法务',
    online: '在线',
    efficiency: 92
  }
]

export const costStats = [
  { label: '本月总消耗', value: '1,245,000', unit: 'Tokens' },
  { label: '预估费用', value: '45.50', unit: 'CNY' },
  { label: '限流触发', value: '12', unit: '次' }
]

export const costBreakdown = [
  { user: 'zhangsan', department: '研发中台', used: 850000, quota: 1000000, cost: '28.3' },
  { user: 'lisi', department: '市场运营', used: 120000, quota: 500000, cost: '6.4' },
  { user: 'wangwu', department: '智能交付', used: 275000, quota: 400000, cost: '10.8' }
]

export const auditLogs = [
  {
    time: '2026-03-20 09:30:22',
    user: 'admin',
    action: '修改配置',
    detail: '更新了 .env 中的 MINIMAX_API_KEY',
    ip: '192.168.1.100',
    status: 'success',
    level: '高'
  },
  {
    time: '2026-03-20 11:10:05',
    user: 'zhangsan',
    action: '调用工具',
    detail: '调用 MCPFilesystem 读取敏感目录 /etc/passwd',
    ip: '10.0.0.55',
    status: 'failed',
    level: '严重'
  },
  {
    time: '2026-03-20 13:42:11',
    user: 'lisi',
    action: '权限审查',
    detail: '复核企业微信白名单配置并提交审批。',
    ip: '10.0.0.73',
    status: 'success',
    level: '中'
  }
]
