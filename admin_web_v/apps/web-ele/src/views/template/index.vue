<template>
  <div class="page-grid template-page">
    <section class="glass-panel panel-block">
      <div class="section-heading section-heading--table">
        <div>
          <div class="eyebrow">Template Management</div>
          <h2>模板管理</h2>
          <p class="heading-description">
            管理报告、图片、视频三类模板，支持上传、编辑、启用/禁用和批量操作。
          </p>
        </div>
        <div class="heading-tags">
          <el-tag type="info">{{ total }} 个模板</el-tag>
          <el-tag type="success">{{ activeCount }} 个启用</el-tag>
        </div>
      </div>

      <div class="toolbar-row">
        <el-button type="primary" plain @click="showCreateDialog">新建模板</el-button>
        <el-select
          v-model="filterCategory"
          clearable
          placeholder="按分类筛选"
          class="filter-select"
          @change="handleSearch"
        >
          <el-option
            v-for="cat in categories"
            :key="cat.category_key"
            :label="cat.category_name"
            :value="cat.category_key"
          />
        </el-select>
        <el-select
          v-model="filterActive"
          clearable
          placeholder="按状态筛选"
          class="filter-select-sm"
          @change="handleSearch"
        >
          <el-option label="启用" :value="1" />
          <el-option label="禁用" :value="0" />
        </el-select>
        <el-input
          v-model="keyword"
          clearable
          placeholder="搜索模板名称或标识"
          class="search-input"
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        >
          <template #append>
            <el-button :loading="fetching" @click="handleSearch">检索</el-button>
          </template>
        </el-input>
      </div>

      <el-table
        :data="templates"
        border
        stripe
        row-key="id"
        table-layout="fixed"
        v-loading="fetching"
        empty-text="暂无模板数据"
        class="template-table"
        :header-cell-style="{ background: '#fafafa', fontWeight: '600', color: '#303133', padding: '12px 16px' }"
        :cell-style="{ padding: '12px 16px', verticalAlign: 'middle' }"
      >
        <el-table-column type="selection" width="45" align="center" />

        <el-table-column label="模板名称" min-width="180" align="center">
          <template #default="{ row }">
            <div class="template-name-cell">
              <el-image
                v-if="row.cover_download_url || row.cover_url"
                :src="row.cover_download_url || row.cover_url"
                fit="cover"
                class="template-cover"
                :preview-src-list="[row.cover_download_url || row.cover_url]"
              />
              <div v-else class="template-cover-placeholder">
                {{ row.category_key === 'report' ? '📄' : row.category_key === 'image' ? '🖼' : '🎬' }}
              </div>
              <div class="template-name-info">
                <el-tooltip :content="row.template_name" placement="top" :show-after="300">
                  <span class="cell-text-ellipsis">{{ row.template_name }}</span>
                </el-tooltip>
                <span class="template-key-hint">{{ row.template_key }}</span>
              </div>
            </div>
          </template>
        </el-table-column>

        <el-table-column label="分类" width="110" align="center">
          <template #default="{ row }">
            <el-tag
              :type="row.category_key === 'report' ? 'primary' : row.category_key === 'image' ? 'success' : 'warning'"
              size="small"
            >
              {{ row.category_name }}
            </el-tag>
          </template>
        </el-table-column>

        <el-table-column label="文件" width="160" align="center">
          <template #default="{ row }">
            <div v-if="row.file_name" class="file-info">
              <span class="cell-text-ellipsis">{{ row.file_name }}</span>
              <span class="file-meta">{{ formatFileSize(row.file_size) }} · {{ row.file_type }}</span>
            </div>
            <span v-else class="meta-text">未上传</span>
          </template>
        </el-table-column>

        <el-table-column label="版本" width="90" align="center" :show-overflow-tooltip="false">
          <template #default="{ row }">
            <el-tag size="small" type="info" style="white-space: nowrap;">v{{ row.version }}</el-tag>
          </template>
        </el-table-column>

        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-switch
              v-model="row.is_active"
              :active-value="1"
              :inactive-value="0"
              inline-prompt
              active-text="启"
              inactive-text="停"
              :loading="togglingId === row.id"
              @change="(value) => handleToggle(row, value)"
            />
          </template>
        </el-table-column>

        <el-table-column label="更新时间" width="170" align="center">
          <template #default="{ row }">
            <span class="meta-text">{{ formatTime(row.updated_at) }}</span>
          </template>
        </el-table-column>

        <el-table-column label="操作" width="320" fixed="right" align="center">
          <template #default="{ row }">
            <div class="table-action-group">
              <el-button size="small" type="primary" plain @click="openEditDialog(row)">编辑</el-button>
              <el-button size="small" @click="openUploadFileDialog(row)">换文件</el-button>
              <el-button size="small" @click="openUploadCoverDialog(row)">封面</el-button>
              <el-button size="small" type="danger" plain @click="handleDelete(row.id)">删除</el-button>
            </div>
          </template>
        </el-table-column>
      </el-table>

      <div class="pagination-wrap">
        <el-pagination
          background
          layout="total, sizes, prev, pager, next"
          :total="total"
          :page-size="pager.pageSize"
          :page-sizes="[10, 20, 50]"
          :current-page="pager.page"
          @current-change="handlePageChange"
          @size-change="handleSizeChange"
        />
      </div>
    </section>

    <!-- 新建/编辑模板对话框 -->
    <el-dialog
      v-model="dialogVisible"
      :title="isEditing ? '编辑模板' : '新建模板'"
      width="620px"
      @close="resetForm"
    >
      <el-form :model="formData" :rules="formRules" ref="formRef" label-width="100px">
        <el-form-item label="模板分类" prop="category_key">
          <el-select
            v-model="formData.category_key"
            placeholder="选择分类"
            :disabled="isEditing"
          >
            <el-option
              v-for="cat in categories"
              :key="cat.category_key"
              :label="cat.category_name"
              :value="cat.category_key"
            />
          </el-select>
        </el-form-item>

        <el-form-item label="模板标识" prop="template_key">
          <el-input
            v-model="formData.template_key"
            placeholder="如: report-jiaoyi-zhongxin"
            :disabled="isEditing"
          />
        </el-form-item>

        <el-form-item label="模板名称" prop="template_name">
          <el-input v-model="formData.template_name" placeholder="如: 广西铝产品仓储交易中心模板" />
        </el-form-item>

        <el-form-item label="兼容类型" prop="template_type">
          <el-input v-model="formData.template_type" placeholder="旧 type 编号，如 0, 1, 2（可选）" />
        </el-form-item>

        <el-form-item label="描述" prop="description">
          <el-input v-model="formData.description" type="textarea" :rows="3" placeholder="模板描述（可选）" />
        </el-form-item>

        <el-form-item v-if="!isEditing" label="模板文件" prop="file">
          <el-upload
            ref="fileUploadRef"
            action="#"
            :auto-upload="false"
            :limit="1"
            :on-change="handleFileChange"
            :on-remove="handleFileRemove"
            :file-list="fileList"
          >
            <el-button type="primary" plain>选择文件</el-button>
          </el-upload>
        </el-form-item>

        <el-form-item v-if="!isEditing" label="封面图">
          <el-upload
            ref="coverUploadRef"
            action="#"
            :auto-upload="false"
            :limit="1"
            accept="image/*"
            :on-change="handleCoverChange"
            :on-remove="handleCoverRemove"
            :file-list="coverList"
          >
            <el-button plain>选择封面图</el-button>
          </el-upload>
        </el-form-item>

        <el-form-item v-if="formData.category_key === 'report'" label="样式配置" prop="style_config">
          <el-input
            v-model="formData.style_config"
            type="textarea"
            :rows="6"
            placeholder='{"DOCX_STYLE": {...}, "TABLE_STYLE": {...}, "IMG_STYLE": {...}}'
          />
        </el-form-item>

        <el-form-item label="排序权重">
          <el-input-number v-model="formData.sort_order" :min="0" :max="9999" />
        </el-form-item>
      </el-form>

      <template #footer>
        <el-button @click="dialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleSubmit">确定</el-button>
      </template>
    </el-dialog>

    <!-- 更换文件对话框 -->
    <el-dialog v-model="fileDialogVisible" title="更换模板文件" width="480px">
      <el-upload
        ref="replaceFileUploadRef"
        action="#"
        :auto-upload="false"
        :limit="1"
        :on-change="handleReplaceFileChange"
        :on-remove="handleReplaceFileRemove"
        :file-list="replaceFileList"
      >
        <el-button type="primary" plain>选择新文件</el-button>
      </el-upload>
      <template #footer>
        <el-button @click="fileDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleReplaceFile">上传</el-button>
      </template>
    </el-dialog>

    <!-- 更换封面对话框 -->
    <el-dialog v-model="coverDialogVisible" title="更换封面图" width="480px">
      <el-upload
        ref="replaceCoverUploadRef"
        action="#"
        :auto-upload="false"
        :limit="1"
        accept="image/*"
        :on-change="handleReplaceCoverChange"
        :on-remove="handleReplaceCoverRemove"
        :file-list="replaceCoverList"
      >
        <el-button type="primary" plain>选择新封面</el-button>
      </el-upload>
      <template #footer>
        <el-button @click="coverDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="submitting" @click="handleReplaceCover">上传</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
