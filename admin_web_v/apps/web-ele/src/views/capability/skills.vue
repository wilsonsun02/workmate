<template>
  <div class="page-grid skill-page">
    <section class="glass-panel panel-block">
      <div class="section-heading section-heading--table">
        <div>
          <div class="eyebrow">SKILLS Service Management</div>
          <h2>SKILLS 服务管理</h2>
          <p class="heading-description">
            统一查看技能元数据、启用状态、打包结果，并保留编辑、授权和在线文件发布能力。
          </p>
        </div>
        <div class="heading-tags">
          <el-tag type="info">当前第 {{ pager.page }} 页</el-tag>
          <el-tag type="success">每页 {{ pager.pageSize }} 条</el-tag>
        </div>
      </div>

      <div class="toolbar-row">
        <el-upload
          action="#"
          :show-file-list="false"
          :http-request="handleUpload"
          accept=".zip"
        >
          <el-button :loading="uploading" type="primary" plain>
            上传 ZIP 技能包
          </el-button>
        </el-upload>
        <el-input
          v-model="keyword"
          clearable
          placeholder="按技能名称或描述检索"
          class="search-input"
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        >
          <template #append>
            <el-button :loading="fetching" @click="handleSearch">检索</el-button>
          </template>
        </el-input>
      </div>

      <div class="table-scroll-wrap">
        <el-table
          :data="skillsList"
          border
          stripe
          row-key="name"
          table-layout="fixed"
          v-loading="fetching"
          empty-text="暂无技能数据"
          class="skill-table"
          :header-cell-style="{ background: '#fafafa', fontWeight: '600', color: '#303133', padding: '12px 16px' }"
          :cell-style="{ padding: '12px 16px', verticalAlign: 'middle' }"
        >
          <el-table-column label="技能名称" width="200" fixed="left">
            <template #default="{ row }">
              <el-tooltip :content="row.name" placement="top" :show-after="300">
                <span class="cell-text-ellipsis skill-name">{{ row.name }}</span>
              </el-tooltip>
            </template>
          </el-table-column>

          <el-table-column label="描述" min-width="240">
            <template #default="{ row }">
              <el-tooltip
                :content="row.description || '暂无描述'"
                placement="top"
                :show-after="300"
                :disabled="!row.description"
              >
                <span class="cell-text-ellipsis skill-desc">{{ row.description || '暂无描述' }}</span>
              </el-tooltip>
            </template>
          </el-table-column>

          <el-table-column label="最新版本" width="120" align="center">
            <template #default="{ row }">
              <el-tag size="small" type="info">{{ formatVersion(row.latest_version) }}</el-tag>
            </template>
          </el-table-column>

          <!-- <el-table-column label="历史包数" width="100" align="center">
            <template #default="{ row }">
              <span class="meta-text">{{ row.package_count ?? 0 }}</span>
            </template>
          </el-table-column> -->

          <el-table-column label="包状态" width="140" align="center">
            <template #default="{ row }">
              <el-tag :type="row.oss_packaged ? 'success' : 'warning'" size="small">
                {{ row.oss_packaged ? '已上传 OSS' : '待上传 OSS' }}
              </el-tag>
            </template>
          </el-table-column>

          <el-table-column label="启用状态" width="120" align="center">
            <template #default="{ row }">
              <el-switch
                v-model="row.enabled"
                inline-prompt
                active-text="开"
                inactive-text="关"
                :loading="savingSkillName === row.name"
                @change="(value) => handleToggleEnabled(row, value)"
              />
            </template>
          </el-table-column>

          <el-table-column label="操作" width="420">
            <template #default="{ row }">
              <div class="table-action-group">
                <el-button size="small" type="primary" plain @click="openEditDialog(row)">编辑</el-button>
                <el-button size="small" @click="openAllocations(row.name)">授权</el-button>
                <el-button size="small" @click="openSkillEditor(row.name)">文件编辑</el-button>
                <el-tooltip
                  :content="row.oss_packaged ? '下载当前技能最新包' : '尚未打包，先执行一键打包并上传 OSS'"
                  placement="top"
                >
                  <el-button
                    size="small"
                    type="success"
                    plain
                    :disabled="!row.oss_packaged"
                    :loading="downloadingSkillName === row.name"
                    @click="downloadLatestPackage(row)"
                  >
                    下载
                  </el-button>
                </el-tooltip>
                <el-popconfirm
                  title="确定要删除这个技能吗？物理文件和权限配置将被永久删除。"
                  width="220"
                  @confirm="handleDelete(row.name)"
                >
                  <template #reference>
                    <el-button size="small" type="danger" plain>删除</el-button>
                  </template>
                </el-popconfirm>
              </div>
            </template>
          </el-table-column>
        </el-table>
      </div>

      <div class="pagination-wrap">
        <el-pagination
          background
          layout="total, sizes, prev, pager, next"
          :total="total"
          :page-size="pager.pageSize"
          :page-sizes="[10, 20, 50, 100]"
          :current-page="pager.page"
          @current-change="handlePageChange"
          @size-change="handleSizeChange"
        />
      </div>
    </section>

    <el-dialog v-model="allocationsVisible" :title="`技能授权 - ${currentSkillName}`" width="600px">
      <div v-loading="allocationsLoading">
        <el-space direction="vertical" fill :size="20">
          <el-descriptions title="分配给用户的权限" :column="1" border>
            <el-descriptions-item label="人员列表">
              <el-space v-if="allocationsData.users.length" wrap>
                <el-tag v-for="u in allocationsData.users" :key="u.username" :type="u.action === 'allow' ? 'success' : 'danger'">
                  {{ u.username }} ({{ u.action }})
                </el-tag>
              </el-space>
              <span v-else>暂无</span>
            </el-descriptions-item>
          </el-descriptions>

          <el-descriptions title="分配给角色的权限" :column="1" border>
            <el-descriptions-item label="角色列表">
              <el-space v-if="allocationsData.roles.length" wrap>
                <el-tag v-for="r in allocationsData.roles" :key="r.role_name" :type="r.action === 'allow' ? 'success' : 'danger'">
                  {{ r.role_name }} ({{ r.action }})
                </el-tag>
              </el-space>
              <span v-else>暂无</span>
            </el-descriptions-item>
          </el-descriptions>

          <el-descriptions title="分配给部门的权限" :column="1" border>
            <el-descriptions-item label="部门列表">
              <el-space v-if="allocationsData.depts.length" wrap>
                <el-tag v-for="d in allocationsData.depts" :key="d.dept_name" :type="d.action === 'allow' ? 'success' : 'danger'">
                  {{ d.dept_name }} ({{ d.action }})
                </el-tag>
              </el-space>
              <span v-else>暂无</span>
            </el-descriptions-item>
          </el-descriptions>
        </el-space>
      </div>
    </el-dialog>

    <el-dialog v-model="editDialogVisible" title="编辑技能" width="500px">
      <el-form :model="editForm" label-width="80px">
        <el-form-item label="技能名称">
          <el-input v-model="editForm.name" disabled />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="editForm.description" type="textarea" :rows="4" />
        </el-form-item>
        <el-form-item label="状态">
          <el-switch v-model="editForm.enabled" active-text="启用" inactive-text="停用" />
        </el-form-item>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="editDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="savingSingle" @click="saveSingleSkill">保存</el-button>
        </span>
      </template>
    </el-dialog>

    <el-dialog v-model="editorVisible" :title="`技能文件编辑 - ${editingSkillName}`" width="1100px" top="4vh">
      <div class="editor-layout">
        <div class="editor-files">
          <div class="editor-toolbar">
            <div class="editor-title">文件列表</div>
            <el-button size="small" @click="refreshSkillFiles" :loading="editorLoading">刷新</el-button>
          </div>
          <el-scrollbar height="520px">
            <div
              v-for="node in skillFiles"
              :key="node.path"
              class="editor-file-item"
              :class="{ active: selectedFilePath === node.path, dir: node.is_dir }"
              @click="selectSkillFile(node)"
            >
              <span>{{ node.path }}</span>
              <el-tag v-if="!node.is_dir" size="small" :type="node.is_text ? 'success' : 'info'">
                {{ node.is_text ? '文本' : '二进制' }}
              </el-tag>
            </div>
          </el-scrollbar>
        </div>
        <div class="editor-content">
          <div class="editor-toolbar">
            <div class="editor-title">{{ selectedFilePath || '请选择文件' }}</div>
            <el-tag v-if="selectedFilePath" :type="selectedFileIsText ? 'success' : 'warning'">
              {{ selectedFileIsText ? '可编辑文本文件' : '二进制文件（只读）' }}
            </el-tag>
          </div>
          <el-input
            v-if="selectedFilePath && selectedFileIsText"
            v-model="selectedFileContent"
            type="textarea"
            :rows="24"
            resize="none"
          />
          <el-empty v-else-if="selectedFilePath && !selectedFileIsText" description="该文件为二进制，不支持在线编辑" />
          <el-empty v-else description="请选择要编辑的文件" />
        </div>
      </div>
      <template #footer>
        <el-button @click="editorVisible = false">关闭</el-button>
        <el-button
          type="primary"
          :disabled="!selectedFilePath || !selectedFileIsText"
          :loading="savingFile"
          @click="saveCurrentFile"
        >
          仅保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
