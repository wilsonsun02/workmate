<template>
  <div class="page-grid">
    <article class="glass-panel org-shell">
      <section class="section-banner compact-banner org-shell__banner">
        <div>
          <div class="eyebrow">Organization</div>
          <h2>员工与额度的统一管理视图</h2>
          <p>支持按部门与关键词快速筛选，并集中维护员工账号、部门结构和权限绑定信息。</p>
        </div>
      </section>

      <section class="content-grid sidebar-layout org-shell__content">
        <article class="glass-panel panel-block dept-panel">
          <div class="section-heading">
            <div>
              <h3>部门架构</h3>
            </div>
            <div class="table-actions">
              <el-input v-model="keyword" placeholder="搜索员工" clearable class="member-search" />
              <el-button type="primary" link size="small" @click="openDialog()">添加员工</el-button>
              <el-button type="primary" link size="small" @click="openDeptDialog()">添加根部门</el-button>
            </div>
          </div>
          <el-tree
            ref="orgTreeRef"
            :data="orgTree"
            :props="defaultProps"
            node-key="id"
            class="clean-tree"
            @node-click="handleNodeClick"
            @node-expand="handleNodeExpand"
            @node-collapse="handleNodeCollapse"
            v-loading="loadingDepts"
            :expand-on-click-node="false"
            :default-expanded-keys="expandedKeys"
            :current-node-key="currentNodeKey"
            highlight-current
          >
            <template #default="{ node, data }">
              <div class="custom-tree-node" style="display: flex; justify-content: space-between; align-items: center; width: 100%;">
                <span>
                  <span>{{ node.label }}</span>
                  <span v-if="data.node_type === 'user'" class="status-tag">
                    （{{ getEmployeeOnlineStatus(data.user_id).is_online ? '在线' : '离线' }}）
                  </span>
                </span>
                <span v-if="data.node_type === 'dept'" class="node-actions" @click.stop>
                  <el-button link type="primary" size="small" @click="openDeptDialog(undefined, data.id)">新增子级</el-button>
                  <el-button v-if="!data.is_virtual" link type="primary" size="small" @click="openDeptDialog(data)">编辑</el-button>
                  <el-button v-if="!data.is_virtual" link type="danger" size="small" @click="handleDeleteDept(data)">删除</el-button>
                </span>
              </div>
            </template>
          </el-tree>
        </article>

        <article v-if="selectedRoot" class="glass-panel panel-block wide-panel">
          <div class="section-heading">
            <div>
              <h3>公司设定</h3>
              <p class="heading-description">维护主节点设定文件 rich.md。</p>
            </div>
          </div>
          <CompanyDeptIdentityTab
            title="公司设定"
            :allowed-files="['rich.md']"
            default-file-name="rich.md"
            owner-type="root"
            owner-id="root"
          />
        </article>
        <DeptDetailPanel
          v-else-if="selectedDept"
          :dept="selectedDept"
          :departments="normalizedDepartments"
          :members="members"
        />
        <UserDetailPanel
          v-else-if="selectedUser"
          :user="selectedUser"
          :departments="departmentTree"
          @saved="handleUserSaved"
          @deleted="handleUserDeleted"
        />
        <article v-else class="glass-panel panel-block wide-panel">
          <div class="section-heading">
            <div>
              <h3>请选择左侧部门或员工</h3>
              <p class="heading-description">点击左侧部门查看部门信息与设定；点击员工后维护该员工的账号、偏好、机器人、任务与员工设定。</p>
            </div>
          </div>
          <el-empty description="暂无选中条目" />
        </article>
      </section>
    </article>

    <!-- User Edit/Create Dialog -->
    <el-dialog v-model="dialogVisible" :title="dialogForm.id ? '编辑员工' : '添加员工'" width="720px">
      <el-form :model="dialogForm" label-width="120px" :rules="rules" ref="formRef" v-loading="dialogLoadingBotConfig">
        <el-form-item label="姓名" prop="name">
          <el-input v-model="dialogForm.name" placeholder="请输入页面显示姓名，不填则默认使用账号名" />
        </el-form-item>
        <el-form-item label="账号名" prop="username">
          <el-input v-model="dialogForm.username" placeholder="请输入登录账号" />
        </el-form-item>
        <el-form-item label="密码" prop="password">
          <el-input v-model="dialogForm.password" placeholder="不填则默认为 workmate123" type="password" show-password />
        </el-form-item>
        <el-form-item label="归属部门" prop="dept_id">
          <el-tree-select
            v-model="dialogForm.dept_id"
            :data="departmentTree"
            :props="defaultProps"
            check-strictly
            placeholder="请选择归属部门 (可选)"
            style="width: 100%"
            clearable
          />
        </el-form-item>
        <el-form-item label="第三方 ID" prop="third_party_id">
          <el-input v-model="dialogForm.third_party_id" placeholder="请输入第三方 ID (可选)" />
        </el-form-item>
        <el-form-item label="企微 ID" prop="wechat_work_id">
          <el-input v-model="dialogForm.wechat_work_id" placeholder="请输入企微 ID (可选)" />
        </el-form-item>
        <el-form-item label="状态" prop="status" v-if="dialogForm.id">
          <el-switch
            v-model="dialogForm.status"
            :active-value="1"
            :inactive-value="0"
            active-text="正常"
            inactive-text="禁用"
            :loading="dialogStatusSaving"
            :disabled="dialogStatusSaving"
            @change="handleDialogStatusChange"
          />
        </el-form-item>
        <el-divider content-position="left">企业微信机器人配置</el-divider>
        <div class="config-block-header">
          <span class="config-block-tip">企业微信机器人配置可留空；若填写任意一项，则需补全三项并会加密存储。</span>
          <el-button link type="primary" size="small" @click="resetBotConfigFields">重置配置</el-button>
        </div>
        <el-row :gutter="16">
          <el-col :xs="24" :sm="12">
            <el-form-item label="机器人名称" prop="wxwork_bot_name">
              <el-input v-model="dialogForm.wxwork_bot_name" placeholder="请输入 WXWORK_BOT_NAME" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="12">
            <el-form-item label="机器人 ID" prop="wxwork_bot_id">
              <el-input v-model="dialogForm.wxwork_bot_id" placeholder="请输入 WXWORK_BOT_ID" />
            </el-form-item>
          </el-col>
          <el-col :xs="24" :sm="24">
            <el-form-item label="机器人密钥" prop="wxwork_secret">
              <el-input
                v-model="dialogForm.wxwork_secret"
                placeholder="请输入 WXWORK_SECRET"
                type="password"
                show-password
              />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button size="small" @click="dialogVisible = false">取消</el-button>
          <el-button size="small" type="primary" @click="submitForm" :loading="submitLoading">确定</el-button>
        </span>
      </template>
    </el-dialog>

    <!-- Department Edit/Create Dialog -->
    <el-dialog v-model="deptDialogVisible" :title="deptDialogForm.id ? '编辑部门' : '添加部门'" width="500px">
      <el-form :model="deptDialogForm" label-width="100px" :rules="deptRules" ref="deptFormRef">
        <el-form-item label="部门名称" prop="name">
          <el-input v-model="deptDialogForm.name" placeholder="请输入部门名称" />
        </el-form-item>
        <el-form-item label="部门编码" prop="dept_code">
          <el-input v-model="deptDialogForm.dept_code" placeholder="请输入部门编码 (租户内唯一，可选)" />
        </el-form-item>
        <el-form-item label="父级部门" prop="parent_id">
          <el-tree-select
            v-model="deptDialogForm.parent_id"
            :data="departmentTree"
            :props="defaultProps"
            check-strictly
            placeholder="请选择父级部门 (可选)"
            style="width: 100%"
            clearable
            :disabled="deptDialogForm.id && !deptDialogForm.parent_id" 
          />
          <!-- 根节点编辑时不建议随意更改父节点，或可以在此放开，但后端会校验防环路 -->
        </el-form-item>
        <el-form-item label="负责人" prop="manager_user_id">
          <el-select v-model="deptDialogForm.manager_user_id" placeholder="请选择部门负责人 (可选)" style="width: 100%" clearable filterable>
            <el-option v-for="user in members" :key="user.id" :label="user.name || user.username" :value="user.id" />
          </el-select>
        </el-form-item>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button size="small" @click="deptDialogVisible = false">取消</el-button>
          <el-button size="small" type="primary" @click="submitDeptForm" :loading="deptSubmitLoading">确定</el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onBeforeUnmount, onMounted, nextTick } from 'vue'