// @ts-nocheck
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminApi } from '@/services/admin'

interface TemplateCategory {
  id: number
  category_key: string
  category_name: string
  description: string
  sort_order: number
  template_count: number
}

interface TemplateItem {
  id: string
  template_key: string
  template_name: string
  template_type: string
  description: string
  cover_url: string
  cover_download_url: string
  file_url: string
  file_download_url: string
  file_name: string
  file_size: number
  file_type: string
  style_config: string
  version: number
  is_active: number
  sort_order: number
  created_by: string
  created_at: string
  updated_at: string
  category_key: string
  category_name: string
}

const categories = ref<TemplateCategory[]>([])
const templates = ref<TemplateItem[]>([])
const total = ref(0)
const fetching = ref(false)
const submitting = ref(false)
const togglingId = ref('')

const filterCategory = ref('')
const filterActive = ref<number | ''>('')
const keyword = ref('')

const pager = ref({ page: 1, pageSize: 20 })

const dialogVisible = ref(false)
const isEditing = ref(false)
const editingId = ref('')
const formRef = ref()
const fileUploadRef = ref()
const coverUploadRef = ref()
const fileList = ref([])
const coverList = ref([])
const selectedFile = ref<File | null>(null)
const selectedCover = ref<File | null>(null)

const formData = ref({
  category_key: '',
  template_key: '',
  template_name: '',
  template_type: '',
  description: '',
  style_config: '',
  sort_order: 0,
})