// @ts-nocheck
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import {
  adminApi,
  type SkillFileNode,
  type SkillItem,
} from '@/services/admin'

const skillsList = ref<SkillItem[]>([])
const total = ref(0)
const fetching = ref(false)
const uploading = ref(false)
const packaging = ref(false)
const downloadingSkillName = ref('')
const savingSkillName = ref('')
const keyword = ref('')

const pager = ref({
  page: 1,
  pageSize: 10,
})

const allocationsVisible = ref(false)
const allocationsLoading = ref(false)
const currentSkillName = ref('')
const allocationsData = ref({
  users: [] as any[],
  roles: [] as any[],
  depts: [] as any[],
})

const editDialogVisible = ref(false)
const savingSingle = ref(false)
const editForm = ref({
  name: '',
  description: '',
  enabled: true,
})

const editorVisible = ref(false)
const editorLoading = ref(false)
const savingFile = ref(false)
const editingSkillName = ref('')
const skillFiles = ref<SkillFileNode[]>([])
const selectedFilePath = ref('')
const selectedFileContent = ref('')
const selectedFileIsText = ref(false)

const enabledCount = computed(() => skillsList.value.filter((item) => item.enabled).length)
const packagedCount = computed(() => skillsList.value.filter((item) => item.oss_packaged).length)
const unpackagedCount = computed(() => skillsList.value.filter((item) => !item.oss_packaged).length)