import { adminApi, type DepartmentItem, type UserItem, type EmployeeBasicItem, type EmployeeStatusItem } from '@/services/admin'
import { ElMessage, ElMessageBox } from 'element-plus'
import UserDetailPanel from './components/UserDetailPanel.vue'
import DeptDetailPanel from './components/DeptDetailPanel.vue'
import CompanyDeptIdentityTab from './components/CompanyDeptIdentityTab.vue'

const keyword = ref('')
const defaultProps = {
  children: 'children',
  label: 'label',
  value: 'id'
}

const normalizeNodeId = (value: unknown) => String(value ?? '').trim()
const normalizeText = (value: unknown) => String(value ?? '').trim()

const employees = ref<EmployeeBasicItem[]>([])
const employeeStatusMap = ref<Record<string, EmployeeStatusItem>>({})
const loadingDepts = ref(false)
const loadingUsers = ref(false)

const rawDepartments = ref<any[]>([])
 
const orgTreeRef = ref<any>(null)
const expandedKeys = ref<string[]>(['__root__'])
const currentNodeKey = ref<string>('')

const addExpandedKey = (key: string) => {
  const normalized = normalizeNodeId(key)
  if (!normalized) return
  if (!expandedKeys.value.includes(normalized)) {
    expandedKeys.value = expandedKeys.value.concat(normalized)
  }
}

