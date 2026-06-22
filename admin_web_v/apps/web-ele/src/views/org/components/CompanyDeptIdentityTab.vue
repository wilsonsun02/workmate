<template>
  <div class="prompt-embed">
    <div class="embed-grid" :class="{ 'embed-grid--single': !showSidebar }">
      <aside v-if="showSidebar" class="glass-panel panel-block embed-sidebar" v-loading="loadingFiles">
        <div class="section-heading">
          <div>
            <div class="eyebrow">Prompt Files</div>
            <h3>{{ title }}</h3>
          </div>
        </div>
        <div class="file-list">
          <button
            v-for="file in files"
            :key="file.file_name"
            type="button"
            class="file-item"
            :class="{ active: file.file_name === activeFileName }"
            @click="selectFile(file.file_name)"
          >
            <strong>{{ displayName(file.file_name) }}</strong>
            <span class="muted-text">v{{ file.version || '-' }}</span>
          </button>
        </div>
      </aside>

      <section class="glass-panel panel-block embed-editor" v-loading="loadingDetail">
        <div class="section-heading">
          <div>
            <div class="eyebrow">Editor</div>
            <h3>{{ displayName(activeFileName) || '请选择配置项' }}</h3>
          </div>
          <div class="table-actions">
            <el-button size="small" type="success" @click="refresh" :loading="loadingFiles || loadingDetail">刷新</el-button>
            <el-button size="small" type="danger" :disabled="!activeFileName || !dirty" :loading="saving" @click="save">保存</el-button>
          </div>
        </div>

        <el-input
          v-model="content"
          type="textarea"
          :rows="18"
          resize="none"
          :disabled="!activeFileName"
          placeholder="请选择一个配置项后开始编辑"
        />

        <el-tabs v-model="activeTab" style="margin-top: 14px;">
          <el-tab-pane label="修改日志" name="logs">
            <el-table :data="logs" v-loading="logsLoading" border stripe empty-text="暂无日志">
              <el-table-column prop="created_at" label="时间" min-width="170" />
              <el-table-column prop="operator_username" label="操作人" min-width="120" />
              <el-table-column label="版本变化" min-width="150">
                <template #default="{ row }">{{ row.before_version }} → {{ row.after_version }}</template>
              </el-table-column>
              <el-table-column prop="after_sha256" label="SHA" min-width="160" show-overflow-tooltip />
            </el-table>
          </el-tab-pane>
          <el-tab-pane label="版本历史" name="versions">
            <el-table :data="versions" v-loading="versionsLoading" border stripe empty-text="暂无版本">
              <el-table-column prop="version" label="版本" width="120" />
              <el-table-column prop="updated_at" label="记录时间" min-width="170" />
              <el-table-column prop="operator_username" label="操作人" min-width="120" />
              <el-table-column prop="sha256" label="SHA" min-width="160" show-overflow-tooltip />
            </el-table>
          </el-tab-pane>
        </el-tabs>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import {
  adminApi,
  type PromptChangeLogItem,
  type PromptFileItem,
  type PromptFileListItem,
  type PromptOwnerType,
  type PromptOwnerParams,
  type PromptVersionHistoryItem
} from '@/services/admin'

const props = withDefaults(defineProps<{
  allowedFiles?: string[]
  title?: string
  defaultFileName?: string
  ownerType?: PromptOwnerType
  ownerId?: string
}>(), {
  allowedFiles: () => ['department.md', 'rich.md', 'identity.md'],
  title: '公司、部门与员工设定',
  defaultFileName: '',
  ownerType: 'root',
  ownerId: 'root',
})

const files = ref<PromptFileListItem[]>([])
const activeFile = ref<PromptFileItem | null>(null)
const activeFileName = ref('')
const content = ref('')
const original = ref('')

const logs = ref<PromptChangeLogItem[]>([])
const versions = ref<PromptVersionHistoryItem[]>([])
const activeTab = ref<'logs' | 'versions'>('logs')

const loadingFiles = ref(false)
const loadingDetail = ref(false)
const saving = ref(false)
const logsLoading = ref(false)
const versionsLoading = ref(false)

const dirty = computed(() => content.value !== original.value)
const showSidebar = computed(() => (props.allowedFiles || []).length > 1)
const title = computed(() => String(props.title || '').trim() || '设定')
const ownerParams = computed<PromptOwnerParams>(() => ({
  owner_type: props.ownerType,
  owner_id: props.ownerId,
}))

