<template>
  <section class="scheduler-shell">
    <div class="scheduler-actions">
      <el-button type="primary" @click="openCreate">新增任务</el-button>
      <el-button @click="fetchTasks">刷新</el-button>
    </div>

    <el-table :data="tasks" v-loading="loading" border stripe row-key="id" empty-text="暂无定时任务">
      <el-table-column prop="id" label="任务ID" min-width="200" show-overflow-tooltip />
      <el-table-column prop="name" label="名称" min-width="160" />
      <el-table-column prop="cron_expression" label="Cron" min-width="160" show-overflow-tooltip />
      <el-table-column prop="status" label="状态" min-width="120" />
      <el-table-column label="操作" min-width="360" fixed="right">
        <template #default="{ row }">
          <el-button size="small" type="primary" plain @click="runNow(row)">立即执行</el-button>
          <el-button size="small" @click="toggle(row)">{{ row.status === 'paused' ? '恢复' : '暂停' }}</el-button>
          <el-button size="small" type="danger" plain @click="remove(row)">删除</el-button>
          <el-button size="small" @click="showExecutions(row)">执行记录</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-dialog v-model="createDialogVisible" title="创建定时任务" width="720px">
      <el-form :model="createForm" label-position="top">
        <el-form-item label="任务名称">
          <el-input v-model="createForm.task_name" placeholder="可选" />
        </el-form-item>
        <el-form-item label="任务描述">
          <el-input v-model="createForm.task_description" type="textarea" :rows="6" placeholder="例如：每天 9 点生成日报并发送到文件传输助手" />
        </el-form-item>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="Cron 表达式">
              <el-input v-model="createForm.cron_expression" placeholder="可选，留空走自动解析" />
            </el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="任务类型">
              <el-input v-model="createForm.task_type" placeholder="custom" />
            </el-form-item>
          </el-col>
        </el-row>
      </el-form>
      <template #footer>
        <span class="dialog-footer">
          <el-button @click="createDialogVisible = false">取消</el-button>
          <el-button type="primary" :loading="creating" @click="create">创建</el-button>
        </span>
      </template>
    </el-dialog>

    <el-dialog v-model="executionsDialogVisible" title="执行记录" width="860px">
      <el-table :data="executions" v-loading="executionsLoading" border stripe row-key="id" empty-text="暂无执行记录">
        <el-table-column prop="id" label="执行ID" min-width="220" show-overflow-tooltip />
        <el-table-column prop="status" label="状态" min-width="120" />
        <el-table-column prop="started_at" label="开始时间" min-width="180" />
        <el-table-column prop="finished_at" label="结束时间" min-width="180" />
      </el-table>
      <template #footer>
        <span class="dialog-footer">
          <el-button type="primary" @click="executionsDialogVisible = false">关闭</el-button>
        </span>
      </template>
    </el-dialog>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminApi, type SchedulerExecutionItem, type SchedulerTaskItem, type UserItem } from '@/services/admin'

const props = defineProps<{
  user: UserItem
}>()

const loading = ref(false)
const tasks = ref<SchedulerTaskItem[]>([])

const createDialogVisible = ref(false)
const creating = ref(false)
const createForm = reactive({
  task_name: '',
  task_description: '',
  cron_expression: '',
  task_type: 'custom'
})

const executionsDialogVisible = ref(false)
const executionsLoading = ref(false)
const executions = ref<SchedulerExecutionItem[]>([])
const activeTaskId = ref('')

const fetchTasks = async () => {
  const username = props.user.username
  if (!username) return
  loading.value = true
  try {
    const res = await adminApi.listSchedulerTasks({ username })
    if (res.success) {
      tasks.value = (res.data as any[]) || []
    }
  } catch (_e) {
    ElMessage.error('获取定时任务失败')
  } finally {
    loading.value = false
  }
}

const openCreate = () => {
  createForm.task_name = ''
  createForm.task_description = ''
  createForm.cron_expression = ''
  createForm.task_type = 'custom'
  createDialogVisible.value = true
}

const create = async () => {
  const username = props.user.username
  const taskDescription = createForm.task_description.trim()
  if (!taskDescription) {
    ElMessage.warning('任务描述不能为空')
    return
  }
  creating.value = true
  try {
    const res = await adminApi.createSchedulerTask({
      username,
      task_description: taskDescription,
      cron_expression: createForm.cron_expression.trim() || undefined,
      task_type: createForm.task_type.trim() || 'custom',
      task_name: createForm.task_name.trim() || undefined
    })
    if (res.success) {
      ElMessage.success('已创建')
      createDialogVisible.value = false
      fetchTasks()
    } else {
      ElMessage.error((res as any).error || '创建失败')
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '创建失败')
  } finally {
    creating.value = false
  }
}

const remove = (row: SchedulerTaskItem) => {
  ElMessageBox.confirm(`确定要删除任务 "${row.name || row.id}" 吗？`, '删除确认', {
    confirmButtonText: '确定',
    cancelButtonText: '取消',
    type: 'warning',
  }).then(async () => {
    try {
      await adminApi.deleteSchedulerTask(row.id, { username: props.user.username })
      ElMessage.success('已删除')
      fetchTasks()
    } catch (e: any) {
      ElMessage.error(e.response?.data?.detail || '删除失败')
    }
  })
}

const toggle = async (row: SchedulerTaskItem) => {
  try {
    if (row.status === 'paused') {
      await adminApi.resumeSchedulerTask(row.id, { username: props.user.username })
      ElMessage.success('已恢复')
    } else {
      await adminApi.pauseSchedulerTask(row.id, { username: props.user.username })
      ElMessage.success('已暂停')
    }
    fetchTasks()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '操作失败')
  }
}

const runNow = async (row: SchedulerTaskItem) => {
  try {
    const res = await adminApi.runSchedulerTaskNow(row.id, { username: props.user.username })
    if (res.success) {
      ElMessage.success(`已触发执行：${res.execution_id || ''}`)
    } else {
      ElMessage.error((res as any).error || '执行失败')
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '执行失败')
  }
}

const showExecutions = async (row: SchedulerTaskItem) => {
  activeTaskId.value = row.id
  executionsDialogVisible.value = true
  executionsLoading.value = true
  try {
    const res = await adminApi.listSchedulerExecutions({
      task_id: row.id,
      username: props.user.username,
      limit: 20
    })
    if (res.success) {
      executions.value = (res.data as any[]) || []
    }
  } catch (_e) {
    ElMessage.error('获取执行记录失败')
  } finally {
    executionsLoading.value = false
  }
}

watch(() => props.user.username, fetchTasks)
onMounted(fetchTasks)
</script>

<style scoped>
.scheduler-actions {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  margin-bottom: 12px;
}
</style>