const removeExpandedKey = (key: string) => {
  const normalized = normalizeNodeId(key)
  if (!normalized) return
  if (expandedKeys.value.includes(normalized)) {
    expandedKeys.value = expandedKeys.value.filter((item) => item !== normalized)
  }
}

const handleNodeExpand = (data: any) => {
  if (data?.node_type === 'dept' || data?.node_type === 'root') {
    addExpandedKey(data.id)
  }
}

const handleNodeCollapse = (data: any) => {
  if (data?.node_type === 'dept' || data?.node_type === 'root') {
    removeExpandedKey(data.id)
  }
}


const selectedUserId = ref<string>('')
const selectedDeptId = ref<string>('')
const selectedRoot = ref(false)
const resolveEmployeeDeptId = (employee: EmployeeBasicItem) => {
  const deptId = normalizeNodeId(employee.dept_id)
  if (deptId) return deptId

  const deptName = normalizeText(employee.dept_name)
  if (!deptName) return ''

  const matchedDept = rawDepartments.value.find((item) => normalizeText(item.name) === deptName)
  return matchedDept ? normalizeNodeId(matchedDept.id) : ''
}

const employeeToUserItem = (employee: EmployeeBasicItem): UserItem => ({
  id: normalizeNodeId(employee.id),
  username: employee.username,
  name: employee.name,
  title: employee.title || '',
  status: employee.status ?? 1,
  dept_id: resolveEmployeeDeptId(employee),
  dept_name: employee.dept_name || '',
  third_party_id: employee.third_party_id || '',
  wechat_work_id: employee.wechat_work_id || '',
  is_special: employee.is_special ?? 0,
  special_type: employee.special_type || '',
  external_agent_base_url: employee.external_agent_base_url || '',
  created_at: '',
})

const members = computed(() => employees.value.map(employeeToUserItem))
const selectedUser = computed(() => {
  const employee = employees.value.find(item => item.id === selectedUserId.value)
  return employee ? employeeToUserItem(employee) : null
})

const normalizedDepartments = computed<DepartmentItem[]>(() => {
  return rawDepartments.value.map((item) => ({
    ...item,
    id: normalizeNodeId(item?.id),
    parent_id: normalizeNodeId(item?.parent_id),
  }))
})

const selectedDept = computed<DepartmentItem | null>(() => {
  const targetId = normalizeNodeId(selectedDeptId.value)
  if (!targetId) return null
  const dept = normalizedDepartments.value.find((item) => normalizeNodeId(item?.id) === targetId)
  return dept || null
})

const getEmployeeOnlineStatus = (userId: string) => {
  return employeeStatusMap.value[normalizeNodeId(userId)] || {
    user_id: normalizeNodeId(userId),
    is_online: false,
    work_status: 'offline',
    current_task: null,
    status_updated_at: '',
  }
}

let statusTimer: any = null