const formatVersion = (version?: string) => (version ? `v${version}` : '未发布')

const fetchSkills = async () => {
  fetching.value = true
  try {
    const res = await adminApi.getSkillsPaginated({
      page: pager.value.page,
      page_size: pager.value.pageSize,
      keyword: keyword.value.trim() || undefined,
    })
    if (res.success) {
      skillsList.value = res.data || []
      total.value = res.total || 0
    }
  } catch {
    ElMessage.error('获取 Skills 列表失败')
  } finally {
    fetching.value = false
  }
}

const refreshAfterMutation = async () => {
  if (skillsList.value.length === 1 && pager.value.page > 1 && total.value > 1) {
    pager.value.page -= 1
  }
  await fetchSkills()
}

const openEditDialog = (skill: SkillItem) => {
  editForm.value = {
    name: skill.name,
    description: skill.description || '',
    enabled: skill.enabled,
  }
  editDialogVisible.value = true
}

const saveSingleSkill = async () => {
  savingSingle.value = true
  try {
    await adminApi.saveSkills([
      {
        name: editForm.value.name,
        description: editForm.value.description,
        enabled: editForm.value.enabled,
      },
    ])
    ElMessage.success('技能修改成功')
    editDialogVisible.value = false
    await fetchSkills()
  } catch (e: any) {
    ElMessage.error(`修改失败: ${e.response?.data?.detail || e.message || '未知错误'}`)
  } finally {
    savingSingle.value = false
  }
}

const handleUpload = async (options: any) => {
  const { file } = options
  uploading.value = true
  try {
    const res = await adminApi.uploadSkill(file)
    if (res.success) {
      ElMessage.success(`技能 ${res.name} 上传成功`)
      pager.value.page = 1
      await fetchSkills()
    }
  } catch (e: any) {
    ElMessage.error(`上传失败: ${e.response?.data?.detail || e.message || '未知错误'}`)
  } finally {
    uploading.value = false
  }
}

const handleDelete = async (skillName: string) => {
  try {
    const res = await adminApi.deleteSkill(skillName)
    if (res.success) {
      ElMessage.success('删除成功')
      await refreshAfterMutation()
    }
  } catch (e: any) {
    ElMessage.error(`删除失败: ${e.response?.data?.detail || e.message || '未知错误'}`)
  }
}

