<template>
  <el-form :model="form" label-position="top" class="tab-form" v-loading="saving">
    <el-row :gutter="16">
      <el-col :span="12">
        <el-form-item label="姓名">
          <el-input v-model="form.name" placeholder="页面显示名称" />
        </el-form-item>
      </el-col>
      <el-col :span="12">
        <el-form-item label="职位">
          <el-input v-model="form.title" placeholder="例如：法务 / 财务 / 人力 / 员工" />
        </el-form-item>
      </el-col>
    </el-row>

    <el-row :gutter="16">
      <el-col :span="12">
        <el-form-item label="归属部门">
          <el-tree-select
            v-model="form.dept_id"
            :data="departments"
            :props="treeProps"
            check-strictly
            placeholder="请选择归属部门 (可选)"
            style="width: 100%"
            clearable
          />
        </el-form-item>
      </el-col>
    </el-row>

    <div class="form-actions">
      <el-button size="small" type="success" @click="save">保存</el-button>
    </div>
  </el-form>
</template>

<script setup lang="ts">
import { reactive, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { adminApi, type UserItem } from '@/services/admin'

const props = defineProps<{
  user: UserItem
  departments: any[]
}>()

const emit = defineEmits<{
  (e: 'saved', patch?: Partial<UserItem>): void
}>()

const treeProps = {
  children: 'children',
  label: 'label',
  value: 'id'
}

const saving = ref(false)
const form = reactive({
  name: '',
  title: '',
  dept_id: ''
})

const findDepartmentName = (nodes: any[], targetId: string): string => {
  for (const node of nodes || []) {
    if (String(node.id || '') === String(targetId || '')) {
      return node.label || node.name || ''
    }
    const nested = findDepartmentName(node.children || [], targetId)
    if (nested) {
      return nested
    }
  }
  return ''
}

watch(
  () => props.user,
  (next) => {
    form.name = next.name || ''
    form.title = next.title || ''
    form.dept_id = next.dept_id || ''
  },
  { immediate: true }
)

const save = async () => {
  saving.value = true
  try {
    await adminApi.updateUser(props.user.id, {
      name: form.name,
      title: form.title || undefined,
      dept_id: form.dept_id || undefined,
    })
    ElMessage.success('已保存')
    const deptName = findDepartmentName(props.departments, form.dept_id)
    emit('saved', {
      name: form.name,
      title: form.title,
      dept_id: form.dept_id,
      dept_name: deptName,
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
  max-width: 920px;
}

.form-actions {
  display: flex;
  justify-content: flex-end;
}
</style>