// Build tree from flat array
const departmentTree = computed(() => {
  if (rawDepartments.value.length === 0) return []
  
  const map: Record<string, any> = {}
  const tree: any[] = []
  
  rawDepartments.value.forEach(item => {
    const id = normalizeNodeId(item.id)
    map[id] = {
      ...item,
      id,
      parent_id: normalizeNodeId(item.parent_id),
      label: item.name,
      children: []
    }
  })
  
  rawDepartments.value.forEach(item => {
    const id = normalizeNodeId(item.id)
    const parentId = normalizeNodeId(item.parent_id)
    if (parentId && map[parentId]) {
      map[parentId].children.push(map[id])
    } else {
      tree.push(map[id])
    }
  })
  return tree
})

const getUserDisplayName = (user: UserItem) => (user.name || user.username || user.id)

const matchesKeyword = (user: UserItem, value: string) => {
  if (!value) return true
  const fields = [
    getUserDisplayName(user),
    user.username || '',
    user.title || '',
    user.third_party_id || '',
    user.wechat_work_id || '',
    user.role_name || '',
    user.dept_name || ''
  ]
  return fields.some(field => String(field).toLowerCase().includes(value))
}

const orgTree = computed(() => {
  const deptTree = departmentTree.value as any[]
  const keywordValue = keyword.value.trim().toLowerCase()
  const userNodesByDept: Record<string, any[]> = {}
  const unassignedUsers: any[] = []
  const deptIdByName: Record<string, string> = {}

  rawDepartments.value.forEach((dept) => {
    const name = normalizeText(dept.name)
    const id = normalizeNodeId(dept.id)
    if (name && id) {
      deptIdByName[name] = id
    }
  })

  employees.value.forEach((employee) => {
    const user = employeeToUserItem(employee)
    if (!matchesKeyword(user, keywordValue)) return
    const display = getUserDisplayName(user)
    const node = {
      id: `user:${user.id}`,
      label: display,
      node_type: 'user',
      user_id: user.id,
    }
    const deptId = normalizeNodeId(user.dept_id) || deptIdByName[normalizeText(user.dept_name)]
    if (deptId) {
      const bucket = userNodesByDept[deptId] || []
      bucket.push(node)
      userNodesByDept[deptId] = bucket
    } else {
      unassignedUsers.push(node)
    }
  })

  const attachUsers = (node: any) => {
    const children = Array.isArray(node.children) ? node.children : []
    const deptId = node.id
    const userChildren = userNodesByDept[deptId] || []
    const nextChildren = children.map(attachUsers).filter(Boolean)
    const merged = nextChildren.concat(userChildren)
    return {
      ...node,
      node_type: 'dept',
      children: merged
    }
  }

  const roots = deptTree.map(attachUsers).filter((node) => (node.children || []).length > 0 || !keywordValue)
  if (unassignedUsers.length > 0) {
    roots.unshift({
      id: '__unassigned__',
      label: '未分配部门',
      node_type: 'dept',
      is_virtual: true,
      children: unassignedUsers
    })
  }
  return [
    {
      id: '__root__',
      label: '公司',
      node_type: 'root',
      children: roots
    }
  ]
})

const handleNodeClick = (data: any) => {
  currentNodeKey.value = data?.id ? String(data.id) : ''
  if (data?.node_type === 'root') {
    selectedRoot.value = true
    selectedUserId.value = ''
    selectedDeptId.value = ''
    return
  }
  if (data?.node_type === 'dept') {
    selectedRoot.value = false
    selectedUserId.value = ''
    selectedDeptId.value = data?.is_virtual ? '' : normalizeNodeId(data?.id)
    return
  }

  if (data?.node_type === 'user' && data.user_id) {
    selectedRoot.value = false
    selectedDeptId.value = ''
    selectedUserId.value = data.user_id
  }
}

const fetchDepartments = async () => {
  loadingDepts.value = true
  try {
    const res = await adminApi.getDepartments()
    if (res.success) {
      const list = Array.isArray(res.data) ? res.data : []
      rawDepartments.value = list
      const valid = new Set(list.map((item) => normalizeNodeId(item?.id)))
      expandedKeys.value = expandedKeys.value.filter((key) => valid.has(normalizeNodeId(key)) || key === '__unassigned__' || key === '__root__')
      if (selectedDeptId.value && !valid.has(normalizeNodeId(selectedDeptId.value))) {
        selectedDeptId.value = ''
      }
    }
  } catch (e) {
    console.error('获取部门失败')
  } finally {
    loadingDepts.value = false
  }
}

