<template>
  <div class="page-grid kb-page">
    <section class="glass-panel panel-block">
      <div class="section-heading section-heading--table">
        <div>
          <div class="eyebrow">Personal Knowledge Base</div>
          <h2>个人知识库管理</h2>
          <p class="heading-description">
            管理员工个人知识库分类与文件，按用户查看。个人知识库的创建和维护请在员工桌面端完成。
          </p>
        </div>
        <div class="heading-tags">
          <el-tag v-if="selectedUsername" type="warning">{{ selectedUsername }} 的知识库</el-tag>
          <el-tag type="info">{{ categories.length }} 个分类</el-tag>
          <el-tag type="success">{{ totalFiles }} 个文件</el-tag>
        </div>
      </div>

      <div class="toolbar-row">
        <el-select
          v-model="selectedUsername"
          filterable
          placeholder="选择用户"
          size="default"
          style="width: 220px"
          @change="onUserChange"
        >
          <el-option
            v-for="user in userOptions"
            :key="user.username"
            :label="user.name || user.username"
            :value="user.username"
          />
        </el-select>
        <el-input
          v-model="searchKeyword"
          clearable
          placeholder="搜索知识库文件"
          class="search-input"
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        >
          <template #append>
            <el-button :loading="fetching" @click="handleSearch">搜索</el-button>
          </template>
        </el-input>
      </div>

      <div v-loading="fetching" class="kb-content-area">
        <div v-if="!categories.length && !fetching" class="kb-empty">
          <el-empty description="请先选择用户查看其个人知识库" />
        </div>

        <div v-else class="kb-category-list">
          <div
            v-for="cat in categories"
            :key="cat.name"
            class="kb-category-card"
            :class="{ active: selectedCategory === cat.name }"
            @click="selectCategory(cat.name)"
          >
            <div class="kb-category-header">
              <div class="kb-category-info">
                <span class="kb-category-name">{{ cat.display_name || cat.name }}</span>
                <el-tag v-if="cat.username" size="small" type="warning">{{ cat.username }}</el-tag>
                <el-tag size="small" type="info">{{ cat.file_count ?? 0 }} 个文件</el-tag>
              </div>
              <div class="kb-category-actions" @click.stop>
                <el-button size="small" type="primary" plain @click="showRenameCategoryDialog(cat)">重命名</el-button>
                <el-popconfirm
                  title="删除分类将同时删除其下所有文件，确定继续？"
                  width="240"
                  @confirm="handleDeleteCategory(cat.name)"
                >
                  <template #reference>
                    <el-button size="small" type="danger" plain>删除分类</el-button>
                  </template>
                </el-popconfirm>
              </div>
            </div>

            <div v-if="selectedCategory === cat.name" class="kb-file-section">
              <div style="margin-bottom: 12px">
                <el-button size="small" @click.stop="selectedCategory = ''">← 返回分类列表</el-button>
              </div>

              <div v-if="categoryFiles.length === 0" class="kb-file-empty">
                暂无文件
              </div>

              <el-table
                v-else
                :data="categoryFiles"
                border
                stripe
                row-key="id"
                table-layout="fixed"
                size="small"
                :header-cell-style="{ background: '#fafafa', fontWeight: '600', padding: '8px 12px' }"
                :cell-style="{ padding: '8px 12px', verticalAlign: 'middle' }"
              >
                <el-table-column label="文件名" min-width="200">
                  <template #default="{ row }">
                    <el-link type="primary" @click="openFileDetail(row)">{{ row.md_filename || row.original_filename }}</el-link>
                  </template>
                </el-table-column>
                <el-table-column label="原始文件名" width="180">
                  <template #default="{ row }">
                    <span class="cell-text-ellipsis">{{ row.original_filename }}</span>
                  </template>
                </el-table-column>
                <el-table-column label="类型" width="80" align="center">
                  <template #default="{ row }">
                    <el-tag size="small">{{ row.file_type }}</el-tag>
                  </template>
                </el-table-column>
                <el-table-column label="大小" width="100" align="right">
                  <template #default="{ row }">
                    {{ formatFileSize(row.file_size) }}
                  </template>
                </el-table-column>
                <el-table-column label="摘要" min-width="200">
                  <template #default="{ row }">
                    <el-tooltip :content="row.summary" placement="top" :show-after="300" :disabled="!row.summary">
                      <span class="cell-text-ellipsis">{{ row.summary || '暂无摘要' }}</span>
                    </el-tooltip>
                  </template>
                </el-table-column>
                <el-table-column label="操作" width="100" fixed="right">
                  <template #default="{ row }">
                    <div class="table-action-group">
                      <el-button size="small" @click="openFileDetail(row)">查看</el-button>
                    </div>
                  </template>
                </el-table-column>
              </el-table>
            </div>
          </div>
        </div>
      </div>
    </section>

    <!-- 重命名分类对话框 -->
    <el-dialog v-model="renameCategoryVisible" title="重命名分类" width="420px">
      <el-form label-width="80px">
        <el-form-item label="当前名称">
          <el-input :model-value="renameCategoryOldName" disabled />
        </el-form-item>
        <el-form-item label="新名称">
          <el-input v-model="renameCategoryNewName" placeholder="请输入新的分类名称" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="renameCategoryVisible = false">取消</el-button>
        <el-button type="primary" :loading="renamingCategory" @click="handleRenameCategory">确认</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="fileDetailVisible" :title="currentFile?.original_filename || '文件详情'" width="800px" top="4vh">
      <div v-loading="loadingFileContent">
        <el-descriptions :column="2" border size="small" class="file-meta-desc">
          <el-descriptions-item label="原始文件名">{{ currentFile?.original_filename }}</el-descriptions-item>
          <el-descriptions-item label="MD 文件名">{{ currentFile?.md_filename }}</el-descriptions-item>
          <el-descriptions-item label="文件类型">{{ currentFile?.file_type }}</el-descriptions-item>
          <el-descriptions-item label="文件大小">{{ formatFileSize(currentFile?.file_size ?? 0) }}</el-descriptions-item>
          <el-descriptions-item label="来源 URL" :span="2">{{ currentFile?.source_url || '无' }}</el-descriptions-item>
          <el-descriptions-item label="摘要" :span="2">{{ currentFile?.summary || '暂无摘要' }}</el-descriptions-item>
        </el-descriptions>

        <div class="file-content-section">
          <h3 style="margin: 0 0 12px 0">Markdown 内容</h3>
          <el-scrollbar height="400px">
            <pre class="file-content-preview">{{ fileContent || '暂无内容' }}</pre>
          </el-scrollbar>
        </div>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
