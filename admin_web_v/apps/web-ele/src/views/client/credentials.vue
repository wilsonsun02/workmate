<template>
  <div class="page-grid">
    <section class="section-banner glass-panel compact-banner">
      <div>
        <div class="eyebrow">Client Credentials</div>
        <h2>登录凭证与客户端访问控制</h2>
        <p>统一维护客户端凭证、在线状态与启用状态，支持快速复制标识符并创建新凭证。</p>
      </div>
      <div class="banner-stats">
        <div>
          <span>凭证总数</span>
          <strong>{{ clients.length }}</strong>
        </div>
        <div>
          <span>在线中</span>
          <strong>{{ clients.filter((item) => item.is_online).length }}</strong>
        </div>
      </div>
    </section>

    <section class="glass-panel panel-block">
      <div class="section-heading section-heading--table">
        <div>
          <div class="eyebrow">Access Registry</div>
          <h3>登录凭证</h3>
          <p class="heading-description">客户端类型可启停、复制标识符并按需删除；用户型凭证仅展示状态。</p>
        </div>
        <div class="heading-tags">
          <el-tag type="info">在线 {{ clients.filter((item) => item.is_online).length }}</el-tag>
        </div>
      </div>

      <div class="toolbar-row">
        <div class="toolbar-actions">
          <el-button :loading="loading" @click="refreshNow">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
          <el-button type="primary" @click="showCreateDialog = true">
            <el-icon><Plus /></el-icon>
            新建登录凭证
          </el-button>
        </div>
      </div>

      <el-table :data="clients" v-loading="loading" border stripe row-key="id">
        <el-table-column prop="name" label="凭证名称" min-width="160" />
        <el-table-column label="类型" width="100">
          <template #default="{ row }">
            <el-tag :type="row.type === 'user' ? 'success' : 'info'">
              {{ row.type === 'user' ? '用户' : '客户端' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="identifier" label="标识符 (Client ID / 用户名)" min-width="200">
          <template #default="{ row }">
            <span class="copyable" @click="copyText(row.identifier)">
              {{ row.identifier }}
              <el-icon><DocumentCopy /></el-icon>
            </span>
          </template>
        </el-table-column>
        <el-table-column label="在线状态" width="120">
          <template #default="{ row }">
            <div class="status-indicator">
              <span :class="['dot', row.is_online ? 'online' : 'offline']"></span>
              {{ row.is_online ? '在线' : '离线' }}
            </div>
          </template>
        </el-table-column>
        <el-table-column label="启用状态" width="100">
          <template #default="{ row }">
            <el-switch
              v-model="row.status"
              :active-value="1"
              :inactive-value="0"
              :disabled="row.type === 'user'"
              @change="handleStatusChange(row)"
            />
          </template>
        </el-table-column>
        <el-table-column prop="last_heartbeat" label="最后心跳时间" min-width="180">
          <template #default="{ row }">
            {{ row.last_heartbeat ? new Date(row.last_heartbeat).toLocaleString() : '-' }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="150" fixed="right">
          <template #default="{ row }">
            <div class="table-action-group">
              <el-button v-if="row.type === 'client'" size="small" type="danger" plain @click="handleDelete(row)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <el-dialog v-model="showCreateDialog" title="新建登录凭证" width="500px">
      <el-form :model="createForm" :rules="rules" ref="createFormRef" label-width="100px">
        <el-form-item label="凭证名称" prop="name">
          <el-input v-model="createForm.name" placeholder="请输入凭证名称，如：测试环境主凭证" />
        </el-form-item>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="showCreateDialog = false">取消</el-button>
          <el-button type="primary" @click="submitCreate" :loading="creating">确定</el-button>
        </span>
      </template>
    </el-dialog>

    <el-dialog v-model="showCredentialsDialog" title="登录凭证创建成功" width="600px" :close-on-click-modal="false" :show-close="false">
      <el-alert
        title="请妥善保存以下凭证，关闭弹窗后将无法再次查看 Client Secret！"
        type="warning"
        show-icon
        :closable="false"
        class="mb-4"
      />
      <el-descriptions :column="1" border>
        <el-descriptions-item label="凭证名称">{{ newClientData?.name }}</el-descriptions-item>
        <el-descriptions-item label="Client ID">
          <span class="copyable" @click="copyText(newClientData?.identifier)">
            {{ newClientData?.identifier }}
            <el-icon><DocumentCopy /></el-icon>
          </span>
        </el-descriptions-item>
        <el-descriptions-item label="Client Secret">
          <span class="copyable" @click="copyText(newClientData?.client_secret)">
            {{ newClientData?.client_secret }}
            <el-icon><DocumentCopy /></el-icon>
          </span>
        </el-descriptions-item>
      </el-descriptions>
      <template #footer>
        <span class="dialog-footer">
          <el-button type="primary" @click="closeCredentialsDialog">我已保存，关闭</el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { Plus, DocumentCopy, Refresh } from '@element-plus/icons-vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminApi } from '@/services/admin'

const clients = ref<any[]>([])
const loading = ref(false)
const showCreateDialog = ref(false)
const creating = ref(false)
const createFormRef = ref()
const createForm = ref({ name: '' })
const rules = {
  name: [{ required: true, message: '请输入凭证名称', trigger: 'blur' }]
}

const showCredentialsDialog = ref(false)
const newClientData = ref<any>(null)
let refreshInterval: any = null

const fetchClients = async () => {
  try {
    const res = await adminApi.request.get('/client/')
    clients.value = Array.isArray(res) ? res : []
  } catch (error: any) {
    ElMessage.error(error.message || '获取凭证列表失败')
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loading.value = true
  fetchClients()
  refreshInterval = setInterval(fetchClients, 10000)
})

onUnmounted(() => {
  if (refreshInterval) {
    clearInterval(refreshInterval)
  }
})

const refreshNow = () => {
  loading.value = true
  fetchClients()
}

const submitCreate = async () => {
  if (!createFormRef.value) return
  await createFormRef.value.validate(async (valid: boolean) => {
    if (valid) {
      creating.value = true
      try {
        const res = await adminApi.request.post('/client/', createForm.value)
        newClientData.value = res || null
        showCreateDialog.value = false
        showCredentialsDialog.value = true
        fetchClients()
      } catch (error: any) {
        ElMessage.error(error.message || '创建登录凭证失败')
      } finally {
        creating.value = false
        createForm.value.name = ''
      }
    }
  })
}

const closeCredentialsDialog = () => {
  showCredentialsDialog.value = false
  newClientData.value = null
}

const handleStatusChange = async (row: any) => {
  try {
    await adminApi.request.put(`/client/${row.id}`, { name: row.name, status: row.status })
    ElMessage.success('状态更新成功')
  } catch (error: any) {
    ElMessage.error(error.message || '状态更新失败')
    row.status = row.status === 1 ? 0 : 1
  }
}

const handleDelete = async (row: any) => {
  try {
    await ElMessageBox.confirm(`确定要删除登录凭证 "${row.name}" 吗？`, '提示', {
      type: 'warning',
      confirmButtonText: '确定',
      cancelButtonText: '取消'
    })

    await adminApi.request.delete(`/client/${row.id}`)
    ElMessage.success('删除成功')
    fetchClients()
  } catch (error: any) {
    if (error !== 'cancel') {
      ElMessage.error(error.message || '删除失败')
    }
  }
}

const copyText = (text: string) => {
  if (!text) return
  navigator.clipboard
    .writeText(text)
    .then(() => {
      ElMessage.success('已复制到剪贴板')
    })
    .catch(() => {
      ElMessage.error('复制失败，请手动复制')
    })
}
</script>

<style scoped>
.status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  display: inline-block;
}

.dot.online {
  background-color: #67c23a;
  box-shadow: 0 0 5px rgba(103, 194, 58, 0.5);
}

.dot.offline {
  background-color: #909399;
}

.copyable {
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 4px;
  color: #409eff;
}

.copyable:hover {
  text-decoration: underline;
}

.mb-4 {
  margin-bottom: 16px;
}

.page-grid :deep(.el-button .el-icon) {
  margin-right: 6px;
}
</style>
