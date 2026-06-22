<template>
  <section class="prefs-shell" v-loading="loading">
    <header class="prefs-header">
      <div class="prefs-heading">
        <h4>员工偏好（长期记忆）</h4>
        <p class="prefs-subtitle">用于控制该员工在执行任务时的默认偏好。</p>
      </div>
      <el-button text @click="fetchRows">刷新</el-button>
    </header>

    <div v-if="!loading && !rows.length" class="prefs-empty">暂无偏好</div>

    <div class="prefs-list">
      <div v-for="row in rows" :key="row.pref_key" class="prefs-card">
        <div class="prefs-card-content">
          <div class="prefs-card-title">{{ row.pref_key }}</div>
          <div class="prefs-card-value">{{ row.pref_value }}</div>
          <div class="prefs-card-time">{{ formatTime(row.updated_at || row.created_at) }}</div>
        </div>
        <div class="prefs-card-actions">
          <el-button size="small" @click="openEdit(row)">编辑</el-button>
          <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
        </div>
      </div>
    </div>

    <el-dialog v-model="dialogVisible" title="编辑偏好" width="680px">
      <el-form :model="dialogForm" label-position="top">
        <el-form-item label="Key">
          <el-input v-model="dialogForm.pref_key" disabled />
        </el-form-item>
        <el-form-item label="Value">
          <el-input v-model="dialogForm.pref_value" type="textarea" :rows="10" placeholder="支持 JSON 或纯文本" />
        </el-form-item>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="dialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="saving" @click="save">保存</el-button>
        </span>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminApi, type UserItem, type UserPreferenceItem } from '@/services/admin'

const props = defineProps<{
  user: UserItem
  active: boolean
}>()

const loading = ref(false)
const saving = ref(false)
const rows = ref<UserPreferenceItem[]>([])

const dialogVisible = ref(false)
const dialogForm = reactive({
  pref_key: '',
  pref_value: ''
})

const formatTime = (value?: string) => {
  const text = String(value || '').trim()
  if (!text) {
    return ''
  }
  return text.replace('T', ' ').split('.')[0]
}

const fetchRows = async () => {
  const username = String(props.user.username || '').trim()
  const userId = String(props.user.id || '').trim()
  if (!username && !userId) {
    rows.value = []
    return
  }
  loading.value = true
  try {
    const res = username
      ? await adminApi.getUserPreferencesByUsername(username)
      : await adminApi.getUserPreferences(userId)
    if (res.success) {
      const list = res.data || []
      rows.value = list
        .slice()
        .sort((a, b) => String(b.updated_at || b.created_at).localeCompare(String(a.updated_at || a.created_at)))
    }
  } catch (_e) {
    ElMessage.error('获取偏好失败')
  } finally {
    loading.value = false
  }
}

const openEdit = (row: UserPreferenceItem) => {
  dialogForm.pref_key = row.pref_key
  dialogForm.pref_value = row.pref_value
  dialogVisible.value = true
}

const save = async () => {
  const key = dialogForm.pref_key.trim()
  if (!key) {
    ElMessage.warning('Key 不能为空')
    return
  }
  if (!props.user.id) {
    ElMessage.error('缺少用户ID，无法保存')
    return
  }
  saving.value = true
  try {
    await adminApi.saveUserPreference(props.user.id, key, dialogForm.pref_value)
    ElMessage.success('已保存')
    dialogVisible.value = false
    fetchRows()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

const remove = async (row: UserPreferenceItem) => {
  if (!props.user.id) {
    ElMessage.error('缺少用户ID，无法删除')
    return
  }
  ElMessageBox.confirm(`确定要删除偏好 "${row.pref_key}" 吗？`, '删除确认', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'warning',
  }).then(async () => {
    try {
      await adminApi.deleteUserPreference(props.user.id, row.pref_key)
      ElMessage.success('已删除')
      fetchRows()
    } catch (e: any) {
      ElMessage.error(e.response?.data?.detail || '删除失败')
    }
  })
}

watch(
  () => [props.active, props.user.id] as const,
  ([active]) => {
    if (active) {
      fetchRows()
    }
  },
  { immediate: true }
)
</script>

<style scoped>
.prefs-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 12px;
}

.prefs-heading h4 {
  margin: 0;
  font-size: 16px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.prefs-subtitle {
  margin: 6px 0 0;
  font-size: 12px;
  line-height: 18px;
  color: var(--el-text-color-secondary);
}

.prefs-empty {
  padding: 28px 0;
  text-align: center;
  color: var(--el-text-color-secondary);
}

.prefs-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.prefs-card {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  padding: 14px 16px;
  border-radius: 12px;
  background: var(--el-bg-color);
  border: 1px solid var(--el-border-color-lighter);
  box-shadow: 0 6px 20px rgba(17, 24, 39, 0.06);
}

.prefs-card-content {
  min-width: 0;
  flex: 1;
}

.prefs-card-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.prefs-card-value {
  margin-top: 6px;
  font-size: 13px;
  line-height: 20px;
  color: var(--el-text-color-regular);
  display: -webkit-box;
  -webkit-box-orient: vertical;
  -webkit-line-clamp: 4;
  overflow: hidden;
  word-break: break-word;
}

.prefs-card-time {
  margin-top: 8px;
  font-size: 12px;
  color: var(--el-text-color-secondary);
}

.prefs-card-actions {
  display: flex;
  flex-shrink: 0;
  gap: 10px;
  padding-top: 2px;
}
</style>