// @ts-nocheck
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi, type KbCategoryItem, type KbFileItem } from '@/services/admin'

const KB_TYPE = 'personal'

const categories = ref<KbCategoryItem[]>([])
const allFiles = ref<KbFileItem[]>([])
const selectedCategory = ref('')
const fetching = ref(false)
const uploading = ref(false)
const searchKeyword = ref('')

const userOptions = ref<{ username: string; name?: string }[]>([])
const selectedUsername = ref('')

const createCategoryVisible = ref(false)
const creatingCategory = ref(false)
const createCategoryForm = ref({ name: '' })

const addUrlVisible = ref(false)
const addingUrl = ref(false)
const addUrlForm = ref({ url: '' })

const fileDetailVisible = ref(false)
const loadingFileContent = ref(false)
const currentFile = ref<KbFileItem | null>(null)
const fileContent = ref('')
const editingContent = ref(false)
const editContentText = ref('')
const savingContent = ref(false)

// 重命名分类相关
const renameCategoryVisible = ref(false)
const renamingCategory = ref(false)
const renameCategoryOldName = ref('')
const renameCategoryName = ref('')  // 分类安全名称（name字段）
const renameCategoryNewName = ref('')

const totalFiles = computed(() => allFiles.value.length)

const categoryFiles = computed(() => {
  if (!selectedCategory.value) return []
  return allFiles.value.filter((f) => f.category === selectedCategory.value)
})

const formatFileSize = (bytes: number) => {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / (1024 * 1024)).toFixed(1) + ' MB'
}

const fetchCategories = async () => {
  fetching.value = true
  try {
    const res = await adminApi.getKbCategories(KB_TYPE, selectedUsername.value)
    if (res.success) {
      categories.value = res.categories || []
    }
  } catch (e: any) {
    ElMessage.error('获取分类列表失败')
  } finally {
    fetching.value = false
  }
}

const extractErrorMsg = (e: any, fallback = '未知错误'): string => {
  const detail = e.response?.data?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((d: any) => d.msg || d.message || String(d)).join('; ')
  }
  if (detail && typeof detail === 'object') {
    return detail.msg || detail.message || JSON.stringify(detail)
  }
  return e.message || fallback
}

const fetchFiles = async () => {
  try {
    const res = await adminApi.getKbFiles(KB_TYPE, undefined, selectedUsername.value)
    if (res.success) {
      allFiles.value = res.files || []
    }
  } catch {
    // 静默处理
  }
}