const formRules = {
  category_key: [{ required: true, message: '请选择分类', trigger: 'change' }],
  template_key: [
    { required: true, message: '请输入模板标识', trigger: 'blur' },
    { pattern: /^[a-zA-Z0-9_-]+$/, message: '仅支持字母、数字、下划线和连字符', trigger: 'blur' },
  ],
  template_name: [{ required: true, message: '请输入模板名称', trigger: 'blur' }],
}

const fileDialogVisible = ref(false)
const replaceFileUploadRef = ref()
const replaceFileList = ref([])
const replaceFile = ref<File | null>(null)
const replaceTargetId = ref('')

const coverDialogVisible = ref(false)
const replaceCoverUploadRef = ref()
const replaceCoverList = ref([])
const replaceCover = ref<File | null>(null)
const replaceCoverTargetId = ref('')

const activeCount = computed(() => templates.value.filter((t) => t.is_active === 1).length)

const formatFileSize = (size: number) => {
  if (!size) return '0 B'
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / (1024 * 1024)).toFixed(1)} MB`
}

const formatTime = (time: string) => {
  if (!time) return '-'
  return time.replace('T', ' ').substring(0, 19)
}

const fetchCategories = async () => {
  try {
    const res = await adminApi.getTemplateCategories()
    if (res.success) {
      categories.value = res.categories || []
    }
  } catch {
    ElMessage.error('获取模板分类失败')
  }
}

const fetchTemplates = async () => {
  fetching.value = true
  try {
    const res = await adminApi.getTemplateList({
      category_key: filterCategory.value || undefined,
      keyword: keyword.value.trim() || undefined,
      is_active: filterActive.value !== '' ? filterActive.value : undefined,
      page: pager.value.page,
      page_size: pager.value.pageSize,
    })
    if (res.success) {
      templates.value = res.items || []
      total.value = res.total || 0
    }
  } catch {
    ElMessage.error('获取模板列表失败')
  } finally {
    fetching.value = false
  }
}

const handleSearch = () => {
  pager.value.page = 1
  fetchTemplates()
}

const handlePageChange = (page: number) => {
  pager.value.page = page
  fetchTemplates()
}

const handleSizeChange = (pageSize: number) => {
  pager.value.pageSize = pageSize
  pager.value.page = 1
  fetchTemplates()
}

const handleToggle = async (row: TemplateItem, value: number) => {
  togglingId.value = row.id
  try {
    const res = await adminApi.toggleTemplate(row.id, value)
    if (res.success) {
      ElMessage.success(`模板已${value === 1 ? '启用' : '禁用'}`)
    } else {
      row.is_active = value === 1 ? 0 : 1
    }
  } catch (e: any) {
    row.is_active = value === 1 ? 0 : 1
    ElMessage.error(`操作失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    togglingId.value = ''
  }
}

