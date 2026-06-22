<template>
  <div class="page-grid mcp-page">
    <section class="glass-panel panel-block">
      <div class="section-heading section-heading--table">
        <div>
          <div class="eyebrow">Server Matrix</div>
          <h2>MCP 服务管理</h2>
          <p class="heading-description">
            集中维护可接入的工具服务器，统一管理传输协议、连接参数、工具启用状态与节点级系统提示词。
          </p>
        </div>
        <div class="heading-tags">
          <el-tag type="info">共 {{ total }} 个节点</el-tag>
          <el-tag type="success">本页启用 {{ enabledCount }} 个</el-tag>
          <el-tag type="warning">本页协议 {{ transportSummary }}</el-tag>
        </div>
      </div>

      <div class="toolbar-row">
        <div class="toolbar-actions">
          <el-button size="small" type="success" plain @click="handleAdd">新增 MCP 服务器</el-button>
        </div>
        <el-input
          v-model="keyword"
          clearable
          placeholder="按名称、描述、协议或连接详情检索"
          class="search-input"
          @clear="handleSearch"
          @keyup.enter="handleSearch"
        >
          <template #append>
            <el-button size="small" :loading="fetching" @click="handleSearch">检索</el-button>
          </template>
        </el-input>
      </div>

      <el-table
        :data="tableData"
        v-loading="fetching"
        border
        stripe
        row-key="server_name"
        table-layout="fixed"
        empty-text="暂无 MCP 节点数据"
        class="mcp-table"
        :header-cell-style="{ background: '#fafafa', fontWeight: '600', color: '#303133', padding: '12px 16px' }"
        :cell-style="{ padding: '12px 16px', verticalAlign: 'middle' }"
      >
        <el-table-column label="服务器名称" min-width="180" fixed="left">
          <template #default="{ row }">
            <el-tooltip :content="row.server_name" placement="top" :show-after="300">
              <span class="cell-text-ellipsis server-name">{{ row.server_name }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="描述" min-width="220">
          <template #default="{ row }">
            <el-tooltip
              :content="row.server_description || '暂无描述'"
              placement="top"
              :show-after="300"
              :disabled="!row.server_description"
            >
              <span class="cell-text-ellipsis server-desc">{{ row.server_description || '暂无描述' }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="通讯协议" min-width="120">
          <template #default="{ row }">
            <el-tag size="small" :type="transportTagType(row.server_config?.transport)">
              {{ row.server_config?.transport || 'stdio' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="连接详情" min-width="220" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tooltip :content="getConnectionDisplay(row)" placement="top" :show-after="300">
              <span class="cell-text-ellipsis connection-text">{{ getConnectionDisplay(row) }}</span>
            </el-tooltip>
          </template>
        </el-table-column>
        <el-table-column label="工具数" min-width="100">
          <template #default="{ row }">
            <el-tag type="info" round size="small">
              {{ row.tools?.filter((t: any) => t.is_load).length || 0 }} / {{ row.tools?.length || 0 }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="启用状态" min-width="100">
          <template #default="{ row }">
            <el-switch
              v-model="row.is_load"
              :loading="savingMap[row.server_name]"
              :disabled="savingMap[row.server_name]"
              @change="handleToggleLoad(row)"
              inline-prompt
              active-text="开"
              inactive-text="关"
            />
          </template>
        </el-table-column>
        <el-table-column label="操作" min-width="160" fixed="right">
          <template #default="{ row, $index }">
            <div class="table-action-group">
              <el-button size="small" type="primary" plain @click="handleEditByName(row.server_name)">配置</el-button>
              <el-button size="small" type="danger" plain @click="handleDelete(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div style="display: flex; justify-content: flex-end; margin-top: 16px;">
        <el-pagination
          background
          layout="total, sizes, prev, pager, next"
          :total="total"
          :page-size="pager.limit"
          :page-sizes="[10, 20, 50, 100]"
          :current-page="currentPage"
          @current-change="handlePageChange"
          @size-change="handleSizeChange"
        />
      </div>
    </section>

    <el-drawer
      v-model="drawerVisible"
      :title="drawerTitle"
      size="min(760px, 92vw)"
      class="mcp-config-drawer"
      destroy-on-close
    >
      <el-tabs v-model="activeTab">
        <!-- Tab 1: 基础连接配置 -->
        <el-tab-pane label="基础配置" name="basic">
          <el-form :model="form" label-position="top" class="drawer-form">
            <el-form-item label="服务器名称">
              <el-input v-model="form.server_name" :disabled="editIndex !== -1" placeholder="唯一标识，例如 filesystem" />
            </el-form-item>
            <el-form-item label="描述">
              <el-input v-model="form.server_description" type="textarea" :rows="2" placeholder="简要描述该服务器的作用" />
            </el-form-item>
            <el-form-item label="启用状态">
              <el-switch v-model="form.is_load" />
            </el-form-item>

            <el-divider border-style="dashed" />

            <el-form-item label="通讯协议 (Transport)">
              <el-select v-model="form.server_config.transport" style="width: 100%">
                <el-option label="stdio (本地进程)" value="stdio" />
                <el-option label="sse (Server-Sent Events)" value="sse" />
                <el-option label="streamable_http" value="streamable_http" />
              </el-select>
            </el-form-item>

            <!-- stdio 配置 -->
            <template v-if="form.server_config.transport === 'stdio' || !form.server_config.transport">
              <el-form-item label="启动命令 (Command)">
                <el-input v-model="form.server_config.command" placeholder="例如 npx 或 python" />
              </el-form-item>
              <el-form-item label="参数 (Args)">
                <div v-for="(_, index) in form.server_config.args" :key="index" class="dynamic-row">
                  <el-input v-model="form.server_config.args[index]" placeholder="参数" />
                  <el-button size="small" type="danger" plain class="mcp-icon-button" :icon="Delete" circle @click="removeArg(index)" />
                </div>
                <el-button type="primary" plain size="small" :icon="Plus" @click="addArg">添加参数</el-button>
              </el-form-item>
              <el-form-item label="环境变量 (Env)">
                <div v-for="(_, key) in form.server_config.env" :key="key" class="dynamic-row">
                  <el-input :value="key" readonly style="width: 140px" />
                  <span style="margin: 0 8px">=</span>
                  <el-input v-model="form.server_config.env[key]" placeholder="Value" />
                  <el-button size="small" type="danger" plain class="mcp-icon-button" :icon="Delete" circle @click="removeEnv(String(key))" />
                </div>
                <div class="dynamic-row" style="margin-top: 8px;">
                  <el-input v-model="newEnvKey" placeholder="Key" style="width: 140px" />
                  <span style="margin: 0 8px">=</span>
                  <el-input v-model="newEnvVal" placeholder="Value" />
                  <el-button size="small" type="success" plain class="mcp-icon-button" :icon="Plus" circle @click="addEnv" />
                </div>
              </el-form-item>
            </template>

            <!-- sse / http 配置 -->
            <template v-else>
              <el-form-item label="远程 URL">
                <el-input v-model="form.server_config.url" placeholder="例如 http://localhost:8000/sse" />
              </el-form-item>
              <el-form-item label="请求头 (Headers)">
                <div v-for="(_, key) in form.server_config.headers" :key="key" class="dynamic-row">
                  <el-input :value="key" readonly style="width: 140px" />
                  <span style="margin: 0 8px">:</span>
                  <el-input v-model="form.server_config.headers[key]" placeholder="Value" />
                  <el-button size="small" type="danger" plain class="mcp-icon-button" :icon="Delete" circle @click="removeHeader(String(key))" />
                </div>
                <div class="dynamic-row" style="margin-top: 8px;">
                  <el-input v-model="newHeaderKey" placeholder="Header Key" style="width: 140px" />
                  <span style="margin: 0 8px">:</span>
                  <el-input v-model="newHeaderVal" placeholder="Value" />
                  <el-button size="small" type="success" plain class="mcp-icon-button" :icon="Plus" circle @click="addHeader" />
                </div>
              </el-form-item>
            </template>
          </el-form>
        </el-tab-pane>

        <!-- Tab 2: Tools -->
        <el-tab-pane label="工具管理" name="tools">
          <div style="margin-bottom: 16px;">
            <el-button type="primary" plain size="small" :icon="Plus" @click="addTool">添加手动配置工具</el-button>
          </div>
          <div class="tools-table-wrap">
            <el-table :data="form.tools" border size="small" table-layout="fixed" class="mcp-tools-table">
              <el-table-column prop="tool_name" label="工具名称" min-width="180">
                <template #default="scope">
                  <el-input v-model="scope.row.tool_name" size="small" placeholder="name" />
                </template>
              </el-table-column>
              <el-table-column prop="tool_description" label="描述" min-width="240">
                <template #default="scope">
                  <el-input v-model="scope.row.tool_description" size="small" placeholder="description" />
                </template>
              </el-table-column>
              <el-table-column label="启用" width="88" align="center">
                <template #default="scope">
                  <el-switch v-model="scope.row.is_load" size="small" />
                </template>
              </el-table-column>
              <el-table-column label="操作" width="72" align="center">
                <template #default="scope">
                  <el-button type="danger" plain :icon="Delete" circle size="small" class="mcp-icon-button" @click="removeTool(scope.$index)" />
                </template>
              </el-table-column>
            </el-table>
          </div>
        </el-tab-pane>

        <!-- Tab 3: Skills -->
        <el-tab-pane label="系统提示词 (Skills)" name="skills">
          <el-alert title="这些提示词将被注入给大模型，用于指导其如何使用该服务器下的工具。" type="info" show-icon style="margin-bottom: 16px;" />
          <el-input
            v-model="form.skills"
            type="textarea"
            :rows="15"
            placeholder="输入针对此 MCP 节点的专属系统提示词..."
          />
        </el-tab-pane>
      </el-tabs>

      <template #footer>
        <div style="display: flex; justify-content: flex-end;">
          <el-button size="small" @click="drawerVisible = false">取消</el-button>
          <el-button size="small" type="primary" @click="confirmEdit">确认并应用修改</el-button>
        </div>
      </template>
    </el-drawer>
  </div>
</template>

<script setup lang="ts">
// @ts-nocheck
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { Plus, Delete } from '@element-plus/icons-vue'
import { adminApi, type McpServerItem, type McpLocalToolsConfig, type McpServerConfig, type McpTool } from '@/services/admin'

type EditableMcpServerConfig = Required<Pick<McpServerConfig, 'transport' | 'command' | 'args' | 'env' | 'url' | 'headers'>>

type EditableMcpServerItem = Omit<McpServerItem, 'server_config' | 'tools'> & {
  server_config: EditableMcpServerConfig
  tools: McpTool[]
}

const tableData = ref<McpServerItem[]>([])
const loading = ref(false)
const fetching = ref(false)
const keyword = ref('')
const total = ref(0)
const pager = reactive({
  limit: 20,
  offset: 0
})
const savingMap = reactive({} as Record<string, boolean>)
const currentPage = computed(() => Math.floor(pager.offset / pager.limit) + 1)

// Local Tools States
const localToolsLoading = ref(false)
const localToolsForm = reactive<McpLocalToolsConfig>({
  MCP_ENABLE_WINDOWS_TOOLS: false,
  MCP_ENABLE_ADVANCED_TOOLS: true,
  MCP_ENABLE_COMMON_TOOLS: true,
  MCP_ENABLE_DOCUMENT_TOOLS: true,
  MCP_ENABLE_EXECUTION_TOOLS: true,
  MCP_ENABLE_MEDIA_TOOLS: true,
  MCP_ENABLE_SEARCH_TOOLS: true,
  MCP_ENABLE_WECHAT_TOOLS: true,
  MCP_ENABLE_HAPP_TOOLS: true
})

const formatLocalToolName = (key: string | number | symbol) => {
  const nameMap: Record<string, string> = {
    'MCP_ENABLE_WINDOWS_TOOLS': 'Windows 系统操作',
    'MCP_ENABLE_ADVANCED_TOOLS': '高级实验性工具',
    'MCP_ENABLE_COMMON_TOOLS': '基础文件操作',
    'MCP_ENABLE_DOCUMENT_TOOLS': '文档处理 (PDF/Word)',
    'MCP_ENABLE_EXECUTION_TOOLS': '代码执行沙盒',
    'MCP_ENABLE_MEDIA_TOOLS': '媒体生成',
    'MCP_ENABLE_SEARCH_TOOLS': '本地与网络搜索',
    'MCP_ENABLE_WECHAT_TOOLS': '微信自动化',
    'MCP_ENABLE_HAPP_TOOLS': 'HAPP 特定工具'
  }
  return nameMap[key as string] || key as string
}

const fetchLocalToolsConfig = async () => {
  localToolsLoading.value = true
  try {
    const config = await adminApi.getMcpLocalToolsConfig()
    if (config) {
      Object.assign(localToolsForm, config)
    }
  } catch (e) {
    console.error('Failed to load local tools config', e)
  } finally {
    localToolsLoading.value = false
  }
}

const saveLocalToolsConfig = async () => {
  localToolsLoading.value = true
  try {
    const res = await adminApi.saveMcpLocalToolsConfig(localToolsForm)
    // The response is {success: true, message: "..."} since we typed it differently in router,
    // but axios data returns the whole object
    ElMessage.success((res as any).message || '本地工具开关保存成功')
  } catch {
    ElMessage.error('本地工具开关保存失败')
  } finally {
    localToolsLoading.value = false
  }
}

// Drawer states
const drawerVisible = ref(false)
const drawerTitle = ref('新增 MCP 服务器')
const editIndex = ref(-1)
const activeTab = ref('basic')

// Dynamic inputs
const newEnvKey = ref('')
const newEnvVal = ref('')
const newHeaderKey = ref('')
const newHeaderVal = ref('')

const form = reactive<EditableMcpServerItem>({
  server_name: '',
  server_description: '',
  is_load: true,
  skills: '',
  server_config: {
    transport: 'stdio',
    command: '',
    args: [],
    env: {},
    url: '',
    headers: {}
  },
  tools: []
})

const fetchServers = async () => {
  fetching.value = true
  try {
    const res = await adminApi.getMcpServersPaginated({
      keyword: keyword.value.trim() || undefined,
      limit: pager.limit,
      offset: pager.offset,
    })
    if (res.success) {
      tableData.value = res.data || []
      total.value = res.total || 0
    }
  } catch {
    ElMessage.error('获取 MCP 服务器列表失败')
  } finally {
    fetching.value = false
  }
}

const handleSearch = () => {
  pager.offset = 0
  fetchServers()
}

const handlePageChange = (page: number) => {
  pager.offset = (page - 1) * pager.limit
  fetchServers()
}

const handleSizeChange = (size: number) => {
  pager.limit = size
  pager.offset = 0
  fetchServers()
}

const handleToggleLoad = async (row: McpServerItem) => {
  const key = row.server_name || ''
  if (!key) return
  savingMap[key] = true
  try {
    const res = await adminApi.updateMcpServer(key, row)
    if (res.success) {
      ElMessage.success('已更新')
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '更新失败')
    fetchServers()
  } finally {
    savingMap[key] = false
  }
}

const enabledCount = computed(() => tableData.value.filter(item => item.is_load).length)

const transportSummary = computed(() => {
  const transports = Array.from(new Set(tableData.value.map(item => item.server_config?.transport || 'stdio')))
  return transports.length ? transports.join(' / ') : '暂无'
})

const getConnectionDisplay = (item: McpServerItem) => {
  const transport = item.server_config?.transport
  if (transport === 'sse' || transport === 'streamable_http') {
    return item.server_config?.url || '未配置远程地址'
  }
  return item.server_config?.command || '未配置启动命令'
}

const transportTagType = (transport?: string) => {
  if (transport === 'sse') return 'success'
  if (transport === 'streamable_http') return 'warning'
  return 'info'
}

const resetForm = () => {
  Object.assign(form, {
    server_name: '',
    server_description: '',
    is_load: true,
    skills: '',
    server_config: { transport: 'stdio', command: '', args: [], env: {}, url: '', headers: {} },
    tools: []
  })
  newEnvKey.value = ''
  newEnvVal.value = ''
  newHeaderKey.value = ''
  newHeaderVal.value = ''
  activeTab.value = 'basic'
}

const handleAdd = () => {
  drawerTitle.value = '新增 MCP 服务器'
  editIndex.value = -1
  resetForm()
  drawerVisible.value = true
}

const handleEdit = (index: number) => {
  drawerTitle.value = '配置 MCP 服务器'
  editIndex.value = index
  resetForm()

  // Deep clone to form
  const origin = tableData.value[index]
  if (!origin) {
    ElMessage.error('未找到对应的 MCP 服务器配置')
    return
  }
  form.server_name = origin.server_name || ''
  form.server_description = origin.server_description || ''
  form.is_load = origin.is_load ?? true
  form.skills = origin.skills || ''

  const conf = origin.server_config || {}
  form.server_config = {
    transport: conf.transport || 'stdio',
    command: conf.command || '',
    args: conf.args ? [...conf.args] : [],
    env: conf.env ? { ...conf.env } : {},
    url: conf.url || '',
    headers: conf.headers ? { ...conf.headers } : {}
  }

  form.tools = origin.tools ? origin.tools.map(t => ({...t})) : []
  drawerVisible.value = true
}

const handleEditByName = (serverName: string) => {
  const index = tableData.value.findIndex(item => item.server_name === serverName)
  if (index === -1) {
    ElMessage.error('未找到对应的 MCP 服务器配置')
    return
  }
  handleEdit(index)
}

const handleDelete = (row: McpServerItem) => {
  if (!row?.id) {
    ElMessage.error('缺少 MCP 服务 ID，无法删除')
    return
  }
  ElMessageBox.confirm('确定要删除该服务器配置吗？', '提示', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'warning'
  })
    .then(async () => {
      await adminApi.deleteMcpServer(row.id)
      ElMessage.success('MCP 服务删除成功')
      if (tableData.value.length === 1 && pager.offset > 0) {
        pager.offset = Math.max(0, pager.offset - pager.limit)
      }
      await fetchServers()
    })
    .catch((e: any) => {
      if (!e || e === 'cancel' || e === 'close' || e === 'cancelled') {
        return
      }
      ElMessage.error(e.response?.data?.detail || '删除失败')
    })
}

const confirmEdit = () => {
  if (!form.server_name) {
    ElMessage.warning('服务器名称为必填项')
    return
  }
  if (form.server_config.transport === 'stdio' && !form.server_config.command) {
    ElMessage.warning('stdio模式下启动命令为必填项')
    return
  }
  if (form.server_config.transport !== 'stdio' && !form.server_config.url) {
    ElMessage.warning('远程模式下URL为必填项')
    return
  }

  // deep clone back to tableData
  const newData: McpServerItem = {
    server_name: form.server_name,
    server_description: form.server_description,
    is_load: form.is_load,
    skills: form.skills,
    server_config: { ...form.server_config },
    tools: form.tools.map(t => ({...t}))
  }

  if (editIndex.value === -1) {
    loading.value = true
    adminApi.createMcpServer(newData)
      .then((res: any) => {
        if (res?.success) {
          ElMessage.success(res?.message || 'MCP 服务创建成功')
          pager.offset = 0
          fetchServers()
          drawerVisible.value = false
        }
      })
      .catch((e: any) => {
        ElMessage.error(e.response?.data?.detail || '创建失败')
      })
      .finally(() => {
        loading.value = false
      })
    return
  }

  loading.value = true
  adminApi.updateMcpServer(newData.server_name, newData)
    .then((res: any) => {
      if (res?.success) {
        ElMessage.success(res?.message || 'MCP 服务更新成功')
        fetchServers()
        drawerVisible.value = false
      }
    })
    .catch((e: any) => {
      ElMessage.error(e.response?.data?.detail || '更新失败')
    })
    .finally(() => {
      loading.value = false
    })
}

// --- Dynamic Form Helpers ---
const addArg = () => form.server_config.args?.push('')
const removeArg = (index: number) => form.server_config.args?.splice(index, 1)

const addEnv = () => {
  if (newEnvKey.value && form.server_config.env) {
    form.server_config.env[newEnvKey.value] = newEnvVal.value
    newEnvKey.value = ''
    newEnvVal.value = ''
  }
}
const removeEnv = (key: string) => {
  if (form.server_config.env) delete form.server_config.env[key]
}

const addHeader = () => {
  if (newHeaderKey.value && form.server_config.headers) {
    form.server_config.headers[newHeaderKey.value] = newHeaderVal.value
    newHeaderKey.value = ''
    newHeaderVal.value = ''
  }
}
const removeHeader = (key: string) => {
  if (form.server_config.headers) delete form.server_config.headers[key]
}

const addTool = () => {
  if (!form.tools) form.tools = []
  form.tools.push({ tool_name: '', tool_description: '', is_load: true })
}
const removeTool = (index: number) => {
  form.tools?.splice(index, 1)
}

onMounted(() => {
  fetchServers()
  fetchLocalToolsConfig()
})
</script>

<style scoped>
.mcp-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.section-heading--table {
  margin-bottom: 16px;
  gap: 16px;
}

.heading-description {
  margin: 8px 0 0;
  color: var(--el-text-color-secondary);
  font-size: 14px;
  line-height: 1.6;
}

.heading-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  justify-content: flex-end;
}

.toolbar-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.toolbar-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.search-input {
  width: min(520px, 100%);
}

.cell-text-ellipsis {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.server-name {
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.server-desc,
.connection-text {
  color: var(--el-text-color-regular);
}

.table-action-group {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.drawer-form {
  padding-right: 16px;
}

.tools-table-wrap {
  width: 100%;
  max-width: 100%;
  overflow-x: auto;
  overflow-y: hidden;
}

.mcp-tools-table {
  width: 100%;
  min-width: 580px;
}

.dynamic-row {
  display: flex;
  align-items: center;
  margin-bottom: 8px;
  gap: 8px;
}

.dynamic-row > .el-input {
  flex: 1 1 auto;
  min-width: 0;
}

.mcp-icon-button {
  flex: 0 0 auto;
}

.mcp-icon-button .el-icon {
  font-size: 14px;
}

.mcp-icon-button.el-button.is-circle {
  width: 28px;
  height: 28px;
  padding: 0;
}

.mcp-config-drawer:deep(.el-drawer__body) {
  overflow-x: hidden;
}

.mcp-config-drawer:deep(.el-tabs),
.mcp-config-drawer:deep(.el-tab-pane) {
  min-width: 0;
}

@media (max-width: 992px) {
  .toolbar-row {
    flex-direction: column;
    align-items: stretch;
  }

  .toolbar-actions,
  .heading-tags {
    justify-content: flex-start;
  }

  .search-input {
    width: 100%;
  }

  .drawer-form {
    padding-right: 0;
  }

  .mcp-tools-table {
    min-width: 520px;
  }
}
</style>
