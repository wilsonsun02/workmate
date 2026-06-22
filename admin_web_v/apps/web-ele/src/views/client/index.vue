<template>
  <div class="page-grid">
    <section class="section-banner glass-panel compact-banner">
      <div>
        <div class="eyebrow">Client Presence</div>
        <h2>在线用户与客户端连接状态</h2>
        <p>统一查看当前在线连接、身份类型与最后心跳时间，便于排查掉线与登录态异常。</p>
      </div>
      <div class="banner-stats">
        <div>
          <span>在线连接</span>
          <strong>{{ onlineClients.length }}</strong>
        </div>
        <div>
          <span>总客户端</span>
          <strong>{{ clients.length }}</strong>
        </div>
      </div>
    </section>

    <section class="glass-panel panel-block">
      <div class="section-heading section-heading--table">
        <div>
          <div class="eyebrow">Realtime Sessions</div>
          <h3>在线用户</h3>
          <p class="heading-description">默认每 10 秒自动刷新一次，也支持手动立即刷新。</p>
        </div>
        <div class="heading-tags">
          <el-tag type="success" effect="plain">在线 {{ onlineClients.length }}</el-tag>
        </div>
      </div>

      <div class="toolbar-row">
        <div class="toolbar-actions">
          <el-button @click="refreshNow" :loading="loading">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
      </div>

      <el-table
        :data="onlineClients"
        v-loading="loading"
        border
        stripe
        row-key="identifier"
        empty-text="暂无在线用户"
      >
        <el-table-column prop="name" label="用户名称" min-width="180" />
        <el-table-column prop="identifier" label="标识符 (Client ID / 用户名)" min-width="220" show-overflow-tooltip />
        <el-table-column prop="type" label="类型" width="120">
          <template #default="{ row }">
            <el-tag :type="row.type === 'user' ? 'success' : 'info'">
              {{ row.type === 'user' ? '用户' : '客户端' }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="last_heartbeat" label="最后心跳时间" min-width="180">
          <template #default="{ row }">
            {{ formatTime(row.last_heartbeat) }}
          </template>
        </el-table-column>
      </el-table>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from 'vue'
import { Refresh } from '@element-plus/icons-vue'
import { ElMessage } from 'element-plus'
import { adminApi } from '@/services/admin'

const clients = ref<any[]>([])
const loading = ref(false)
let refreshInterval: any = null

const onlineClients = computed(() => clients.value.filter(item => item.is_online))

const fetchClients = async () => {
  try {
    const res = await adminApi.request.get('/client/')
    clients.value = Array.isArray(res) ? res : []
  } catch (error: any) {
    ElMessage.error(error.message || '获取在线用户失败')
  } finally {
    loading.value = false
  }
}

const refreshNow = () => {
  loading.value = true
  fetchClients()
}

const formatTime = (value?: string) => {
  return value ? new Date(value).toLocaleString() : '-'
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

</script>

<style scoped>
.page-grid :deep(.el-button .el-icon) {
  margin-right: 6px;
}
</style>