const handleDelete = async (id: string) => {
  try {
    await ElMessageBox.confirm('确定要删除这个模板吗？', '提示', {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning',
    })
    const res = await adminApi.deleteTemplate(id)
    if (res.success) {
      ElMessage.success('删除成功')
      await fetchTemplates()
    }
  } catch (e: any) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(`删除失败: ${e.response?.data?.detail || e.message}`)
  }
}

const showCreateDialog = () => {
  isEditing.value = false
  editingId.value = ''
  formData.value = {
    category_key: '',
    template_key: '',
    template_name: '',
    template_type: '',
    description: '',
    style_config: '',
    sort_order: 0,
  }
  fileList.value = []
  coverList.value = []
  selectedFile.value = null
  selectedCover.value = null
  dialogVisible.value = true
}

const openEditDialog = (row: TemplateItem) => {
  isEditing.value = true
  editingId.value = row.id
  formData.value = {
    category_key: row.category_key,
    template_key: row.template_key,
    template_name: row.template_name,
    template_type: row.template_type || '',
    description: row.description || '',
    style_config: row.style_config || '',
    sort_order: row.sort_order || 0,
  }
  fileList.value = []
  coverList.value = []
  selectedFile.value = null
  selectedCover.value = null
  dialogVisible.value = true
}

const resetForm = () => {
  formRef.value?.resetFields()
}

const handleFileChange = (file: any) => {
  selectedFile.value = file.raw
  fileList.value = [file]
}

const handleFileRemove = () => {
  selectedFile.value = null
  fileList.value = []
}

const handleCoverChange = (file: any) => {
  selectedCover.value = file.raw
  coverList.value = [file]
}

const handleCoverRemove = () => {
  selectedCover.value = null
  coverList.value = []
}

