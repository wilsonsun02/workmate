<template>
  <div class="page-grid prompt-page">
    <section class="section-banner glass-panel compact-banner">
      <div>
        <div class="eyebrow">Prompt Control Deck</div>
        <h2>统一维护 Department、Rich、Identity 的当前内容与版本历史</h2>
        <p>左侧选择配置项，右侧直接编辑数据库中的当前内容，并查看修改日志与版本历史。</p>
      </div>
      <div class="action-row">
        <el-button :loading="pageLoading" @click="refreshAll">刷新</el-button>
        <el-button
          type="primary"
          :loading="saving"
          :disabled="!activeFileName || !hasUnsavedChanges || !isActiveFileEditable"
          @click="saveCurrentFile"
        >
          保存当前文件
        </el-button>
      </div>
    </section>

    <section class="stats-grid">
      <article class="glass-panel stat-card">
        <span class="stat-label">配置项总数</span>
        <strong>{{ promptFiles.length }}</strong>
        <small>当前接入的 Prompt 文件</small>
      </article>
      <article class="glass-panel stat-card">
        <span class="stat-label">可编辑项</span>
        <strong>{{ editableCount }}</strong>
        <small>支持直接在线修改</small>
      </article>
      <article class="glass-panel stat-card">
        <span class="stat-label">当前状态</span>
        <strong>{{ hasUnsavedChanges ? '待保存' : '已同步' }}</strong>
        <small>{{ activeFileName ? displayPromptName(activeFileName) : '未选择配置项' }}</small>
      </article>
      <article class="glass-panel stat-card">
        <span class="stat-label">历史记录</span>
        <strong>{{ activeTab === 'logs' ? logs.length : versions.length }}</strong>
        <small>{{ activeTab === 'logs' ? '修改日志条数' : '版本记录条数' }}</small>
      </article>
    </section>

    <section class="workspace-grid">
      <aside class="glass-panel file-sidebar">
        <div class="panel-heading">
          <div>
            <div class="eyebrow">File Map</div>
            <h3>配置项</h3>
          </div>
          <el-tag round>{{ promptFiles.length }} 个</el-tag>
        </div>
        <div v-if="promptFiles.length" class="file-list">
          <button
            v-for="item in promptFiles"
            :key="item.file_name"
            type="button"
            class="file-card"
            :class="{ active: item.file_name === activeFileName }"
            @click="selectFile(item.file_name)"
          >
            <div class="file-card-top">
              <strong>{{ displayPromptName(item.file_name) }}</strong>
              <div class="file-card-tags">
                <el-tag v-if="item.file_name === activeFileName" size="small" type="primary">当前</el-tag>
                <el-tag size="small" :type="item.editable ? 'success' : 'info'">
                  {{ item.editable ? '可编辑' : '只读' }}
                </el-tag>
              </div>
            </div>
            <div class="file-card-meta">
              <span>最新版本 {{ item.version || '0.0.1' }}</span>
            </div>
          </button>
        </div>
        <el-empty v-else description="暂无 Prompt 配置项" />
      </aside>

      <div class="editor-stack">
        <section class="glass-panel editor-panel" v-loading="editorLoading">
          <div class="panel-heading">
            <div>
              <div class="eyebrow">Editor</div>
              <h3>{{ displayPromptName(activeFileName) || '请选择配置项' }}</h3>
              <p class="muted-text">从左侧选择一个配置项开始编辑</p>
            </div>
            <div class="editor-metas">
              <el-tag round>{{ activeFile?.editable ? '可编辑' : '只读' }}</el-tag>
              <el-tag round type="info">当前版本 {{ activeFile?.version || '-' }}</el-tag>
              <el-tag round type="info">SHA {{ shortSha(activeFile?.sha256) }}</el-tag>
              <el-tag round :type="hasUnsavedChanges ? 'warning' : 'success'">
                {{ hasUnsavedChanges ? '待保存' : '已保存' }}
              </el-tag>
            </div>
          </div>

          <p v-if="activeFileName && !isActiveFileEditable" class="readonly-tip">
            该 Prompt 只支持查看和版本管理，当前页面禁止直接编辑保存。
          </p>

          <el-input
            v-model="editorContent"
            type="textarea"
            :rows="22"
            resize="none"
            placeholder="请选择一个 prompt 文件后开始编辑"
            class="prompt-editor"
            :disabled="!activeFileName || !isActiveFileEditable"
          />

          <div class="editor-footer">
            <div class="muted-text">最后保存：{{ formatTime(activeFile?.updated_at || '') }}</div>
            <div class="editor-footer-actions">
              <el-button
                type="primary"
                :loading="saving"
                :disabled="!activeFileName || !hasUnsavedChanges || !isActiveFileEditable"
                @click="saveCurrentFile"
              >
                保存
              </el-button>
            </div>
          </div>
        </section>

        <section class="glass-panel panel-tabs">
          <div class="panel-heading">
            <div>
              <div class="eyebrow">History</div>
              <h3>修改日志与版本历史</h3>
            </div>
            <div class="panel-tab-actions">
              <el-button text :type="activeTab === 'logs' ? 'primary' : 'default'" @click="activeTab = 'logs'">修改日志</el-button>
              <el-button text :type="activeTab === 'versions' ? 'primary' : 'default'" @click="activeTab = 'versions'">版本历史</el-button>
            </div>
          </div>

          <template v-if="activeTab === 'logs'">
            <el-table :data="logs" v-loading="logsLoading" empty-text="当前文件暂无保存日志" border stripe row-key="id">
              <el-table-column prop="created_at" label="时间" min-width="170">
                <template #default="{ row }">{{ formatTime(row.created_at) }}</template>
              </el-table-column>
              <el-table-column prop="operator_username" label="操作人" min-width="120" />
              <el-table-column prop="source_ip" label="IP" min-width="120" />
              <el-table-column label="版本变化" min-width="150">
                <template #default="{ row }">
                  {{ row.before_version }} → {{ row.after_version }}
                </template>
              </el-table-column>
              <el-table-column label="变更摘要" min-width="340">
                <template #default="{ row }">
                  <div class="history-snippet">
                    <strong>旧：</strong>
                    <span>{{ snippet(row.before_content) }}</span>
                    <strong>新：</strong>
                    <span>{{ snippet(row.after_content) }}</span>
                  </div>
                </template>
              </el-table-column>
            </el-table>
          </template>

          <template v-else>
            <el-table :data="versions" v-loading="versionsLoading" empty-text="当前配置项暂无版本历史" border stripe row-key="id">
              <el-table-column prop="version" label="版本" width="120" />
              <el-table-column prop="updated_at" label="记录时间" min-width="170">
                <template #default="{ row }">{{ formatTime(row.updated_at) }}</template>
              </el-table-column>
              <el-table-column prop="operator_username" label="操作人" min-width="120" />
              <el-table-column prop="sha256" label="SHA" min-width="180">
                <template #default="{ row }">{{ shortSha(row.sha256) }}</template>
              </el-table-column>
              <el-table-column label="内容摘要" min-width="320">
                <template #default="{ row }">
                  <span class="muted-text">{{ snippet(row.content) }}</span>
                </template>
              </el-table-column>
            </el-table>
          </template>
        </section>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  adminApi,
  type PromptChangeLogItem,
  type PromptFileItem,
  type PromptFileListItem,
  type PromptVersionHistoryItem
} from '@/services/admin'