const selectCategory = (name: string) => {
  selectedCategory.value = selectedCategory.value === name ? '' : name
}

const showCreateCategoryDialog = () => {
  createCategoryForm.value.name = ''
  createCategoryVisible.value = true
}

const handleCreateCategory = async () => {
  const name = createCategoryForm.value.name.trim()
  if (!name) {
    ElMessage.warning('请输入分类名称')
    return
  }
  creatingCategory.value = true
  try {
    const res = await adminApi.createKbCategory(name, KB_TYPE, selectedUsername.value)
    if (res.success) {
      ElMessage.success('分类创建成功')
      createCategoryVisible.value = false
      await fetchCategories()
    }
  } catch (e: any) {
    ElMessage.error(`创建失败: ${extractErrorMsg(e)}`)
  } finally {
    creatingCategory.value = false
  }
}

const handleDeleteCategory = async (name: string) => {
  try {
    const res = await adminApi.deleteKbCategory(name, KB_TYPE, selectedUsername.value)
    if (res.success) {
      ElMessage.success('分类已删除')
      if (selectedCategory.value === name) {
        selectedCategory.value = ''
      }
      await fetchCategories()
      await fetchFiles()
    }
  } catch (e: any) {
    ElMessage.error(`删除分类失败: ${extractErrorMsg(e)}`)
  }
}

const showRenameCategoryDialog = (cat: KbCategoryItem) => {
  renameCategoryName.value = cat.name
  renameCategoryOldName.value = cat.display_name || cat.name
  renameCategoryNewName.value = cat.display_name || cat.name
  renameCategoryVisible.value = true
}

const handleRenameCategory = async () => {
  const newName = renameCategoryNewName.value.trim()
  if (!newName) {
    ElMessage.warning('请输入新的分类名称')
    return
  }
  renamingCategory.value = true
  try {
    const res = await adminApi.renameKbCategory(renameCategoryName.value, newName, KB_TYPE, selectedUsername.value)
    if (res.success) {
      ElMessage.success('重命名成功')
      renameCategoryVisible.value = false
      await fetchCategories()
    }
  } catch (e: any) {
    ElMessage.error(`重命名失败: ${extractErrorMsg(e)}`)
  } finally {
    renamingCategory.value = false
  }
}

const handleFileUpload = async (options: any) => {
  const { file } = options
  if (!selectedCategory.value) {
    ElMessage.warning('请先选择分类')
    return
  }
  uploading.value = true
  try {
    const res = await adminApi.uploadKbFile(file, selectedCategory.value, KB_TYPE, selectedUsername.value)
    if (res.success) {
      ElMessage.success(`${file.name} 上传成功`)
      await fetchFiles()
      await fetchCategories()
    } else {
      ElMessage.error(res.error || '上传失败')
    }
  } catch (e: any) {
    ElMessage.error(`上传失败: ${extractErrorMsg(e)}`)
  } finally {
    uploading.value = false
  }
}

const showAddUrlDialog = () => {
  addUrlForm.value.url = ''
  addUrlVisible.value = true
}

const handleAddUrl = async () => {
  const url = addUrlForm.value.url.trim()
  if (!url) {
    ElMessage.warning('请输入 URL 地址')
    return
  }
  if (!selectedCategory.value) {
    ElMessage.warning('请先选择分类')
    return
  }
  addingUrl.value = true
  try {
    const res = await adminApi.uploadKbUrl(url, selectedCategory.value, KB_TYPE, selectedUsername.value)
    if (res.success) {
      ElMessage.success('URL 添加成功')
      addUrlVisible.value = false
      await fetchFiles()
      await fetchCategories()
    } else {
      ElMessage.error(res.error || '添加失败')
    }
  } catch (e: any) {
    ElMessage.error(`添加失败: ${extractErrorMsg(e)}`)
  } finally {
    addingUrl.value = false
  }
}

const handleDeleteFile = async (fileId: string) => {
  try {
    const res = await adminApi.deleteKbFile(fileId, KB_TYPE, selectedUsername.value)
    if (res.success) {
      ElMessage.success('文件已删除')
      await fetchFiles()
      await fetchCategories()
    }
  } catch (e: any) {
    ElMessage.error(`删除文件失败: ${extractErrorMsg(e)}`)
  }
}