const handleSubmit = async () => {
  try {
    await formRef.value?.validate()
  } catch {
    return
  }

  submitting.value = true
  try {
    if (isEditing.value) {
      const res = await adminApi.updateTemplate(editingId.value, {
        template_name: formData.value.template_name,
        template_type: formData.value.template_type,
        description: formData.value.description,
        style_config: formData.value.style_config,
        sort_order: formData.value.sort_order,
      })
      if (res.success) {
        ElMessage.success('更新成功')
        dialogVisible.value = false
        await fetchTemplates()
      } else {
        ElMessage.error(res.error || '更新失败')
      }
    } else {
      if (!selectedFile.value) {
        ElMessage.warning('请选择模板文件')
        return
      }
      const res = await adminApi.createTemplate({
        category_key: formData.value.category_key,
        template_key: formData.value.template_key,
        template_name: formData.value.template_name,
        template_type: formData.value.template_type,
        description: formData.value.description,
        style_config: formData.value.style_config,
        sort_order: formData.value.sort_order,
        file: selectedFile.value,
        cover: selectedCover.value || undefined,
      })
      if (res.success) {
        ElMessage.success('创建成功')
        dialogVisible.value = false
        await fetchTemplates()
      } else {
        ElMessage.error(res.error || '创建失败')
      }
    }
  } catch (e: any) {
    ElMessage.error(`操作失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    submitting.value = false
  }
}

const openUploadFileDialog = (row: TemplateItem) => {
  replaceTargetId.value = row.id
  replaceFile.value = null
  replaceFileList.value = []
  fileDialogVisible.value = true
}

const handleReplaceFileChange = (file: any) => {
  replaceFile.value = file.raw
  replaceFileList.value = [file]
}

const handleReplaceFileRemove = () => {
  replaceFile.value = null
  replaceFileList.value = []
}

const handleReplaceFile = async () => {
  if (!replaceFile.value) {
    ElMessage.warning('请选择文件')
    return
  }
  submitting.value = true
  try {
    const res = await adminApi.updateTemplateFile(replaceTargetId.value, replaceFile.value)
    if (res.success) {
      ElMessage.success('文件更新成功')
      fileDialogVisible.value = false
      await fetchTemplates()
    } else {
      ElMessage.error(res.error || '更新失败')
    }
  } catch (e: any) {
    ElMessage.error(`更新失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    submitting.value = false
  }
}

const openUploadCoverDialog = (row: TemplateItem) => {
  replaceCoverTargetId.value = row.id
  replaceCover.value = null
  replaceCoverList.value = []
  coverDialogVisible.value = true
}

const handleReplaceCoverChange = (file: any) => {
  replaceCover.value = file.raw
  replaceCoverList.value = [file]
}

const handleReplaceCoverRemove = () => {
  replaceCover.value = null
  replaceCoverList.value = []
}

const handleReplaceCover = async () => {
  if (!replaceCover.value) {
    ElMessage.warning('请选择封面图')
    return
  }
  submitting.value = true
  try {
    const res = await adminApi.uploadTemplateCover(replaceCoverTargetId.value, replaceCover.value)
    if (res.success) {
      ElMessage.success('封面更新成功')
      coverDialogVisible.value = false
      await fetchTemplates()
    } else {
      ElMessage.error(res.error || '更新失败')
    }
  } catch (e: any) {
    ElMessage.error(`更新失败: ${e.response?.data?.detail || e.message}`)
  } finally {
    submitting.value = false
  }
}

onMounted(() => {
  fetchCategories()
  fetchTemplates()
})
</script>

<style scoped>
.glass-panel {
  padding: 20px;
}

.template-page {
  display: flex;
  flex-direction: column;
  gap: 20px;
}

.toolbar-row {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
}

.filter-select {
  width: 160px;
}

.filter-select-sm {
  width: 120px;
}

.search-input {
  width: 280px;
  margin-left: auto;
}

.template-table {
  margin-top: 16px;
}

.template-name-cell {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  justify-content: center;
}

.template-cover {
  width: 40px;
  height: 40px;
  border-radius: 6px;
  flex-shrink: 0;
  border: 1px solid var(--el-border-color-lighter);
}

.template-cover-placeholder {
  width: 40px;
  height: 40px;
  border-radius: 6px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  background: var(--el-fill-color-light);
  font-size: 18px;
}

.template-name-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.template-key-hint {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.cell-text-ellipsis {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 13px;
}

.file-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.file-meta {
  font-size: 11px;
  color: var(--el-text-color-secondary);
}

.meta-text {
  font-size: 13px;
  color: var(--el-text-color-secondary);
}

.table-action-group {
  display: inline-flex;
  gap: 4px;
  align-items: center;
  white-space: nowrap;
  flex-wrap: nowrap;
  justify-content: center;
}

.table-action-group .el-button {
  width: 48px;
  min-width: 48px;
  max-width: 48px;
  height: 28px !important;
  min-height: 28px !important;
  max-height: 28px !important;
  padding: 0 2px !important;
  font-size: 12px !important;
  line-height: 1 !important;
  border-width: 1px !important;
  border-style: solid !important;
  box-sizing: border-box !important;
  display: inline-flex !important;
  align-items: center !important;
  justify-content: center !important;
  vertical-align: middle !important;
  overflow: hidden;
}

.table-action-group .el-button--primary {
  min-height: 28px !important;
}

.table-action-group .el-button span {
  line-height: 1 !important;
  display: inline-block !important;
  vertical-align: middle !important;
}

.template-table .el-table__cell {
  font-size: 13px;
  text-align: center !important;
}

.template-table .el-table__header .el-table__cell {
  text-align: center !important;
}

.pagination-wrap {
  display: flex;
  justify-content: flex-end;
  margin-top: 16px;
}
</style>
