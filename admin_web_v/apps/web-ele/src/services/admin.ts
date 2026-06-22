// @ts-nocheck
import axios from 'axios'
import { isAuthFailureStatus, redirectToLogin } from '#/utils/auth-redirect'

export interface EnvConfigPayload {
  GOOGLE_API_KEY: string
  MINIMAX_API_KEY: string
  DASHSCOPE_API_KEY: string
  RUNLOOP_API_KEY: string
  OSS_ENDPOINT: string
  OSS_REGION: string
  OSS_BUCKET: string
  OSS_ACCESS_KEY_ID: string
  OSS_ACCESS_KEY_SECRET: string
  OSS_AUTH_MODE: string
  OSS_STS_TOKEN: string
  SKILL_INSTALL_TRIGGER_MODE: string
}

export interface EnvFieldOption {
  label: string
  value: string
}

export interface EnvFieldMeta {
  key: string
  label: string
  description: string
  component: 'input' | 'password' | 'textarea' | 'select' | 'switch'
  sensitive: boolean
  section_id: string
  options: EnvFieldOption[]
  default_value: string
  value: string | boolean
}

export interface EnvSection {
  id: string
  title: string
  description: string
  fields: EnvFieldMeta[]
}

export interface EnvFileItem {
  key: string
  value: string
}

export interface EnvFilePayload {
  path: string
  updated_at: string
  hidden_sections?: string[]
  hidden_keys?: string[]
  all_sections?: Array<{ id: string, title: string, description: string, keys: string[] }>
  values: Record<string, string>
  raw_items: EnvFileItem[]
  unknown_items: EnvFileItem[]
  sections: EnvSection[]
}

export interface EnvFileUpdatePayload {
  values: Record<string, string | boolean>
  deleted_keys?: string[]
  hidden_sections?: string[]
  shown_sections?: string[]
  hidden_keys?: string[]
  shown_keys?: string[]
}

export interface EnvChangeLogItem {
  id: string
  operator_user_id: string
  operator_username: string
  source_ip: string
  target_file: string
  changed_keys: string[]
  before_values: Record<string, string>
  after_values: Record<string, string>
  created_at: string
}

export type PromptOwnerType = 'root' | 'dept' | 'user'

export interface PromptOwnerParams {
  owner_type?: PromptOwnerType
  owner_id?: string
}

export interface PromptFileListItem {
  file_name: string
  path: string
  version: string
  sha256: string
  updated_at: string
  editable: boolean
}

export interface PromptFileItem extends PromptFileListItem {
  content: string
}

export interface PromptChangeLogItem {
  id: string
  file_name: string
  target_file: string
  operator_user_id: string
  operator_username: string
  source_ip: string
  before_version: string
  after_version: string
  before_sha256: string
  after_sha256: string
  before_content: string
  after_content: string
  created_at: string
}

export interface PromptVersionHistoryItem {
  file_name: string
  version: string
  content: string
  sha256: string
  operator_user_id: string
  operator_username: string
  source_ip: string
  updated_at: string
}

export interface McpTool {
  tool_name: string
  tool_description: string
  is_load: boolean
}

export interface McpServerConfig {
  transport?: 'stdio' | 'sse' | 'streamable_http'
  command?: string
  args?: string[]
  env?: Record<string, string>
  url?: string
  headers?: Record<string, string>
}

export interface McpServerItem {
  id: string
  server_name: string
  server_description?: string
  is_load: boolean
  skills?: string
  server_config: McpServerConfig
  tools?: McpTool[]
}

export interface McpServerPaginatedResponse {
  success: boolean
  data: McpServerItem[]
  total: number
  limit: number
  offset: number
}

export interface McpLocalToolsConfig {
  MCP_ENABLE_WINDOWS_TOOLS: boolean
  MCP_ENABLE_ADVANCED_TOOLS: boolean
  MCP_ENABLE_COMMON_TOOLS: boolean
  MCP_ENABLE_DOCUMENT_TOOLS: boolean
  MCP_ENABLE_EXECUTION_TOOLS: boolean
  MCP_ENABLE_MEDIA_TOOLS: boolean
  MCP_ENABLE_SEARCH_TOOLS: boolean
  MCP_ENABLE_WECHAT_TOOLS: boolean
  MCP_ENABLE_HAPP_TOOLS: boolean
}