const fetchUsers = async () => {
  if (loadingUsers.value) return
  loadingUsers.value = true
  try {
    const res = await adminApi.getEmployeeBasics()
    if (res.success) {
      employees.value = res.data || []
      if (selectedUserId.value && !employees.value.some(item => item.id === selectedUserId.value)) {
        selectedUserId.value = ''
      }
      await refreshEmployeeStatuses()
    }
  } catch (e) {
    ElMessage.error('获取用户列表失败')
  } finally {
    loadingUsers.value = false
  }
}

const refreshEmployeeStatuses = async () => {
  const userIds = employees.value.map(item => normalizeNodeId(item.id)).filter(Boolean)
  if (userIds.length === 0) {
    employeeStatusMap.value = {}
    return
  }

  try {
    const res = await adminApi.getEmployeesStatus(userIds)
    if (res.success) {
      const nextMap: Record<string, EmployeeStatusItem> = {}
      ;(res.employees || []).forEach((item) => {
        const userId = normalizeNodeId(item.user_id)
        if (!userId) return
        nextMap[userId] = item
      })
      employeeStatusMap.value = nextMap
    }
  } catch (e) {
    console.error('获取员工在线状态失败')
  }
}

const handleUserSaved = (patch?: Partial<UserItem>) => {
  const userId = selectedUserId.value
  if (!userId || !patch) return

  const idx = employees.value.findIndex(item => item.id === userId)
  if (idx < 0) return

  const current = employees.value[idx]
  if (!current) return

  const next: EmployeeBasicItem = {
    ...current,
    id: current.id,
    username: patch.username ?? current.username,
    name: patch.name ?? current.name,
    title: patch.title ?? current.title,
    status: patch.status ?? current.status,
    dept_id: patch.dept_id ?? current.dept_id,
    dept_name: patch.dept_name ?? current.dept_name,
    third_party_id: patch.third_party_id ?? current.third_party_id,
    wechat_work_id: patch.wechat_work_id ?? current.wechat_work_id,
    is_special: patch.is_special ?? current.is_special,
    special_type: patch.special_type ?? current.special_type,
    external_agent_base_url: patch.external_agent_base_url ?? current.external_agent_base_url,
  }

  employees.value.splice(idx, 1, next)
}

const handleUserDeleted = async (userId: string) => {
  const normalizedUserId = normalizeNodeId(userId)
  if (!normalizedUserId) return

  employees.value = employees.value.filter(item => normalizeNodeId(item.id) !== normalizedUserId)
  const nextStatusMap = { ...employeeStatusMap.value }
  delete nextStatusMap[normalizedUserId]
  employeeStatusMap.value = nextStatusMap

  if (selectedUserId.value === normalizedUserId) {
    selectedUserId.value = ''
    currentNodeKey.value = ''
  }
}

// Dialog Logic
const dialogVisible = ref(false)
const submitLoading = ref(false)
const dialogLoadingBotConfig = ref(false)
const dialogStatusSaving = ref(false)
const formRef = ref()
const emptyBotConfig = () => ({
  wxwork_bot_name: '',
  wxwork_bot_id: '',
  wxwork_secret: ''
})
const dialogBotConfigSnapshot = ref(emptyBotConfig())
const dialogForm = ref({
  id: '',
  name: '',
  title: '',
  username: '',
  password: '',
  third_party_id: '',
  wechat_work_id: '',
  ...emptyBotConfig(),
  dept_id: '',
  status: 1,
  is_special: 0,
  special_type: '',
  external_agent_base_url: '',
  external_agent_token: ''
})

const getNormalizedBotFields = () => ({
  wxwork_bot_name: dialogForm.value.wxwork_bot_name.trim(),
  wxwork_bot_id: dialogForm.value.wxwork_bot_id.trim(),
  wxwork_secret: dialogForm.value.wxwork_secret.trim()
})

const normalizeOptionalField = (value: string) => {
  const normalized = String(value || '').trim()
  return normalized || undefined
}

