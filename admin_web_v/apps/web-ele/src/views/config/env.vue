<template>
  <div class="page-grid">
    <section class="section-banner glass-panel compact-banner">
      <div>
        <div class="eyebrow">Env Config Center</div>
      </div>
      <div class="action-row">
        <el-button :loading="fetching" @click="fetchConfig">刷新</el-button>
        <el-button plain @click="sectionManagerVisible = true">板块管理</el-button>
        <el-button plain @click="logsVisible = true">查看日志</el-button>
        <el-tag v-if="changedKeys.length" type="warning">待保存 {{ changedKeys.length }} 项</el-tag>
      </div>
    </section>

    <section
      v-for="section in sections"
      :key="section.id"
      class="glass-panel panel-block section-panel"
    >
      <div class="section-heading">
        <div>
          <div class="eyebrow">{{ section.id.toUpperCase() }}</div>
          <h3>{{ section.title }}</h3>
          <p class="section-desc">{{ section.description }}</p>
        </div>
        <div class="section-actions">
          <el-tag round>{{ section.fields.length }} 项</el-tag>
          <el-button
            type="primary"
            :loading="sectionSaving[section.id]"
            :disabled="getSectionChangedKeys(section).length === 0"
            @click="saveSection(section)"
          >
            保存本板块
          </el-button>
          <el-button plain :loading="sectionHiding[section.id]" @click="hideSection(section)">
            隐藏
          </el-button>
          <el-button
            type="danger"
            plain
            :loading="sectionDeleting[section.id]"
            @click="deleteSection(section)"
          >
            删除本板块
          </el-button>
        </div>
      </div>

      <div class="field-grid">
        <el-form-item
          v-for="field in section.fields"
          :key="field.key"
          :label="field.label"
          class="env-form-item"
        >
          <div class="field-control-row">
            <div class="field-control">
              <el-switch
                v-if="field.component === 'switch'"
                v-model="formValues[field.key]"
                inline-prompt
                active-text="开"
                inactive-text="关"
              />
              <el-select
                v-else-if="field.component === 'select'"
                v-model="formValues[field.key]"
                style="width: 100%;"
              >
                <el-option
                  v-for="option in field.options"
                  :key="option.value"
                  :label="option.label"
                  :value="option.value"
                />
              </el-select>
              <el-input
                v-else-if="field.component === 'textarea'"
                v-model="formValues[field.key]"
                type="textarea"
                :rows="3"
                :placeholder="field.default_value || '请输入配置值'"
              />
              <el-input
                v-else
                v-model="formValues[field.key]"
                :show-password="field.component === 'password'"
                :type="field.component === 'password' ? 'password' : 'text'"
                :placeholder="field.default_value || '请输入配置值'"
              />
            </div>
            <el-button
              class="field-delete"
              type="danger"
              text
              :icon="Delete"
              :loading="fieldDeleting[field.key]"
              @click="deleteField(field)"
            />
          </div>
          <div class="field-hints">
            <span v-if="field.default_value">默认值：{{ field.default_value }}</span>
            <span v-if="field.sensitive">敏感项，仅在日志中展示脱敏内容</span>
          </div>
        </el-form-item>
      </div>
    </section>

    <section class="glass-panel panel-block">
      <div class="section-heading">
        <div>
          <div class="eyebrow">Custom Entries</div>
          <h3>其他配置项</h3>
          <p class="section-desc">未预置的环境变量可以在这里继续维护，支持新增与删除。</p>
        </div>
        <div class="section-actions">
          <el-button type="primary" plain @click="addCustomItem">新增配置项</el-button>
          <el-button
            type="primary"
            :loading="customSaving"
            :disabled="customChangedKeys.length === 0"
            @click="saveCustomSection"
          >
            保存本板块
          </el-button>
        </div>
      </div>

      <div v-if="customItems.length" class="custom-list">
        <div v-for="item in customItems" :key="item.id" class="custom-row">
          <el-input v-model="item.key" placeholder="KEY" class="custom-key" />
          <span class="custom-sep">=</span>
          <el-input v-model="item.value" placeholder="VALUE" />
          <el-button type="danger" plain @click="removeCustomItem(item.id)">移除</el-button>
        </div>
      </div>
      <el-empty v-else description="当前没有额外的自定义环境变量" />
    </section>

    <el-dialog v-model="sectionManagerVisible" title="板块管理" width="760">
      <div class="section-manager">
        <div class="section-manager-summary">
          <el-tag type="info">总板块 {{ allSections.length }}</el-tag>
          <el-tag v-if="hiddenSectionIds.length" type="warning">已隐藏板块 {{ hiddenSectionIds.length }}</el-tag>
        </div>
        <el-table :data="allSections" border stripe row-key="id">
          <el-table-column prop="title" label="板块" min-width="160" />
          <el-table-column prop="id" label="标识" min-width="120" />
          <el-table-column label="状态" min-width="120">
            <template #default="{ row }">
              <el-tag :type="hiddenSectionIds.includes(row.id) ? 'warning' : 'success'">
                {{ hiddenSectionIds.includes(row.id) ? '已隐藏' : '显示中' }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="操作" min-width="220">
            <template #default="{ row }">
              <el-button
                v-if="hiddenSectionIds.includes(row.id)"
                type="primary"
                plain
                :loading="sectionRestoring[row.id]"
                @click="restoreSection(row.id)"
              >
                恢复
              </el-button>
              <template v-else>
                <el-button
                  plain
                  :loading="sectionHiding[row.id]"
                  @click="hideSectionById(row.id)"
                >
                  隐藏
                </el-button>
              </template>
            </template>
          </el-table-column>
        </el-table>
      </div>
      <template #footer>
        <el-button @click="sectionManagerVisible = false">关闭</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="logsVisible" title="修改日志" width="1080" @open="fetchLogs">
      <div class="logs-dialog">
        <div class="logs-toolbar">
          <el-tag type="info">记录 {{ logs.length }} 条</el-tag>
          <el-button :loading="logsLoading" @click="fetchLogs">刷新</el-button>
        </div>
        <el-table :data="logs" v-loading="logsLoading" border stripe row-key="id">
          <el-table-column prop="created_at" label="时间" min-width="180">
            <template #default="{ row }">
              {{ formatTime(row.created_at) }}
            </template>
          </el-table-column>
          <el-table-column prop="operator_username" label="操作人" min-width="120" />
          <el-table-column prop="source_ip" label="IP" min-width="120" />
          <el-table-column label="变更键" min-width="260">
            <template #default="{ row }">
              <div class="tag-row">
                <el-tag v-for="key in row.changed_keys" :key="key" size="small">{{ key }}</el-tag>
              </div>
            </template>
          </el-table-column>
          <el-table-column label="变更详情" min-width="340">
            <template #default="{ row }">
              <div class="diff-block">
                <div v-for="key in row.changed_keys" :key="`${row.id}-${key}`" class="diff-line">
                  <strong>{{ key }}</strong>
                  <span>{{ row.before_values[key] || '(空)' }} -> {{ row.after_values[key] || '(空)' }}</span>
                </div>
              </div>
            </template>
          </el-table-column>
        </el-table>
        <el-empty v-if="!logsLoading && logs.length === 0" description="暂无修改日志" />
      </div>
      <template #footer>
        <el-button @click="logsVisible = false">关闭</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
// @ts-nocheck
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  adminApi,
  type EnvChangeLogItem,
  type EnvFieldMeta,
  type EnvFilePayload,
  type EnvSection
} from '@/services/admin'
import { Delete } from '@element-plus/icons-vue'