const handleToggleEnabled = async (row: SkillItem, enabled: boolean) => {
  if (!row?.name) return
  const previousEnabled = !enabled
  savingSkillName.value = row.name
  try {
    await adminApi.saveSkills([
      {
        name: row.name,
        description: row.description,
        enabled,
      },
    ])
    ElMessage.success(`技能 ${row.name} 已${enabled ? '启用' : '停用'}`)
  } catch (e: any) {
    row.enabled = previousEnabled
    ElMessage.error(`状态更新失败: ${e.response?.data?.detail || e.message || '未知错误'}`)
  } finally {
    savingSkillName.value = ''
  }
}

const handlePackageAll = async () => {
  packaging.value = true
  try {
    const res = await adminApi.packageAllSkills()
    if (res.success) {
      ElMessage.success(`总计 ${res.data.total}，成功 ${res.data.success}，失败 ${res.data.failed}`)
      await fetchSkills()
    }
  } catch (e: any) {
    ElMessage.error(`打包上传失败: ${e.response?.data?.detail || e.message || '未知错误'}`)
  } finally {
    packaging.value = false
  }
}

const openAllocations = async (skillName: string) => {
  currentSkillName.value = skillName
  allocationsVisible.value = true
  allocationsLoading.value = true

  try {
    const res = await adminApi.getSkillAllocations(skillName)
    if (res.success) {
      allocationsData.value = res.data
    }
  } catch {
    ElMessage.error('获取授权失败')
  } finally {
    allocationsLoading.value = false
  }
}

const openSkillEditor = async (skillName: string) => {
  editorVisible.value = true
  editingSkillName.value = skillName
  selectedFilePath.value = ''
  selectedFileContent.value = ''
  selectedFileIsText.value = false
  await refreshSkillFiles()
}

const refreshSkillFiles = async () => {
  if (!editingSkillName.value) return
  editorLoading.value = true
  try {
    const res = await adminApi.getSkillFiles(editingSkillName.value)
    if (res.success) {
      skillFiles.value = (res.data || []).sort((a, b) => {
        if (a.is_dir && !b.is_dir) return -1
        if (!a.is_dir && b.is_dir) return 1
        return a.path.localeCompare(b.path)
      })
    }
  } catch (e: any) {
    ElMessage.error(`获取文件列表失败: ${e.response?.data?.detail || e.message || '未知错误'}`)
  } finally {
    editorLoading.value = false
  }
}

const selectSkillFile = async (node: SkillFileNode) => {
  if (node.is_dir) return
  selectedFilePath.value = node.path
  selectedFileIsText.value = Boolean(node.is_text)
  selectedFileContent.value = ''
  if (!node.is_text || !editingSkillName.value) return

  editorLoading.value = true
  try {
    const res = await adminApi.getSkillFileContent(editingSkillName.value, node.path)
    if (res.success) {
      selectedFileContent.value = res.data.content
    }
  } catch (e: any) {
    ElMessage.error(`读取文件失败: ${e.response?.data?.detail || e.message || '未知错误'}`)
  } finally {
    editorLoading.value = false
  }
}

const saveCurrentFile = async () => {
  if (!editingSkillName.value || !selectedFilePath.value || !selectedFileIsText.value) return
  savingFile.value = true
  try {
    const res = await adminApi.saveSkillFileContent(editingSkillName.value, {
      path: selectedFilePath.value,
      content: selectedFileContent.value,
    })
    if (res.success) {
      ElMessage.success('文件已保存')
      await refreshSkillFiles()
    }
  } catch (e: any) {
    ElMessage.error(`保存失败: ${e.response?.data?.detail || e.message || '未知错误'}`)
  } finally {
    savingFile.value = false
  }
}

const getFileNameFromDisposition = (disposition?: string, fallback = 'skill-latest.zip') => {
  if (!disposition) return fallback
  const utf8NameMatch = disposition.match(/filename\*=UTF-8''([^;]+)/i)
  if (utf8NameMatch && utf8NameMatch[1]) {
    return decodeURIComponent(utf8NameMatch[1])
  }
  const fileNameMatch = disposition.match(/filename="?([^"]+)"?/i)
  if (fileNameMatch && fileNameMatch[1]) {
    return fileNameMatch[1]
  }
  return fallback
}

const triggerFileDownload = (blob: Blob, fileName: string) => {
  const url = window.URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = fileName
  document.body.appendChild(link)
  link.click()
  document.body.removeChild(link)
  window.URL.revokeObjectURL(url)
}