const handleSearch = async () => {
  const kw = searchKeyword.value.trim()
  if (!kw) {
    await fetchFiles()
    return
  }
  fetching.value = true
  try {
    const res = await adminApi.getKbFiles(KB_TYPE, undefined, selectedUsername.value)
    if (res.success) {
      const all = res.files || []
      allFiles.value = all.filter(
        (f) =>
          (f.original_filename || '').toLowerCase().includes(kw.toLowerCase()) ||
          (f.summary || '').toLowerCase().includes(kw.toLowerCase()) ||
          (f.md_filename || '').toLowerCase().includes(kw.toLowerCase()),
      )
    }
  } catch {
    ElMessage.error('搜索失败')
  } finally {
    fetching.value = false
  }
}

const openFileDetail = async (file: KbFileItem) => {
  currentFile.value = file
  fileContent.value = ''
  editingContent.value = false
  fileDetailVisible.value = true
  loadingFileContent.value = true
  try {
    const res = await adminApi.getKbFileContent(file.id, KB_TYPE, selectedUsername.value)
    if (res.success) {
      fileContent.value = res.content || ''
    }
  } catch {
    ElMessage.error('获取文件内容失败')
  } finally {
    loadingFileContent.value = false
  }
}

const startEditContent = () => {
  editContentText.value = fileContent.value
  editingContent.value = true
}

const cancelEditContent = () => {
  editingContent.value = false
}

const saveContent = async () => {
  if (!currentFile.value) return
  savingContent.value = true
  try {
    const res = await adminApi.updateKbFileContent(currentFile.value.id, editContentText.value, KB_TYPE, selectedUsername.value)
    if (res.success) {
      ElMessage.success('内容已保存')
      fileContent.value = editContentText.value
      editingContent.value = false
      await fetchFiles()
    }
  } catch (e: any) {
    ElMessage.error(`保存失败: ${extractErrorMsg(e)}`)
  } finally {
    savingContent.value = false
  }
}

const fetchUsers = async () => {
  try {
    const res = await adminApi.getUsers()
    userOptions.value = (res.data || []).filter((u: any) => u.status === 1 && u.username)
  } catch {
    // 静默处理
  }
}

const onUserChange = async () => {
  selectedCategory.value = ''
  await fetchCategories()
  await fetchFiles()
}

onMounted(async () => {
  await fetchUsers()
  await fetchCategories()
  await fetchFiles()
})
</script>

<style scoped>
.kb-page {
  padding: 0;
}

:deep(.el-dialog) {
  background: #fff !important;
  border-radius: 12px;
}

:deep(.el-dialog__header) {
  background: #fafafa;
  border-radius: 12px 12px 0 0;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

:deep(.el-dialog__body) {
  background: #fff;
}

:deep(.el-textarea__inner) {
  border: 1px solid var(--el-border-color) !important;
  border-radius: 8px;
}

:deep(.el-table .cell) {
  font-size: 13px;
  line-height: 1.5;
}

:deep(.el-table .el-link__inner) {
  font-size: 13px;
  vertical-align: middle;
}

:deep(.el-table .el-tag--small) {
  vertical-align: middle;
}

.kb-content-area {
  min-height: 300px;
}

.kb-empty {
  padding: 60px 0;
}

.kb-category-list {
  display: grid;
  gap: 16px;
}

.kb-category-card {
  border: 1px solid var(--el-border-color-light);
  border-radius: 10px;
  overflow: hidden;
  transition: border-color 0.2s;
  cursor: pointer;
}

.kb-category-card:hover {
  border-color: var(--el-color-primary-light-5);
}

.kb-category-card.active {
  border-color: var(--el-color-primary);
  box-shadow: 0 0 0 1px var(--el-color-primary-light-8);
}

.kb-category-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 18px;
  background: linear-gradient(180deg, #ffffff 0%, #fbfdff 100%);
}

.kb-category-info {
  display: flex;
  align-items: center;
  gap: 10px;
}

.kb-category-name {
  font-weight: 600;
  font-size: 15px;
  color: var(--el-text-color-primary);
}

.kb-file-section {
  padding: 16px 18px;
  border-top: 1px solid var(--el-border-color-lighter);
  background: #fafbfc;
}

.kb-file-toolbar {
  display: flex;
  gap: 10px;
  margin-bottom: 12px;
}

.kb-file-empty {
  text-align: center;
  padding: 24px 0;
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.file-meta-desc {
  margin-bottom: 16px;
}

.file-content-section {
  margin-top: 16px;
}

.file-content-preview {
  margin: 0;
  padding: 16px;
  background: #f5f7fa;
  border-radius: 8px;
  font-size: 13px;
  line-height: 1.7;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}

.cell-text-ellipsis {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.kb-category-actions .el-button--small {
  min-height: auto;
}
</style>