interface CustomItem {
  id: string
  key: string
  value: string
  originalKey: string
}

const sections = ref<EnvSection[]>([])
const logs = ref<EnvChangeLogItem[]>([])
const configPath = ref('')
const updatedAt = ref('')
const customItems = ref<CustomItem[]>([])
const removedCustomKeys = ref<string[]>([])
const allSections = ref<Array<{ id: string, title: string, description: string, keys: string[] }>>([])
const hiddenSectionIds = ref<string[]>([])
const sectionManagerVisible = ref(false)
const logsVisible = ref(false)
const formValues = reactive<Record<string, string | boolean>>({})
const originalSnapshot = ref<Record<string, string | boolean>>({})

const fetching = ref(false)
const logsLoading = ref(false)
const customSaving = ref(false)
const sectionSaving = reactive<Record<string, boolean>>({})
const sectionDeleting = reactive<Record<string, boolean>>({})
const sectionHiding = reactive<Record<string, boolean>>({})
const sectionRestoring = reactive<Record<string, boolean>>({})
const fieldDeleting = reactive<Record<string, boolean>>({})

const makeCustomItem = (key = '', value = '', originalKey = ''): CustomItem => ({
  id: `${Date.now()}-${Math.random().toString(16).slice(2)}`,
  key,
  value,
  originalKey
})

