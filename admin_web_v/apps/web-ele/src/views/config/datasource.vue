<template>
  <div class="page-grid">
    <section class="section-banner glass-panel compact-banner">
      <div>
        <div class="eyebrow">Integration</div>
        <h2>多租户数据源集成</h2>
        <p>配置并同步第三方系统的组织架构与用户数据，实现账号打通。</p>
      </div>
      <div class="action-row">
        <el-button type="success" plain :icon="Plus" @click="handleAddSource">新增数据源</el-button>
        <el-button class="primary-action" type="primary" :loading="saving" @click="saveAll">保存所有配置</el-button>
      </div>
    </section>

    <section class="stats-grid">
      <article class="glass-panel stat-card">
        <span class="stat-label">数据源总数</span>
        <strong>{{ sources.length }}</strong>
        <small>当前租户集成配置数量</small>
      </article>
      <article class="glass-panel stat-card">
        <span class="stat-label">当前选中</span>
        <strong>{{ currentSource?.tenant_name || '未选择' }}</strong>
        <small>{{ currentSource?.tenant_id || '请选择一个数据源进行编辑' }}</small>
      </article>
      <article class="glass-panel stat-card">
        <span class="stat-label">已配置 Host</span>
        <strong>{{ configuredHostCount }}</strong>
        <small>已填写数据库连接地址的数据源数</small>
      </article>
      <article class="glass-panel stat-card">
        <span class="stat-label">同步状态</span>
        <strong>{{ syncing ? '同步中' : '空闲' }}</strong>
        <small>执行全量同步前会自动保存当前配置</small>
      </article>
    </section>

    <div class="content-grid sidebar-layout">
      <!-- 左侧数据源列表 -->
      <article class="glass-panel panel-block">
        <div class="section-heading">
          <div>
            <div class="eyebrow">Data Sources</div>
            <h3>数据源列表</h3>
            <p class="heading-description">左侧维护租户级来源，右侧集中编辑连接信息与字段映射。</p>
          </div>
          <el-tag type="info">{{ sources.length }} 个来源</el-tag>
        </div>
        
        <el-empty v-if="sources.length === 0" description="暂无数据源" />
        
        <div class="source-list" v-else>
          <div 
            v-for="(source, index) in sources" 
            :key="source.tenant_id"
            class="source-item"
            :class="{ active: currentIndex === index }"
            @click="currentIndex = index"
          >
            <div class="source-info">
              <strong>{{ source.tenant_name || '未命名租户' }}</strong>
              <span>{{ source.connection.host || '未配置Host' }}</span>
            </div>
            <el-button type="danger" :icon="Delete" circle size="small" @click.stop="handleRemoveSource(index)" />
          </div>
        </div>
      </article>

      <!-- 右侧详情配置 -->
      <article class="glass-panel panel-block wide-panel" v-if="currentSource">
        <div class="section-heading">
          <div>
            <div class="eyebrow">Configuration</div>
            <h3>{{ currentSource.tenant_name || '配置详情' }}</h3>
            <p class="heading-description">建议先测试连接，再执行全量同步，避免错误配置写入后续组织数据。</p>
          </div>
          <div class="table-actions">
            <el-button plain :loading="testing" @click="testConnection">测试连接</el-button>
            <el-button type="warning" :loading="syncing" @click="handleSync">执行全量同步</el-button>
          </div>
        </div>

        <el-form :model="currentSource" label-position="top">
          <!-- 基础信息 -->
          <h4>基础信息</h4>
          <el-row :gutter="20">
            <el-col :span="12">
              <el-form-item label="租户ID (自动生成)">
                <el-input v-model="currentSource.tenant_id" disabled />
              </el-form-item>
            </el-col>
            <el-col :span="12">
              <el-form-item label="租户名称">
                <el-input v-model="currentSource.tenant_name" placeholder="例如：集团ERP系统" />
              </el-form-item>
            </el-col>
          </el-row>

          <el-divider border-style="dashed" />

          <!-- 连接配置 -->
          <div class="subsection-header">
            <h4 style="margin: 0;">MySQL 连接配置</h4>
          </div>
          <el-row :gutter="20">
            <el-col :span="16">
              <el-form-item label="Host">
                <el-input v-model="currentSource.connection.host" placeholder="127.0.0.1" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="Port">
                <el-input-number v-model="currentSource.connection.port" :min="1" :max="65535" style="width: 100%" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="Database">
                <el-input v-model="currentSource.connection.database" placeholder="数据库名" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="User">
                <el-input v-model="currentSource.connection.user" placeholder="用户名" />
              </el-form-item>
            </el-col>
            <el-col :span="8">
              <el-form-item label="Password">
                <el-input v-model="currentSource.connection.password" type="password" placeholder="密码" show-password />
              </el-form-item>
            </el-col>
          </el-row>

          <el-divider border-style="dashed" />

          <!-- 字段映射 -->
          <h4>表与字段映射</h4>
          
          <el-alert title="部门表映射" type="info" :closable="false" style="margin-bottom: 12px;" />
          <el-row :gutter="20">
            <el-col :span="6">
              <el-form-item label="第三方部门表名">
                <el-input v-model="currentSource.mapping.dept_table" placeholder="如 departments" />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="部门ID字段">
                <el-input v-model="currentSource.mapping.dept_id_field" placeholder="如 id" />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="部门名称字段">
                <el-input v-model="currentSource.mapping.dept_name_field" placeholder="如 name" />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="父部门ID字段">
                <el-input v-model="currentSource.mapping.dept_parent_id_field" placeholder="如 parent_id" />
              </el-form-item>
            </el-col>
          </el-row>

          <el-alert title="用户表映射" type="info" :closable="false" style="margin-bottom: 12px;" />
          <el-row :gutter="20">
            <el-col :span="6">
              <el-form-item label="第三方用户表名">
                <el-input v-model="currentSource.mapping.user_table" placeholder="如 users" />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="用户ID字段">
                <el-input v-model="currentSource.mapping.user_id_field" placeholder="如 id" />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="登录账号字段">
                <el-input v-model="currentSource.mapping.user_name_field" placeholder="如 username，用于映射登录账号" />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="显示名字段">
                <el-input v-model="currentSource.mapping.user_display_name_field" placeholder="如 name，不填则回退账号字段" />
              </el-form-item>
            </el-col>
            <el-col :span="6">
              <el-form-item label="归属部门ID字段">
                <el-input v-model="currentSource.mapping.user_dept_id_field" placeholder="如 dept_id" />
              </el-form-item>
            </el-col>
          </el-row>

        </el-form>
      </article>
      
      <article class="glass-panel panel-block wide-panel" v-else>
        <el-empty description="请在左侧选择或新增一个数据源" />
      </article>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminApi, type ThirdPartyDbConfig } from '@/services/admin'
