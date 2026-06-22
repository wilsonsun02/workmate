<template>
  <section class="memory-shell">
    <div class="table-actions">
      <el-input v-model="filters.thread_id" placeholder="按 thread_id 筛选" clearable style="width: 260px;" />
      <el-input v-model="filters.keyword" placeholder="按摘要关键词筛选" clearable style="width: 260px;" />
      <el-button size="small" type="success" @click="handleSearch">查询</el-button>
      <el-button size="small" type="danger" @click="handleReset">重置</el-button>
    </div>

    <div class="memory-table">
      <el-table
        :data="rows"
        v-loading="loading"
        border
        stripe
        row-key="id"
        empty-text="暂无中期记忆记录"
        max-height="60vh"
        width="100%"
      >
        <el-table-column prop="id" label="ID" min-width="80" />
        <el-table-column prop="thread_id" label="Thread ID" min-width="140" show-overflow-tooltip />
        <el-table-column prop="summary" label="摘要" min-width="220" show-overflow-tooltip />
        <el-table-column prop="created_at" label="创建时间" min-width="120" />
        <el-table-column label="操作" min-width="120" fixed="right">
          <template #default="scope">
            <el-button size="small" @click="openEditDialog(scope.row)">编辑摘要</el-button>
            <el-button size="small" type="danger" plain @click="handleDelete(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </div>

    <div style="display: flex; justify-content: flex-end; margin-top: 16px;">
      <el-pagination
        background
        layout="total, sizes, prev, pager, next"
        :total="total"
        :page-size="pager.limit"
        :page-sizes="[10, 20, 50, 100]"
        :current-page="currentPage"
        @current-change="handlePageChange"
        @size-change="handleSizeChange"
      />
    </div>

    <el-dialog v-model="editDialogVisible" title="编辑中期记忆摘要" width="640px">
      <el-form :model="editForm" label-position="top">
        <el-form-item label="Thread ID">
          <el-input v-model="editForm.thread_id" disabled />
        </el-form-item>
        <el-form-item label="摘要">
          <el-input v-model="editForm.summary" type="textarea" :rows="8" />
        </el-form-item>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button size="small" @click="editDialogVisible = false">取消</el-button>
          <el-button size="small" type="primary" :loading="editLoading" @click="submitEdit">保存</el-button>
        </span>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminApi, type MidTermMemoryItem, type UserItem } from '@/services/admin'

const props = defineProps<{
  user: UserItem
}>()

const loading = ref(false)
const editLoading = ref(false)
const rows = ref<MidTermMemoryItem[]>([])
const total = ref(0)

const filters = ref({
  thread_id: '',
  keyword: ''
})

const pager = ref({
  limit: 20,
  offset: 0
})

const currentPage = computed(() => Math.floor(pager.value.offset / pager.value.limit) + 1)

const editDialogVisible = ref(false)
const editForm = ref({
  id: 0,
  thread_id: '',
  summary: ''
})

const fetchRows = async () => {
  const username = props.user.username
  if (!username) return
  loading.value = true
  try {
    const res = await adminApi.getMidTermMemories({
      username,
      thread_id: filters.value.thread_id || undefined,
      keyword: filters.value.keyword || undefined,
      limit: pager.value.limit,
      offset: pager.value.offset
    })
    if (res.success) {
      rows.value = res.data || []
      total.value = res.total || 0
    }
  } catch (_e) {
    ElMessage.error('获取中期记忆失败')
  } finally {
    loading.value = false
  }
}

const handleSearch = () => {
  pager.value.offset = 0
  fetchRows()
}

const handleReset = () => {
  filters.value = { thread_id: '', keyword: '' }
  pager.value.offset = 0
  fetchRows()
}

const handlePageChange = (page: number) => {
  pager.value.offset = (page - 1) * pager.value.limit
  fetchRows()
}

const handleSizeChange = (size: number) => {
  pager.value.limit = size
  pager.value.offset = 0
  fetchRows()
}

const openEditDialog = (row: MidTermMemoryItem) => {
  editForm.value = {
    id: row.id,
    thread_id: row.thread_id,
    summary: row.summary || ''
  }
  editDialogVisible.value = true
}

const submitEdit = async () => {
  const summary = editForm.value.summary.trim()
  if (!summary) {
    ElMessage.warning('摘要不能为空')
    return
  }
  editLoading.value = true
  try {
    await adminApi.updateMidTermMemory(editForm.value.id, { summary })
    ElMessage.success('更新成功')
    editDialogVisible.value = false
    fetchRows()
  } catch (_e) {
    ElMessage.error('更新失败')
  } finally {
    editLoading.value = false
  }
}

const handleDelete = (row: MidTermMemoryItem) => {
  ElMessageBox.confirm(`确定要删除该条中期记忆吗？（ID: ${row.id}）`, '删除确认', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'warning'
  }).then(async () => {
    try {
      await adminApi.deleteMidTermMemory(row.id)
      ElMessage.success('删除成功')
      if (rows.value.length === 1 && pager.value.offset > 0) {
        pager.value.offset = Math.max(0, pager.value.offset - pager.value.limit)
      }
      fetchRows()
    } catch (_e) {
      ElMessage.error('删除失败')
    }
  })
}

watch(() => props.user.username, () => {
  pager.value.offset = 0
  fetchRows()
})

onMounted(fetchRows)
</script>

<style scoped>
.table-actions {
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  justify-content: flex-end;
  margin-bottom: 12px;
}

.memory-shell {
  min-width: 0;
}

.memory-table {
  min-width: 0;
  width: 100%;
}

.memory-table :deep(.el-table) {
  width: 100%;
}
</style>