const validateBotConfigGroup = (_rule: unknown, value: string, callback: (error?: Error) => void) => {
  const normalized = getNormalizedBotFields()
  const fields = Object.values(normalized)
  const hasAnyValue = fields.some(field => field.length > 0)

  if (!hasAnyValue) {
    callback()
    return
  }

  if (fields.every(field => field.length > 0)) {
    callback()
    return
  }

  if (String(value || '').trim()) {
    callback()
    return
  }

  callback(new Error('已填写企业微信机器人配置时，三项都必须填写'))
}

const validateBotFieldNoWhitespace = (_rule: unknown, value: string, callback: (error?: Error) => void) => {
  const text = String(value || '')
  if (text && /\s/.test(text)) {
    callback(new Error('不能包含空白字符'))
    return
  }
  callback()
}

const rules = {
  username: [{ required: true, message: '请输入账号名', trigger: 'blur' }],
  wxwork_bot_name: [{ validator: validateBotConfigGroup, trigger: ['blur', 'change'] }],
  wxwork_bot_id: [
    { validator: validateBotConfigGroup, trigger: ['blur', 'change'] },
    { validator: validateBotFieldNoWhitespace, trigger: 'blur' }
  ],
  wxwork_secret: [
    { validator: validateBotConfigGroup, trigger: ['blur', 'change'] },
    { validator: validateBotFieldNoWhitespace, trigger: 'blur' }
  ]
}

const resetBotConfigFields = () => {
  dialogForm.value.wxwork_bot_name = dialogBotConfigSnapshot.value.wxwork_bot_name
  dialogForm.value.wxwork_bot_id = dialogBotConfigSnapshot.value.wxwork_bot_id
  dialogForm.value.wxwork_secret = dialogBotConfigSnapshot.value.wxwork_secret
}

const handleDialogStatusChange = async (value: string | number | boolean) => {
  if (!dialogForm.value.id) {
    return
  }

  const nextStatus = Number(value)
  const previousStatus = nextStatus === 1 ? 0 : 1

  dialogStatusSaving.value = true
  try {
    await adminApi.updateUser(dialogForm.value.id, { status: nextStatus })
    ElMessage.success(nextStatus === 1 ? '已启用' : '已禁用')
    handleUserSaved({ status: nextStatus })
    await fetchUsers()
  } catch (e: any) {
    dialogForm.value.status = previousStatus
    ElMessage.error(e.response?.data?.detail || '状态更新失败')
  } finally {
    dialogStatusSaving.value = false
  }
}