export interface SkillItem {
  name: string
  description?: string
  enabled: boolean
  latest_version?: string
  package_count?: number
  oss_packaged?: boolean
}

export interface SkillCatalogItem {
  name: string
  description?: string
  enabled: boolean
  latest_version: string
  package_count: number
}

export interface SkillPaginatedResponse {
  success: boolean
  data: SkillItem[]
  total: number
  page: number
  page_size: number
}

export interface SkillInstallTask {
  id: string
  release_id?: string
  target_owner_type: string
  target_owner_id: string
  target_user_id: string
  username?: string
  client_id?: string
  skill_name: string
  target_version: string
  rollout_batch?: number
  retry_policy?: Record<string, any> | string
  status: string
  error_message?: string
  started_at?: string
  finished_at?: string
  created_at?: string
  updated_at?: string
}

export interface SkillReleaseItem {
  id: string
  skill_name: string
  version: string
  strategy: 'active' | 'passive' | 'hybrid' | string
  rollout_type: 'user' | 'role' | 'dept' | string
  rollout_id: string
  status: 'draft' | 'running' | 'paused' | 'completed' | 'rollback' | string
  total_targets?: number
  batch_size?: number
  failure_threshold?: number
  created_by?: string
  created_at?: string
  updated_at?: string
}

export interface SkillReleaseTargetItem {
  id: string
  release_id: string
  target_user_id: string
  username?: string
  rollout_batch: number
  status: string
  latest_task_id?: string
  last_error_message?: string
  created_at?: string
  updated_at?: string
}

export interface SkillReleaseCreatePayload {
  skill_name: string
  version: string
  rollout_type: 'user' | 'role' | 'dept'
  rollout_id: string
  strategy?: 'active' | 'passive' | 'hybrid'
  batch_size?: number
  failure_threshold?: number
  created_by?: string
}

export interface SkillReleaseDispatchPayload {
  rollout_batch?: number
}

export interface SkillReleaseRollbackPayload {
  rollback_version: string
}

export interface PermissionPreviewResult {
  user_id: string
  skills: Array<{
    name: string
    description?: string
    latest_version?: string
    package_id?: string
    sha256?: string
  }>
}

export interface SkillFileNode {
  path: string
  is_dir: boolean
  is_text: boolean
  size: number
  updated_at: number
}

export interface SkillFileContentPayload {
  path: string
  content: string
}

export interface SkillPublishResult {
  name: string
  version: string
  file_path: string
}

export interface RoleItem {
  id: string
  name: string
  code?: string
  description?: string
}

export interface DepartmentItem {
  id: string
  name: string
  parent_id?: string
  tenant_id?: string
  dept_code?: string
  manager_user_id?: string
  third_party_id?: string
}

export interface UserItem {
  id: string
  username: string // 登录账号
  name?: string
  title?: string
  password?: string
  third_party_id?: string
  wechat_work_id?: string
  wxwork_bot_name?: string
  wxwork_bot_id?: string
  wxwork_secret?: string
  role_id?: string
  role_name?: string
  dept_id?: string
  dept_name?: string
  status: number
  is_special?: number
  special_type?: string
  external_agent_base_url?: string
  external_agent_token?: string
  tenant_id?: string
  created_at: string
}

export interface EmployeeBasicItem {
  id: string
  username: string
  name: string
  title?: string
  dept_id?: string
  dept_name?: string
  third_party_id?: string
  wechat_work_id?: string
  status?: number
  is_special?: number
  special_type?: string
  external_agent_base_url?: string
  created_at: string
}

export interface UserWxWorkBotConfig {
  user_id: string
  wxwork_bot_name: string
  wxwork_bot_id: string
  wxwork_secret: string
}

export interface MidTermMemoryItem {
  id: number
  username: string
  thread_id: string
  summary: string
  full_conversation?: string | null
  last_sequence_number: number
  last_chat_index: number
  created_at: string
}

export interface EmployeeStatusItem {
  user_id: string
  is_online: boolean
  work_status: string
  current_task: any
  status_updated_at: string
}

export interface UserPreferenceItem {
  pref_key: string
  pref_value: string
  created_at: string
  updated_at: string
}

