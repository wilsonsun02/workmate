<template>
  <el-form :model="form" label-position="top" class="tab-form" v-loading="saving">
    <el-row :gutter="16">
      <el-col :span="12">
        <el-form-item label="账号名">
          <el-input v-model="form.username" placeholder="登录账号" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="状态">
          <el-switch
            v-model="form.status"
            :active-value="1"
            :inactive-value="0"
            active-text="正常"
            inactive-text="禁用"
            :loading="statusSaving"
            :disabled="statusSaving"
            @change="handleStatusChange"
          />
        </el-form-item>
      </el-col>
    </el-row>

    <el-form-item label="重置密码">
      <el-input v-model="form.password" placeholder="留空则不修改" type="password" show-password />
    </el-form-item>

    <div class="form-actions">
      <el-button size="small" type="success" @click="save">保存</el-button>
      <el-button size="small" type="danger" plain :loading="deleting" @click="removeUser">删除员工</el-button>
    </div>
  </el-form>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { adminApi, type UserItem } from '@/services/admin'

const props = defineProps<{
  user: UserItem
}>()

const emit = defineEmits<{
  (e: 'saved', patch?: Partial<UserItem>): void
  (e: 'deleted', userId: string): void
}>()

const saving = ref(false)
const statusSaving = ref(false)
const deleting = ref(false)
const form = reactive({
  username: '',
  status: 1,
  password: ''
})

watch(
  () => props.user,
  (next) => {
    form.username = next.username || ''
    form.status = next.status ?? 1
    form.password = ''
  },
  { immediate: true }
)

const handleStatusChange = async (value: string | number | boolean) => {
  const nextStatus = Number(value)
  const previousStatus = props.user.status ?? 1

  if (nextStatus === previousStatus) {
    return
  }

  statusSaving.value = true
  try {
    await adminApi.updateUser(props.user.id, { status: nextStatus })
    ElMessage.success(nextStatus === 1 ? '已启用' : '已禁用')
    emit('saved', { status: nextStatus })
  } catch (e: any) {
    form.status = previousStatus
    ElMessage.error(e.response?.data?.detail || '状态更新失败')
  } finally {
    statusSaving.value = false
  }
}

const save = async () => {
  saving.value = true
  try {
    const payload: any = {
      username: form.username,
      status: form.status
    }
    if (form.password.trim()) {
      payload.password = form.password
    }
    await adminApi.updateUser(props.user.id, payload)
    ElMessage.success('已保存')
    form.password = ''
    emit('saved', { username: form.username, status: form.status })
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

const removeUser = async () => {
  try {
    await ElMessageBox.confirm(
      `删除后该员工会从列表中隐藏，账号将不可登录。确定删除“${props.user.name || props.user.username}”吗？`,
      '删除员工',
      {
        type: 'warning',
        confirmButtonText: '确认删除',
        cancelButtonText: '取消',
        confirmButtonClass: 'el-button--danger el-button--small',
        cancelButtonClass: 'el-button--small',
      }
    )
  } catch {
    return
  }

  deleting.value = true
  try {
    await adminApi.deleteUser(props.user.id)
    ElMessage.success('员工已删除')
    emit('deleted', props.user.id)
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '删除失败')
  } finally {
    deleting.value = false
  }
}
</script>

<style scoped>
.tab-form {
  max-width: 760px;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
  gap: 12px;
}
</style>