const downloadLatestPackage = async (skill: SkillItem) => {
  if (!skill.oss_packaged) {
    ElMessage.warning('尚未打包，先执行一键打包并上传 OSS')
    return
  }
  downloadingSkillName.value = skill.name
  try {
    const res = await adminApi.downloadLatestSkillPackage(skill.name)
    const fileName = getFileNameFromDisposition(
      res.headers?.['content-disposition'],
      `${skill.name}-latest.zip`,
    )
    triggerFileDownload(res.data, fileName)
    ElMessage.success(`下载成功（最新版本 ${skill.latest_version || '未知'}）`)
  } catch (e: any) {
    ElMessage.error(`下载失败: ${e.response?.data?.detail || e.message || '未知错误'}`)
  } finally {
    downloadingSkillName.value = ''
  }
}

const handleSearch = () => {
  pager.value.page = 1
  fetchSkills()
}

const handlePageChange = (page: number) => {
  pager.value.page = page
  fetchSkills()
}

const handleSizeChange = (pageSize: number) => {
  pager.value.pageSize = pageSize
  pager.value.page = 1
  fetchSkills()
}

onMounted(() => {
  fetchSkills()
})
</script>

<style scoped>
.glass-panel {
  padding: 20px;
}

.skill-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.overview-row {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 16px;
}

.overview-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-height: 84px;
  justify-content: center;
  padding: 18px 20px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 10px;
  background: var(--el-fill-color-blank);
}

.overview-item span {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.overview-item strong {
  font-size: 28px;
  line-height: 1;
  color: var(--el-text-color-primary);
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
}

.toolbar-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  margin-bottom: 16px;
}

.search-input {
  width: min(520px, 100%);
}

.cell-text-ellipsis {
  display: block;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
  max-width: 100%;
}

.skill-name {
  font-weight: 600;
  font-size: 13px;
  color: var(--el-text-color-primary);
  line-height: 1.5;
}

.skill-desc {
  font-size: 13px;
  color: var(--el-text-color-secondary);
  line-height: 1.5;
}

.meta-text {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.table-action-group {
  display: flex;
  flex-wrap: nowrap;
  gap: 6px;
  align-items: center;
}

.table-scroll-wrap {
  width: 100%;
  max-width: 100%;
  overflow-x: auto;
  overflow-y: hidden;
  padding-bottom: 4px;
}

.table-scroll-wrap::-webkit-scrollbar {
  height: 8px;
}

.table-scroll-wrap::-webkit-scrollbar-thumb {
  background: var(--el-border-color);
  border-radius: 999px;
}

.table-scroll-wrap::-webkit-scrollbar-track {
  background: var(--el-fill-color-light);
  border-radius: 999px;
}

.skill-table {
  width: 100%;
  min-width: 1320px;
}

.skill-table :deep(.el-table__inner-wrapper) {
  min-width: 1320px;
}

.skill-table :deep(.el-table__cell) {
  border-right: 1px solid var(--el-border-color-light) !important;
}

.skill-table :deep(.el-table__header-wrapper th) {
  border-right: 1px solid var(--el-border-color) !important;
  border-bottom: 2px solid var(--el-border-color) !important;
}

.skill-table :deep(.el-table__row td) {
  border-bottom: 1px solid var(--el-border-color-lighter) !important;
}

.skill-table :deep(.el-table__row:hover td) {
  background-color: var(--el-fill-color-light) !important;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}

.editor-layout {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 12px;
}

.editor-files {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 10px;
}

.editor-content {
  border: 1px solid #ebeef5;
  border-radius: 8px;
  padding: 10px;
}

.editor-toolbar {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 8px;
}

.editor-title {
  font-weight: 600;
}

.editor-file-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 6px;
  cursor: pointer;
}

.editor-file-item:hover {
  background: #f5f7fa;
}

.editor-file-item.active {
  background: #ecf5ff;
}

.editor-file-item.dir {
  color: #909399;
}

@media (max-width: 1200px) {
  .overview-row {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }

  .editor-layout {
    grid-template-columns: 1fr;
  }
}

@media (max-width: 768px) {
  .overview-row {
    grid-template-columns: 1fr;
  }

  .banner-actions {
    justify-content: stretch;
    align-items: stretch;
    flex-direction: column;
  }

  .search-input {
    width: 100%;
  }

  .skill-table {
    min-width: 1240px;
  }

  .skill-table :deep(.el-table__inner-wrapper) {
    min-width: 1240px;
  }
}
</style>