export interface SchedulerTaskItem {
  id: string
  name?: string
  description?: string
  cron_expression?: string
  status?: string
  next_run_time?: string
  last_run_time?: string
  created_at?: string
  updated_at?: string
}

export interface SchedulerExecutionItem {
  id: string
  task_id: string
  status: string
  started_at?: string
  finished_at?: string
  result?: any
  error?: string
}

export interface ThirdPartyDbConfig {
  tenant_id: string
  tenant_name: string
  connection: {
    host: string
    port: number
    user: string
    password?: string
    database: string
  }
  mapping: {
    dept_table: string
    dept_id_field: string
    dept_parent_id_field: string
    dept_name_field: string
    user_table: string
    user_id_field: string
    user_name_field: string
    user_display_name_field?: string
    user_dept_id_field: string
  }
}

export interface KbCategoryItem {
  name: string
  display_name: string
  kb_type?: string
  username?: string
  file_count?: number
  created_at?: string
}

export interface KbFileItem {
  id: string
  category: string
  original_filename: string
  md_filename: string
  file_type: string
  file_size: number
  summary: string
  source_url: string
  created_at: string
  updated_at: string
}

export interface KbShareItem {
  share_id: string
  file_id: string
  owner_username: string
  target_username: string
  share_category: string
  original_filename: string
  md_filename: string
  file_type: string
  summary: string
  shared_at: string
}

const runtimeAdminApiBase = window.__APP_CONFIG__?.VITE_ADMIN_API_BASE
const adminApiBase = (runtimeAdminApiBase || import.meta.env.VITE_ADMIN_API_BASE || '/api/admin').replace(/\/$/, '')

const http = axios.create({
  baseURL: adminApiBase,
  timeout: 15000,
})

// 请求拦截器：自动附加 Token
http.interceptors.request.use(config => {
  const token = localStorage.getItem('workmate_admin_token')
  if (token) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
}, error => {
  return Promise.reject(error)
})

// 响应拦截器：处理登录过期/无权限
http.interceptors.response.use(response => {
  return response
}, error => {
  if (isAuthFailureStatus(error?.response?.status)) {
    redirectToLogin()
  }
  return Promise.reject(error)
})