const openDialog = async (row?: UserItem) => {
  if (row) {
    dialogForm.value = {
      id: row.id,
      name: row.name || '',
      username: row.username,
      password: '', // 编辑时密码留空表示不修改
      title: row.title || '',
      third_party_id: row.third_party_id || '',
      wechat_work_id: row.wechat_work_id || '',
      ...emptyBotConfig(),
      dept_id: row.dept_id || '',
      is_special: row.is_special ?? 0,
      special_type: row.special_type || '',
      external_agent_base_url: row.external_agent_base_url || '',
      external_agent_token: '',
      status: row.status
    }
  } else {
    dialogForm.value = {
      id: '',
      name: '',
      username: '',
      password: '',
      title: '',
      third_party_id: '',
      wechat_work_id: '',
      ...emptyBotConfig(),
      dept_id: '',
      is_special: 0,
      special_type: '',
      external_agent_base_url: '',
      external_agent_token: '',
      status: 1
    }
  }
  dialogBotConfigSnapshot.value = emptyBotConfig()
  dialogVisible.value = true

  await nextTick()
  if (formRef.value) {
    formRef.value.clearValidate()
  }

  if (!row?.id) {
    return
  }

  dialogLoadingBotConfig.value = true
  try {
    const res = await adminApi.getUserWxWorkBotConfig(row.id)
    if (res.success) {
      dialogBotConfigSnapshot.value = {
        wxwork_bot_name: res.data.wxwork_bot_name || '',
        wxwork_bot_id: res.data.wxwork_bot_id || '',
        wxwork_secret: res.data.wxwork_secret || ''
      }
      resetBotConfigFields()
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载机器人配置失败')
  } finally {
    dialogLoadingBotConfig.value = false
  }
}

const submitForm = async () => {
  if (!formRef.value) return
  await formRef.value.validate(async (valid: boolean) => {
    if (valid) {
      submitLoading.value = true
      try {
        if (dialogForm.value.id) {
          const updateData: any = {
            name: dialogForm.value.name,
            username: dialogForm.value.username,
            title: normalizeOptionalField(dialogForm.value.title),
            third_party_id: normalizeOptionalField(dialogForm.value.third_party_id),
            wechat_work_id: normalizeOptionalField(dialogForm.value.wechat_work_id),
            wxwork_bot_name: dialogForm.value.wxwork_bot_name,
            wxwork_bot_id: dialogForm.value.wxwork_bot_id,
            wxwork_secret: dialogForm.value.wxwork_secret,
            dept_id: dialogForm.value.dept_id || undefined,
            status: dialogForm.value.status
          }
          if (dialogForm.value.is_special !== undefined) {
            updateData.is_special = dialogForm.value.is_special
          }
          updateData.special_type = normalizeOptionalField(dialogForm.value.special_type)
          updateData.external_agent_base_url = normalizeOptionalField(dialogForm.value.external_agent_base_url)
          if (String(dialogForm.value.external_agent_token || '').trim()) {
            updateData.external_agent_token = dialogForm.value.external_agent_token
          }
          if (dialogForm.value.password) {
            updateData.password = dialogForm.value.password
          }
          await adminApi.updateUser(dialogForm.value.id, updateData)
          ElMessage.success('更新成功')
        } else {
          await adminApi.createUser({
            name: dialogForm.value.name,
            username: dialogForm.value.username,
            password: dialogForm.value.password || undefined,
            title: normalizeOptionalField(dialogForm.value.title),
            third_party_id: normalizeOptionalField(dialogForm.value.third_party_id),
            wechat_work_id: normalizeOptionalField(dialogForm.value.wechat_work_id),
            wxwork_bot_name: dialogForm.value.wxwork_bot_name,
            wxwork_bot_id: dialogForm.value.wxwork_bot_id,
            wxwork_secret: dialogForm.value.wxwork_secret,
            dept_id: dialogForm.value.dept_id || undefined,
            is_special: dialogForm.value.is_special,
            special_type: normalizeOptionalField(dialogForm.value.special_type),
            external_agent_base_url: normalizeOptionalField(dialogForm.value.external_agent_base_url),
            external_agent_token: String(dialogForm.value.external_agent_token || '').trim() || undefined,
          })
          ElMessage.success('创建成功')
        }
        dialogVisible.value = false
        fetchUsers()
      } catch (e: any) {
        ElMessage.error(e.response?.data?.detail || '操作失败')
      } finally {
        submitLoading.value = false
      }
    }
  })
}

// Department Dialog Logic
const deptDialogVisible = ref(false)
const deptSubmitLoading = ref(false)
const deptFormRef = ref()
const deptDialogForm = ref({
  id: '',
  name: '',
  dept_code: '',
  manager_user_id: '',
  parent_id: '',
  third_party_id: ''
})

const deptRules = {
  name: [{ required: true, message: '请输入部门名称', trigger: 'blur' }]
}

const openDeptDialog = (row?: any, parentId?: string) => {
  if (row) {
    deptDialogForm.value = {
      id: row.id,
      name: row.label, // 映射到树上的 label
      dept_code: rawDepartments.value.find(d => d.id === row.id)?.dept_code || '',
      manager_user_id: rawDepartments.value.find(d => d.id === row.id)?.manager_user_id || '',
      parent_id: row.parent_id || '',
      third_party_id: rawDepartments.value.find(d => d.id === row.id)?.third_party_id || ''
    }
  } else {
    deptDialogForm.value = {
      id: '',
      name: '',
      dept_code: '',
      manager_user_id: '',
      parent_id: parentId || '',
      third_party_id: ''
    }
  }
  deptDialogVisible.value = true
  if (deptFormRef.value) {
    deptFormRef.value.clearValidate()
  }
}

const submitDeptForm = async () => {
  if (!deptFormRef.value) return
  await deptFormRef.value.validate(async (valid: boolean) => {
    if (valid) {
      deptSubmitLoading.value = true
      try {
        const payload: any = {
          name: deptDialogForm.value.name,
          dept_code: deptDialogForm.value.dept_code || undefined,
          manager_user_id: deptDialogForm.value.manager_user_id || undefined,
          parent_id: deptDialogForm.value.parent_id || undefined,
          third_party_id: deptDialogForm.value.third_party_id || undefined
        }

        if (deptDialogForm.value.id) {
          const res = await adminApi.updateDepartment(deptDialogForm.value.id, payload)
          if (!(res as any)?.success) {
            throw new Error((res as any)?.message || '更新失败')
          }
          const idx = rawDepartments.value.findIndex((item) => normalizeNodeId(item?.id) === normalizeNodeId(deptDialogForm.value.id))
          if (idx >= 0) {
            const current = rawDepartments.value[idx] || {}
            rawDepartments.value.splice(idx, 1, {
              ...current,
              id: normalizeNodeId(deptDialogForm.value.id),
              name: payload.name,
              dept_code: payload.dept_code !== undefined ? payload.dept_code : current.dept_code,
              manager_user_id: payload.manager_user_id !== undefined ? payload.manager_user_id : current.manager_user_id,
              parent_id: payload.parent_id !== undefined ? payload.parent_id : current.parent_id,
              third_party_id: payload.third_party_id !== undefined ? payload.third_party_id : current.third_party_id,
            })
          } else {
            fetchDepartments()
          }
          ElMessage.success('更新部门成功')
        } else {
          const res = await adminApi.createDepartment(payload)
          const deptId = normalizeNodeId((res as any)?.department_id)
          if (!(res as any)?.success || !deptId) {
            throw new Error((res as any)?.message || '创建失败')
          }
          rawDepartments.value = rawDepartments.value.concat({
            id: deptId,
            name: payload.name,
            dept_code: payload.dept_code,
            manager_user_id: payload.manager_user_id,
            parent_id: payload.parent_id,
            third_party_id: payload.third_party_id,
          })
          if (payload.parent_id) {
            addExpandedKey(payload.parent_id)
          }
          ElMessage.success('创建部门成功')
        }
        deptDialogVisible.value = false
      } catch (e: any) {
        ElMessage.error(e.response?.data?.detail || '操作失败')
      } finally {
        deptSubmitLoading.value = false
      }
    }
  })
}

const handleDeleteDept = (row: any) => {
  ElMessageBox.confirm(
    `确定要删除部门 "${row.label}" 吗？`,
    '删除部门确认',
    {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    }
  ).then(async () => {
    try {
      await adminApi.deleteDepartment(row.id)
      ElMessage.success('删除成功')
      const deptId = normalizeNodeId(row.id)
      rawDepartments.value = rawDepartments.value.filter((item) => normalizeNodeId(item?.id) !== deptId)
      removeExpandedKey(deptId)
      if (currentNodeKey.value === deptId) {
        currentNodeKey.value = ''
      }
      if (selectedDeptId.value === deptId) {
        selectedDeptId.value = ''
      }
    } catch (e: any) {
      ElMessage.error(e.response?.data?.detail || '删除失败')
    }
  }).catch(() => {
    // canceled
  })
}

onMounted(() => {
  fetchDepartments()
  fetchUsers()
  statusTimer = setInterval(refreshEmployeeStatuses, 15000)
})

onBeforeUnmount(() => {
  if (statusTimer) {
    clearInterval(statusTimer)
    statusTimer = null
  }
})
</script>

<style scoped>
.org-shell {
  padding: 0;
  overflow: hidden;
}

.org-shell__banner {
  border-bottom: 1px solid var(--el-border-color-light);
}

.org-shell__content {
  padding: 20px;
  align-items: start;
}

.section-banner {
  align-items: flex-start;
  box-sizing: border-box;
  height: 140px;
  overflow: hidden;
}

.section-banner > div {
  max-width: 72ch;
}

.section-banner h2 {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 1;
  overflow: hidden;
}

.section-banner p {
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 2;
  overflow: hidden;
}

.dept-panel {
  align-content: start;
  align-self: start;
  grid-auto-rows: max-content;
}

.wide-panel {
  align-self: start;
}

.dept-panel .section-heading {
  align-items: center;
}

.config-block-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin: 0 0 8px;
}

.config-block-tip {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  line-height: 1.6;
}

.tenant-select {
  width: 220px;
}

.member-search {
  width: 220px;
}

.status-tag {
  margin-left: 4px;
  color: var(--el-text-color-secondary);
}

@media (max-width: 768px) {
  .config-block-header {
    align-items: flex-start;
    flex-direction: column;
  }

  .tenant-select,
  .member-search {
    width: 100%;
  }
}
</style>