const displayName = (name?: string) => String(name || '').replace(/\.md$/i, '')

const loadFiles = async () => {
  loadingFiles.value = true
  try {
    const res = await adminApi.getPromptFiles(ownerParams.value)
    const whitelist = (props.allowedFiles || []).map((item) => String(item || '').trim()).filter(Boolean)
    let items = (res.items || []).filter(item => whitelist.includes(item.file_name))
    if (items.length === 0 && whitelist.length > 0) {
      const preferred = String(props.defaultFileName || '').trim()
      const targetName = preferred || whitelist[0] || ''
      if (targetName) {
        await loadDetail(targetName)
        const seeded = await adminApi.getPromptFiles(ownerParams.value)
        items = (seeded.items || []).filter(item => whitelist.includes(item.file_name))
      }
    }
    files.value = items
    const hasActive = items.some((item) => item.file_name === activeFileName.value)
    const preferred = String(props.defaultFileName || '').trim()
    const preferredExists = preferred ? items.some((item) => item.file_name === preferred) : false
    const next = hasActive
      ? activeFileName.value
      : (preferredExists ? preferred : (items[0]?.file_name || ''))
    if (next) {
      await selectFile(next)
    }
  } catch (_e) {
    ElMessage.error('加载配置项失败')
  } finally {
    loadingFiles.value = false
  }
}

const loadDetail = async (fileName: string) => {
  if (!fileName) return
  loadingDetail.value = true
  try {
    const res = await adminApi.getPromptFile(fileName, ownerParams.value)
    activeFile.value = res.data
    activeFileName.value = res.data.file_name
    content.value = res.data.content || ''
    original.value = content.value
    loadLogs()
    loadVersions()
  } catch (_e) {
    ElMessage.error('加载内容失败')
  } finally {
    loadingDetail.value = false
  }
}

const selectFile = async (fileName: string) => {
  if (fileName === activeFileName.value) return
  if (dirty.value) {
    ElMessage.warning('当前内容未保存，请先保存或刷新')
    return
  }
  await loadDetail(fileName)
}

const save = async () => {
  if (!activeFileName.value) return
  saving.value = true
  try {
    const res = await adminApi.savePromptFile(activeFileName.value, { content: content.value }, ownerParams.value)
    if (res.success) {
      ElMessage.success(res.changed ? '已保存' : '内容未变化')
      original.value = content.value
      loadFiles()
      loadLogs()
      loadVersions()
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

const loadLogs = async () => {
  if (!activeFileName.value) return
  logsLoading.value = true
  try {
    const res = await adminApi.getPromptFileLogs(activeFileName.value, 30, ownerParams.value)
    logs.value = res.items || []
  } catch (_e) {
    logs.value = []
  } finally {
    logsLoading.value = false
  }
}

const loadVersions = async () => {
  if (!activeFileName.value) return
  versionsLoading.value = true
  try {
    const res = await adminApi.getPromptFileVersions(activeFileName.value, 30, ownerParams.value)
    versions.value = res.items || []
  } catch (_e) {
    versions.value = []
  } finally {
    versionsLoading.value = false
  }
}

const refresh = async () => {
  await loadFiles()
  if (activeFileName.value) {
    await loadDetail(activeFileName.value)
  }
}

onMounted(loadFiles)

watch(
  () => [props.ownerType, props.ownerId, JSON.stringify(props.allowedFiles || [])],
  () => {
    activeFile.value = null
    activeFileName.value = ''
    content.value = ''
    original.value = ''
    logs.value = []
    versions.value = []
    loadFiles()
  }
)
</script>

<style scoped>
.embed-grid {
  display: grid;
  grid-template-columns: 260px 1fr;
  gap: 16px;
}

.embed-grid--single {
  grid-template-columns: 1fr;
}

.embed-sidebar {
  padding: 16px;
}

.file-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.file-item {
  border: 1px solid var(--el-border-color-light);
  border-radius: 12px;
  padding: 10px 12px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: transparent;
  cursor: pointer;
  text-align: left;
}

.file-item.active {
  border-color: var(--el-color-primary);
}

.embed-editor {
  padding: 16px;
}

@media (max-width: 960px) {
  .embed-grid {
    grid-template-columns: 1fr;
  }
}
</style>