const promptFiles = ref<PromptFileListItem[]>([])
const activeFile = ref<PromptFileItem | null>(null)
const activeFileName = ref('')
const editorContent = ref('')
const originalContent = ref('')
const logs = ref<PromptChangeLogItem[]>([])
const versions = ref<PromptVersionHistoryItem[]>([])
const activeTab = ref<'logs' | 'versions'>('logs')

const pageLoading = ref(false)
const editorLoading = ref(false)
const logsLoading = ref(false)
const versionsLoading = ref(false)
const saving = ref(false)

const hasUnsavedChanges = computed(() => editorContent.value !== originalContent.value)
const isActiveFileEditable = computed(() => Boolean(activeFile.value?.editable))
const editableCount = computed(() => promptFiles.value.filter(item => item.editable).length)

const displayPromptName = (value?: string) => String(value || '').replace(/\.md$/i, '')

const formatTime = (value: string) => {
  if (!value) return '-'
  return value.replace('T', ' ').replace(/\.\d+$/, '')
}

const shortSha = (value?: string) => {
  const text = String(value || '').trim()
  return text ? `${text.slice(0, 12)}...` : '-'
}

const snippet = (value: string) => {
  const text = String(value || '').replace(/\s+/g, ' ').trim()
  if (!text) return '空内容'
  return text.length > 120 ? `${text.slice(0, 120)}...` : text
}

const loadPromptFiles = async (preserveSelection = true) => {
  const currentName = preserveSelection ? activeFileName.value : ''
  const res = await adminApi.getPromptFiles()
  promptFiles.value = res.items || []
  if (!promptFiles.value.length) {
    activeFile.value = null
    activeFileName.value = ''
    editorContent.value = ''
    originalContent.value = ''
    return
  }
  const firstFile = promptFiles.value[0]
  const nextName = promptFiles.value.some(item => item.file_name === currentName)
    ? currentName
    : (firstFile?.file_name || '')
  await loadPromptDetail(nextName)
}