import { Plus, Delete } from '@element-plus/icons-vue'
const sources = ref<ThirdPartyDbConfig[]>([])
const currentIndex = ref(-1)
const saving = ref(false)
const testing = ref(false)
const syncing = ref(false)
const configuredHostCount = computed(() => sources.value.filter(item => item.connection?.host).length)

const currentSource = computed(() => {
  if (currentIndex.value >= 0 && currentIndex.value < sources.value.length) {
    return sources.value[currentIndex.value]
  }
  return null
})

const generateUUID = () => {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    var r = Math.random() * 16 | 0, v = c == 'x' ? r : (r & 0x3 | 0x8);
    return v.toString(16);
  });
}

const fetchSources = async () => {
  try {
    sources.value = await adminApi.getThirdPartyDbs()
    if (sources.value.length > 0) {
      currentIndex.value = 0
    }
  } catch (e) {
    ElMessage.error('获取数据源配置失败')
  }
}

const handleAddSource = () => {
  sources.value.push({
    tenant_id: generateUUID(),
    tenant_name: '新建数据源',
    connection: { host: '', port: 3306, user: '', password: '', database: '' },
    mapping: {
      dept_table: 'sys_dept', dept_id_field: 'id', dept_name_field: 'name', dept_parent_id_field: 'parent_id',
      user_table: 'sys_user', user_id_field: 'id', user_name_field: 'username', user_display_name_field: 'name', user_dept_id_field: 'dept_id'
    }
  })
  currentIndex.value = sources.value.length - 1
}

const handleRemoveSource = (index: number) => {
  ElMessageBox.confirm('确定移除该数据源配置吗？', '提示', { type: 'warning' }).then(() => {
    sources.value.splice(index, 1)
    if (currentIndex.value >= sources.value.length) {
      currentIndex.value = sources.value.length - 1
    }
  }).catch(() => {})
}

const saveAll = async () => {
  saving.value = true
  try {
    await adminApi.saveThirdPartyDbs(sources.value)
    ElMessage.success('配置保存成功')
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    saving.value = false
  }
}

const testConnection = async () => {
  if (!currentSource.value) return
  testing.value = true
  try {
    const res = await adminApi.testThirdPartyDbConnection(currentSource.value.connection)
    if (res.success) {
      ElMessage.success('连接成功')
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '连接失败')
  } finally {
    testing.value = false
  }
}

const handleSync = async () => {
  if (!currentSource.value) return
  
  ElMessageBox.confirm('全量同步将读取外部库并覆盖本地数据，是否继续？', '高危操作', {
    confirmButtonText: '立即同步',
    cancelButtonText: '取消',
    type: 'warning'
  }).then(async () => {
    syncing.value = true
    try {
      // 必须先保存最新配置
      await adminApi.saveThirdPartyDbs(sources.value)
      
      const res = await adminApi.syncTenantData(currentSource.value!.tenant_id)
      if (res.success) {
        ElMessage.success(`同步完成！同步部门: ${res.stats.dept_synced}, 同步用户: ${res.stats.user_synced}`)
      }
    } catch (e: any) {
      ElMessage.error(e.response?.data?.detail || '同步失败')
    } finally {
      syncing.value = false
    }
  }).catch(() => {})
}

onMounted(fetchSources)
</script>

<style scoped>
.source-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.source-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 16px;
  border-radius: 8px;
  background: var(--el-fill-color-light);
  border: 1px solid var(--el-border-color-light);
  cursor: pointer;
  transition: all 0.2s;
}

.source-item:hover {
  border-color: var(--el-border-color);
}

.source-item.active {
  background: rgba(var(--el-color-primary-rgb), 0.1);
  border-color: var(--el-color-primary);
}

.source-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.source-info strong {
  font-size: 14px;
  color: var(--el-text-color-primary);
}

.source-info span {
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.subsection-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

@media (max-width: 768px) {
  .subsection-header {
    flex-direction: column;
    align-items: flex-start;
  }
}
</style>
