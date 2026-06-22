<template>
  <el-form :model="form" label-position="top" class="tab-form" v-loading="saving">
    <el-form-item label="是否特殊员工">
      <el-switch v-model="form.is_special" :active-value="1" :inactive-value="0" active-text="是" inactive-text="否" />
    </el-form-item>

    <el-row :gutter="16">
      <el-col :span="12">
        <el-form-item label="特殊员工类型">
          <el-input v-model="form.special_type" placeholder="例如：法务 / 财务 / 人力" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="外部 Agent 地址">
          <el-input v-model="form.external_agent_base_url" placeholder="例如：http://127.0.0.1:9000" />
        </el-form-item>
      </el-col>
    </el-row>

    <el-form-item label="外部 Agent Token">
      <el-input v-model="form.external_agent_token" placeholder="留空则不修改" type="password" show-password />
    </el-form-item>

    <div class="form-actions">
      <el-button type="primary" @click="save">保存</el-button>
    </div>
  </el-form>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi, type UserItem } from '@/services/admin'

const props = defineProps<{
  user: UserItem
}>()

const emit = defineEmits<{
  (e: 'saved', patch?: Partial<UserItem>): void
}>()

const saving = ref(false)
const form = reactive({
  is_special: 0,
  special_type: '',
  external_agent_base_url: '',
  external_agent_token: ''
})

watch(
  () => props.user,
  (next) => {
    form.is_special = next.is_special ?? 0
    form.special_type = next.special_type || ''
    form.external_agent_base_url = next.external_agent_base_url || ''
    form.external_agent_token = ''
  },
  { immediate: true }
)

const save = async () => {
  saving.value = true
  try {
    const payload: any = {
      is_special: form.is_special,
      special_type: form.special_type || undefined,
      external_agent_base_url: form.external_agent_base_url || undefined,
    }
    if (form.external_agent_token.trim()) {
      payload.external_agent_token = form.external_agent_token
    }
    await adminApi.updateUser(props.user.id, payload)
    ElMessage.success('已保存')
    form.external_agent_token = ''
    emit('saved', {
      is_special: form.is_special,
      special_type: form.special_type,
      external_agent_base_url: form.external_agent_base_url,
    })
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
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
}
</style>