const loadPromptDetail = async (fileName: string) => {
  if (!fileName) return
  editorLoading.value = true
  try {
    const res = await adminApi.getPromptFile(fileName)
    activeFile.value = res.data
    activeFileName.value = res.data.file_name
    editorContent.value = res.data.content || ''
    originalContent.value = res.data.content || ''
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '读取 prompt 文件失败')
  } finally {
    editorLoading.value = false
  }
}

const loadLogs = async () => {
  if (!activeFileName.value) {
    logs.value = []
    return
  }
  logsLoading.value = true
  try {
    const res = await adminApi.getPromptFileLogs(activeFileName.value)
    logs.value = res.items || []
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '读取修改日志失败')
  } finally {
    logsLoading.value = false
  }
}

const loadVersions = async () => {
  if (!activeFileName.value) {
    versions.value = []
    return
  }
  versionsLoading.value = true
  try {
    const res = await adminApi.getPromptFileVersions(activeFileName.value)
    versions.value = res.items || []
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '读取发布版本失败')
  } finally {
    versionsLoading.value = false
  }
}

const refreshAll = async () => {
  pageLoading.value = true
  try {
    await loadPromptFiles(true)
    await Promise.all([loadLogs(), loadVersions()])
  } finally {
    pageLoading.value = false
  }
}

const selectFile = async (fileName: string) => {
  if (!fileName || fileName === activeFileName.value) return
  if (hasUnsavedChanges.value) {
    try {
      await ElMessageBox.confirm('当前文件有未保存内容，切换后将放弃这些编辑，是否继续？', '切换文件', {
        confirmButtonText: '继续切换',
        cancelButtonText: '取消',
        type: 'warning'
      })
    } catch {
      return
    }
  }
  await loadPromptDetail(fileName)
  await Promise.all([loadLogs(), loadVersions()])
}

const saveCurrentFile = async () => {
  if (!activeFileName.value || !hasUnsavedChanges.value || !isActiveFileEditable.value) return true
  saving.value = true
  try {
    const res = await adminApi.savePromptFile(activeFileName.value, {
      content: editorContent.value
    })
    ElMessage.success(res.message || '保存成功')
    await Promise.all([loadPromptFiles(true), loadLogs(), loadVersions()])
    return true
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '保存 prompt 文件失败')
    return false
  } finally {
    saving.value = false
  }
}

onMounted(async () => {
  await refreshAll()
})
</script>

<style scoped>
.prompt-page {
  gap: 18px;
}

.stats-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.stat-card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 20px;
}

.stat-card strong {
  font-size: 18px;
  line-height: 1.4;
  word-break: break-word;
}

.stat-label {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.workspace-grid {
  display: grid;
  grid-template-columns: 320px minmax(0, 1fr);
  gap: 18px;
}

.file-sidebar,
.editor-panel,
.panel-tabs {
  padding: 20px;
}

.editor-stack {
  display: grid;
  gap: 18px;
}

.panel-heading {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 16px;
  margin-bottom: 16px;
}

.panel-heading h3 {
  margin: 4px 0 0;
}

.muted-text {
  margin: 6px 0 0;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.file-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.file-card {
  width: 100%;
  text-align: left;
  border: 1px solid rgba(15, 23, 42, 0.08);
  background: rgba(255, 255, 255, 0.72);
  border-radius: 16px;
  padding: 14px;
  transition: all 0.2s ease;
  cursor: pointer;
}

.file-card:hover {
  transform: translateY(-1px);
  border-color: rgba(59, 130, 246, 0.24);
  box-shadow: 0 14px 30px rgba(15, 23, 42, 0.08);
}

.file-card.active {
  border-color: rgba(59, 130, 246, 0.42);
  background: linear-gradient(135deg, rgba(59, 130, 246, 0.12), rgba(14, 165, 233, 0.08));
}

.file-card-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 8px;
}

.file-card-tags {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.file-card p {
  margin: 0 0 10px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  line-height: 1.5;
  word-break: break-all;
}

.file-card-meta {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  flex-wrap: wrap;
}

.editor-metas,
.panel-tab-actions,
.editor-footer-actions {
  display: flex;
  gap: 10px;
  align-items: center;
  flex-wrap: wrap;
}

.readonly-tip {
  margin: 0 0 12px;
  color: var(--el-color-warning);
}

.editor-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16px;
  margin-top: 16px;
}

.editor-footer .muted-text {
  display: flex;
  gap: 16px;
  flex-wrap: wrap;
}

.history-snippet {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 4px 10px;
  align-items: start;
}

@media (max-width: 1280px) {
  .stats-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .workspace-grid {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .stats-grid {
    grid-template-columns: 1fr;
  }

  .panel-heading,
  .editor-footer {
    flex-direction: column;
    align-items: flex-start;
  }

  .file-card-meta {
    flex-direction: column;
  }
}
</style>