const fieldMap = computed<Record<string, EnvFieldMeta>>(() => {
  return sections.value.reduce<Record<string, EnvFieldMeta>>((acc, section) => {
    section.fields.forEach((field) => {
      acc[field.key] = field
    })
    return acc
  }, {})
})

const normalizeValue = (field: EnvFieldMeta | undefined, value: unknown): string | boolean => {
  if (field?.component === 'switch') {
    return value === true || String(value ?? '').trim().toLowerCase() === 'true'
  }
  return value == null ? '' : String(value)
}

const buildCurrentValues = () => {
  const values: Record<string, string | boolean> = {}
  sections.value.forEach((section) => {
    section.fields.forEach((field) => {
      values[field.key] = normalizeValue(fieldMap.value[field.key], formValues[field.key])
    })
  })
  customItems.value.forEach((item) => {
    const nextKey = item.key.trim()
    if (!nextKey) return
    values[nextKey] = item.value
  })
  return values
}

const buildSectionValues = (section: EnvSection) => {
  const values: Record<string, string | boolean> = {}
  section.fields.forEach((field) => {
    values[field.key] = normalizeValue(fieldMap.value[field.key], formValues[field.key])
  })
  return values
}

const getSectionChangedKeys = (section: EnvSection) => {
  const current = buildSectionValues(section)
  return section.fields
    .map(field => field.key)
    .filter((key) => String(current[key] ?? '') !== String(originalSnapshot.value[key] ?? ''))
}

const deletedCustomKeys = computed(() => {
  const currentKeys = new Set(customItems.value.map(item => item.key.trim()).filter(Boolean))
  const keys = new Set(removedCustomKeys.value)
  customItems.value.forEach((item) => {
    if (item.originalKey && item.originalKey !== item.key.trim()) {
      keys.add(item.originalKey)
    }
  })
  return Array.from(keys).filter(key => !currentKeys.has(key))
})

const changedKeys = computed(() => {
  const current = buildCurrentValues()
  const original = originalSnapshot.value
  const keys = new Set([
    ...Object.keys(current),
    ...Object.keys(original),
    ...deletedCustomKeys.value
  ])
  return Array.from(keys).filter((key) => {
    if (deletedCustomKeys.value.includes(key)) {
      return key in original
    }
    return String(current[key] ?? '') !== String(original[key] ?? '')
  }).sort()
})

const customChangedKeys = computed(() => {
  const changed = new Set<string>(deletedCustomKeys.value)
  customItems.value.forEach((item) => {
    const nextKey = item.key.trim()
    const originalKey = item.originalKey.trim()
    if (originalKey && originalKey !== nextKey) {
      changed.add(originalKey)
    }
    if (!nextKey) {
      return
    }
    if (originalKey && originalKey !== nextKey) {
      changed.add(nextKey)
      return
    }
    if (String(item.value ?? '') !== String(originalSnapshot.value[nextKey] ?? '')) {
      changed.add(nextKey)
    }
    if (!originalKey && nextKey) {
      changed.add(nextKey)
    }
  })
  return Array.from(changed).filter(Boolean).sort()
})

