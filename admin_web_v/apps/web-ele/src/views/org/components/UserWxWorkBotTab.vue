<template>
  <el-form :model="form" label-position="top" class="tab-form" v-loading="loading">
    <el-row :gutter="16">
      <el-col :span="12">
        <el-form-item label="机器人名称">
          <el-input v-model="form.wxwork_bot_name" placeholder="可留空" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="机器人 ID">
          <el-input v-model="form.wxwork_bot_id" placeholder="可留空" />
        </el-form-item>
      </el-col>
      <el-col :span="24">
        <el-form-item label="机器人密钥">
          <el-input v-model="form.wxwork_secret" placeholder="可留空" type="password" show-password />
        </el-form-item>
      </el-col>
    </el-row>

    <div class="form-actions">
      <el-button size="small" type="success" @click="reset">重置</el-button>
      <el-button size="small" type="danger" :loading="saving" @click="save">保存</el-button>
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

const loading = ref(false)
const saving = ref(false)
const snapshot = reactive({
  wxwork_bot_name: '',
  wxwork_bot_id: '',
  wxwork_secret: ''
})
const form = reactive({
  wxwork_bot_name: '',
  wxwork_bot_id: '',
  wxwork_secret: ''
})

const load = async () => {
  loading.value = true
  try {
    const res = await adminApi.getUserWxWorkBotConfig(props.user.id)
    if (res.success) {
      snapshot.wxwork_bot_name = res.data.wxwork_bot_name || ''
      snapshot.wxwork_bot_id = res.data.wxwork_bot_id || ''
      snapshot.wxwork_secret = res.data.wxwork_secret || ''
      reset()
    }
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '加载失败')
  } finally {
    loading.value = false
  }
}

const reset = () => {
  form.wxwork_bot_name = snapshot.wxwork_bot_name
  form.wxwork_bot_id = snapshot.wxwork_bot_id
  form.wxwork_secret = snapshot.wxwork_secret
}

const save = async () => {
  saving.value = true
  try {
    await adminApi.updateUser(props.user.id, {
      wxwork_bot_name: form.wxwork_bot_name,
      wxwork_bot_id: form.wxwork_bot_id,
      wxwork_secret: form.wxwork_secret,
    })
    ElMessage.success('已保存')
    emit('saved')
    load()
  } catch (e: any) {
    ElMessage.error(e.response?.data?.detail || '保存失败')
  } finally {
    saving.value = false
  }
}

watch(() => props.user.id, load, { immediate: true })
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
