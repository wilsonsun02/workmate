<template>
  <div class="page-grid">
    <section class="section-banner glass-panel compact-banner">
      <div>
        <div class="eyebrow">Mid-Term Memory</div>
        <h2>中期记忆维护（conversation_summaries）</h2>
      </div>
      <div class="banner-stats">
        <div>
          <span>总记录数</span>
          <strong>{{ total }}</strong>
        </div>
      </div>
    </section>

    <section class="glass-panel panel-block">
      <div class="section-heading">
        <div>
          <div class="eyebrow">Filters</div>
          <h3>筛选条件</h3>
        </div>
      </div>

      <div class="table-actions" style="display: flex; gap: 12px; flex-wrap: wrap;">
        <el-input v-model="filters.username" placeholder="按用户名筛选" clearable style="width: 220px;" />
        <el-input v-model="filters.thread_id" placeholder="按 thread_id 筛选" clearable style="width: 260px;" />
        <el-input v-model="filters.keyword" placeholder="按摘要关键词筛选" clearable style="width: 260px;" />
        <el-button type="primary" @click="handleSearch">查询</el-button>
        <el-button @click="handleReset">重置</el-button>
      </div>
    </section>

    <section class="glass-panel panel-block">
      <div class="section-heading">
        <div>
          <div class="eyebrow">Records</div>
          <h3>中期记忆列表</h3>
        </div>
      </div>

      <el-table :data="rows" v-loading="loading">
        <el-table-column prop="id" label="ID" min-width="80" />
        <el-table-column prop="username" label="用户名" min-width="140" />
        <el-table-column prop="thread_id" label="Thread ID" min-width="220" show-overflow-tooltip />
        <el-table-column prop="summary" label="摘要" min-width="360" show-overflow-tooltip />
        <el-table-column prop="created_at" label="创建时间" min-width="180" />
        <el-table-column label="操作" min-width="280" fixed="right">
          <template #default="scope">
            <el-button size="small" type="primary" plain @click="openFullConversationDialog(scope.row)">查看会话</el-button>
            <el-button size="small" @click="openEditDialog(scope.row)">编辑摘要</el-button>
            <el-button size="small" type="danger" @click="handleDelete(scope.row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>

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
    </section>

    <el-dialog v-model="editDialogVisible" title="编辑中期记忆摘要" width="640px">
      <el-form :model="editForm" label-width="90px">
        <el-form-item label="用户名">
          <el-input v-model="editForm.username" disabled />
        </el-form-item>
        <el-form-item label="Thread ID">
          <el-input v-model="editForm.thread_id" disabled />
        </el-form-item>
        <el-form-item label="摘要">
          <el-input
            v-model="editForm.summary"
            type="textarea"
            :rows="8"
            placeholder="请输入摘要内容"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="editDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="editLoading" @click="submitEdit">保存</el-button>
        </span>
      </template>
    </el-dialog>

    <el-dialog v-model="fullConversationDialogVisible" title="完整对话内容" width="760px">
      <el-form :model="fullConversationForm" label-width="90px">
        <el-form-item label="用户名">
          <el-input v-model="fullConversationForm.username" disabled />
        </el-form-item>
        <el-form-item label="Thread ID">
          <el-input v-model="fullConversationForm.thread_id" disabled />
        </el-form-item>
        <el-form-item label="内容">
          <el-input
            v-model="fullConversationForm.full_conversation"
            type="textarea"
            :rows="14"
            readonly
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button type="primary" @click="fullConversationDialogVisible = false">关闭</el-button>
        </span>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminApi, type MidTermMemoryItem } from '@/services/admin'

const loading = ref(false)
const editLoading = ref(false)
const rows = ref<MidTermMemoryItem[]>([])
const total = ref(0)

const filters = ref({
  username: '',
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
  username: '',
  thread_id: '',
  summary: ''
})

const fullConversationDialogVisible = ref(false)
const fullConversationForm = ref({
  username: '',
  thread_id: '',
  full_conversation: ''
})

const fetchRows = async () => {
  loading.value = true
  try {
    const res = await adminApi.getMidTermMemories({
      username: filters.value.username || undefined,
      thread_id: filters.value.thread_id || undefined,
      keyword: filters.value.keyword || undefined,
      limit: pager.value.limit,
      offset: pager.value.offset
    })
    if (res.success) {
      rows.value = res.data
      total.value = res.total
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
  filters.value = { username: '', thread_id: '', keyword: '' }
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
    username: row.username,
    thread_id: row.thread_id,
    summary: row.summary || ''
  }
  editDialogVisible.value = true
}

const openFullConversationDialog = (row: MidTermMemoryItem) => {
  fullConversationForm.value = {
    username: row.username,
    thread_id: row.thread_id,
    full_conversation: row.full_conversation || '暂无 full_conversation 内容'
  }
  fullConversationDialogVisible.value = true
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
  ElMessageBox.confirm(
    `确定要删除该条中期记忆吗？（ID: ${row.id}）`,
    '删除确认',
    {
      confirmButtonText: '确定',
      cancelButtonText: '取消',
      type: 'warning'
    }
  ).then(async () => {
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
  }).catch(() => {
    // canceled
  })
}

onMounted(() => {
  fetchRows()
})
</script>