const applyPayload = (payload: EnvFilePayload) => {
  sections.value = payload.sections || []
  configPath.value = payload.path || ''
  updatedAt.value = payload.updated_at || ''
  removedCustomKeys.value = []
  allSections.value = payload.all_sections || []
  hiddenSectionIds.value = payload.hidden_sections || []

  Object.keys(formValues).forEach((key) => {
    delete formValues[key]
  })

  const snapshot: Record<string, string | boolean> = {}
  sections.value.forEach((section) => {
    section.fields.forEach((field) => {
      const normalized = normalizeValue(field, payload.values?.[field.key] ?? field.value ?? field.default_value)
      formValues[field.key] = normalized
      snapshot[field.key] = normalized
    })
  })

  customItems.value = (payload.unknown_items || []).map((item) => {
    snapshot[item.key] = item.value
    return makeCustomItem(item.key, item.value, item.key)
  })

  originalSnapshot.value = snapshot
}

const fetchConfig = async () => {
  fetching.value = true
  try {
    const payload = await adminApi.getEnvFileConfig()
    applyPayload(payload)
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '获取 `.env` 配置失败')
  } finally {
    fetching.value = false
  }
}

const fetchLogs = async () => {
  logsLoading.value = true
  try {
    const res = await adminApi.getEnvFileConfigLogs()
    logs.value = res.items || []
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '获取日志失败')
  } finally {
    logsLoading.value = false
  }
}

const deleteSection = async (section: EnvSection) => {
  const keys = section.fields.map(field => field.key).filter(Boolean)
  if (!keys.length) return
  try {
    await ElMessageBox.confirm(
      `确认删除「${section.title}」板块下 ${keys.length} 个配置项吗？删除后该板块会被隐藏，配置值将从数据库配置中心移除（字段回到默认值/空值）。`,
      '删除板块',
      {
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
  } catch {
    return
  }
  sectionDeleting[section.id] = true
  try {
    const res = await adminApi.saveEnvFileConfig({
      values: {},
      deleted_keys: keys,
      hidden_sections: [section.id]
    })
    ElMessage.success(res.message || '配置已删除')
    await Promise.all([fetchConfig(), fetchLogs()])
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '删除配置失败')
  } finally {
    sectionDeleting[section.id] = false
  }
}

const deleteField = async (field: EnvFieldMeta) => {
  const key = String(field.key || '').trim()
  if (!key) return
  try {
    await ElMessageBox.confirm(
      `确认删除配置项「${key}」吗？删除后将从页面移除，可在「板块管理」中恢复显示。`,
      '删除配置项',
      {
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
  } catch {
    return
  }
  fieldDeleting[key] = true
  try {
    await adminApi.saveEnvFileConfig({
      values: {},
      deleted_keys: [key],
      hidden_keys: [key]
    })
    ElMessage.success('配置项已删除')
    await Promise.all([fetchConfig(), fetchLogs()])
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '删除配置项失败')
  } finally {
    fieldDeleting[key] = false
  }
}

const hideSectionById = async (sectionId: string) => {
  if (!sectionId) return
  try {
    await ElMessageBox.confirm(
      '确认隐藏该板块吗？隐藏后可在「板块管理」中恢复显示。',
      '隐藏板块',
      {
        confirmButtonText: '确认隐藏',
        cancelButtonText: '取消',
        type: 'warning'
      }
    )
  } catch {
    return
  }
  sectionHiding[sectionId] = true
  try {
    await adminApi.saveEnvFileConfig({
      values: {},
      hidden_sections: [sectionId]
    })
    ElMessage.success('板块已隐藏')
    await Promise.all([fetchConfig(), fetchLogs()])
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '隐藏板块失败')
  } finally {
    sectionHiding[sectionId] = false
  }
}

const hideSection = async (section: EnvSection) => {
  await hideSectionById(section.id)
}

const restoreSection = async (sectionId: string) => {
  if (!sectionId) return
  sectionRestoring[sectionId] = true
  try {
    await adminApi.saveEnvFileConfig({
      values: {},
      shown_sections: [sectionId]
    })
    ElMessage.success('板块已恢复')
    await Promise.all([fetchConfig(), fetchLogs()])
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '恢复板块失败')
  } finally {
    sectionRestoring[sectionId] = false
  }
}