export const adminApi = {
  login: async (payload: any) => (await http.post<{success: boolean, token: string, user: any, message?: string}>('/auth/login', payload)).data,
  logout: async (token: string) => (await http.post<{success: boolean, message: string}>(`/auth/logout?token=${token}`)).data,
  getEnvFileConfig: async () => (await http.get<EnvFilePayload>('/config/env-file')).data,
  saveEnvFileConfig: async (payload: EnvFileUpdatePayload) =>
    (await http.put<{success: boolean, message: string, changed_keys: string[]}>('/config/env-file', payload)).data,
  getEnvFileConfigLogs: async (limit = 50) =>
    (await http.get<{success: boolean, items: EnvChangeLogItem[], total: number}>('/config/env-file/logs', { params: { limit } })).data,
  getPromptFiles: async (params?: PromptOwnerParams) =>
    (await http.get<{success: boolean, items: PromptFileListItem[]}>('/prompts/files', { params })).data,
  getPromptFile: async (fileName: string, params?: PromptOwnerParams) =>
    (await http.get<{success: boolean, data: PromptFileItem}>(`/prompts/files/${encodeURIComponent(fileName)}`, { params })).data,
  savePromptFile: async (fileName: string, payload: {content: string}, params?: PromptOwnerParams) =>
    (await http.put<{success: boolean, message: string, changed: boolean, file_name: string, sha256: string, updated_at: string}>(`/prompts/files/${encodeURIComponent(fileName)}`, payload, { params })).data,
  getPromptFileLogs: async (fileName: string, limit = 50, params?: PromptOwnerParams) =>
    (await http.get<{success: boolean, items: PromptChangeLogItem[], total: number}>(`/prompts/files/${encodeURIComponent(fileName)}/logs`, { params: { ...params, limit } })).data,
  getPromptFileVersions: async (fileName: string, limit = 50, params?: PromptOwnerParams) =>
    (await http.get<{success: boolean, items: PromptVersionHistoryItem[], total: number}>(`/prompts/files/${encodeURIComponent(fileName)}/versions`, { params: { ...params, limit } })).data,
  getEnvConfig: async () => (await http.get<EnvConfigPayload>('/config/env')).data,
  saveEnvConfig: async (payload: EnvConfigPayload) => http.put('/config/env', payload),
  getMcpServers: async () => (await http.get<McpServerItem[]>('/mcp/')).data,
  getMcpServersPaginated: async (params?: { keyword?: string, enabled_only?: boolean, limit?: number, offset?: number }) =>
    (await http.get<McpServerPaginatedResponse>('/mcp/paginated', { params })).data,
  saveMcpServers: async (payload: McpServerItem[]) => http.put('/mcp/', payload),
  createMcpServer: async (payload: McpServerItem) =>
    (await http.post<{success: boolean, message: string, data: McpServerItem}>('/mcp/', payload)).data,
  updateMcpServer: async (serverName: string, payload: McpServerItem) =>
    (await http.put<{success: boolean, message: string, data: McpServerItem}>(`/mcp/${encodeURIComponent(serverName)}`, payload)).data,
  deleteMcpServer: async (serverId: string) =>
    (await http.delete<{success: boolean, message: string}>(`/mcp/${encodeURIComponent(serverId)}`)).data,
  getMcpLocalToolsConfig: async () => (await http.get<McpLocalToolsConfig>('/mcp/local-tools')).data,
  saveMcpLocalToolsConfig: async (payload: McpLocalToolsConfig) => http.put('/mcp/local-tools', payload),
  getSkills: async () => (await http.get<SkillItem[]>('/skills/')).data,
  getSkillsPaginated: async (params?: { page?: number, page_size?: number, keyword?: string }) =>
    (await http.get<SkillPaginatedResponse>('/skills/paginated', { params })).data,
  saveSkills: async (payload: SkillItem[]) => http.put('/skills/', payload),
  getSkillCatalog: async () => (await http.get<{success: boolean, data: SkillCatalogItem[]}>('/skills/catalog')).data,
  packageAllSkills: async () => (await http.post<{success: boolean, data: {total: number, success: number, failed: number, details: any[]}}>('/skills/package-all')).data,
  downloadLatestSkillPackage: async (skillName: string) => await http.get(`/skills/${skillName}/download-latest`, { responseType: 'blob' }),
  getSkillVersions: async (skillName: string) => (await http.get<{success: boolean, data: any[]}>(`/skills/${skillName}/versions`)).data,
  getSkillFiles: async (skillName: string) => (await http.get<{success: boolean, data: SkillFileNode[]}>(`/skills/${skillName}/files`)).data,
  getSkillFileContent: async (skillName: string, path: string) => (await http.get<{success: boolean, data: {path: string, content: string}}>(`/skills/${skillName}/files/content`, { params: { path } })).data,
  saveSkillFileContent: async (skillName: string, payload: SkillFileContentPayload) => (await http.put<{success: boolean, message: string}>(`/skills/${skillName}/files/content`, payload)).data,
  publishSkill: async (skillName: string) => (await http.post<{success: boolean, data: SkillPublishResult}>(`/skills/${skillName}/publish`)).data,
  getSkillReleases: async (params?: {skill_name?: string, status?: string, limit?: number, offset?: number}) => (await http.get<{success: boolean, data: SkillReleaseItem[]}>('/skills/releases', { params })).data,
  createSkillRelease: async (payload: SkillReleaseCreatePayload) => (await http.post<{success: boolean, data: SkillReleaseItem}>('/skills/releases', payload)).data,
  getSkillReleaseDetail: async (releaseId: string) => (await http.get<{success: boolean, data: SkillReleaseItem}>(`/skills/releases/${releaseId}`)).data,
  getSkillReleaseTargets: async (releaseId: string) => (await http.get<{success: boolean, data: SkillReleaseTargetItem[]}>(`/skills/releases/${releaseId}/targets`)).data,
  dispatchSkillRelease: async (releaseId: string, payload: SkillReleaseDispatchPayload) => (await http.post<{success: boolean, data: {trigger_mode: string, release_id: string, rollout_batch: number, created: number, dispatched: number, tasks: any[]}}>(`/skills/releases/${releaseId}/dispatch`, payload)).data,
  pauseSkillRelease: async (releaseId: string) => (await http.post<{success: boolean, message: string}>(`/skills/releases/${releaseId}/pause`)).data,
  resumeSkillRelease: async (releaseId: string) => (await http.post<{success: boolean, message: string}>(`/skills/releases/${releaseId}/resume`)).data,
  rollbackSkillRelease: async (releaseId: string, payload: SkillReleaseRollbackPayload) => (await http.post<{success: boolean, data: {trigger_mode: string, release_id: string, rollback_version: string, created: number, dispatched: number, tasks: any[]}}>(`/skills/releases/${releaseId}/rollback`, payload)).data,
  createSkillInstallTasks: async (payload: {owner_type: string, owner_id: string, skill_name: string, version?: string}) => (await http.post<{success: boolean, data: {trigger_mode: string, created: number, dispatched: number, tasks: any[]}}>('/skills/install-tasks', payload)).data,
  getSkillInstallTasks: async (params?: {status?: string, limit?: number, offset?: number}) => (await http.get<{success: boolean, data: SkillInstallTask[]}>('/skills/install-tasks', { params })).data,
  uploadSkill: async (file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return (await http.post<{success: boolean, message: string, name: string}>('/skills/upload', formData, {
      headers: { 'Content-Type': 'multipart/form-data' }
    })).data
  },
  deleteSkill: async (skillName: string) => (await http.delete<{success: boolean, message: string}>(`/skills/${skillName}`)).data,
  getSkillAllocations: async (skillName: string) => (await http.get<{success: boolean, data: {users: any[], roles: any[], depts: any[]}}>(`/skills/${skillName}/allocations`)).data,
  getUsers: async (tenant_id?: string) => {
    const limit = 200
    let offset = 0
    let total = 0
    let merged: UserItem[] = []

    while (true) {
      const url = tenant_id
        ? `/users/?tenant_id=${tenant_id}&limit=${limit}&offset=${offset}`
        : `/users/?limit=${limit}&offset=${offset}`
      const res = (await http.get<{success: boolean, data: UserItem[], total: number, limit: number, offset: number }>(url)).data
      if (!res?.success) {
        return res as any
      }
      total = Number(res.total || 0)
      merged = merged.concat(res.data || [])
      offset += limit
      if (!total || merged.length >= total) {
        return { ...res, data: merged }
      }
    }
  },
  getMidTermMemories: async (params?: {username?: string, thread_id?: string, keyword?: string, limit?: number, offset?: number}) =>
    (await http.get<{success: boolean, data: MidTermMemoryItem[], total: number}>('/memory/mid-term', { params })).data,
  updateMidTermMemory: async (id: number, payload: {summary: string}) =>
    (await http.put<{success: boolean, message: string}>(`/memory/mid-term/${id}`, payload)).data,
  deleteMidTermMemory: async (id: number) =>
    (await http.delete<{success: boolean, message: string}>(`/memory/mid-term/${id}`)).data,
  getDepartments: async (tenant_id?: string) => {
    const url = tenant_id ? `/users/departments?tenant_id=${tenant_id}` : '/users/departments'
    return (await http.get<{success: boolean, data: DepartmentItem[] }>(url)).data
  },
  getEmployeeBasics: async (params?: {tenant_id?: string, keyword?: string, dept_id?: string, status?: number}) => {
    const limit = 200
    let offset = 0
    let total = 0
    let merged: EmployeeBasicItem[] = []

    while (true) {
      const res = (await http.get<{success: boolean, data: EmployeeBasicItem[], total: number, limit: number, offset: number}>(
        '/users/employees/basic',
        { params: { ...(params || {}), limit, offset } }
      )).data
      if (!res?.success) {
        return res as any
      }
      total = Number(res.total || 0)
      merged = merged.concat(res.data || [])
      offset += limit
      if (!total || merged.length >= total) {
        return { ...res, data: merged }
      }
    }
  },
  createDepartment: async (payload: Partial<DepartmentItem>) => (await http.post<{success: boolean, department_id: string, message: string}>('/users/departments', payload)).data,
  updateDepartment: async (id: string, payload: Partial<DepartmentItem>) => (await http.put<{success: boolean, message: string}>(`/users/departments/${id}`, payload)).data,
  deleteDepartment: async (id: string) => (await http.delete<{success: boolean, message: string}>(`/users/departments/${id}`)).data,
  getRoles: async () => (await http.get<{success: boolean, data: RoleItem[]}>('/users/roles')).data,
  createUser: async (payload: Partial<UserItem>) => (await http.post<{success: boolean, user_id: string, message: string}>('/users/', payload)).data,
  updateUser: async (id: string, payload: Partial<UserItem>) => (await http.put<{success: boolean, message: string}>(`/users/${id}`, payload)).data,
  deleteUser: async (id: string) => (await http.delete<{success: boolean, message: string}>(`/users/${id}`)).data,
  getUserWxWorkBotConfig: async (id: string) => (await http.get<{success: boolean, data: UserWxWorkBotConfig}>(`/users/${id}/wxwork-bot-config`)).data,
  saveUserWxWorkBotConfig: async (id: string, payload: Omit<UserWxWorkBotConfig, 'user_id'>) => (await http.put<{success: boolean, message: string}>(`/users/${id}/wxwork-bot-config`, payload)).data,
  getUserPreferences: async (id: string) =>
    (await http.get<{success: boolean, data: UserPreferenceItem[]}>(`/users/${id}/preferences`)).data,
  getUserPreferencesByUsername: async (username: string) =>
    (await http.get<{success: boolean, data: UserPreferenceItem[]}>(`/users/by-username/${encodeURIComponent(username)}/preferences`)).data,
  saveUserPreference: async (id: string, prefKey: string, prefValue: string) =>
    (await http.put<{success: boolean, message: string}>(`/users/${id}/preferences/${encodeURIComponent(prefKey)}`, { pref_value: prefValue })).data,
  deleteUserPreference: async (id: string, prefKey: string) =>
    (await http.delete<{success: boolean, message: string}>(`/users/${id}/preferences/${encodeURIComponent(prefKey)}`)).data,
  getEmployeesStatus: async (userIds: string[]) => {
    const ids = (userIds || []).map(id => String(id || '').trim()).filter(Boolean)
    const res = (await http.get<{success: boolean, employees: EmployeeStatusItem[], total: number}>(
      '/monitor/employees',
      { params: { user_ids: ids.join(',') } }
    )).data
    return res
  },
  listSchedulerTasks: async (params: {username: string, status?: string}) => {
    const res = (await http.get<{success: boolean, total?: number, tasks?: SchedulerTaskItem[], error?: string}>('/scheduler/tasks', { params })).data
    return { ...(res as any), data: (res as any).tasks || [] }
  },
  createSchedulerTask: async (payload: {username: string, task_description: string, cron_expression?: string, task_type?: string, task_name?: string}) =>
    (await http.post<{success: boolean, data?: any, error?: string}>('/scheduler/tasks', payload)).data,
  deleteSchedulerTask: async (taskId: string, params: {username: string}) =>
    (await http.delete<{success: boolean, message?: string, error?: string}>(`/scheduler/tasks/${encodeURIComponent(taskId)}`, { params })).data,
  pauseSchedulerTask: async (taskId: string, params: {username: string}) =>
    (await http.post<{success: boolean, message?: string, error?: string}>(`/scheduler/tasks/${encodeURIComponent(taskId)}/pause`, null, { params })).data,
  resumeSchedulerTask: async (taskId: string, params: {username: string}) =>
    (await http.post<{success: boolean, message?: string, error?: string}>(`/scheduler/tasks/${encodeURIComponent(taskId)}/resume`, null, { params })).data,
  runSchedulerTaskNow: async (taskId: string, params: {username: string}) =>
    (await http.post<{success: boolean, execution_id?: string, error?: string}>(`/scheduler/tasks/${encodeURIComponent(taskId)}/run`, null, { params })).data,
  listSchedulerExecutions: async (params: {task_id: string, username: string, limit?: number}) => {
    const res = (await http.get<{success: boolean, total?: number, executions?: SchedulerExecutionItem[], error?: string}>('/scheduler/executions', { params })).data
    return { ...(res as any), data: (res as any).executions || [] }
  },

  // Third Party DB Sync
  getThirdPartyDbs: async () => (await http.get<ThirdPartyDbConfig[]>('/config/third-party-dbs')).data,
  saveThirdPartyDbs: async (payload: ThirdPartyDbConfig[]) => http.put('/config/third-party-dbs', payload),
  testThirdPartyDbConnection: async (payload: any) => (await http.post<{success: boolean, message: string}>('/config/third-party-dbs/test-connection', payload)).data,
  syncTenantData: async (tenantId: string) => (await http.post<{success: boolean, message: string, stats: any}>(`/sync/${tenantId}`)).data,

  // Permissions
  getPermissions: async (ownerType: string, ownerId: string) => (await http.get<{success: boolean, data: {mcp_tools: any[], skills: any[]}}>(`/permissions/${ownerType}/${ownerId}`)).data,
  savePermissions: async (ownerType: string, ownerId: string, payload: any) => (await http.post<{success: boolean, message: string}>(`/permissions/${ownerType}/${ownerId}`, payload)).data,
  previewUserSkills: async (userId: string) => (await http.get<{success: boolean, data: PermissionPreviewResult}>(`/permissions/preview/user/${userId}`)).data,

  // 知识库管理
  getKbCategories: async (kbType: string = 'personal', username: string = '') => {
    let url = `/knowledge/categories?type=${kbType}`
    if (username) url += `&user=${encodeURIComponent(username)}`
    return (await http.get<{success: boolean, categories: KbCategoryItem[]}>(url)).data
  },
  createKbCategory: async (name: string, kbType: string = 'personal', username: string = '') =>
    (await http.post<{success: boolean, message: string, category?: KbCategoryItem}>('/knowledge/categories', { name, kb_type: kbType, username })).data,
  deleteKbCategory: async (name: string, kbType: string = 'personal', username: string = '') => {
    let url = `/knowledge/categories/${encodeURIComponent(name)}?type=${kbType}`
    if (username) url += `&user=${encodeURIComponent(username)}`
    return (await http.delete<{success: boolean, name: string}>(url)).data
  },
  renameKbCategory: async (name: string, newDisplayName: string, kbType: string = 'personal', username: string = '') => {
    let url = `/knowledge/categories/${encodeURIComponent(name)}/rename?type=${kbType}`
    if (username) url += `&user=${encodeURIComponent(username)}`
    return (await http.put<{success: boolean, name: string, display_name: string}>(url, { new_display_name: newDisplayName })).data
  },
  getKbFiles: async (kbType: string = 'personal', category?: string, username: string = '') => {
    const params: Record<string, string> = { type: kbType }
    if (category) params.category = category
    if (username) params.user = username
    return (await http.get<{success: boolean, files: KbFileItem[]}>('/knowledge/files', { params })).data
  },
  uploadKbFile: async (file: File, category: string, kbType: string = 'personal', username: string = '') => {
    const formData = new FormData()
    formData.append('file', file)
    let url = `/knowledge/files/upload?category=${encodeURIComponent(category)}&type=${kbType}`
    if (username) url += `&user=${encodeURIComponent(username)}`
    return (await http.post<{success: boolean, file?: KbFileItem, error?: string}>(
      url,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    )).data
  },
  uploadKbUrl: async (url: string, category: string, kbType: string = 'personal', username: string = '') =>
    (await http.post<{success: boolean, file?: KbFileItem, error?: string}>('/knowledge/files/url', { url, category, kb_type: kbType, username })).data,
  deleteKbFile: async (fileId: string, kbType: string = 'personal', username: string = '') => {
    let url = `/knowledge/files/${fileId}?type=${kbType}`
    if (username) url += `&user=${encodeURIComponent(username)}`
    return (await http.delete<{success: boolean, message: string}>(url)).data
  },
  getKbFileContent: async (fileId: string, kbType: string = 'personal', username: string = '') => {
    let url = `/knowledge/files/${fileId}?type=${kbType}`
    if (username) url += `&user=${encodeURIComponent(username)}`
    return (await http.get<{success: boolean, content: string, file?: KbFileItem}>(url)).data
  },
  updateKbFileContent: async (fileId: string, content: string, kbType: string = 'personal', username: string = '') => {
    let url = `/knowledge/files/${fileId}?type=${kbType}`
    if (username) url += `&user=${encodeURIComponent(username)}`
    return (await http.put<{success: boolean, message: string}>(url, { content })).data
  },

  // ---- 知识库分享 & 移动 API ----
  /** 查询分享记录（管理端，分页） */
  getKbShares: async (params: { page?: number; size?: number; keyword?: string; owner?: string; target?: string }) =>
    (await http.get<{success: boolean, total: number, items: KbShareItem[], page: number, size: number}>('/knowledge/shares', { params })).data,

  /** 移动知识库文件到另一个分类 */
  moveKbFile: async (fileId: string, targetCategory: string, kbType: string = 'company', username: string = '') => {
    let url = `/knowledge/files/${fileId}/move?type=${kbType}`
    if (username) url += `&user=${encodeURIComponent(username)}`
    return (await http.post<{success: boolean, message: string}>(url, { target_category: targetCategory })).data
  },

  // ---- 模板管理 API ----
  getTemplateCategories: async () =>
    (await http.get<{success: boolean, categories: any[]}>('/templates/categories')).data,

  getTemplateList: async (params: {
    category_key?: string
    keyword?: string
    is_active?: number
    page?: number
    page_size?: number
  }) => (await http.get<{success: boolean, total: number, items: any[]}>('/templates/list', { params })).data,

  getTemplateDetail: async (id: string) =>
    (await http.get<{success: boolean, data: any}>(`/templates/${id}`)).data,

  createTemplate: async (payload: {
    category_key: string
    template_key: string
    template_name: string
    template_type?: string
    description?: string
    style_config?: string
    sort_order?: number
    file: File
    cover?: File
  }) => {
    const formData = new FormData()
    formData.append('category_key', payload.category_key)
    formData.append('template_key', payload.template_key)
    formData.append('template_name', payload.template_name)
    if (payload.template_type) formData.append('template_type', payload.template_type)
    if (payload.description) formData.append('description', payload.description)
    if (payload.style_config) formData.append('style_config', payload.style_config)
    if (payload.sort_order) formData.append('sort_order', String(payload.sort_order))
    formData.append('file', payload.file)
    if (payload.cover) formData.append('cover', payload.cover)
    return (await http.post<{success: boolean, id: string, template_key: string, error?: string}>(
      '/templates',
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    )).data
  },

  updateTemplate: async (id: string, payload: {
    template_name?: string
    template_type?: string
    description?: string
    style_config?: string
    is_active?: number
    sort_order?: number
  }) => (await http.put<{success: boolean, error?: string}>(`/templates/${id}`, payload)).data,

  updateTemplateFile: async (id: string, file: File) => {
    const formData = new FormData()
    formData.append('file', file)
    return (await http.put<{success: boolean, file_url: string, version: number, error?: string}>(
      `/templates/${id}/file`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    )).data
  },

  uploadTemplateCover: async (id: string, cover: File) => {
    const formData = new FormData()
    formData.append('cover', cover)
    return (await http.post<{success: boolean, cover_url: string, error?: string}>(
      `/templates/${id}/upload-cover`,
      formData,
      { headers: { 'Content-Type': 'multipart/form-data' } }
    )).data
  },

  toggleTemplate: async (id: string, is_active: number) =>
    (await http.put<{success: boolean, error?: string}>(`/templates/${id}/toggle`, { is_active })).data,

  deleteTemplate: async (id: string) =>
    (await http.delete<{success: boolean, error?: string}>(`/templates/${id}`)).data,

  // ---- 安全合规 API ----
  getInterceptLogs: async (params?: {
    keyword?: string
    channel?: string
    intercept_type?: string
    username?: string
    start_time?: string
    end_time?: string
    limit?: number
    offset?: number
  }) => (await http.get<{success: boolean, logs: any[], total: number, limit: number, offset: number}>('/security/intercept-logs', { params })).data,

  getInterceptStats: async () =>
    (await http.get<{success: boolean, stats: {total: number, today: number, by_channel: {channel: string, count: number}[], by_type: {intercept_type: string, count: number}[]}}>('/security/intercept-logs/stats')).data,

  getSecurityRules: async () =>
    (await http.get<{success: boolean, rules: any, source: string}>('/security/rules')).data,

  saveSecurityRules: async (rules: any) =>
    (await http.put<{success: boolean, message: string}>('/security/rules', { rules })).data,

  // 暴露底层 request 方法
  request: http
}