const saveSection = async (section: EnvSection) => {
  const keys = getSectionChangedKeys(section)
  if (!keys.length) return
  const values = buildSectionValues(section)
  sectionSaving[section.id] = true
  try {
    const res = await adminApi.saveEnvFileConfig({
      values: keys.reduce<Record<string, string | boolean>>((acc, key) => {
        acc[key] = values[key]
        return acc
      }, {})
    })
    ElMessage.success(res.message || '配置保存成功')
    await Promise.all([fetchConfig(), fetchLogs()])
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '配置保存失败')
  } finally {
    sectionSaving[section.id] = false
  }
}

const saveCustomSection = async () => {
  if (!customChangedKeys.value.length) return
  const values: Record<string, string | boolean> = {}
  customItems.value.forEach((item) => {
    const nextKey = item.key.trim()
    if (!nextKey) return
    values[nextKey] = item.value
  })
  customSaving.value = true
  try {
    const res = await adminApi.saveEnvFileConfig({
      values,
      deleted_keys: deletedCustomKeys.value
    })
    ElMessage.success(res.message || '配置保存成功')
    await Promise.all([fetchConfig(), fetchLogs()])
  } catch (error: any) {
    ElMessage.error(error.response?.data?.detail || '配置保存失败')
  } finally {
    customSaving.value = false
  }
}

const addCustomItem = () => {
  customItems.value.push(makeCustomItem())
}

const removeCustomItem = (id: string) => {
  const index = customItems.value.findIndex(item => item.id === id)
  if (index === -1) return
  const current = customItems.value[index]
  if (current.originalKey) {
    removedCustomKeys.value = Array.from(new Set([...removedCustomKeys.value, current.originalKey]))
  }
  customItems.value.splice(index, 1)
}

const formatTime = (value: string) => {
  if (!value) return '-'
  return value.replace('T', ' ').replace(/\.\d+$/, '')
}

onMounted(async () => {
  await Promise.all([fetchConfig(), fetchLogs()])
})
</script>

<style scoped>
.banner-desc {
  margin: 8px 0 0;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
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
  word-break: break-all;
}

.stat-label {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.section-manager {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.section-manager-summary {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
}

.guide-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.guide-card {
  padding: 16px;
  border-radius: 14px;
  background: rgba(255, 255, 255, 0.72);
  border: 1px solid rgba(15, 23, 42, 0.06);
}

.guide-card p,
.section-desc,
.field-hints {
  margin: 6px 0 0;
  color: var(--el-text-color-secondary);
  line-height: 1.6;
}

.section-actions {
  display: flex;
  align-items: center;
  gap: 12px;
}

.field-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 18px;
}

.env-form-item {
  margin-bottom: 18px;
}

.field-control-row {
  display: flex;
  align-items: flex-start;
  gap: 12px;
}

.field-control {
  flex: 1;
  min-width: 0;
}

.field-delete {
  flex: 0 0 auto;
  margin-top: 2px;
}

.field-hints {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  font-size: 12px;
  flex-wrap: wrap;
}

.logs-dialog {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.logs-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  flex-wrap: wrap;
}

.custom-list {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.custom-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.custom-key {
  width: 240px;
  flex: 0 0 240px;
}

.custom-sep {
  color: var(--el-text-color-secondary);
}

.tag-row {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.diff-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.diff-line {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

@media (max-width: 1200px) {
  .stats-grid,
  .guide-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}

@media (max-width: 768px) {
  .stats-grid,
  .guide-grid,
  .field-grid {
    grid-template-columns: 1fr;
  }

  .custom-row {
    flex-direction: column;
    align-items: stretch;
  }

  .custom-key {
    width: 100%;
    flex: 1 1 auto;
  }

  .field-control-row {
    flex-direction: column;
    align-items: stretch;
  }

  .field-delete {
    align-self: flex-end;
    margin-top: 0;
  }

  .field-hints {
    flex-direction: column;
    gap: 4px;
  }

  .section-actions {
    width: 100%;
    flex-wrap: wrap;
    justify-content: flex-start;
  }
}
</style>
